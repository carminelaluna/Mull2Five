"""
Router archivio — le liste dei tornei conclusi, cercabili da tutti.

In archivio entra solo quello che il torneo ha già reso pubblico: a torneo
concluso, con classifica e liste visibili (standings_public e decklists_public).
Si cerca per formato, archetipo, carta, negozio e periodo; /meta riassume il
metagame delle stesse liste: archetipi e carte più giocate.
"""
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.core.clock import local_today
from backend.app.core.ttl_cache import TtlCache
from backend.app.db import get_db
from backend.app.models import Decklist, Organization, Registration, Tournament, TournamentStatus
from backend.app.schemas import ArchiveDeckDetailOut, ArchiveDeckOut, ArchiveMetaOut, ArchivePageOut
from backend.app.services.decklists import MTG_BASIC_LANDS, parse_decklist
from backend.app.services.pairings import calculate_standings

router = APIRouter(prefix="/decklists", tags=["archive"])

# Le liste più recenti su cui si filtra: un anno abbondante di tornei di negozio.
MAX_CANDIDATES = 2000
# Le classifiche dei tornei conclusi cambiano solo se lo staff corregge un risultato.
_standings_cache = TtlCache(ttl=600, size=2000)


def _placements(tournament_id: int, db: Session) -> dict[int, tuple[int, str, int, str]]:
    """registration_id → (posizione, record, punti, nome in classifica)."""
    hit, value = _standings_cache.get(tournament_id)
    if hit:
        return value
    value = {
        row.registration_id: (row.position, row.record, row.points, row.name)
        for row in calculate_standings(tournament_id, db)
    }
    _standings_cache.set(tournament_id, value)
    return value


def _public_lists() -> Select:
    return (
        select(Decklist, Registration, Tournament, Organization)
        .join(Registration, Registration.id == Decklist.registration_id)
        .join(Tournament, Tournament.id == Registration.tournament_id)
        .outerjoin(Organization, Organization.id == Tournament.organization_id)
        .where(
            Tournament.status == TournamentStatus.COMPLETED,
            Tournament.standings_public.is_(True),
            Tournament.decklists_public.is_(True),
            Registration.waitlisted.is_(False),
        )
    )


def _filtered(game: str, fmt: str, archetype: str, card: str, store: str, days: int) -> Select:
    stmt = _public_lists().where(Tournament.game == game)
    if fmt:
        # La lista di un segmento ha il suo formato; quella principale quello del torneo.
        list_format = func.coalesce(func.nullif(Decklist.format, ""), Tournament.format)
        stmt = stmt.where(func.lower(list_format) == fmt.lower())
    if archetype:
        stmt = stmt.where(func.lower(Registration.archetype).contains(archetype.lower(), autoescape=True))
    if card:
        # Primo taglio in SQL; il nome esatto si controlla dopo, riga per riga.
        stmt = stmt.where(func.lower(Decklist.raw_text).contains(card.lower(), autoescape=True))
    if store:
        stmt = stmt.where(Organization.slug == store)
    if days:
        stmt = stmt.where(Tournament.starts_on >= local_today() - timedelta(days=days))
    return stmt.order_by(Tournament.starts_on.desc(), Tournament.id.desc()).limit(MAX_CANDIDATES)


def _entries(rows, db: Session, card: str = "", top: int = 0) -> list[dict]:
    wanted = card.lower()
    out = []
    for decklist, registration, tournament, store in rows:
        if wanted and not any(entry.name.lower() == wanted for entry in parse_decklist(decklist.raw_text)):
            continue
        placements = _placements(tournament.id, db)
        placement = placements.get(registration.id)
        if not placement:            # iscritto ma mai in classifica: la lista non è stata giocata
            continue
        position, record, points, name = placement
        if top and position > top:
            continue
        out.append({
            "decklist_id": decklist.id, "registration_id": registration.id,
            "tournament_id": tournament.id, "tournament_name": tournament.name, "starts_on": tournament.starts_on,
            "store_name": store.name if store else None, "store_slug": store.slug if store else None,
            "format": decklist.format or tournament.format, "position": position, "players": len(placements),
            "player_name": name, "archetype": registration.archetype or "", "record": record, "points": points,
            "main_count": decklist.main_count, "side_count": decklist.side_count, "raw_text": decklist.raw_text,
        })
    out.sort(key=lambda e: (-e["starts_on"].toordinal(), -e["tournament_id"], e["position"]))
    return out


