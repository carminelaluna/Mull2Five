"""
test_games.py — Più giochi: formato dei match, filtro in ricerca, dati del torneo.
"""
from datetime import date, timedelta


def _register_user(client, email, role="player", name=None):
    client.post("/api/auth/register", json={
        "email": email, "display_name": name or email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, **extra):
    body = {
        "name": extra.pop("name", "Torneo di prova"), "format": extra.pop("format", "Standard"),
        "starts_on": str(date.today() + timedelta(days=3)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def test_the_catalog_lists_the_five_games(client):
    games = {g["code"]: g for g in client.get("/api/games").json()}
    assert set(games) == {"mtg", "lorcana", "swu", "onepiece", "pokemon"}
    assert games["onepiece"]["default_best_of"] == 1
    assert games["pokemon"]["tiebreakers"] == "pokemon"
    assert "Premier" in games["swu"]["formats"]


def test_match_format_defaults_to_the_game_rules(client):
    org = _register_user(client, "games-org@example.com", role="organizer")
    assert _tournament(client, org, game="onepiece")["best_of"] == 1
    assert _tournament(client, org, game="lorcana")["best_of"] == 3
    # Il regolamento è il punto di partenza, non un vincolo.
    assert _tournament(client, org, game="onepiece", best_of=3)["best_of"] == 3


def test_an_unknown_game_is_refused(client):
    org = _register_user(client, "games-org2@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Gioco inventato", "format": "X", "game": "scacchi",
        "starts_on": str(date.today() + timedelta(days=3)), "capacity": 8,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert created.status_code == 422


def test_search_filters_by_game(client):
    org = _register_user(client, "games-org3@example.com", role="organizer")
    _tournament(client, org, name="Serata Magic", game="mtg")
    _tournament(client, org, name="Serata Lorcana", game="lorcana", format="Core Constructed")
    names = [t["name"] for t in client.get("/api/tournaments?games=lorcana").json()]
    assert names == ["Serata Lorcana"]


def test_the_tournament_shows_who_organizes_it(client):
    org = _register_user(client, "games-org4@example.com", role="organizer", name="Marta Rossi")
    tid = _tournament(client, org)["id"]
    assert client.get(f"/api/tournaments/{tid}").json()["organizer_name"] == "Marta Rossi"
    listed = next(t for t in client.get("/api/tournaments").json() if t["id"] == tid)
    assert listed["organizer_name"] == "Marta Rossi"


def _first_pairing(client, org, **extra):
    tournament = _tournament(client, org, **extra)
    tid = tournament["id"]
    for i in range(2):
        player = _register_user(client, f"games-p{i}-{tid}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                          json={"wizards_account": f"G{i}{tid}"})
        assert reg.status_code == 201, reg.text
        # Solo chi ha pagato gioca: qui il pagamento al banco, segnato dall'organizzatore.
        paid = client.post(f"/api/tournaments/{tid}/registrations/{reg.json()['id']}/mark-paid",
                           headers=org)
        assert paid.status_code == 200, paid.text
    round_ = client.post(f"/api/tournaments/{tid}/start", headers=org)   # genera il turno 1
    assert round_.status_code == 200, round_.text
    pairing = next(p for p in round_.json()["pairings"] if p.get("player_b_registration_id"))
    return tid, pairing["id"]


def _report(client, org, tid, pid, a, b):
    return client.patch(f"/api/tournaments/{tid}/pairings/{pid}/result", headers=org,
                        json={"match_wins_a": a, "match_wins_b": b})


def test_best_of_one_refuses_a_two_game_score(client):
    org = _register_user(client, "games-org5@example.com", role="organizer")
    tid, pid = _first_pairing(client, org, game="onepiece")
    assert _report(client, org, tid, pid, 2, 1).status_code == 422
    assert _report(client, org, tid, pid, 1, 0).status_code == 200


def test_best_of_three_accepts_two_to_one(client):
    org = _register_user(client, "games-org6@example.com", role="organizer")
    tid, pid = _first_pairing(client, org, game="mtg")
    assert _report(client, org, tid, pid, 2, 1).status_code == 200
