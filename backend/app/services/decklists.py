"""
Liste dei giocatori: lettura del testo, regole di mazzo e carte da Scryfall.

Le regole sono per gioco. Per ora c'è solo Magic (ENABLED_GAMES): per gli altri
giochi la lista si legge e si conta, ma non si controlla. Le loro regole e la loro
ricerca carte vanno in RULES, LEGALITY e CARD_SOURCES in fondo al file.
"""
import re
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.app.models import DecklistStatus

SCRYFALL = "https://api.scryfall.com"
SCRYFALL_BATCH = 75                      # limite di /cards/collection
# Scryfall chiede di presentarsi: senza User-Agent e Accept risponde 400.
SCRYFALL_HEADERS = {"User-Agent": "Mull2Five/1.0", "Accept": "application/json"}


@dataclass(frozen=True)
class DeckEntry:
    section: str          # "main" o "side"
    quantity: int
    name: str


@dataclass(frozen=True)
class DeckValidation:
    main_count: int
    side_count: int
    status: str
    errors: list[str]


# "4 Lightning Bolt", "4x Lightning Bolt", "SB: 2 Pyroblast" (MTGO).
_CARD_LINE = re.compile(r"^(?:(sb)\s*:\s*)?(\d+)\s*x?\s+(.+)$", re.IGNORECASE)
# "(2XM) 141" dell'export di Arena e "*F*" delle foil di MTGO: Scryfall cerca per nome.
_SET_SUFFIX = re.compile(r"\s+\([A-Za-z0-9]{2,6}\)(?:\s+\S+)?$")
_FOIL = re.compile(r"\s*\*[A-Za-z]+\*$")
_SIDE_HEADER = re.compile(r"^(?://\s*)?(sideboard|side|sb|companion|compagno)\b", re.IGNORECASE)
# Le intestazioni che riportano al main, anche dopo la riga vuota: "Deck" di Arena,
# "Commander", e i gruppi per tipo delle esportazioni testuali ("Creatures (12)").
_MAIN_HEADER = re.compile(
    r"^(?://\s*)?(deck|main|maindeck|mazzo|commander|comandante|creatures?|creature|lands?|terre|"
    r"instants?|istantanei|sorcery|sorceries|stregonerie|artifacts?|artefatti|enchantments?|incantesimi|"
    r"planeswalkers?|battles?|battaglie|other|altro)\b",
    re.IGNORECASE,
)


def clean_card_name(raw: str) -> str:
    name = _SET_SUFFIX.sub("", _FOIL.sub("", raw.strip()))
    if "//" in name:
        name = " // ".join(part.strip() for part in name.split("//"))
    return re.sub(r"\s+", " ", name).strip()


def parse_decklist(raw_text: str) -> list[DeckEntry]:
    entries: list[DeckEntry] = []
    section = "main"
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            # Una riga vuota dopo il main: il resto è sideboard (formato MTGO/Arena).
            if section == "main" and any(entry.section == "main" for entry in entries):
                section = "side"
            continue
        card = _CARD_LINE.match(line)
        if card:
            sideboard_prefix, quantity, name = card.groups()
            name = clean_card_name(name)
            if name and int(quantity) > 0:
                entries.append(DeckEntry("side" if sideboard_prefix else section, int(quantity), name))
            continue
        if _SIDE_HEADER.match(line):
            section = "side"
        elif _MAIN_HEADER.match(line):
            section = "main"
    return entries


def parse_card_names(raw_text: str) -> list[str]:
    return [entry.name for entry in parse_decklist(raw_text)]


def validate_decklist(raw_text: str, tournament_format: str, game: str = "mtg") -> DeckValidation:
    entries = parse_decklist(raw_text)
    main_count = sum(entry.quantity for entry in entries if entry.section == "main")
    side_count = sum(entry.quantity for entry in entries if entry.section == "side")
    if not entries:
        errors = ["Nessuna carta riconosciuta. Usa righe come '4 Lightning Bolt'."]
    else:
        rules = RULES.get(game)
        errors = rules(entries, main_count, side_count, tournament_format) if rules else []
    return DeckValidation(
        main_count=main_count,
        side_count=side_count,
        status=DecklistStatus.INVALID if errors else DecklistStatus.VALID,
        errors=errors,
    )


def validate_card_legality(raw_text: str, tournament_format: str, game: str = "mtg") -> list[str]:
    """Le carte che non si possono giocare nel formato, secondo l'editore.
    Serve la rete: si chiama solo se il torneo ha il controllo attivo."""
    check = LEGALITY.get(game)
    return check(parse_decklist(raw_text), tournament_format) if check else []


