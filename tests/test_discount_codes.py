"""
test_discount_codes.py — I codici sconto sulla quota.

Qui si muovono soldi, quindi contano i bordi: un codice sbagliato non deve
lasciar credere a uno sconto, uno esaurito non deve funzionare lo stesso, e chi
si è iscritto con uno sconto deve tenerlo anche quando il negozio ritira il
codice.
"""
from datetime import timedelta

from sqlalchemy import select

from backend.app.core.clock import local_today
from backend.app.models import Payment, Registration


def _utente(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _torneo(client, org, quota=2000):
    creato = client.post("/api/tournaments", headers=org, json={
        "name": "Serata Modern", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=5)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": quota, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert creato.status_code == 201, creato.text
    return creato.json()["id"]


def _codice(client, org, tid, **extra):
    corpo = {"code": "amici20", "percent_off": 20}
    corpo.update(extra)
    return client.post(f"/api/tournaments/{tid}/discount-codes", headers=org, json=corpo)


def _iscrivi(client, tid, email, codice=""):
    player = _utente(client, email)
    return player, client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                               json={"wizards_account": "", "discount_code": codice})


def _incassato(db_session, tid):
    return list(db_session.scalars(
        select(Payment.amount_cents)
        .join(Registration, Registration.id == Payment.registration_id)
        .where(Registration.tournament_id == tid)
    ).all())


def test_the_code_lands_on_what_the_player_actually_pays(client, db_session):
    org = _utente(client, "sconti-org@example.com", role="organizer")
    tid = _torneo(client, org)
    creato = _codice(client, org, tid)
    assert creato.status_code == 201, creato.text
    assert creato.json()["code"] == "AMICI20", "i codici stanno in maiuscolo, o 'Amici20' non entrerebbe"

    _, iscritto = _iscrivi(client, tid, "sconti-a@example.com", "amici20")
    assert iscritto.status_code == 201, iscritto.text
    reg_id = iscritto.json()["id"]
    # L'iscrizione dice quanto deve: la quota del torneo direbbe un'altra cifra,
    # e la pagina che la mostra prometterebbe un prezzo che il banco non fa.
    assert iscritto.json()["amount_due_cents"] == 1600
    assert iscritto.json()["discount_code"] == "AMICI20"

    pagato = client.post(f"/api/tournaments/{tid}/registrations/{reg_id}/mark-paid", headers=org)
    assert pagato.status_code == 200, pagato.text
    assert _incassato(db_session, tid) == [1600]   # 20 euro meno il 20%

    elenco = client.get(f"/api/tournaments/{tid}/discount-codes", headers=org).json()
    assert [(c["code"], c["uses"]) for c in elenco] == [("AMICI20", 1)]


def test_a_fixed_amount_comes_off_too(client, db_session):
    org = _utente(client, "sconti-org2@example.com", role="organizer")
    tid = _torneo(client, org)
    assert _codice(client, org, tid, code="MENO5", percent_off=0, cents_off=500).status_code == 201

    _, iscritto = _iscrivi(client, tid, "sconti-b@example.com", "meno5")
    client.post(f"/api/tournaments/{tid}/registrations/{iscritto.json()['id']}/mark-paid", headers=org)
    assert _incassato(db_session, tid) == [1500]


def test_a_code_that_does_not_hold_up_stops_the_registration(client):
    org = _utente(client, "sconti-org3@example.com", role="organizer")
    tid = _torneo(client, org)
    _codice(client, org, tid, code="SCADUTO", valid_until=str(local_today() - timedelta(days=1)))
    _codice(client, org, tid, code="FINITO", max_uses=1)

    _, inventato = _iscrivi(client, tid, "sconti-c@example.com", "NONESISTE")
    assert inventato.status_code == 422, inventato.text
    _, scaduto = _iscrivi(client, tid, "sconti-d@example.com", "SCADUTO")
    assert scaduto.status_code == 422

    _, primo = _iscrivi(client, tid, "sconti-e@example.com", "FINITO")
    assert primo.status_code == 201
    _, secondo = _iscrivi(client, tid, "sconti-f@example.com", "FINITO")
    assert secondo.status_code == 422, "il secondo non deve passare: era per uno solo"

    # Nessuno dei rifiutati è finito fra gli iscritti.
    iscritti = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
    assert [r["player_email"] for r in iscritti] == ["sconti-e@example.com"]


def test_a_code_belongs_to_its_tournament_and_to_the_staff(client):
    org = _utente(client, "sconti-org4@example.com", role="organizer")
    uno = _torneo(client, org)
    due = _torneo(client, org)
    _codice(client, org, uno, code="SOLOUNO")

    _, altrove = _iscrivi(client, due, "sconti-g@example.com", "SOLOUNO")
    assert altrove.status_code == 422, "un codice di un altro torneo non vale qui"

    curioso = _utente(client, "sconti-curioso@example.com")
    assert client.get(f"/api/tournaments/{uno}/discount-codes", headers=curioso).status_code in (403, 404)


def test_withdrawing_a_used_code_does_not_change_what_was_promised(client, db_session):
    org = _utente(client, "sconti-org5@example.com", role="organizer")
    tid = _torneo(client, org)
    codice = _codice(client, org, tid).json()
    _, iscritto = _iscrivi(client, tid, "sconti-h@example.com", "AMICI20")
    reg_id = iscritto.json()["id"]

    assert client.delete(f"/api/tournaments/{tid}/discount-codes/{codice['id']}",
                         headers=org).status_code == 204
    # Usato: resta, chiuso. Nessuno ne approfitta più…
    rimasti = client.get(f"/api/tournaments/{tid}/discount-codes", headers=org).json()
    assert [(c["code"], c["uses"], c["max_uses"]) for c in rimasti] == [("AMICI20", 1, 1)]
    _, tardi = _iscrivi(client, tid, "sconti-i@example.com", "AMICI20")
    assert tardi.status_code == 422

    # …ma chi si era iscritto paga quello che gli era stato detto.
    client.post(f"/api/tournaments/{tid}/registrations/{reg_id}/mark-paid", headers=org)
    assert _incassato(db_session, tid) == [1600]


def test_an_unused_code_just_goes_away(client):
    org = _utente(client, "sconti-org6@example.com", role="organizer")
    tid = _torneo(client, org)
    codice = _codice(client, org, tid, code="MAIUSATO").json()
    assert client.delete(f"/api/tournaments/{tid}/discount-codes/{codice['id']}",
                         headers=org).status_code == 204
    assert client.get(f"/api/tournaments/{tid}/discount-codes", headers=org).json() == []


def test_a_discount_must_say_what_it_discounts(client):
    org = _utente(client, "sconti-org7@example.com", role="organizer")
    tid = _torneo(client, org)
    assert _codice(client, org, tid, percent_off=20, cents_off=500).status_code == 422
    assert _codice(client, org, tid, percent_off=0, cents_off=0).status_code == 422
    # Due volte lo stesso codice sullo stesso torneo, no.
    assert _codice(client, org, tid, code="UNICO").status_code == 201
    assert _codice(client, org, tid, code="unico").status_code == 409
