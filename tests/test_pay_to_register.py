"""
test_pay_to_register.py — Chi non paga e non sceglie il banco non è iscritto.

Il 23/11/2026, sullo staging: scegliendo Stripe o PayPal nel modulo d'iscrizione
si diventava iscritti subito, e il pagamento restava da fare da un'altra
pagina. Ora al banco si è iscritti subito; online il posto è tenuto mezz'ora e
l'iscrizione vale quando il pagamento arriva, altrimenti sparisce.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import stripe
from fastapi import HTTPException

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.models import DiscountCode, Registration
from backend.app.services.registrations import release_unpaid_holds


def _utente(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _torneo(client, org, **extra):
    corpo = {
        "name": "Modern del martedì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=4)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "pay_stripe": True, "pay_paypal": True, "decklist_required": False,
    }
    corpo.update(extra)
    creato = client.post("/api/tournaments", headers=org, json=corpo)
    assert creato.status_code == 201, creato.text
    return creato.json()["id"]


def _iscrivi(client, tid, player, **corpo):
    return client.post(f"/api/tournaments/{tid}/registrations", headers=player, json=corpo)


def _mia(client, tid, player):
    return client.get(f"/api/tournaments/{tid}/my-registration", headers=player)


def _scaduta(db_session, tid, player_email):
    """Porta indietro l'orologio di un posto tenuto, come se fosse passata un'ora."""
    db_session.expire_all()
    reg = next(r for r in db_session.query(Registration).filter_by(tournament_id=tid) if r.player.email == player_email)
    reg.payment_due_by = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()


def test_paying_at_the_desk_registers_right_away(client):
    org = _utente(client, "banco-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "banco-a@example.com")

    iscritto = _iscrivi(client, tid, player, payment_method="at_event")

    assert iscritto.status_code == 201, iscritto.text
    assert (iscritto.json()["checkout_url"], iscritto.json()["payment_due_by"]) == ("", None)
    assert _mia(client, tid, player).status_code == 200


def test_choosing_online_sends_to_pay_and_registers_when_paid(client):
    org = _utente(client, "online-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "online-a@example.com")

    iscritto = _iscrivi(client, tid, player, payment_method="stripe")

    assert iscritto.status_code == 201, iscritto.text
    assert "sandbox-checkout.html" in iscritto.json()["checkout_url"]
    assert iscritto.json()["payment_due_by"] is not None, "non è iscritto: ha solo il posto tenuto"

    pid = parse_qs(urlparse(iscritto.json()["checkout_url"]).query)["payment_id"][0]
    assert client.post(f"/api/payments/sandbox/{pid}/complete").status_code == 200

    mia = _mia(client, tid, player).json()
    assert (mia["payment_status"], mia["payment_due_by"]) == ("paid", None)


def test_an_unpaid_seat_is_released_after_the_deadline(client, db_session):
    org = _utente(client, "scade-org@example.com", role="organizer")
    tid = _torneo(client, org)
    created = client.post(f"/api/tournaments/{tid}/discount-codes", headers=org,
                          json={"code": "amici", "percent_off": 20, "max_uses": 1})
    assert created.status_code == 201, created.text
    player = _utente(client, "scade-a@example.com")
    assert _iscrivi(client, tid, player, payment_method="paypal", discount_code="amici").status_code == 201

    # Ancora nel suo tempo: resta.
    assert release_unpaid_holds(db_session) == 0
    _scaduta(db_session, tid, "scade-a@example.com")
    assert release_unpaid_holds(db_session) == 1

    assert _mia(client, tid, player).status_code == 404
    db_session.expire_all()
    assert db_session.query(DiscountCode).filter_by(tournament_id=tid).one().uses == 0, \
        "il codice usato da chi non ha pagato torna disponibile"
    # E può riprovare: un'iscrizione solo ritirata gli direbbe "Sei già iscritto".
    assert _iscrivi(client, tid, player, payment_method="at_event", discount_code="amici").status_code == 201


def test_a_paid_seat_is_never_released(client, db_session):
    org = _utente(client, "pagato-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "pagato-a@example.com")
    url = _iscrivi(client, tid, player, payment_method="stripe").json()["checkout_url"]
    pid = parse_qs(urlparse(url).query)["payment_id"][0]
    client.post(f"/api/payments/sandbox/{pid}/complete")
    _scaduta(db_session, tid, "pagato-a@example.com")

    assert release_unpaid_holds(db_session) == 0
    assert _mia(client, tid, player).json()["payment_status"] == "paid"


def test_cancelling_the_payment_frees_the_seat_at_once(client):
    org = _utente(client, "annulla-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "annulla-a@example.com")
    _iscrivi(client, tid, player, payment_method="paypal")

    tolto = client.post(f"/api/tournaments/{tid}/my-registration/abandon-payment", headers=player)

    assert tolto.json() == {"released": True}
    assert _mia(client, tid, player).status_code == 404
    assert _iscrivi(client, tid, player, payment_method="at_event").status_code == 201


def test_cancelling_does_not_touch_who_pays_at_the_desk(client):
    org = _utente(client, "resta-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "resta-a@example.com")
    _iscrivi(client, tid, player, payment_method="at_event")

    tolto = client.post(f"/api/tournaments/{tid}/my-registration/abandon-payment", headers=player)

    assert tolto.json() == {"released": False}
    assert _mia(client, tid, player).status_code == 200


def test_cancelling_an_unpaid_registration_lets_you_register_again(client):
    """"Annulla iscrizione" su un posto non ancora pagato: prima lo ritirava, e
    ritirato non ci si poteva più iscrivere."""
    org = _utente(client, "ritira-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "ritira-a@example.com")
    _iscrivi(client, tid, player, payment_method="stripe")

    assert client.post(f"/api/tournaments/{tid}/my-registration/cancel", headers=player).status_code == 200
    assert _iscrivi(client, tid, player, payment_method="at_event").status_code == 201


def test_an_online_only_tournament_needs_an_online_payment(client):
    org = _utente(client, "solo-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_at_event=False)
    player = _utente(client, "solo-a@example.com")

    assert _iscrivi(client, tid, player).status_code == 422
    assert _iscrivi(client, tid, player, payment_method="at_event").status_code == 422
    assert _mia(client, tid, player).status_code == 404
    assert _iscrivi(client, tid, player, payment_method="paypal").status_code == 201


def test_where_payments_are_off_online_is_not_a_choice(client, monkeypatch):
    org = _utente(client, "spento-org@example.com", role="organizer")
    tid = _torneo(client, org)
    monkeypatch.setattr(get_settings(), "online_payments_enabled", False)
    player = _utente(client, "spento-a@example.com")

    assert _iscrivi(client, tid, player, payment_method="stripe").status_code == 422
    assert _iscrivi(client, tid, player, payment_method="at_event").status_code == 201


def test_free_tournaments_ask_nothing(client):
    org = _utente(client, "gratis-org@example.com", role="organizer")
    # Solo online e gratis: se ci fosse una quota vorrebbe un pagamento, qui no.
    tid = _torneo(client, org, entry_fee_cents=0, pay_at_event=False, pay_paypal=False)
    player = _utente(client, "gratis-a@example.com")

    iscritto = _iscrivi(client, tid, player)

    assert iscritto.status_code == 201, iscritto.text
    assert iscritto.json()["payment_due_by"] is None


def test_when_paypal_refuses_nobody_is_registered(client, monkeypatch):
    from backend.app.services import payments as servizio

    settings = get_settings()
    monkeypatch.setattr(settings, "paypal_client_id", "id-di-prova")
    monkeypatch.setattr(settings, "paypal_client_secret", "segreto-di-prova")

    async def rifiuta(registration, store=None):
        raise HTTPException(status_code=502, detail="PayPal ha rifiutato l'ordine: PAYEE_ACCOUNT_INVALID")

    monkeypatch.setattr(servizio, "create_paypal_checkout", rifiuta)
    org = _utente(client, "rifiuto-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "rifiuto-a@example.com")

    risposta = _iscrivi(client, tid, player, payment_method="paypal")

    assert risposta.status_code == 502
    assert _mia(client, tid, player).status_code == 404
    assert client.get(f"/api/tournaments/{tid}").json()["registered_players"] == 0


def test_a_held_seat_counts_and_goes_to_the_waitlist_when_released(client, db_session):
    org = _utente(client, "posto-org@example.com", role="organizer")
    tid = _torneo(client, org, capacity=2)
    primo = _utente(client, "posto-a@example.com")
    secondo = _utente(client, "posto-b@example.com")
    _iscrivi(client, tid, _utente(client, "posto-c@example.com"), payment_method="at_event")
    _iscrivi(client, tid, primo, payment_method="paypal")

    # Il posto tenuto conta: chi arriva dopo va in lista d'attesa.
    assert _iscrivi(client, tid, secondo, payment_method="at_event").json()["waitlisted"] is True

    _scaduta(db_session, tid, "posto-a@example.com")
    assert release_unpaid_holds(db_session) == 1
    assert _mia(client, tid, secondo).json()["waitlisted"] is False


@pytest.fixture
def stripe_vero(monkeypatch):
    """Stripe con le chiavi: la sessione si crea (finta) e si può far scadere."""
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_platform")
    chiamate: dict = {"scadute": []}

    def crea(**kwargs):
        chiamate["sessione"] = kwargs
        return SimpleNamespace(id="cs_test_1", url="https://checkout.stripe.test/cs_test_1")

    def scade(session_id):
        if chiamate.get("gia_pagata"):
            raise stripe.InvalidRequestError("Session already completed", None)
        chiamate["scadute"].append(session_id)

    monkeypatch.setattr(stripe.checkout.Session, "create", crea)
    monkeypatch.setattr(stripe.checkout.Session, "expire", scade)
    return chiamate


def test_the_stripe_page_expires_with_the_seat(client, stripe_vero):
    org = _utente(client, "cs-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "cs-a@example.com")

    iscritto = _iscrivi(client, tid, player, payment_method="stripe")

    assert iscritto.json()["checkout_url"] == "https://checkout.stripe.test/cs_test_1"
    scade_fra = stripe_vero["sessione"]["expires_at"] - datetime.now(UTC).timestamp()
    assert 30 * 60 <= scade_fra <= 32 * 60, "Stripe vuole almeno 30 minuti, e non deve durare più del posto"
    assert stripe_vero["sessione"]["cancel_url"].endswith(f"/event.html?id={tid}&pagamento=annullato")

    # Annullato: la pagina Stripe si chiude prima di togliere l'iscrizione.
    client.post(f"/api/tournaments/{tid}/my-registration/abandon-payment", headers=player)
    assert stripe_vero["scadute"] == ["cs_test_1"]
    assert _mia(client, tid, player).status_code == 404


def test_a_stripe_page_already_paid_keeps_the_registration(client, stripe_vero):
    """Se Stripe non chiude la pagina (già pagata) l'iscrizione resta: la
    notifica del pagamento la confermerà, e nessuno paga un posto tolto."""
    org = _utente(client, "cs2-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "cs2-a@example.com")
    _iscrivi(client, tid, player, payment_method="stripe")
    stripe_vero["gia_pagata"] = True

    tolto = client.post(f"/api/tournaments/{tid}/my-registration/abandon-payment", headers=player)

    assert tolto.json() == {"released": False}
    assert _mia(client, tid, player).status_code == 200
