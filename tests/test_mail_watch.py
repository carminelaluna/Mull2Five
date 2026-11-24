"""
test_mail_watch.py — Le email che arrivano alle caselle del sito, su Telegram.

Il server IMAP è finto ma si comporta come Dovecot (quello di register.it): STATUS
dice UIDVALIDITY e UIDNEXT, e `UID SEARCH UID n:*` restituisce l'ultima email
anche quando non ce n'è nessuna dopo n — una stranezza vera dello standard, che
farebbe avvisare due volte la stessa email.
"""
import imaplib

import pytest

from backend.app.core.config import get_settings
from backend.app.services import mail_watch


def _headers(sender: str, subject: str) -> bytes:
    return f"From: {sender}\r\nSubject: {subject}\r\n\r\n".encode()


class FakeServer:
    """Le caselle: utente → password, UIDVALIDITY e le email (uid → intestazioni)."""

    def __init__(self):
        self.boxes: dict[str, dict] = {}
        self.logins: list[str] = []
        self.selected_readonly: list[bool] = []
        self.fetched: list[str] = []

    def add_box(self, user, password="pw", uidvalidity=1):
        self.boxes[user] = {"password": password, "uidvalidity": uidvalidity, "messages": {}}

    def deliver(self, user, sender, subject):
        box = self.boxes[user]
        uid = max(box["messages"], default=0) + 1
        box["messages"][uid] = _headers(sender, subject)
        return uid

    def connect(self, host, port):
        assert (host, port) == ("mail.example.test", 993)
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, server: FakeServer):
        self.server = server
        self.box = None

    def login(self, user, password):
        box = self.server.boxes.get(user)
        if not box or box["password"] != password:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Authentication failed.")
        self.server.logins.append(user)
        self.box = box
        return "OK", [b"Logged in"]

    def status(self, mailbox, names):
        uidnext = max(self.box["messages"], default=0) + 1
        return "OK", [f'"INBOX" (UIDVALIDITY {self.box["uidvalidity"]} UIDNEXT {uidnext})'.encode()]

    def select(self, mailbox="INBOX", readonly=False):
        self.server.selected_readonly.append(readonly)
        return "OK", [str(len(self.box["messages"])).encode()]

    def uid(self, command, *args):
        messages = self.box["messages"]
        if command == "SEARCH":
            first = int(args[-1].split()[1].split(":")[0])
            found = [u for u in messages if u >= first] or ([max(messages)] if messages else [])
            return "OK", [" ".join(str(u) for u in sorted(found)).encode()]
        if command == "FETCH":
            uid, what = args
            self.server.fetched.append(what)
            head = messages[int(uid)]
            return "OK", [(f"1 (UID {uid} BODY[HEADER.FIELDS (FROM SUBJECT)] {{{len(head)}}}".encode(), head), b")"]
        raise AssertionError(f"comando inatteso: {command}")

    def logout(self):
        return "BYE", [b""]


@pytest.fixture
def server(monkeypatch):
    s = get_settings()
    for name, value in {
        "imap_host": "mail.example.test", "imap_port": 993,
        "telegram_bot_token": "123:abc", "telegram_chat_id": "42",
        "smtp_from_email": "admin@mull2five.test", "smtp_username": "admin@mull2five.test",
        "smtp_password": "pw",
        "smtp_account_from_email": "info@mull2five.test", "smtp_account_username": "info@mull2five.test",
        "smtp_account_password": "pw",
        "smtp_payments_from_email": "commercial@mull2five.test",
        "smtp_payments_username": "commercial@mull2five.test", "smtp_payments_password": "pw",
    }.items():
        monkeypatch.setattr(s, name, value)
    fake = FakeServer()
    for user in ("admin@mull2five.test", "info@mull2five.test", "commercial@mull2five.test"):
        fake.add_box(user)
    return fake


@pytest.fixture
def sent():
    return []


def _watcher(server, sent):
    def notify(text):
        sent.append(text)
        return True
    return mail_watch.MailWatcher(notify=notify, connect=server.connect)


def test_the_first_look_only_takes_note(server, sent):
    server.deliver("commercial@mull2five.test", "Vecchia <old@example.com>", "Già letta")

    _watcher(server, sent).check()

    assert sent == []


def test_a_new_email_says_which_mailbox_who_and_what(server, sent):
    watcher = _watcher(server, sent)
    watcher.check()
    server.deliver("commercial@mull2five.test", "=?utf-8?q?Mario_Rossi?= <mario@example.com>",
                   "=?utf-8?q?Rimborso_quota_=E2=82=AC15?=")

    watcher.check()

    assert sent == ["📬 commercial@mull2five.test\nDa: Mario Rossi <mario@example.com>\nOggetto: Rimborso quota €15"]
    # Solo le intestazioni, e senza segnarla come letta: la casella resta com'era.
    assert server.fetched == ["(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])"]
    assert all(server.selected_readonly)


