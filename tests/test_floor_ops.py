"""
test_floor_ops.py — Gestione della sala: judge assegnato al tavolo, stato del
tavolo e registro dei deck check.
"""
from datetime import date, timedelta

import jwt

from backend.app.core.config import get_settings


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _user_id(headers) -> int:
    """L'id sta nel claim `sub` del token."""
    token = headers["Authorization"].split()[1]
    return int(jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["sub"])


def _running_tournament(client):
    """Torneo avviato con un judge nello staff e due tavoli."""
    org = _register_user(client, "floor-org@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Floor Open", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=1)),
        "capacity": 8, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "decklist_required": False, "pay_stripe": True,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]

    judge = _register_user(client, "floor-judge@example.com")
    assert client.post(f"/api/tournaments/{tid}/staff", headers=org,
                       json={"email": "floor-judge@example.com", "role": "judge"}).status_code == 201

    regs = []
    for i in range(4):
        headers = _register_user(client, f"floor-p{i}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                          json={"wizards_account": f"F{i}"})
        checkout = client.post(f"/api/tournaments/{tid}/checkout", headers=headers,
                               json={"provider": "stripe"})
        client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")
        regs.append(reg.json()["id"])

    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text
    return tid, org, judge, started.json()["pairings"], regs


# ── Judge sui tavoli ──────────────────────────────────────────


def test_judge_can_be_assigned_and_released(client):
    tid, org, judge, pairings, _ = _running_tournament(client)
    pid = pairings[0]["id"]
    judge_id = _user_id(judge)

    assigned = client.patch(f"/api/tournaments/{tid}/pairings/{pid}/assign", headers=org,
                            json={"user_id": judge_id})
    assert assigned.status_code == 200, assigned.text
    table = next(p for p in assigned.json()["pairings"] if p["id"] == pid)
    assert table["assigned_judge_id"] == judge_id
    assert table["assigned_judge_name"] == "floor-judge"

    freed = client.patch(f"/api/tournaments/{tid}/pairings/{pid}/assign", headers=org,
                         json={"user_id": None})
    table = next(p for p in freed.json()["pairings"] if p["id"] == pid)
    assert table["assigned_judge_id"] is None
    assert table["assigned_judge_name"] == ""


def test_table_goes_only_to_someone_on_the_staff(client):
    """Assegnare un tavolo a un giocatore qualunque non ha senso in sala."""
    tid, org, _, pairings, _ = _running_tournament(client)
    estraneo = _register_user(client, "floor-outsider@example.com")

    refused = client.patch(f"/api/tournaments/{tid}/pairings/{pairings[0]['id']}/assign",
                           headers=org, json={"user_id": _user_id(estraneo)})
    assert refused.status_code == 422, refused.text


def test_the_judge_assigns_tables_too(client):
    """Non serve l'organizzatore: chi e in sala si prende il tavolo."""
    tid, _, judge, pairings, _ = _running_tournament(client)
    taken = client.patch(f"/api/tournaments/{tid}/pairings/{pairings[0]['id']}/assign",
                         headers=judge, json={"user_id": _user_id(judge)})
    assert taken.status_code == 200, taken.text


def test_outsiders_cannot_touch_the_floor(client):
    tid, _, _, pairings, _ = _running_tournament(client)
    estraneo = _register_user(client, "floor-nosy@example.com")
    pid = pairings[0]["id"]

    assert client.patch(f"/api/tournaments/{tid}/pairings/{pid}/assign", headers=estraneo,
                        json={"user_id": None}).status_code == 404
    assert client.patch(f"/api/tournaments/{tid}/pairings/{pid}/status", headers=estraneo,
                        json={"status": "called"}).status_code == 404


# ── Stato del tavolo ──────────────────────────────────────────


def test_table_status_defaults_to_playing_and_changes(client):
    tid, org, judge, pairings, _ = _running_tournament(client)
    pid = pairings[0]["id"]
    assert pairings[0]["table_status"] == "playing"

    called = client.patch(f"/api/tournaments/{tid}/pairings/{pid}/status", headers=judge,
                          json={"status": "called"})
    assert called.status_code == 200, called.text
    assert next(p for p in called.json()["pairings"] if p["id"] == pid)["table_status"] == "called"


def test_unknown_table_status_is_refused(client):
    tid, org, _, pairings, _ = _running_tournament(client)
    bad = client.patch(f"/api/tournaments/{tid}/pairings/{pairings[0]['id']}/status",
                       headers=org, json={"status": "esploso"})
    assert bad.status_code == 422


# ── Deck check ────────────────────────────────────────────────


def test_deck_check_is_recorded_with_round_and_judge(client):
    tid, org, judge, _, regs = _running_tournament(client)

    created = client.post(f"/api/tournaments/{tid}/deck-checks", headers=judge, json={
        "registration_id": regs[0], "result": "minor", "note": "Una carta in piu a side",
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["judge_name"] == "floor-judge"
    assert body["round_number"] == 1
    assert body["result"] == "minor"

    listed = client.get(f"/api/tournaments/{tid}/deck-checks", headers=org)
    assert listed.status_code == 200, listed.text
    assert [c["note"] for c in listed.json()] == ["Una carta in piu a side"]


def test_deck_checks_are_staff_only(client):
    tid, _, judge, _, regs = _running_tournament(client)
    client.post(f"/api/tournaments/{tid}/deck-checks", headers=judge,
                json={"registration_id": regs[0], "result": "ok"})
    player = _register_user(client, "floor-curious@example.com")

    assert client.get(f"/api/tournaments/{tid}/deck-checks", headers=player).status_code == 404
    assert client.post(f"/api/tournaments/{tid}/deck-checks", headers=player,
                       json={"registration_id": regs[0], "result": "ok"}).status_code == 404


def test_deck_check_survives_a_round_regeneration(client):
    """E un atto del torneo, non uno stato del turno: rigenerare non lo cancella."""
    tid, org, judge, _, regs = _running_tournament(client)
    client.post(f"/api/tournaments/{tid}/deck-checks", headers=judge,
                json={"registration_id": regs[0], "result": "major", "note": "Deck error"})

    regenerated = client.post(f"/api/tournaments/{tid}/rounds/regenerate", headers=org,
                              json={"drop_registration_ids": []})
    assert regenerated.status_code == 200, regenerated.text

    checks = client.get(f"/api/tournaments/{tid}/deck-checks", headers=org).json()
    assert [c["result"] for c in checks] == ["major"]


def test_deck_check_needs_a_registration_of_this_tournament(client):
    tid, org, judge, _, _ = _running_tournament(client)
    bad = client.post(f"/api/tournaments/{tid}/deck-checks", headers=judge,
                      json={"registration_id": 9999, "result": "ok"})
    assert bad.status_code == 404
