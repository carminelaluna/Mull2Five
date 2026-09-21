"""
test_tournament_settings.py — La scheda Impostazioni: cosa si cambia, e quando no.
"""
from datetime import date, timedelta


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
        "name": "Serata del giovedì", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=7)), "start_time": "20:00",
        "capacity": 8, "entry_fee_cents": 500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _patch(client, org, tid, **changes):
    return client.patch(f"/api/tournaments/{tid}", headers=org, json=changes)


def _enroll(client, org, tid, email, pay=False):
    player = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                      json={"wizards_account": email[:6]})
    assert reg.status_code == 201, reg.text
    if pay:
        assert client.post(f"/api/tournaments/{tid}/registrations/{reg.json()['id']}/mark-paid",
                           headers=org).status_code == 200
    return reg.json()


def test_settings_change_and_are_logged(client):
    org = _register_user(client, "set-org@example.com", role="organizer")
    tid = _tournament(client, org)
    updated = _patch(client, org, tid, name="Serata del venerdì", capacity=16,
                     description="Porta le bustine", round_timer_minutes=45)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["name"], body["capacity"], body["round_timer_minutes"]) == ("Serata del venerdì", 16, 45)

    audit = client.get(f"/api/tournaments/{tid}/audit", headers=org).json()
    entry = next(a for a in audit if a["action"] == "tournament_updated")
    assert "capacity: 8 → 16" in entry["detail"]


def test_changing_game_resets_the_match_format(client):
    org = _register_user(client, "set-org2@example.com", role="organizer")
    tid = _tournament(client, org)
    body = _patch(client, org, tid, game="onepiece", format="Standard").json()
    assert (body["game"], body["best_of"]) == ("onepiece", 1)
    # ...a meno che non se ne scelga uno esplicitamente.
    assert _patch(client, org, tid, game="lorcana", best_of=2).json()["best_of"] == 2


def test_after_the_start_some_settings_are_locked(client):
    org = _register_user(client, "set-org3@example.com", role="organizer")
    tid = _tournament(client, org, entry_fee_cents=0)
    for i in range(2):
        _enroll(client, org, tid, f"set-p{i}@example.com", pay=True)
    assert client.post(f"/api/tournaments/{tid}/start", headers=org).status_code == 200

    locked = _patch(client, org, tid, capacity=32, game="pokemon")
    assert locked.status_code == 409
    assert "capacity" in locked.json()["detail"] and "game" in locked.json()["detail"]
    # Il nome e il timer invece si sistemano anche a torneo in corso.
    assert _patch(client, org, tid, name="Serata (rinviata)", round_timer_minutes=40).status_code == 200


def test_capacity_cannot_drop_below_the_players_already_in(client):
    org = _register_user(client, "set-org4@example.com", role="organizer")
    tid = _tournament(client, org)
    for i in range(3):
        _enroll(client, org, tid, f"set-cap{i}@example.com")
    assert _patch(client, org, tid, capacity=2).status_code == 409
    assert _patch(client, org, tid, capacity=3).status_code == 200


def test_raising_capacity_lets_the_waitlist_in(client):
    org = _register_user(client, "set-org5@example.com", role="organizer")
    tid = _tournament(client, org, capacity=2)
    regs = [_enroll(client, org, tid, f"set-wl{i}@example.com") for i in range(3)]
    assert regs[2]["waitlisted"] is True

    assert _patch(client, org, tid, capacity=3).status_code == 200
    rows = {r["id"]: r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()}
    assert rows[regs[2]["id"]]["waitlisted"] is False


def test_the_fee_is_frozen_once_someone_paid(client):
    org = _register_user(client, "set-org6@example.com", role="organizer")
    tid = _tournament(client, org)
    assert _patch(client, org, tid, entry_fee_cents=700).status_code == 200
    _enroll(client, org, tid, "set-pay@example.com", pay=True)
    assert _patch(client, org, tid, entry_fee_cents=900).status_code == 409


def test_at_least_one_payment_method_remains(client):
    org = _register_user(client, "set-org7@example.com", role="organizer")
    tid = _tournament(client, org)
    assert _patch(client, org, tid, pay_at_event=False).status_code == 422
    assert _patch(client, org, tid, pay_at_event=False, pay_paypal=True).status_code == 200


def test_only_the_owner_edits(client):
    org = _register_user(client, "set-org8@example.com", role="organizer")
    other = _register_user(client, "set-org9@example.com", role="organizer")
    tid = _tournament(client, org)
    assert _patch(client, other, tid, name="Presa in prestito").status_code == 404
