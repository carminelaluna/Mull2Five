"""
Giochi supportati: formati, formato dei match e sistema di spareggi.

Un solo elenco, servito anche al frontend da GET /api/games: la lista dei
formati o le colonne della classifica non vanno ricopiate in JavaScript, dove
finirebbero per non corrispondere più.

Gli spareggi seguono i regolamenti ufficiali (le fonti in TODO.md, "Parità con
Melee"): Magic, Lorcana e Star Wars Unlimited usano lo schema del Magic Tournament
Rules; One Piece e Pokémon hanno il loro.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Game:
    code: str
    name: str
    formats: tuple[str, ...]
    # Formato dei match in svizzera secondo il regolamento: al meglio di 1, 2 o 3.
    default_best_of: int
    # "mtr" (Magic e affini), "onepiece" o "pokemon": vedi services/standings.py.
    tiebreakers: str
    # Formati limited: la lista si costruisce al tavolo, con regole di mazzo diverse.
    limited_formats: tuple[str, ...] = field(default_factory=tuple)
    # Come si chiama l'identificativo del giocatore presso l'editore.
    publisher_id_label: str = ""


GAMES: dict[str, Game] = {
    game.code: game
    for game in (
        Game(
            code="mtg",
            name="Magic: The Gathering",
            formats=("Standard", "Pioneer", "Modern", "Legacy", "Vintage", "Pauper",
                     "Premodern", "Commander", "Sealed", "Draft"),
            limited_formats=("Sealed", "Draft"),
            default_best_of=3,
            tiebreakers="mtr",
            publisher_id_label="Wizards Account",
        ),
        Game(
            code="lorcana",
            name="Disney Lorcana",
            formats=("Core Constructed", "Infinity Constructed", "Sealed", "Draft"),
            limited_formats=("Sealed", "Draft"),
            default_best_of=3,
            tiebreakers="mtr",
            publisher_id_label="Ravensburger Play Hub",
        ),
        Game(
            code="swu",
            name="Star Wars: Unlimited",
            formats=("Premier", "Twin Suns", "Sealed", "Draft"),
            limited_formats=("Sealed", "Draft"),
            default_best_of=3,
            tiebreakers="mtr",
            publisher_id_label="SWU ID",
        ),
        Game(
            code="onepiece",
            name="One Piece Card Game",
            formats=("Standard", "Sealed"),
            limited_formats=("Sealed",),
            # Svizzera al meglio di 1, top cut al meglio di 3 (Tournament Rules Manual 3.5).
            default_best_of=1,
            tiebreakers="onepiece",
            publisher_id_label="Bandai Card Games+",
        ),
        Game(
            code="pokemon",
            name="Pokémon TCG",
            formats=("Standard", "Expanded", "Gym Leader Challenge", "Prerelease"),
            limited_formats=("Prerelease",),
            default_best_of=3,
            tiebreakers="pokemon",
            publisher_id_label="Play! Pokémon ID",
        ),
    )
}

DEFAULT_GAME = "mtg"


def get_game(code: str | None) -> Game:
    """Il gioco del torneo; un codice sconosciuto (dati vecchi) vale come Magic."""
    return GAMES.get(code or DEFAULT_GAME, GAMES[DEFAULT_GAME])


# Punteggi ammessi, come (vittorie di A, vittorie di B). 0-0 è la patta, anche
# intenzionale; 1-1 in un al meglio di 2 o 3 è la patta a tempo scaduto.
ALLOWED_SCORES: dict[int, frozenset[tuple[int, int]]] = {
    1: frozenset({(1, 0), (0, 1), (0, 0)}),
    2: frozenset({(2, 0), (1, 0), (1, 1), (0, 1), (0, 2), (0, 0)}),
    3: frozenset({(2, 0), (2, 1), (1, 0), (1, 1), (0, 1), (1, 2), (0, 2), (0, 0)}),
}


def enabled_games() -> list[Game]:
    """I giochi che si possono scegliere per un torneo nuovo (ENABLED_GAMES).
    Quelli spenti restano nel codice e nei tornei che li usano già."""
    from backend.app.core.config import get_settings

    wanted = get_settings().enabled_games.strip().lower()
    if wanted == "all":
        return list(GAMES.values())
    codes = {code.strip() for code in wanted.split(",") if code.strip()}
    return [game for game in GAMES.values() if game.code in codes] or [GAMES[DEFAULT_GAME]]


def is_enabled(code: str) -> bool:
    return any(game.code == code for game in enabled_games())


def games_catalog() -> list[dict]:
    """Quello che il frontend deve sapere dei giochi che si possono scegliere."""
    return [
        {
            "code": game.code,
            "name": game.name,
            "formats": list(game.formats),
            "limited_formats": list(game.limited_formats),
            "default_best_of": game.default_best_of,
            "tiebreakers": game.tiebreakers,
            "publisher_id_label": game.publisher_id_label,
        }
        for game in enabled_games()
    ]
