"""
notifications.py — Le email che il torneo manda da solo.

Iscrizione confermata, abbinamenti pronti, torneo avviato, pagamento
incassato. Le rotte chiamano queste funzioni e basta: non aspettano niente e
non devono proteggersi da niente, perché a mandare davvero è send_email, che
usa un suo thread e tiene per sé i guai di SMTP (email.py).

C'era un giro in più — le email passavano da un executor di asyncio preso con
get_event_loop() — che dentro una rotta sincrona, cioè in un thread del pool di
FastAPI, sollevava RuntimeError: nessuna email partiva, e i chiamanti lo
ingoiavano. Da qui in poi si manda e si prova con un test (test_notifications).
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models import Registration, Ticket, Tournament, User

from backend.app.services.email import Sender, event_announcement_html, send_email

logger = logging.getLogger(__name__)


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


def _tournament_cancelled(
    player_name: str, tournament: "Tournament", refund: str | None, amount: float,
) -> tuple[str, str, str]:
    subject = f"Torneo annullato — {tournament.name}"
    giorno = f" del {tournament.starts_on.strftime('%d/%m/%Y')}" if tournament.starts_on else ""
    body = (
        f"Ciao {player_name},\n\n"
        f"il negozio ha annullato {tournament.name}{giorno}: il torneo non si gioca.\n\n"
    )
    if refund == "refunded":
        body += (f"Avevi pagato €{amount:.2f}: il rimborso è partito e torna sul metodo con cui "
                 "avevi pagato. Possono volerci alcuni giorni prima che tu lo veda.\n\n")
    elif refund == "requested":
        body += (f"Avevi pagato €{amount:.2f}: la richiesta di rimborso è registrata, e la quota "
                 "te la restituisce il negozio. Per qualsiasi cosa, scrivi a chi organizza.\n\n")
    else:
        body += "Non devi fare niente.\n\n"
    body += "Mull2Five"
    html = event_announcement_html(tournament.name, "Torneo annullato", body)
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
    send_email(registration.player.email, subject, body, html)


def notify_pairings_ready(tournament: "Tournament", round_number: int, registrations: list) -> None:
    if not getattr(tournament, "email_notifications_enabled", False):
        return
    for reg in registrations:
        if reg.player and reg.player.email:
            subject, body, html = _pairings_ready(
                reg.player.display_name, tournament, round_number
            )
            send_email(reg.player.email, subject, body, html)


def notify_tournament_started(tournament: "Tournament", registrations: list) -> None:
    if not getattr(tournament, "email_notifications_enabled", False):
        return
    for reg in registrations:
        if reg.player and reg.player.email:
            subject, body, html = _tournament_started(reg.player.display_name, tournament)
            send_email(reg.player.email, subject, body, html)


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


def notify_tournament_cancelled(
    tournament: "Tournament", notices: list[tuple["Registration", str | None, float]],
) -> None:
    """Il torneo è stato annullato: lo dice a ognuno, con cosa succede alla sua
    quota ("refunded", "requested" o None se non aveva pagato). Parte anche con
    le email del torneo spente, come la ricevuta: ci sono di mezzo dei soldi, e
    chi viene apposta deve saperlo."""
    for reg, refund, amount in notices:
        if not reg.player or not reg.player.email:
            continue
        subject, body, html = _tournament_cancelled(reg.player.display_name, tournament, refund, amount)
        send_email(reg.player.email, subject, body, html, sender=Sender.PAYMENTS)


def _ticket_opened(recipient_name: str, ticket: "Ticket", page: str) -> tuple[str, str, str]:
    opener = ticket.opened_by.display_name if ticket.opened_by else "Un giocatore"
    about = f"sul torneo {ticket.tournament.name}" if ticket.tournament else "per chi tiene il sito"
    # L'oggetto lo scrive il giocatore e va nell'intestazione dell'email, dove un
    # a capo non può stare (EmailMessage solleva): lo si tiene su una riga.
    title = " ".join(ticket.subject.split())
    first = ticket.messages[0].body if ticket.messages else ""
    subject = f"Nuova segnalazione: {title}"
    body = (
        f"Ciao {recipient_name},\n\n"
        f"{opener} ha aperto una segnalazione {about}.\n\n"
        f"{title}\n\n{first}\n\n"
        f"La leggi e rispondi da Segnalazioni, scheda Ricevute: {page}\n\n"
        "Mull2Five"
    )
    context = ticket.tournament.name if ticket.tournament else "Segnalazione al sito"
    html = event_announcement_html(context, "Nuova segnalazione", body)
    return subject, body, html


def notify_ticket_opened(ticket: "Ticket", recipients: list["User"], page: str) -> None:
    """Una segnalazione nuova: lo si dice a chi la deve leggere, che sennò lo
    scopre solo aprendo la pagina. Parte anche con le email del torneo spente:
    quelle sono per i giocatori, questa è posta per chi organizza."""
    for user in recipients:
        if user.email:
            subject, body, html = _ticket_opened(user.display_name, ticket, page)
            send_email(user.email, subject, body, html)


def notify_payment_confirmed(registration: "Registration", amount: float) -> None:
    if not registration.player or not registration.player.email:
        return
    tournament = registration.tournament
    subject, body, html = _payment_confirmed(
        registration.player.display_name, tournament, amount
    )
    send_email(registration.player.email, subject, body, html, sender=Sender.PAYMENTS)
