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
    public_id = client.get("/api/auth/me", headers=players[0]["headers"]).json()["public_id"]
    r = client.get(f"/api/tournaments/players/{public_id}/public-history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["public_id"] == public_id
    assert "email" not in body
    assert body["tournaments_played"] >= 1
    assert len(body["rows"]) >= 1

    # identificativo inesistente → 404
    assert client.get("/api/tournaments/players/nessuno/public-history").status_code == 404


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
    from backend.app.services.pairings import default_swiss_rounds
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


# ── Organizzatore carica la lista per un iscritto ─────────────


def test_organizer_uploads_decklist_for_registration(client):
    org = _register(client, "v2-deck-org@example.com", role="organizer")
    tid = _make_tournament(client, org, decklist_required=True)
    reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                      json={"email": "deckp@example.com", "display_name": "DeckP", "mark_paid": True})
    rid = reg.json()["id"]
    deck = "4 Lightning Bolt\n4 Ragavan, Nimble Pilferer\n52 Mountain\n\nSideboard\n2 Blood Moon"
    r = client.post(f"/api/tournaments/{tid}/registrations/{rid}/decklist", headers=org,
                    json={"raw_text": deck, "archetype": "Burn"})
    assert r.status_code == 200, r.text
    assert r.json()["main_count"] > 0
    # ora compare nella lista iscritti
    regs = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
    row = next(x for x in regs if x["id"] == rid)
    assert row["decklist_status"] in ("valid", "invalid")
    assert row["decklist_raw_text"].startswith("4 Lightning Bolt")


# ── Profilo pubblico organizzatore ────────────────────────────


def test_public_profile_shows_organized_tournaments(client):
    org = _register(client, "v2-prof-org2@example.com", role="organizer")
    _make_tournament(client, org, name="FNM Uno", starts_on="2027-06-01")
    _make_tournament(client, org, name="RCQ Due", starts_on="2027-07-01")
    public_id = client.get("/api/auth/me", headers=org).json()["public_id"]
    r = client.get(f"/api/tournaments/players/{public_id}/public-history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "organizer"
    names = {o["name"] for o in body["organized"]}
    assert {"FNM Uno", "RCQ Due"} <= names


# ── Storico pubblico: risultati torneo concluso ───────────────


def test_public_results_winner_and_decklists(client):
    org = _register(client, "v2-pr-org@example.com", role="organizer")
    tid = _make_tournament(client, org, standings_public=True, decklists_public=True)
    for i in range(2):
        em = f"pr{i}-{tid}@example.com"
        _register(client, em)
        client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                    json={"email": em, "display_name": f"PR{i}", "mark_paid": True})
    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    pairing = next(p for p in round1["pairings"] if p["player_b"])
    # carica una lista (come organizzatore) per il giocatore A
    a_reg = pairing["player_a_registration_id"]
    client.post(f"/api/tournaments/{tid}/registrations/{a_reg}/decklist", headers=org,
                json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn"})
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    client.post(f"/api/tournaments/{tid}/close", headers=org)

    # endpoint pubblico, senza autenticazione
    r = client.get(f"/api/tournaments/{tid}/public-results")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["standings_public"] is True
    assert len(body["standings"]) == 2
    assert body["standings"][0]["position"] == 1   # vincitore
    # la lista pubblica del giocatore con archetipo Burn è presente
    burn = next((s for s in body["standings"] if s["archetype"] == "Burn"), None)
    assert burn and burn["decklist"] and "Lightning Bolt" in burn["decklist"]


def test_public_results_hidden_when_not_public(client):
    org = _register(client, "v2-pr2-org@example.com", role="organizer")
    tid = _make_tournament(client, org, standings_public=False)
    r = client.get(f"/api/tournaments/{tid}/public-results")
    assert r.status_code == 200
    assert r.json()["standings_public"] is False
    assert r.json()["standings"] == []


# ── Parser: riga vuota = sideboard ────────────────────────────


def test_blank_line_marks_sideboard():
    from backend.app.services.decklists import validate_decklist
    deck = "4 Lightning Bolt\n56 Mountain\n\n3 Blood Moon\n2 Pyroblast"
    v = validate_decklist(deck, "Modern")
    assert v.main_count == 60
    assert v.side_count == 5   # tutto dopo la riga vuota è sideboard


def test_blank_line_before_main_ignored():
    from backend.app.services.decklists import validate_decklist
    deck = "\n\n4 Lightning Bolt\n56 Mountain"   # righe vuote iniziali ignorate
    v = validate_decklist(deck, "Modern")
    assert v.main_count == 60 and v.side_count == 0


# ── Deadline caricamento lista (solo giocatore) ───────────────


def test_decklist_locked_past_deadline(client):
    org = _register(client, "v2-dl-org@example.com", role="organizer")
    # inizio nel passato → oltre la deadline di 30 min
    tid = _make_tournament(client, org, starts_on="2020-01-01", start_time="10:00", decklist_required=True)
    player = _register(client, "v2-dl-player@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", json={"wizards_account": ""}, headers=player)
    r = client.post(f"/api/tournaments/{tid}/decklist", headers=player,
                    json={"raw_text": "4 Bolt\n56 Mountain", "archetype": "Burn"})
    assert r.status_code == 409   # liste bloccate (deadline superata)


# ── Orario di inizio ──────────────────────────────────────────


def test_tournament_start_time(client):
    org = _register(client, "v2-time-org@example.com", role="organizer")
    tid = _make_tournament(client, org, start_time="20:30")
    t = client.get(f"/api/tournaments/{tid}").json()
    assert t["start_time"] == "20:30"


def test_invalid_start_time_rejected(client):
    org = _register(client, "v2-badtime-org@example.com", role="organizer")
    r = client.post("/api/tournaments", headers=org, json={
        "name": "Bad Time", "format": "Modern", "starts_on": "2027-06-01",
        "start_time": "25:99", "capacity": 8, "entry_fee_cents": 0, "pay_at_event": True,
    })
    assert r.status_code == 422


def test_cache_set_accepts_float_ttl():
    """Regressione: ttl float non deve sollevare (Redis vuole int)."""
    from backend.app.core.cache import cache_set
    cache_set("ttltest", {"a": 1}, ttl=5.0)   # non deve lanciare


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