@router.get("", response_model=ArchivePageOut)
def search_archive(
    fmt: str = Query(default="", alias="format", max_length=80),
    archetype: str = Query(default="", max_length=120),
    card: str = Query(default="", max_length=150),
    store: str = Query(default="", max_length=120),
    days: int = Query(default=90, ge=0, le=3650),       # 0 = da sempre
    top: int = Query(default=0, ge=0, le=64),           # 0 = tutte le posizioni
    game: str = Query(default="mtg", max_length=20),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ArchivePageOut:
    rows = db.execute(_filtered(game, fmt.strip(), archetype.strip(), card.strip(), store.strip(), days)).all()
    entries = _entries(rows, db, card.strip(), top)
    start = (page - 1) * per_page
    return ArchivePageOut(
        total=len(entries), page=page, per_page=per_page,
        items=[ArchiveDeckOut(**entry) for entry in entries[start:start + per_page]],
    )


@router.get("/meta", response_model=ArchiveMetaOut)
def archive_meta(
    fmt: str = Query(default="", alias="format", max_length=80),
    store: str = Query(default="", max_length=120),
    days: int = Query(default=90, ge=0, le=3650),
    game: str = Query(default="mtg", max_length=20),
    db: Session = Depends(get_db),
) -> ArchiveMetaOut:
    """Il metagame delle liste in archivio: quanto si gioca ogni archetipo e le
    carte che compaiono in più liste (terre base escluse)."""
    entries = _entries(db.execute(_filtered(game, fmt.strip(), "", "", store.strip(), days)).all(), db)
    total = len(entries)
    groups: dict[str, dict] = {}
    spellings: dict[str, Counter[str]] = {}
    for entry in entries:
        label = entry["archetype"].strip()
        group = groups.setdefault(label.lower(), {"lists": 0, "top8": 0, "wins": 0})
        spellings.setdefault(label.lower(), Counter())[label] += 1
        group["lists"] += 1
        group["top8"] += entry["position"] <= 8
        group["wins"] += entry["position"] == 1
    for key, group in groups.items():
        # "tron" e "Tron" sono lo stesso archetipo: si mostra la grafia più usata,
        # a parità quella con le maiuscole.
        label = max(spellings[key].items(), key=lambda item: (item[1], sum(c.isupper() for c in item[0])))[0]
        group["archetype"] = label or "Non indicato"
        group["share"] = round(100 * group["lists"] / total, 1)
    archetypes = sorted(groups.values(), key=lambda g: (-g["lists"], g["archetype"].lower()))

    in_lists: Counter[str] = Counter()
    copies: Counter[str] = Counter()
    spelled: dict[str, str] = {}
    for entry in entries:
        seen: set[str] = set()
        for card in parse_decklist(entry["raw_text"]):
            key = card.name.lower()
            if key in MTG_BASIC_LANDS:
                continue
            copies[key] += card.quantity
            spelled.setdefault(key, card.name)
            if key not in seen:
                seen.add(key)
                in_lists[key] += 1
    top_cards = [
        {"name": spelled[key], "lists": count, "share": round(100 * count / total, 1),
         "copies": round(copies[key] / count, 1)}
        for key, count in in_lists.most_common(20)
    ]
    return ArchiveMetaOut(total_lists=total, archetypes=archetypes, top_cards=top_cards)


@router.get("/{decklist_id}", response_model=ArchiveDeckDetailOut)
def archive_deck(decklist_id: int, db: Session = Depends(get_db)) -> ArchiveDeckDetailOut:
    entries = _entries(db.execute(_public_lists().where(Decklist.id == decklist_id)).all(), db)
    if not entries:
        raise HTTPException(status_code=404, detail="Lista non pubblica o inesistente")
    return ArchiveDeckDetailOut(**entries[0])
