"""
mail_watch.py — Le email che arrivano alle caselle del sito, su Telegram.

Le caselle sono quelle da cui il sito manda (SMTP_*: info@, commercial@ e quella
admin, su register.it), e con le stesse credenziali si leggono via IMAP. Ogni
minuto si chiede a ognuna fin dove è arrivata (STATUS, UIDNEXT); se c'è del
nuovo si leggono mittente e oggetto, e nient'altro. Il testo resta nella
casella, e la casella resta com'era: aperta in sola lettura, niente segnato come
letto.

Dove si era arrivati lo tiene la memoria del processo. Al primo giro dopo
l'avvio si prende nota e basta, così un deploy non rimanda le email vecchie; il
prezzo è che un'email arrivata proprio nel minuto del riavvio può non essere
avvisata (resta nella casella). Durante un deploy l'istanza vecchia e la nuova
girano insieme per poco: la stessa email può arrivare due volte.

Gli avvisi vanno solo su Telegram, mai a ALERT_EMAIL: un'email che avvisa di
un'email finirebbe in una casella sorvegliata.
"""
import email
import imaplib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from email import policy
from email.message import Message

from backend.app.core.alerting import send_telegram
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# Oltre, un riassunto: un'ondata di email non diventa un'ondata di notifiche.
MAX_PER_CHECK = 5
# Tre giri di fila senza riuscire a leggere, non un singhiozzo della rete.
FAILURES_BEFORE_ALERT = 3
# PEEK: leggere le intestazioni non segna l'email come letta.
_FIELDS = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])"


@dataclass(frozen=True)
class Mailbox:
    username: str
    password: str


def watched_mailboxes() -> list[Mailbox]:
    """Le caselle con un accesso loro, una volta sola ciascuna. Una casella senza
    credenziali sue manda con quelle generali: la sua posta da qui non si legge."""
    s = get_settings()
    found: dict[str, Mailbox] = {}
    for username, password in (
        (s.smtp_username, s.smtp_password),
        (s.smtp_account_username, s.smtp_account_password),
        (s.smtp_payments_username, s.smtp_payments_password),
    ):
        if username and password and username.lower() not in found:
            found[username.lower()] = Mailbox(username, password)
    return list(found.values())


def mail_watch_enabled() -> bool:
    s = get_settings()
    return bool(s.imap_host and s.telegram_bot_token and s.telegram_chat_id and watched_mailboxes())


def _connect(host: str, port: int) -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(host, port, timeout=30)


class MailWatcher:
    """Un giro di controllo per volta (`check`), da chiamare ogni minuto."""

    def __init__(
        self,
        notify: Callable[[str], bool] = send_telegram,
        connect: Callable[[str, int], imaplib.IMAP4] = _connect,
    ) -> None:
        self._notify = notify
        self._connect = connect
        self._seen: dict[str, tuple[int, int]] = {}   # casella → (UIDVALIDITY, ultimo UID avvisato)
        self._failures: dict[str, int] = {}
        self._alerted: set[str] = set()

    def check(self) -> None:
        s = get_settings()
        for box in watched_mailboxes():
            try:
                self._check_one(box, s.imap_host, s.imap_port)
            except Exception as exc:  # noqa: BLE001 — una casella rotta non ferma le altre
                self._failed(box, exc)
            else:
                self._recovered(box)

    def _check_one(self, box: Mailbox, host: str, port: int) -> None:
        conn = self._connect(host, port)
        try:
            conn.login(box.username, box.password)
            validity, uidnext = _status(conn)
            seen = self._seen.get(box.username)
            if seen is None or seen[0] != validity:
                # Primo sguardo, o il server ha rinumerato la casella: si prende nota.
                self._seen[box.username] = (validity, uidnext - 1)
                return
            last = seen[1]
            if uidnext - 1 <= last:
                return
            conn.select("INBOX", readonly=True)
            _, data = conn.uid("SEARCH", None, f"UID {last + 1}:*")
            # "n:*" dà comunque l'ultima email anche se non ce n'è nessuna dopo n.
            uids = sorted(uid for uid in map(int, data[0].split()) if uid > last)
            for uid in uids[:MAX_PER_CHECK]:
                if not self._notify(_notice(box.username, _headers(conn, uid))):
                    return          # Telegram non risponde: il giro dopo si riparte da qui
                self._seen[box.username] = (validity, uid)
            rest = uids[MAX_PER_CHECK:]
            if rest and not self._notify(f"📬 {box.username}\n…e altre {len(rest)} email."):
                return
            self._seen[box.username] = (validity, max([uidnext - 1, *uids]))
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001, S110 — la connessione si chiude comunque
                pass

    def _failed(self, box: Mailbox, exc: Exception) -> None:
        count = self._failures.get(box.username, 0) + 1
        self._failures[box.username] = count
        logger.warning("Casella %s non letta: %s", box.username, _reason(exc))
        if count >= FAILURES_BEFORE_ALERT and box.username not in self._alerted:
            if self._notify(f"⚠️ Non riesco a leggere {box.username}: {_reason(exc)}"):
                self._alerted.add(box.username)

    def _recovered(self, box: Mailbox) -> None:
        self._failures.pop(box.username, None)
        if box.username in self._alerted and self._notify(f"✅ {box.username} si legge di nuovo."):
            self._alerted.discard(box.username)


def _status(conn: imaplib.IMAP4) -> tuple[int, int]:
    typ, data = conn.status("INBOX", "(UIDVALIDITY UIDNEXT)")
    line = data[0] if typ == "OK" and data else b""
    validity = re.search(rb"UIDVALIDITY (\d+)", line)
    uidnext = re.search(rb"UIDNEXT (\d+)", line)
    if not (validity and uidnext):
        raise imaplib.IMAP4.error(f"STATUS senza UIDVALIDITY/UIDNEXT: {typ}")
    return int(validity.group(1)), int(uidnext.group(1))


def _headers(conn: imaplib.IMAP4, uid: int) -> Message:
    _, data = conn.uid("FETCH", str(uid), _FIELDS)
    raw = next((part[1] for part in data if isinstance(part, tuple)), b"")
    return email.message_from_bytes(raw, policy=policy.default)


def _field(message: Message, name: str) -> str:
    try:
        value = str(message.get(name) or "")
    except Exception:  # noqa: BLE001 — un'intestazione storta non deve fermare gli avvisi
        value = ""
    return " ".join(value.split())[:200]


def _notice(mailbox: str, message: Message) -> str:
    sender = _field(message, "From") or "(mittente sconosciuto)"
    subject = _field(message, "Subject") or "(senza oggetto)"
    return f"📬 {mailbox}\nDa: {sender}\nOggetto: {subject}"


def _reason(exc: Exception) -> str:
    """Il perché, leggibile: imaplib mette i messaggi del server in bytes."""
    arg = exc.args[0] if exc.args else exc
    text = arg.decode(errors="replace") if isinstance(arg, bytes) else str(arg)
    return text or type(exc).__name__
