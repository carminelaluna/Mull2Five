"""
test_v2_features.py — Test delle funzionalità/fix introdotti nella V2:

- timer: non parte all'avvio, stop, stop alla chiusura
- round generato pubblicato e refertabile dai giocatori
- contestazione risultato (conflict → chiama Judge)
- filtri di ricerca tornei (nome/formato/stato/data)
- profilo pubblico giocatore per email
- duplica torneo, organizzazioni, classifica visibile a torneo chiuso
"""


def _register(client, email, role="player", name=None):
    client.post("/api/auth/register", json={
        "email": email, "display_name": name or email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tournament(client, headers, **overrides):
    payload = {
        "name": "V2 Test Open", "format": "Modern", "starts_on": "2027-06-01",
        "capacity": 8, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "decklist_required": False, "pairings_public": True, "standings_public": True,
        "pay_at_event": True,
    }
    payload.update(overrides)
    r = client.post("/api/tournaments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_started(client, org, n=2, **t_overrides):
    """Torneo avviato con n giocatori paganti (walk-in). Ritorna (tid, round1, players)."""
    tid = _make_tournament(client, org, **t_overrides)
    players = []
    for i in range(n):
        email = f"v2p{i}-{tid}@example.com"
        h = _register(client, email)
        # walk-in dell'organizzatore: iscrive e segna pagato
        reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
            "email": email, "display_name": f"Player{i}", "mark_paid": True,
        })
        assert reg.status_code == 201, reg.text
        players.append({"headers": h, "registration_id": reg.json()["id"], "email": email})
    start = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert start.status_code == 200, start.text
    return tid, start.json(), players


# ── Timer lifecycle ───────────────────────────────────────────


def test_start_does_not_start_timer(client):
    org = _register(client, "v2-timer-org@example.com", role="organizer")
    tid, round1, _ = _seed_started(client, org)
    assert round1["ends_at"] is None   # il timer NON parte all'avvio
    disp = client.get(f"/api/tournaments/{tid}/public-display").json()
    assert disp["round_ends_at"] is None


def test_timer_restart_then_stop(client):
    org = _register(client, "v2-stop-org@example.com", role="organizer")
    tid, _, _ = _seed_started(client, org)

    r = client.post(f"/api/tournaments/{tid}/timer/restart", json={"minutes": 50}, headers=org)
    assert r.status_code == 200 and r.json()["ends_at"] is not None

    r = client.post(f"/api/tournaments/{tid}/timer/stop", headers=org)
    assert r.status_code == 200, r.text
    assert r.json()["ends_at"] is None   # Stop azzera il timer


def test_close_stops_all_timers(client):
    org = _register(client, "v2-close-org@example.com", role="organizer")
    tid, _, _ = _seed_started(client, org)
    client.post(f"/api/tournaments/{tid}/timer/restart", json={"minutes": 50}, headers=org)

    r = client.post(f"/api/tournaments/{tid}/close", headers=org)
    assert r.status_code == 200 and r.json()["status"] == "completed"

    rounds = client.get(f"/api/tournaments/{tid}/rounds", headers=org).json()
    assert all(rnd["ends_at"] is None for rnd in rounds)   # timer fermi alla chiusura


def test_timer_stop_requires_staff(client):
    org = _register(client, "v2-auth-org@example.com", role="organizer")
    tid, _, players = _seed_started(client, org)
    r = client.post(f"/api/tournaments/{tid}/timer/stop", headers=players[0]["headers"])
    assert r.status_code in (403, 404)   # un giocatore non può fermare il timer


# ── Round pubblicato e refertabile ────────────────────────────


def test_generated_round_is_published_and_reportable(client):
    org = _register(client, "v2-pub-org@example.com", role="organizer")
    tid, round1, players = _seed_started(client, org)
    assert round1["is_published"] is True
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    by_reg = {p["registration_id"]: p for p in players}
    a = by_reg[pairing["player_a_registration_id"]]
    # Un giocatore può refertare subito (round pubblicato all'avvio)
    r = client.patch(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result",
        json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=a["headers"])
    assert r.status_code == 200, r.text


# ── Contestazione risultato (conflict → Judge) ────────────────


def test_player_result_reject_creates_conflict(client):
    org = _register(client, "v2-reject-org@example.com", role="organizer")
    tid, round1, players = _seed_started(client, org)
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    by_reg = {p["registration_id"]: p for p in players}
    a = by_reg[pairing["player_a_registration_id"]]
    b = by_reg[pairing["player_b_registration_id"]]

    # A referta, B contesta → stato conflict
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=a["headers"])
    r = client.post(f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result/reject",
                    json={"note": "Punteggio errato"}, headers=b["headers"])
    assert r.status_code == 200, r.text
    pj = next(p for p in r.json()["pairings"] if p["id"] == pairing["id"])
    assert pj["report_status"] == "conflict"
    assert pj["result"] == ""   # nessun risultato applicato finché c'è conflitto


