"""
test_scorekeeper.py — Chi tiene il tabellone conferma i referti.

Con uno scorekeeper nello staff un judge non scrive più in classifica:
propone, e il risultato entra quando lo conferma qualcun altro. Dove lo
scorekeeper non c'è, non cambia niente.
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


def _avviato(client, org, prefisso):
    tid = client.post("/api/tournaments", headers=org, json={
        "name": "Serata", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=1)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False}).json()["id"]
    for i in range(2):
        client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                    json={"display_name": f"{prefisso} {i}"})
    turno = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert turno.status_code == 200, turno.text
    return tid, turno.json()["pairings"][0]["id"]


@pytest.fixture
def sala(client):
    org = _user(client, "sk-org@example.com", role="organizer")
    tid, pid = _avviato(client, org, "Sk")
    judge = _user(client, "sk-judge@example.com")
    keeper = _user(client, "sk-keeper@example.com")
    for email, ruolo in (("sk-judge@example.com", "judge"), ("sk-keeper@example.com", "scorekeeper")):
        aggiunto = client.post(f"/api/tournaments/{tid}/staff", headers=org,
                               json={"email": email, "role": ruolo})
        assert aggiunto.status_code == 201, aggiunto.text
    return {"org": org, "judge": judge, "keeper": keeper, "tid": tid, "pid": pid}


def test_a_judge_proposes_and_the_scorekeeper_confirms(client, sala):
    proposto = client.patch(f"/api/tournaments/{sala['tid']}/pairings/{sala['pid']}/result",
                            headers=sala["judge"], json={"match_wins_a": 2, "match_wins_b": 0})
    assert proposto.status_code == 200, proposto.text
    riga = proposto.json()["pairings"][0]
    assert riga["result"] in ("", None)          # non è ancora in classifica
    assert riga["report_status"] == "pending"

    confermato = client.post(f"/api/tournaments/{sala['tid']}/pairings/{sala['pid']}/confirm-report",
                             headers=sala["keeper"])
    assert confermato.status_code == 200, confermato.text
    assert confermato.json()["pairings"][0]["result"] == "A"


def test_the_one_who_proposed_cannot_confirm_it(client, sala):
    client.patch(f"/api/tournaments/{sala['tid']}/pairings/{sala['pid']}/result",
                 headers=sala["judge"], json={"match_wins_a": 2, "match_wins_b": 0})
    assert client.post(f"/api/tournaments/{sala['tid']}/pairings/{sala['pid']}/confirm-report",
                       headers=sala["judge"]).status_code in (403, 409)


def test_the_organizer_still_writes_straight_in(client, sala):
    scritto = client.patch(f"/api/tournaments/{sala['tid']}/pairings/{sala['pid']}/result",
                           headers=sala["org"], json={"match_wins_a": 0, "match_wins_b": 2})
    assert scritto.json()["pairings"][0]["result"] == "B"


def test_without_a_scorekeeper_a_judge_writes_as_before(client):
    org = _user(client, "sk2-org@example.com", role="organizer")
    tid, pid = _avviato(client, org, "Solo")
    judge = _user(client, "sk2-judge@example.com")
    client.post(f"/api/tournaments/{tid}/staff", headers=org,
                json={"email": "sk2-judge@example.com", "role": "judge"})

    scritto = client.patch(f"/api/tournaments/{tid}/pairings/{pid}/result",
                           headers=judge, json={"match_wins_a": 2, "match_wins_b": 0})
    assert scritto.json()["pairings"][0]["result"] == "A"
