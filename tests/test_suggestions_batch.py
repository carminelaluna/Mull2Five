"""
test_suggestions_batch.py — Test per il batch di suggerimenti #39/#37/#41/#43/#46/#32/#45.

- #39 correzione risultato post-torneo + audit log
- #37 no-show: marca assenti e rigenera l'ultimo round
- #41 statistiche meta (archetipi + win rate)
- #43 annulla iscrizione self-service + rimborso
- #46 bracket pubblico dalla SPA
- #32 scadenza promozione waitlist (sweep diretto)
- #45 ricevuta pagamento (sandbox complete → PAID + timer waitlist azzerato)
"""
from datetime import UTC, datetime, timedelta


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
        "name": "Batch Test Open", "format": "Modern", "starts_on": "2027-06-01",
        "capacity": 8, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "decklist_required": False, "pairings_public": True, "standings_public": True,
        "pay_at_event": True,
    }
    payload.update(overrides)
    r = client.post("/api/tournaments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_started(client, org, n=2, **t_overrides):
    tid = _make_tournament(client, org, **t_overrides)
    players = []
    for i in range(n):
        email = f"batchp{i}-{tid}@example.com"
        h = _register(client, email)
        reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
            "email": email, "display_name": f"Player{i}", "mark_paid": True,
        })
        assert reg.status_code == 201, reg.text
        players.append({"headers": h, "registration_id": reg.json()["id"], "email": email})
    start = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert start.status_code == 200, start.text
    return tid, start.json(), players


# ── #39 correzione risultato + audit log ──────────────────────
def test_correct_result_post_close_and_audit(client):
    org = _register(client, "corr-org@example.com", role="organizer")
    tid, round1, _ = _seed_started(client, org)
    pairing = round1["pairings"][0]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    client.post(f"/api/tournaments/{tid}/close", headers=org)

    # Correzione consentita anche a torneo chiuso
    r = client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/correct",
                     json={"match_wins_a": 0, "match_wins_b": 2, "draws": 0}, headers=org)
    assert r.status_code == 200, r.text
    corrected = next(p for p in r.json()["pairings"] if p["id"] == pairing["id"])
    assert corrected["match_wins_b"] == 2

    audit = client.get(f"/api/tournaments/{tid}/audit", headers=org)
    assert audit.status_code == 200, audit.text
    actions = [a["action"] for a in audit.json()]
    assert "correct_result" in actions


# ── #37 no-show: rigenera l'ultimo round ──────────────────────
def test_regenerate_round_marks_no_show(client):
    org = _register(client, "noshow-org@example.com", role="organizer")
    tid, round1, players = _seed_started(client, org, n=4)
    drop_id = players[0]["registration_id"]

    r = client.post(f"/api/tournaments/{tid}/rounds/regenerate",
                    json={"drop_registration_ids": [drop_id]}, headers=org)
    assert r.status_code == 200, r.text
    # il giocatore segnato assente non compare più negli abbinamenti
    seated = set()
    for p in r.json()["pairings"]:
        seated.add(p["player_a_registration_id"])
        if p["player_b_registration_id"]:
            seated.add(p["player_b_registration_id"])
    assert drop_id not in seated


def test_regenerate_blocked_with_results(client):
    org = _register(client, "noshow2-org@example.com", role="organizer")
    tid, round1, _ = _seed_started(client, org, n=4)
    pairing = round1["pairings"][0]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    r = client.post(f"/api/tournaments/{tid}/rounds/regenerate",
                    json={"drop_registration_ids": []}, headers=org)
    assert r.status_code == 409, r.text


# ── #41 statistiche meta ──────────────────────────────────────
def test_meta_stats(client):
    org = _register(client, "meta-org@example.com", role="organizer")
    tid, round1, _ = _seed_started(client, org)
    pairing = round1["pairings"][0]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=org)
    r = client.get(f"/api/tournaments/{tid}/meta-stats", headers=org)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows
    assert sum(row["players"] for row in rows) == 2
    for row in rows:
        assert 0.0 <= row["win_rate"] <= 100.0