def test_the_same_email_is_not_told_twice(server, sent):
    watcher = _watcher(server, sent)
    watcher.check()
    server.deliver("info@mull2five.test", "a@example.com", "Uno")
    watcher.check()

    watcher.check()      # nessuna email nuova: il server risponde comunque con l'ultima

    assert len(sent) == 1


def test_a_renumbered_mailbox_starts_over_without_a_flood(server, sent):
    watcher = _watcher(server, sent)
    for n in range(3):
        server.deliver("info@mull2five.test", "a@example.com", f"Vecchia {n}")
    watcher.check()
    server.boxes["info@mull2five.test"]["uidvalidity"] = 2

    watcher.check()

    assert sent == []


def test_many_emails_at_once_are_summed_up(server, sent):
    watcher = _watcher(server, sent)
    watcher.check()
    for n in range(8):
        server.deliver("admin@mull2five.test", "a@example.com", f"Email {n}")

    watcher.check()
    watcher.check()

    assert len(sent) == mail_watch.MAX_PER_CHECK + 1
    assert sent[-1] == "📬 admin@mull2five.test\n…e altre 3 email."


def test_a_mailbox_without_its_own_login_is_read_once(server, sent, monkeypatch):
    """Una casella senza credenziali sue manda con quelle generali: non è una
    casella da leggere in più, e due caselle con lo stesso accesso sono una."""
    monkeypatch.setattr(get_settings(), "smtp_account_username", None)
    monkeypatch.setattr(get_settings(), "smtp_payments_username", "ADMIN@mull2five.test")

    assert [b.username for b in mail_watch.watched_mailboxes()] == ["admin@mull2five.test"]
    _watcher(server, sent).check()
    assert server.logins == ["admin@mull2five.test"]


def test_a_mailbox_that_cannot_be_read_is_told_once_and_when_it_is_back(server, sent):
    watcher = _watcher(server, sent)
    server.boxes["info@mull2five.test"]["password"] = "cambiata"

    for _ in range(mail_watch.FAILURES_BEFORE_ALERT + 3):
        watcher.check()
    assert len(sent) == 1
    assert sent[0].startswith("⚠️ Non riesco a leggere info@mull2five.test")
    assert "cambiata" not in sent[0] and "pw" not in sent[0]

    server.boxes["info@mull2five.test"]["password"] = "pw"
    watcher.check()
    assert sent[1] == "✅ info@mull2five.test si legge di nuovo."


def test_a_blip_is_not_an_alarm(server, sent):
    watcher = _watcher(server, sent)
    server.boxes["info@mull2five.test"]["password"] = "cambiata"
    watcher.check()
    server.boxes["info@mull2five.test"]["password"] = "pw"

    watcher.check()

    assert sent == []


def test_when_telegram_does_not_answer_the_email_waits(server, sent):
    answers = iter([False, True])

    def notify(text):
        if next(answers):
            sent.append(text)
            return True
        return False

    watcher = mail_watch.MailWatcher(notify=notify, connect=server.connect)
    watcher.check()
    server.deliver("info@mull2five.test", "a@example.com", "Importante")

    watcher.check()      # Telegram giù: non la si dà per avvisata
    watcher.check()

    assert sent == ["📬 info@mull2five.test\nDa: a@example.com\nOggetto: Importante"]


def test_it_is_off_without_imap_or_telegram(server, monkeypatch):
    assert mail_watch.mail_watch_enabled()
    monkeypatch.setattr(get_settings(), "telegram_chat_id", None)
    assert not mail_watch.mail_watch_enabled()
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "42")
    monkeypatch.setattr(get_settings(), "imap_host", None)
    assert not mail_watch.mail_watch_enabled()


def test_the_notice_goes_to_telegram_and_never_to_the_alert_email(monkeypatch):
    """Un avviso via email su un'email arrivata finirebbe in una casella
    sorvegliata: un giro senza fine. Le email arrivate vanno solo su Telegram."""
    from backend.app.core import alerting

    posted, emailed = [], []

    class Answer:
        is_success = True

    def post(url, json, timeout):
        posted.append((url, json))
        return Answer()

    monkeypatch.setattr(get_settings(), "telegram_bot_token", "123:abc")
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "42")
    monkeypatch.setattr(get_settings(), "alert_email", "admin@mull2five.test")
    monkeypatch.setattr(alerting.httpx, "post", post)
    monkeypatch.setattr(alerting, "_send_email_alert", lambda *a: emailed.append(a))

    assert alerting.send_telegram("📬 prova") is True

    assert posted == [("https://api.telegram.org/bot123:abc/sendMessage",
                       {"chat_id": "42", "text": "📬 prova", "disable_web_page_preview": True})]
    assert emailed == []


def test_without_telegram_nothing_is_sent(monkeypatch):
    from backend.app.core import alerting

    monkeypatch.setattr(get_settings(), "telegram_bot_token", None)
    assert alerting.send_telegram("📬 prova") is False
