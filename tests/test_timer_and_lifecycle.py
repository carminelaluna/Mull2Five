"""
test_timer_and_lifecycle.py — Fuso orario del timer, lock delle liste e stato
del torneo dopo la chiusura.
"""
from datetime import UTC, datetime, timedelta


def _register_user(client, email, role="player", name=None):
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "display_name": name or email.split("@")[0],
            "password": "supersecret123",
            "role": role,
        },
    )
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tournament(client, headers, **overrides):
    payload = {
        "name": "Timer Test Open",
        "format": "Modern",
        "starts_on": "2027-07-01",
        "capacity": 8,
        "entry_fee_cents": 1500,
        "currency": "EUR",
        "status": "published",
        "decklist_required": False,
        "pairings_public": True,
        "pay_stripe": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _enroll(client, tid, email):
    headers = _register_user(client, email)
    reg = client.post(
        f"/api/tournaments/{tid}/registrations", json={"wizards_account": email[:8]}, headers=headers
    )
    assert reg.status_code == 201, reg.text
    checkout = client.post(
        f"/api/tournaments/{tid}/checkout", json={"provider": "stripe"}, headers=headers
    )
    client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")
    return headers, reg.json()["id"]


def _running_tournament(client, **overrides):
    org = _register_user(client, "timer-org@example.com", role="organizer")
    tid = _make_tournament(client, org, **overrides)
    for i in range(2):
        _enroll(client, tid, f"timer-p{i}@example.com")
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text
    return tid, org, started.json()


# ── Fuso orario ───────────────────────────────────────────────


def test_timer_returns_utc_aware_instants(client):
    """SQLite rileggeva i datetime naive: il browser li prendeva per ora locale e
    un round da 50' avviato da Roma partiva da -70."""
    tid, org, _ = _running_tournament(client)

    rnd = client.post(f"/api/tournaments/{tid}/timer/restart", json={"minutes": 50}, headers=org)
    assert rnd.status_code == 200, rnd.text
    ends_raw = rnd.json()["ends_at"]
    assert ends_raw.endswith("Z") or "+00:00" in ends_raw, f"scadenza senza fuso: {ends_raw}"

    remaining = (datetime.fromisoformat(ends_raw) - datetime.now(UTC)).total_seconds() / 60
    assert 49 < remaining <= 50, f"minuti residui fuori scala: {remaining}"

    display = client.get(f"/api/tournaments/{tid}/public-display")
    assert display.status_code == 200
    shown = display.json()["round_ends_at"]
    assert shown.endswith("Z") or "+00:00" in shown, f"display senza fuso: {shown}"


def test_created_at_is_utc_aware(client):
    """Non solo il timer: ogni istante che esce dall'API deve portare il fuso."""
    org = _register_user(client, "tz-org@example.com", role="organizer")
    tid = _make_tournament(client, org)
    announcement = client.post(
        f"/api/tournaments/{tid}/announcements",
        json={"title": "Test", "body": "corpo", "send_email": False},
        headers=org,
    )
    assert announcement.status_code == 201, announcement.text
    created = announcement.json()["created_at"]
    assert created.endswith("Z") or "+00:00" in created, f"created_at senza fuso: {created}"


# ── Lock delle liste ──────────────────────────────────────────


def test_decklist_lock_is_exposed_to_the_player(client):
    org = _register_user(client, "lock-org@example.com", role="organizer")
    deadline = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    tid = _make_tournament(client, org, decklist_required=True, decklist_deadline=deadline)

    t = client.get(f"/api/tournaments/{tid}").json()
    assert t["decklist_locked"] is False
    assert t["decklist_locks_at"] is not None
    assert t["decklist_locks_at"].endswith("Z") or "+00:00" in t["decklist_locks_at"]


def test_decklist_locks_at_falls_back_to_start_time(client):
    """Senza deadline esplicita le liste chiudono 30 minuti prima dell'inizio."""
    org = _register_user(client, "lock2-org@example.com", role="organizer")
    tid = _make_tournament(client, org, starts_on="2027-07-01", start_time="20:30")

    locks_at = client.get(f"/api/tournaments/{tid}").json()["decklist_locks_at"]
    assert datetime.fromisoformat(locks_at) == datetime(2027, 7, 1, 20, 0, tzinfo=UTC)


def test_player_can_rewrite_his_list_until_the_deadline(client):
    org = _register_user(client, "edit-org@example.com", role="organizer")
    deadline = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    tid = _make_tournament(client, org, decklist_required=True, decklist_deadline=deadline)
    player, _ = _enroll(client, tid, "edit-player@example.com")

    first = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "4 Lightning Bolt\n56 Mountain\n\nSideboard\n15 Pyroblast",
        "archetype": "Burn",
    })
    assert first.status_code == 200, first.text

    second = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "4 Ragavan, Nimble Pilferer\n56 Mountain\n\nSideboard\n15 Pyroblast",
        "archetype": "Prowess",
    })
    assert second.status_code == 200, second.text
    assert "Ragavan" in second.json()["raw_text"], "la seconda lista non ha sovrascritto la prima"

    mine = client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()
    assert mine["archetype"] == "Prowess"


