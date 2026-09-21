"""
test_registration_only.py — Eventi di sola iscrizione: si raccolgono iscritti, niente turni.
"""
from datetime import date, timedelta

from backend.app.core.clock import local_today


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _event(client, org, starts_on):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Serata casual", "format": "Commander", "structure": "registration_only",
        "rules_enforcement_level": "Competitive",
        "starts_on": str(starts_on), "start_time": "20:00", "capacity": 20,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_players_register_but_there_are_no_rounds(client):
    org = _register_user(client, "regonly-org@example.com", role="organizer")
    tid = _event(client, org, local_today() + timedelta(days=2))
    for i in range(3):
        player = _register_user(client, f"regonly-p{i}@example.com")
        assert client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                           json={"wizards_account": ""}).status_code == 201

    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 409 and "sola iscrizione" in started.json()["detail"]
    assert client.post(f"/api/tournaments/{tid}/close", headers=org).json()["status"] == "completed"


def test_warnings_speak_about_closing(client):
    org = _register_user(client, "regonly-org2@example.com", role="organizer")
    tid = _event(client, org, local_today() - timedelta(days=1))
    codes = {w["code"]: w["message"] for w in client.get(f"/api/tournaments/{tid}/warnings", headers=org).json()}
    assert "chiudilo" in codes["missed_start"] and "avvialo" not in codes["missed_start"]
    # Senza turni non serve un capojudge, anche a REL Competitive.
    assert "no_head_judge" not in codes
