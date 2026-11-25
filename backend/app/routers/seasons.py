"""
Router circuiti (nel codice "stagioni") — raggruppa tornei e calcola la classifica cumulativa.

La classifica è il motivo per cui i regular tornano in negozio: punti
configurabili per vittoria, pareggio, partecipazione e torneo vinto, sommati su
tutti i tornei del circuito. I tornei si aggiungono quando si vuole, anche dopo
averli giocati: la classifica si ricalcola dai risultati.
"""
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import false, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from backend.app.core.cache import cache_get, cache_invalidate, cache_set
from backend.app.db import get_db
from backend.app.games import get_game
from backend.app.models import (
    Organization,
    Pairing,
    Registration,
    Round,
    Season,
    Tournament,
    TournamentStatus,
    User,
)
from backend.app.schemas import (
    LeaderboardRowOut,
    SeasonCreate,
    SeasonOut,
    SeasonTournamentsIn,
    SeasonUpdate,
    SeriesPublicOut,
)
from backend.app.security import require_organizer
from backend.app.services.standings import Match as StandingMatch
from backend.app.services.standings import Player as StandingPlayer
from backend.app.services.standings import compute_standings
from backend.app.services.stores import (
    can_manage_store,
    managed_tournaments,
    store_ids,
    working_store,
)
from backend.app.services.tournament_views import tournament_with_counts

router = APIRouter(prefix="/seasons", tags=["seasons"])

ELIMINATION_PHASES = {"elimination", "topcut"}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "circuito"


