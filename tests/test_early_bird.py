"""
test_early_bird.py — La quota di chi si iscrive presto.

Due prezzi sullo stesso torneo sono un invito a sbagliare: quello che la pagina
mostra e quello che il banco incassa devono venire dallo stesso conto
(`entry_fee_now`), e lo sconto non deve poter essere più caro della quota piena.
"""
from datetime import timedelta

from sqlalchemy import select

from backend.app.core.clock import local_today
from backend.app.models import Payment, Registration


def _register_user(client, email, role="organizer"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _crea(client, org, **extra):
    corpo = {
        "name": "RCQ Modern", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=10)), "start_time": "10:00",
        "capacity": 32, "entry_fee_cents": 2500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    corpo.update(extra)
    return client.post("/api/tournaments", headers=org, json=corpo)


def test_who_pays_during_the_early_bird_pays_less_and_the_desk_charges_that(client, db_session):
    """Conta il giorno in cui si paga, non quello dell'iscrizione: regola
    confermata il 24/11/2026 (tests/test_terms_promises.py)."""
    org = _register_user(client, "early-org@example.com")
    creato = _crea(client, org, early_bird_cents=1500,
                   early_bird_until=str(local_today() + timedelta(days=3)))
    assert creato.status_code == 201, creato.text
    tid = creato.json()["id"]
    assert creato.json()["entry_fee_now_cents"] == 1500

    # La pagina pubblica dice la stessa cifra.
    pubblico = client.get(f"/api/tournaments/{tid}").json()
    assert pubblico["entry_fee_now_cents"] == 1500
    assert pubblico["entry_fee_cents"] == 2500

    # E al banco si incassa quella, non la piena.
    walkin = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "early-player@example.com", "display_name": "Chi arriva presto", "mark_paid": True,
    })
    assert walkin.status_code == 201, walkin.text
    importi = db_session.scalars(
        select(Payment.amount_cents)
        .join(Registration, Registration.id == Payment.registration_id)
        .where(Registration.tournament_id == tid)
    ).all()
    assert list(importi) == [1500]


def test_when_the_early_bird_is_over_the_full_price_is_back(client):
    org = _register_user(client, "early-org2@example.com")
    creato = _crea(client, org, early_bird_cents=1500,
                   early_bird_until=str(local_today() - timedelta(days=1)))
    assert creato.status_code == 201, creato.text
    assert creato.json()["entry_fee_now_cents"] == 2500

    # L'ultimo giorno è compreso: chi si iscrive oggi paga ancora lo sconto.
    oggi = _crea(client, org, name="Oggi", early_bird_cents=1500,
                 early_bird_until=str(local_today()))
    assert oggi.json()["entry_fee_now_cents"] == 1500


def test_a_discount_that_does_not_discount_is_refused(client):
    org = _register_user(client, "early-org3@example.com")
    piu_caro = _crea(client, org, early_bird_cents=2500,
                     early_bird_until=str(local_today() + timedelta(days=2)))
    assert piu_caro.status_code == 422, piu_caro.text

    meta = _crea(client, org, early_bird_cents=1500)
    assert meta.status_code == 422, "la quota ridotta senza scadenza non dice quando vale"

    dopo = _crea(client, org, early_bird_cents=1500,
                 early_bird_until=str(local_today() + timedelta(days=30)))
    assert dopo.status_code == 422, "non può scadere dopo il torneo"


def test_the_early_bird_can_be_taken_away(client):
    org = _register_user(client, "early-org4@example.com")
    tid = _crea(client, org, early_bird_cents=1500,
                early_bird_until=str(local_today() + timedelta(days=3))).json()["id"]

    tolto = client.patch(f"/api/tournaments/{tid}", headers=org, json={"early_bird_cents": 0})
    assert tolto.status_code == 200, tolto.text
    dopo = client.get(f"/api/tournaments/{tid}").json()
    assert dopo["early_bird_cents"] is None
    assert dopo["early_bird_until"] is None
    assert dopo["entry_fee_now_cents"] == 2500
