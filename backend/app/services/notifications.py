"""
Notifiche email per eventi del torneo.
Tutte le funzioni sono async fire-and-forget: vengono lanciate con
asyncio.create_task() dal router, quindi non bloccano la risposta API.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models import Registration, Tournament

from backend.app.services.email import event_announcement_html, send_email

logger = logging.getLogger(__name__)


def _send_async(to: str, subject: str, body: str, html: str) -> None:
    """Wrapper sincrono per inviare email in un thread separato."""
    try:
        send_email(to, subject, body, html)
    except Exception as exc:
        logger.warning("Email not sent to %s: %s", to, exc)


def fire_email(to: str, subject: str, body: str, html: str) -> None:
    """Lancia l'invio email in background senza attendere il risultato."""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _send_async, to, subject, body, html)


# ── Template helpers ─────────────────────────────────


def _registration_confirmed(player_name: str, tournament: "Tournament") -> tuple[str, str, str]:
    subject = f"Iscrizione confermata — {tournament.name}"
    body = (
        f"Ciao {player_name},\n\n"
        f"La tua iscrizione a {tournament.name} è stata confermata.\n\n"
        f"Data: {tournament.starts_on.strftime('%d/%m/%Y') if tournament.starts_on else 'TBD'}\n"
        f"Formato: {tournament.format}\n"
        f"Luogo: {tournament.place or 'TBD'}\n\n"
        f"Buona fortuna!\n\nMull2Five"
    )
    html = event_announcement_html(tournament.name, "Iscrizione confermata ✓", body)
    return subject, body, html


def _pairings_ready(player_name: str, tournament: "Tournament", round_number: int) -> tuple[str, str, str]:
    subject = f"Round {round_number} — {tournament.name}"
    body = (
        f"Ciao {player_name},\n\n"
        f"Gli abbinamenti del Round {round_number} di {tournament.name} sono pronti.\n"
        f"Controlla i pairings sul sito e siediti al tuo tavolo.\n\n"
        f"In bocca al lupo!\n\nMull2Five"
    )
    html = event_announcement_html(tournament.name, f"Round {round_number} — Abbinamenti pronti", body)
    return subject, body, html


def _tournament_started(player_name: str, tournament: "Tournament") -> tuple[str, str, str]:
    subject = f"Il torneo è iniziato — {tournament.name}"
    body = (
        f"Ciao {player_name},\n\n"
        f"{tournament.name} è ufficialmente iniziato.\n"
        f"Assicurati di avere la tua decklist con te.\n\n"
        f"Mull2Five"
    )
    html = event_announcement_html(tournament.name, "Il torneo è iniziato!", body)
    return subject, body, html


def _payment_confirmed(player_name: str, tournament: "Tournament", amount: float) -> tuple[str, str, str]:
    subject = f"Pagamento confermato — {tournament.name}"
    body = (
        f"Ciao {player_name},\n\n"
        f"Il tuo pagamento di €{amount:.2f} per {tournament.name} è stato ricevuto.\n\n"
        f"Mull2Five"
    )
    html = event_announcement_html(tournament.name, "Pagamento confermato ✓", body)
    return subject, body, html


# ── Funzioni pubbliche chiamate dai router ────────────


def notify_registration_confirmed(registration: "Registration") -> None:
    if not registration.player or not registration.player.email:
        return
    tournament = registration.tournament
    if not tournament or not getattr(tournament, "email_notifications_enabled", False):
        return
    subject, body, html = _registration_confirmed(
        registration.player.display_name, tournament
    )
    fire_email(registration.player.email, subject, body, html)


def notify_pairings_ready(tournament: "Tournament", round_number: int, registrations: list) -> None:
    if not getattr(tournament, "email_notifications_enabled", False):
        return
    for reg in registrations:
        if reg.player and reg.player.email:
            subject, body, html = _pairings_ready(
                reg.player.display_name, tournament, round_number
            )
            fire_email(reg.player.email, subject, body, html)


def notify_tournament_started(tournament: "Tournament", registrations: list) -> None:
    if not getattr(tournament, "email_notifications_enabled", False):
        return
    for reg in registrations:
        if reg.player and reg.player.email:
            subject, body, html = _tournament_started(reg.player.display_name, tournament)
            fire_email(reg.player.email, subject, body, html)


def push_to_tournament(
    db,
    tournament_id: int,
    title: str,
    body: str,
    url: str = "",
    user_ids: list[int] | None = None,
) -> int:
    """Invia una notifica Web Push agli iscritti del torneo che hanno una
    subscription attiva. Rimuove gli endpoint scaduti. Ritorna il numero inviato.
    No-op se Web Push non è configurato.

    `user_ids` restringe a una platea già scelta da chi chiama (un annuncio
    mirato); `None` vuol dire tutti gli iscritti. Una lista vuota non è lo stesso:
    è una platea scelta che non contiene nessuno, e non manda niente."""
    from sqlalchemy import select

    from backend.app.core.webpush import push_enabled, send_push
    from backend.app.models import PushSubscription, Registration

    if not push_enabled():
        return 0
    if user_ids is not None and not user_ids:
        return 0

    stmt = (
        select(PushSubscription)
        .join(Registration, Registration.player_id == PushSubscription.user_id)
        .where(Registration.tournament_id == tournament_id)
    )
    if user_ids is not None:
        stmt = stmt.where(PushSubscription.user_id.in_(user_ids))
    subs = db.scalars(stmt).all()

    payload = {"title": title, "body": body, "url": url}
    sent = 0
    stale: list = []
    for sub in subs:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        result = send_push(info, payload)
        if result == "sent":
            sent += 1
        elif result == "gone":
            stale.append(sub)
    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()
    return sent


def notify_payment_confirmed(registration: "Registration", amount: float) -> None:
    if not registration.player or not registration.player.email:
        return
    tournament = registration.tournament
    subject, body, html = _payment_confirmed(
        registration.player.display_name, tournament, amount
    )
    fire_email(registration.player.email, subject, body, html)
