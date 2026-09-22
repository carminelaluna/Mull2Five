import csv
import io
import math
import random
import re
from datetime import UTC, date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload  # noqa: F401

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.core.tenant import requested_org
from backend.app.db import get_db
from backend.app.games import ALLOWED_SCORES, get_game, is_enabled, online_platform
from backend.app.models import (
    Announcement,
    AnnouncementRecipient,
    AuditLog,
    DeckCheck,
    Decklist,
    DecklistRevision,
    DecklistStatus,
    Event,
    EventStaff,
    InviteCode,
    Location,
    Organization,
    Pairing,
    PairingResultReport,
    Payment,
    PaymentStatus,
    Penalty,
    PlayerTag,
    PlayerTagAssignment,
    Registration,
    RegistrationAnswer,
    RegistrationField,
    RegistrationMode,
    ResultReportStatus,
    Round,
    StaffRole,
    Team,
    Tournament,
    TournamentSeries,
    TournamentStaff,
    TournamentStatus,
    TournamentStructure,
    User,
    UserRole,
)
from backend.app.schemas import (
    AnnouncementAudienceOut,
    AnnouncementCreate,
    AnnouncementOut,
    AuditLogOut,
    BracketMatchOut,
    ByesIn,
    CheckoutCreate,
    Day2ConversionRow,
    Day2In,
    DeckCheckIn,
    DeckCheckOut,
    DecklistCreate,
    DecklistOut,
    DropUnpaidOut,
    FixedTableIn,
    GameHandleIn,
    ImportIn,
    ImportOut,
    ImportRowOut,
    InviteCodeCreate,
    InviteCodeOut,
    ManualPairingIn,
    MetaStatRow,
    OfficialReportOut,
    OfficialReportRowOut,
    OrganizedTournamentRow,
    OrganizerRegistrationOut,
    PairingOut,
    PairingResultIn,
    PairingResultRejectIn,
    PaymentOut,
    PenaltyCreate,
    PenaltyHistoryOut,
    PenaltyOut,
    PlayerCardOut,
    PlayerHistoryRowOut,
    PlayerPublicProfileOut,
    PodOut,
    PodSeatOut,
    PodsIn,
    PrizeIn,
    PublicDisplayOut,
    PublicPairingOut,
    PublicResultsOut,
    PublicStandingRow,
    PublisherIdIn,
    RefundDecisionIn,
    RefundRequestIn,
    RegenerateRoundIn,
    RegistrationCreate,
    RegistrationFieldIn,
    RegistrationFieldOut,
    RegistrationOut,
    RepeatIn,
    RepeatPreviewOut,
    RoundFormatIn,
    RoundOut,
    StaffIn,
    StaffOut,
    StaffRoleIn,
    StandingOut,
    TableAssignIn,
    TableExtendIn,
    TableStatusIn,
    TardinessIn,
    TeamIn,
    TeamMemberOut,
    TeamOut,
    TeamSeatIn,
    TeamStandingOut,
    TimerExtendIn,
    TimerRestartIn,
    TournamentControlsIn,
    TournamentCreate,
    TournamentOut,
    TournamentReportOut,
    TournamentRoleOut,
    TournamentUpdate,
    WalkInIn,
    WarningOut,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.decklists import validate_card_legality, validate_decklist
from backend.app.services.email import event_announcement_html, send_email
from backend.app.services.payments import (
    create_paypal_checkout,
    create_stripe_checkout,
    refund_paypal_capture,
)
from backend.app.services.player_import import parse_players_csv
from backend.app.services.stores import active_suspension, managed_tournaments, store_role
from backend.app.services.warnings import build_context, tournament_warnings

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distanza in chilometri fra due punti sulla sfera terrestre."""
    radius = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    )
    return 2 * radius * asin(sqrt(a))


def filter_by_distance(
    tournaments: list[TournamentOut], lat: float, lng: float, radius_km: float | None, db: Session
) -> list[TournamentOut]:
    """Calcola la distanza e, se c'è un raggio, scarta chi ne sta fuori.

    Il conto si fa in Python: i tornei per tenant sono poche centinaia e SQLite
    non ha funzioni geospaziali. Un torneo senza coordinate proprie eredita quelle
    del negozio; se non le ha nessuno dei due resta fuori dalla ricerca per distanza.
    """
    org_coords = {
        o.slug: (o.latitude, o.longitude)
        for o in db.scalars(select(Organization)).all()
        if o.latitude is not None and o.longitude is not None
    }
    located: list[TournamentOut] = []
    for t in tournaments:
        coords = (t.latitude, t.longitude)
        if coords[0] is None or coords[1] is None:
            coords = org_coords.get(t.organization_slug, (None, None))
        if coords[0] is None or coords[1] is None:
            continue
        distance = haversine_km(lat, lng, coords[0], coords[1])
        if radius_km is not None and distance > radius_km:
            continue
        located.append(t.model_copy(update={"distance_km": round(distance, 1)}))
    located.sort(key=lambda t: t.distance_km or 0)
    return located


def tournament_out(tournament: Tournament, registered: int, db: Session) -> TournamentOut:
    """Serializza un torneo con negozio ed evento di appartenenza.

    Unico punto: prima l'arricchimento stava solo nell'helper della lista e il
    GET del singolo torneo rispondeva con event_slug nullo.
    """
    org = db.get(Organization, tournament.organization_id) if tournament.organization_id else None
    event = db.get(Event, tournament.event_id) if tournament.event_id else None
    organizer = db.get(User, tournament.organizer_id)
    location = tournament.location
    # La sede presta al torneo quello che non ha di suo: il luogo scritto e le
    # coordinate, così compare anche nella ricerca per distanza.
    inherited = {"venue": tournament.place}
    if location:
        inherited["location_name"] = location.name
        if tournament.latitude is None and location.latitude is not None:
            inherited["latitude"] = location.latitude
            inherited["longitude"] = location.longitude
    # I segmenti nascono dai round: dichiarare un formato su un turno significa
    # che per quella porzione serve una lista a parte.
    segments = db.scalars(
        select(Round.format)
        .where(Round.tournament_id == tournament.id, Round.format.is_not(None))
        .distinct()
    ).all()
    return TournamentOut.model_validate(tournament).model_copy(update={
        "registered_players": registered,
        "online_link": "",      # lo vedono solo iscritti e staff: vedi my_tournaments
        "organizer_name": organizer.display_name if organizer else None,
        **inherited,
        "organization_slug": org.slug if org else None,
        "organization_name": org.name if org else None,
        "event_slug": event.slug if event else None,
        "event_name": event.name if event else None,
        "decklist_formats": [""] + sorted(f for f in segments if f),
    })


# ── Domande all'iscrizione ────────────────────────────────────


def _field_out(field: RegistrationField) -> RegistrationFieldOut:
    return RegistrationFieldOut(id=field.id, label=field.label, kind=field.kind,
                                options=field.option_list, required=field.required, position=field.position)


def _fields_of(tournament_id: int, db: Session) -> list[RegistrationField]:
    return list(db.scalars(
        select(RegistrationField).where(RegistrationField.tournament_id == tournament_id)
        .order_by(RegistrationField.position, RegistrationField.id)
    ).all())


@router.get("/{tournament_id}/fields", response_model=list[RegistrationFieldOut])
def list_fields(tournament_id: int, db: Session = Depends(get_db)) -> list[RegistrationFieldOut]:
    """Le domande del torneo: pubbliche, servono al modulo d'iscrizione."""
    return [_field_out(f) for f in _fields_of(tournament_id, db)]


@router.put("/{tournament_id}/fields", response_model=list[RegistrationFieldOut])
def replace_fields(
    tournament_id: int,
    payload: list[RegistrationFieldIn],
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[RegistrationFieldOut]:
    """Le domande, tutte insieme e nell'ordine voluto. Quelle che mantengono il
    loro id tengono le risposte già date; quelle che mancano spariscono, con le
    loro risposte."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    existing = {f.id: f for f in _fields_of(tournament.id, db)}
    kept: set[int] = set()
    for position, item in enumerate(payload):
        field = existing.get(item.id) if item.id else None
        if item.id and not field:
            raise HTTPException(status_code=404, detail=f"Domanda {item.id} non trovata")
        if field is None:
            field = RegistrationField(tournament_id=tournament.id)
            db.add(field)
        field.label, field.kind, field.required = item.label.strip(), item.kind, item.required
        field.options = "\n".join(item.options)
        field.position = position
        if item.id:
            kept.add(item.id)
    for field_id, field in existing.items():
        if field_id not in kept:
            db.execute(delete(RegistrationAnswer).where(RegistrationAnswer.field_id == field_id))
            db.delete(field)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament.id}")
    return [_field_out(f) for f in _fields_of(tournament.id, db)]


def validate_answers(
    tournament_id: int, raw: dict[int, str | bool], db: Session, enforce_required: bool = True
) -> dict[int, str]:
    """Controlla le risposte contro le domande del torneo e le rende testo.
    Al banco le obbligatorie si possono lasciare vuote: decide chi iscrive."""
    fields = {f.id: f for f in _fields_of(tournament_id, db)}
    if set(raw) - set(fields):
        raise HTTPException(status_code=422, detail="Risposta a una domanda che il torneo non ha")
    answers: dict[int, str] = {}
    for field in fields.values():
        value = raw.get(field.id)
        if field.kind == "checkbox":
            text = "sì" if value is True or str(value).lower() in {"true", "sì", "si", "1"} else ""
        else:
            text = str(value).strip() if value not in (None, False) else ""
        if field.kind == "choice" and text and text not in field.option_list:
            raise HTTPException(status_code=422, detail=f"«{field.label}»: scegli una delle opzioni")
        if enforce_required and field.required and not text:
            raise HTTPException(status_code=422, detail=f"Rispondi a «{field.label}»")
        if text:
            answers[field.id] = text[:1000]
    return answers


def save_answers(registration_id: int, answers: dict[int, str], db: Session) -> None:
    for field_id, value in answers.items():
        db.add(RegistrationAnswer(registration_id=registration_id, field_id=field_id, value=value))


def answers_for(registration_ids: list[int], db: Session) -> dict[int, dict[int, str]]:
    out: dict[int, dict[int, str]] = {}
    if not registration_ids:
        return out
    for answer in db.scalars(
        select(RegistrationAnswer).where(RegistrationAnswer.registration_id.in_(registration_ids))
    ):
        out.setdefault(answer.registration_id, {})[answer.field_id] = answer.value
    return out


def check_not_suspended(player: User, tournament: Tournament, db: Session, at_desk: bool = False) -> None:
    """Un giocatore sospeso dal negozio non si iscrive ai suoi eventi. Al banco
    l'organizzatore vede anche il motivo; il giocatore solo fino a quando."""
    suspension = active_suspension(player.id, tournament.organization_id, db)
    if not suspension:
        return
    until = f" fino al {suspension.ends_on:%d/%m/%Y}" if suspension.ends_on else ""
    if at_desk:
        raise HTTPException(
            status_code=409,
            detail=f"{player.display_name} è sospeso dagli eventi del negozio{until}: {suspension.reason}",
        )
    raise HTTPException(
        status_code=403,
        detail=f"Sei sospeso dagli eventi di questo negozio{until}. Per chiarimenti rivolgiti al negozio.",
    )


def check_location(location_id: int | None, organizer: User, db: Session) -> None:
    """La sede dev'essere del negozio di chi organizza: non si gioca a casa d'altri."""
    if not location_id:
        return
    from backend.app.routers.tags import org_id_for

    location = db.get(Location, location_id)
    if not location or location.organization_id != org_id_for(organizer, db):
        raise HTTPException(status_code=404, detail="Sede non trovata")


def tournament_with_counts(stmt: Select[tuple[Tournament]], db: Session) -> list[TournamentOut]:
    """
    Ottimizzazione: unica query con LEFT JOIN invece di 2 query separate.
    La versione precedente eseguiva COUNT su tutte le iscrizioni (N+1 sotto carico).
    """
    count_subq = (
        select(
            Registration.tournament_id,
            func.count(Registration.id).label("cnt"),
        )
        .group_by(Registration.tournament_id)
        .subquery("reg_counts")
    )

    combined = (
        stmt.add_columns(func.coalesce(count_subq.c.cnt, 0).label("reg_count"))
        .outerjoin(count_subq, Tournament.id == count_subq.c.tournament_id)
    )

    rows = db.execute(combined).all()
    return [
        tournament_out(tournament, int(reg_count), db)
        for tournament, reg_count in rows
    ]


@router.get("", response_model=list[TournamentOut])
def list_tournaments(
    org: Organization | None = Depends(requested_org),
    name: str | None = None,
    format: str | None = None,
    formats: str | None = None,
    event_types: str | None = None,
    games: str | None = None,
    rel: str | None = None,
    venue: str | None = None,
    stores: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    days: int | None = Query(default=None, ge=1, le=730),
    near_lat: float | None = Query(default=None, ge=-90, le=90),
    near_lng: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float | None = Query(default=None, gt=0, le=20000),
    status: str | None = None,
    online: bool | None = None,
    db: Session = Depends(get_db),
) -> list[TournamentOut]:
    """Elenco pubblico dei tornei di tutti i negozi, o di uno solo se la
    richiesta lo chiede (header del tenant o ?org=), con filtri di ricerca.

    I parametri a valori multipli (`status`, `formats`, `event_types`, `games`, `rel`,
    `stores`) accettano una lista separata da virgola. `days` è una finestra
    temporale a partire da oggi; `near_lat`/`near_lng`/`radius_km` filtrano per
    distanza usando le coordinate del torneo o, se assenti, quelle del negozio.
    """
    stmt = select(Tournament).where(Tournament.status != TournamentStatus.CANCELLED)
    if org:
        stmt = stmt.where(
            (Tournament.organization_id == org.id) | (Tournament.organization_id.is_(None))
        )
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        if wanted:
            stmt = stmt.where(Tournament.status.in_(wanted))
    if name:
        stmt = stmt.where(Tournament.name.ilike(f"%{name}%"))
    if format:
        stmt = stmt.where(Tournament.format == format)
    if formats:
        wanted = [f.strip() for f in formats.split(",") if f.strip()]
        if wanted:
            stmt = stmt.where(Tournament.format.in_(wanted))
    if games:
        wanted_games = [g.strip() for g in games.split(",") if g.strip()]
        if wanted_games:
            stmt = stmt.where(Tournament.game.in_(wanted_games))
    if event_types:
        wanted = [e.strip() for e in event_types.split(",") if e.strip()]
        if wanted:
            stmt = stmt.where(Tournament.event_type.in_(wanted))
    if rel:
        wanted = [r.strip() for r in rel.split(",") if r.strip()]
        if wanted:
            stmt = stmt.where(Tournament.rules_enforcement_level.in_(wanted))
    if stores:
        slugs = [s_.strip() for s_ in stores.split(",") if s_.strip()]
        if slugs:
            store_ids = db.scalars(select(Organization.id).where(Organization.slug.in_(slugs))).all()
            stmt = stmt.where(Tournament.organization_id.in_(store_ids or [0]))
    if days:
        today = local_today()
        stmt = stmt.where(Tournament.starts_on >= today, Tournament.starts_on <= today + timedelta(days=days))
    if venue:
        pattern = f"%{venue}%"
        at_location = select(Location.id).where(or_(
            Location.name.ilike(pattern), Location.address.ilike(pattern), Location.city.ilike(pattern)
        ))
        stmt = stmt.where(or_(Tournament.venue.ilike(pattern), Tournament.location_id.in_(at_location)))
    if online is not None:
        stmt = stmt.where(Tournament.is_online.is_(online))
    if date_from:
        stmt = stmt.where(Tournament.starts_on >= date_from)
    if date_to:
        stmt = stmt.where(Tournament.starts_on <= date_to)
    stmt = stmt.order_by(Tournament.starts_on.asc())
    results = tournament_with_counts(stmt, db)
    if near_lat is not None and near_lng is not None:
        results = filter_by_distance(results, near_lat, near_lng, radius_km, db)
    return results


@router.get("/mine", response_model=list[TournamentOut])
def my_tournaments(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TournamentOut]:
    # I propri, quelli del negozio e quelli dentro i propri eventi.
    organizer_stmt = select(Tournament).where(or_(
        managed_tournaments(user, db),
        Tournament.event_id.in_(select(Event.id).where(Event.organizer_id == user.id)),
    ))
    registered_stmt = (
        select(Tournament)
        .join(Registration)
        .where(Registration.player_id == user.id)
        .distinct()
    )
    # Senza questa terza query un capojudge/judge non troverebbe il torneo che deve
    # arbitrare: non lo organizza e non ci è iscritto.
    staff_stmt = (
        select(Tournament)
        .join(TournamentStaff, TournamentStaff.tournament_id == Tournament.id)
        .where(TournamentStaff.user_id == user.id)
        .distinct()
    )
    managed = {item.id for item in db.scalars(organizer_stmt).all()}
    ids = set(managed)
    ids.update(item.id for item in db.scalars(registered_stmt).all())
    ids.update(item.id for item in db.scalars(staff_stmt).all())
    if not ids:
        return []
    links = dict(db.execute(select(Tournament.id, Tournament.online_link).where(Tournament.id.in_(ids))).all())
    return [
        t.model_copy(update={"can_manage": t.id in managed, "online_link": links.get(t.id) or ""})
        for t in tournament_with_counts(select(Tournament).where(Tournament.id.in_(ids)), db)
    ]


@router.get("/me/history", response_model=list[PlayerHistoryRowOut])
def my_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlayerHistoryRowOut]:
    """Storico tornei del giocatore: piazzamento, record e punti per ogni torneo giocato."""
    regs = db.scalars(
        select(Registration)
        .where(Registration.player_id == user.id)
        .options(joinedload(Registration.tournament))
    ).all()
    rows: list[PlayerHistoryRowOut] = []
    for reg in regs:
        t = reg.tournament
        if not t:
            continue
        placement = None
        record = ""
        points = 0
        # Calcola piazzamento solo per tornei iniziati/conclusi
        if t.status in {TournamentStatus.RUNNING, TournamentStatus.COMPLETED}:
            standings = calculate_standings(t.id, db)
            mine = next((s for s in standings if s.registration_id == reg.id), None)
            if mine:
                placement = mine.position
                record = mine.record
                points = mine.points
        rows.append(PlayerHistoryRowOut(
            tournament_id=t.id, tournament_name=t.name, starts_on=t.starts_on,
            format=t.format, status=t.status, placement=placement, record=record, points=points,
        ))
    rows.sort(key=lambda r: str(r.starts_on), reverse=True)
    return rows


@router.get("/players/{email}/public-history", response_model=PlayerPublicProfileOut)
def player_public_history(
    email: str,
    db: Session = Depends(get_db),
) -> PlayerPublicProfileOut:
    """Profilo pubblico di un giocatore: storico e statistiche aggregate, calcolate
    solo dai tornei con classifica pubblica. Nessuna autenticazione richiesta."""
    player = db.scalar(select(User).where(User.email == email.lower()))
    if not player:
        raise HTTPException(status_code=404, detail="Giocatore non trovato")
    regs = db.scalars(
        select(Registration)
        .where(Registration.player_id == player.id)
        .options(joinedload(Registration.tournament))
    ).all()
    rows: list[PlayerHistoryRowOut] = []
    tot_pts = wins = draws = losses = 0
    for reg in regs:
        t = reg.tournament
        if not t or not t.standings_public:
            continue
        if t.status not in {TournamentStatus.RUNNING, TournamentStatus.COMPLETED}:
            continue
        standings = calculate_standings(t.id, db)
        mine = next((s for s in standings if s.registration_id == reg.id), None)
        if not mine:
            continue
        # record è "V/P/S" (vittorie/pareggi/sconfitte)
        try:
            w, d, ls = (int(x) for x in str(mine.record).split("/"))
        except (ValueError, AttributeError):
            w = d = ls = 0
        wins += w
        draws += d
        losses += ls
        tot_pts += mine.points
        rows.append(PlayerHistoryRowOut(
            tournament_id=t.id, tournament_name=t.name, starts_on=t.starts_on,
            format=t.format, status=t.status, placement=mine.position,
            record=mine.record, points=mine.points, event_type=t.event_type,
            invited=t.status == TournamentStatus.COMPLETED and mine.position <= t.invites,
        ))
    rows.sort(key=lambda r: str(r.starts_on), reverse=True)

    # Tornei organizzati (pubblicati/in corso/conclusi) — sezione profilo organizzatore.
    organized: list[OrganizedTournamentRow] = []
    org_tournaments = db.scalars(
        select(Tournament)
        .where(
            Tournament.organizer_id == player.id,
            Tournament.status.in_([
                TournamentStatus.PUBLISHED, TournamentStatus.RUNNING, TournamentStatus.COMPLETED,
            ]),
        )
        .order_by(Tournament.starts_on.desc())
    ).all()
    for t in org_tournaments:
        count = db.scalar(
            select(func.count(Registration.id)).where(Registration.tournament_id == t.id)
        )
        organized.append(OrganizedTournamentRow(
            tournament_id=t.id, name=t.name, format=t.format, starts_on=t.starts_on,
            status=t.status, registered_players=count or 0,
        ))

    return PlayerPublicProfileOut(
        display_name=player.display_name, email=player.email, role=player.role,
        tournaments_played=len(rows), total_points=tot_pts,
        wins=wins, draws=draws, losses=losses, rows=rows, organized=organized,
    )


def _copy_tournament(src: Tournament, organizer: User, starts_on: date, series_id: int | None = None) -> Tournament:
    """Lo stesso torneo in un'altra data: impostazioni sì, iscritti e round no."""
    return Tournament(
        organizer_id=organizer.id,
        organization_id=src.organization_id,
        event_type=src.event_type,
        team_size=src.team_size,
        series_id=series_id,
        starts_on=starts_on,
        name=src.name,
        format=src.format,
        game=src.game,
        best_of=src.best_of,
        allow_intentional_draws=src.allow_intentional_draws,
        rules_enforcement_level=src.rules_enforcement_level,
        venue=src.venue,
        location_id=src.location_id,
        start_time=src.start_time,
        capacity=src.capacity,
        entry_fee_cents=src.entry_fee_cents,
        currency=src.currency,
        status=TournamentStatus.PUBLISHED,
        structure=src.structure,
        swiss_rounds=src.swiss_rounds,
        top_cut_size=src.top_cut_size,
        decklist_required=src.decklist_required,
        check_in_required=src.check_in_required,
        self_check_in_enabled=src.self_check_in_enabled,
        late_registration_enabled=src.late_registration_enabled,
        registration_mode=src.registration_mode,
        pairings_public=src.pairings_public,
        standings_public=src.standings_public,
        decklists_public=src.decklists_public,
        round_timer_minutes=src.round_timer_minutes,
        refund_policy=src.refund_policy,
        invite_code_required=src.invite_code_required,
        email_notifications_enabled=src.email_notifications_enabled,
        legal_validation_enabled=src.legal_validation_enabled,
        description=src.description,
        season_id=src.season_id,
        invites=src.invites,      # l'ID evento no: ogni data ha il suo
        is_online=src.is_online,
        online_platform=src.online_platform,
        online_link=src.online_link,
        pay_at_event=src.pay_at_event,
        pay_stripe=src.pay_stripe,
        pay_paypal=src.pay_paypal,
    )


# Una serie si crea al massimo un anno avanti: oltre, è più facile ripeterla dopo.
SERIES_LIMIT = 52


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """L'n-esimo giorno della settimana del mese; nth=-1 è l'ultimo."""
    if nth == -1:
        last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def series_dates(start: date, frequency: str, count: int | None = None, until: date | None = None) -> list[date]:
    """Le date dopo `start`: ogni settimana, ogni due, o ogni mese nello stesso
    giorno della settimana. Il secondo venerdì resta il secondo venerdì; il
    quinto diventa l'ultimo, perché non tutti i mesi ce l'hanno."""
    limit = min(count or SERIES_LIMIT, SERIES_LIMIT)
    nth = (start.day - 1) // 7 + 1
    out: list[date] = []
    step = 1
    while len(out) < limit:
        if frequency == "monthly":
            month_index = start.month - 1 + step
            day = _nth_weekday(start.year + month_index // 12, month_index % 12 + 1,
                               start.weekday(), -1 if nth == 5 else nth)
        else:
            day = start + timedelta(weeks=step * (2 if frequency == "biweekly" else 1))
        if until and day > until:
            break
        out.append(day)
        step += 1
    return out


def _repeat_plan(src: Tournament, payload: RepeatIn, db: Session) -> tuple[list[date], list[date]]:
    """Le date da creare e quelle in cui la serie ha già un torneo."""
    dates = series_dates(src.starts_on, payload.frequency, payload.count, payload.until)
    taken: set[date] = set()
    if src.series_id:
        taken = set(db.scalars(select(Tournament.starts_on).where(
            Tournament.series_id == src.series_id, Tournament.status != TournamentStatus.CANCELLED,
        )).all())
    return [d for d in dates if d not in taken], [d for d in dates if d in taken]


@router.post("/{tournament_id}/repeat/preview", response_model=RepeatPreviewOut)
def preview_repeat(
    tournament_id: int,
    payload: RepeatIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RepeatPreviewOut:
    """Le date che «Ripeti» creerebbe, per vederle prima di confermare."""
    src = load_owned_tournament(tournament_id, organizer, db)
    new, taken = _repeat_plan(src, payload, db)
    return RepeatPreviewOut(dates=new, already_there=taken)


@router.post("/{tournament_id}/repeat", response_model=list[TournamentOut], status_code=201)
def repeat_tournament(
    tournament_id: int,
    payload: RepeatIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[TournamentOut]:
    """Ripete il torneo: ogni copia ha le stesse impostazioni, la sua data e
    nessun iscritto. Stanno tutte nella stessa serie, per modificarle insieme."""
    from backend.app.core.cache import cache_invalidate

    src = load_owned_tournament(tournament_id, organizer, db)
    new_dates, _ = _repeat_plan(src, payload, db)
    if not new_dates:
        raise HTTPException(status_code=422, detail="Nessuna data nuova da creare")
    if src.series_id is None:
        series = TournamentSeries(name=src.name, frequency=payload.frequency,
                                  organizer_id=src.organizer_id, organization_id=src.organization_id)
        db.add(series)
        db.flush()
        src.series_id = series.id
    copies = [_copy_tournament(src, organizer, day, src.series_id) for day in new_dates]
    db.add_all(copies)
    db.commit()
    cache_invalidate("tournaments:")
    return [tournament_out(copy, 0, db) for copy in copies]


@router.post("/{tournament_id}/duplicate", response_model=TournamentOut, status_code=201)
def duplicate_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    """Duplica un torneo (stesse impostazioni, data +7 giorni, senza iscritti né round).
    Utile per gli eventi ricorrenti (es. FNM ogni venerdì)."""
    src = load_owned_tournament(tournament_id, organizer, db)
    copy = _copy_tournament(src, organizer, src.starts_on + timedelta(days=7))
    db.add(copy)
    db.commit()
    db.refresh(copy)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate("tournaments:")
    return tournament_out(copy, 0, db)


@router.post("", response_model=TournamentOut, status_code=201)
def create_tournament(
    payload: TournamentCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    check_location(payload.location_id, organizer, db)
    tournament = Tournament(
        **payload.model_dump(),
        organizer_id=organizer.id,
        organization_id=organizer.organization_id,
    )
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate("tournaments:")
    return tournament_out(tournament, 0, db)


@router.get("/{tournament_id}", response_model=TournamentOut)
def get_tournament(tournament_id: int, db: Session = Depends(get_db)) -> TournamentOut:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    count = db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament.id))
    return tournament_out(tournament, count or 0, db)


@router.post("/{tournament_id}/start", response_model=RoundOut)
def start_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.structure == TournamentStructure.REGISTRATION_ONLY:
        raise HTTPException(status_code=409, detail=NO_ROUNDS)
    if tournament.status not in {TournamentStatus.PUBLISHED, TournamentStatus.DRAFT}:
        raise HTTPException(status_code=409, detail="Tournament is already started or closed")
    if len(eligible_registrations(tournament, db)) < 2:
        raise HTTPException(status_code=409, detail="At least two eligible players are required")
    tournament.status = TournamentStatus.RUNNING
    db.add(tournament)
    result = create_round_for_tournament(tournament, db)
    # Notifica email giocatori idonei
    try:
        from backend.app.services.notifications import notify_tournament_started
        notify_tournament_started(tournament, eligible_registrations(tournament, db))
    except Exception:
        pass
    return result


@router.post("/{tournament_id}/close", response_model=TournamentOut)
def close_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status == TournamentStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Cancelled tournaments cannot be closed")
    tournament.status = TournamentStatus.COMPLETED
    db.add(tournament)
    # Ferma i timer di tutti i round alla chiusura del torneo.
    for rnd in db.scalars(select(Round).where(Round.tournament_id == tournament_id)).all():
        rnd.ends_at = None
        db.add(rnd)
    db.commit()
    db.refresh(tournament)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    count = db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament.id))
    return tournament_out(tournament, count or 0, db)


