import csv
import io
import math
import random
from datetime import UTC, date, datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, joinedload, selectinload  # noqa: F401

from backend.app.core.config import get_settings
from backend.app.core.tenant import resolve_org
from backend.app.db import get_db
from backend.app.models import (
    Announcement,
    Decklist,
    DecklistRevision,
    DecklistStatus,
    InviteCode,
    Organization,
    Pairing,
    PairingResultReport,
    Payment,
    PaymentStatus,
    Penalty,
    Registration,
    RegistrationMode,
    ResultReportStatus,
    Round,
    Tournament,
    TournamentStaff,
    TournamentStatus,
    TournamentStructure,
    User,
    UserRole,
)
from backend.app.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    BracketMatchOut,
    CheckoutCreate,
    DecklistCreate,
    DecklistOut,
    InviteCodeCreate,
    InviteCodeOut,
    ManualPairingIn,
    OrganizerRegistrationOut,
    PairingOut,
    PairingResultIn,
    PairingResultRejectIn,
    PaymentOut,
    PenaltyCreate,
    PenaltyOut,
    PlayerCardOut,
    PlayerHistoryRowOut,
    PlayerPublicProfileOut,
    PublicDisplayOut,
    PublicPairingOut,
    RefundDecisionIn,
    RefundRequestIn,
    RegistrationCreate,
    RegistrationOut,
    RoundOut,
    StaffIn,
    StaffOut,
    StandingOut,
    TableExtendIn,
    TimerExtendIn,
    TimerRestartIn,
    TournamentControlsIn,
    TournamentCreate,
    TournamentOut,
    TournamentReportOut,
    WalkInIn,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.decklists import validate_card_legality, validate_decklist
from backend.app.services.email import event_announcement_html, send_email
from backend.app.services.payments import (
    create_paypal_checkout,
    create_stripe_checkout,
    refund_paypal_capture,
)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


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
        TournamentOut.model_validate(tournament).model_copy(
            update={"registered_players": int(reg_count)}
        )
        for tournament, reg_count in rows
    ]


@router.get("", response_model=list[TournamentOut])
def list_tournaments(
    org: Organization | None = Depends(resolve_org),
    name: str | None = None,
    format: str | None = None,
    venue: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[TournamentOut]:
    """Elenco pubblico tornei del negozio (tenant), con filtri di ricerca.
    `status` accetta valori multipli separati da virgola (es. published,running)."""
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
    if venue:
        stmt = stmt.where(Tournament.venue.ilike(f"%{venue}%"))
    if date_from:
        stmt = stmt.where(Tournament.starts_on >= date_from)
    if date_to:
        stmt = stmt.where(Tournament.starts_on <= date_to)
    stmt = stmt.order_by(Tournament.starts_on.asc())
    return tournament_with_counts(stmt, db)


@router.get("/mine", response_model=list[TournamentOut])
def my_tournaments(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TournamentOut]:
    organizer_stmt = select(Tournament).where(Tournament.organizer_id == user.id)
    registered_stmt = (
        select(Tournament)
        .join(Registration)
        .where(Registration.player_id == user.id)
        .distinct()
    )
    ids = {item.id for item in db.scalars(organizer_stmt).all()}
    ids.update(item.id for item in db.scalars(registered_stmt).all())
    if not ids:
        return []
    return tournament_with_counts(select(Tournament).where(Tournament.id.in_(ids)), db)


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
            record=mine.record, points=mine.points,
        ))
    rows.sort(key=lambda r: str(r.starts_on), reverse=True)
    return PlayerPublicProfileOut(
        display_name=player.display_name, email=player.email,
        tournaments_played=len(rows), total_points=tot_pts,
        wins=wins, draws=draws, losses=losses, rows=rows,
    )


@router.post("/{tournament_id}/duplicate", response_model=TournamentOut, status_code=201)
def duplicate_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    """Duplica un torneo (stesse impostazioni, data +7 giorni, senza iscritti né round).
    Utile per gli eventi ricorrenti (es. FNM ogni venerdì)."""
    src = load_owned_tournament(tournament_id, organizer, db)
    copy = Tournament(
        organizer_id=organizer.id,
        name=src.name,
        format=src.format,
        rules_enforcement_level=src.rules_enforcement_level,
        venue=src.venue,
        starts_on=src.starts_on + timedelta(days=7),
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
        pay_at_event=src.pay_at_event,
        pay_stripe=src.pay_stripe,
        pay_paypal=src.pay_paypal,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate("tournaments:")
    return TournamentOut.model_validate(copy).model_copy(update={"registered_players": 0})


@router.post("", response_model=TournamentOut, status_code=201)
def create_tournament(
    payload: TournamentCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
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
    return TournamentOut.model_validate(tournament).model_copy(update={"registered_players": 0})


@router.get("/{tournament_id}", response_model=TournamentOut)
def get_tournament(tournament_id: int, db: Session = Depends(get_db)) -> TournamentOut:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    count = db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament.id))
    return TournamentOut.model_validate(tournament).model_copy(update={"registered_players": count or 0})


