"""
reminders.py — Il promemoria del giorno prima.

Un torneo prenotato dieci giorni prima si dimentica, e chi non si presenta lascia
un posto vuoto che il negozio aveva già venduto. Questo compito manda **una sola**
email, il giorno prima, a chi è iscritto davvero: non a chi è in lista d'attesa,
non a chi si è ritirato. Che sia partita sta scritta sul torneo
(`reminder_sent_at`), perché il compito gira ogni ora e un riavvio del server non
deve far ripartire le stesse email da capo.

Rispetta l'interruttore del torneo (`email_notifications_enabled`), come tutte le
altre email automatiche: se l'organizzatore ha deciso che il sito non scrive ai
suoi giocatori, questo non fa eccezione.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.models import (
    PaymentStatus,
    Registration,
    Tournament,
    TournamentStatus,
)
from backend.app.services.email import event_announcement_html, send_email


def reminder_body(player_name: str, tournament: Tournament, to_pay: bool) -> str:
    """Il testo del promemoria. Fuori dalla funzione che manda, così un test può
    leggerlo senza un server SMTP."""
    pagina = f"{str(get_settings().frontend_url).rstrip('/')}/event.html?id={tournament.id}"
    ora = f" alle {tournament.start_time}" if tournament.start_time else ""
    righe = [
        f"Ciao {player_name},",
        "",
        f"domani si gioca: {tournament.name} ({tournament.format}), "
        f"{tournament.starts_on.strftime('%d/%m')}{ora}.",
    ]
    if tournament.is_online:
        # Il link della stanza lo vedono solo gli iscritti, e qui lo sono tutti.
        dove = f" su {tournament.online_platform}" if tournament.online_platform else ""
        righe.append(f"Si gioca online{dove}.")
        if tournament.online_link:
            righe.append(f"Stanza: {tournament.online_link}")
    elif tournament.place:
        righe.append(f"Dove: {tournament.place}")
    if to_pay:
        # Chi deve ancora pagare lo scopre adesso, non al banco con la fila dietro.
        quota = f"{tournament.entry_fee_cents / 100:.2f} {tournament.currency}"
        righe += ["", f"L'iscrizione risulta ancora da pagare ({quota}): "
                      "puoi farlo dalla pagina del torneo."]
    if tournament.decklist_required:
        righe += ["", "Ricordati la lista del mazzo."]
    righe += ["", f"Tutti i dettagli: {pagina}", "", "Mull2Five"]
    return "\n".join(righe)


def send_event_reminders(db: Session) -> int:
    """Manda il promemoria agli iscritti dei tornei di domani, una volta sola.
    Ritorna quante email sono partite. Pensata per essere chiamata periodicamente
    da un task in background."""
    tomorrow = local_today() + timedelta(days=1)
    tournaments = db.scalars(
        select(Tournament)
        .where(
            Tournament.starts_on == tomorrow,
            Tournament.reminder_sent_at.is_(None),
            Tournament.email_notifications_enabled == True,   # noqa: E712
            Tournament.status.in_([TournamentStatus.PUBLISHED, TournamentStatus.RUNNING]),
        )
        .options(joinedload(Tournament.location))
    ).all()

    sent = 0
    for tournament in tournaments:
        registrations = db.scalars(
            select(Registration)
            .where(
                Registration.tournament_id == tournament.id,
                Registration.waitlisted == False,   # noqa: E712
                Registration.dropped == False,      # noqa: E712
            )
            .options(joinedload(Registration.player), joinedload(Registration.payment))
        ).all()
        for reg in registrations:
            if not reg.player or not reg.player.email:
                continue
            to_pay = bool(tournament.entry_fee_cents) and not (
                reg.payment and reg.payment.status == PaymentStatus.PAID
            )
            body = reminder_body(reg.player.display_name, tournament, to_pay)
            html = event_announcement_html(tournament.name, "Si gioca domani", body)
            if send_email(reg.player.email, f"Domani: {tournament.name}", body, html):
                sent += 1
        # Segnato anche se non è partita nessuna email (SMTP spento, nessun
        # iscritto): il torneo è stato guardato, e non va riguardato ogni ora.
        tournament.reminder_sent_at = datetime.now(UTC)
        db.add(tournament)
    db.commit()
    return sent
