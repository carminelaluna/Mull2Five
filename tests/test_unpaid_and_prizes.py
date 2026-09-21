"""
test_unpaid_and_prizes.py — Togliere chi non ha pagato; segnare i premi consegnati.
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


def _tournament(client, org, fee=1000, capacity=3):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern del venerdì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=4)), "start_time": "20:00",
        "capacity": capacity, "entry_fee_cents": fee, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _enroll(client, org, tid, email, pay=False):
    player = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""})
    assert reg.status_code == 201, reg.text
    if pay:
        assert client.post(f"/api/tournaments/{tid}/registrations/{reg.json()['id']}/mark-paid",
                           headers=org).status_code == 200
    return reg.json()


def test_unpaid_players_leave_and_the_waitlist_moves_up(client):
    org = _register_user(client, "unpaid-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=3)
    _enroll(client, org, tid, "unpaid-paid@example.com", pay=True)
    _enroll(client, org, tid, "unpaid-a@example.com")
    _enroll(client, org, tid, "unpaid-b@example.com")
    waiting = _enroll(client, org, tid, "unpaid-wait@example.com")
    assert waiting["waitlisted"] is True

    preview = client.post(f"/api/tournaments/{tid}/drop-unpaid", headers=org).json()
    assert preview == {"dropped": ["unpaid-a", "unpaid-b"], "promoted": 0}
    assert not any(r["dropped"] for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json())

    done = client.post(f"/api/tournaments/{tid}/drop-unpaid?dry_run=false", headers=org).json()
    assert done == {"dropped": ["unpaid-a", "unpaid-b"], "promoted": 1}
    rows = {r["player_email"]: r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()}
    assert rows["unpaid-a@example.com"]["dropped"] and rows["unpaid-b@example.com"]["dropped"]
    assert not rows["unpaid-paid@example.com"]["dropped"]
    assert rows["unpaid-wait@example.com"]["waitlisted"] is False

    audit = client.get(f"/api/tournaments/{tid}/audit", headers=org).json()
    assert any(a["action"] == "unpaid_dropped" for a in audit)


def test_nothing_to_drop_when_free_or_started(client):
    org = _register_user(client, "unpaid-org2@example.com", role="organizer")
    free = _tournament(client, org, fee=0)
    assert client.post(f"/api/tournaments/{free}/drop-unpaid", headers=org).status_code == 409

    paid_event = _tournament(client, org, capacity=8)
    for i in range(2):
        _enroll(client, org, paid_event, f"unpaid-s{i}@example.com", pay=True)
    assert client.post(f"/api/tournaments/{paid_event}/start", headers=org).status_code == 200
    assert client.post(f"/api/tournaments/{paid_event}/drop-unpaid", headers=org).status_code == 409


def test_prizes_are_recorded_and_can_be_undone(client):
    org = _register_user(client, "prize-org@example.com", role="organizer")
    tid = _tournament(client, org)
    reg = _enroll(client, org, tid, "prize-winner@example.com", pay=True)
    url = f"/api/tournaments/{tid}/registrations/{reg['id']}/prize"

    given = client.put(url, headers=org, json={"given": True, "note": "3 buste"}).json()
    assert given["prize_note"] == "3 buste" and given["prize_given_at"]
    undone = client.put(url, headers=org, json={"given": False}).json()
    assert undone["prize_note"] == "" and undone["prize_given_at"] is None

    actions = [(a["action"], a["detail"]) for a in client.get(f"/api/tournaments/{tid}/audit", headers=org).json()]
    assert ("prize_given", "prize-winner: 3 buste") in actions
    assert ("prize_revoked", "prize-winner: 3 buste") in actions


def test_only_the_organizer_hands_out_prizes(client):
    org = _register_user(client, "prize-org2@example.com", role="organizer")
    tid = _tournament(client, org)
    reg = _enroll(client, org, tid, "prize-p2@example.com")
    other = _register_user(client, "prize-other@example.com", role="organizer")
    assert client.put(f"/api/tournaments/{tid}/registrations/{reg['id']}/prize", headers=other,
                      json={"given": True}).status_code == 404
