"""
test_tickets.py — Le segnalazioni, e chi può leggerle.

Due livelli: quella su un torneo la legge chi lo organizza, quella sul sito la
leggono gli admin. Nessuno dei due deve vedere quelle dell'altro.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today


def _user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role})
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def scena(client):
    org = _user(client, "tk-org@example.com", role="organizer")
    altro = _user(client, "tk-altro@example.com", role="organizer")
    player = _user(client, "tk-player@example.com")
    tid = client.post("/api/tournaments", headers=org, json={
        "name": "Serata", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False}).json()["id"]
    return {"org": org, "altro": altro, "player": player, "tid": tid}


def test_the_organizer_reads_what_is_addressed_to_the_tournament(client, scena):
    aperta = client.post("/api/tickets", headers=scena["player"], json={
        "scope": "organizer", "tournament_id": scena["tid"],
        "subject": "Risultato sbagliato", "body": "Il mio 2-1 risulta 1-2."})
    assert aperta.status_code == 201, aperta.text
    ticket = aperta.json()
    assert ticket["status"] == "open" and len(ticket["messages"]) == 1

    assert [t["id"] for t in client.get("/api/tickets/inbox", headers=scena["org"]).json()] == [ticket["id"]]
    # Un altro organizzatore non c'entra niente.
    assert client.get("/api/tickets/inbox", headers=scena["altro"]).json() == []
    assert client.get(f"/api/tickets/{ticket['id']}", headers=scena["altro"]).status_code == 404


def test_a_reply_puts_the_ticket_back_to_the_player(client, scena):
    ticket = client.post("/api/tickets", headers=scena["player"], json={
        "scope": "organizer", "tournament_id": scena["tid"],
        "subject": "Pagamento", "body": "Ho pagato al banco."}).json()

    risposta = client.post(f"/api/tickets/{ticket['id']}/messages", headers=scena["org"],
                           json={"body": "Segnato, grazie."})
    assert risposta.status_code == 200
    assert risposta.json()["status"] == "answered"
    assert len(risposta.json()["messages"]) == 2

    di_nuovo = client.post(f"/api/tickets/{ticket['id']}/messages", headers=scena["player"],
                           json={"body": "Perfetto."})
    assert di_nuovo.json()["status"] == "open"

    chiusa = client.post(f"/api/tickets/{ticket['id']}/close", headers=scena["org"]).json()
    assert chiusa["status"] == "closed"
    assert client.post(f"/api/tickets/{ticket['id']}/messages", headers=scena["player"],
                       json={"body": "Ancora?"}).status_code == 409


def test_a_site_ticket_never_reaches_an_organizer(client, scena):
    ticket = client.post("/api/tickets", headers=scena["player"], json={
        "scope": "admin", "subject": "Non riesco a entrare", "body": "La password non va."})
    assert ticket.status_code == 201, ticket.text

    assert client.get("/api/tickets/inbox", headers=scena["org"]).json() == []
    assert client.get(f"/api/tickets/{ticket.json()['id']}", headers=scena["org"]).status_code == 404
    # Chi l'ha aperta la ritrova sempre.
    assert [t["id"] for t in client.get("/api/tickets/mine", headers=scena["player"]).json()] \
        == [ticket.json()["id"]]


def test_an_organizer_ticket_needs_a_tournament(client, scena):
    rifiutata = client.post("/api/tickets", headers=scena["player"], json={
        "scope": "organizer", "subject": "Senza torneo", "body": "A chi lo mando?"})
    assert rifiutata.status_code == 422
