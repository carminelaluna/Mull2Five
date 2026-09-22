"""
test_official.py — ID dell'editore e programmi ufficiali.

Un RCQ ha il suo ID evento (EventLink) e un invito al Regional Championship per
chi vince: il report ufficiale mette insieme classifica e Wizards Account, e
segnala chi non l'ha dato, perché senza l'invito non arriva.
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


def _tournament(client, org, **extra):
    body = {
        "name": "RCQ di ottobre", "format": "Pioneer", "event_type": "rcq", "sanction_id": "EL-123456",
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "10:00",
        "capacity": 32, "entry_fee_cents": 2000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "standings_public": True,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _play_and_close(client, org, tid, winner_registration_id):
    pairing = client.post(f"/api/tournaments/{tid}/start", headers=org).json()["pairings"][0]
    a_wins = pairing["player_a_registration_id"] == winner_registration_id
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result", headers=org,
                 json={"match_wins_a": 2 if a_wins else 0, "match_wins_b": 0 if a_wins else 2})
    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200


def test_an_rcq_invites_its_winner_and_the_report_lists_the_ids(client):
    org = _register_user(client, "official-org@example.com", role="organizer")
    rcq = _tournament(client, org)
    assert (rcq["sanction_id"], rcq["invites"]) == ("EL-123456", 1)
    assert _tournament(client, org, name="Pioneer del giovedì", event_type="locals")["invites"] == 0

    tid = rcq["id"]
    client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                json={"display_name": "Anna", "wizards_account": "1111111111"})
    bruno = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={"display_name": "Bruno"}).json()

    before = {w["code"]: w for w in client.get(f"/api/tournaments/{tid}/warnings", headers=org).json()}
    assert "Bruno" in before["missing_publisher_ids"]["message"]

    _play_and_close(client, org, tid, bruno["id"])
    report = client.get(f"/api/tournaments/{tid}/official-report", headers=org).json()
    assert (report["sanction_id"], report["players"], report["invites"]) == ("EL-123456", 2, 1)
    assert [(r["name"], r["publisher_id"], r["invited"]) for r in report["rows"]] == [
        ("Bruno", "", True), ("Anna", "1111111111", False),
    ]
    assert report["missing_ids"] == ["Bruno"]

    fixed = client.put(f"/api/tournaments/{tid}/registrations/{bruno['id']}/publisher-id", headers=org,
                       json={"publisher_id": "2222222222"})
    assert fixed.status_code == 200, fixed.text
    assert client.get(f"/api/tournaments/{tid}/official-report", headers=org).json()["missing_ids"] == []

    csv = client.get(f"/api/tournaments/{tid}/official-report.csv", headers=org)
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[1].startswith("1;Bruno;2222222222")

    outsider = _register_user(client, "official-outsider@example.com", role="organizer")
    assert client.get(f"/api/tournaments/{tid}/official-report", headers=outsider).status_code in {403, 404}


def test_players_add_their_id_and_see_the_invite_on_their_profile(client):
    org = _register_user(client, "official-org2@example.com", role="organizer")
    tid = _tournament(client, org)["id"]
    player = _register_user(client, "official-player@example.com")
    mine = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).json()
    client.post(f"/api/tournaments/{tid}/registrations/{mine['id']}/mark-paid", headers=org)
    client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                json={"display_name": "Carla", "wizards_account": "3333333333"})

    updated = client.put(f"/api/tournaments/{tid}/my-publisher-id", headers=player, json={"publisher_id": " 4444444444 "})
    assert updated.status_code == 200 and updated.json()["wizards_account"] == "4444444444"
    assert client.get("/api/auth/me/publisher-ids", headers=player).json() == {"mtg": "4444444444"}

    _play_and_close(client, org, tid, mine["id"])
    profile = client.get("/api/tournaments/players/official-player@example.com/public-history").json()
    row = next(r for r in profile["rows"] if r["tournament_id"] == tid)
    assert (row["placement"], row["invited"], row["event_type"]) == (1, True, "rcq")
