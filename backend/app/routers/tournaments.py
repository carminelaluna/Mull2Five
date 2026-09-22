"""
tournaments.py — Il torneo come oggetto: crearlo, cambiarlo, aprirlo, chiuderlo.

Qui c'e il torneo in se: la ricerca pubblica e gli elenchi di chi organizza e
di chi gioca, la creazione (anche copiando, ripetendo o importando un
calendario), le modifiche, l'avvio e la chiusura, gli annunci, i soldi
(pagamento e rimborsi), i report e le esportazioni, gli avvisi e lo staff.

Chi si iscrive sta in tournament_registrations.py, il torneo mentre si gioca in
tournament_rounds.py, e quello che si calcola senza rispondere a una richiesta
sotto backend/app/services/.
"""
import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.core.tenant import requested_org
from backend.app.db import get_db
from backend.app.games import get_game, is_enabled, online_platform
from backend.app.models import (
    Announcement,
    AnnouncementRecipient,
    Decklist,
    DecklistRevision,
    Event,
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
    Round,
    StaffRole,
    Tournament,
    TournamentSeries,
    TournamentStaff,
    TournamentStatus,
    TournamentStructure,
    User,
)
from backend.app.schemas import (
    AnnouncementAudienceOut,
    AnnouncementCreate,
    AnnouncementOut,
    CheckoutCreate,
    MyRegistrationOut,
    OfficialReportOut,
    OfficialReportRowOut,
    OrganizedTournamentRow,
    PaymentOut,
    PlayerHistoryRowOut,
    PlayerPublicProfileOut,
    RefundDecisionIn,
    RefundRequestIn,
    RepeatIn,
    RepeatPreviewOut,
    RoundOut,
    ScheduleImportIn,
    ScheduleImportOut,
    ScheduleRowOut,
    StaffIn,
    StaffOut,
    StaffRoleIn,
    TournamentControlsIn,
    TournamentCreate,
    TournamentOut,
    TournamentReportOut,
    TournamentRoleOut,
    TournamentUpdate,
    WarningOut,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.audit import write_audit
from backend.app.services.email import event_announcement_html, send_email
from backend.app.services.pairings import (
    NO_ROUNDS,
    calculate_standings,
    create_round_for_tournament,
    eligible_registrations,
)
from backend.app.services.payments import (
    create_paypal_checkout,
    create_stripe_checkout,
    refund_paypal_capture,
)
from backend.app.services.registrations import (
    promote_from_waitlist,
)
from backend.app.services.schedule_import import parse_schedule_csv
from backend.app.services.stores import managed_tournaments
from backend.app.services.tournament_access import (
    ensure_head_judge_seat_free,
    is_tournament_staff,
    load_owned_tournament,
    load_tournament_for_head_judge,
    load_tournament_for_staff,
    owns_tournament,
    staff_out,
    tournament_role,
)
from backend.app.services.tournament_views import (
    bounding_box,
    filter_by_distance,
    registration_out,
    tournament_out,
    tournament_with_counts,
)
from backend.app.services.warnings import build_context, tournament_warnings

router = APIRouter(prefix="/tournaments", tags=["tournaments"])



def check_location(location_id: int | None, organizer: User, db: Session) -> None:
    """La sede dev'essere del negozio di chi organizza: non si gioca a casa d'altri."""
    if not location_id:
        return
    from backend.app.routers.tags import org_id_for

    location = db.get(Location, location_id)
    if not location or location.organization_id != org_id_for(organizer, db):
        raise HTTPException(status_code=404, detail="Sede non trovata")


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
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
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
    # Cerca vicino: prima si scartano in SQL quelli fuori dal riquadro, poi si
    # calcola la distanza vera solo sui rimasti (i tornei senza coordinate
    # proprie le ereditano dal negozio, quindi restano in gioco).
    if near_lat is not None and near_lng is not None and radius_km is not None:
        south, north, west, east = bounding_box(near_lat, near_lng, radius_km)
        stmt = stmt.where(or_(
            Tournament.latitude.is_(None),
            and_(Tournament.latitude.between(south, north), Tournament.longitude.between(west, east)),
        ))
    stmt = stmt.order_by(Tournament.starts_on.asc()).limit(limit).offset(offset)
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


@router.get("/me/registrations", response_model=list[MyRegistrationOut])
def my_registrations_list(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MyRegistrationOut]:
    """Le iscrizioni di chi chiama, con il loro torneo: una richiesta sola.
    Prima la pagina chiedeva tutti i tornei e poi la propria iscrizione a uno a
    uno: con molti tornei erano centinaia di richieste, e il limite per IP le
    bloccava."""
    registrations = db.scalars(
        select(Registration)
        .where(Registration.player_id == user.id)
        .options(
            joinedload(Registration.player),
            joinedload(Registration.decklists),
            joinedload(Registration.payment),
            joinedload(Registration.tournament),
        )
    ).unique().all()
    if not registrations:
        return []
    ids = {reg.tournament_id for reg in registrations}
    tournaments = {t.id: t for t in tournament_with_counts(select(Tournament).where(Tournament.id.in_(ids)), db)}
    rows = [
        MyRegistrationOut(tournament=tournaments[reg.tournament_id], registration=registration_out(reg))
        for reg in registrations if reg.tournament_id in tournaments
    ]
    # I tornei più vicini per primi, come li legge la pagina.
    rows.sort(key=lambda row: (row.tournament.starts_on, row.tournament.start_time or ""), reverse=True)
    return rows


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


@router.get("/players/{public_id}/public-history", response_model=PlayerPublicProfileOut)
def player_public_history(
    public_id: str,
    db: Session = Depends(get_db),
) -> PlayerPublicProfileOut:
    """Profilo pubblico di un giocatore: storico e statistiche aggregate, calcolate
    solo dai tornei con classifica pubblica. Nessuna autenticazione richiesta.

    Si cerca per identificativo pubblico, non per email: un link condiviso non
    rivela l'indirizzo di nessuno e non si può chiedere "questa email gioca?"."""
    player = db.scalar(select(User).where(User.public_id == public_id))
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
        display_name=player.display_name, public_id=player.public_id, role=player.role,
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


SCHEDULE_LIMIT = 200
# Il campo di TournamentCreate che non va, detto come nel file.
SCHEDULE_FIELDS = {"name": "il nome (almeno 3 lettere)", "format": "il formato", "capacity": "i posti (almeno 2)",
                   "entry_fee_cents": "la quota", "start_time": "l'orario", "starts_on": "la data"}


@router.post("/import-schedule", response_model=ScheduleImportOut)
def import_schedule(
    payload: ScheduleImportIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> ScheduleImportOut:
    """Il calendario del negozio da un file, un torneo per riga: EventLink non lo
    esporta, così lo si porta qui da un foglio di calcolo. Ogni riga passa gli
    stessi controlli di «Nuovo evento». Una riga con lo stesso nome e la stessa
    data di un torneo del negozio non crea un doppione, quindi si può ricaricare
    lo stesso file. Con dry_run dice cosa creerebbe, senza toccare niente."""
    from pydantic import ValidationError

    from backend.app.core.cache import cache_invalidate

    check_location(payload.location_id, organizer, db)
    game = get_game("mtg")
    try:
        parsed = parse_schedule_csv(payload.csv_text, game.formats)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(parsed) > SCHEDULE_LIMIT:
        raise HTTPException(status_code=422, detail=f"Al massimo {SCHEDULE_LIMIT} righe per volta")

    mine = (Tournament.organization_id == organizer.organization_id if organizer.organization_id
            else Tournament.organizer_id == organizer.id)
    existing = {(name.strip().lower(), day) for name, day in db.execute(
        select(Tournament.name, Tournament.starts_on).where(mine, Tournament.status != TournamentStatus.CANCELLED)
    ).all()}
    today = local_today()
    rows: list[ScheduleRowOut] = []
    planned: list[TournamentCreate] = []
    for item in parsed:
        row = ScheduleRowOut(
            line=item.line, name=item.name, starts_on=item.starts_on, start_time=item.start_time,
            format=item.format, entry_fee_cents=item.entry_fee_cents or 0,
            capacity=item.capacity or payload.capacity, outcome="new",
        )
        rows.append(row)
        if item.error:
            row.outcome, row.detail = "error", item.error
            continue
        if item.starts_on < today:
            row.outcome, row.detail = "error", "La data è già passata"
            continue
        key = (item.name.strip().lower(), item.starts_on)
        if key in existing:
            row.outcome, row.detail = "already", "Già in calendario"
            continue
        try:
            planned.append(TournamentCreate(
                name=item.name, format=item.format, game=game.code, event_type=item.event_type,
                rules_enforcement_level=item.rules_enforcement_level or "Regular",
                starts_on=item.starts_on, start_time=item.start_time, capacity=row.capacity,
                entry_fee_cents=row.entry_fee_cents, description=item.description,
                location_id=payload.location_id, venue="" if payload.location_id else payload.venue,
                status="published" if payload.publish else "draft",
                decklist_required=payload.decklist_required,
            ))
        except ValidationError as exc:
            field_name = str(exc.errors()[0]["loc"][0]) if exc.errors()[0]["loc"] else ""
            row.outcome, row.detail = "error", f"Controlla {SCHEDULE_FIELDS.get(field_name, field_name or 'la riga')}"
            continue
        existing.add(key)   # la stessa riga due volte nel file conta una

    if not payload.dry_run and planned:
        db.add_all([Tournament(**data.model_dump(), organizer_id=organizer.id,
                               organization_id=organizer.organization_id) for data in planned])
        db.commit()
        cache_invalidate("tournaments:")
    return ScheduleImportOut(rows=rows, new=len(planned), skipped=len(rows) - len(planned))


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
        raise HTTPException(status_code=404, detail="Torneo non trovato")
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
        raise HTTPException(status_code=409, detail="Il torneo è già iniziato o chiuso")
    if len(eligible_registrations(tournament, db)) < 2:
        raise HTTPException(status_code=409, detail="Servono almeno due giocatori idonei")
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
        raise HTTPException(status_code=409, detail="Un torneo annullato non si può chiudere")
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
    write_audit(db, tournament.id, organizer.id, "tournament_updated", detail[:1000])
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
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    is_registered = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    is_staff = owns_tournament(tournament, user, db) or is_tournament_staff(tournament_id, user.id, db)
    if not is_staff and not is_registered:
        raise HTTPException(status_code=403, detail="Serve l'accesso a questo torneo")
    stmt = select(Announcement).where(Announcement.tournament_id == tournament_id)
    if not is_staff:
        # Un annuncio mirato lo legge solo chi era fra i destinatari: filtrarlo
        # sull'invio e lasciarlo poi in pagina per tutti non lo renderebbe mirato.
        miei = select(AnnouncementRecipient.announcement_id).where(
            AnnouncementRecipient.user_id == user.id
        )
        stmt = stmt.where(Announcement.targeted.is_(False) | Announcement.id.in_(miei))
    return db.scalars(stmt.order_by(Announcement.created_at.desc())).all()




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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
        raise HTTPException(status_code=404, detail="Pagamento non trovato")
    if registration.payment.status != PaymentStatus.PAID:
        raise HTTPException(status_code=409, detail="Il rimborso si chiede solo per un'iscrizione pagata")
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
        raise HTTPException(status_code=404, detail="Pagamento non trovato")
    if payment.status not in {PaymentStatus.PAID, PaymentStatus.REFUND_REQUESTED}:
        raise HTTPException(status_code=409, detail="Questo pagamento non si può rimborsare")
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


@router.get("/{tournament_id}/ical")
def tournament_ical(tournament_id: int, db: Session = Depends(get_db)) -> Response:
    """File .ics per 'Aggiungi al calendario' — pubblico."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.status == TournamentStatus.CANCELLED:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
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
        raise HTTPException(status_code=404, detail="Torneo non trovato")
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
        raise HTTPException(status_code=404, detail="Membro dello staff non trovato")
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
        raise HTTPException(status_code=404, detail="Membro dello staff non trovato")
    if not is_owner and staff.role == StaffRole.HEAD_JUDGE:
        # Il capojudge rimuove i judge, non sé stesso: a revocare l'incarico è chi
        # l'ha conferito.
        raise HTTPException(status_code=403, detail="Solo l'organizzatore rimuove il capojudge")
    db.delete(staff)
    db.commit()
