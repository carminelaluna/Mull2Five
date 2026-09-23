"""
registrations.py — I pezzi sugli iscritti che servono a piu di un router.

Le domande di un torneo, quante penalita ha gia preso un giocatore e la
promozione dalla lista d'attesa: li usano sia il router del torneo sia quello
degli iscritti, quindi non possono stare ne in uno ne nell'altro.
"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.core.cache import cache_invalidate
from backend.app.models import (
    Penalty,
    Registration,
    RegistrationField,
    Tournament,
)
from backend.app.services.email import send_email


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
