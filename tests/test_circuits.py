"""
test_circuits.py — Il circuito (la lega) del negozio: si scelgono i tornei, anche
già giocati, o si aggiungono man mano; la classifica somma vittorie, pareggi,
partecipazioni e tornei vinti.
"""
from types import SimpleNamespace

from backend.app.routers.seasons import _champion
from tests.test_query_counts import _counting


def _login(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, **extra):
    body = {
        "name": "Lega del venerdì", "format": "Modern", "starts_on": "2027-05-01",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "standings_public": True,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _played(client, org, players, winner):
    """Un torneo concluso in un turno: `winner` (il nome) batte l'altro 2-0; None è un pareggio 1-1."""
    tid = _tournament(client, org)
    for headers in players:
        reg = client.post(f"/api/tournaments/{tid}/registrations",
                          json={"wizards_account": "12345678"}, headers=headers)
        assert reg.status_code == 201, reg.text
        client.post(f"/api/tournaments/{tid}/registrations/{reg.json()['id']}/mark-paid", headers=org)
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text
    pairing = next(p for p in started.json()["pairings"] if p["player_b"])
    a_wins = pairing["player_a"] == winner
    score = (1, 1) if winner is None else (2, 0) if a_wins else (0, 2)
    saved = client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result", headers=org,
                         json={"match_wins_a": score[0], "match_wins_b": score[1], "draws": 0})
    assert saved.status_code == 200, saved.text
    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200
    return tid


def _circuit(client, org, **extra):
    body = {"name": "Lega di prova", "points_win": 3, "points_draw": 1}
    body.update(extra)
    created = client.post("/api/seasons", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _board(client, season_id):
    response = client.get(f"/api/seasons/{season_id}/leaderboard")
    assert response.status_code == 200, response.text
    return {row["player_name"]: row for row in response.json()}


def test_a_list_of_played_and_future_tournaments(client):
    org = _login(client, "lega-org1@example.com", role="organizer")
    anna, bruno = _login(client, "anna1@example.com"), _login(client, "bruno1@example.com")
    first = _played(client, org, [anna, bruno], winner="anna1")
    second = _played(client, org, [anna, bruno], winner="anna1")
    future = _tournament(client, org)
    client.post(f"/api/tournaments/{future}/registrations", json={"wizards_account": "1"}, headers=anna)

    circuit = _circuit(client, org, points_participation=1, points_champion_bonus=2)
    added = client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org,
                        json={"tournament_ids": [first, second, future]})
    assert added.status_code == 200, added.text
    assert added.json()["tournament_count"] == 3

    board = _board(client, circuit["id"])
    # Due vittorie (6) + due tappe giocate (2) + due tornei vinti (4).
    assert board["anna1"]["points"] == 12
    assert (board["anna1"]["titles"], board["anna1"]["tournaments_played"]) == (2, 2)
    # Solo la partecipazione: la tappa futura non conta finché non si gioca.
    assert board["bruno1"]["points"] == 2
    assert board["anna1"]["position"] == 1

    mine = {t["id"]: t["season_id"] for t in client.get("/api/tournaments/mine", headers=org).json()}
    assert mine[first] == mine[future] == circuit["id"]


def test_added_one_at_a_time_as_they_are_played(client):
    org = _login(client, "lega-org2@example.com", role="organizer")
    anna, bruno = _login(client, "anna2@example.com"), _login(client, "bruno2@example.com")
    circuit = _circuit(client, org)
    assert _board(client, circuit["id"]) == {}

    first = _played(client, org, [anna, bruno], winner="bruno2")
    assert client.post(f"/api/seasons/{circuit['id']}/tournaments/{first}", headers=org).status_code == 200
    assert _board(client, circuit["id"])["bruno2"]["points"] == 3    # subito, senza aspettare la cache

    second = _played(client, org, [anna, bruno], winner="anna2")
    client.post(f"/api/seasons/{circuit['id']}/tournaments/{second}", headers=org)
    board = _board(client, circuit["id"])
    assert board["anna2"]["points"] == board["bruno2"]["points"] == 3
    assert board["anna2"]["tournaments_played"] == 2


def test_remove_and_move_a_tournament(client):
    org = _login(client, "lega-org3@example.com", role="organizer")
    anna, bruno = _login(client, "anna3@example.com"), _login(client, "bruno3@example.com")
    first = _played(client, org, [anna, bruno], winner="anna3")
    second = _played(client, org, [anna, bruno], winner="anna3")
    circuit = _circuit(client, org)
    client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org,
                json={"tournament_ids": [first, second]})
    assert _board(client, circuit["id"])["anna3"]["points"] == 6

    removed = client.delete(f"/api/seasons/{circuit['id']}/tournaments/{first}", headers=org)
    assert removed.status_code == 200 and removed.json()["tournament_count"] == 1
    assert _board(client, circuit["id"])["anna3"]["points"] == 3
    assert client.delete(f"/api/seasons/{circuit['id']}/tournaments/{first}", headers=org).status_code == 404

    # Un torneo sta in un circuito solo: aggiunto a un altro, lascia il primo.
    other = _circuit(client, org, name="Altra lega")
    client.post(f"/api/seasons/{other['id']}/tournaments/{second}", headers=org)
    assert _board(client, circuit["id"]) == {}
    assert _board(client, other["id"])["anna3"]["points"] == 3


