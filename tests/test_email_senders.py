"""
test_email_senders.py — Da quale casella parte ogni email.

Il reset password parte da una casella, i pagamenti da un'altra, il resto da
quella generale: chi risponde a una ricevuta deve arrivare a chi segue i
pagamenti, non perdersi fra gli avvisi dei turni. Con le caselle di register.it
ogni indirizzo entra con le sue credenziali, e un server SMTP che riceve un
mittente diverso da chi è entrato rifiuta l'email.
"""
import pytest

from backend.app.core.config import get_settings
from backend.app.services import email
from backend.app.services.email import Sender, send_email


@pytest.fixture
def smtp(monkeypatch):
    """Ogni consegna: con chi è entrato e che cosa ha mandato."""
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(get_settings(), "email_async", False)
    delivered: list[tuple[tuple | None, object]] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            self.credentials = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            self.credentials = (username, password)

        def send_message(self, message):
            delivered.append((self.credentials, message))

    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    return delivered


@pytest.fixture
def three_mailboxes(monkeypatch):
    settings = get_settings()
    for name, value in {
        "smtp_from_email": "Mull2Five <admin@example.com>",
        "smtp_username": "admin@example.com",
        "smtp_password": "pw-admin",
        "smtp_account_from_email": "Mull2Five <info@example.com>",
        "smtp_account_username": "info@example.com",
        "smtp_account_password": "pw-info",
        "smtp_payments_from_email": "Mull2Five <commercial@example.com>",
        "smtp_payments_username": "commercial@example.com",
        "smtp_payments_password": "pw-commercial",
    }.items():
        monkeypatch.setattr(settings, name, value)


@pytest.mark.parametrize(("sender", "mailbox"), [
    (Sender.ACCOUNT, "info"),
    (Sender.PAYMENTS, "commercial"),
    (Sender.GENERAL, "admin"),
])
def test_each_kind_of_email_leaves_from_its_own_mailbox(smtp, three_mailboxes, sender, mailbox):
    assert send_email("player@example.com", "Oggetto", "Testo", sender=sender) is True

    [(credentials, message)] = smtp
    assert message["From"] == f"Mull2Five <{mailbox}@example.com>"
    assert credentials == (f"{mailbox}@example.com", f"pw-{mailbox}")


def test_the_password_reset_leaves_from_the_account_mailbox(client, smtp, three_mailboxes):
    client.post("/api/auth/register", json={
        "email": "reset-me@example.com", "display_name": "reset-me",
        "password": "supersecret123", "role": "player",
    })

    response = client.post("/api/auth/forgot-password", json={"email": "reset-me@example.com"})

    assert response.status_code == 200, response.text
    [(credentials, message)] = [d for d in smtp if d[1]["To"] == "reset-me@example.com"]
    assert message["From"] == "Mull2Five <info@example.com>"
    assert credentials == ("info@example.com", "pw-info")


def test_an_address_without_its_own_credentials_uses_the_general_ones(smtp, monkeypatch):
    """Brevo: una chiave sola, e i mittenti sono indirizzi del dominio autenticato."""
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_from_email", "general@example.com")
    monkeypatch.setattr(settings, "smtp_username", "relay-login")
    monkeypatch.setattr(settings, "smtp_password", "relay-key")
    monkeypatch.setattr(settings, "smtp_payments_from_email", "payments@example.com")

    send_email("player@example.com", "Ricevuta", "Testo", sender=Sender.PAYMENTS)

    [(credentials, message)] = smtp
    assert message["From"] == "payments@example.com"
    assert credentials == ("relay-login", "relay-key")


def test_without_a_mailbox_of_its_own_everything_leaves_from_the_general_one(smtp, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_from_email", "general@example.com")
    monkeypatch.setattr(settings, "smtp_username", "general-login")
    monkeypatch.setattr(settings, "smtp_password", "general-pw")

    send_email("player@example.com", "Reset", "Testo", sender=Sender.ACCOUNT)

    [(credentials, message)] = smtp
    assert message["From"] == "general@example.com"
    assert credentials == ("general-login", "general-pw")
