from dataclasses import dataclass

import httpx

from backend.app.models import DecklistStatus


@dataclass(frozen=True)
class DeckValidation:
    main_count: int
    side_count: int
    status: str
    errors: list[str]


def validate_decklist(raw_text: str, tournament_format: str) -> DeckValidation:
    main_count = 0
    side_count = 0
    section = "main"
    parsed_lines = 0

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith(("sideboard", "side", "sb")):
            section = "side"
            continue
        parts = line.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        parsed_lines += 1
        quantity = int(parts[0])
        if section == "side":
            side_count += quantity
        else:
            main_count += quantity

    errors: list[str] = []
    normalized = tournament_format.lower()
    if parsed_lines == 0:
        errors.append("Nessuna carta riconosciuta. Usa righe come '4 Lightning Bolt'.")
    if normalized == "commander":
        if main_count + side_count != 100:
            errors.append("Commander richiede esattamente 100 carte totali.")
    elif normalized not in {"draft", "sealed"}:
        if main_count < 60:
            errors.append("Il main deck deve contenere almeno 60 carte.")
        if side_count > 15:
            errors.append("Il sideboard non puo superare 15 carte.")

    return DeckValidation(
        main_count=main_count,
        side_count=side_count,
        status=DecklistStatus.INVALID if errors else DecklistStatus.VALID,
        errors=errors,
    )


def validate_card_legality(raw_text: str, tournament_format: str) -> list[str]:
    legality_key = tournament_format.lower()
    if legality_key in {"sealed", "draft"}:
        return []
    names = sorted({name for name in parse_card_names(raw_text)})
    if not names:
        return []
    errors: list[str] = []
    try:
        response = httpx.post(
            "https://api.scryfall.com/cards/collection",
            json={"identifiers": [{"name": name} for name in names[:75]]},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError:
        return ["Validazione Scryfall non disponibile: riprova piu tardi."]

    found = {card["name"].lower(): card for card in payload.get("data", [])}
    for missing in payload.get("not_found", []):
        errors.append(f"Carta non trovata: {missing.get('name', 'N/D')}")
    for name in names:
        card = found.get(name.lower())
        if not card:
            continue
        legalities = card.get("legalities", {})
        if legalities.get(legality_key) not in {"legal", "not_legal"}:
            continue
        if legalities.get(legality_key) != "legal":
            errors.append(f"{name} non e legale in {tournament_format}.")
    return errors


def parse_card_names(raw_text: str) -> list[str]:
    names = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(("sideboard", "side", "sb")):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        names.append(parts[1].replace("//", " // ").strip())
    return names