def test_player_reads_back_his_own_list_only(client):
    org = _register_user(client, "read-org@example.com", role="organizer")
    tid = _make_tournament(client, org, decklist_required=True)
    player, _ = _enroll(client, tid, "read-player@example.com")
    other, _ = _enroll(client, tid, "read-other@example.com")

    assert client.get(f"/api/tournaments/{tid}/decklist", headers=player).status_code == 404
    client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn",
    })

    mine = client.get(f"/api/tournaments/{tid}/decklist", headers=player)
    assert mine.status_code == 200, mine.text
    assert "Lightning Bolt" in mine.json()["raw_text"]

    # L'avversario vede la propria assenza di lista, non la mia.
    assert client.get(f"/api/tournaments/{tid}/decklist", headers=other).status_code == 404


def test_player_cannot_touch_his_list_after_the_deadline(client):
    org = _register_user(client, "late-org@example.com", role="organizer")
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    tid = _make_tournament(client, org, decklist_required=True, decklist_deadline=past)
    player, _ = _enroll(client, tid, "late-player@example.com")

    assert client.get(f"/api/tournaments/{tid}").json()["decklist_locked"] is True
    late = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn",
    })
    assert late.status_code == 409, late.text


# ── Torneo chiuso ─────────────────────────────────────────────


def test_closed_tournament_refuses_rounds_and_timers(client):
    tid, org, round1 = _running_tournament(client)
    pairing_id = round1["pairings"][0]["id"]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing_id}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)

    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200

    refused = {
        "nuovo round": client.post(f"/api/tournaments/{tid}/rounds", headers=org),
        "riavvio timer": client.post(f"/api/tournaments/{tid}/timer/restart",
                                     json={"minutes": 50}, headers=org),
        "estensione round": client.post(f"/api/tournaments/{tid}/timer/extend",
                                        json={"minutes": 5}, headers=org),
        "estensione tavolo": client.patch(f"/api/tournaments/{tid}/pairings/{pairing_id}/extend",
                                          json={"minutes": 5}, headers=org),
    }
    for what, response in refused.items():
        assert response.status_code == 409, f"{what} accettata su torneo chiuso: {response.text}"

    # La chiusura azzera i timer e nulla li resuscita.
    display = client.get(f"/api/tournaments/{tid}/public-display").json()
    assert display["round_ends_at"] is None


def test_closed_tournament_results_stay_readable(client):
    """Lo storico resta consultabile: è il punto delle pagine pubbliche."""
    tid, org, round1 = _running_tournament(client, standings_public=True, decklists_public=True)
    pairing_id = round1["pairings"][0]["id"]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing_id}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    client.post(f"/api/tournaments/{tid}/close", headers=org)

    public = client.get(f"/api/tournaments/{tid}/public-results")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["status"] == "completed"
    assert body["standings"], "nessuna classifica sul torneo chiuso"
    assert body["standings"][0]["position"] == 1
