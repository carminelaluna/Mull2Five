"""
Router stagioni — raggruppa tornei e calcola la leaderboard cumulativa.

La leaderboard è il motivo per cui i regular tornano in negozio: punti
configurabili per vittoria/pareggio, sommati su tutti i tornei della stagione.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import (
    Organization,
    Pairing,
    Registration,
    Round,
    Season,
    Tournament,
    User,
)
from backend.app.schemas import (
    LeaderboardRowOut,
    SeasonCreate,
    SeasonOut,
    SeasonUpdate,
    SeriesPublicOut,
)
from backend.app.security import require_organizer
from backend.app.services.tournament_views import tournament_with_counts

router = APIRouter(prefix="/seasons", tags=["seasons"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "circuito"


def _unique_slug(name: str, db: Session) -> str:
    base = _slugify(name)
    slug, n = base, 2
    while db.scalar(select(Season.id).where(Season.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _season_out(season: Season, db: Session) -> SeasonOut:
    count = db.scalar(
        select(func.count(Tournament.id)).where(Tournament.season_id == season.id)
    ) or 0
    org_slug = db.scalar(
        select(Organization.slug).where(Organization.id == season.organization_id)
    ) if season.organization_id else None
    return SeasonOut.model_validate(season).model_copy(
        update={"tournament_count": count, "organization_slug": org_slug}
    )


def _load_owned_season(season_id: int, organizer: User, db: Session) -> Season:
    season = db.get(Season, season_id)
    if not season or season.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Circuito non trovato")
    return season


@router.get("", response_model=list[SeasonOut])
def list_seasons(db: Session = Depends(get_db)) -> list[SeasonOut]:
    """Stagioni attive — pubblico, per la pagina leaderboard."""
    seasons = db.scalars(select(Season).where(Season.is_active == True)).all()  # noqa: E712
    return [_season_out(s, db) for s in seasons]


@router.post("", response_model=SeasonOut, status_code=201)
def create_season(
    payload: SeasonCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = Season(
        organizer_id=organizer.id,
        organization_id=organizer.organization_id,
        name=payload.name,
        slug=_unique_slug(payload.name, db),
        points_win=payload.points_win,
        points_draw=payload.points_draw,
    )
    db.add(season)
    db.commit()
    db.refresh(season)
    return _season_out(season, db)


@router.post("/{season_id}/tournaments/{tournament_id}", response_model=SeasonOut)
def add_tournament_to_season(
    season_id: int,
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = db.get(Season, season_id)
    if not season or season.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Circuito non trovato")
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    tournament.season_id = season.id
    db.commit()
    return _season_out(season, db)


@router.post("/{season_id}/close", response_model=SeasonOut)
def close_season(
    season_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = db.get(Season, season_id)
    if not season or season.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Circuito non trovato")
    season.is_active = False
    db.commit()
    return _season_out(season, db)


@router.get("/{season_id}/leaderboard", response_model=list[LeaderboardRowOut])
def season_leaderboard(season_id: int, db: Session = Depends(get_db)) -> list[LeaderboardRowOut]:
    """Classifica cumulativa della stagione — pubblica, cache 30s."""
    from backend.app.core.cache import cache_get, cache_set
    cache_key = f"leaderboard:{season_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    season = db.get(Season, season_id)
    if not season:
        raise HTTPException(status_code=404, detail="Circuito non trovato")

    tournament_ids = db.scalars(
        select(Tournament.id).where(Tournament.season_id == season_id)
    ).all()
    if not tournament_ids:
        return []

    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id.in_(tournament_ids))
        .options(joinedload(Registration.player))
    ).all()
    reg_to_player = {r.id: r.player_id for r in registrations}
    player_names = {r.player_id: r.player.display_name for r in registrations}

    # Statistiche per giocatore (cross-torneo, chiave = player_id)
    stats: dict[int, dict] = {
        pid: {"wins": 0, "draws": 0, "losses": 0, "tournaments": set()}
        for pid in player_names
    }
    for reg in registrations:
        stats[reg.player_id]["tournaments"].add(reg.tournament_id)

    pairings = db.scalars(
        select(Pairing).join(Round).where(Round.tournament_id.in_(tournament_ids))
    ).all()
    for pairing in pairings:
        pid_a = reg_to_player.get(pairing.player_a_registration_id)
        pid_b = reg_to_player.get(pairing.player_b_registration_id)
        if pid_a is None:
            continue
        if pairing.player_b_registration_id is None:       # BYE = vittoria
            stats[pid_a]["wins"] += 1
            continue
        if not pairing.result:
            continue
        if pairing.result == "A":
            stats[pid_a]["wins"] += 1
            if pid_b is not None:
                stats[pid_b]["losses"] += 1
        elif pairing.result == "B":
            if pid_b is not None:
                stats[pid_b]["wins"] += 1
            stats[pid_a]["losses"] += 1
        else:                                               # pareggio
            stats[pid_a]["draws"] += 1
            if pid_b is not None:
                stats[pid_b]["draws"] += 1

    rows = [
        LeaderboardRowOut(
            position=0,
            player_name=player_names[pid],
            points=item["wins"] * season.points_win + item["draws"] * season.points_draw,
            wins=item["wins"],
            draws=item["draws"],
            losses=item["losses"],
            tournaments_played=len(item["tournaments"]),
        )
        for pid, item in stats.items()
    ]
    rows.sort(key=lambda r: (r.points, r.wins), reverse=True)
    for index, row in enumerate(rows, start=1):
        row.position = index

    cache_set(cache_key, rows, ttl=30.0)
    return rows


@router.patch("/{season_id}", response_model=SeasonOut)
def update_season(
    season_id: int,
    payload: SeasonUpdate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    """Anagrafica e struttura punti del circuito."""
    season = _load_owned_season(season_id, organizer, db)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None:
            setattr(season, field, value)
    if changes.get("name") and not season.slug:
        season.slug = _unique_slug(season.name, db)
    db.commit()
    db.refresh(season)
    return _season_out(season, db)


@router.get("/public", response_model=list[SeasonOut])
def list_public_series(db: Session = Depends(get_db)) -> list[SeasonOut]:
    """Circuiti pubblicati — alimentano la rail "Circuiti" della home."""
    seasons = db.scalars(
        select(Season)
        .where(Season.is_public.is_(True), Season.slug.is_not(None))
        .order_by(Season.is_active.desc(), Season.created_at.desc())
    ).all()
    return [_season_out(s, db) for s in seasons]


@router.get("/by-slug/{slug}", response_model=SeriesPublicOut)
def public_series(slug: str, db: Session = Depends(get_db)) -> SeriesPublicOut:
    """Pagina pubblica del circuito: tappe in calendario e classifica cumulativa."""
    season = db.scalar(select(Season).where(Season.slug == slug))
    if not season or not season.is_public:
        raise HTTPException(status_code=404, detail="Circuito non trovato")
    tournaments = tournament_with_counts(
        select(Tournament)
        .where(Tournament.season_id == season.id)
        .order_by(Tournament.starts_on.asc()),
        db,
    )
    return SeriesPublicOut(
        season=_season_out(season, db),
        tournaments=tournaments,
        leaderboard=season_leaderboard(season.id, db),
    )
