"""
test_teams.py — Tornei a squadre: composizione, abbinamenti posto contro posto, classifica.
"""
from datetime import timedelta

from backend.app.core.clock import local_today
from backend.app.services.standings import TeamMatch, compute_team_standings


def test_team_standings_count_the_seats_won():
    rows = compute_team_standings(
        {1: "Alfa", 2: "Beta", 3: "Gamma"},
        [TeamMatch(a=1, b=2, seats_a=2, seats_b=1), TeamMatch(a=3, b=None)],
    )
    assert [(r["name"], r["points"], r["record"]) for r in rows] == [
        ("Alfa", 3, "1/0/0"), ("Gamma", 3, "1/0/0"), ("Beta", 0, "0/1/0"),
    ]
    assert rows[0]["seat_wins"] == 2


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _team_event(client, org, players, prefix, **extra):
    body = {
        "name": "Team Sealed", "format": "Sealed", "team_size": 3,
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "10:00",
        "capacity": 30, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    regs = []
    for i in range(players):
        player = _register_user(client, f"{prefix}{tid}-{i}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""}).json()
        client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid", headers=org)
        regs.append(reg["id"])
    return tid, regs


def _team(client, org, tid, name, members):
    teams = client.post(f"/api/tournaments/{tid}/teams", headers=org, json={"name": name}).json()
    team_id = next(t["id"] for t in teams if t["name"] == name)
    for seat, rid in enumerate(members, start=1):
        r = client.put(f"/api/tournaments/{tid}/teams/{team_id}/seats/{seat}", headers=org, json={"registration_id": rid})
        assert r.status_code == 200, r.text
    return team_id


def test_teams_play_seat_against_seat_and_win_with_two_seats(client):
    org = _register_user(client, "team-org@example.com", role="organizer")
    tid, regs = _team_event(client, org, 6, "tm")
    alfa = _team(client, org, tid, "Alfa", regs[:3])
    _team(client, org, tid, "Beta", regs[3:])
    seat_of = {rid: (i % 3) + 1 for i, rid in enumerate(regs)}
    team_of = {rid: ("Alfa" if i < 3 else "Beta") for i, rid in enumerate(regs)}

    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    pairings = sorted(round1["pairings"], key=lambda p: p["table_number"])
    assert [p["table_number"] for p in pairings] == [1, 2, 3]
    for p in pairings:
        a, b = p["player_a_registration_id"], p["player_b_registration_id"]
        assert seat_of[a] == seat_of[b] and team_of[a] != team_of[b]

    # Alfa vince due posti su tre: vince l'incontro.
    for index, p in enumerate(pairings):
        alfa_is_a = team_of[p["player_a_registration_id"]] == "Alfa"
        alfa_wins = index < 2
        wins = (2, 0) if alfa_wins == alfa_is_a else (0, 2)
        client.patch(f"/api/tournaments/{tid}/pairings/{p['id']}/result", headers=org,
                     json={"match_wins_a": wins[0], "match_wins_b": wins[1]})
    table = client.get(f"/api/tournaments/{tid}/team-standings").json()
    assert [(r["team_id"], r["points"], r["seat_wins"]) for r in table][0] == (alfa, 3, 2)

    player = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()[0]
    assert player["team_name"] in {"Alfa", "Beta"} and player["team_seat"] in {1, 2, 3}


def test_incomplete_teams_sit_out(client):
    org = _register_user(client, "team-org2@example.com", role="organizer")
    tid, regs = _team_event(client, org, 8, "ti")
    _team(client, org, tid, "Alfa", regs[:3])
    _team(client, org, tid, "Beta", regs[3:6])
    _team(client, org, tid, "Gamma", regs[6:8])          # manca il terzo
    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    playing = {p["player_a_registration_id"] for p in round1["pairings"]} | {
        p["player_b_registration_id"] for p in round1["pairings"] if p.get("player_b_registration_id")}
    assert playing == set(regs[:6])
    teams = {t["name"]: t["complete"] for t in client.get(f"/api/tournaments/{tid}/teams").json()}
    assert teams == {"Alfa": True, "Beta": True, "Gamma": False}


def test_team_rules(client):
    org = _register_user(client, "team-org3@example.com", role="organizer")
    refused = client.post("/api/tournaments", headers=org, json={
        "name": "Squadre a eliminazione", "format": "Sealed", "team_size": 3, "structure": "single_elimination",
        "starts_on": str(local_today() + timedelta(days=3)), "capacity": 8,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert refused.status_code == 422

    tid, regs = _team_event(client, org, 3, "tr")
    _team(client, org, tid, "Alfa", regs[:1])
    teams = client.post(f"/api/tournaments/{tid}/teams", headers=org, json={"name": "Beta"}).json()
    beta = next(t["id"] for t in teams if t["name"] == "Beta")
    moved = client.put(f"/api/tournaments/{tid}/teams/{beta}/seats/1", headers=org, json={"registration_id": regs[0]})
    assert moved.status_code == 409                       # è già nella squadra Alfa
