"""
Router API pubblica (v1) — i tornei di un negozio per i suoi siti, bot e
overlay di streaming. Sola lettura, con una chiave del negozio.

La chiave si crea dal back-office (Negozio → API), si vede una volta sola e nel
database resta solo il suo hash (services/api_keys.py). Ogni richiesta la porta
nell'intestazione X-API-Key e vede solo i tornei del suo negozio. I dati
personali (email, ID presso l'editore, pagamenti) da qui non escono mai.
"""
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.limiter import limiter
from backend.app.db import get_db
from backend.app.models import (
    ApiKey,
    Organization,
    Pairing,
    Registration,
    Round,
    Tournament,
    TournamentStatus,
)
from backend.app.schemas import ApiPairingsOut, ApiPlayerOut, ApiTournamentOut, StandingOut
from backend.app.services.api_keys import hash_key
from backend.app.services.pairings import calculate_standings

router = APIRouter(prefix="/v1", tags=["public-api"])

# Quanto spesso si scrive "usata l'ultima volta": non a ogni richiesta di un overlay.
LAST_USED_EVERY = timedelta(minutes=1)


def _key_or_ip(request: Request) -> str:
    """Il limite di richieste vale per chiave: più siti dietro lo stesso IP non si pestano i piedi."""
    return request.headers.get("X-API-Key") or get_remote_address(request)


def store_for_key(request: Request, db: Session = Depends(get_db)) -> Organization:
    raw = request.headers.get("X-API-Key", "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Serve una chiave API nell'intestazione X-API-Key")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw), ApiKey.revoked_at.is_(None)))
    if not key:
        raise HTTPException(status_code=401, detail="Chiave API non valida o revocata")
    now = datetime.now(UTC)
    last = key.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is None or now - last >= LAST_USED_EVERY:
        key.last_used_at = now
        db.commit()
    return db.get(Organization, key.organization_id)


def _store_tournament(tournament_id: int, store: Organization, db: Session) -> Tournament:
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.organization_id != store.id or tournament.status == TournamentStatus.DRAFT:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    return tournament


def _tournament_out(tournament: Tournament, db: Session) -> ApiTournamentOut:
    registered = db.scalar(select(func.count(Registration.id)).where(
        Registration.tournament_id == tournament.id, Registration.waitlisted.is_(False))) or 0
    current_round = db.scalar(select(func.max(Round.number)).where(Round.tournament_id == tournament.id))
    return ApiTournamentOut(
        id=tournament.id, name=tournament.name, game=tournament.game, format=tournament.format,
        event_type=tournament.event_type, status=tournament.status, starts_on=tournament.starts_on,
        start_time=tournament.start_time, place="" if tournament.is_online else tournament.place,
        is_online=tournament.is_online, online_platform=tournament.online_platform,
        capacity=tournament.capacity, registered_players=registered,
        entry_fee_cents=tournament.entry_fee_cents, currency=tournament.currency,
        structure=tournament.structure, current_round=current_round,
    )


@router.get("/tournaments", response_model=list[ApiTournamentOut])
@limiter.limit("120/minute", key_func=_key_or_ip)
def api_tournaments(
    request: Request,
    status: str | None = Query(default=None, description="Uno o più stati separati da virgola"),
    date_from: date | None = None,
    date_to: date | None = None,
    store: Organization = Depends(store_for_key),
    db: Session = Depends(get_db),
) -> list[ApiTournamentOut]:
    """I tornei del negozio, dal più vicino nel tempo. Le bozze non escono."""
    stmt = select(Tournament).where(
        Tournament.organization_id == store.id, Tournament.status != TournamentStatus.DRAFT)
    if status:
        stmt = stmt.where(Tournament.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if date_from:
        stmt = stmt.where(Tournament.starts_on >= date_from)
    if date_to:
        stmt = stmt.where(Tournament.starts_on <= date_to)
    return [_tournament_out(t, db) for t in db.scalars(stmt.order_by(Tournament.starts_on, Tournament.id))]


@router.get("/tournaments/{tournament_id}", response_model=ApiTournamentOut)
@limiter.limit("120/minute", key_func=_key_or_ip)
def api_tournament(
    request: Request, tournament_id: int,
    store: Organization = Depends(store_for_key), db: Session = Depends(get_db),
) -> ApiTournamentOut:
    return _tournament_out(_store_tournament(tournament_id, store, db), db)


@router.get("/tournaments/{tournament_id}/players", response_model=list[ApiPlayerOut])
@limiter.limit("120/minute", key_func=_key_or_ip)
def api_players(
    request: Request, tournament_id: int,
    store: Organization = Depends(store_for_key), db: Session = Depends(get_db),
) -> list[ApiPlayerOut]:
    """Chi è iscritto: nome e stato, niente contatti né pagamenti."""
    tournament = _store_tournament(tournament_id, store, db)
    registrations = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament.id)
        .options(selectinload(Registration.player)).order_by(Registration.id)
    ).all()
    return [
        ApiPlayerOut(registration_id=r.id, name=r.player.display_name, checked_in=r.checked_in,
                     dropped=r.dropped, waitlisted=r.waitlisted)
        for r in registrations
    ]


@router.get("/tournaments/{tournament_id}/pairings", response_model=ApiPairingsOut)
@limiter.limit("120/minute", key_func=_key_or_ip)
def api_pairings(
    request: Request, tournament_id: int, round: int | None = Query(default=None, ge=1),
    store: Organization = Depends(store_for_key), db: Session = Depends(get_db),
) -> ApiPairingsOut:
    """Gli abbinamenti di un turno: l'ultimo, se non se ne chiede uno."""
    tournament = _store_tournament(tournament_id, store, db)
    stmt = select(Round).where(Round.tournament_id == tournament.id, Round.is_published.is_(True))
    stmt = stmt.where(Round.number == round) if round else stmt.order_by(Round.number.desc())
    rnd = db.scalars(stmt.limit(1)).first()
    if not rnd:
        raise HTTPException(status_code=404, detail="Nessun turno")
    pairings = db.scalars(
        select(Pairing).where(Pairing.round_id == rnd.id).order_by(Pairing.table_number)
        .options(selectinload(Pairing.player_a).selectinload(Registration.player),
                 selectinload(Pairing.player_b).selectinload(Registration.player))
    ).all()
    return ApiPairingsOut(
        round=rnd.number, phase=rnd.phase, ends_at=rnd.ends_at,
        pairings=[{
            "table": p.table_number,
            "player_a": p.player_a.player.display_name,
            "player_b": p.player_b.player.display_name if p.player_b else None,
            "result": p.result or "", "match_wins_a": p.match_wins_a, "match_wins_b": p.match_wins_b,
            "draws": p.draws,
        } for p in pairings],
    )


@router.get("/tournaments/{tournament_id}/standings", response_model=list[StandingOut])
@limiter.limit("120/minute", key_func=_key_or_ip)
def api_standings(
    request: Request, tournament_id: int,
    store: Organization = Depends(store_for_key), db: Session = Depends(get_db),
) -> list[StandingOut]:
    """La classifica con gli spareggi del gioco del torneo."""
    return calculate_standings(_store_tournament(tournament_id, store, db).id, db)
