"""
test_penalty_history.py — Lo storico penalità del giocatore, per chi lo arbitra in un altro torneo.
"""
from datetime import timedelta

from backend.app.core.clock import local_today


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, name, days):
    created = client.post("/api/tournaments", headers=org, json={
        "name": name, "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=days)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _enroll(client, tid, player):
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""})
    assert reg.status_code == 201, reg.text
    return reg.json()["id"]


def test_judges_see_what_happened_in_other_tournaments(client):
    first_org = _register_user(client, "hist-org1@example.com", role="organizer")
    second_org = _register_user(client, "hist-org2@example.com", role="organizer")
    player = _register_user(client, "hist-player@example.com")

    before = _tournament(client, first_org, "Modern di settembre", 1)
    reg_before = _enroll(client, before, player)
    for kind, note in (("game_loss", "Deck error"), ("note", "Appunto interno")):
        client.post(f"/api/tournaments/{before}/penalties", headers=first_org,
                    json={"registration_id": reg_before, "kind": kind, "note": note})

    now = _tournament(client, second_org, "Modern di ottobre", 5)
    reg_now = _enroll(client, now, player)
    row = client.get(f"/api/tournaments/{now}/registrations", headers=second_org).json()[0]
    assert row["prior_penalties"] == 1                     # la nota non conta

    history = client.get(f"/api/tournaments/{now}/registrations/{reg_now}/penalty-history", headers=second_org).json()
    assert [(h["tournament_name"], h["kind"], h["note"]) for h in history] == [
        ("Modern di settembre", "game_loss", "Deck error"),
    ]
    assert history[0]["judge_name"] == "hist-org1"


def test_only_the_staff_of_the_current_tournament_reads_it(client):
    org = _register_user(client, "hist-org3@example.com", role="organizer")
    player = _register_user(client, "hist-player2@example.com")
    tid = _tournament(client, org, "Serata", 3)
    reg = _enroll(client, tid, player)
    outsider = _register_user(client, "hist-out@example.com", role="organizer")
    assert client.get(f"/api/tournaments/{tid}/registrations/{reg}/penalty-history", headers=outsider).status_code == 404
    assert client.get(f"/api/tournaments/{tid}/registrations/{reg}/penalty-history", headers=player).status_code == 404