def test_closed_circuit_takes_no_tournaments_until_reopened(client):
    org = _login(client, "lega-org4@example.com", role="organizer")
    circuit = _circuit(client, org)
    tid = _tournament(client, org)
    assert client.post(f"/api/seasons/{circuit['id']}/close", headers=org).status_code == 200
    assert client.post(f"/api/seasons/{circuit['id']}/tournaments/{tid}", headers=org).status_code == 409

    reopened = client.patch(f"/api/seasons/{circuit['id']}", headers=org, json={"is_active": True})
    assert reopened.status_code == 200 and reopened.json()["is_active"] is True
    assert client.post(f"/api/seasons/{circuit['id']}/tournaments/{tid}", headers=org).status_code == 200


def test_someone_elses_tournament_spoils_the_whole_batch(client):
    org = _login(client, "lega-org5@example.com", role="organizer")
    stranger = _login(client, "lega-altro5@example.com", role="organizer")
    mine, theirs = _tournament(client, org), _tournament(client, stranger)
    circuit = _circuit(client, org)
    refused = client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org,
                          json={"tournament_ids": [mine, theirs]})
    assert refused.status_code == 404
    assert client.get("/api/seasons/mine", headers=org).json()[0]["tournament_count"] == 0
    # E il circuito di un altro non si tocca.
    assert client.delete(f"/api/seasons/{circuit['id']}/tournaments/{mine}", headers=stranger).status_code == 404
    assert client.get("/api/seasons/mine", headers=stranger).json() == []


def test_mine_shows_private_and_closed_the_public_list_does_not(client):
    org = _login(client, "lega-org6@example.com", role="organizer")
    hidden = _circuit(client, org, name="Lega segreta", is_public=False)
    closed = _circuit(client, org, name="Lega finita")
    client.post(f"/api/seasons/{closed['id']}/close", headers=org)

    mine = {s["name"] for s in client.get("/api/seasons/mine", headers=org).json()}
    assert {"Lega segreta", "Lega finita"} <= mine
    public = {s["name"] for s in client.get("/api/seasons").json()}
    assert not {"Lega segreta", "Lega finita"} & public
    assert hidden["is_public"] is False


def test_threshold_and_dates_can_be_cleared(client):
    org = _login(client, "lega-org7@example.com", role="organizer")
    circuit = _circuit(client, org, qualification_threshold=10, starts_on="2027-01-01")
    assert circuit["qualification_threshold"] == 10
    cleared = client.patch(f"/api/seasons/{circuit['id']}", headers=org,
                           json={"qualification_threshold": None, "starts_on": None, "name": None})
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["qualification_threshold"] is None and body["starts_on"] is None
    assert body["name"] == "Lega di prova"


def test_deleting_the_circuit_keeps_the_tournaments(client):
    org = _login(client, "lega-org8@example.com", role="organizer")
    circuit = _circuit(client, org)
    tid = _tournament(client, org)
    client.post(f"/api/seasons/{circuit['id']}/tournaments/{tid}", headers=org)
    assert client.delete(f"/api/seasons/{circuit['id']}", headers=org).status_code == 204
    assert client.get(f"/api/tournaments/{tid}").json()["season_id"] is None
    assert client.get("/api/seasons/mine", headers=org).json() == []


def test_undefeated_bonus_needs_every_match_won(client):
    """La lega del negozio: 1 punto presenza, 1 bonus imbattuto, niente bonus vincitore."""
    org = _login(client, "lega-org10@example.com", role="organizer")
    anna, bruno = _login(client, "anna10@example.com"), _login(client, "bruno10@example.com")
    circuit = _circuit(client, org, points_participation=1, points_undefeated_bonus=1)
    assert circuit["points_undefeated_bonus"] == 1
    won = _played(client, org, [anna, bruno], winner="anna10")
    drawn = _played(client, org, [anna, bruno], winner=None)
    client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org, json={"tournament_ids": [won, drawn]})

    board = _board(client, circuit["id"])
    # Tappa vinta: 3 + 1 presenza + 1 imbattuto. Tappa pareggiata: 1 + 1, nessun bonus.
    assert (board["anna10"]["points"], board["anna10"]["undefeated"]) == (7, 1)
    assert (board["bruno10"]["points"], board["bruno10"]["undefeated"]) == (3, 0)


