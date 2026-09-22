"""
test_store_payments.py — Gli incassi online vanno al negozio.

Stripe Connect: il negozio collega il suo account (Express) e i pagamenti con
carta diventano destination charge verso di lui, con la quota della
piattaforma se c'è. PayPal: l'email PayPal del negozio è il beneficiario
dell'ordine. Stripe qui è finto: nessuna chiamata esce dal test.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import stripe

from backend.app.core.config import get_settings
from backend.app.models import Organization, Registration


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _store(client, email="pay-owner@example.com", name="Carte e Draghi"):
    owner = _register_user(client, email, role="organizer")
    slug = client.post("/api/organizations/mine", headers=owner, json={"name": name, "city": "Pavia"}).json()["slug"]
    return owner, slug


def _tournament(client, owner, **extra):
    body = {
        "name": "Modern del venerdì", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=6)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 2000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "pay_stripe": True, "pay_paypal": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=owner, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest.fixture
def fake_stripe(monkeypatch):
    """Un finto Stripe: registra le chiamate e risponde come l'API vera."""
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_platform")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    calls: dict = {"charges_enabled": True}

    def account_create(**kwargs):
        calls["account"] = kwargs
        return SimpleNamespace(id="acct_store1")

    def account_link_create(**kwargs):
        calls["link"] = kwargs
        return SimpleNamespace(url="https://connect.stripe.test/onboarding")

    def session_create(**kwargs):
        calls["session"] = kwargs
        return SimpleNamespace(id="cs_1", url="https://checkout.stripe.test/cs_1")

    def refund_create(**kwargs):
        calls["refund"] = kwargs
        return SimpleNamespace(id="re_1")

    monkeypatch.setattr(stripe.Account, "create", account_create)
    monkeypatch.setattr(stripe.AccountLink, "create", account_link_create)
    monkeypatch.setattr(stripe.Account, "retrieve",
                        lambda account_id: SimpleNamespace(id=account_id, charges_enabled=calls["charges_enabled"]))
    monkeypatch.setattr(stripe.Account, "create_login_link",
                        lambda account_id: SimpleNamespace(url=f"https://dashboard.stripe.test/{account_id}"))
    monkeypatch.setattr(stripe.checkout.Session, "create", session_create)
    monkeypatch.setattr(stripe.Refund, "create", refund_create)
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda payload, signature, secret: calls["event"])
    return calls


def _connect(client, owner, slug):
    assert client.post(f"/api/organizations/{slug}/stripe/connect", headers=owner).status_code == 200
    return client.post(f"/api/organizations/{slug}/stripe/refresh", headers=owner).json()


def test_the_owner_connects_the_store_stripe_account(client, fake_stripe):
    owner, slug = _store(client)
    status = client.get(f"/api/organizations/{slug}/payments", headers=owner).json()
    assert (status["stripe_available"], status["stripe_status"]) == (True, "none")

    link = client.post(f"/api/organizations/{slug}/stripe/connect", headers=owner).json()
    assert link["url"] == "https://connect.stripe.test/onboarding"
    assert fake_stripe["account"]["type"] == "express"
    assert fake_stripe["link"]["account"] == "acct_store1"
    assert client.get(f"/api/organizations/{slug}/payments", headers=owner).json()["stripe_status"] == "pending"

    assert client.post(f"/api/organizations/{slug}/stripe/refresh", headers=owner).json()["stripe_status"] == "active"
    dashboard = client.post(f"/api/organizations/{slug}/stripe/dashboard", headers=owner).json()
    assert dashboard["url"].endswith("/acct_store1")

    # Stripe avvisa se l'account non può più incassare.
    fake_stripe["event"] = {"type": "account.updated", "data": {"object": {"id": "acct_store1", "charges_enabled": False}}}
    client.post("/api/payments/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})
    assert client.get(f"/api/organizations/{slug}/payments", headers=owner).json()["stripe_status"] == "pending"

    staff = _register_user(client, "pay-staff@example.com", role="organizer")
    client.post(f"/api/organizations/{slug}/members", headers=owner, json={"email": "pay-staff@example.com", "role": "organizer"})
    assert client.post(f"/api/organizations/{slug}/stripe/connect", headers=staff).status_code == 403


def test_card_payments_go_to_the_store_and_refunds_reverse_the_transfer(client, fake_stripe, monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_fee_percent", 5.0)
    owner, slug = _store(client, "pay-owner2@example.com", "Arcana")
    assert _connect(client, owner, slug)["stripe_status"] == "active"
    tid = _tournament(client, owner)

    player = _register_user(client, "pay-player@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})
    payment = client.post(f"/api/tournaments/{tid}/checkout", headers=player, json={"provider": "stripe"}).json()
    assert payment["checkout_url"] == "https://checkout.stripe.test/cs_1"
    assert fake_stripe["session"]["payment_intent_data"] == {
        "transfer_data": {"destination": "acct_store1"}, "application_fee_amount": 100,   # il 5% di 20 €
    }

    fake_stripe["event"] = {"type": "checkout.session.completed", "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}}}
    client.post("/api/payments/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})
    refunded = client.post(f"/api/tournaments/{tid}/payments/{payment['id']}/refund", headers=owner, json={"approve": True})
    assert refunded.status_code == 200 and refunded.json()["status"] == "refunded"
    assert fake_stripe["refund"] == {"payment_intent": "pi_1", "reverse_transfer": True, "refund_application_fee": True}


def test_without_a_connected_account_the_platform_collects_and_warns(client, fake_stripe):
    owner, slug = _store(client, "pay-owner3@example.com", "Dadi e Mana")
    tid = _tournament(client, owner)
    warnings = {w["code"] for w in client.get(f"/api/tournaments/{tid}/warnings", headers=owner).json()}
    assert "store_stripe_not_connected" in warnings

    player = _register_user(client, "pay-player3@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})
    client.post(f"/api/tournaments/{tid}/checkout", headers=player, json={"provider": "stripe"})
    assert "payment_intent_data" not in fake_stripe["session"]


def test_paypal_orders_pay_the_store_account(client, db_session):
    from backend.app.services.payments import paypal_order_body

    owner, slug = _store(client, "pay-owner4@example.com", "Mana Store")
    saved = client.put(f"/api/organizations/{slug}/paypal", headers=owner, json={"paypal_email": "cassa@negozio.it"})
    assert saved.status_code == 200 and saved.json()["paypal_email"] == "cassa@negozio.it"
    tid = _tournament(client, owner)
    player = _register_user(client, "pay-player4@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})

    registration = db_session.query(Registration).filter_by(tournament_id=tid).one()
    store = db_session.query(Organization).filter_by(slug=slug).one()
    unit = paypal_order_body(registration, store)["purchase_units"][0]
    assert unit["payee"] == {"email_address": "cassa@negozio.it"}
    assert unit["amount"] == {"currency_code": "EUR", "value": "20.00"}
    assert "payee" not in paypal_order_body(registration, None)["purchase_units"][0]