@router.post("/{tournament_id}/start", response_model=RoundOut)
def start_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
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
    return TournamentOut.model_validate(tournament).model_copy(update={"registered_players": count or 0})


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
    # Torneo pieno → lista d'attesa invece di rifiuto
    registration = Registration(
        tournament_id=tournament_id,
        player_id=user.id,
        wizards_account=payload.wizards_account,
        waitlisted=is_full,
    )
    db.add(registration)
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
    if not tournament or tournament.organizer_id != organizer.id:
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
            selectinload(Registration.decklist),
            selectinload(Registration.payment),
            selectinload(Registration.decklist_revisions),  # conta revisioni senza N+1
        )
    ).all()
    result = [organizer_registration_out(item) for item in registrations]
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
            joinedload(Registration.decklist),
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
            joinedload(Registration.decklist),
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
            joinedload(Registration.decklist),
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


@router.post("/{tournament_id}/announcements", response_model=AnnouncementOut, status_code=201)
def create_announcement(
    tournament_id: int,
    payload: AnnouncementCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Announcement:
    load_owned_tournament(tournament_id, organizer, db)
    announcement = Announcement(
        tournament_id=tournament_id,
        author_id=organizer.id,
        title=payload.title,
        body=payload.body,
        send_email=payload.send_email,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    tournament = db.get(Tournament, tournament_id)
    if payload.send_email and tournament and tournament.email_notifications_enabled:
        recipients = db.scalars(
            select(User.email)
            .join(Registration, Registration.player_id == User.id)
            .where(Registration.tournament_id == tournament_id)
        ).all()
        for email in recipients:
            send_email(
                email,
                f"{tournament.name}: {payload.title}",
                payload.body,
                event_announcement_html(tournament.name, payload.title, payload.body),
            )
    # Notifica Web Push a tutti gli iscritti (no-op se VAPID non configurato)
    if tournament:
        from backend.app.services.notifications import push_to_tournament

        push_to_tournament(db, tournament_id, f"{tournament.name}: {payload.title}", payload.body)
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
    if tournament.organizer_id != user.id and not is_registered:
        raise HTTPException(status_code=403, detail="Tournament access required")
    return db.scalars(
        select(Announcement).where(Announcement.tournament_id == tournament_id).order_by(Announcement.created_at.desc())
    ).all()


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
    return penalty


@router.get("/{tournament_id}/penalties", response_model=list[PenaltyOut])
def list_penalties(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[Penalty]:
    tournament = load_owned_tournament(tournament_id, organizer, db)
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
    email = payload.email.lower()
    player = db.scalar(select(User).where(User.email == email))
    if not player:
        player = User(
            email=email,
            display_name=payload.display_name,
            role=UserRole.PLAYER,
            password_hash=None,
            is_active=True,
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
    return TournamentOut.model_validate(tournament).model_copy(update={"registered_players": count or 0})


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
    if tournament.organizer_id != user.id and not tournament.standings_public:
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
    is_organizer = tournament.organizer_id == user.id
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
        )
        .order_by(Round.number)
    ).all()
    report_map = latest_result_reports(tournament_id, db)
    if not is_organizer:
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

    return result


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
        .options(selectinload(Registration.tournament), selectinload(Registration.decklist))
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    if decklists_locked(registration.tournament):
        raise HTTPException(status_code=409, detail="Decklist submissions are locked")

    validation = validate_decklist(payload.raw_text, registration.tournament.format)
    registration.archetype = payload.archetype.strip()
    errors = validation.errors[:]
    if registration.tournament.legal_validation_enabled:
        errors.extend(validate_card_legality(payload.raw_text, registration.tournament.format))
    status = DecklistStatus.INVALID if errors else DecklistStatus.VALID
    decklist = registration.decklist or Decklist(registration_id=registration.id, raw_text="")
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

    session = (
        await create_stripe_checkout(registration)
        if payload.provider == "stripe"
        else await create_paypal_checkout(registration)
    )
    payment.provider_checkout_id = session.provider_checkout_id
    payment.checkout_url = session.checkout_url
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
        stripe.Refund.create(payment_intent=payment.provider_payment_id)
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
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
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
    if tournament.organizer_id != user.id and not tournament.pairings_public:
        return []
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase.in_(["elimination", "topcut"]))
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
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


@router.patch("/{tournament_id}/pairings/{pairing_id}/player-result", response_model=RoundOut)
def report_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    ensure_allowed_score(payload)
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
    load_tournament_for_staff(tournament_id, user, db)
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
    load_tournament_for_staff(tournament_id, user, db)
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
        f"UID:manabind-tournament-{tournament.id}@manabind\r\n"
        f"DTSTART;VALUE=DATE:{start}\r\n"
        f"SUMMARY:{_ical_escape(tournament.name)} ({_ical_escape(tournament.format)})\r\n"
        f"LOCATION:{_ical_escape(tournament.venue)}\r\n"
        f"DESCRIPTION:{_ical_escape(tournament.description or tournament.format)}\r\n"
        "END:VEVENT\r\n"
    )


