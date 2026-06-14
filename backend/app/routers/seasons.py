"""
Router stagioni — raggruppa tornei e calcola la leaderboard cumulativa.

La leaderboard è il motivo per cui i regular tornano in negozio: punti
configurabili per vittoria/pareggio, sommati su tutti i tornei della stagione.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import (
    Pairing,
    Registration,
    Round,
    Season,
    Tournament,
    User,
)
from backend.app.schemas import LeaderboardRowOut, SeasonCreate, SeasonOut
from backend.app.security import require_organizer

router = APIRouter(prefix="/seasons", tags=["seasons"])


def _season_out(season: Season, db: Session) -> SeasonOut:
    count = db.scalar(
        select(func.count(Tournament.id)).where(Tournament.season_id == season.id)
    ) or 0
    return SeasonOut.model_validate(season).model_copy(update={"tournament_count": count})


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
        name=payload.name,
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
        raise HTTPException(status_code=404, detail="Season not found")
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Tournament not found")
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
        raise HTTPException(status_code=404, detail="Season not found")
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
        raise HTTPException(status_code=404, detail="Season not found")

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
