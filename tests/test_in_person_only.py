"""
test_in_person_only.py — Un sito dove si paga solo al banco.

La produzione apre in una fumetteria prima che i pagamenti online passino dal
legale: con ONLINE_PAYMENTS_ENABLED spento Stripe e PayPal non si salvano, non
si mostrano e il checkout li rifiuta. Lo staging li tiene accesi per provarli.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, **payments):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern del giovedì", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "decklist_required": False, **payments,
    })
    assert created.status_code == 201, created.text
    return created.json()


@pytest.fixture
def at_the_desk(monkeypatch):
    monkeypatch.setattr(get_settings(), "online_payments_enabled", False)


def test_the_site_says_whether_it_takes_online_payments(client, monkeypatch):
    assert client.get("/api/payments/options").json() == {"online": True}
    monkeypatch.setattr(get_settings(), "online_payments_enabled", False)
    assert client.get("/api/payments/options").json() == {"online": False}


def test_a_tournament_asking_for_card_only_is_paid_at_the_desk(client, db_session, at_the_desk):
    from backend.app.models import Tournament

    org = _register_user(client, "desk-org@example.com", role="organizer")
    created = _tournament(client, org, pay_at_event=False, pay_stripe=True, pay_paypal=True)

    assert (created["pay_at_event"], created["pay_stripe"], created["pay_paypal"]) == (True, False, False)
    saved = db_session.get(Tournament, created["id"])
    assert (saved.pay_at_event, saved.pay_stripe, saved.pay_paypal) == (True, False, False)


def test_editing_cannot_switch_online_payments_back_on(client, at_the_desk):
    org = _register_user(client, "desk-edit@example.com", role="organizer")
    tid = _tournament(client, org)["id"]

    edited = client.patch(f"/api/tournaments/{tid}", headers=org, json={"pay_paypal": True})

    assert edited.status_code == 200, edited.text
    assert edited.json()["pay_paypal"] is False


def test_a_duplicate_of_an_online_tournament_is_paid_at_the_desk(client, monkeypatch):
    org = _register_user(client, "desk-dup@example.com", role="organizer")
    tid = _tournament(client, org, pay_at_event=False, pay_stripe=True)["id"]   # salvato quando c'erano
    monkeypatch.setattr(get_settings(), "online_payments_enabled", False)

    copy = client.post(f"/api/tournaments/{tid}/duplicate", headers=org)

    assert copy.status_code == 201, copy.text
    assert (copy.json()["pay_at_event"], copy.json()["pay_stripe"]) == (True, False)


def test_a_tournament_saved_with_online_payments_no_longer_offers_them(client, monkeypatch):
    """Salvato quando c'erano, poi spenti: le pagine non mostrano il bottone, il
    checkout lo rifiuta, e salvare il modulo (che li manda falsi) non è un errore."""
    org = _register_user(client, "desk-old@example.com", role="organizer")
    tid = _tournament(client, org, pay_stripe=True)["id"]
    player = _register_user(client, "desk-player@example.com")
    assert client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).status_code == 201
    monkeypatch.setattr(get_settings(), "online_payments_enabled", False)

    assert client.get(f"/api/tournaments/{tid}").json()["pay_stripe"] is False
    checkout = client.post(f"/api/tournaments/{tid}/checkout", headers=player, json={"provider": "stripe"})
    assert checkout.status_code == 409
    assert "al banco" in checkout.json()["detail"]
    saved = client.patch(f"/api/tournaments/{tid}", headers=org, json={
        "pay_at_event": True, "pay_stripe": False, "pay_paypal": False})
    assert saved.status_code == 200, saved.text


def test_with_online_payments_on_nothing_changes(client):
    org = _register_user(client, "online-org@example.com", role="organizer")
    created = _tournament(client, org, pay_at_event=False, pay_stripe=True)

    assert (created["pay_at_event"], created["pay_stripe"]) == (False, True)