@router.get("/{tournament_id}/ical")
def tournament_ical(tournament_id: int, db: Session = Depends(get_db)) -> Response:
    """File .ics per 'Aggiungi al calendario' — pubblico."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.status == TournamentStatus.CANCELLED:
        raise HTTPException(status_code=404, detail="Tournament not found")
    body = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Manabind//IT\r\n"
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
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Manabind//IT\r\n"
        "X-WR-CALNAME:Manabind — Tornei\r\n"
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


@router.get("/reports/mine", response_model=list[TournamentReportOut])
def my_reports(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[TournamentReportOut]:
    """Report incassi/presenze per tutti i tornei dell'organizzatore."""
    tournaments = db.scalars(
        select(Tournament).where(Tournament.organizer_id == organizer.id)
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
        player=registration.player,
        decklist_status=registration.decklist.status if registration.decklist else "missing",
        payment_status=registration.payment.status if registration.payment else "pending",
    )


def organizer_registration_out(registration: Registration) -> OrganizerRegistrationOut:
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
    )


def is_tournament_staff(tournament_id: int, user_id: int, db: Session) -> bool:
    return bool(db.scalar(
        select(func.count(TournamentStaff.id)).where(
            TournamentStaff.tournament_id == tournament_id,
            TournamentStaff.user_id == user_id,
        )
    ))


def load_tournament_for_staff(tournament_id: int, user: User, db: Session) -> Tournament:
    """Torneo accessibile da organizzatore proprietario O staff/judge invitato.

    Lo staff può inserire risultati e penalità ma non eliminare il torneo
    né vedere i pagamenti (quelli restano dietro load_owned_tournament).
    """
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.organizer_id == user.id:
        return tournament
    if is_tournament_staff(tournament_id, user.id, db):
        return tournament
    raise HTTPException(status_code=404, detail="Tournament not found")


