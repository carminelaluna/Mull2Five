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
    owner, slug = _store(client, "pay-owner2@example.com", "Tana del Drago")
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


@pytest.fixture
def paypal(monkeypatch):
    """Un finto PayPal: dice se la firma è buona e registra gli incassi."""
    from backend.app.routers import payments as router_pagamenti
    from backend.app.routers import tournaments as router_tornei
    from backend.app.services.payments import CheckoutSession

    settings = get_settings()
    monkeypatch.setattr(settings, "paypal_client_id", "id-di-prova")
    monkeypatch.setattr(settings, "paypal_client_secret", "segreto-di-prova")
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-PROVA")
    stato = {"firma_valida": True, "incassi": [], "ricevute": 0}

    async def checkout(registration, store=None):
        return CheckoutSession(provider_checkout_id="ORDINE-1", checkout_url="https://paypal.test/approva")

    async def verifica(headers, event):
        return stato["firma_valida"]

    async def incassa(order_id):
        stato["incassi"].append(order_id)
        return "INCASSO-1"

    monkeypatch.setattr(router_tornei, "create_paypal_checkout", checkout)
    monkeypatch.setattr(router_pagamenti, "paypal_webhook_is_authentic", verifica)
    monkeypatch.setattr(router_pagamenti, "capture_paypal_order", incassa)
    monkeypatch.setattr(router_pagamenti, "notify_payment_confirmed",
                        lambda *a, **k: stato.__setitem__("ricevute", stato["ricevute"] + 1))
    return stato


def _iscritto_con_ordine_paypal(client, email="pp-player@example.com"):
    """Un giocatore iscritto con un ordine PayPal in attesa."""
    owner, _ = _store(client, f"owner-{email}", "Tana del Drago")
    tid = _tournament(client, owner)
    player = _register_user(client, email)
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})
    pagamento = client.post(f"/api/tournaments/{tid}/checkout", headers=player,
                            json={"provider": "paypal"})
    assert pagamento.status_code in (200, 201), pagamento.text
    return owner, tid, pagamento.json()["id"]


APPROVATO = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORDINE-1"}}
INCASSATO = {
    "event_type": "PAYMENT.CAPTURE.COMPLETED",
    "resource": {"id": "INCASSO-1",
                 "supplementary_data": {"related_ids": {"order_id": "ORDINE-1"}}},
}


def _pagamento(db_session, pid):
    """La riga vera, riletta dal database: è lo stato persistito che conta."""
    from backend.app.models import Payment
    db_session.expire_all()
    return db_session.get(Payment, pid)


def test_a_forged_paypal_notification_pays_for_nobody(client, paypal, db_session):
    """L'endpoint è pubblico: senza verifica, chiunque dichiarava pagata
    l'iscrizione di chiunque. È la voce 4 del TODO."""
    owner, tid, pid = _iscritto_con_ordine_paypal(client, "pp-falso@example.com")
    paypal["firma_valida"] = False

    risposta = client.post("/api/payments/paypal/webhook", json=INCASSATO)

    assert risposta.status_code == 400
    assert _pagamento(db_session, pid).status != "paid"
    assert paypal["ricevute"] == 0


def test_without_a_webhook_id_paypal_notifications_are_refused(client, paypal, monkeypatch):
    """Senza l'identificativo non c'è niente contro cui verificare la firma:
    meglio rifiutare che fidarsi."""
    monkeypatch.setattr(get_settings(), "paypal_webhook_id", None)
    assert client.post("/api/payments/paypal/webhook", json=INCASSATO).status_code == 503


def test_an_approved_order_is_captured_and_not_yet_paid(client, paypal, db_session):
    """Approvato vuol dire che il compratore ha detto sì, non che i soldi sono
    arrivati: l'ordine ha `intent: CAPTURE` e va incassato. Prima nessuno lo
    faceva, e il negozio non vedeva un euro."""
    owner, tid, pid = _iscritto_con_ordine_paypal(client, "pp-approva@example.com")

    assert client.post("/api/payments/paypal/webhook", json=APPROVATO).status_code == 200

    assert paypal["incassi"] == ["ORDINE-1"]
    assert _pagamento(db_session, pid).status != "paid"
    assert paypal["ricevute"] == 0


def test_the_capture_is_what_marks_it_paid_and_can_be_refunded(client, paypal, db_session):
    owner, tid, pid = _iscritto_con_ordine_paypal(client, "pp-incassa@example.com")

    assert client.post("/api/payments/paypal/webhook", json=INCASSATO).status_code == 200

    riga = _pagamento(db_session, pid)
    assert riga.status == "paid"
    assert paypal["ricevute"] == 1
    # L'identificativo dell'incasso, non quello dell'ordine: l'ordine non si rimborsa.
    assert riga.provider_payment_id == "INCASSO-1"


def test_the_same_notification_twice_sends_one_receipt(client, paypal, db_session):
    """PayPal può ripetere una notifica: due ricevute per un pagamento solo
    sarebbero un errore visibile al giocatore."""
    owner, tid, pid = _iscritto_con_ordine_paypal(client, "pp-doppio@example.com")

    client.post("/api/payments/paypal/webhook", json=INCASSATO)
    client.post("/api/payments/paypal/webhook", json=INCASSATO)

    assert _pagamento(db_session, pid).status == "paid"
    assert paypal["ricevute"] == 1
