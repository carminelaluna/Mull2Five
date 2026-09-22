"""
tournament_registrations.py — Chi gioca: iscrizioni, liste, squadre e pod.

Iscriversi e disiscriversi, il check-in, i pagamenti segnati a mano, il
walk-in, l'import da file, le domande all'iscrizione, le penalita, i codici
invito, le liste dei mazzi, le squadre e i pod di draft. Le rotte stanno
sotto /tournaments come le altre: qui cambia solo il file.
"""
import math
import random
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.app.db import get_db
from backend.app.games import online_platform
from backend.app.models import (
    Decklist,
    DecklistRevision,
    DecklistStatus,
    InviteCode,
    Organization,
    Pairing,
    Payment,
    PaymentStatus,
    Penalty,
    Registration,
    RegistrationAnswer,
    RegistrationField,
    RegistrationMode,
    Round,
    Team,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)
from backend.app.schemas import (
    ByesIn,
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
    OrganizerRegistrationOut,
    PairingOut,
    PaymentOut,
    PenaltyCreate,
    PenaltyHistoryOut,
    PenaltyOut,
    PlayerCardOut,
    PodOut,
    PodSeatOut,
    PodsIn,
    PrizeIn,
    PublisherIdIn,
    RegistrationCreate,
    RegistrationFieldIn,
    RegistrationFieldOut,
    RegistrationOut,
    TeamIn,
    TeamMemberOut,
    TeamOut,
    TeamSeatIn,
    TeamStandingOut,
    WalkInIn,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.audit import write_audit
from backend.app.services.decklists import validate_card_legality, validate_decklist
from backend.app.services.pairings import (
    decklists_locked,
    eligible_registrations,
    team_matches,
)
from backend.app.services.player_import import parse_players_csv
from backend.app.services.registrations import (
    fields_of,
    prior_penalties,
    promote_from_waitlist,
)
from backend.app.services.stores import active_suspension
from backend.app.services.tournament_access import (
    load_owned_tournament,
    load_registration_for_tournament,
    load_tournament_for_staff,
    owns_tournament,
)
from backend.app.services.tournament_views import (
    organizer_registration_out,
    registration_out,
)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


CANCEL_REFUND_HOURS = 24   # rimborso automatico se l'annullamento è > 24h prima dell'inizio


IMPORT_LIMIT = 500


def _field_out(field: RegistrationField) -> RegistrationFieldOut:
    return RegistrationFieldOut(id=field.id, label=field.label, kind=field.kind,
                                options=field.option_list, required=field.required, position=field.position)


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


def _team_editable(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = load_owned_tournament(tournament_id, organizer, db)
    if (tournament.team_size or 1) < 2:
        raise HTTPException(status_code=409, detail="Il torneo non è a squadre")
    if tournament.status not in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Le squadre si compongono prima dell'inizio del torneo")
    return tournament


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


def answers_for(registration_ids: list[int], db: Session) -> dict[int, dict[int, str]]:
    out: dict[int, dict[int, str]] = {}
    if not registration_ids:
        return out
    for answer in db.scalars(
        select(RegistrationAnswer).where(RegistrationAnswer.registration_id.in_(registration_ids))
    ):
        out.setdefault(answer.registration_id, {})[answer.field_id] = answer.value
    return out


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


def prior_penalty_counts(tournament_id: int, player_ids: list[int], db: Session) -> dict[int, int]:
    if not player_ids:
        return {}
    counts: dict[int, int] = {}
    for _, player_id in db.execute(prior_penalties(player_ids, tournament_id)).all():
        counts[player_id] = counts.get(player_id, 0) + 1
    return counts


def save_answers(registration_id: int, answers: dict[int, str], db: Session) -> None:
    for field_id, value in answers.items():
        db.add(RegistrationAnswer(registration_id=registration_id, field_id=field_id, value=value))


def validate_answers(
    tournament_id: int, raw: dict[int, str | bool], db: Session, enforce_required: bool = True
) -> dict[int, str]:
    """Controlla le risposte contro le domande del torneo e le rende testo.
    Al banco le obbligatorie si possono lasciare vuote: decide chi iscrive."""
    fields = {f.id: f for f in fields_of(tournament_id, db)}
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


@router.get("/{tournament_id}/fields", response_model=list[RegistrationFieldOut])
def list_fields(tournament_id: int, db: Session = Depends(get_db)) -> list[RegistrationFieldOut]:
    """Le domande del torneo: pubbliche, servono al modulo d'iscrizione."""
    return [_field_out(f) for f in fields_of(tournament_id, db)]


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
    existing = {f.id: f for f in fields_of(tournament.id, db)}
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
    return [_field_out(f) for f in fields_of(tournament.id, db)]


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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
        raise HTTPException(status_code=404, detail="Torneo non disponibile")
    if tournament.registration_mode != RegistrationMode.OPEN:
        raise HTTPException(status_code=409, detail="Le iscrizioni sono chiuse")
    if tournament.status == TournamentStatus.RUNNING and not tournament.late_registration_enabled:
        raise HTTPException(status_code=409, detail="Le iscrizioni a torneo iniziato sono chiuse")
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
        raise HTTPException(status_code=409, detail="Sei già iscritto")
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
        raise HTTPException(status_code=404, detail="Torneo non trovato")

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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
    if not registration.tournament.self_check_in_enabled:
        raise HTTPException(status_code=409, detail="Il check-in da soli è spento")
    if registration.tournament.status not in {TournamentStatus.PUBLISHED, TournamentStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="Il check-in è chiuso")
    registration.checked_in = True
    db.commit()
    db.refresh(registration)
    return registration_out(registration)


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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
    if registration.dropped:
        raise HTTPException(status_code=409, detail="Ti sei già ritirato")
    tournament = registration.tournament
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Il torneo è chiuso")
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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
    rows = db.execute(prior_penalties([registration.player_id], tournament.id)).all()
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
        raise HTTPException(status_code=409, detail="Un torneo chiuso non si può modificare")
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
    write_audit(db, tournament.id, organizer.id, "unpaid_dropped", ", ".join(names)[:1000])
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
    write_audit(db, tournament.id, user.id, "fixed_table",
                 f"{registration.player.display_name}: " + (f"tavolo {payload.table}" if payload.table else "nessun tavolo fisso"))
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    return organizer_registration_out(load_registration_for_tournament(tournament_id, registration_id, db))


@router.get("/{tournament_id}/teams", response_model=list[TeamOut])
def list_teams(tournament_id: int, db: Session = Depends(get_db)) -> list[TeamOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
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
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    teams = {t.id: t.name for t in db.scalars(select(Team).where(Team.tournament_id == tournament.id))}
    return compute_team_standings(teams, team_matches(tournament.id, db))


@router.get("/{tournament_id}/pods", response_model=list[PodOut])
def list_pods(tournament_id: int, db: Session = Depends(get_db)) -> list[PodOut]:
    """I pod con i posti: pubblici, si leggono al tavolo del draft."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
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
    write_audit(db, tournament.id, organizer.id, "pods_created", f"{count} pod da {payload.pod_size} al massimo")
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
        write_audit(db, tournament.id, organizer.id, "byes_assigned",
                     f"{registration.player.display_name}: {payload.byes} bye")
        db.commit()
        cache_invalidate(f"registrations:{tournament.id}")
    return organizer_registration_out(load_registration_for_tournament(tournament_id, registration_id, db))


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
        write_audit(db, tournament.id, organizer.id, "prize_given",
                     f"{name}: {registration.prize_note or 'premio'}")
    elif registration.prize_given_at:
        write_audit(db, tournament.id, organizer.id, "prize_revoked",
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
        raise HTTPException(status_code=409, detail="Un torneo chiuso non accetta iscrizioni")
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
        raise HTTPException(status_code=409, detail="Il giocatore è già iscritto")
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
        raise HTTPException(status_code=409, detail="Un torneo chiuso non accetta iscrizioni")
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
        write_audit(db, tournament.id, organizer.id, "registrations_imported",
                     f"{added} iscritti, {waiting} in lista d'attesa, {len(rows) - added - waiting} saltati")
        db.commit()
        from backend.app.core.cache import cache_invalidate
        cache_invalidate(f"registrations:{tournament.id}")
        cache_invalidate("tournaments:")
    return ImportOut(rows=rows, added=added, waitlisted=waiting, skipped=len(rows) - added - waiting)


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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
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
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
    if decklists_locked(registration.tournament):
        raise HTTPException(status_code=409, detail="Le liste sono bloccate")

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