@router.post("/{tournament_id}/staff", response_model=StaffOut, status_code=201)
def add_staff(
    tournament_id: int,
    payload: StaffIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> StaffOut:
    """Invita un utente come staff/judge del torneo (per email)."""
    load_owned_tournament(tournament_id, organizer, db)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Nessun utente registrato con questa email")
    if user.id == organizer.id:
        raise HTTPException(status_code=409, detail="Sei già l'organizzatore")
    if is_tournament_staff(tournament_id, user.id, db):
        raise HTTPException(status_code=409, detail="Utente già nello staff")
    staff = TournamentStaff(tournament_id=tournament_id, user_id=user.id)
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return StaffOut(
        id=staff.id, user_id=user.id,
        display_name=user.display_name, email=user.email,
    )


@router.get("/{tournament_id}/staff", response_model=list[StaffOut])
def list_staff(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[StaffOut]:
    load_owned_tournament(tournament_id, organizer, db)
    members = db.scalars(
        select(TournamentStaff)
        .where(TournamentStaff.tournament_id == tournament_id)
        .options(joinedload(TournamentStaff.user))
    ).all()
    return [
        StaffOut(
            id=m.id, user_id=m.user_id,
            display_name=m.user.display_name, email=m.user.email,
        )
        for m in members
    ]


@router.delete("/{tournament_id}/staff/{staff_id}", status_code=204)
def remove_staff(
    tournament_id: int,
    staff_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    load_owned_tournament(tournament_id, organizer, db)
    staff = db.get(TournamentStaff, staff_id)
    if not staff or staff.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Staff member not found")
    db.delete(staff)
    db.commit()


def load_owned_tournament(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))  # pairings non servono qui
    )
    if not tournament or tournament.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


def load_registration_for_tournament(tournament_id: int, registration_id: int, db: Session) -> Registration:
    registration = db.scalar(
        select(Registration)
        .where(Registration.id == registration_id, Registration.tournament_id == tournament_id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklist),
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
            selectinload(Registration.decklist),
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


def create_round_for_tournament(tournament: Tournament, db: Session) -> RoundOut:
    eligible = eligible_registrations(tournament, db)
    if len(eligible) < 2:
        raise HTTPException(status_code=409, detail="At least two eligible players are required")

    current_round_number = len(tournament.rounds) + 1
    phase = next_phase(tournament, len(tournament.rounds), len(eligible))
    ordered = pair_order(tournament, eligible, phase, db)
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

    pairings = []
    for index in range(0, len(ordered), 2):
        player_a = ordered[index]
        player_b = ordered[index + 1] if index + 1 < len(ordered) else None
        pairing = Pairing(
            round_id=round_obj.id,
            table_number=(index // 2) + 1,
            player_a_registration_id=player_a.id,
            player_b_registration_id=player_b.id if player_b else None,
            result="A" if not player_b else "",
            match_wins_a=2 if not player_b else 0,
            match_wins_b=0,
        )
        db.add(pairing)
        pairings.append(pairing)
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
    return swiss_pair_order(ordered, previous_opponents(tournament.id, db))


def elimination_advancers(tournament_id: int, phase: str, db: Session) -> list[Registration] | None:
    latest_phase_round = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase == phase)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
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
    if tournament.status in {TournamentStatus.RUNNING, TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        return True
    if tournament.decklist_deadline:
        deadline = tournament.decklist_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return datetime.now(UTC) > deadline
    return False


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
    ensure_allowed_score(payload)
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


def ensure_allowed_score(payload: PairingResultIn) -> None:
    allowed_scores = {(0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (0, 2), (2, 1), (1, 2)}
    if (payload.match_wins_a, payload.match_wins_b) not in allowed_scores:
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
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(selectinload(Registration.player))
    ).all()
    stats = {
        registration.id: {
            "registration": registration,
            "points": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "game_wins": 0,
            "game_losses": 0,
            "game_draws": 0,
            "opponents": [],
        }
        for registration in registrations
    }
    pairings = db.scalars(select(Pairing).join(Round).where(Round.tournament_id == tournament_id)).all()
    for pairing in pairings:
        a = stats.get(pairing.player_a_registration_id)
        b = stats.get(pairing.player_b_registration_id) if pairing.player_b_registration_id else None
        if not a:
            continue
        if not b:
            a["points"] += 3
            a["wins"] += 1
            a["game_wins"] += max(pairing.match_wins_a, 2)
            continue
        if not pairing.result:
            continue
        a["opponents"].append(pairing.player_b_registration_id)
        b["opponents"].append(pairing.player_a_registration_id)
        a["game_wins"] += pairing.match_wins_a
        a["game_losses"] += pairing.match_wins_b
        a["game_draws"] += pairing.draws
        b["game_wins"] += pairing.match_wins_b
        b["game_losses"] += pairing.match_wins_a
        b["game_draws"] += pairing.draws
        if pairing.result == "A":
            a["points"] += 3
            a["wins"] += 1
            b["losses"] += 1
        elif pairing.result == "B":
            b["points"] += 3
            b["wins"] += 1
            a["losses"] += 1
        else:
            a["points"] += 1
            b["points"] += 1
            a["draws"] += 1
            b["draws"] += 1

    match_win = {}
    game_win = {}
    for registration_id, item in stats.items():
        rounds_played = item["wins"] + item["losses"] + item["draws"]
        match_win[registration_id] = (
            max(item["points"] / (rounds_played * 3), 0.33) if rounds_played else 0.0
        )
        games = item["game_wins"] + item["game_losses"] + item["game_draws"]
        game_win[registration_id] = item["game_wins"] / games if games else 0.0

    rows = []
    for registration_id, item in stats.items():
        opponents = item["opponents"]
        omw = average([match_win[opponent_id] for opponent_id in opponents]) if opponents else 0.0
        ogw = average([game_win[opponent_id] for opponent_id in opponents]) if opponents else 0.0
        rows.append(
            StandingOut(
                position=0,
                registration_id=registration_id,
                name=item["registration"].player.display_name,
                pod=1,
                points=item["points"],
                record=f"{item['wins']}/{item['losses']}/{item['draws']}",
                match_win_percentage=round(match_win[registration_id] * 100, 1),
                opponent_match_win_percentage=round(omw * 100, 1),
                game_win_percentage=round(game_win[registration_id] * 100, 1),
                opponent_game_win_percentage=round(ogw * 100, 1),
            )
        )
    rows.sort(
        key=lambda row: (
            row.points,
            row.opponent_match_win_percentage,
            row.game_win_percentage,
            row.opponent_game_win_percentage,
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row.position = index
    return rows


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
