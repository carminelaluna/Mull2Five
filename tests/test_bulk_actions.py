"""
test_bulk_actions.py — Check-in e rimozione in blocco dalla scheda Giocatori.

Al banco la fila non aspetta un clic per volta. Ma chi ha pagato non si toglie
dal torneo con una spunta: prima lo si rimborsa.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today


def _user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role})
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def torneo(client):
    org = _user(client, "bulk-org@example.com", role="organizer")
    tid = client.post("/api/tournaments", headers=org, json={
        "name": "Serata", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "check_in_required": True}).json()["id"]
    iscritti = []
    for i in range(3):
        reg = client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                          json={"display_name": f"Giocatore {i}", "mark_paid": i == 0}).json()
        iscritti.append(reg["id"])
    return {"org": org, "tid": tid, "iscritti": iscritti}


def test_check_in_of_everyone_selected(client, torneo):
    esito = client.post(f"/api/tournaments/{torneo['tid']}/registrations/bulk-check-in",
                        headers=torneo["org"], json={"registration_ids": torneo["iscritti"]})
    assert esito.status_code == 200, esito.text
    assert esito.json() == {"done": 3, "skipped": []}

    lista = client.get(f"/api/tournaments/{torneo['tid']}/registrations", headers=torneo["org"]).json()
    assert all(r["checked_in"] for r in lista)

    # Ripeterlo non è un errore: chi c'è già non viene ricontato.
    di_nuovo = client.post(f"/api/tournaments/{torneo['tid']}/registrations/bulk-check-in",
                           headers=torneo["org"], json={"registration_ids": torneo["iscritti"]})
    assert di_nuovo.json()["done"] == 0


def test_whoever_paid_is_not_dropped_by_a_tick(client, torneo):
    esito = client.post(f"/api/tournaments/{torneo['tid']}/registrations/bulk-drop",
                        headers=torneo["org"], json={"registration_ids": torneo["iscritti"]})
    assert esito.status_code == 200, esito.text
    corpo = esito.json()
    assert corpo["done"] == 2                       # i due che non avevano pagato
    assert [s for s in corpo["skipped"] if "ha pagato" in s]

    lista = client.get(f"/api/tournaments/{torneo['tid']}/registrations", headers=torneo["org"]).json()
    ritirati = {r["id"] for r in lista if r["dropped"]}
    assert ritirati == set(torneo["iscritti"][1:])


def test_a_judge_checks_in_but_does_not_drop(client, torneo):
    judge = _user(client, "bulk-judge@example.com")
    client.post(f"/api/tournaments/{torneo['tid']}/staff", headers=torneo["org"],
                json={"email": "bulk-judge@example.com", "role": "judge"})

    assert client.post(f"/api/tournaments/{torneo['tid']}/registrations/bulk-check-in",
                       headers=judge, json={"registration_ids": torneo["iscritti"]}).status_code == 200
    assert client.post(f"/api/tournaments/{torneo['tid']}/registrations/bulk-drop",
                       headers=judge, json={"registration_ids": torneo["iscritti"]}).status_code in (403, 404)