def test_opponent_sees_report_immediately(client):
    """Dopo che A referta, B deve vedere il report (sezione conferma)."""
    org = _register(client, "v2-see-org@example.com", role="organizer")
    tid, round1, players = _seed_started(client, org)
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    by_reg = {p["registration_id"]: p for p in players}
    a = by_reg[pairing["player_a_registration_id"]]
    b = by_reg[pairing["player_b_registration_id"]]

    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result",
                 json={"match_wins_a": 2, "match_wins_b": 1, "draws": 0}, headers=a["headers"])
    seen = client.get(f"/api/tournaments/{tid}/my-pairings", headers=b["headers"]).json()
    p = seen[0]["pairings"][0]
    assert p["report_status"] == "pending"
    assert p["report_reporter_registration_id"] == a["registration_id"]


# ── Filtri di ricerca tornei ──────────────────────────────────


def test_list_tournaments_filters(client):
    org = _register(client, "v2-search-org@example.com", role="organizer")
    _make_tournament(client, org, name="Modern Masters", format="Modern", starts_on="2027-07-01")
    _make_tournament(client, org, name="Legacy Legends", format="Legacy", starts_on="2027-09-01")

    names = lambda r: {t["name"] for t in r.json()}  # noqa: E731
    assert names(client.get("/api/tournaments?name=legacy")) == {"Legacy Legends"}
    assert names(client.get("/api/tournaments?format=Modern")) == {"Modern Masters"}
    assert names(client.get("/api/tournaments?date_from=2027-08-01")) == {"Legacy Legends"}
    both = client.get("/api/tournaments?status=published").json()
    assert {"Modern Masters", "Legacy Legends"} <= {t["name"] for t in both}


# ── Profilo pubblico giocatore ────────────────────────────────


def test_public_player_history(client):
    org = _register(client, "v2-prof-org@example.com", role="organizer")
    tid, round1, players = _seed_started(client, org, standings_public=True)
    # chiudi una partita così ci sono standings
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    email = players[0]["email"]
    r = client.get(f"/api/tournaments/players/{email}/public-history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == email
    assert body["tournaments_played"] >= 1
    assert len(body["rows"]) >= 1

    # email inesistente → 404
    assert client.get("/api/tournaments/players/nobody@nowhere.it/public-history").status_code == 404


# ── Duplica torneo ────────────────────────────────────────────


def test_duplicate_tournament(client):
    org = _register(client, "v2-dup-org@example.com", role="organizer")
    tid = _make_tournament(client, org, name="FNM Settimanale", starts_on="2027-06-06")
    r = client.post(f"/api/tournaments/{tid}/duplicate", headers=org)
    assert r.status_code == 201, r.text
    copy = r.json()
    assert copy["id"] != tid
    assert copy["name"] == "FNM Settimanale"
    assert copy["starts_on"] == "2027-06-13"   # +7 giorni
    assert copy["registered_players"] == 0


# ── Organizzazioni (multi-tenant) ─────────────────────────────


def test_organizations_endpoints(client):
    r = client.get("/api/organizations")
    assert r.status_code == 200 and isinstance(r.json(), list)
    cur = client.get("/api/organizations/current")
    # In assenza di seed può essere 404; con org di default è 200
    assert cur.status_code in (200, 404)


# ── Round svizzeri automatici = ceil(log2(iscritti)) ──────────


def test_default_swiss_rounds_is_log2():
    from backend.app.routers.tournaments import default_swiss_rounds
    assert default_swiss_rounds(2) == 1
    assert default_swiss_rounds(4) == 2
    assert default_swiss_rounds(8) == 3
    assert default_swiss_rounds(16) == 4
    assert default_swiss_rounds(32) == 5   # 32 persone → 5 turni
    assert default_swiss_rounds(64) == 6
    assert default_swiss_rounds(9) == 4    # non potenza di 2: ceil(log2(9))


def test_extra_swiss_round_requires_force(client):
    """Superati i turni previsti, /rounds chiede conferma (409); con force=true procede."""
    org = _register(client, "v2-extra-org@example.com", role="organizer")
    # 2 giocatori → turni previsti = ceil(log2(2)) = 1
    tid, round1, players = _seed_started(client, org)
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    # referta il turno 1 (necessario per generarne un altro)
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)

    # turno 2 > previsti(1) senza force → 409 con marcatore EXTRA_SWISS_ROUND
    r = client.post(f"/api/tournaments/{tid}/rounds", headers=org)
    assert r.status_code == 409
    assert "EXTRA_SWISS_ROUND" in r.json()["detail"]

    # con force=true → procede (abbinamenti eventualmente ripetuti)
    r = client.post(f"/api/tournaments/{tid}/rounds?force=true", headers=org)
    assert r.status_code == 200, r.text
    assert r.json()["number"] == 2


# ── Classifica visibile a torneo chiuso ───────────────────────


def test_standings_visible_after_close(client):
    org = _register(client, "v2-stand-org@example.com", role="organizer")
    tid, round1, _ = _seed_started(client, org)
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    client.post(f"/api/tournaments/{tid}/close", headers=org)
    r = client.get(f"/api/tournaments/{tid}/standings", headers=org)
    assert r.status_code == 200
    assert len(r.json()) == 2   # standings consultabili anche dopo la chiusura
