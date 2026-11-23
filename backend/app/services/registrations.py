"""
registrations.py — I pezzi sugli iscritti che servono a piu di un router.

Le domande di un torneo, quante penalita ha gia preso un giocatore e la
promozione dalla lista d'attesa: li usano sia il router del torneo sia quello
degli iscritti, quindi non possono stare ne in uno ne nell'altro.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
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
)
from backend.app.services.email import Sender, send_email
from backend.app.services.payments import HOLD_GRACE_MINUTES


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


WAITLIST_PAY_HOURS = 6   # ore per pagare dopo la promozione dalla waitlist (#32)


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
    cache_invalidate(f"registrations:{tournament.id}")
    cache_invalidate(f"my-reg:{tournament.id}:{next_in_line.player_id}")
    # Il posto scade, e questa email è l'unico posto in cui il giocatore può
    # scoprirlo: senza il link e l'ora torna in coda senza aver mai saputo di
    # avere un orologio addosso.
    pagina = f"{str(get_settings().frontend_url).rstrip('/')}/event.html?id={tournament.id}"
    scadenza = next_in_line.promoted_at + timedelta(hours=WAITLIST_PAY_HOURS)
    try:
        send_email(
            next_in_line.player.email,
            f"{tournament.name} — Sei dentro!",
            f"Ciao {next_in_line.player.display_name},\n\n"
            f"si è liberato un posto per \"{tournament.name}\" e sei stato promosso "
            "dalla lista d'attesa.\n\n"
            f"Il posto resta tuo per {WAITLIST_PAY_HOURS} ore: completa il pagamento "
            f"entro il {scadenza.strftime('%d/%m alle %H:%M')} UTC, altrimenti torni in "
            "coda e il posto passa al prossimo.\n\n"
            f"Paga qui: {pagina}",
            sender=Sender.PAYMENTS,
        )
    except Exception:
        pass


def release_hold(registration: Registration, db: Session) -> None:
    """Toglie l'iscrizione di chi aveva scelto di pagare online e non ha pagato.

    Non era iscritto, quindi la riga sparisce — e con lei, per le chiavi
    esterne, il pagamento aperto, le risposte e la lista — così può riprovare:
    un'iscrizione solo ritirata gli direbbe "Sei già iscritto". Il codice sconto
    torna disponibile. Il commit lo fa chi chiama.
    """
    if registration.discount_code_id:
        code = db.get(DiscountCode, registration.discount_code_id)
        if code and code.uses > 0:
            code.uses -= 1
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