# ── #43 annulla iscrizione + rimborso ─────────────────────────
def test_cancel_registration_refunds_when_paid(client):
    org = _register(client, "cancel-org@example.com", role="organizer")
    tid = _make_tournament(client, org, start_time="20:00")
    h = _register(client, "cancel-player@example.com")
    reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "cancel-player@example.com", "display_name": "Canceller", "mark_paid": True,
    })
    assert reg.status_code == 201, reg.text

    r = client.post(f"/api/tournaments/{tid}/my-registration/cancel", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert r.json()["refunded"] is True


# ── #46 bracket pubblico ──────────────────────────────────────
def test_public_bracket_gated_on_pairings_public(client):
    org = _register(client, "brk-org@example.com", role="organizer")
    tid, _, _ = _seed_started(client, org, pairings_public=False, structure="single_elimination")
    r = client.get(f"/api/tournaments/{tid}/public-bracket")
    assert r.status_code == 200
    assert r.json() == []   # non pubblico → vuoto

    # Reso pubblico
    tid2, _, _ = _seed_started(client, org, pairings_public=True, structure="single_elimination")
    r2 = client.get(f"/api/tournaments/{tid2}/public-bracket")
    assert r2.status_code == 200, r2.text


# ── #32 scadenza promozione waitlist (sweep diretto) ──────────
def test_waitlist_sweep_requeues_unpaid(client, db_session):
    from backend.app.models import Registration
    from backend.app.routers.tournaments import sweep_waitlist_deadlines

    org = _register(client, "sweep-org@example.com", role="organizer")
    tid = _make_tournament(client, org)
    _register(client, "sweep-player@example.com")
    reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "sweep-player@example.com", "display_name": "Promoted", "mark_paid": False,
    })
    rid = reg.json()["id"]

    # Simula una promozione dalla waitlist scaduta e non pagata
    r = db_session.get(Registration, rid)
    r.waitlisted = False
    r.promoted_at = datetime.now(UTC) - timedelta(hours=12)
    db_session.add(r)
    db_session.commit()

    # Il promosso non pagante e scaduto viene riaccodato dallo sweep.
    requeued = sweep_waitlist_deadlines(db_session)
    assert requeued == 1
    # (con un solo iscritto e un posto libero viene poi ri-promosso: ciò che conta è
    #  che lo sweep abbia rilevato e gestito la scadenza.)


# ── #45 ricevuta pagamento (sandbox) ──────────────────────────
def test_sandbox_payment_complete_clears_promoted_at(client, db_session, monkeypatch):
    from backend.app.core.config import get_settings
    from backend.app.models import Payment, Registration

    settings = get_settings()
    monkeypatch.setattr(settings, "payment_sandbox_mock", True, raising=False)

    org = _register(client, "pay-org@example.com", role="organizer")
    tid = _make_tournament(client, org, pay_stripe=True)
    h = _register(client, "pay-player@example.com")
    rr = client.post(f"/api/tournaments/{tid}/registrations", headers=h, json={"wizards_account": ""})
    assert rr.status_code == 201, rr.text

    co = client.post(f"/api/tournaments/{tid}/checkout", headers=h, json={"provider": "stripe"})
    assert co.status_code in (200, 201), co.text
    payment_id = co.json()["id"]

    # marca promoted_at per verificare che il pagamento lo azzeri (#32 + #45)
    db_session.query(Registration).filter(Registration.tournament_id == tid).update(
        {"promoted_at": datetime.now(UTC)}
    )
    db_session.commit()

    r = client.post(f"/api/payments/sandbox/{payment_id}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    pay = db_session.get(Payment, payment_id)
    assert str(pay.status).endswith("paid") or pay.status == "paid"
    updated = db_session.query(Registration).filter(Registration.tournament_id == tid).first()
    assert updated.promoted_at is None