def _unique_slug(name: str, db: Session) -> str:
    base = _slugify(name)
    slug, n = base, 2
    while db.scalar(select(Season.id).where(Season.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _seasons_out(seasons: list[Season], db: Session) -> list[SeasonOut]:
    """Due query in tutto, quanti che siano i circuiti: conteggi e negozi in blocco."""
    if not seasons:
        return []
    ids = [s.id for s in seasons]
    counts = dict(db.execute(
        select(Tournament.season_id, func.count(Tournament.id))
        .where(Tournament.season_id.in_(ids))
        .group_by(Tournament.season_id)
    ).all())
    org_ids = {s.organization_id for s in seasons if s.organization_id}
    slugs = dict(db.execute(
        select(Organization.id, Organization.slug).where(Organization.id.in_(org_ids))
    ).all()) if org_ids else {}
    return [
        SeasonOut.model_validate(s).model_copy(update={
            "tournament_count": counts.get(s.id, 0),
            "organization_slug": slugs.get(s.organization_id),
        })
        for s in seasons
    ]


def _season_out(season: Season, db: Session) -> SeasonOut:
    return _seasons_out([season], db)[0]


def _load_owned_season(season_id: int, organizer: User, db: Session) -> Season:
    """Il circuito lo gestisce chi l'ha creato e chi fa parte del suo negozio."""
    season = db.get(Season, season_id)
    if not season or not (
        season.organizer_id == organizer.id
        or (season.organization_id and can_manage_store(organizer, season.organization_id, db))
    ):
        raise HTTPException(status_code=404, detail="Circuito non trovato")
    return season


def _forget_leaderboard(season_id: int) -> None:
    cache_invalidate(f"leaderboard:{season_id}")


def _attach(season: Season, tournament_ids: list[int], organizer: User, db: Session) -> None:
    """Mette i tornei nel circuito. Un torneo sta in un circuito solo: se era in
    un altro, passa a questo, e anche quella classifica va ricalcolata."""
    if not season.is_active:
        raise HTTPException(status_code=409, detail="Il circuito è chiuso: riaprilo per aggiungere tornei")
    wanted = set(tournament_ids)
    found = db.execute(
        select(Tournament.id, Tournament.season_id)
        .where(Tournament.id.in_(wanted), managed_tournaments(organizer, db))
    ).all()
    if len(found) != len(wanted):
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    for previous in {old for _, old in found if old and old != season.id}:
        _forget_leaderboard(previous)
    db.execute(update(Tournament).where(Tournament.id.in_(wanted)).values(season_id=season.id))
    db.commit()
    _forget_leaderboard(season.id)


@router.get("", response_model=list[SeasonOut])
def list_seasons(db: Session = Depends(get_db)) -> list[SeasonOut]:
    """Circuiti attivi e pubblici — per la pagina leaderboard."""
    seasons = db.scalars(
        select(Season).where(Season.is_active.is_(True), Season.is_public.is_(True))
    ).all()
    return _seasons_out(list(seasons), db)


@router.get("/mine", response_model=list[SeasonOut])
def my_seasons(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[SeasonOut]:
    """I circuiti che si gestiscono, anche chiusi o privati: per il back-office."""
    stores = store_ids(organizer, db)
    in_store = Season.organization_id.in_(stores) if stores else false()
    seasons = db.scalars(
        select(Season)
        .where(or_(Season.organizer_id == organizer.id, in_store))
        .order_by(Season.is_active.desc(), Season.created_at.desc())
    ).all()
    return _seasons_out(list(seasons), db)


@router.post("", response_model=SeasonOut, status_code=201)
def create_season(
    payload: SeasonCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = Season(
        organizer_id=organizer.id,
        organization_id=working_store(organizer, db),
        slug=_unique_slug(payload.name, db),
        **payload.model_dump(),
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
    season = _load_owned_season(season_id, organizer, db)
    _attach(season, [tournament_id], organizer, db)
    return _season_out(season, db)


@router.post("/{season_id}/tournaments", response_model=SeasonOut)
def add_tournaments_to_season(
    season_id: int,
    payload: SeasonTournamentsIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    """Più tornei insieme, già giocati o ancora da giocare. O tutti o nessuno."""
    season = _load_owned_season(season_id, organizer, db)
    _attach(season, payload.tournament_ids, organizer, db)
    return _season_out(season, db)


@router.delete("/{season_id}/tournaments/{tournament_id}", response_model=SeasonOut)
def remove_tournament_from_season(
    season_id: int,
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    """Il torneo esce dal circuito e i suoi punti dalla classifica. Il torneo resta."""
    season = _load_owned_season(season_id, organizer, db)
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.season_id != season.id:
        raise HTTPException(status_code=404, detail="Torneo non trovato nel circuito")
    tournament.season_id = None
    db.commit()
    _forget_leaderboard(season.id)
    return _season_out(season, db)


@router.post("/{season_id}/close", response_model=SeasonOut)
def close_season(
    season_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = _load_owned_season(season_id, organizer, db)
    season.is_active = False
    db.commit()
    return _season_out(season, db)


@router.delete("/{season_id}", status_code=204)
def delete_season(
    season_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Response:
    """Elimina il circuito. I tornei restano, liberi: si perde solo la classifica."""
    season = _load_owned_season(season_id, organizer, db)
    db.execute(update(Tournament).where(Tournament.season_id == season.id).values(season_id=None))
    db.delete(season)
    db.commit()
    _forget_leaderboard(season_id)
    return Response(status_code=204)


def _champion(
    tournament: Tournament,
    registrations: list[Registration],
    pairings: list[tuple[Pairing, str, int]],
) -> int | None:
    """La registrazione che ha vinto un torneo concluso.

    Con un taglio (top 8, eliminazione diretta) vince chi vince la finale; senza,
    il primo della classifica, con gli spareggi del gioco.
    """
    finals = [row for row in pairings if row[1] in ELIMINATION_PHASES]
    if finals:
        last = max(number for _, _, number in finals)
        final = [p for p, _, number in finals if number == last]
        if len(final) != 1 or final[0].result not in {"A", "B"}:
            return None
        p = final[0]
        return p.player_a_registration_id if p.result == "A" else p.player_b_registration_id
    if not pairings:
        return None
    rows = compute_standings(
        [StandingPlayer(r.id, r.player.display_name, dropped=r.dropped) for r in registrations],
        [StandingMatch(p.player_a_registration_id, p.player_b_registration_id, p.result,
                       p.match_wins_a, p.match_wins_b, p.draws) for p, _, _ in pairings],
        system=get_game(tournament.game).tiebreakers,
        total_rounds=len({p.round_id for p, phase, _ in pairings if phase == "swiss"}),
    )
    return rows[0]["registration_id"] if rows else None


@router.get("/{season_id}/leaderboard", response_model=list[LeaderboardRowOut])
def season_leaderboard(season_id: int, db: Session = Depends(get_db)) -> list[LeaderboardRowOut]:
    """Classifica cumulativa del circuito — pubblica, cache 30s.

    Il punteggio di una tappa: vittorie e pareggi, i punti presenza, il bonus
    vincitore e il bonus imbattuto. Il totale somma le tappe, meno gli scarti.
    Contano i tornei in cui si è giocato almeno un turno: chi è solo iscritto a
    una tappa futura non compare, e non prende i punti di partecipazione.
    Query costanti, quanti che siano i tornei: tutto si carica in blocco.
    """
    cache_key = f"leaderboard:{season_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    season = db.get(Season, season_id)
    if not season:
        raise HTTPException(status_code=404, detail="Circuito non trovato")

    tournaments = db.scalars(select(Tournament).where(Tournament.season_id == season_id)).all()
    if not tournaments:
        return []
    tournament_ids = [t.id for t in tournaments]

    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id.in_(tournament_ids))
        .options(joinedload(Registration.player))
    ).all()
    reg_by_id = {r.id: r for r in registrations}
    regs_by_tournament: dict[int, list[Registration]] = defaultdict(list)
    for reg in registrations:
        regs_by_tournament[reg.tournament_id].append(reg)

    pairings_by_tournament: dict[int, list[tuple[Pairing, str, int]]] = defaultdict(list)
    for pairing, tid, phase, number in db.execute(
        select(Pairing, Round.tournament_id, Round.phase, Round.number)
        .join(Round, Round.id == Pairing.round_id)
        .where(Round.tournament_id.in_(tournament_ids))
    ).all():
        pairings_by_tournament[tid].append((pairing, phase, number))

    # Il record di ogni iscrizione nel suo torneo: [vittorie, pareggi, sconfitte].
    # Nasce al primo abbinamento, anche senza risultato: quella tappa è giocata.
    records: dict[int, list[int]] = {}

    def record(registration_id: int | None) -> list[int] | None:
        if registration_id is None or registration_id not in reg_by_id:
            return None
        return records.setdefault(registration_id, [0, 0, 0])

    for rows in pairings_by_tournament.values():
        for pairing, _, _ in rows:
            a = record(pairing.player_a_registration_id)
            b = record(pairing.player_b_registration_id)
            if a is None:
                continue
            if pairing.player_b_registration_id is None:       # BYE = vittoria
                a[0] += 1
            elif not pairing.result:
                continue
            elif pairing.result == "A":
                a[0] += 1
                if b is not None:
                    b[2] += 1
            elif pairing.result == "B":
                if b is not None:
                    b[0] += 1
                a[2] += 1
            else:                                           # pareggio
                a[1] += 1
                if b is not None:
                    b[1] += 1

    # Vincitore e imbattuti si sanno solo a torneo concluso.
    completed = {t.id for t in tournaments if t.status == TournamentStatus.COMPLETED}
    champions = {
        _champion(t, regs_by_tournament[t.id], pairings_by_tournament[t.id])
        for t in tournaments if t.id in completed
    }

    # Il punteggio di ogni giocatore tappa per tappa: serve agli scarti.
    stats: dict[int, dict] = {}
    for registration_id, (wins, draws, losses) in records.items():
        reg = reg_by_id[registration_id]
        item = stats.setdefault(reg.player_id, {
            "name": reg.player.display_name, "wins": 0, "draws": 0, "losses": 0,
            "titles": 0, "undefeated": 0, "stages": defaultdict(int),
        })
        item["wins"] += wins
        item["draws"] += draws
        item["losses"] += losses
        score = wins * season.points_win + draws * season.points_draw + season.points_participation
        if registration_id in champions:
            item["titles"] += 1
            score += season.points_champion_bonus
        # Imbattuto: tutti i match vinti, i bye compresi. Un pareggio basta a perderlo.
        if reg.tournament_id in completed and wins and not draws and not losses:
            item["undefeated"] += 1
            score += season.points_undefeated_bonus
        item["stages"][reg.tournament_id] += score

    # Scarti: con più di N tornei giocati nel circuito, a ognuno si tolgono i
    # suoi punteggi peggiori, contando 0 le tappe che ha saltato. Almeno una resta.
    played = [tid for tid in tournament_ids if pairings_by_tournament[tid]]
    drop = 0
    if season.drop_worst_scores and len(played) > season.drop_above_tournaments:
        drop = min(season.drop_worst_scores, len(played) - 1)

    leaderboard = []
    for item in stats.values():
        scores = sorted(item["stages"].get(tid, 0) for tid in played)
        discarded = sum(scores[:drop])
        leaderboard.append(LeaderboardRowOut(
            position=0,
            player_name=item["name"],
            points=sum(scores) - discarded,
            wins=item["wins"],
            draws=item["draws"],
            losses=item["losses"],
            tournaments_played=len(item["stages"]),
            titles=item["titles"],
            undefeated=item["undefeated"],
            discarded=discarded,
        ))
    leaderboard.sort(key=lambda r: (r.points, r.wins), reverse=True)
    for index, row in enumerate(leaderboard, start=1):
        row.position = index

    cache_set(cache_key, leaderboard, ttl=30.0)
    return leaderboard


@router.patch("/{season_id}", response_model=SeasonOut)
def update_season(
    season_id: int,
    payload: SeasonUpdate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SeasonOut:
    """Anagrafica, struttura punti, chiusura e riapertura del circuito.

    Date e soglia si possono svuotare mandando null; il resto, null, resta com'è.
    """
    season = _load_owned_season(season_id, organizer, db)
    clearable = {"starts_on", "ends_on", "qualification_threshold"}
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None or field in clearable:
            setattr(season, field, value)
    if changes.get("name") and not season.slug:
        season.slug = _unique_slug(season.name, db)
    db.commit()
    db.refresh(season)
    _forget_leaderboard(season.id)
    return _season_out(season, db)


@router.get("/public", response_model=list[SeasonOut])
def list_public_series(db: Session = Depends(get_db)) -> list[SeasonOut]:
    """Circuiti pubblicati — alimentano la rail "Circuiti" della home."""
    seasons = db.scalars(
        select(Season)
        .where(Season.is_public.is_(True), Season.slug.is_not(None))
        .order_by(Season.is_active.desc(), Season.created_at.desc())
    ).all()
    return _seasons_out(list(seasons), db)


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
