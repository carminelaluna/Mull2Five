"""
test_site_watch.py — Gli avvisi che il sito manda di suo.

Il controllo da GitHub che smette di passare (chi controlla il controllore), il
database che si avvicina al limite di Supabase, e le email che non partono: un
reset password che non arriva, senza questo, non lo vede nessuno.
"""
import smtplib
import uuid

import pytest

from backend.app.core import alerting
from backend.app.core.config import get_settings
from backend.app.services import email, site_watch
from backend.app.services.email import Sender, send_email

ORA = 1000.0


class Orologio:
    def __init__(self):
        self.ora = ORA

    def __call__(self):
        return self.ora


@pytest.fixture
def orologio():
    return Orologio()


def _guardia(orologio, inviati, risponde=True):
    def notify(text):
        inviati.append(text)
        return risponde
    return site_watch.StatusCheckWatch(notify=notify, clock=orologio)


def test_the_check_from_github_is_recognised_by_its_user_agent(client, monkeypatch, orologio):
    guardia = site_watch.StatusCheckWatch(notify=lambda text: True, clock=orologio)
    monkeypatch.setattr(site_watch, "status_check", guardia)
    orologio.ora = ORA + 500

    client.get("/health", headers={"User-Agent": "curl/8"})
    assert guardia.last_seen == ORA

    client.get("/health", headers={"User-Agent": "mull2five-stato-sito"})
    assert guardia.last_seen == ORA + 500


def test_a_check_that_stops_passing_is_told_once_and_when_it_is_back(orologio):
    inviati = []
    guardia = _guardia(orologio, inviati)

    orologio.ora = ORA + 2 * 3600
    guardia.check(3)
    assert inviati == []            # due ore: GitHub è solo in ritardo

    orologio.ora = ORA + 3 * 3600 + 1
    guardia.check(3)
    guardia.check(3)
    assert len(inviati) == 1 and inviati[0].startswith("⏸️ Il controllo da GitHub non passa da più di 3 ore")

    guardia.seen()
    guardia.check(3)
    assert inviati[1] == "▶️ Il controllo da GitHub è ripartito."


def test_when_telegram_does_not_answer_it_tries_again(orologio):
    inviati = []
    guardia = _guardia(orologio, inviati, risponde=False)
    orologio.ora = ORA + 4 * 3600

    guardia.check(3)
    guardia.check(3)

    assert len(inviati) == 2 and not guardia.told


def test_zero_hours_is_off(orologio):
    inviati = []
    guardia = _guardia(orologio, inviati)
    orologio.ora = ORA + 100 * 3600
    guardia.check(0)
    assert inviati == []


@pytest.fixture
def allarmi(monkeypatch):
    chiamate = []
    monkeypatch.setattr(site_watch, "send_alert", lambda *a, **k: chiamate.append((a, k)) or True)
    return chiamate


def test_a_small_database_says_nothing(allarmi):
    assert not site_watch.check_database_size(120.0, 400)
    assert not site_watch.check_database_size(None, 400)       # SQLite
    assert not site_watch.check_database_size(450.0, 0)        # spento
    assert allarmi == []


def test_a_database_near_the_limit_is_told_once_a_day(allarmi):
    assert site_watch.check_database_size(412.4, 400)
    (args, kwargs), = allarmi
    assert args[:2] == ("db-size", "Database a 412 MB")
    assert kwargs == {"level": "warning", "throttle_secs": 24 * 3600}


def test_the_database_size_is_read_only_on_postgresql():
    size = site_watch.database_size_mb()
    if site_watch.engine.dialect.name == "postgresql":
        assert size > 0
    else:
        assert size is None


@pytest.fixture
def telegram(monkeypatch):
    """Telegram acceso e finto, ALERT_EMAIL impostata: si vede dove va ogni allarme."""
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(s, "telegram_chat_id", "42")
    monkeypatch.setattr(s, "alert_email", "admin@mull2five.test")
    posted, emailed = [], []
    monkeypatch.setattr(alerting, "_send_telegram", lambda token, chat, text: posted.append(text) or True)
    monkeypatch.setattr(alerting, "_send_email_alert", lambda *a: emailed.append(a))
    return posted, emailed


