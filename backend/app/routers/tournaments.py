import random
from datetime import UTC, datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db import get_db
from backend.app.models import (
    Announcement,
    Decklist,
    DecklistRevision,
    DecklistStatus,
    Payment,
    PaymentStatus,
    Pairing,
    Penalty,
    Registration,
    Round,
    Tournament,
    InviteCode,
    RegistrationMode,
    TournamentStructure,
    TournamentStatus,
    User,
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
    PaymentOut,
    PairingResultIn,
    PenaltyCreate,
    PenaltyOut,
    PlayerCardOut,
    RegistrationCreate,
    RegistrationOut,
    RefundRequestIn,
    RefundDecisionIn,
    RoundOut,
    StandingOut,
    TournamentControlsIn,
    TournamentCreate,
    TournamentOut,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.core.config import get_settings
from backend.app.services.decklists import validate_card_legality, validate_decklist
from backend.app.services.email import event_announcement_html, send_email
from backend.app.services.payments import create_paypal_checkout, create_stripe_checkout, refund_paypal_capture

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


def tournament_with_counts(stmt: Select[tuple[Tournament]], db: Session) -> list[TournamentOut]:
    tournaments = db.scalars(stmt).all()
    counts = dict(
        db.execute(
            select(Registration.tournament_id, func.count(Registration.id)).group_by(
                Registration.tournament_id
            )
        ).all()
    )
    return [
        TournamentOut.model_validate(tournament).model_copy(
            update={"registered_players": counts.get(tournament.id, 0)}
        )
        for tournament in tournaments
    ]


@router.get("", response_model=list[TournamentOut])
def list_tournaments(db: Session = Depends(get_db)) -> list[TournamentOut]:
    stmt = select(Tournament).where(Tournament.status != TournamentStatus.CANCELLED)
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


@router.post("", response_model=TournamentOut, status_code=201)
def create_tournament(
    payload: TournamentCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> TournamentOut:
    tournament = Tournament(**payload.model_dump(), organizer_id=organizer.id)
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
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
    return create_round_for_tournament(tournament, db)


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
    db.commit()
    db.refresh(tournament)
    count = db.scalar(select(func.count(Registration.id)).where(Registration.tournament_id == tournament.id))
    return TournamentOut.model_validate(tournament).model_copy(update={"registered_players": count or 0})


@router.delete("/{tournament_id}", status_code=204)
def delete_tournament(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    round_ids = db.scalars(select(Round.id).where(Round.tournament_id == tournament.id)).all()
    if round_ids:
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
        select(func.count(Registration.id)).where(Registration.tournament_id == tournament_id)
    )
    if registered and registered >= tournament.capacity:
        raise HTTPException(status_code=409, detail="Tournament is full")
    existing = db.scalar(
        select(Registration).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already registered")
    registration = Registration(
        tournament_id=tournament_id,
        player_id=user.id,
        wizards_account=payload.wizards_account,
    )
    db.add(registration)
    db.commit()
    db.refresh(registration)
    return registration_out(registration)


@router.get("/{tournament_id}/registrations", response_model=list[OrganizerRegistrationOut])
def list_registrations(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[OrganizerRegistrationOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Tournament not found")
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklist),
            selectinload(Registration.decklist_revisions),
            selectinload(Registration.payment),
        )
    ).all()
    return [organizer_registration_out(item) for item in registrations]


@router.get("/{tournament_id}/my-registration", response_model=RegistrationOut)
def my_registration(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegistrationOut:
    registration = db.scalar(
        select(Registration)
        .where(Registration.tournament_id == tournament_id, Registration.player_id == user.id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklist),
            selectinload(Registration.payment),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    return registration_out(registration)


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
            selectinload(Registration.player),
            selectinload(Registration.decklist),
            selectinload(Registration.payment),
            selectinload(Registration.tournament),
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
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Penalty:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    load_registration_for_tournament(tournament.id, payload.registration_id, db)
    penalty = Penalty(
        tournament_id=tournament.id,
        registration_id=payload.registration_id,
        judge_id=organizer.id,
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
    load_owned_tournament(tournament_id, organizer, db)
    registration = load_registration_for_tournament(tournament_id, registration_id, db)
    registration.dropped = dropped
    db.commit()
    db.refresh(registration)
    return organizer_registration_out(registration)


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
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.organizer_id != user.id and not tournament.standings_public:
        return []
    return calculate_standings(tournament_id, db)


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
    if not is_organizer:
        rounds = [round_obj for round_obj in rounds if round_obj.is_published and tournament.pairings_public]
    return [round_out(round_obj) for round_obj in rounds]


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
            f"{frontend_url}/sandbox-checkout?payment_id={payment.id}&provider={payload.provider}"
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
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if tournament.status != TournamentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Start the tournament before creating rounds")
    ensure_latest_round_has_results(tournament_id, db)
    return create_round_for_tournament(tournament, db)


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
    apply_pairing_result(tournament_id, pairing, payload, db)
    db.refresh(pairing.round)
    return round_out(pairing.round)


@router.patch("/{tournament_id}/pairings/{pairing_id}/player-result", response_model=RoundOut)
def report_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .join(Tournament)
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
    apply_pairing_result(tournament_id, pairing, payload, db)
    db.refresh(pairing.round)
    return round_out(pairing.round)


def registration_out(registration: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=registration.id,
        tournament_id=registration.tournament_id,
        player_id=registration.player_id,
        archetype=registration.archetype,
        wizards_account=registration.wizards_account,
        checked_in=registration.checked_in,
        dropped=registration.dropped,
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


def load_owned_tournament(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds).selectinload(Round.pairings))
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
    starts_at = datetime.now(UTC)
    round_obj = Round(
        tournament_id=tournament.id,
        number=current_round_number,
        phase=phase,
        is_published=tournament.pairings_public,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=tournament.round_timer_minutes),
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
    allowed_scores = {(0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (0, 2), (2, 1), (1, 2)}
    if (payload.match_wins_a, payload.match_wins_b) not in allowed_scores:
        raise HTTPException(status_code=422, detail="Unsupported match result")
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


def default_swiss_rounds(player_count: int) -> int:
    if player_count <= 8:
        return 3
    if player_count <= 16:
        return 4
    if player_count <= 32:
        return 5
    if player_count <= 64:
        return 6
    if player_count <= 128:
        return 7
    if player_count <= 226:
        return 8
    return 9


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


def round_out(round_obj: Round) -> RoundOut:
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
            )
            for pairing in sorted(round_obj.pairings, key=lambda item: item.table_number)
        ],
    )