# ── Magic: The Gathering ─────────────────────────────────────────────────

MTG_BASIC_LANDS = frozenset(
    name.lower()
    for base in ("Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes")
    for name in (base, f"Snow-Covered {base}")
)
# "Un mazzo può contenere un numero qualsiasi di carte chiamate…"
MTG_ANY_NUMBER = frozenset(name.lower() for name in (
    "Relentless Rats", "Shadowborn Apostle", "Rat Colony", "Persistent Petitioners",
    "Dragon's Approach", "Slime Against Humanity", "Hare Apparent", "Templar Knight",
    "Cid, Timeless Artificer", "Tempest Hawk",
))
# "…fino a sette/nove carte chiamate…"
MTG_MAX_COPIES = {"seven dwarves": 7, "nazgûl": 9, "nazgul": 9}

# Le chiavi delle legalità di Scryfall.
MTG_LEGALITY_KEYS = frozenset({
    "standard", "future", "historic", "timeless", "gladiator", "pioneer", "explorer", "modern",
    "legacy", "pauper", "vintage", "penny", "commander", "oathbreaker", "standardbrawl", "brawl",
    "alchemy", "paupercommander", "duel", "oldschool", "premodern", "predh",
})
_MTG_FORMAT_ALIASES = {
    "edh": "commander", "duelcommander": "duel", "pennydreadful": "penny", "historicbrawl": "brawl",
}


def mtg_format_kind(tournament_format: str) -> str:
    """"limited", "commander" o "constructed": decide quante carte e quante copie."""
    normalized = tournament_format.lower().strip()
    if "commander" in normalized or normalized in {"edh", "cedh"}:
        return "commander"
    if any(word in normalized for word in ("draft", "sealed", "prerelease", "pre-release", "cube", "limited")):
        return "limited"
    return "constructed"


def mtg_legality_key(tournament_format: str) -> str | None:
    key = re.sub(r"[^a-z]", "", tournament_format.lower())
    key = _MTG_FORMAT_ALIASES.get(key, key)
    return key if key in MTG_LEGALITY_KEYS else None


def _mtg_copy_limit(lowered_name: str, singleton: bool) -> int | None:
    if lowered_name in MTG_BASIC_LANDS or lowered_name in MTG_ANY_NUMBER:
        return None
    return MTG_MAX_COPIES.get(lowered_name, 1 if singleton else 4)


def _totals(entries: list[DeckEntry]) -> tuple[Counter[str], dict[str, str]]:
    """Copie per nome (minuscolo, main e sideboard insieme) e il nome come è scritto."""
    totals: Counter[str] = Counter()
    spelled: dict[str, str] = {}
    for entry in entries:
        totals[entry.name.lower()] += entry.quantity
        spelled.setdefault(entry.name.lower(), entry.name)
    return totals, spelled


def _mtg_rules(entries: list[DeckEntry], main_count: int, side_count: int, tournament_format: str) -> list[str]:
    kind = mtg_format_kind(tournament_format)
    errors: list[str] = []
    if kind == "limited":
        # Il pool è del giocatore: niente limite di copie né di sideboard.
        if main_count < 40:
            errors.append("Nel limited il mazzo deve contenere almeno 40 carte.")
        return errors
    if kind == "commander":
        if main_count + side_count != 100:
            errors.append("Commander richiede esattamente 100 carte totali, comandante compreso.")
    else:
        if main_count < 60:
            errors.append("Il main deck deve contenere almeno 60 carte.")
        if side_count > 15:
            errors.append("Il sideboard non può superare 15 carte.")
    totals, spelled = _totals(entries)
    for lowered, total in totals.items():
        limit = _mtg_copy_limit(lowered, singleton=kind == "commander")
        if limit is not None and total > limit:
            where = "fra main e sideboard" if kind == "constructed" else "nel mazzo"
            errors.append(f"{spelled[lowered]}: {total} copie {where}, al massimo {limit}.")
    return errors


def _mtg_legality(entries: list[DeckEntry], tournament_format: str) -> list[str]:
    key = mtg_legality_key(tournament_format)
    if key is None:            # limited o formato che Scryfall non conosce: niente da controllare
        return []
    totals, spelled = _totals(entries)
    if not totals:
        return []
    try:
        cards = scryfall_cards(list(spelled.values()))
    except httpx.HTTPError:
        return ["Validazione Scryfall non disponibile: riprova più tardi."]
    errors: list[str] = []
    for lowered, name in spelled.items():
        card = cards.get(lowered)
        if card is None:
            errors.append(f"Carta non trovata: {name}")
            continue
        status = card.get("legalities", {}).get(key)
        if status == "banned":
            errors.append(f"{name} è bandita in {tournament_format}.")
        elif status == "restricted" and totals[lowered] > 1:
            errors.append(f"{name} è ristretta in {tournament_format}: al massimo 1 copia.")
        elif status == "not_legal":
            errors.append(f"{name} non è legale in {tournament_format}.")
    return errors


