"""
registrations.py — I pezzi sugli iscritti che servono a piu di un router.

Le domande di un torneo, quante penalita ha gia preso un giocatore e la
promozione dalla lista d'attesa: li usano sia il router del torneo sia quello
degli iscritti, quindi non possono stare ne in uno ne nell'altro.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from backend.app.core.cache import cache_invalidate
from backend.app.core.config import get_settings
from backend.app.models import (
    DiscountCode,
    Pairing,
    PaymentStatus,
    Penalty,
    Registration,
    RegistrationField,
    Tournament,
    TournamentStatus,
)
from backend.app.services.email import Sender, send_email
from backend.app.services.inbox import event_url, notify
from backend.app.services.payments import HOLD_GRACE_MINUTES, amount_due, payment_methods


def fields_of(tournament_id: int, db: Session) -> list[RegistrationField]:
    return list(db.scalars(
        select(RegistrationField).where(RegistrationField.tournament_id == tournament_id)
        .order_by(RegistrationField.position, RegistrationField.id)
    ).all())


def prior_penalties(player_ids: list[int], tournament_id: int):
    """Le penalità degli stessi giocatori negli altri tornei. Le note restano del
    torneo che le ha scritte: sono appunti dello staff, non penalità."""
    return (
        select(Penalty, Registration.player_id)
        .join(Registration, Registration.id == Penalty.registration_id)
        .where(Registration.player_id.in_(player_ids), Penalty.tournament_id != tournament_id, Penalty.kind != "note")
    )


WAITLIST_PAY_HOURS = 6   # ore per pagare online dopo la promozione dalla lista d'attesa (#32)


def must_pay_online(registration: Registration, tournament: Tournament) -> bool:
    """Chi entra dalla lista d'attesa deve pagare online per tenersi il posto?

    Solo allora ha WAITLIST_PAY_HOURS per farlo: c'è una quota, non l'ha ancora
    pagata, e il torneo non accetta il banco. Al banco o gratis il posto è suo e
    basta; prima tornava in coda ogni sei ore anche lì (24/11/2026).
    """
    if registration.payment and registration.payment.status == PaymentStatus.PAID:
        return False
    methods = payment_methods(tournament)
    return bool(methods) and "at_event" not in methods and amount_due(registration, tournament) > 0


def lock_seats(tournament_id: int, db: Session) -> None:
    """I posti di un torneo li conta una richiesta alla volta, fino al commit.

    Contare i posti liberi e poi iscrivere sono due passi. Senza questo lock due
    persone che prendono l'ultimo posto nello stesso istante lo trovano libero
    tutte e due, ed entrano tutte e due; lo stesso per l'ultimo uso di un codice
    sconto. Si blocca la riga del torneo: chi arriva secondo aspetta il commit
    del primo, e poi conta i posti che restano. Va chiamato prima di contare.
    SQLite il FOR UPDATE non lo conosce, ma lì le scritture vanno già in fila.
    """
    db.execute(select(Tournament.id).where(Tournament.id == tournament_id).with_for_update())


def promote_from_waitlist(tournament: Tournament, db: Session) -> None:
    """Promuove il primo in lista d'attesa se si è liberato un posto.

    Chi aveva già avuto il posto e non l'ha pagato in tempo aspetta dietro agli
    altri: ha ancora `promoted_at` (sweep_waitlist_deadlines), e la coda lo
    mette in fondo. Prima tornava primo e veniva ripromosso subito.
    """
    lock_seats(tournament.id, db)
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
        .order_by(Registration.promoted_at.is_not(None), Registration.created_at, Registration.id)
        .options(joinedload(Registration.player))
    )
    if not next_in_line:
        return
    next_in_line.waitlisted = False
    # L'orologio parte solo per chi deve pagare online, e solo prima dell'inizio (#32).
    on_clock = tournament.status == TournamentStatus.PUBLISHED and must_pay_online(next_in_line, tournament)
    next_in_line.promoted_at = datetime.now(UTC) if on_clock else None
    db.commit()
    cache_invalidate(f"registrations:{tournament.id}")
    cache_invalidate(f"my-reg:{tournament.id}:{next_in_line.player_id}")
    notify(db, [next_in_line.player_id], "waitlist_in", context=tournament.name,
           detail=str(WAITLIST_PAY_HOURS) if on_clock else "", url=event_url(tournament.id))
    try:
        send_email(
            next_in_line.player.email,
            f"{tournament.name} — Sei dentro!",
            _promotion_text(next_in_line, tournament),
            sender=Sender.PAYMENTS if on_clock else Sender.GENERAL,
        )
    except Exception:
        pass


def _promotion_text(registration: Registration, tournament: Tournament) -> str:
    """L'email di chi entra dalla lista d'attesa.

    Se il posto scade, questa email è l'unico modo in cui il giocatore può
    scoprirlo: senza il link e l'ora tornerebbe in coda senza aver mai saputo di
    avere un orologio addosso. Se non scade, non gli si chiede di pagare.
    """
    pagina = f"{str(get_settings().frontend_url).rstrip('/')}/event.html?id={tournament.id}"
    testo = (
        f"Ciao {registration.player.display_name},\n\n"
        f"si è liberato un posto per \"{tournament.name}\" e sei stato promosso "
        "dalla lista d'attesa.\n\n"
    )
    if registration.promoted_at:
        scadenza = registration.promoted_at + timedelta(hours=WAITLIST_PAY_HOURS)
        return testo + (
            f"Il posto resta tuo per {WAITLIST_PAY_HOURS} ore: completa il pagamento "
            f"entro il {scadenza.strftime('%d/%m alle %H:%M')} UTC, altrimenti torni in "
            "fondo alla coda e il posto passa al prossimo.\n\n"
            f"Paga qui: {pagina}"
        )
    quota = amount_due(registration, tournament)
    if quota and "at_event" in payment_methods(tournament):
        testo += f"Sei iscritto. La quota (€{quota / 100:.2f}) la paghi al banco, il giorno del torneo.\n\n"
    else:
        testo += "Sei iscritto.\n\n"
    return testo + f"Pagina del torneo: {pagina}"


def release_hold(registration: Registration, db: Session) -> None:
    """Toglie l'iscrizione di chi aveva scelto di pagare online e non ha pagato.

    Non era iscritto, quindi la riga sparisce — e con lei, per le chiavi
    esterne, il pagamento aperto, le risposte e la lista — così può riprovare:
    un'iscrizione solo ritirata gli direbbe "Sei già iscritto". Il codice sconto
    torna disponibile. Il commit lo fa chi chiama.
    """
    if registration.discount_code_id:
        # Il conto lo fa il database, non Python: leggere, togliere uno e
        # riscrivere perderebbe l'uso aggiunto nel frattempo da un'iscrizione.
        db.execute(
            update(DiscountCode)
            .where(DiscountCode.id == registration.discount_code_id, DiscountCode.uses > 0)
            .values(uses=DiscountCode.uses - 1)
        )
    paired = db.scalar(
        select(Pairing.id).where(or_(
            Pairing.player_a_registration_id == registration.id,
            Pairing.player_b_registration_id == registration.id,
        )).limit(1)
    )
    if paired:
        # Iscritto tardi a un torneo in corso e già abbinato: la riga serve agli
        # abbinamenti, quindi si ritira invece di sparire.
        registration.dropped = True
        registration.payment_due_by = None
        return
    db.execute(delete(Registration).where(Registration.id == registration.id))


def release_unpaid_holds(db: Session, tournament_id: int | None = None) -> int:
    """Toglie le iscrizioni con pagamento online non arrivato in tempo, e
    promuove chi aspetta in lista. Ritorna quante ne ha tolte.

    Gira in background ogni due minuti e prima di ogni iscrizione al torneo,
    così un posto tenuto e non pagato non fa dire "pieno" a chi arriva dopo.
    """
    limite = datetime.now(UTC) - timedelta(minutes=HOLD_GRACE_MINUTES)
    query = (
        select(Registration)
        .where(Registration.payment_due_by.is_not(None))
        .options(joinedload(Registration.payment), joinedload(Registration.tournament))
    )
    if tournament_id is not None:
        query = query.where(Registration.tournament_id == tournament_id)
    released = 0
    touched: dict[int, Tournament] = {}
    for reg in db.scalars(query).unique().all():
        if reg.payment and reg.payment.status == PaymentStatus.PAID:
            reg.payment_due_by = None   # ha pagato: l'orologio si ferma
            continue
        due = reg.payment_due_by
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        if due > limite:
            continue
        touched[reg.tournament_id] = reg.tournament
        cache_invalidate(f"my-reg:{reg.tournament_id}:{reg.player_id}")
        release_hold(reg, db)
        released += 1
    db.commit()
    for tournament in touched.values():
        cache_invalidate(f"registrations:{tournament.id}")
        promote_from_waitlist(tournament, db)
    if released:
        cache_invalidate("tournaments:")
    return released