# Una volta avviato il torneo questi non cambiano più: rifarebbero abbinamenti,
# spareggi o pagamenti già fatti. Nome, descrizione, luogo e timer restano liberi.
LOCKED_AFTER_START = frozenset({
    "game", "format", "best_of", "starts_on", "start_time", "capacity", "entry_fee_cents",
    "pay_at_event", "pay_stripe", "pay_paypal", "structure", "swiss_rounds", "top_cut_size",
    "decklist_required", "check_in_required", "team_size", "is_online",
})


SERIES_OWN_FIELDS = frozenset({"starts_on"})   # ogni torneo della serie ha la sua data


def _apply_settings(tournament: Tournament, requested: dict, organizer: User, db: Session) -> dict:
    """Valida e applica le modifiche; ritorna quelle vere, già scritte nel
    registro. Ogni controllo viene prima di toccare il torneo: se uno fallisce,
    il torneo resta com'era."""
    from backend.app.games import GAMES

    changes = {
        key: value for key, value in requested.items()
        # null vuol dire "non toccare", tranne per l'orario, che si può togliere
        if (value is not None or key == "start_time") and getattr(tournament, key) != value
    }
    if not changes:
        return changes

    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        locked = sorted(set(changes) & LOCKED_AFTER_START)
        if locked:
            raise HTTPException(status_code=409, detail=f"A torneo avviato non si cambiano: {', '.join(locked)}")

    if "location_id" in changes:
        if changes["location_id"] == 0:
            changes["location_id"] = None
            if tournament.location_id is None:
                changes.pop("location_id")
        else:
            check_location(changes["location_id"], organizer, db)

    if "game" in changes:
        if not is_enabled(changes["game"]):
            raise HTTPException(status_code=422, detail=f"Gioco non disponibile: {changes['game']}")
        # Cambiando gioco si riparte dal suo formato dei match, se non se ne sceglie un altro.
        changes.setdefault("best_of", GAMES[changes["game"]].default_best_of)

    if {"is_online", "online_platform", "game"} & set(changes):
        if changes.get("is_online", tournament.is_online):
            game = changes.get("game", tournament.game)
            if not online_platform(game, changes.get("online_platform", tournament.online_platform)):
                raise HTTPException(status_code=422, detail="Scegli dove si gioca il torneo online")
        else:
            # Tornato al negozio: piattaforma e link non servono più.
            changes.update({key: "" for key in ("online_platform", "online_link") if getattr(tournament, key)})

    if changes.get("team_size", tournament.team_size) > 1 and changes.get("structure", tournament.structure) != "swiss":
        raise HTTPException(status_code=422, detail="I tornei a squadre si giocano in svizzera")

    payments = {key: changes.get(key, getattr(tournament, key)) for key in ("pay_at_event", "pay_stripe", "pay_paypal")}
    if not any(payments.values()):
        raise HTTPException(status_code=422, detail="Serve almeno un metodo di pagamento (al banco, Stripe o PayPal)")

    if "capacity" in changes:
        active = db.scalar(
            select(func.count(Registration.id)).where(
                Registration.tournament_id == tournament.id,
                Registration.waitlisted.is_(False),
                Registration.dropped.is_(False),
            )
        ) or 0
        if changes["capacity"] < active:
            raise HTTPException(status_code=409, detail=f"Ci sono già {active} iscritti: la capienza non può scendere sotto")

    if "entry_fee_cents" in changes:
        already_paid = db.scalar(
            select(func.count(Payment.id))
            .join(Registration, Registration.id == Payment.registration_id)
            .where(Registration.tournament_id == tournament.id, Payment.status == PaymentStatus.PAID,
                   Payment.amount_cents > 0)
        ) or 0
        if already_paid:
            raise HTTPException(status_code=409, detail="Qualcuno ha già pagato: la quota non si cambia più")

    if not changes:
        return changes
    detail = "; ".join(f"{key}: {getattr(tournament, key)!s} → {value!s}" for key, value in changes.items())
    for key, value in changes.items():
        setattr(tournament, key, value)
    _write_audit(db, tournament.id, organizer.id, "tournament_updated", detail[:1000])
    return changes


def _following_in_series(tournament: Tournament, db: Session) -> list[Tournament]:
    """I tornei della serie dopo questo, finché non sono iniziati."""
    return list(db.scalars(
        select(Tournament).where(
            Tournament.series_id == tournament.series_id,
            Tournament.id != tournament.id,
            Tournament.starts_on > tournament.starts_on,
            Tournament.status.in_([TournamentStatus.DRAFT, TournamentStatus.PUBLISHED]),
        ).order_by(Tournament.starts_on)
    ).all())


@router.patch("/{tournament_id}", response_model=TournamentOut)
def update_tournament(
    tournament_id: int,
    payload: TournamentUpdate,
    series: bool = False,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    """Modifica le impostazioni del torneo. Ogni cambio finisce nel registro.

    Con ?series=true le stesse modifiche vanno anche ai tornei successivi della
    serie non ancora iniziati. La data resta la loro; chi non può prenderle
    (capienza sotto gli iscritti, quota già pagata) resta com'era e viene elencato."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    changes = _apply_settings(tournament, payload.model_dump(exclude_unset=True), organizer, db)
    touched = [tournament] if changes else []
    updated: int | None = None
    skipped: list[str] = []
    if series and tournament.series_id and changes:
        # Solo quello che è cambiato qui: il form manda tutti i campi, e gli
        # altri tornei della serie possono avere le loro differenze.
        wanted = {key: (0 if key == "location_id" and value is None else value)
                  for key, value in changes.items() if key not in SERIES_OWN_FIELDS}
        updated = 0
        for other in _following_in_series(tournament, db):
            if not owns_tournament(other, organizer, db):
                continue
            try:
                if _apply_settings(other, wanted, organizer, db):
                    updated += 1
                    touched.append(other)
            except HTTPException as exc:
                skipped.append(f"{other.starts_on:%d/%m}: {exc.detail}")
    if touched:
        db.commit()
        for changed in touched:
            if "capacity" in changes:
                promote_from_waitlist(changed, db)   # più posti: chi aspettava entra
            cache_invalidate(f"public-display:{changed.id}")
            cache_invalidate(f"registrations:{changed.id}")
        cache_invalidate("tournaments")
        db.refresh(tournament)
    return tournament_out(tournament, _registered_count(tournament.id, db), db).model_copy(
        update={"series_updated": updated, "series_skipped": skipped}
    )


def _registered_count(tournament_id: int, db: Session) -> int:
    return db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament_id)) or 0


@router.delete("/{tournament_id}", status_code=204)
def delete_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    # Un torneo concluso è parte dello storico: non può essere eliminato.
    if tournament.status == TournamentStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="I tornei conclusi non possono essere eliminati (storico)")
    round_ids = db.scalars(select(Round.id).where(Round.tournament_id == tournament.id)).all()
    if round_ids:
        db.execute(delete(PairingResultReport).where(PairingResultReport.pairing_id.in_(select(Pairing.id).where(Pairing.round_id.in_(round_ids)))))
        db.execute(delete(Pairing).where(Pairing.round_id.in_(round_ids)))
    registration_ids = db.scalars(
        select(Registration.id).where(Registration.tournament_id == tournament.id)
    ).all()
    if registration_ids:
        db.execute(delete(Penalty).where(Penalty.registration_id.in_(registration_ids)))
        db.execute(delete(DecklistRevision).where(DecklistRevision.registration_id.in_(registration_ids)))
        db.execute(delete(Decklist).where(Decklist.registration_id.in_(registration_ids)))
        db.execute(delete(Payment).where(Payment.registration_id.in_(registration_ids)))
        db.execute(delete(Registration).where(Registration.id.in_(registration_ids)))
    db.execute(delete(Announcement).where(Announcement.tournament_id == tournament.id))
    db.execute(delete(InviteCode).where(InviteCode.tournament_id == tournament.id))
    db.execute(delete(Round).where(Round.tournament_id == tournament.id))
    db.delete(tournament)
    db.commit()


def check_game_handle(tournament: Tournament, handle: str) -> str:
    """Il nome in gioco, come lo vuole la piattaforma del torneo online."""
    platform = online_platform(tournament.game, tournament.online_platform)
    handle = handle.strip()
    if not platform:
        return handle
    if not handle:
        raise HTTPException(status_code=422, detail=f"Per giocare online serve il tuo {platform.handle_label}.")
    if platform.handle_pattern and not re.fullmatch(platform.handle_pattern, handle):
        raise HTTPException(
            status_code=422,
            detail=f"{platform.handle_label} non valido: si scrive come {platform.handle_hint}.",
        )
    return handle


@router.put("/{tournament_id}/my-publisher-id", response_model=RegistrationOut)
def update_my_publisher_id(
    tournament_id: int,
    payload: PublisherIdIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    """Il giocatore aggiunge o corregge il suo ID presso l'editore: anche a torneo
    concluso, perché è lì che arriva l'invito."""
    registration = db.scalar(select(Registration).where(
        Registration.tournament_id == tournament_id, Registration.player_id == user.id))
    if not registration or registration.tournament.status == TournamentStatus.CANCELLED:
        raise HTTPException(status_code=404, detail="Registration not found")
    registration.wizards_account = payload.publisher_id.strip()
    db.commit()
    db.refresh(registration)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    return registration_out(registration)


@router.put("/{tournament_id}/my-handle", response_model=RegistrationOut)
def update_my_handle(
    tournament_id: int,
    payload: GameHandleIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    """Il giocatore corregge il suo nome in gioco finché il torneo non è concluso."""
    registration = db.scalar(select(Registration).where(
        Registration.tournament_id == tournament_id, Registration.player_id == user.id))
    if not registration or not registration.tournament.is_online:
        raise HTTPException(status_code=404, detail="Registration not found")
    if registration.tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Il torneo è concluso")
    registration.game_handle = check_game_handle(registration.tournament, payload.game_handle)
    db.commit()
    db.refresh(registration)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    return registration_out(registration)


@router.post("/{tournament_id}/registrations", response_model=RegistrationOut, status_code=201)
def register_for_tournament(
    tournament_id: int,
    payload: RegistrationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.status not in {
        TournamentStatus.PUBLISHED,
        TournamentStatus.RUNNING,
    }:
        raise HTTPException(status_code=404, detail="Tournament not available")
    if tournament.registration_mode != RegistrationMode.OPEN:
        raise HTTPException(status_code=409, detail="Registration is not open")
    if tournament.status == TournamentStatus.RUNNING and not tournament.late_registration_enabled:
        raise HTTPException(status_code=409, detail="Late registration is disabled")
    registered = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament_id,
            Registration.waitlisted == False,  # noqa: E712
        )
    )
    is_full = bool(registered and registered >= tournament.capacity)
    existing = db.scalar(
        select(Registration).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already registered")
    check_not_suspended(user, tournament, db)
    answers = validate_answers(tournament.id, payload.answers, db)
    handle = check_game_handle(tournament, payload.game_handle) if tournament.is_online else ""
    # Torneo pieno → lista d'attesa invece di rifiuto
    registration = Registration(
        tournament_id=tournament_id,
        player_id=user.id,
        wizards_account=payload.wizards_account,
        game_handle=handle,
        waitlisted=is_full,
    )
    db.add(registration)
    db.flush()
    save_answers(registration.id, answers, db)
    db.commit()
    db.refresh(registration)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate("tournaments:")               # il count cambia
    cache_invalidate(f"registrations:{tournament_id}")  # lista iscritti cambia
    # Notifica email
    try:
        from backend.app.services.notifications import notify_registration_confirmed
        notify_registration_confirmed(registration)
    except Exception:
        pass
    return registration_out(registration)


@router.get("/{tournament_id}/registrations", response_model=list[OrganizerRegistrationOut])
def list_registrations(
    tournament_id: int,
    page: int = 1,
    page_size: int = 100,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[OrganizerRegistrationOut]:
    """Lista iscritti con paginazione (default 100/pagina).
    Usa ?page=2 per la pagina successiva, ?page_size=50 per ridurre il carico.
    """
    from backend.app.core.cache import cache_get, cache_set
    tournament = db.get(Tournament, tournament_id)
    if not tournament or not owns_tournament(tournament, organizer, db):
        raise HTTPException(status_code=404, detail="Tournament not found")

    page = max(1, page)
    page_size = max(1, min(page_size, 200))   # max 200/pagina
    offset = (page - 1) * page_size

    cache_key = f"registrations:{tournament_id}:p{page}:s{page_size}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .order_by(Registration.id)
        .offset(offset)
        .limit(page_size)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklists),
            selectinload(Registration.payment),
            selectinload(Registration.decklist_revisions),  # conta revisioni senza N+1
        )
    ).all()
    from backend.app.routers.tags import tags_for_users

    player_tags = tags_for_users(
        [r.player_id for r in registrations], organizer.organization_id or 0, db
    )
    answers = answers_for([item.id for item in registrations], db)
    prior = prior_penalty_counts(tournament_id, [item.player_id for item in registrations], db)
    result = [organizer_registration_out(item, player_tags, answers, prior) for item in registrations]
    cache_set(cache_key, result, ttl=8.0)
    return result


