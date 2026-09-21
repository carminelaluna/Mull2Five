"""
test_byes_and_tardiness.py — Bye assegnati, bye naturale, sconfitte ai ritardatari.
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


def _tournament(client, org, players, best_of=3, prefix="bye"):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern del giovedì", "format": "Modern", "best_of": best_of,
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    regs = {}
    for i in range(players):
        email = f"{prefix}{tid}-p{i}@example.com"
        player = _register_user(client, email)
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""}).json()
        assert client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid",
                           headers=org).status_code == 200
        regs[i] = reg["id"]
    return tid, regs


def _byes_of(round_):
    return [p["player_a_registration_id"] for p in round_["pairings"] if not p.get("player_b_registration_id")]


def _finish(client, org, tid, round_):
    for p in round_["pairings"]:
        if p.get("player_b_registration_id"):
            r = client.patch(f"/api/tournaments/{tid}/pairings/{p['id']}/result", headers=org,
                             json={"match_wins_a": 2, "match_wins_b": 0})
            assert r.status_code == 200, r.text


def test_assigned_byes_skip_the_first_rounds(client):
    org = _register_user(client, "bye-org@example.com", role="organizer")
    tid, regs = _tournament(client, org, players=5)
    star = regs[0]
    assigned = client.put(f"/api/tournaments/{tid}/registrations/{star}/byes", headers=org, json={"byes": 2})
    assert assigned.status_code == 200 and assigned.json()["byes"] == 2

    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    assert _byes_of(round1) == [star]            # gli altri 4 giocano
    _finish(client, org, tid, round1)
    round2 = client.post(f"/api/tournaments/{tid}/rounds?force=true", headers=org).json()
    assert star in _byes_of(round2)
    _finish(client, org, tid, round2)
    round3 = client.post(f"/api/tournaments/{tid}/rounds?force=true", headers=org).json()
    playing = {p["player_a_registration_id"] for p in round3["pairings"] if p.get("player_b_registration_id")} | {
        p["player_b_registration_id"] for p in round3["pairings"] if p.get("player_b_registration_id")}
    assert star in playing                        # al terzo turno gioca

    # A torneo iniziato i bye non si cambiano più.
    assert client.put(f"/api/tournaments/{tid}/registrations/{regs[1]}/byes", headers=org,
                      json={"byes": 1}).status_code == 409
    audit = client.get(f"/api/tournaments/{tid}/audit", headers=org).json()
    assert any(a["action"] == "byes_assigned" for a in audit)


def test_the_natural_bye_never_goes_twice_to_the_same_player(client):
    org = _register_user(client, "bye-org2@example.com", role="organizer")
    tid, _ = _tournament(client, org, players=3, prefix="nat")
    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    first_bye = _byes_of(round1)
    _finish(client, org, tid, round1)
    round2 = client.post(f"/api/tournaments/{tid}/rounds?force=true", headers=org).json()
    second_bye = _byes_of(round2)
    assert len(first_bye) == len(second_bye) == 1
    assert first_bye != second_bye


def _first_table(round_):
    return next(p for p in round_["pairings"] if p.get("player_b_registration_id"))


def test_a_no_show_loses_the_match_and_can_be_dropped(client):
    org = _register_user(client, "late-org@example.com", role="organizer")
    tid, _ = _tournament(client, org, players=2, best_of=1, prefix="late")
    table = _first_table(client.post(f"/api/tournaments/{tid}/start", headers=org).json())
    late = table["player_a_registration_id"]

    after = client.post(f"/api/tournaments/{tid}/pairings/{table['id']}/tardiness", headers=org,
                        json={"registration_id": late, "penalty": "match_loss", "drop": True})
    assert after.status_code == 200, after.text
    row = next(p for p in after.json()["pairings"] if p["id"] == table["id"])
    assert (row["result"], row["match_wins_a"], row["match_wins_b"]) == ("B", 0, 1)   # al meglio di 1: 1-0

    penalty = client.get(f"/api/tournaments/{tid}/penalties", headers=org).json()[0]
    assert (penalty["registration_id"], penalty["kind"]) == (late, "match_loss")
    assert "Non presentato al turno 1" in penalty["note"]
    regs = {r["id"]: r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()}
    assert regs[late]["dropped"] is True

    # Il tavolo ha già un risultato: una seconda sconfitta a tavolino non passa.
    again = client.post(f"/api/tournaments/{tid}/pairings/{table['id']}/tardiness", headers=org,
                        json={"registration_id": late, "penalty": "match_loss"})
    assert again.status_code == 409


def test_a_late_arrival_gets_a_game_loss_and_the_match_is_played(client):
    org = _register_user(client, "late-org2@example.com", role="organizer")
    tid, _ = _tournament(client, org, players=2, prefix="gl")
    table = _first_table(client.post(f"/api/tournaments/{tid}/start", headers=org).json())
    late = table["player_b_registration_id"]
    after = client.post(f"/api/tournaments/{tid}/pairings/{table['id']}/tardiness", headers=org,
                        json={"registration_id": late, "penalty": "game_loss"}).json()
    row = next(p for p in after["pairings"] if p["id"] == table["id"])
    assert row["result"] == ""                                   # si gioca
    kinds = [p["kind"] for p in client.get(f"/api/tournaments/{tid}/penalties", headers=org).json()]
    assert kinds == ["game_loss"]


def test_the_player_must_be_at_that_table(client):
    org = _register_user(client, "late-org3@example.com", role="organizer")
    tid, regs = _tournament(client, org, players=4, prefix="wt")
    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    table = _first_table(round1)
    other = next(r for r in regs.values() if r not in {table["player_a_registration_id"], table["player_b_registration_id"]})
    assert client.post(f"/api/tournaments/{tid}/pairings/{table['id']}/tardiness", headers=org,
                       json={"registration_id": other}).status_code == 422
