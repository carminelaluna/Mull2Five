"""
inbox.py — Lo storico delle notifiche: la campanella del sito e l'app.

Quello che il sito dice da solo a un giocatore — iscrizione, pagamento, turno,
annuncio, torneo annullato, segnalazione — parte per email e resta anche qui.
L'email si perde fra le altre, e l'organizzatore può averla spenta per il suo
torneo; la campanella c'è sempre, e l'app la legge per avvisare sul telefono.
Per questo `notify` non guarda `email_notifications_enabled`: quell'interruttore
riguarda le email.

Si salva il tipo e i pezzi della frase, non la frase (vedi `Notification`): la
scrive chi la mostra, nella lingua di chi legge. I tipi sono quelli di `KINDS`,
e il sito e l'app hanno una frase per ognuno.

Chi chiama ha già salvato quello che è successo: un errore qui lo si scrive nel
log e basta, l'iscrizione o il pagamento non devono sembrare falliti.
"""
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.models import Notification

logger = logging.getLogger(__name__)

KINDS = (
    "registered",     # iscrizione confermata
    "waitlisted",     # in lista d'attesa
    "waitlist_in",    # dalla lista d'attesa al torneo; detail = ore per pagare, se deve
    "paid",           # pagamento ricevuto; detail = "10.00 EUR"
    "reminder",       # si gioca domani; detail = l'ora
    "started",        # il torneo è iniziato
    "pairings",       # abbinamenti pronti; detail = il turno
    "announcement",   # un annuncio dell'organizzatore: title e body sono suoi
    "cancelled",      # torneo annullato; detail = "refunded", "requested" o niente
    "ticket_new",     # una segnalazione da leggere: title è l'oggetto
    "ticket_reply",   # una risposta a una segnalazione
)
# Le pagine a cui porta una notifica, relative: il sito e l'app le aprono a modo loro.
TICKETS_URL = "/tickets.html"
# Più vecchie di così le toglie prune(): la campanella è un avviso, non un archivio.
KEEP_DAYS = 90


def event_url(tournament_id: int) -> str:
    return f"/event.html?id={tournament_id}"


def live_url(tournament_id: int) -> str:
    """Il torneo in corso: sul sito sta in Le mie iscrizioni, che `t` lo ignora;
    l'app lo usa per aprire direttamente quel torneo."""
    return f"/my-registrations.html?t={tournament_id}"


def notify(
    db: Session | None,
    user_ids: Iterable[int | None],
    kind: str,
    *,
    context: str = "",
    title: str = "",
    body: str = "",
    detail: str = "",
    url: str = "",
) -> int:
    """Una notifica uguale per ognuno di `user_ids`. Ritorna quante ne ha scritte."""
    ids = sorted({user_id for user_id in user_ids if user_id})
    if db is None or not ids:
        return 0
    try:
        db.add_all(
            Notification(user_id=user_id, kind=kind, context=context[:200], title=title[:200],
                         body=body[:1000], detail=str(detail)[:64], url=url[:300])
            for user_id in ids
        )
        db.commit()
    except Exception:  # noqa: BLE001 — quello che l'ha causata è già salvato
        db.rollback()
        logger.exception("Notifica %s non salvata per %d persone", kind, len(ids))
        return 0
    return len(ids)


def prune(db: Session, now: datetime | None = None) -> int:
    """Toglie le notifiche più vecchie di KEEP_DAYS. La chiama main.py ogni ora."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)
    removed = db.execute(delete(Notification).where(Notification.created_at < cutoff)).rowcount
    db.commit()
    return removed or 0