@router.get("/{tournament_id}/my-registration", response_model=RegistrationOut)
def my_registration(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    from backend.app.core.cache import cache_get, cache_set
    cache_key = f"my-reg:{tournament_id}:{user.id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    # joinedload per query singola: 1 query con JOIN invece di 3+1 selectinload
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(
            joinedload(Registration.player),
            joinedload(Registration.decklists),
            joinedload(Registration.payment),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    result = registration_out(registration)
    cache_set(cache_key, result, ttl=10.0)
    return result


@router.patch("/{tournament_id}/self-check-in", response_model=RegistrationOut)
def self_check_in(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(
            joinedload(Registration.player),
            joinedload(Registration.decklists),
            joinedload(Registration.payment),
            joinedload(Registration.tournament),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    if not registration.tournament.self_check_in_enabled:
        raise HTTPException(status_code=409, detail="Self check-in is disabled")
    if registration.tournament.status not in {TournamentStatus.PUBLISHED, TournamentStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="Check-in is closed")
    registration.checked_in = True
    db.commit()
    db.refresh(registration)
    return registration_out(registration)


def promote_from_waitlist(tournament: Tournament, db: Session) -> None:
    """Promuove il primo in lista d'attesa se si è liberato un posto."""
    active = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament.id,
            Registration.waitlisted == False,  # noqa: E712
            Registration.dropped == False,     # noqa: E712
        )
    )
    if active and active >= tournament.capacity:
        return
    next_in_line = db.scalar(
        select(Registration)
        .where(
            Registration.tournament_id == tournament.id,
            Registration.waitlisted == True,  # noqa: E712
        )
        .order_by(Registration.created_at, Registration.id)
        .options(joinedload(Registration.player))
    )
    if not next_in_line:
        return
    next_in_line.waitlisted = False
    next_in_line.promoted_at = datetime.now(UTC)   # parte il timer per il pagamento (#32)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament.id}")
    cache_invalidate(f"my-reg:{tournament.id}:{next_in_line.player_id}")
    try:
        send_email(
            next_in_line.player.email,
            f"{tournament.name} — Sei dentro!",
            f"Ciao {next_in_line.player.display_name},\n\n"
            f"si è liberato un posto per \"{tournament.name}\" e sei stato promosso "
            "dalla lista d'attesa. Completa il pagamento per confermare l'iscrizione.",
        )
    except Exception:
        pass


WAITLIST_PAY_HOURS = 6   # ore per pagare dopo la promozione dalla waitlist (#32)


def sweep_waitlist_deadlines(db: Session) -> int:
    """Riaccoda i giocatori promossi dalla waitlist che non hanno pagato entro
    WAITLIST_PAY_HOURS, e promuove il successivo. Ritorna quanti ne ha riaccodati.
    Pensata per essere chiamata periodicamente da un task in background."""
    cutoff = datetime.now(UTC) - timedelta(hours=WAITLIST_PAY_HOURS)
    expired = db.scalars(
        select(Registration)
        .where(
            Registration.waitlisted == False,   # noqa: E712
            Registration.dropped == False,       # noqa: E712
            Registration.promoted_at.is_not(None),
        )
        .options(joinedload(Registration.payment), joinedload(Registration.tournament))
    ).all()
    requeued = 0
    touched_tournaments = set()
    for reg in expired:
        pa = reg.promoted_at
        if pa and pa.tzinfo is None:
            pa = pa.replace(tzinfo=UTC)
        if not pa or pa > cutoff:
            continue
        if reg.payment and reg.payment.status == PaymentStatus.PAID:
            reg.promoted_at = None   # ha pagato: conferma, ferma il timer
            db.add(reg)
            continue
        # Non ha pagato in tempo → torna in coda
        reg.waitlisted = True
        reg.promoted_at = None
        db.add(reg)
        requeued += 1
        touched_tournaments.add(reg.tournament)
    db.commit()
    for t in touched_tournaments:
        if t:
            promote_from_waitlist(t, db)
    return requeued


@router.post("/{tournament_id}/my-registration/drop", response_model=RegistrationOut)
def self_drop(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    """Il giocatore si ritira da solo dal torneo (tra un round e l'altro)."""
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(
            joinedload(Registration.player),
            joinedload(Registration.decklists),
            joinedload(Registration.payment),
            joinedload(Registration.tournament),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    if registration.dropped:
        raise HTTPException(status_code=409, detail="Already dropped")
    tournament = registration.tournament
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Tournament is closed")
    # Drop consentito solo tra i round: blocca se ha una partita in corso senza risultato
    open_pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(
            Round.tournament_id == tournament_id,
            Round.number == select(func.max(Round.number))
                .where(Round.tournament_id == tournament_id)
                .scalar_subquery(),
            Pairing.result == "",
            (Pairing.player_a_registration_id == registration.id)
            | (Pairing.player_b_registration_id == registration.id),
        )
    )
    if open_pairing:
        raise HTTPException(
            status_code=409,
            detail="Completa o fai refertare la partita in corso prima di ritirarti",
        )
    was_waitlisted = registration.waitlisted
    registration.dropped = True
    db.commit()
    db.refresh(registration)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    cache_invalidate(f"my-reg:{tournament_id}:{user.id}")
    # Il drop di un iscritto attivo libera un posto per la waitlist
    if not was_waitlisted:
        promote_from_waitlist(tournament, db)
    return registration_out(registration)


CANCEL_REFUND_HOURS = 24   # rimborso automatico se l'annullamento è > 24h prima dell'inizio


@router.post("/{tournament_id}/my-registration/cancel")
def cancel_registration(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Il giocatore annulla l'iscrizione PRIMA dell'inizio. Se aveva pagato e mancano
    più di 24h all'inizio, il pagamento viene rimborsato automaticamente."""
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(joinedload(Registration.tournament), joinedload(Registration.payment))
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    tournament = registration.tournament
    if tournament.status != TournamentStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="Annullabile solo prima dell'inizio del torneo")

    refunded = False
    payment = registration.payment
    if payment and payment.status == PaymentStatus.PAID:
        # Calcola le ore mancanti all'inizio (se c'è un orario).
        start_dt = tournament.starts_at
        within_policy = start_dt is None or datetime.now(UTC) <= start_dt - timedelta(hours=CANCEL_REFUND_HOURS)
        if within_policy:
            payment.status = PaymentStatus.REFUNDED
            payment.refund_reason = "Annullamento self-service"
            payment.refund_requested_at = datetime.now(UTC)
            db.add(payment)
            refunded = True

    # Niente hard-delete (le relazioni non hanno cascade: lascerebbe pagamento/lista
    # orfani con FK NOT NULL). Marca come ritirato e libera il posto, come il drop.
    was_active = not registration.waitlisted and not registration.dropped
    registration.dropped = True
    registration.waitlisted = False
    db.add(registration)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    cache_invalidate(f"my-reg:{tournament_id}:{user.id}")
    if was_active:
        promote_from_waitlist(tournament, db)
    return {"status": "cancelled", "refunded": refunded}


@router.get("/{tournament_id}/player-card/{registration_id}", response_model=PlayerCardOut)
def player_card(
    tournament_id: int,
    registration_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> PlayerCardOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    registration = load_registration_for_tournament(tournament.id, registration_id, db)
    pairings = db.scalars(
        select(Pairing)
        .join(Round)
        .where(
            Round.tournament_id == tournament.id,
            (Pairing.player_a_registration_id == registration.id)
            | (Pairing.player_b_registration_id == registration.id),
        )
        .options(
            selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Pairing.player_b).selectinload(Registration.player),
        )
    ).all()
    penalties = db.scalars(
        select(Penalty).where(Penalty.tournament_id == tournament.id, Penalty.registration_id == registration.id)
    ).all()
    return PlayerCardOut(
        registration=registration_out(registration),
        payment=PaymentOut.model_validate(registration.payment) if registration.payment else None,
        decklist=DecklistOut.model_validate(registration.decklist) if registration.decklist else None,
        pairings=[
            PairingOut(
                id=pairing.id,
                table_number=pairing.table_number,
                player_a=pairing.player_a.player.display_name,
                player_a_registration_id=pairing.player_a_registration_id,
                player_b=pairing.player_b.player.display_name if pairing.player_b else None,
                player_b_registration_id=pairing.player_b_registration_id,
                result=pairing.result,
                match_wins_a=pairing.match_wins_a,
                match_wins_b=pairing.match_wins_b,
                draws=pairing.draws,
            )
            for pairing in pairings
        ],
        penalties=[PenaltyOut.model_validate(penalty) for penalty in penalties],
    )


def resolve_audience(
    tournament_id: int, tag_ids: list[int], organizer: User, db: Session
) -> tuple[list[User], str]:
    """Gli iscritti a cui va un annuncio, piu l'etichetta da mostrare.

    Senza tag sono tutti: e il caso normale e non produce righe di destinatario.
    Con dei tag e chi ne porta almeno uno — un'unione, non un'intersezione: "Nuovi"
    e "Commander" insieme vogliono dire entrambi i gruppi, non chi sta in tutti e due.
    """
    from backend.app.routers.tags import org_id_for

    base = (
        select(User)
        .join(Registration, Registration.player_id == User.id)
        .where(Registration.tournament_id == tournament_id)
    )
    if not tag_ids:
        return list(db.scalars(base).all()), ""

    # I tag di un altro negozio non si possono usare: sono suoi clienti, non nostri.
    tags = db.scalars(
        select(PlayerTag).where(
            PlayerTag.id.in_(tag_ids),
            PlayerTag.organization_id == org_id_for(organizer, db),
        )
    ).all()
    if len(tags) != len(set(tag_ids)):
        raise HTTPException(status_code=404, detail="Tag non trovato")

    recipients = db.scalars(
        base.join(PlayerTagAssignment, PlayerTagAssignment.user_id == User.id)
        .where(PlayerTagAssignment.tag_id.in_([tag.id for tag in tags]))
        .distinct()
    ).all()
    return list(recipients), ", ".join(sorted(tag.name for tag in tags))


@router.get("/{tournament_id}/announcements/audience", response_model=AnnouncementAudienceOut)
def preview_audience(
    tournament_id: int,
    tag_ids: Annotated[list[int], Query()] = [],  # noqa: B006 — FastAPI vuole il default qui
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> AnnouncementAudienceOut:
    """Cosa succedera inviando: quanti lo leggono e se l'email parte davvero."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    recipients, label = resolve_audience(tournament_id, list(tag_ids), organizer, db)
    total = db.scalar(
        select(func.count(Registration.id)).where(Registration.tournament_id == tournament_id)
    ) or 0
    if not get_settings().smtp_host:
        email_status = "no_smtp"
    elif not tournament.email_notifications_enabled:
        email_status = "tournament_off"
    else:
        email_status = "ok"
    return AnnouncementAudienceOut(
        recipients=len(recipients), total=total, label=label, email_status=email_status
    )


@router.post("/{tournament_id}/announcements", response_model=AnnouncementOut, status_code=201)
def create_announcement(
    tournament_id: int,
    payload: AnnouncementCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Announcement:
    load_owned_tournament(tournament_id, organizer, db)
    recipients, label = resolve_audience(tournament_id, payload.tag_ids, organizer, db)
    announcement = Announcement(
        tournament_id=tournament_id,
        author_id=organizer.id,
        title=payload.title,
        body=payload.body,
        send_email=payload.send_email,
        targeted=bool(payload.tag_ids),
        audience=label,
    )
    db.add(announcement)
    db.flush()
    if payload.tag_ids:
        # Solo per gli annunci mirati: senza righe l'annuncio resta di tutti,
        # compreso chi si iscrive domani.
        db.add_all(
            AnnouncementRecipient(announcement_id=announcement.id, user_id=user.id)
            for user in recipients
        )
    db.commit()
    db.refresh(announcement)
    tournament = db.get(Tournament, tournament_id)
    if payload.send_email and tournament and tournament.email_notifications_enabled:
        for user in recipients:
            send_email(
                user.email,
                f"{tournament.name}: {payload.title}",
                payload.body,
                event_announcement_html(tournament.name, payload.title, payload.body),
            )
    # Notifica Web Push (no-op se VAPID non configurato)
    if tournament:
        from backend.app.services.notifications import push_to_tournament

        push_to_tournament(
            db,
            tournament_id,
            f"{tournament.name}: {payload.title}",
            payload.body,
            user_ids=[user.id for user in recipients] if payload.tag_ids else None,
        )
    return announcement


@router.get("/{tournament_id}/announcements", response_model=list[AnnouncementOut])
def list_announcements(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Announcement]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    is_registered = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    is_staff = owns_tournament(tournament, user, db) or is_tournament_staff(tournament_id, user.id, db)
    if not is_staff and not is_registered:
        raise HTTPException(status_code=403, detail="Tournament access required")
    stmt = select(Announcement).where(Announcement.tournament_id == tournament_id)
    if not is_staff:
        # Un annuncio mirato lo legge solo chi era fra i destinatari: filtrarlo
        # sull'invio e lasciarlo poi in pagina per tutti non lo renderebbe mirato.
        miei = select(AnnouncementRecipient.announcement_id).where(
            AnnouncementRecipient.user_id == user.id
        )
        stmt = stmt.where(Announcement.targeted.is_(False) | Announcement.id.in_(miei))
    return db.scalars(stmt.order_by(Announcement.created_at.desc())).all()


@router.post("/{tournament_id}/penalties", response_model=PenaltyOut, status_code=201)
def create_penalty(
    tournament_id: int,
    payload: PenaltyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Penalty:
    # Organizzatore proprietario o staff/judge invitato
    tournament = load_tournament_for_staff(tournament_id, user, db)
    load_registration_for_tournament(tournament.id, payload.registration_id, db)
    penalty = Penalty(
        tournament_id=tournament.id,
        registration_id=payload.registration_id,
        judge_id=user.id,
        round_id=payload.round_id,
        kind=payload.kind,
        note=payload.note,
        is_private=payload.is_private,
    )
    db.add(penalty)
    db.commit()
    db.refresh(penalty)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate("registrations:")   # "precedenti" nelle liste degli altri tornei
    return penalty


def _prior_penalties(player_ids: list[int], tournament_id: int):
    """Le penalità degli stessi giocatori negli altri tornei. Le note restano del
    torneo che le ha scritte: sono appunti dello staff, non penalità."""
    return (
        select(Penalty, Registration.player_id)
        .join(Registration, Registration.id == Penalty.registration_id)
        .where(Registration.player_id.in_(player_ids), Penalty.tournament_id != tournament_id, Penalty.kind != "note")
    )


def prior_penalty_counts(tournament_id: int, player_ids: list[int], db: Session) -> dict[int, int]:
    if not player_ids:
        return {}
    counts: dict[int, int] = {}
    for _, player_id in db.execute(_prior_penalties(player_ids, tournament_id)).all():
        counts[player_id] = counts.get(player_id, 0) + 1
    return counts


@router.get("/{tournament_id}/registrations/{registration_id}/penalty-history", response_model=list[PenaltyHistoryOut])
def penalty_history(
    tournament_id: int,
    registration_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PenaltyHistoryOut]:
    """Le penalità del giocatore negli altri tornei, dalla più recente: le vede
    lo staff del torneo in cui gioca ora, per capire se è recidivo."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    registration = load_registration_for_tournament(tournament.id, registration_id, db)
    rows = db.execute(_prior_penalties([registration.player_id], tournament.id)).all()
    out = []
    for penalty, _ in rows:
        other = db.get(Tournament, penalty.tournament_id)
        store = db.get(Organization, other.organization_id) if other and other.organization_id else None
        out.append(PenaltyHistoryOut(
            tournament_id=penalty.tournament_id, tournament_name=other.name if other else "—",
            starts_on=other.starts_on if other else penalty.created_at.date(),
            store_name=store.name if store else None,
            round_number=penalty.round.number if penalty.round else None,
            kind=penalty.kind, note=penalty.note or "",
            judge_name=penalty.judge.display_name if penalty.judge else None,
            created_at=penalty.created_at,
        ))
    return sorted(out, key=lambda p: p.created_at, reverse=True)


@router.get("/{tournament_id}/penalties", response_model=list[PenaltyOut])
def list_penalties(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Penalty]:
    # Un judge deve poter rileggere i warning che ha dato lui e quelli dei colleghi,
    # altrimenti non sa se il giocatore è recidivo.
    tournament = load_tournament_for_staff(tournament_id, user, db)
    return db.scalars(select(Penalty).where(Penalty.tournament_id == tournament.id)).all()


@router.post("/{tournament_id}/invite-codes", response_model=InviteCodeOut, status_code=201)
def create_invite_code(
    tournament_id: int,
    payload: InviteCodeCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> InviteCode:
    load_owned_tournament(tournament_id, organizer, db)
    invite = InviteCode(tournament_id=tournament_id, code=payload.code.strip(), max_uses=payload.max_uses)
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/{tournament_id}/invite-codes", response_model=list[InviteCodeOut])
def list_invite_codes(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[InviteCode]:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    return db.scalars(select(InviteCode).where(InviteCode.tournament_id == tournament.id)).all()


@router.patch("/{tournament_id}/registrations/{registration_id}/check-in", response_model=OrganizerRegistrationOut)
def set_check_in(
    tournament_id: int,
    registration_id: int,
    checked_in: bool,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Closed tournaments cannot be edited")
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    registration.checked_in = checked_in
    db.commit()
    db.refresh(registration)
    return organizer_registration_out(registration)


@router.patch("/{tournament_id}/registrations/{registration_id}/drop", response_model=OrganizerRegistrationOut)
def set_drop(
    tournament_id: int,
    registration_id: int,
    dropped: bool,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    registration.dropped = dropped
    db.commit()
    db.refresh(registration)
    if dropped and not registration.waitlisted:
        promote_from_waitlist(tournament, db)
    return organizer_registration_out(registration)


@router.post("/{tournament_id}/drop-unpaid", response_model=DropUnpaidOut)
def drop_unpaid(
    tournament_id: int,
    dry_run: bool = True,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> DropUnpaidOut:
    """Prima dell'inizio, toglie chi occupa un posto senza aver pagato: i posti
    tornano liberi e salgono quelli in lista d'attesa. Con dry_run dice solo chi."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Solo prima dell'inizio del torneo")
    if not tournament.entry_fee_cents:
        raise HTTPException(status_code=409, detail="Il torneo è gratuito: non c'è niente da pagare")
    unpaid = [
        registration for registration in db.scalars(
            select(Registration).where(
                Registration.tournament_id == tournament.id,
                Registration.waitlisted.is_(False),
                Registration.dropped.is_(False),
            ).options(joinedload(Registration.player), joinedload(Registration.payment))
        ).unique().all()
        if not registration.payment or registration.payment.status != PaymentStatus.PAID
    ]
    names = sorted(r.player.display_name for r in unpaid)
    if dry_run or not unpaid:
        return DropUnpaidOut(dropped=names)
    for registration in unpaid:
        registration.dropped = True
    _write_audit(db, tournament.id, organizer.id, "unpaid_dropped", ", ".join(names)[:1000])
    db.commit()

    def waiting() -> int:
        return db.scalar(select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament.id, Registration.waitlisted.is_(True),
        )) or 0

    before = waiting()
    for _ in range(min(len(unpaid), before)):
        promote_from_waitlist(tournament, db)   # uno per posto liberato
    cache_invalidate(f"registrations:{tournament.id}")
    cache_invalidate("tournaments:")
    return DropUnpaidOut(dropped=names, promoted=before - waiting())


@router.put("/{tournament_id}/registrations/{registration_id}/fixed-table", response_model=OrganizerRegistrationOut)
def set_fixed_table(
    tournament_id: int,
    registration_id: int,
    payload: FixedTableIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    """Un tavolo fisso per chi ne ha bisogno (una sedia a rotelle, un tavolo
    vicino all'uscita): dal turno dopo i suoi match si giocano lì."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_tournament_for_staff(tournament_id, user, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    registration.fixed_table = payload.table
    _write_audit(db, tournament.id, user.id, "fixed_table",
                 f"{registration.player.display_name}: " + (f"tavolo {payload.table}" if payload.table else "nessun tavolo fisso"))
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    return organizer_registration_out(load_registration_for_tournament(tournament_id, registration_id, db))


# ── Squadre ──────────────────────────────────────────────────


def _teams_of(tournament: Tournament, db: Session) -> list[TeamOut]:
    members: dict[int, list[TeamMemberOut]] = {}
    for reg in db.scalars(
        select(Registration).where(Registration.tournament_id == tournament.id, Registration.team_id.is_not(None))
        .options(selectinload(Registration.player))
    ):
        members.setdefault(reg.team_id, []).append(
            TeamMemberOut(registration_id=reg.id, name=reg.player.display_name, seat=reg.team_seat or 0))
    return [
        TeamOut(id=team.id, name=team.name, members=sorted(members.get(team.id, []), key=lambda m: m.seat),
                complete=len(members.get(team.id, [])) == tournament.team_size)
        for team in db.scalars(select(Team).where(Team.tournament_id == tournament.id).order_by(Team.name))
    ]


def _team_editable(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if (tournament.team_size or 1) < 2:
        raise HTTPException(status_code=409, detail="Il torneo non è a squadre")
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Le squadre si compongono prima dell'inizio del torneo")
    return tournament


@router.get("/{tournament_id}/teams", response_model=list[TeamOut])
def list_teams(tournament_id: int, db: Session = Depends(get_db)) -> list[TeamOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return _teams_of(tournament, db)


@router.post("/{tournament_id}/teams", response_model=list[TeamOut], status_code=201)
def create_team(
    tournament_id: int, payload: TeamIn,
    organizer: User = Depends(require_organizer), db: Session = Depends(get_db),
) -> list[TeamOut]:
    tournament = _team_editable(tournament_id, organizer, db)
    db.add(Team(tournament_id=tournament.id, name=payload.name.strip()))
    db.commit()
    return _teams_of(tournament, db)


@router.delete("/{tournament_id}/teams/{team_id}", response_model=list[TeamOut])
def delete_team(
    tournament_id: int, team_id: int,
    organizer: User = Depends(require_organizer), db: Session = Depends(get_db),
) -> list[TeamOut]:
    tournament = _team_editable(tournament_id, organizer, db)
    team = db.get(Team, team_id)
    if not team or team.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Squadra non trovata")
    for reg in db.scalars(select(Registration).where(Registration.team_id == team.id)):
        reg.team_id = reg.team_seat = None
    db.delete(team)
    db.commit()
    return _teams_of(tournament, db)


@router.put("/{tournament_id}/teams/{team_id}/seats/{seat}", response_model=list[TeamOut])
def set_team_seat(
    tournament_id: int, team_id: int, seat: int, payload: TeamSeatIn,
    organizer: User = Depends(require_organizer), db: Session = Depends(get_db),
) -> list[TeamOut]:
    """Mette un iscritto a un posto della squadra (o lo libera). Chi era a quel
    posto torna senza squadra; chi è già in un'altra squadra non si sposta da solo."""
    from backend.app.core.cache import cache_invalidate

    tournament = _team_editable(tournament_id, organizer, db)
    team = db.get(Team, team_id)
    if not team or team.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Squadra non trovata")
    if not 1 <= seat <= tournament.team_size:
        raise HTTPException(status_code=422, detail="Posto non valido")
    for reg in db.scalars(select(Registration).where(Registration.team_id == team.id, Registration.team_seat == seat)):
        reg.team_id = reg.team_seat = None
    if payload.registration_id:
        registration = load_registration_for_tournament(tournament.id, payload.registration_id, db)
        if registration.team_id and registration.team_id != team.id:
            raise HTTPException(status_code=409, detail="È già in un'altra squadra")
        registration.team_id, registration.team_seat = team.id, seat
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    return _teams_of(tournament, db)


@router.get("/{tournament_id}/team-standings", response_model=list[TeamStandingOut])
def team_standings(tournament_id: int, db: Session = Depends(get_db)) -> list[dict]:
    from backend.app.services.standings import compute_team_standings

    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    teams = {t.id: t.name for t in db.scalars(select(Team).where(Team.tournament_id == tournament.id))}
    return compute_team_standings(teams, team_matches(tournament.id, db))


def _pods_of(tournament: Tournament, db: Session) -> list[PodOut]:
    regs = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament.id, Registration.pod.is_not(None))
        .options(selectinload(Registration.player))
    ).all()
    pods: dict[int, list[PodSeatOut]] = {}
    for reg in regs:
        pods.setdefault(reg.pod, []).append(PodSeatOut(registration_id=reg.id, name=reg.player.display_name,
                                                       seat=reg.pod_seat or 0))
    return [PodOut(pod=pod, players=sorted(seats, key=lambda s: s.seat)) for pod, seats in sorted(pods.items())]


@router.get("/{tournament_id}/pods", response_model=list[PodOut])
def list_pods(tournament_id: int, db: Session = Depends(get_db)) -> list[PodOut]:
    """I pod con i posti: pubblici, si leggono al tavolo del draft."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return _pods_of(tournament, db)


@router.post("/{tournament_id}/pods", response_model=list[PodOut])
def create_pods(
    tournament_id: int,
    payload: PodsIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[PodOut]:
    """Divide chi gioca in pod di draft il più possibile uguali (18 giocatori in
    pod da 8 fanno tre pod da 6) e assegna i posti a caso. Si rifanno finché il
    torneo non è iniziato."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="I pod si fanno prima dell'inizio del torneo")
    players = eligible_registrations(tournament, db)
    if len(players) < 2:
        raise HTTPException(status_code=409, detail="Servono almeno due giocatori pronti a giocare")
    random.shuffle(players)
    count = math.ceil(len(players) / payload.pod_size)
    base, extra = divmod(len(players), count)
    for reg in db.scalars(select(Registration).where(Registration.tournament_id == tournament.id)):
        reg.pod = reg.pod_seat = None
    start = 0
    for pod in range(1, count + 1):
        size = base + (1 if pod <= extra else 0)
        for seat, reg in enumerate(players[start:start + size], start=1):
            reg.pod, reg.pod_seat = pod, seat
        start += size
    tournament.pod_size = payload.pod_size
    _write_audit(db, tournament.id, organizer.id, "pods_created", f"{count} pod da {payload.pod_size} al massimo")
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    return _pods_of(tournament, db)


@router.delete("/{tournament_id}/pods", status_code=204)
def clear_pods(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="I pod si tolgono prima dell'inizio del torneo")
    for reg in db.scalars(select(Registration).where(Registration.tournament_id == tournament.id)):
        reg.pod = reg.pod_seat = None
    tournament.pod_size = 0
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")


@router.put("/{tournament_id}/registrations/{registration_id}/byes", response_model=OrganizerRegistrationOut)
def set_byes(
    tournament_id: int,
    registration_id: int,
    payload: ByesIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    """Bye assegnati: si decidono prima dell'inizio, poi i turni sono già fatti."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="I bye si assegnano prima dell'inizio del torneo")
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    if registration.byes != payload.byes:
        registration.byes = payload.byes
        _write_audit(db, tournament.id, organizer.id, "byes_assigned",
                     f"{registration.player.display_name}: {payload.byes} bye")
        db.commit()
        cache_invalidate(f"registrations:{tournament.id}")
    return organizer_registration_out(load_registration_for_tournament(tournament_id, registration_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/tardiness", response_model=RoundOut)
def penalize_tardiness(
    tournament_id: int,
    pairing_id: int,
    payload: TardinessIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Chi non si presenta al tavolo, o arriva tardi. Con la sconfitta a
    tavolino l'avversario vince con il punteggio pieno del formato; con il game
    loss la partita si gioca e la penalità resta scritta. Chi non si è
    presentato si può anche ritirare dal torneo, così non viene più abbinato."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing).join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(selectinload(Pairing.round).selectinload(Round.pairings))
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Tavolo non trovato")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="Un bye non ha avversario")
    if payload.registration_id not in {pairing.player_a_registration_id, pairing.player_b_registration_id}:
        raise HTTPException(status_code=422, detail="Il giocatore non è a questo tavolo")
    if payload.penalty == "match_loss" and pairing.result:
        raise HTTPException(status_code=409, detail="Il tavolo ha già un risultato: correggi quello")
    registration = load_registration_for_tournament(tournament_id, payload.registration_id, db)
    number = pairing.round.number
    note = payload.note.strip() or (f"Non presentato al turno {number}" if payload.penalty == "match_loss"
                                    else f"In ritardo al turno {number}")
    db.add(Penalty(tournament_id=tournament.id, registration_id=registration.id, judge_id=user.id,
                   round_id=pairing.round_id, kind=payload.penalty, note=note, is_private=True))
    if payload.drop:
        registration.dropped = True
    _write_audit(db, tournament.id, user.id, f"tardiness_{payload.penalty}",
                 f"{registration.player.display_name}, turno {number}: {note}" + (" (ritirato)" if payload.drop else ""))
    if payload.penalty == "match_loss":
        # Il punteggio pieno: 1-0 al meglio di 1 in svizzera, altrimenti 2-0.
        full = 1 if pairing.round.phase == "swiss" and tournament.best_of == 1 else 2
        late_is_a = registration.id == pairing.player_a_registration_id
        apply_pairing_result(tournament_id, pairing, PairingResultIn(
            match_wins_a=0 if late_is_a else full, match_wins_b=full if late_is_a else 0,
        ), db)
    else:
        db.commit()
    db.refresh(pairing.round)
    for key in ("standings", "result-reports", "my-pairings", "registrations", "public-display"):
        cache_invalidate(f"{key}:{tournament_id}")
    return round_out(pairing.round)


@router.put("/{tournament_id}/registrations/{registration_id}/prize", response_model=OrganizerRegistrationOut)
def set_prize(
    tournament_id: int,
    registration_id: int,
    payload: PrizeIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    """Segna il premio consegnato, o lo annulla. Resta scritto nel registro chi
    l'ha dato e quando: a fine serata si ritrova se qualcuno è rimasto senza."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_owned_tournament(tournament_id, organizer, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    name = registration.player.display_name
    if payload.given:
        registration.prize_note = payload.note.strip()
        registration.prize_given_at = datetime.now(UTC)
        registration.prize_given_by_id = organizer.id
        _write_audit(db, tournament.id, organizer.id, "prize_given",
                     f"{name}: {registration.prize_note or 'premio'}")
    elif registration.prize_given_at:
        _write_audit(db, tournament.id, organizer.id, "prize_revoked",
                     f"{name}: {registration.prize_note or 'premio'}")
        registration.prize_note = ""
        registration.prize_given_at = None
        registration.prize_given_by_id = None
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    return organizer_registration_out(load_registration_for_tournament(tournament_id, registration_id, db))


@router.post("/{tournament_id}/registrations/{registration_id}/mark-paid", response_model=OrganizerRegistrationOut)
def mark_registration_paid(
    tournament_id: int,
    registration_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    """Segna pagata un'iscrizione (contanti/al banco). Organizer o staff."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    payment = registration.payment or Payment(
        registration_id=registration.id,
        provider="cash",
        amount_cents=tournament.entry_fee_cents,
        currency=tournament.currency,
    )
    payment.provider = payment.provider or "cash"
    payment.status = PaymentStatus.PAID
    payment.paid_at = datetime.now(UTC)
    db.add(payment)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    cache_invalidate(f"my-reg:{tournament_id}:{registration.player_id}")
    return organizer_registration_out(
        load_registration_for_tournament(tournament_id, registration_id, db)
    )


@router.post("/{tournament_id}/walk-in", response_model=OrganizerRegistrationOut, status_code=201)
def add_walk_in(
    tournament_id: int,
    payload: WalkInIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizerRegistrationOut:
    """Iscrive al banco un giocatore presente. Crea l'account se non esiste
    (il giocatore potrà poi impostare la password via 'password dimenticata')."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Closed tournaments cannot accept registrations")
    email = payload.email.lower() if payload.email else None
    player = db.scalar(select(User).where(User.email == email)) if email else None
    if not player:
        # Senza email è un ospite: un indirizzo finto (.invalid) che nessuno usa
        # per entrare e a cui non parte nessuna email.
        from uuid import uuid4

        player = User(
            email=email or f"guest-{uuid4().hex}@guests.mull2five.invalid",
            display_name=payload.display_name,
            role=UserRole.PLAYER,
            password_hash=None,
            is_active=True,
            is_guest=not email,
        )
        db.add(player)
        db.flush()
    existing = db.scalar(
        select(Registration).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == player.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Player already registered")
    check_not_suspended(player, tournament, db, at_desk=True)
    answers = validate_answers(tournament.id, payload.answers, db, enforce_required=False)
    active = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament_id,
            Registration.waitlisted == False,  # noqa: E712
        )
    ) or 0
    is_full = active >= tournament.capacity
    registration = Registration(
        tournament_id=tournament_id,
        player_id=player.id,
        wizards_account=payload.wizards_account,
        waitlisted=is_full,
    )
    db.add(registration)
    db.flush()
    save_answers(registration.id, answers, db)
    if payload.mark_paid and not is_full:
        db.add(Payment(
            registration_id=registration.id,
            provider="cash",
            status=PaymentStatus.PAID,
            amount_cents=tournament.entry_fee_cents,
            currency=tournament.currency,
            paid_at=datetime.now(UTC),
        ))
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    cache_invalidate("tournaments:")
    return organizer_registration_out(
        load_registration_for_tournament(tournament_id, registration.id, db)
    )


IMPORT_LIMIT = 500


@router.post("/{tournament_id}/import", response_model=ImportOut)
def import_registrations(
    tournament_id: int,
    payload: ImportIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> ImportOut:
    """Iscrive una lista di giocatori da un file: preiscrizioni raccolte altrove,
    un torneo spostato da un'altra piattaforma. Valgono le regole del banco: chi
    non ha un account lo riceve, chi è sospeso resta fuori, oltre la capienza si
    va in lista d'attesa. Con dry_run dice cosa succederebbe, riga per riga,
    senza toccare niente."""
    from email_validator import EmailNotValidError, validate_email

    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Closed tournaments cannot accept registrations")
    try:
        players = parse_players_csv(payload.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(players) > IMPORT_LIMIT:
        raise HTTPException(status_code=422, detail=f"Al massimo {IMPORT_LIMIT} righe per volta")

    active = db.scalar(select(func.count(Registration.id)).where(
        Registration.tournament_id == tournament.id, Registration.waitlisted.is_(False),
    )) or 0
    already = set(db.scalars(
        select(User.email).join(Registration, Registration.player_id == User.id)
        .where(Registration.tournament_id == tournament.id)
    ).all())
    rows: list[ImportRowOut] = []
    for item in players:
        email = item.email.strip().lower()
        row = ImportRowOut(line=item.line, email=email, name=(item.name or email.split("@")[0])[:160],
                           outcome="added")
        rows.append(row)
        if not email:
            row.outcome, row.detail = "error", "Manca l'email"
            continue
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            row.outcome, row.detail = "error", "Email non valida"
            continue
        if email in already:
            row.outcome, row.detail = "already", "Già iscritto"
            continue
        already.add(email)   # la stessa email due volte nel file conta una
        player = db.scalar(select(User).where(User.email == email))
        if player and active_suspension(player.id, tournament.organization_id, db):
            row.outcome, row.detail = "error", "Sospeso dagli eventi del negozio"
            continue
        waitlisted = active >= tournament.capacity
        if waitlisted:
            row.outcome = "waitlisted"
        else:
            active += 1
        if payload.dry_run:
            continue
        if not player:
            player = User(email=email, display_name=row.name, role=UserRole.PLAYER,
                          password_hash=None, is_active=True)
            db.add(player)
            db.flush()
        registration = Registration(tournament_id=tournament.id, player_id=player.id,
                                    wizards_account=item.publisher_id[:80], waitlisted=waitlisted)
        db.add(registration)
        db.flush()
        if (payload.mark_paid or item.paid) and not waitlisted:
            db.add(Payment(registration_id=registration.id, provider="cash", status=PaymentStatus.PAID,
                           amount_cents=tournament.entry_fee_cents, currency=tournament.currency,
                           paid_at=datetime.now(UTC)))

    added = sum(r.outcome == "added" for r in rows)
    waiting = sum(r.outcome == "waitlisted" for r in rows)
    if not payload.dry_run and (added or waiting):
        _write_audit(db, tournament.id, organizer.id, "registrations_imported",
                     f"{added} iscritti, {waiting} in lista d'attesa, {len(rows) - added - waiting} saltati")
        db.commit()
        from backend.app.core.cache import cache_invalidate
        cache_invalidate(f"registrations:{tournament.id}")
        cache_invalidate("tournaments:")
    return ImportOut(rows=rows, added=added, waitlisted=waiting, skipped=len(rows) - added - waiting)


@router.patch("/{tournament_id}/controls", response_model=TournamentOut)
def update_tournament_controls(
    tournament_id: int,
    payload: TournamentControlsIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(tournament, key, value)
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    count = db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament.id))
    return tournament_out(tournament, count or 0, db)


@router.get("/{tournament_id}/standings", response_model=list[StandingOut])
def get_standings(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StandingOut]:
    from backend.app.core.cache import cache_get, cache_set
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if not tournament.standings_public and not owns_tournament(tournament, user, db):
        return []
    cache_key = f"standings:{tournament_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    result = calculate_standings(tournament_id, db)
    cache_set(cache_key, result, ttl=30.0)   # 30s — invalidata esplicitamente dopo ogni risultato
    return result


@router.get("/{tournament_id}/rounds", response_model=list[RoundOut])
def list_rounds(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RoundOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    is_staff = owns_tournament(tournament, user, db) or is_tournament_staff(tournament_id, user.id, db)
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number)
    ).all()
    report_map = latest_result_reports(tournament_id, db)
    if not is_staff:
        rounds = [round_obj for round_obj in rounds if round_obj.is_published and tournament.pairings_public]
    return [round_out(round_obj, report_map) for round_obj in rounds]


@router.get("/{tournament_id}/my-pairings", response_model=list[RoundOut])
def my_pairings(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RoundOut]:
    # Niente cache: dato live e per-giocatore. Con più worker Gunicorn la cache
    # in-memory è per-processo e l'invalidazione non si propaga: un avversario
    # potrebbe non vedere il risultato appena inserito (sezione conferma assente).
    # La query carica solo i 3 pairing del giocatore, è economica.
    registration = db.scalar(
        select(Registration).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    # Carica SOLO i pairing di questo giocatore (3 righe), non tutti i 1500
    pairings = db.scalars(
        select(Pairing)
        .join(Round)
        .where(
            Round.tournament_id == tournament_id,
            (Pairing.player_a_registration_id == registration.id)
            | (Pairing.player_b_registration_id == registration.id),
        )
        .options(
            selectinload(Pairing.round),
            selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Pairing.player_b).selectinload(Registration.player),
        )
        .order_by(Round.number)
    ).all()

    # Raggruppa per round
    round_map: dict[int, tuple[Round, list[Pairing]]] = {}
    for pairing in pairings:
        rnd = pairing.round
        if rnd.id not in round_map:
            round_map[rnd.id] = (rnd, [])
        round_map[rnd.id][1].append(pairing)

    report_map = latest_result_reports(tournament_id, db)
    result = []
    for rnd, player_pairings in sorted(round_map.values(), key=lambda x: x[0].number):
        # NON mutare rnd.pairings: assegnare la relazione ORM dissocia gli altri
        # pairing dal round (UPDATE round_id=NULL al commit successivo)
        result.append(round_out(rnd, report_map, pairings=player_pairings))

    if registration.tournament.is_online:
        # Online l'avversario si cerca col suo nome in gioco: lo vede solo chi ci gioca.
        by_id = {pairing.id: pairing for pairing in pairings}
        for rnd_out in result:
            for item in rnd_out.pairings:
                pairing = by_id[item.id]
                item.player_a_handle = pairing.player_a.game_handle
                item.player_b_handle = pairing.player_b.game_handle if pairing.player_b else ""
    return result


@router.get("/{tournament_id}/decklist", response_model=DecklistOut)
def my_decklist(
    tournament_id: int,
    format: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Decklist:
    """La lista che il giocatore ha inviato per questo torneo. Senza questa non
    poteva né rileggerla né correggerla: il client aveva solo lo stato."""
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(selectinload(Registration.decklists))
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    decklist = registration.decklist_for(format)
    if not decklist:
        raise HTTPException(status_code=404, detail="Nessuna lista inviata")
    return decklist


@router.post("/{tournament_id}/decklist", response_model=DecklistOut)
def submit_decklist(
    tournament_id: int,
    payload: DecklistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Decklist:
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(selectinload(Registration.tournament), selectinload(Registration.decklists))
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    if decklists_locked(registration.tournament):
        raise HTTPException(status_code=409, detail="Decklist submissions are locked")

    tournament = registration.tournament
    validation = validate_decklist(payload.raw_text, payload.format or tournament.format, tournament.game)
    registration.archetype = payload.archetype.strip()
    errors = validation.errors[:]
    if tournament.legal_validation_enabled:
        errors.extend(validate_card_legality(payload.raw_text, payload.format or tournament.format, tournament.game))
    status = DecklistStatus.INVALID if errors else DecklistStatus.VALID
    fmt = (payload.format or "").strip()
    decklist = registration.decklist_for(fmt) or Decklist(
        registration_id=registration.id, format=fmt, raw_text=""
    )
    decklist.raw_text = payload.raw_text
    decklist.main_count = validation.main_count
    decklist.side_count = validation.side_count
    decklist.status = status
    decklist.validation_errors = "\n".join(errors)
    db.add(registration)
    db.add(decklist)
    db.add(
        DecklistRevision(
            registration_id=registration.id,
            edited_by_id=user.id,
            raw_text=payload.raw_text,
            main_count=validation.main_count,
            side_count=validation.side_count,
            status=status,
            validation_errors="\n".join(errors),
        )
    )
    db.commit()
    db.refresh(decklist)
    return decklist


@router.post("/{tournament_id}/registrations/{registration_id}/decklist", response_model=DecklistOut)
def submit_decklist_for_registration(
    tournament_id: int,
    registration_id: int,
    payload: DecklistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Decklist:
    """L'organizzatore/staff carica la decklist per conto di un iscritto (deck check
    al banco). Non soggetto al lock delle liste, a differenza dell'invio del giocatore."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)

    validation = validate_decklist(payload.raw_text, payload.format or tournament.format, tournament.game)
    registration.archetype = payload.archetype.strip()
    errors = validation.errors[:]
    if tournament.legal_validation_enabled:
        errors.extend(validate_card_legality(payload.raw_text, payload.format or tournament.format, tournament.game))
    status = DecklistStatus.INVALID if errors else DecklistStatus.VALID
    fmt = (payload.format or "").strip()
    decklist = registration.decklist_for(fmt) or Decklist(
        registration_id=registration.id, format=fmt, raw_text=""
    )
    decklist.raw_text = payload.raw_text
    decklist.main_count = validation.main_count
    decklist.side_count = validation.side_count
    decklist.status = status
    decklist.validation_errors = "\n".join(errors)
    db.add(registration)
    db.add(decklist)
    db.add(DecklistRevision(
        registration_id=registration.id, edited_by_id=user.id, raw_text=payload.raw_text,
        main_count=validation.main_count, side_count=validation.side_count,
        status=status, validation_errors="\n".join(errors),
    ))
    db.commit()
    db.refresh(decklist)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    return decklist


@router.post("/{tournament_id}/checkout", response_model=PaymentOut)
async def checkout(
    tournament_id: int,
    payload: CheckoutCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(selectinload(Registration.tournament), selectinload(Registration.payment))
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    tournament = registration.tournament
    # Il provider richiesto deve essere abilitato dall'organizzatore per questo torneo
    if payload.provider == "stripe" and not tournament.pay_stripe:
        raise HTTPException(status_code=409, detail="Pagamento con Stripe non disponibile per questo torneo")
    if payload.provider == "paypal" and not tournament.pay_paypal:
        raise HTTPException(status_code=409, detail="Pagamento con PayPal non disponibile per questo torneo")
    payment = registration.payment or Payment(
        registration_id=registration.id,
        provider=payload.provider,
        amount_cents=tournament.entry_fee_cents,
        currency=tournament.currency,
    )
    payment.provider = payload.provider
    payment.amount_cents = tournament.entry_fee_cents
    payment.currency = tournament.currency
    db.add(payment)
    db.flush()

    settings = get_settings()
    if settings.payment_sandbox_mock and (
        (payload.provider == "stripe" and not settings.stripe_secret_key)
        or (
            payload.provider == "paypal"
            and (not settings.paypal_client_id or not settings.paypal_client_secret)
        )
    ):
        frontend_url = str(settings.frontend_url).rstrip("/")
        payment.provider_checkout_id = f"sandbox-{payload.provider}-{payment.id}"
        payment.checkout_url = (
            f"{frontend_url}/sandbox-checkout.html"
            f"?payment_id={payment.id}&provider={payload.provider}"
        )
        db.commit()
        db.refresh(payment)
        return payment

    # L'incasso va al negozio del torneo, se ha collegato i suoi conti.
    store = db.get(Organization, tournament.organization_id) if tournament.organization_id else None
    session = (
        await create_stripe_checkout(registration, store)
        if payload.provider == "stripe"
        else await create_paypal_checkout(registration, store)
    )
    payment.provider_checkout_id = session.provider_checkout_id
    payment.checkout_url = session.checkout_url
    payment.payee = session.payee
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/{tournament_id}/refund-request", response_model=PaymentOut)
def request_refund(
    tournament_id: int,
    payload: RefundRequestIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(selectinload(Registration.payment), selectinload(Registration.tournament))
    )
    if not registration or not registration.payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if registration.payment.status != PaymentStatus.PAID:
        raise HTTPException(status_code=409, detail="Only paid registrations can request a refund")
    registration.payment.status = PaymentStatus.REFUND_REQUESTED
    registration.payment.refund_reason = payload.reason
    registration.payment.refund_requested_at = datetime.now(UTC)
    db.commit()
    db.refresh(registration.payment)
    return registration.payment


@router.post("/{tournament_id}/payments/{payment_id}/refund", response_model=PaymentOut)
async def decide_refund(
    tournament_id: int,
    payment_id: int,
    payload: RefundDecisionIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Payment:
    load_owned_tournament(tournament_id, organizer, db)
    payment = db.scalar(
        select(Payment)
        .join(Registration)
        .where(Payment.id == payment_id, Registration.tournament_id == tournament_id)
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status not in {PaymentStatus.PAID, PaymentStatus.REFUND_REQUESTED}:
        raise HTTPException(status_code=409, detail="Payment cannot be refunded")
    if not payload.approve:
        payment.status = PaymentStatus.PAID
        payment.refund_reason = ""
        payment.refund_requested_at = None
        db.commit()
        db.refresh(payment)
        return payment

    settings = get_settings()
    if payment.provider == "stripe" and settings.stripe_secret_key and payment.provider_payment_id:
        stripe.api_key = settings.stripe_secret_key
        # Pagato al negozio: il rimborso riprende il bonifico e restituisce la quota della piattaforma.
        store_paid = {"reverse_transfer": True, "refund_application_fee": True} if payment.payee.startswith("stripe:") else {}
        stripe.Refund.create(payment_intent=payment.provider_payment_id, **store_paid)
    elif payment.provider == "paypal" and payment.payee.startswith("paypal:"):
        pass   # l'incasso è sul PayPal del negozio: il rimborso lo fa il negozio da lì, qui si registra
    elif payment.provider == "paypal" and not settings.payment_sandbox_mock:
        await refund_paypal_capture(payment.provider_payment_id)

    payment.status = PaymentStatus.REFUNDED
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/{tournament_id}/rounds", response_model=RoundOut)
def create_round(
    tournament_id: int,
    force: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Genera il round successivo. Organizzatore o capojudge: in sala è il capojudge
    a mandare avanti i turni, e se l'organizzatore esce dal negozio il torneo non
    deve fermarsi."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    ensure_tournament_live(tournament)   # su torneo chiuso dà il messaggio giusto
    if tournament.status != TournamentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Start the tournament before creating rounds")
    ensure_latest_round_has_results(tournament_id, db)

    # Torneo svizzero "puro": i turni previsti sono ceil(log2(iscritti)). Generare
    # un turno oltre quel numero può ripetere gli abbinamenti → richiede conferma.
    if tournament.structure == TournamentStructure.SWISS and not force:
        eligible_count = len(eligible_registrations(tournament, db))
        planned = planned_swiss_rounds(tournament, eligible_count)
        next_number = len(tournament.rounds) + 1
        if next_number > planned:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"EXTRA_SWISS_ROUND: i {planned} turni svizzeri previsti per "
                    f"{eligible_count} giocatori sono completati. Un turno aggiuntivo "
                    "può ripetere gli abbinamenti: è sconsigliato."
                ),
            )

    result = create_round_for_tournament(tournament, db)
    # Notifica email pairings pronti
    try:
        from backend.app.services.notifications import notify_pairings_ready
        regs = eligible_registrations(tournament, db)
        notify_pairings_ready(tournament, result.number, regs)
    except Exception:
        pass
    return result


@router.patch("/{tournament_id}/pairings/{pairing_id}", response_model=RoundOut)
def update_manual_pairing(
    tournament_id: int,
    pairing_id: int,
    payload: ManualPairingIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    load_owned_tournament(tournament_id, organizer, db)
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    latest_round_number = db.scalar(select(func.max(Round.number)).where(Round.tournament_id == tournament_id))
    if latest_round_number and pairing.round.number < latest_round_number:
        raise HTTPException(status_code=409, detail="Pairing is locked because a later round exists")
    if pairing.result:
        raise HTTPException(status_code=409, detail="Pairing already has a result")
    validate_pairing_registration(tournament_id, payload.player_a_registration_id, db)
    if payload.player_b_registration_id:
        validate_pairing_registration(tournament_id, payload.player_b_registration_id, db)
        if payload.player_a_registration_id == payload.player_b_registration_id:
            raise HTTPException(status_code=422, detail="A player cannot be paired against themself")
    validate_manual_pairing_conflicts(pairing, payload, db)
    pairing.table_number = payload.table_number
    pairing.player_a_registration_id = payload.player_a_registration_id
    pairing.player_b_registration_id = payload.player_b_registration_id
    db.commit()
    db.refresh(pairing.round)
    return round_out(pairing.round)


@router.get("/{tournament_id}/bracket", response_model=list[BracketMatchOut])
def get_bracket(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BracketMatchOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if not tournament.pairings_public and not owns_tournament(tournament, user, db):
        return []
    return _build_bracket(tournament_id, db)


def _build_bracket(tournament_id: int, db: Session) -> list[BracketMatchOut]:
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase.in_(["elimination", "topcut"]))
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number)
    ).all()
    matches: list[BracketMatchOut] = []
    for round_obj in rounds:
        for pairing in sorted(round_obj.pairings, key=lambda item: item.table_number):
            winner = None
            if pairing.result == "A":
                winner = pairing.player_a.player.display_name
            elif pairing.result == "B" and pairing.player_b:
                winner = pairing.player_b.player.display_name
            matches.append(
                BracketMatchOut(
                    pairing_id=pairing.id,
                    round_number=round_obj.number,
                    table_number=pairing.table_number,
                    player_a=pairing.player_a.player.display_name,
                    player_b=pairing.player_b.player.display_name if pairing.player_b else None,
                    match_wins_a=pairing.match_wins_a,
                    match_wins_b=pairing.match_wins_b,
                    winner=winner,
                )
            )
    return matches


@router.patch("/{tournament_id}/pairings/{pairing_id}/result", response_model=RoundOut)
def report_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    # Organizzatore proprietario o staff/judge invitato
    load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    apply_pairing_result(tournament_id, pairing, payload, db)
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")       # standings cambiano dopo ogni risultato
    cache_invalidate(f"result-reports:{tournament_id}")  # report map obsoleta
    cache_invalidate(f"my-pairings:{tournament_id}")     # card giocatori obsoleta
    return round_out(pairing.round)


def _write_audit(db: Session, tournament_id: int, editor_id: int, action: str, detail: str) -> None:
    db.add(AuditLog(tournament_id=tournament_id, editor_id=editor_id, action=action, detail=detail))


# ── #39 Correzione risultato post-torneo + audit log ──────────
@router.patch("/{tournament_id}/pairings/{pairing_id}/correct", response_model=RoundOut)
def correct_pairing_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Corregge il risultato di un tavolo anche a torneo concluso e ricalcola la
    classifica. L'azione viene tracciata nell'audit log (chi/quando/cosa)."""
    load_owned_tournament(tournament_id, organizer, db)
    pairing = db.scalar(
        select(Pairing).join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round).selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Pairing.round).selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="I BYE non si correggono")
    ensure_allowed_score(payload, pairing, db)
    old = f"{pairing.match_wins_a}-{pairing.match_wins_b}"
    pairing.match_wins_a = payload.match_wins_a
    pairing.match_wins_b = payload.match_wins_b
    pairing.draws = payload.draws
    pairing.result = "A" if payload.match_wins_a > payload.match_wins_b else ("B" if payload.match_wins_b > payload.match_wins_a else "D")
    new = f"{payload.match_wins_a}-{payload.match_wins_b}"
    _write_audit(db, tournament_id, organizer.id, "correct_result",
                 f"Tavolo {pairing.table_number} round {pairing.round.number}: {old} → {new}")
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round)


@router.get("/{tournament_id}/audit", response_model=list[AuditLogOut])
def list_audit(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[AuditLogOut]:
    load_owned_tournament(tournament_id, organizer, db)
    logs = db.scalars(
        select(AuditLog).where(AuditLog.tournament_id == tournament_id)
        .options(joinedload(AuditLog.editor)).order_by(AuditLog.created_at.desc())
    ).all()
    return [AuditLogOut(id=lg.id, action=lg.action, detail=lg.detail,
                        editor=(lg.editor.display_name if lg.editor else "?"),
                        created_at=lg.created_at) for lg in logs]


# ── #37 Gestione no-show: marca assenti e rigenera l'ultimo round ──
@router.post("/{tournament_id}/rounds/regenerate", response_model=RoundOut)
def regenerate_round(
    tournament_id: int,
    payload: RegenerateRoundIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Segna come ritirati i giocatori assenti (no-show) ed elimina+rigenera
    l'ultimo round (consentito solo se quel round non ha ancora risultati).
    Organizzatore o capojudge, come la generazione."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    if tournament.status != TournamentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Il torneo non è in corso")
    latest = db.scalar(
        select(Round).where(Round.tournament_id == tournament_id)
        .options(selectinload(Round.pairings)).order_by(Round.number.desc())
    )
    if not latest:
        raise HTTPException(status_code=409, detail="Nessun round da rigenerare")
    if any(p.result and p.player_b_registration_id for p in latest.pairings):
        raise HTTPException(status_code=409, detail="Il round ha già dei risultati: non rigenerabile")
    # Marca assenti come ritirati
    for rid in set(payload.drop_registration_ids):
        reg = db.get(Registration, rid)
        if reg and reg.tournament_id == tournament_id:
            reg.dropped = True
            db.add(reg)
    if payload.drop_registration_ids:
        _write_audit(db, tournament_id, user.id, "no_show",
                     f"Segnati assenti: {len(set(payload.drop_registration_ids))} giocatori, round {latest.number} rigenerato")
    # Elimina il round e i suoi pairing, poi rigenera
    for p in list(latest.pairings):
        db.delete(p)
    db.delete(latest)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return create_round_for_tournament(tournament, db)


# ── #41 Statistiche meta (archetipi + win rate) ───────────────
def compute_meta_stats(tournament_id: int, db: Session) -> list[MetaStatRow]:
    """Ripartizione per archetipo: quanti l'hanno giocato e come è andata."""
    standings = calculate_standings(tournament_id, db)
    regs = db.scalars(select(Registration).where(Registration.tournament_id == tournament_id)).all()
    arch_by_reg = {r.id: (r.archetype.strip() or "Sconosciuto") for r in regs}
    agg: dict[str, dict] = {}
    for s in standings:
        arch = arch_by_reg.get(s.registration_id, "Sconosciuto")
        # calculate_standings scrive il record come "vittorie/sconfitte/pareggi":
        # leggerlo in un altro ordine gonfia il win rate (le sconfitte finivano
        # fra i pareggi e sparivano dal denominatore).
        try:
            w, ls, d = (int(x) for x in str(s.record).split("/"))
        except (ValueError, AttributeError):
            w = d = ls = 0
        a = agg.setdefault(arch, {"players": 0, "wins": 0, "draws": 0, "losses": 0})
        a["players"] += 1
        a["wins"] += w
        a["draws"] += d
        a["losses"] += ls
    rows = []
    for arch, a in agg.items():
        games = a["wins"] + a["losses"]
        rows.append(MetaStatRow(
            archetype=arch, players=a["players"], wins=a["wins"], draws=a["draws"], losses=a["losses"],
            win_rate=round(a["wins"] / games * 100, 1) if games else 0.0,
        ))
    rows.sort(key=lambda r: (-r.players, -r.win_rate))
    return rows


@router.get("/{tournament_id}/meta-stats", response_model=list[MetaStatRow])
def meta_stats(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[MetaStatRow]:
    """Metagame a torneo in corso: solo per chi lo organizza."""
    load_owned_tournament(tournament_id, organizer, db)
    return compute_meta_stats(tournament_id, db)


@router.get("/{tournament_id}/public-meta", response_model=list[MetaStatRow])
def public_meta_stats(tournament_id: int, db: Session = Depends(get_db)) -> list[MetaStatRow]:
    """Metagame di un torneo concluso, per la pagina coverage e lo storico.

    Vincolato alla classifica pubblica: gli archetipi compaiono già lì accanto
    ai nomi, quindi chi nasconde la classifica non se li vede uscire da qui.
    """
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.status != TournamentStatus.COMPLETED or not tournament.standings_public:
        raise HTTPException(status_code=404, detail="Metagame non pubblico per questo torneo")
    return compute_meta_stats(tournament_id, db)


# ── #46 Bracket pubblico (SPA) ────────────────────────────────
@router.get("/{tournament_id}/public-bracket", response_model=list[BracketMatchOut])
def public_bracket(tournament_id: int, db: Session = Depends(get_db)) -> list[BracketMatchOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if not tournament.pairings_public:
        return []
    return _build_bracket(tournament_id, db)


@router.patch("/{tournament_id}/pairings/{pairing_id}/player-result", response_model=RoundOut)
def report_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    ensure_allowed_score(payload, pairing, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    existing = latest_open_report(pairing.id, db)
    if existing and existing.reporter_registration_id != reporter_id:
        raise HTTPException(status_code=409, detail="Opponent result is waiting for confirm or reject")
    if existing and existing.reporter_registration_id == reporter_id:
        existing.match_wins_a = payload.match_wins_a
        existing.match_wins_b = payload.match_wins_b
        existing.draws = payload.draws
        existing.created_at = datetime.now(UTC)
        db.add(existing)
    else:
        db.add(
            PairingResultReport(
                pairing_id=pairing.id,
                reporter_registration_id=reporter_id,
                match_wins_a=payload.match_wins_a,
                match_wins_b=payload.match_wins_b,
                draws=payload.draws,
                status=ResultReportStatus.PENDING,
            )
        )
    db.commit()
    db.refresh(pairing.round)
    # Invalida PRIMA di ricostruire: così l'avversario vede subito il report e
    # gli compare la sezione "Conferma / Chiama Judge" (no attesa del TTL cache).
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/player-result/confirm", response_model=RoundOut)
def confirm_player_result(
    tournament_id: int,
    pairing_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    report = latest_open_report(pairing.id, db)
    if not report:
        raise HTTPException(status_code=404, detail="No pending result to confirm")
    if report.reporter_registration_id == reporter_id:
        raise HTTPException(status_code=409, detail="Opponent must confirm this result")
    apply_pairing_result(
        tournament_id,
        pairing,
        PairingResultIn(
            match_wins_a=report.match_wins_a,
            match_wins_b=report.match_wins_b,
            draws=report.draws,
        ),
        db,
    )
    report.status = ResultReportStatus.CONFIRMED
    report.resolved_at = datetime.now(UTC)
    db.add(report)
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/player-result/reject", response_model=RoundOut)
def reject_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultRejectIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    report = latest_open_report(pairing.id, db)
    if not report:
        raise HTTPException(status_code=404, detail="No pending result to reject")
    if report.reporter_registration_id == reporter_id:
        raise HTTPException(status_code=409, detail="Opponent must reject this result")
    report.status = ResultReportStatus.CONFLICT
    report.note = payload.note
    report.resolved_at = datetime.now(UTC)
    db.add(report)
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.get("/{tournament_id}/public-results", response_model=PublicResultsOut)
def public_results(tournament_id: int, db: Session = Depends(get_db)) -> PublicResultsOut:
    """Risultati pubblici di un torneo (storico): vincitore, classifica e — se le
    liste sono pubbliche — le decklist. Nessuna autenticazione richiesta."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    rows: list[PublicStandingRow] = []
    if tournament.standings_public:
        standings = calculate_standings(tournament_id, db)
        decks: dict[int, Registration] = {}
        if tournament.decklists_public:
            regs = db.scalars(
                select(Registration)
                .where(Registration.tournament_id == tournament_id)
                .options(selectinload(Registration.decklists))
            ).all()
            decks = {r.id: r for r in regs}
        for s in standings:
            reg = decks.get(s.registration_id)
            rows.append(PublicStandingRow(
                position=s.position, registration_id=s.registration_id, name=s.name,
                points=s.points, record=s.record,
                archetype=(reg.archetype if reg else "") or "",
                decklist=(reg.decklist.raw_text if reg and reg.decklist else None),
            ))
    return PublicResultsOut(
        tournament_id=tournament.id, name=tournament.name, format=tournament.format,
        starts_on=tournament.starts_on, start_time=tournament.start_time, status=tournament.status,
        standings_public=tournament.standings_public, decklists_public=tournament.decklists_public,
        standings=rows,
    )


@router.get("/{tournament_id}/public-display", response_model=PublicDisplayOut)
def public_display(tournament_id: int, db: Session = Depends(get_db)) -> PublicDisplayOut:
    """Dati per lo schermo pubblico in negozio (TV/proiettore) — nessuna autenticazione.

    Restituisce pairing del round corrente (se pairings_public), scadenza timer
    e standings (se standings_public). Cache 10s: regge il polling di più schermi.
    """
    from backend.app.core.cache import cache_get, cache_set
    cache_key = f"public-display:{tournament_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    latest_round = None
    pairings_out: list[PublicPairingOut] = []
    if tournament.pairings_public:
        latest_round = db.scalar(
            select(Round)
            .where(Round.tournament_id == tournament_id, Round.is_published == True)  # noqa: E712
            .options(
                selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
                selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
            )
            .order_by(Round.number.desc())
        )
        if latest_round:
            base_end = latest_round.ends_at
            pairings_out = [
                PublicPairingOut(
                    table_number=p.table_number,
                    player_a=p.player_a.player.display_name,
                    player_b=p.player_b.player.display_name if p.player_b else None,
                    result=p.result,
                    extra_seconds=p.extra_seconds,
                    # Fine effettiva del tavolo = fine round + minuti extra concessi
                    ends_at=(base_end + timedelta(seconds=p.extra_seconds)) if base_end else None,
                )
                for p in sorted(latest_round.pairings, key=lambda x: x.table_number)
            ]

    standings = calculate_standings(tournament_id, db) if tournament.standings_public else []

    result = PublicDisplayOut(
        tournament_name=tournament.name,
        round_number=latest_round.number if latest_round else None,
        round_ends_at=latest_round.ends_at if latest_round else None,
        pairings=pairings_out,
        standings=standings[:16],   # top 16 bastano per lo schermo
    )
    cache_set(cache_key, result, ttl=10.0)
    return result


def _latest_round_or_404(tournament_id: int, db: Session) -> Round:
    rnd = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .order_by(Round.number.desc())
    )
    if not rnd:
        raise HTTPException(status_code=404, detail="Nessun round generato")
    return rnd


@router.post("/{tournament_id}/timer/restart", response_model=RoundOut)
def restart_round_timer(
    tournament_id: int,
    payload: TimerRestartIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """(Ri)avvia il timer dell'ultimo round: ends_at = ora + minuti. Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    rnd = _latest_round_or_404(tournament_id, db)
    now = datetime.now(UTC)
    rnd.starts_at = now
    rnd.ends_at = now + timedelta(minutes=payload.minutes)
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/timer/stop", response_model=RoundOut)
def stop_round_timer(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Ferma il timer dell'ultimo round (ends_at = None). Organizer o staff."""
    load_tournament_for_staff(tournament_id, user, db)
    rnd = _latest_round_or_404(tournament_id, db)
    rnd.ends_at = None
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/timer/extend", response_model=RoundOut)
def extend_round_timer(
    tournament_id: int,
    payload: TimerExtendIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Aggiunge minuti alla scadenza dell'intero round corrente. Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    rnd = _latest_round_or_404(tournament_id, db)
    base = rnd.ends_at or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    rnd.ends_at = base + timedelta(minutes=payload.minutes)
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.patch("/{tournament_id}/pairings/{pairing_id}/extend", response_model=RoundOut)
def extend_table_timer(
    tournament_id: int,
    pairing_id: int,
    payload: TableExtendIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Aggiunge minuti al singolo tavolo (es. ruling del judge). Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    pairing.extra_seconds = (pairing.extra_seconds or 0) + payload.minutes * 60
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


def _ical_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def _tournament_to_vevent(tournament: Tournament) -> str:
    start = tournament.starts_on.strftime("%Y%m%d")
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:mull2five-tournament-{tournament.id}@mull2five\r\n"
        f"DTSTART;VALUE=DATE:{start}\r\n"
        f"SUMMARY:{_ical_escape(tournament.name)} ({_ical_escape(tournament.format)})\r\n"
        f"LOCATION:{_ical_escape(tournament.place)}\r\n"
        f"DESCRIPTION:{_ical_escape(tournament.description or tournament.format)}\r\n"
        "END:VEVENT\r\n"
    )


def official_report(tournament: Tournament, db: Session) -> OfficialReportOut:
    game = get_game(tournament.game)
    ids = dict(db.execute(
        select(Registration.id, Registration.wizards_account).where(Registration.tournament_id == tournament.id)
    ).all())
    done = tournament.status == TournamentStatus.COMPLETED
    rows = [
        OfficialReportRowOut(
            position=row.position, registration_id=row.registration_id, name=row.name,
            publisher_id=(ids.get(row.registration_id) or "").strip(), record=row.record, points=row.points,
            invited=done and row.position <= tournament.invites,
        )
        for row in calculate_standings(tournament.id, db)
    ]
    return OfficialReportOut(
        tournament_id=tournament.id, name=tournament.name, format=tournament.format,
        starts_on=tournament.starts_on, status=tournament.status, event_type=tournament.event_type,
        sanction_id=tournament.sanction_id, sanction_label=game.sanction_label,
        publisher_id_label=game.publisher_id_label, players=len(rows),
        rounds=db.scalar(select(func.count(Round.id)).where(Round.tournament_id == tournament.id)) or 0,
        invites=tournament.invites, rows=rows, missing_ids=[row.name for row in rows if not row.publisher_id],
    )


@router.get("/{tournament_id}/official-report", response_model=OfficialReportOut)
def get_official_report(
    tournament_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> OfficialReportOut:
    """Il report per l'editore: classifica con gli ID dei giocatori e gli inviti."""
    return official_report(load_tournament_for_staff(tournament_id, user, db), db)


@router.get("/{tournament_id}/official-report.csv")
def official_report_csv(
    tournament_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    report = official_report(load_tournament_for_staff(tournament_id, user, db), db)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Posizione", "Giocatore", report.publisher_id_label, "Record", "Punti", "Invito"])
    for row in report.rows:
        writer.writerow([row.position, row.name, row.publisher_id, row.record, row.points, "sì" if row.invited else ""])
    name = f"report-{report.sanction_id or tournament_id}.csv".replace(" ", "-")
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/{tournament_id}/registrations/{registration_id}/publisher-id", response_model=RegistrationOut)
def set_publisher_id(
    tournament_id: int,
    registration_id: int,
    payload: PublisherIdIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    """Lo staff completa l'ID di chi l'ha dato a voce al banco."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    registration = load_registration_for_tournament(tournament.id, registration_id, db)
    registration.wizards_account = payload.publisher_id.strip()
    db.commit()
    db.refresh(registration)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"registrations:{tournament_id}")
    return registration_out(registration)


@router.get("/{tournament_id}/ical")
def tournament_ical(tournament_id: int, db: Session = Depends(get_db)) -> Response:
    """File .ics per 'Aggiungi al calendario' — pubblico."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.status == TournamentStatus.CANCELLED:
        raise HTTPException(status_code=404, detail="Tournament not found")
    body = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Mull2Five//IT\r\n"
        + _tournament_to_vevent(tournament)
        + "END:VCALENDAR\r\n"
    )
    return Response(
        content=body,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="torneo-{tournament_id}.ics"'},
    )


@router.get("/calendar/feed.ics")
def calendar_feed(db: Session = Depends(get_db)) -> Response:
    """Feed iCal di tutti i tornei pubblicati — da far seguire ai regular."""
    tournaments = db.scalars(
        select(Tournament).where(
            Tournament.status.in_([TournamentStatus.PUBLISHED, TournamentStatus.RUNNING])
        )
    ).all()
    body = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Mull2Five//IT\r\n"
        "X-WR-CALNAME:Mull2Five — Tornei\r\n"
        + "".join(_tournament_to_vevent(t) for t in tournaments)
        + "END:VCALENDAR\r\n"
    )
    return Response(content=body, media_type="text/calendar")


@router.get("/{tournament_id}/export.csv")
def export_results_csv(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Response:
    """Export CSV iscritti + risultati round per round (per Wizards EventLink)."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(joinedload(Registration.player))
    ).all()
    reg_names = {r.id: r.player.display_name for r in registrations}

    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(selectinload(Round.pairings))
        .order_by(Round.number)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["# Torneo", tournament.name, tournament.format, str(tournament.starts_on)])
    writer.writerow([])
    writer.writerow(["## Iscritti"])
    writer.writerow(["Nome", "Wizards Account", "Archetipo", "Check-in", "Drop", "Waitlist"])
    for reg in registrations:
        writer.writerow([
            reg.player.display_name, reg.wizards_account, reg.archetype,
            "si" if reg.checked_in else "no",
            "si" if reg.dropped else "no",
            "si" if reg.waitlisted else "no",
        ])
    writer.writerow([])
    writer.writerow(["## Risultati"])
    writer.writerow(["Round", "Tavolo", "Giocatore A", "Giocatore B", "Risultato", "Games A", "Games B", "Pareggi"])
    for rnd in rounds:
        for p in sorted(rnd.pairings, key=lambda x: x.table_number):
            writer.writerow([
                rnd.number, p.table_number,
                reg_names.get(p.player_a_registration_id, "?"),
                reg_names.get(p.player_b_registration_id, "BYE") if p.player_b_registration_id else "BYE",
                p.result, p.match_wins_a, p.match_wins_b, p.draws,
            ])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="torneo-{tournament_id}-risultati.csv"'},
    )


@router.get("/warnings/mine", response_model=dict[int, list[WarningOut]])
def my_warnings(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> dict[int, list[WarningOut]]:
    """Gli avvisi di tutti i propri tornei aperti, in una chiamata: la lista
    eventi mostra il contatore su ogni scheda."""
    tournaments = db.scalars(
        select(Tournament).where(
            managed_tournaments(organizer, db),
            Tournament.status.not_in([TournamentStatus.COMPLETED, TournamentStatus.CANCELLED]),
        )
    ).all()
    ctx = build_context(list(tournaments), db)
    found = {t.id: tournament_warnings(t, ctx) for t in tournaments}
    return {tid: items for tid, items in found.items() if items}


@router.get("/{tournament_id}/warnings", response_model=list[WarningOut])
def warnings_for_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[WarningOut]:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    return tournament_warnings(tournament, build_context([tournament], db))


@router.get("/reports/mine", response_model=list[TournamentReportOut])
def my_reports(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[TournamentReportOut]:
    """Report incassi/presenze per tutti i tornei dell'organizzatore."""
    tournaments = db.scalars(
        select(Tournament).where(managed_tournaments(organizer, db))
    ).all()
    reports = []
    for tournament in tournaments:
        regs = db.scalar(
            select(func.count(Registration.id)).where(
                Registration.tournament_id == tournament.id,
                Registration.waitlisted == False,  # noqa: E712
            )
        ) or 0
        paid = db.scalar(
            select(func.count(Payment.id))
            .join(Registration, Payment.registration_id == Registration.id)
            .where(
                Registration.tournament_id == tournament.id,
                Payment.status == PaymentStatus.PAID,
            )
        ) or 0
        reports.append(TournamentReportOut(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            starts_on=tournament.starts_on,
            format=tournament.format,
            registrations=regs,
            paid_count=paid,
            revenue_cents=paid * tournament.entry_fee_cents,
            currency=tournament.currency,
        ))
    reports.sort(key=lambda r: r.starts_on, reverse=True)
    return reports


def load_player_pairing(tournament_id: int, pairing_id: int, user: User, db: Session) -> Pairing:
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    participant_ids = {
        pairing.player_a.player_id,
        pairing.player_b.player_id if pairing.player_b else None,
    }
    if user.id not in participant_ids:
        raise HTTPException(status_code=403, detail="You are not seated at this table")
    if not pairing.round.is_published:
        raise HTTPException(status_code=409, detail="Pairing is not published")
    if pairing.result:
        raise HTTPException(status_code=409, detail="Result is already final")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="BYE results are automatic")
    return pairing


def player_registration_id_for_pairing(pairing: Pairing, user: User) -> int:
    if pairing.player_a.player_id == user.id:
        return pairing.player_a_registration_id
    if pairing.player_b and pairing.player_b.player_id == user.id:
        return pairing.player_b_registration_id
    raise HTTPException(status_code=403, detail="You are not seated at this table")


def latest_open_report(pairing_id: int, db: Session) -> PairingResultReport | None:
    return db.scalar(
        select(PairingResultReport)
        .where(
            PairingResultReport.pairing_id == pairing_id,
            PairingResultReport.status.in_([ResultReportStatus.PENDING, ResultReportStatus.CONFLICT]),
        )
        .order_by(PairingResultReport.created_at.desc(), PairingResultReport.id.desc())
    )


def latest_result_reports(tournament_id: int, db: Session) -> dict[int, dict]:
    """Restituisce {pairing_id: dict} con i dati del report più recente.

    Usa plain dict invece di oggetti SQLAlchemy per evitare DetachedInstanceError.
    Niente cache: con più worker Gunicorn la cache in-memory è per-processo e
    l'invalidazione non si propaga, così l'avversario non vedrebbe il report
    appena inserito. È una query piccola, la leggiamo sempre fresca.
    """
    reports = db.scalars(
        select(PairingResultReport)
        .join(Pairing)
        .join(Round)
        .where(Round.tournament_id == tournament_id)
        .options(
            selectinload(PairingResultReport.reporter).selectinload(Registration.player),
        )
        .order_by(PairingResultReport.created_at.asc(), PairingResultReport.id.asc())
    ).all()
    # Serializza subito — prima che la sessione si chiuda
    result: dict[int, dict] = {}
    for report in reports:
        reporter_name = ""
        if report.reporter and report.reporter.player:
            reporter_name = report.reporter.player.display_name
        result[report.pairing_id] = {
            "id": report.id,
            "status": report.status,
            "match_wins_a": report.match_wins_a,
            "match_wins_b": report.match_wins_b,
            "reporter_registration_id": report.reporter_registration_id,
            "reporter_name": reporter_name,
        }
    return result


def registration_out(registration: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=registration.id,
        tournament_id=registration.tournament_id,
        player_id=registration.player_id,
        archetype=registration.archetype,
        wizards_account=registration.wizards_account,
        checked_in=registration.checked_in,
        dropped=registration.dropped,
        waitlisted=registration.waitlisted,
        **_seating(registration),
        game_handle=registration.game_handle,
        online_link=registration.tournament.online_link if registration.tournament.is_online else "",
        player=registration.player,
        decklist_status=registration.decklist.status if registration.decklist else "missing",
        decklist_formats=sorted(d.format for d in registration.decklists),
        payment_status=registration.payment.status if registration.payment else "pending",
    )


def _seating(registration: Registration) -> dict:
    return {"pod": registration.pod, "pod_seat": registration.pod_seat, "fixed_table": registration.fixed_table,
            "team_id": registration.team_id, "team_seat": registration.team_seat,
            "team_name": registration.team.name if registration.team else None}


def organizer_registration_out(
    registration: Registration,
    tags: dict[int, list] | None = None,
    answers: dict[int, dict[int, str]] | None = None,
    prior: dict[int, int] | None = None,
) -> OrganizerRegistrationOut:
    base = registration_out(registration).model_dump()
    decklist = registration.decklist
    payment = registration.payment
    return OrganizerRegistrationOut(
        **base,
        player_email=registration.player.email,
        decklist_id=decklist.id if decklist else None,
        decklist_main_count=decklist.main_count if decklist else None,
        decklist_side_count=decklist.side_count if decklist else None,
        decklist_errors=decklist.validation_errors if decklist else "",
        decklist_raw_text=decklist.raw_text if decklist else "",
        payment_id=payment.id if payment else None,
        payment_provider=payment.provider if payment else None,
        decklist_revision_count=len(registration.decklist_revisions),
        tags=(tags or {}).get(registration.player_id, []),
        answers=(answers or {}).get(registration.id, {}),
        prize_note=registration.prize_note or "",
        prize_given_at=registration.prize_given_at,
        byes=registration.byes or 0,
        player_kind=registration.player.kind,
        prior_penalties=(prior or {}).get(registration.player_id, 0),
        guardian_name=registration.player.guardian.display_name if registration.player.guardian else None,
        guardian_email=registration.player.guardian.email if registration.player.guardian else None,
    )


# Dal piu forte al piu debole: serve a scegliere quando un utente ha due
# incarichi, uno sul torneo e uno sull'evento che lo contiene.
_STAFF_RANK = {StaffRole.HEAD_JUDGE: 2, StaffRole.JUDGE: 1}


def staff_role(tournament_id: int, user_id: int, db: Session) -> str | None:
    """Incarico giudicante dell'utente su questo torneo, None se non è nello staff.

    Conta anche la nomina sull'evento che contiene il torneo: a un weekend il
    capojudge si nomina una volta e vale su tutte le tappe. Se qualcuno ha due
    incarichi diversi vince il piu alto — una nomina non puo togliere poteri.
    """
    roles = [
        db.scalar(
            select(TournamentStaff.role).where(
                TournamentStaff.tournament_id == tournament_id,
                TournamentStaff.user_id == user_id,
            )
        )
    ]
    event_id = db.scalar(select(Tournament.event_id).where(Tournament.id == tournament_id))
    if event_id:
        roles.append(
            db.scalar(
                select(EventStaff.role).where(
                    EventStaff.event_id == event_id, EventStaff.user_id == user_id
                )
            )
        )
    found = [r for r in roles if r]
    return max(found, key=lambda r: _STAFF_RANK.get(r, 0)) if found else None


def is_tournament_staff(tournament_id: int, user_id: int, db: Session) -> bool:
    return staff_role(tournament_id, user_id, db) is not None


def tournament_role(tournament: Tournament, user: User, db: Session) -> str:
    """Che cosa è questo utente su questo torneo, dal più potente al meno potente."""
    if owns_tournament(tournament, user, db):
        return "organizer"
    role = staff_role(tournament.id, user.id, db)
    if role:
        return role
    is_registered = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament.id,
            Registration.player_id == user.id,
        )
    )
    return "player" if is_registered else "none"


def load_tournament_for_staff(tournament_id: int, user: User, db: Session) -> Tournament:
    """Torneo accessibile da organizzatore proprietario O capojudge O judge.

    Capojudge e judge hanno gli stessi poteri di campo — forzare un risultato, dare
    penalità, allungare il tempo di un tavolo — ma non possono eliminare il torneo
    né vedere i pagamenti (quelli restano dietro load_owned_tournament). Quello che
    distingue il capojudge è la nomina dei judge: vedi load_tournament_for_staff_admin.
    """
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if owns_tournament(tournament, user, db):
        return tournament
    if is_tournament_staff(tournament_id, user.id, db):
        return tournament
    raise HTTPException(status_code=404, detail="Tournament not found")


def owns_tournament(tournament: Tournament, user: User, db: Session) -> bool:
    """Proprietario del torneo, dell'evento che lo contiene, o nello staff del
    negozio che lo organizza."""
    if tournament.organizer_id == user.id:
        return True
    if store_role(user.id, tournament.organization_id, db):
        return True
    if not tournament.event_id:
        return False
    return db.scalar(
        select(Event.organizer_id).where(Event.id == tournament.event_id)
    ) == user.id


def load_tournament_for_head_judge(
    tournament_id: int, user: User, db: Session
) -> tuple[Tournament, bool]:
    """Torneo accessibile all'organizzatore proprietario o al capojudge.

    È il livello di chi comanda la sala: comporre lo staff e far scorrere i round.
    I judge semplici restano fuori — arbitrano i tavoli, non decidono la struttura
    del torneo. Il bool dice se chi chiama è il proprietario."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if owns_tournament(tournament, user, db):
        return tournament, True
    if staff_role(tournament_id, user.id, db) == StaffRole.HEAD_JUDGE:
        return tournament, False
    raise HTTPException(status_code=404, detail="Tournament not found")


def ensure_tournament_live(tournament: Tournament) -> None:
    """Un torneo chiuso non ha più round da far scorrere: niente timer, niente
    estensioni. Senza questo un restart resuscitava l'ends_at che la chiusura azzera,
    e il display in negozio ripartiva a contare su un torneo finito."""
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Il torneo è chiuso")


def ensure_head_judge_seat_free(
    tournament_id: int, db: Session, exclude_staff_id: int | None = None
) -> None:
    """Di capojudge ce n'è uno solo: la catena di comando deve essere inequivocabile."""
    stmt = select(TournamentStaff.id).where(
        TournamentStaff.tournament_id == tournament_id,
        TournamentStaff.role == StaffRole.HEAD_JUDGE,
    )
    if exclude_staff_id is not None:
        stmt = stmt.where(TournamentStaff.id != exclude_staff_id)
    if db.scalar(stmt):
        raise HTTPException(
            status_code=409,
            detail="C'è già un capojudge: rimuovilo o degradalo a judge prima di nominarne un altro",
        )


def staff_out(staff: TournamentStaff, user: User) -> StaffOut:
    return StaffOut(
        id=staff.id, user_id=user.id, role=staff.role,
        display_name=user.display_name, email=user.email,
    )


@router.get("/{tournament_id}/my-role", response_model=TournamentRoleOut)
def my_tournament_role(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TournamentRoleOut:
    """Che cosa può fare chi chiama su questo torneo — la UI ci costruisce sopra i
    controlli da mostrare."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    role = tournament_role(tournament, user, db)
    return TournamentRoleOut(
        role=role,
        can_manage_judges=role in {"organizer", StaffRole.HEAD_JUDGE},
    )


@router.post("/{tournament_id}/staff", response_model=StaffOut, status_code=201)
def add_staff(
    tournament_id: int,
    payload: StaffIn,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StaffOut:
    """Nomina un membro dello staff giudicante, per email.

    L'organizzatore nomina il capojudge (e, se vuole, anche dei judge); il capojudge
    nomina solo judge — non può scegliersi un pari grado né un successore.
    """
    tournament, is_owner = load_tournament_for_head_judge(tournament_id, actor, db)
    if payload.role == StaffRole.HEAD_JUDGE and not is_owner:
        raise HTTPException(status_code=403, detail="Solo l'organizzatore nomina il capojudge")
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Nessun utente registrato con questa email")
    if user.id == tournament.organizer_id:
        raise HTTPException(status_code=409, detail="È già l'organizzatore del torneo")
    if is_tournament_staff(tournament_id, user.id, db):
        raise HTTPException(status_code=409, detail="Utente già nello staff")
    if payload.role == StaffRole.HEAD_JUDGE:
        ensure_head_judge_seat_free(tournament_id, db)
    staff = TournamentStaff(tournament_id=tournament_id, user_id=user.id, role=payload.role)
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff_out(staff, user)


@router.get("/{tournament_id}/staff", response_model=list[StaffOut])
def list_staff(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StaffOut]:
    """Lo staff al completo, capojudge in testa. Lo vede anche il judge: deve sapere
    a chi escalare un ruling."""
    load_tournament_for_staff(tournament_id, user, db)
    members = db.scalars(
        select(TournamentStaff)
        .where(TournamentStaff.tournament_id == tournament_id)
        .options(joinedload(TournamentStaff.user))
    ).all()
    members = sorted(members, key=lambda m: (m.role != StaffRole.HEAD_JUDGE, m.id))
    return [staff_out(m, m.user) for m in members]


@router.patch("/{tournament_id}/staff/{staff_id}", response_model=StaffOut)
def update_staff_role(
    tournament_id: int,
    staff_id: int,
    payload: StaffRoleIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> StaffOut:
    """Promuove un judge a capojudge o lo degrada. Solo l'organizzatore: il capojudge
    non si nomina un successore da sé."""
    load_owned_tournament(tournament_id, organizer, db)
    staff = db.get(TournamentStaff, staff_id)
    if not staff or staff.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if payload.role == StaffRole.HEAD_JUDGE:
        ensure_head_judge_seat_free(tournament_id, db, exclude_staff_id=staff_id)
    staff.role = payload.role
    db.commit()
    db.refresh(staff)
    return staff_out(staff, staff.user)


@router.delete("/{tournament_id}/staff/{staff_id}", status_code=204)
def remove_staff(
    tournament_id: int,
    staff_id: int,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    _, is_owner = load_tournament_for_head_judge(tournament_id, actor, db)
    staff = db.get(TournamentStaff, staff_id)
    if not staff or staff.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if not is_owner and staff.role == StaffRole.HEAD_JUDGE:
        # Il capojudge rimuove i judge, non sé stesso: a revocare l'incarico è chi
        # l'ha conferito.
        raise HTTPException(status_code=403, detail="Solo l'organizzatore rimuove il capojudge")
    db.delete(staff)
    db.commit()


def load_owned_tournament(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))  # pairings non servono qui
    )
    if not tournament or not owns_tournament(tournament, organizer, db):
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


def load_registration_for_tournament(tournament_id: int, registration_id: int, db: Session) -> Registration:
    registration = db.scalar(
        select(Registration)
        .where(Registration.id == registration_id, Registration.tournament_id == tournament_id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklists),
            selectinload(Registration.decklist_revisions),
            selectinload(Registration.payment),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    return registration


def validate_pairing_registration(tournament_id: int, registration_id: int, db: Session) -> None:
    exists = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.id == registration_id,
            Registration.tournament_id == tournament_id,
            Registration.dropped == False,  # noqa: E712
        )
    )
    if not exists:
        raise HTTPException(status_code=422, detail="Registration is not eligible for this pairing")


def validate_manual_pairing_conflicts(pairing: Pairing, payload: ManualPairingIn, db: Session) -> None:
    requested_ids = {payload.player_a_registration_id}
    if payload.player_b_registration_id:
        requested_ids.add(payload.player_b_registration_id)
    round_pairings = db.scalars(
        select(Pairing).where(Pairing.round_id == pairing.round_id, Pairing.id != pairing.id)
    ).all()
    for existing in round_pairings:
        if existing.table_number == payload.table_number:
            raise HTTPException(status_code=409, detail="Table number is already in use")
        existing_ids = {existing.player_a_registration_id}
        if existing.player_b_registration_id:
            existing_ids.add(existing.player_b_registration_id)
        if requested_ids & existing_ids:
            raise HTTPException(status_code=409, detail="Player is already paired in this round")


def eligible_registrations(tournament: Tournament, db: Session) -> list[Registration]:
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament.id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklists),
            selectinload(Registration.payment),
        )
    ).all()
    return [
        registration
        for registration in registrations
        if registration.payment
        and registration.payment.status == PaymentStatus.PAID
        and not registration.dropped
        and not registration.waitlisted
        and (not tournament.check_in_required or registration.checked_in)
        and (
            not tournament.decklist_required
            or (registration.decklist and registration.decklist.status == DecklistStatus.VALID)
        )
    ]


NO_ROUNDS = "Evento di sola iscrizione: non ci sono turni. Quando è finito, chiudilo."


def create_round_for_tournament(tournament: Tournament, db: Session) -> RoundOut:
    if tournament.structure == TournamentStructure.REGISTRATION_ONLY:
        raise HTTPException(status_code=409, detail=NO_ROUNDS)
    eligible = eligible_registrations(tournament, db)
    if len(eligible) < 2:
        raise HTTPException(status_code=409, detail="At least two eligible players are required")

    current_round_number = len(tournament.rounds) + 1
    phase = next_phase(tournament, len(tournament.rounds), len(eligible))
    # Chi ha bye assegnati salta i primi turni della svizzera: li vince senza giocare.
    with_bye = [r for r in eligible if phase == "swiss" and (r.byes or 0) >= current_round_number]
    playing = [r for r in eligible if r not in with_bye]
    # A squadre si abbinano le squadre; ogni incontro sono i match posto contro
    # posto (A contro A, B contro B…), su tavoli vicini. Con la squadra in bye
    # ogni suo giocatore ha il bye. I bye assegnati ai singoli qui non valgono.
    if (tournament.team_size or 1) > 1:
        with_bye = []
        groups = team_round_groups(tournament, eligible, db)
    # In svizzera con i pod di draft ogni pod gioca per conto suo: al primo turno
    # contro chi siede di fronte, poi svizzera dentro il pod.
    elif phase == "swiss" and playing and all(r.pod for r in playing):
        groups = [pod_pair_order(tournament, [r for r in playing if r.pod == pod], db)
                  for pod in sorted({r.pod for r in playing})]
    else:
        groups = [pair_order(tournament, playing, phase, db)] if playing else []
    ordered = [r for group in groups for r in group]
    if phase in {"elimination", "topcut"} and len(ordered) < 2:
        tournament.status = TournamentStatus.COMPLETED
        db.add(tournament)
        db.commit()
        raise HTTPException(status_code=409, detail="Elimination bracket is complete")
    round_obj = Round(
        tournament_id=tournament.id,
        number=current_round_number,
        # Online-first: il round è subito pubblicato così i giocatori possono
        # inserire i propri risultati. `pairings_public` controlla separatamente
        # la visibilità sul display pubblico/TV, non la possibilità di refertare.
        phase=phase,
        is_published=True,
        # Il timer NON parte automaticamente: l'organizzatore lo avvia a mano
        # ("Avvia timer" in Regia). Finché ends_at è None il timer è fermo.
        starts_at=None,
        ends_at=None,
    )
    db.add(round_obj)
    db.flush()

    matches = [(group[i], group[i + 1] if i + 1 < len(group) else None)
               for group in groups for i in range(0, len(group), 2)]
    pairings = []
    for (player_a, player_b), table in zip(matches, assign_tables(matches), strict=True):
        pairing = Pairing(
            round_id=round_obj.id,
            table_number=table,
            player_a_registration_id=player_a.id,
            player_b_registration_id=player_b.id if player_b else None,
            result="A" if not player_b else "",
            match_wins_a=2 if not player_b else 0,
            match_wins_b=0,
        )
        db.add(pairing)
        pairings.append(pairing)
    for offset, registration in enumerate(with_bye, start=max([p.table_number for p in pairings], default=0) + 1):
        db.add(Pairing(round_id=round_obj.id, table_number=offset,
                       player_a_registration_id=registration.id, player_b_registration_id=None,
                       result="A", match_wins_a=2, match_wins_b=0))
    db.commit()
    db.refresh(round_obj)
    return round_out(round_obj)


def next_phase(tournament: Tournament, completed_rounds: int, player_count: int) -> str:
    if tournament.structure == TournamentStructure.SINGLE_ELIMINATION:
        return "elimination"
    if tournament.structure == TournamentStructure.SWISS_TOPCUT:
        swiss_rounds = tournament.swiss_rounds or default_swiss_rounds(player_count)
        return "topcut" if completed_rounds >= swiss_rounds else "swiss"
    return "swiss"


def pair_order(tournament: Tournament, eligible: list[Registration], phase: str, db: Session) -> list[Registration]:
    if phase in {"elimination", "topcut"}:
        advancing = elimination_advancers(tournament.id, phase, db)
        if advancing is not None:
            return advancing
        standings = calculate_standings(tournament.id, db)
        top_cut_size = tournament.top_cut_size if phase == "topcut" else len(eligible)
        seed_ids = [standing.registration_id for standing in standings[:top_cut_size]]
        seeded = [registration for registration_id in seed_ids for registration in eligible if registration.id == registration_id]
        return seed_for_elimination(seeded)

    if not tournament.rounds:
        shuffled = eligible[:]
        random.shuffle(shuffled)
        return shuffled

    standings = calculate_standings(tournament.id, db)
    by_id = {registration.id: registration for registration in eligible}
    ordered = [by_id[standing.registration_id] for standing in standings if standing.registration_id in by_id]
    ordered, bye = set_aside_bye(ordered, players_with_bye(tournament.id, db))
    return swiss_pair_order(ordered, previous_opponents(tournament.id, db)) + bye


def complete_teams(tournament: Tournament, eligible: list[Registration], db: Session) -> list[tuple[Team, list[Registration]]]:
    """Le squadre che possono giocare: tutti i posti occupati da giocatori pronti."""
    ready = {r.id: r for r in eligible}
    out = []
    for team in db.scalars(select(Team).where(Team.tournament_id == tournament.id).order_by(Team.id)):
        members = sorted((r for r in ready.values() if r.team_id == team.id), key=lambda r: r.team_seat or 0)
        if len(members) == tournament.team_size and [m.team_seat for m in members] == list(range(1, tournament.team_size + 1)):
            out.append((team, members))
    return out


def team_matches(tournament_id: int, db: Session) -> list:
    """Gli incontri fra squadre giocati finora, ricostruiti dai match individuali."""
    from backend.app.services.standings import TeamMatch

    team_of = dict(db.execute(
        select(Registration.id, Registration.team_id).where(Registration.tournament_id == tournament_id)
    ).all())
    grouped: dict[tuple, TeamMatch] = {}
    for rnd in db.scalars(select(Round).where(Round.tournament_id == tournament_id).options(selectinload(Round.pairings))):
        for p in rnd.pairings:
            ta = team_of.get(p.player_a_registration_id)
            tb = team_of.get(p.player_b_registration_id) if p.player_b_registration_id else None
            if ta is None:
                continue
            if tb is None:
                grouped.setdefault((rnd.id, ta, None), TeamMatch(a=ta, b=None))
                continue
            key = (rnd.id, *sorted((ta, tb)))
            match = grouped.setdefault(key, TeamMatch(a=key[1], b=key[2]))
            winner = {"A": ta, "B": tb}.get(p.result)
            if not p.result:
                match.complete = False
            if winner == match.a:
                match.seats_a += 1
            elif winner == match.b:
                match.seats_b += 1
    return list(grouped.values())


def team_round_groups(tournament: Tournament, eligible: list[Registration], db: Session) -> list[list[Registration]]:
    """Gli abbinamenti di un turno a squadre, come gruppi da due (un match) o
    da uno (un bye). Primo turno a caso, poi svizzera sulla classifica a squadre."""
    from backend.app.services.standings import compute_team_standings

    teams = complete_teams(tournament, eligible, db)
    if len(teams) < 2:
        raise HTTPException(status_code=409, detail="Servono almeno due squadre complete")
    by_id = {team.id: (team, members) for team, members in teams}
    played = team_matches(tournament.id, db)
    if not tournament.rounds:
        ordered = [team for team, _ in teams]
        random.shuffle(ordered)
    else:
        table = compute_team_standings({t.id: t.name for t, _ in teams}, played)
        ordered = [by_id[row["team_id"]][0] for row in table]
        ordered, bye = set_aside_bye(ordered, {m.a for m in played if m.b is None})
        previous = {tuple(sorted((m.a, m.b))) for m in played if m.b is not None}
        ordered = swiss_pair_order(ordered, previous) + bye
    groups: list[list[Registration]] = []
    for i in range(0, len(ordered), 2):
        home = by_id[ordered[i].id][1]
        away = by_id[ordered[i + 1].id][1] if i + 1 < len(ordered) else None
        if away is None:
            groups += [[member] for member in home]
        else:
            groups += [[a, b] for a, b in zip(home, away, strict=True)]
    return groups


def assign_tables(matches: list[tuple[Registration, Registration | None]]) -> list[int]:
    """I numeri di tavolo: chi ha un tavolo fisso gioca lì (se due lo chiedono,
    vince il primo), gli altri riempiono i numeri liberi in ordine."""
    fixed: dict[int, int] = {}
    for index, (a, b) in enumerate(matches):
        wanted = a.fixed_table or (b.fixed_table if b else None)
        if wanted and wanted not in fixed.values():
            fixed[index] = wanted
    used = set(fixed.values())
    tables, next_free = [], 1
    for index in range(len(matches)):
        if index in fixed:
            tables.append(fixed[index])
            continue
        while next_free in used:
            next_free += 1
        tables.append(next_free)
        used.add(next_free)
    return tables


def pod_pair_order(tournament: Tournament, members: list[Registration], db: Session) -> list[Registration]:
    """L'ordine di abbinamento dentro un pod. Al primo turno si gioca contro chi
    siede di fronte (posto 1 contro 5, 2 contro 6 in un pod da 8); con un pod
    dispari resta senza avversario l'ultimo della prima metà. Poi svizzera."""
    if tournament.rounds:
        return pair_order(tournament, members, "swiss", db)
    seated = sorted(members, key=lambda r: r.pod_seat or 0)
    half = (len(seated) + 1) // 2
    ordered: list[Registration] = []
    for i in range(half):
        if i + half < len(seated):
            ordered += [seated[i], seated[i + half]]
    return ordered + [r for r in seated[:half] if r not in ordered]


def players_with_bye(tournament_id: int, db: Session) -> set[int]:
    """Chi ha già avuto un bye, naturale o assegnato."""
    return set(db.scalars(
        select(Pairing.player_a_registration_id).join(Round)
        .where(Round.tournament_id == tournament_id, Pairing.player_b_registration_id.is_(None))
    ).all())


def set_aside_bye(ordered: list[Registration], had_bye: set[int]) -> tuple[list[Registration], list[Registration]]:
    """Con un numero dispari il bye va al più basso in classifica che non l'ha
    ancora avuto (se l'hanno avuto tutti, all'ultimo): lo si mette da parte prima
    di abbinare gli altri, così non finisce abbinato per sbaglio."""
    if len(ordered) % 2 == 0:
        return ordered, []
    chosen = next((r for r in reversed(ordered) if r.id not in had_bye), ordered[-1])
    return [r for r in ordered if r is not chosen], [chosen]


def elimination_advancers(tournament_id: int, phase: str, db: Session) -> list[Registration] | None:
    latest_phase_round = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase == phase)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number.desc())
    )
    if not latest_phase_round:
        return None
    if any(not pairing.result and pairing.player_b_registration_id for pairing in latest_phase_round.pairings):
        raise HTTPException(status_code=409, detail="Complete all current bracket results first")

    winners: list[Registration] = []
    for pairing in sorted(latest_phase_round.pairings, key=lambda item: item.table_number):
        if not pairing.player_b_registration_id or pairing.result == "A":
            winners.append(pairing.player_a)
        elif pairing.result == "B" and pairing.player_b:
            winners.append(pairing.player_b)
    return winners


def swiss_pair_order(ordered: list[Registration], previous: set[tuple[int, int]]) -> list[Registration]:
    remaining = ordered[:]
    pairs: list[Registration] = []
    while remaining:
        player = remaining.pop(0)
        opponent_index = 0
        for index, candidate in enumerate(remaining):
            if tuple(sorted((player.id, candidate.id))) not in previous:
                opponent_index = index
                break
        pairs.append(player)
        if remaining:
            pairs.append(remaining.pop(opponent_index))
    return pairs


def seed_for_elimination(seeded: list[Registration]) -> list[Registration]:
    ordered: list[Registration] = []
    left = 0
    right = len(seeded) - 1
    while left <= right:
        ordered.append(seeded[left])
        if left != right:
            ordered.append(seeded[right])
        left += 1
        right -= 1
    return ordered


def previous_opponents(tournament_id: int, db: Session) -> set[tuple[int, int]]:
    pairs = db.scalars(select(Pairing).join(Round).where(Round.tournament_id == tournament_id)).all()
    return {
        tuple(sorted((pairing.player_a_registration_id, pairing.player_b_registration_id)))
        for pairing in pairs
        if pairing.player_b_registration_id
    }


def ensure_latest_round_has_results(tournament_id: int, db: Session) -> None:
    latest_round = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(selectinload(Round.pairings))
        .order_by(Round.number.desc())
    )
    if latest_round and any(
        not pairing.result and pairing.player_b_registration_id for pairing in latest_round.pairings
    ):
        raise HTTPException(status_code=409, detail="Complete all current round results first")


def decklists_locked(tournament: Tournament) -> bool:
    """Delega al modello: la regola vive accanto ai campi che la determinano."""
    return tournament.decklist_locked


def apply_pairing_result(
    tournament_id: int,
    pairing: Pairing,
    payload: PairingResultIn,
    db: Session,
) -> None:
    latest_round_number = db.scalar(
        select(func.max(Round.number)).where(Round.tournament_id == tournament_id)
    )
    if latest_round_number and pairing.round.number < latest_round_number:
        raise HTTPException(status_code=409, detail="This result is locked because a later round exists")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="BYE results are automatic")
    ensure_allowed_score(payload, pairing, db)
    pairing.match_wins_a = payload.match_wins_a
    pairing.match_wins_b = payload.match_wins_b
    pairing.draws = payload.draws
    if payload.match_wins_a > payload.match_wins_b:
        pairing.result = "A"
    elif payload.match_wins_b > payload.match_wins_a:
        pairing.result = "B"
    else:
        pairing.result = "D"
    db.commit()


def ensure_allowed_score(payload: PairingResultIn, pairing: Pairing, db: Session) -> None:
    """Il punteggio deve essere possibile nel formato del match: al meglio di 1, 2
    o 3 in svizzera; nei playoff sempre al meglio di 3 e senza patta."""
    phase, best_of = db.execute(
        select(Round.phase, Tournament.best_of)
        .join(Tournament, Tournament.id == Round.tournament_id)
        .where(Round.id == pairing.round_id)
    ).one()
    if phase != "swiss":
        allowed = {score for score in ALLOWED_SCORES[3] if score[0] != score[1]}
    else:
        allowed = ALLOWED_SCORES.get(best_of or 3, ALLOWED_SCORES[3])
    if (payload.match_wins_a, payload.match_wins_b) not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported match result")


def default_swiss_rounds(player_count: int) -> int:
    """Numero di turni svizzeri = ceil(log2(iscritti)).
    Es: 8→3, 16→4, 32→5, 64→6 (standard MTG). Minimo 1."""
    return max(1, math.ceil(math.log2(max(2, player_count))))


def planned_swiss_rounds(tournament: Tournament, eligible_count: int) -> int:
    """Turni svizzeri previsti per il torneo: override manuale se impostato,
    altrimenti calcolo automatico ceil(log2(iscritti))."""
    return tournament.swiss_rounds or default_swiss_rounds(eligible_count)


def calculate_standings(tournament_id: int, db: Session) -> list[StandingOut]:
    """La classifica del torneo, con gli spareggi del suo gioco (services/standings.py)."""
    from backend.app.services.standings import Match as StandingMatch
    from backend.app.services.standings import Player as StandingPlayer
    from backend.app.services.standings import compute_standings

    tournament = db.get(Tournament, tournament_id)
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(selectinload(Registration.player))
    ).all()
    pairings = db.scalars(select(Pairing).join(Round).where(Round.tournament_id == tournament_id)).all()
    swiss_rounds = db.scalar(
        select(func.count(Round.id)).where(Round.tournament_id == tournament_id, Round.phase == "swiss")
    ) or 0
    rows = compute_standings(
        [StandingPlayer(r.id, r.player.display_name, dropped=r.dropped) for r in registrations],
        [
            StandingMatch(p.player_a_registration_id, p.player_b_registration_id, p.result,
                          p.match_wins_a, p.match_wins_b, p.draws)
            for p in pairings
        ],
        system=get_game(tournament.game if tournament else None).tiebreakers,
        total_rounds=swiss_rounds,
    )
    return [StandingOut(**row) for row in rows]


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def round_out(
    round_obj: Round,
    report_map: dict[int, dict] | None = None,
    pairings: list[Pairing] | None = None,
) -> RoundOut:
    """Costruisce RoundOut da un Round SQLAlchemy.

    report_map deve essere dict[pairing_id, dict] (plain dict, non oggetti SQLAlchemy)
    per evitare DetachedInstanceError quando il risultato viene servito dalla cache.
    pairings, se fornito, sostituisce round_obj.pairings senza mutare la relazione ORM
    (assegnare round_obj.pairings dissocerebbe gli altri pairing dal round).
    """
    report_map = report_map or {}
    pairing_list = pairings if pairings is not None else round_obj.pairings
    return RoundOut(
        id=round_obj.id,
        tournament_id=round_obj.tournament_id,
        number=round_obj.number,
        phase=round_obj.phase,
        format=round_obj.format,
        is_published=round_obj.is_published,
        starts_at=round_obj.starts_at,
        ends_at=round_obj.ends_at,
        pairings=[
            PairingOut(
                id=pairing.id,
                table_number=pairing.table_number,
                player_a=pairing.player_a.player.display_name,
                player_a_registration_id=pairing.player_a_registration_id,
                player_b=pairing.player_b.player.display_name if pairing.player_b else None,
                player_b_registration_id=pairing.player_b_registration_id,
                result=pairing.result,
                match_wins_a=pairing.match_wins_a,
                match_wins_b=pairing.match_wins_b,
                draws=pairing.draws,
                extra_seconds=pairing.extra_seconds,
                assigned_judge_id=pairing.assigned_judge_id,
                assigned_judge_name=(
                    pairing.assigned_judge.display_name if pairing.assigned_judge else ""
                ),
                table_status=pairing.table_status or "playing",
                report_id=report_map[pairing.id]["id"] if pairing.id in report_map else None,
                report_status=report_map[pairing.id]["status"] if pairing.id in report_map else "",
                report_score=(
                    f"{report_map[pairing.id]['match_wins_a']}-{report_map[pairing.id]['match_wins_b']}"
                    if pairing.id in report_map
                    else ""
                ),
                report_reporter_registration_id=(
                    report_map[pairing.id]["reporter_registration_id"] if pairing.id in report_map else None
                ),
                report_reporter_name=(
                    report_map[pairing.id]["reporter_name"] if pairing.id in report_map else ""
                ),
            )
            for pairing in sorted(pairing_list, key=lambda item: item.table_number)
        ],
    )


# ── Gestione della sala: chi copre quale tavolo e come sta ────

def _load_pairing_for_staff(tournament_id: int, pairing_id: int, user: User, db: Session) -> Pairing:
    load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing).join(Round).where(
            Pairing.id == pairing_id, Round.tournament_id == tournament_id
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Tavolo non trovato")
    return pairing


@router.patch("/{tournament_id}/pairings/{pairing_id}/assign", response_model=RoundOut)
def assign_table(
    tournament_id: int,
    pairing_id: int,
    payload: TableAssignIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Assegna il tavolo a un judge, o lo libera con user_id nullo.

    A fine round serve sapere chi sta seguendo cosa: senza, due judge vanno
    allo stesso tavolo e un altro resta scoperto.
    """
    pairing = _load_pairing_for_staff(tournament_id, pairing_id, user, db)
    if payload.user_id is not None and not is_tournament_staff(tournament_id, payload.user_id, db):
        owner, store = db.execute(
            select(Tournament.organizer_id, Tournament.organization_id).where(Tournament.id == tournament_id)
        ).one()
        if payload.user_id != owner and not store_role(payload.user_id, store, db):
            raise HTTPException(status_code=422, detail="Il tavolo si assegna a chi è nello staff")
    pairing.assigned_judge_id = payload.user_id
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(db.get(Round, pairing.round_id), latest_result_reports(tournament_id, db))


@router.patch("/{tournament_id}/pairings/{pairing_id}/status", response_model=RoundOut)
def set_table_status(
    tournament_id: int,
    pairing_id: int,
    payload: TableStatusIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Stato manuale del tavolo. Quello deducibile — risultato presente, tempo
    extra, referto in conflitto — resta dedotto dai dati, non si scrive qui."""
    pairing = _load_pairing_for_staff(tournament_id, pairing_id, user, db)
    pairing.table_status = payload.status
    db.commit()
    return round_out(db.get(Round, pairing.round_id), latest_result_reports(tournament_id, db))


# ── Deck check ────────────────────────────────────────────────

def _deck_check_out(check: DeckCheck, rounds: dict[int, int]) -> DeckCheckOut:
    player = check.registration.player if check.registration else None
    return DeckCheckOut(
        id=check.id,
        registration_id=check.registration_id,
        player_name=player.display_name if player else "",
        round_number=rounds.get(check.round_id) if check.round_id else None,
        judge_name=check.judge.display_name if check.judge else "",
        result=check.result,
        note=check.note,
        created_at=check.created_at,
    )


@router.post("/{tournament_id}/deck-checks", response_model=DeckCheckOut, status_code=201)
def create_deck_check(
    tournament_id: int,
    payload: DeckCheckIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeckCheckOut:
    """Registra il controllo di una lista. Lo fa chiunque sia nello staff:
    il deck check è lavoro da judge, non da organizzatore."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    load_registration_for_tournament(tournament.id, payload.registration_id, db)
    latest = db.scalar(
        select(Round).where(Round.tournament_id == tournament_id).order_by(Round.number.desc())
    )
    check = DeckCheck(
        tournament_id=tournament_id,
        registration_id=payload.registration_id,
        round_id=latest.id if latest else None,
        judge_id=user.id,
        result=payload.result,
        note=payload.note.strip(),
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    rounds = {r.id: r.number for r in db.scalars(
        select(Round).where(Round.tournament_id == tournament_id)).all()}
    return _deck_check_out(check, rounds)


@router.get("/{tournament_id}/deck-checks", response_model=list[DeckCheckOut])
def list_deck_checks(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeckCheckOut]:
    """Storico dei controlli. Visibile a tutto lo staff: sapere che un tavolo è
    già stato controllato evita di rifarlo e di perdere tempo di round."""
    load_tournament_for_staff(tournament_id, user, db)
    checks = db.scalars(
        select(DeckCheck)
        .where(DeckCheck.tournament_id == tournament_id)
        .options(
            joinedload(DeckCheck.registration).joinedload(Registration.player),
            joinedload(DeckCheck.judge),
        )
        .order_by(DeckCheck.created_at.desc())
    ).all()
    rounds = {r.id: r.number for r in db.scalars(
        select(Round).where(Round.tournament_id == tournament_id)).all()}
    return [_deck_check_out(c, rounds) for c in checks]


# ── Day 2 e segmenti a formato diverso ────────────────────────

@router.post("/{tournament_id}/day2", response_model=list[Day2ConversionRow])
def set_day2(
    tournament_id: int,
    payload: Day2In,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[Day2ConversionRow]:
    """Segna chi passa alla seconda giornata. La lista sostituisce la precedente:
    rimandare l'elenco corretto ripara un import sbagliato senza azzerare a mano."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    registrations = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament.id)
    ).all()
    wanted = set(payload.registration_ids)
    unknown = wanted - {r.id for r in registrations}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Iscrizioni non di questo torneo: {sorted(unknown)[:5]}",
        )
    for reg in registrations:
        reg.day2 = reg.id in wanted
    db.commit()
    return day2_conversion(tournament_id, db)


@router.get("/{tournament_id}/day2/conversion", response_model=list[Day2ConversionRow])
def day2_conversion_endpoint(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[Day2ConversionRow]:
    load_owned_tournament(tournament_id, organizer, db)
    return day2_conversion(tournament_id, db)


def day2_conversion(tournament_id: int, db: Session) -> list[Day2ConversionRow]:
    """Quanti di ogni archetipo hanno passato il taglio. E la domanda che si fa
    la coverage: non quanti lo giocavano, ma quanti sono arrivati."""
    registrations = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament_id)
    ).all()
    agg: dict[str, dict] = {}
    for reg in registrations:
        arch = (reg.archetype or "").strip() or "Sconosciuto"
        row = agg.setdefault(arch, {"players": 0, "day2": 0})
        row["players"] += 1
        if reg.day2:
            row["day2"] += 1
    rows = [
        Day2ConversionRow(
            archetype=arch,
            players=v["players"],
            day2=v["day2"],
            conversion=round(v["day2"] / v["players"] * 100, 1) if v["players"] else 0.0,
        )
        for arch, v in agg.items()
    ]
    rows.sort(key=lambda r: (-r.conversion, -r.players))
    return rows


@router.patch("/{tournament_id}/rounds/{round_id}/format", response_model=RoundOut)
def set_round_format(
    tournament_id: int,
    round_id: int,
    payload: RoundFormatIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Formato del segmento: draft ai primi turni, constructed dopo. Nullo
    significa "il formato del torneo", che resta il caso normale."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    rnd = db.get(Round, round_id)
    if not rnd or rnd.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Round non trovato")
    rnd.format = (payload.format or "").strip() or None
    db.commit()
    db.refresh(rnd)
    return round_out(rnd, latest_result_reports(tournament_id, db))
