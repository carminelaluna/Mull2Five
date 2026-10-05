"""
test_reminders.py — Il promemoria del giorno prima.

Tre cose devono essere vere, o il promemoria fa più danni che bene: parte una
volta sola (il compito gira ogni ora), va solo a chi è dentro davvero, e dice
dove si paga a chi non ha ancora pagato.
"""
from datetime import timedelta

from backend.app.core.clock import local_today
from backend.app.services import reminders
from backend.app.services.reminders import send_event_reminders


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, *, giorni=1, capacity=2, avvisi=True):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern di domani", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=giorni)), "start_time": "20:00",
        "capacity": capacity, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
        "email_notifications_enabled": avvisi, "venue": "Il Covo del Drago",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _enroll(client, tid, email):
    player = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""})
    assert reg.status_code == 201, reg.text
    return reg.json()


def _catch_emails(monkeypatch):
    inviate: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        reminders, "send_email",
        lambda to, subject, body, html_body=None: bool(inviate.append((to, subject, body))) or True,
    )
    return inviate


def test_the_reminder_goes_out_once_and_only_to_the_players_who_are_in(client, db_session, monkeypatch):
    inviate = _catch_emails(monkeypatch)
    org = _register_user(client, "promemoria-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=2)
    _enroll(client, tid, "promemoria-dentro@example.com")
    _enroll(client, tid, "promemoria-dentro2@example.com")
    coda = _enroll(client, tid, "promemoria-coda@example.com")
    assert coda["waitlisted"] is True, "il terzo deve finire in lista d'attesa"

    assert send_event_reminders(db_session) == 2
    assert [m[0] for m in inviate] == [
        "promemoria-dentro@example.com", "promemoria-dentro2@example.com",
    ]
    _, oggetto, corpo = inviate[0]
    assert "Domani" in oggetto
    assert "domani si gioca" in corpo
    assert "Il Covo del Drago" in corpo
    assert f"event.html?id={tid}" in corpo
    # Non ha pagato: deve saperlo prima di trovarsi al banco con la fila dietro.
    assert "ancora da pagare" in corpo

    # Il compito gira ogni ora: al secondo passaggio non deve ripartire niente.
    assert send_event_reminders(db_session) == 0
    assert len(inviate) == 2


def test_no_reminder_for_other_days_or_when_the_organizer_said_no(client, db_session, monkeypatch):
    inviate = _catch_emails(monkeypatch)
    org = _register_user(client, "promemoria-org2@example.com", role="organizer")

    dopodomani = _tournament(client, org, giorni=2)
    _enroll(client, dopodomani, "promemoria-dopo@example.com")
    zitto = _tournament(client, org, giorni=1, avvisi=False)
    _enroll(client, zitto, "promemoria-zitto@example.com")

    assert send_event_reminders(db_session) == 0
    assert inviate == []