class _TtlCache:
    """Piccola cache in memoria, per processo: le carte cambiano di rado (le legalità
    al massimo una volta al mese) e Scryfall chiede di non ripetere le stesse domande."""

    def __init__(self, ttl: float, size: int) -> None:
        self.ttl, self.size = ttl, size
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, object]:
        with self._lock:
            hit = self._data.get(key)
            if not hit or hit[0] < time.monotonic():
                return False, None
            self._data.move_to_end(key)
            return True, hit[1]

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cards_cache = _TtlCache(ttl=12 * 3600, size=20_000)
_search_cache = _TtlCache(ttl=12 * 3600, size=5_000)


def _names_of(card: dict) -> set[str]:
    """Tutti i nomi con cui si può scrivere la carta: intero, facce, metà delle split."""
    full = card.get("name", "")
    names = {full.lower(), *(part.lower() for part in full.split(" // "))}
    names.update(face.get("name", "").lower() for face in card.get("card_faces") or [])
    return names - {""}


def scryfall_cards(names: list[str]) -> dict[str, dict | None]:
    """Le carte per nome (minuscolo): None se Scryfall non la conosce.
    Solleva httpx.HTTPError se Scryfall non risponde."""
    result: dict[str, dict | None] = {}
    missing: list[str] = []
    for name in dict.fromkeys(names):
        hit, card = _cards_cache.get(name.lower())
        if hit:
            result[name.lower()] = card
        else:
            missing.append(name)
    for start in range(0, len(missing), SCRYFALL_BATCH):
        batch = missing[start:start + SCRYFALL_BATCH]
        response = httpx.post(
            f"{SCRYFALL}/cards/collection",
            json={"identifiers": [{"name": name} for name in batch]},
            headers=SCRYFALL_HEADERS, timeout=8,
        )
        response.raise_for_status()
        index: dict[str, dict] = {}
        for card in response.json().get("data", []):
            for alias in _names_of(card):
                index.setdefault(alias, card)
        for name in batch:
            card = index.get(name.lower())
            _cards_cache.set(name.lower(), card)
            result[name.lower()] = card
    return result


def _mtg_search(query: str) -> list[str]:
    hit, names = _search_cache.get(query.lower())
    if hit:
        return names
    response = httpx.get(f"{SCRYFALL}/cards/autocomplete", params={"q": query},
                         headers=SCRYFALL_HEADERS, timeout=6)
    response.raise_for_status()
    names = response.json().get("data", [])[:20]
    _search_cache.set(query.lower(), names)
    return names


# In che ordine si raggruppano le carte, come nelle liste stampate.
MTG_CATEGORIES = ("creature", "planeswalker", "battle", "instant", "sorcery", "artifact", "enchantment", "land")


def _mtg_card_info(name: str, card: dict | None) -> dict:
    if card is None:
        return {"query": name, "found": False, "name": name, "mana_cost": "", "type_line": "",
                "category": "other", "image": ""}
    faces = card.get("card_faces") or []
    front = faces[0] if faces else card
    type_line = card.get("type_line") or front.get("type_line", "")
    front_type = type_line.split(" // ")[0].lower()
    category = next((word for word in MTG_CATEGORIES if word in front_type), "other")
    images = card.get("image_uris") or front.get("image_uris") or {}
    return {
        "query": name, "found": True, "name": card.get("name", name),
        "mana_cost": card.get("mana_cost") or front.get("mana_cost", ""),
        "type_line": type_line, "category": category,
        "image": images.get("normal") or images.get("small") or "",
    }


def _mtg_lookup(names: list[str]) -> list[dict]:
    cards = scryfall_cards(names)
    return [_mtg_card_info(name, cards.get(name.lower())) for name in names]


@dataclass(frozen=True)
class CardSource:
    search: Callable[[str], list[str]]
    lookup: Callable[[list[str]], list[dict]]


RULES: dict[str, Callable[[list[DeckEntry], int, int, str], list[str]]] = {"mtg": _mtg_rules}
LEGALITY: dict[str, Callable[[list[DeckEntry], str], list[str]]] = {"mtg": _mtg_legality}
CARD_SOURCES: dict[str, CardSource] = {"mtg": CardSource(search=_mtg_search, lookup=_mtg_lookup)}
