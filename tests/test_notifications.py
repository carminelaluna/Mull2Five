"""
test_notifications.py — Le email che il torneo manda da solo.

Iscrizione confermata, turno abbinato, torneo avviato, pagamento incassato:
partono dentro le rotte, quindi da un thread del pool di FastAPI e non dal
ciclo asincrono. Se quel dettaglio si rompe non se ne accorge nessuno — chi
chiama ingoiava l'errore — e i giocatori smettono di ricevere le email.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def sent(monkeypatch):
    """Le email consegnate, senza uscire dal processo."""
    from backend.app.core.config import get_settings
    from backend.app.services import email

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    delivered = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            delivered.append(message)

    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    return delivered


def _tournament(client, org):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Serata di prova", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
        "email_notifications_enabled": True,
    })
    assert created.status_code == 201, created.text
    return created.json()


def test_registering_sends_the_confirmation_email(client, sent):
    org = _register_user(client, "notif-org@example.com", role="organizer")
    tid = _tournament(client, org)["id"]
    player = _register_user(client, "notif-player@example.com")

    assert client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).status_code == 201

    assert [m["To"] for m in sent] == ["notif-player@example.com"]
    assert "Serata di prova" in sent[0]["Subject"]


def test_starting_the_tournament_tells_the_players(client, sent):
    org = _register_user(client, "notif-org2@example.com", role="organizer")
    tid = _tournament(client, org)["id"]
    for i in range(2):
        player = _register_user(client, f"notif-p{i}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).json()
        # Si abbina solo chi ha pagato: al banco lo segna l'organizzatore.
        client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid", headers=org)
    sent.clear()

    assert client.post(f"/api/tournaments/{tid}/start", headers=org).status_code == 200

    # Torneo avviato più abbinamenti pronti, a ciascuno dei due giocatori.
    assert sorted({m["To"] for m in sent}) == ["notif-p0@example.com", "notif-p1@example.com"]