def test_the_two_worst_scores_go_above_four_tournaments(client):
    org = _login(client, "lega-org11@example.com", role="organizer")
    anna, bruno = _login(client, "anna11@example.com"), _login(client, "bruno11@example.com")
    carla, dario = _login(client, "carla11@example.com"), _login(client, "dario11@example.com")
    circuit = _circuit(client, org, points_participation=1, drop_worst_scores=2, drop_above_tournaments=4)
    add = lambda ids: client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org,  # noqa: E731
                                  json={"tournament_ids": ids})

    # Quattro tornei: non più di quattro, si somma tutto. Anna 4 a tappa, Bruno 1.
    add([_played(client, org, [anna, bruno], winner="anna11") for _ in range(4)])
    board = _board(client, circuit["id"])
    assert (board["anna11"]["points"], board["anna11"]["discarded"]) == (16, 0)
    assert (board["bruno11"]["points"], board["bruno11"]["discarded"]) == (4, 0)

    # Il quinto: si tolgono i due punteggi peggiori di ognuno.
    add([_played(client, org, [anna, bruno], winner="bruno11")])
    board = _board(client, circuit["id"])
    assert (board["anna11"]["points"], board["anna11"]["discarded"]) == (12, 5)     # 4+4+4+4+1, via 1 e 4
    assert (board["bruno11"]["points"], board["bruno11"]["discarded"]) == (6, 2)    # 1+1+1+1+4, via 1 e 1

    # Il sesto lo giocano altri due: per Anna e Bruno è una tappa saltata, vale 0 e va negli scarti.
    add([_played(client, org, [carla, dario], winner="carla11")])
    board = _board(client, circuit["id"])
    assert (board["anna11"]["points"], board["anna11"]["discarded"]) == (16, 1)     # via 0 e 1
    assert (board["bruno11"]["points"], board["bruno11"]["discarded"]) == (7, 1)    # via 0 e 1
    assert (board["carla11"]["points"], board["carla11"]["discarded"]) == (4, 0)    # via due tappe da 0
    assert board["anna11"]["position"] == 1


def test_existing_circuits_keep_their_leaderboard(client):
    """Senza bonus imbattuto e senza scarti la classifica è quella di sempre."""
    org = _login(client, "lega-org12@example.com", role="organizer")
    anna, bruno = _login(client, "anna12@example.com"), _login(client, "bruno12@example.com")
    circuit = _circuit(client, org)
    assert (circuit["points_undefeated_bonus"], circuit["drop_worst_scores"]) == (0, 0)
    ids = [_played(client, org, [anna, bruno], winner="anna12") for _ in range(5)]
    client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org, json={"tournament_ids": ids})
    board = _board(client, circuit["id"])
    assert (board["anna12"]["points"], board["anna12"]["discarded"]) == (15, 0)

    changed = client.patch(f"/api/seasons/{circuit['id']}", headers=org,
                           json={"drop_worst_scores": 2, "drop_above_tournaments": 4})
    assert changed.status_code == 200 and changed.json()["drop_worst_scores"] == 2
    assert _board(client, circuit["id"])["anna12"]["points"] == 9        # la modifica si vede subito


def test_with_a_top_cut_the_final_decides_the_champion():
    swiss = SimpleNamespace(player_a_registration_id=1, player_b_registration_id=2, result="A", round_id=1)
    semi = SimpleNamespace(player_a_registration_id=1, player_b_registration_id=3, result="A", round_id=2)
    final = SimpleNamespace(player_a_registration_id=1, player_b_registration_id=4, result="B", round_id=3)
    rows = [(swiss, "swiss", 1), (semi, "topcut", 2), (final, "topcut", 3)]
    assert _champion(SimpleNamespace(game="mtg"), [], rows) == 4
    # Finale senza risultato: nessun vincitore, nessun bonus.
    final.result = None
    assert _champion(SimpleNamespace(game="mtg"), [], rows) is None


def test_leaderboard_queries_do_not_grow_with_tournaments(client, db_session):
    org = _login(client, "lega-org9@example.com", role="organizer")
    anna, bruno = _login(client, "anna9@example.com"), _login(client, "bruno9@example.com")
    circuit = _circuit(client, org, points_champion_bonus=1)

    def count():
        db_session.expunge_all()
        with _counting() as statements:
            assert client.get(f"/api/seasons/{circuit['id']}/leaderboard").status_code == 200
        return len(statements)

    ids = [_played(client, org, [anna, bruno], winner="anna9") for _ in range(2)]
    client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org, json={"tournament_ids": ids})
    few = count()
    ids = [_played(client, org, [anna, bruno], winner="anna9") for _ in range(4)]
    client.post(f"/api/seasons/{circuit['id']}/tournaments", headers=org, json={"tournament_ids": ids})
    many = count()
    assert many == few, f"2 tornei: {few} query, 6 tornei: {many}"
    assert _board(client, circuit["id"])["anna9"]["titles"] == 6