def test_an_alert_can_skip_the_email_and_wait_longer(telegram):
    posted, emailed = telegram
    key = f"prova-{uuid.uuid4()}"

    assert alerting.send_alert(key, "Email non partite", "dettaglio", email=False, throttle_secs=3600)
    assert not alerting.send_alert(key, "Email non partite", "dettaglio", email=False, throttle_secs=3600)

    assert len(posted) == 1 and emailed == []


def test_a_mailbox_that_cannot_send_is_told_without_the_recipient(monkeypatch, telegram):
    """Una casella con la password cambiata lascia tutti senza reset password, e
    l'unico segno era una riga nei log di Render."""
    posted, emailed = telegram
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "email_async", False)
    monkeypatch.setattr(s, "smtp_account_from_email", f"info-{uuid.uuid4().hex[:6]}@mull2five.test")
    monkeypatch.setattr(s, "smtp_account_username", "info@mull2five.test")
    monkeypatch.setattr(s, "smtp_account_password", "sbagliata")

    class RefusingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")

    monkeypatch.setattr(email.smtplib, "SMTP", RefusingSMTP)

    send_email("giocatore@example.com", "Reimposta la password", "…", sender=Sender.ACCOUNT)
    send_email("altro@example.com", "Reimposta la password", "…", sender=Sender.ACCOUNT)

    assert len(posted) == 1                     # una volta l'ora, non una per email
    assert f"Email non partite da {s.smtp_account_from_email}" in posted[0]
    assert "SMTPAuthenticationError" in posted[0]
    assert "giocatore@example.com" not in posted[0] and "sbagliata" not in posted[0]
    assert emailed == []                        # non dalla casella rotta


# ── Il battito verso Healthchecks.io ─────────────────────────────────────

class _Risposta:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"status": "ok"}

    def json(self):
        return self._body


def _rete(salute):
    """Una finta httpx.get: /health risponde `salute`, il ping si annota."""
    chiamate = []

    def get(url, **kwargs):
        chiamate.append(url)
        if url.endswith("/health"):
            if isinstance(salute, Exception):
                raise salute
            return salute
        return _Risposta()
    return get, chiamate


@pytest.fixture
def battito(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "heartbeat_url", "https://hc-ping.com/prova-uuid")
    monkeypatch.setattr(s, "site_url", "https://mull2five.it")
    return s


def test_the_heartbeat_pings_only_when_the_public_site_is_healthy(battito):
    get, chiamate = _rete(_Risposta())
    assert site_watch.heartbeat(get=get) == "ok"
    # Dal dominio pubblico, non da dentro: così si ferma anche se cade il DNS.
    assert chiamate == ["https://mull2five.it/health", "https://hc-ping.com/prova-uuid"]


@pytest.mark.parametrize("salute, stato", [
    (_Risposta(body={"status": "degraded"}), "degraded"),
    (_Risposta(status_code=502, body={}), "HTTP 502"),
    (ConnectionError("dominio irraggiungibile"), "ConnectionError"),
])
def test_no_ping_when_the_site_is_not_well(battito, salute, stato):
    """Niente battito vuol dire avviso da Healthchecks.io, dopo la tolleranza."""
    get, chiamate = _rete(salute)
    assert site_watch.heartbeat(get=get) == stato
    assert chiamate == ["https://mull2five.it/health"]


def test_no_heartbeat_without_its_address(monkeypatch):
    monkeypatch.setattr(get_settings(), "heartbeat_url", None)
    get, chiamate = _rete(_Risposta())
    assert site_watch.heartbeat(get=get) is None
    assert chiamate == []


def test_a_lost_ping_does_not_break_the_loop(battito):
    def get(url, **kwargs):
        if url.endswith("/health"):
            return _Risposta()
        raise TimeoutError("hc-ping.com non risponde")
    assert site_watch.heartbeat(get=get) == "ok"


def test_the_heartbeat_is_not_mistaken_for_the_github_check(client):
    """/health riconosce il controllo da GitHub dallo User-Agent: il battito ne
    ha un altro, e non deve far credere che GitHub stia ancora controllando."""
    site_watch.status_check.last_seen = -1.0
    client.get("/health", headers={"User-Agent": site_watch.HEARTBEAT_AGENT})
    assert site_watch.status_check.last_seen == -1.0
