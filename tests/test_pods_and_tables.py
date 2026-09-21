"""
test_pods_and_tables.py — Pod di draft e tavoli fissi.
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


def _draft(client, org, players, prefix):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Draft del sabato", "format": "Draft",
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "15:00",
        "capacity": 32, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    regs = []
    for i in range(players):
        player = _register_user(client, f"{prefix}{tid}-{i}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""}).json()
        client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid", headers=org)
        regs.append(reg["id"])
    return tid, regs


def test_pods_are_balanced_and_seated(client):
    org = _register_user(client, "pod-org@example.com", role="organizer")
    tid, _ = _draft(client, org, 18, "pod")
    pods = client.post(f"/api/tournaments/{tid}/pods", headers=org, json={"pod_size": 8}).json()
    assert [len(p["players"]) for p in pods] == [6, 6, 6]
    assert all([s["seat"] for s in p["players"]] == list(range(1, 7)) for p in pods)
    assert client.get(f"/api/tournaments/{tid}/pods").json() == pods   # pubblici


def test_the_first_round_is_played_across_the_table_inside_the_pod(client):
    org = _register_user(client, "pod-org2@example.com", role="organizer")
    tid, _ = _draft(client, org, 10, "podr")
    pods = client.post(f"/api/tournaments/{tid}/pods", headers=org, json={"pod_size": 8}).json()
    assert [len(p["players"]) for p in pods] == [5, 5]
    where = {s["registration_id"]: (p["pod"], s["seat"]) for p in pods for s in p["players"]}

    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    byes = 0
    for pairing in round1["pairings"]:
        a, b = pairing["player_a_registration_id"], pairing.get("player_b_registration_id")
        if not b:
            byes += 1
            continue
        assert where[a][0] == where[b][0]                 # stesso pod
        assert abs(where[a][1] - where[b][1]) == 3        # di fronte: 1-4, 2-5 in un pod da 5
    assert byes == 2                                      # uno per pod dispari

    # A torneo iniziato i pod non si rifanno.
    assert client.post(f"/api/tournaments/{tid}/pods", headers=org, json={"pod_size": 8}).status_code == 409


def test_a_fixed_table_is_kept(client):
    org = _register_user(client, "table-org@example.com", role="organizer")
    tid, regs = _draft(client, org, 6, "tab")
    fixed = client.put(f"/api/tournaments/{tid}/registrations/{regs[0]}/fixed-table", headers=org, json={"table": 10})
    assert fixed.status_code == 200 and fixed.json()["fixed_table"] == 10

    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    tables = {p["table_number"] for p in round1["pairings"]}
    star = next(p for p in round1["pairings"] if regs[0] in (p["player_a_registration_id"], p.get("player_b_registration_id")))
    assert star["table_number"] == 10
    assert tables == {1, 2, 10}                           # gli altri riempiono i numeri liberi


def test_pods_can_be_cleared_before_the_start(client):
    org = _register_user(client, "pod-org3@example.com", role="organizer")
    tid, _ = _draft(client, org, 4, "podc")
    client.post(f"/api/tournaments/{tid}/pods", headers=org, json={"pod_size": 8})
    assert client.delete(f"/api/tournaments/{tid}/pods", headers=org).status_code == 204
    assert client.get(f"/api/tournaments/{tid}/pods").json() == []
