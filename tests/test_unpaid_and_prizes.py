"""
test_unpaid_and_prizes.py — Togliere chi non ha pagato; segnare i premi consegnati.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today
from backend.app.services import registrations
from backend.app.services.registrations import WAITLIST_PAY_HOURS


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, fee=1000, capacity=3, **extra):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern del venerdì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=4)), "start_time": "20:00",
        "capacity": capacity, "entry_fee_cents": fee, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, **extra,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _enroll(client, org, tid, email, pay=False, **extra):
    player = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": "", **extra})
    assert reg.status_code == 201, reg.text
    if pay:
        assert client.post(f"/api/tournaments/{tid}/registrations/{reg.json()['id']}/mark-paid",
                           headers=org).status_code == 200
    return reg.json()


def test_unpaid_players_leave_and_the_waitlist_moves_up(client):
    org = _register_user(client, "unpaid-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=3)
    _enroll(client, org, tid, "unpaid-paid@example.com", pay=True)
    _enroll(client, org, tid, "unpaid-a@example.com")
    _enroll(client, org, tid, "unpaid-b@example.com")
    waiting = _enroll(client, org, tid, "unpaid-wait@example.com")
    assert waiting["waitlisted"] is True

    preview = client.post(f"/api/tournaments/{tid}/drop-unpaid", headers=org).json()
    assert preview == {"dropped": ["unpaid-a", "unpaid-b"], "promoted": 0}
    assert not any(r["dropped"] for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json())

    done = client.post(f"/api/tournaments/{tid}/drop-unpaid?dry_run=false", headers=org).json()
    assert done == {"dropped": ["unpaid-a", "unpaid-b"], "promoted": 1}
    rows = {r["player_email"]: r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()}
    assert rows["unpaid-a@example.com"]["dropped"] and rows["unpaid-b@example.com"]["dropped"]
    assert not rows["unpaid-paid@example.com"]["dropped"]
    assert rows["unpaid-wait@example.com"]["waitlisted"] is False

    audit = client.get(f"/api/tournaments/{tid}/audit", headers=org).json()
    assert any(a["action"] == "unpaid_dropped" for a in audit)


@pytest.fixture
def promotion_emails(monkeypatch):
    """Le email partite, e da quale casella."""
    inviate: list[tuple[str, str, str, object]] = []
    monkeypatch.setattr(
        registrations, "send_email",
        lambda to, subject, body, html_body=None, sender=None:
            bool(inviate.append((to, subject, body, sender))) or True,
    )
    return inviate


def _promotion_of(inviate, email):
    promozioni = [m for m in inviate if m[0] == email and "Sei dentro" in m[1]]
    assert promozioni, f"nessuna email di promozione: {inviate}"
    return promozioni[-1]


def test_the_promotion_email_says_where_to_pay_and_by_when(client, promotion_emails):
    """Chi deve pagare online ha sei ore per farlo, e quell'email è l'unico posto
    in cui può venirlo a sapere: senza il link e la scadenza il posto torna in
    coda e il giocatore non capisce perché."""
    org = _register_user(client, "promo-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=2, pay_at_event=False, pay_stripe=True)
    _enroll(client, org, tid, "promo-paid@example.com", pay=True, payment_method="stripe")
    _enroll(client, org, tid, "promo-unpaid@example.com", payment_method="stripe")
    waiting = _enroll(client, org, tid, "promo-wait@example.com", payment_method="stripe")
    assert waiting["waitlisted"] is True

    client.post(f"/api/tournaments/{tid}/drop-unpaid?dry_run=false", headers=org)

    _, _, corpo, mittente = _promotion_of(promotion_emails, "promo-wait@example.com")
    assert f"event.html?id={tid}" in corpo
    assert f"{WAITLIST_PAY_HOURS} ore" in corpo
    # Chiede di pagare: parte dalla casella dei pagamenti, e lì arriva chi risponde.
    assert mittente == "payments"


def test_at_the_desk_the_promotion_email_asks_for_nothing_by_a_deadline(client, promotion_emails):
    """Al banco non c'è niente da pagare entro sei ore: il posto è suo, e
    l'email dice solo quanto pagherà il giorno del torneo."""
    org = _register_user(client, "promo-desk-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=2)
    _enroll(client, org, tid, "promo-desk-paid@example.com", pay=True)
    _enroll(client, org, tid, "promo-desk-unpaid@example.com")
    _enroll(client, org, tid, "promo-desk-wait@example.com")

    client.post(f"/api/tournaments/{tid}/drop-unpaid?dry_run=false", headers=org)

    _, _, corpo, mittente = _promotion_of(promotion_emails, "promo-desk-wait@example.com")
    assert f"event.html?id={tid}" in corpo
    assert "al banco" in corpo and f"{WAITLIST_PAY_HOURS} ore" not in corpo
    assert mittente == "general"


def test_nothing_to_drop_when_free_or_started(client):
    org = _register_user(client, "unpaid-org2@example.com", role="organizer")
    free = _tournament(client, org, fee=0)
    assert client.post(f"/api/tournaments/{free}/drop-unpaid", headers=org).status_code == 409

    paid_event = _tournament(client, org, capacity=8)
    for i in range(2):
        _enroll(client, org, paid_event, f"unpaid-s{i}@example.com", pay=True)
    assert client.post(f"/api/tournaments/{paid_event}/start", headers=org).status_code == 200
    assert client.post(f"/api/tournaments/{paid_event}/drop-unpaid", headers=org).status_code == 409


def test_prizes_are_recorded_and_can_be_undone(client):
    org = _register_user(client, "prize-org@example.com", role="organizer")
    tid = _tournament(client, org)
    reg = _enroll(client, org, tid, "prize-winner@example.com", pay=True)
    url = f"/api/tournaments/{tid}/registrations/{reg['id']}/prize"

    given = client.put(url, headers=org, json={"given": True, "note": "3 buste"}).json()
    assert given["prize_note"] == "3 buste" and given["prize_given_at"]
    undone = client.put(url, headers=org, json={"given": False}).json()
    assert undone["prize_note"] == "" and undone["prize_given_at"] is None

    actions = [(a["action"], a["detail"]) for a in client.get(f"/api/tournaments/{tid}/audit", headers=org).json()]
    assert ("prize_given", "prize-winner: 3 buste") in actions
    assert ("prize_revoked", "prize-winner: 3 buste") in actions


def test_only_the_organizer_hands_out_prizes(client):
    org = _register_user(client, "prize-org2@example.com", role="organizer")
    tid = _tournament(client, org)
    reg = _enroll(client, org, tid, "prize-p2@example.com")
    other = _register_user(client, "prize-other@example.com", role="organizer")
    assert client.put(f"/api/tournaments/{tid}/registrations/{reg['id']}/prize", headers=other,
                      json={"given": True}).status_code == 404
