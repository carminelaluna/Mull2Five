"""
test_my_registrations.py — "Le mie iscrizioni" in una richiesta sola.

Prima la pagina chiedeva tutti i tornei e poi, per ognuno, la propria
iscrizione: centinaia di richieste, e oltre il limite per IP la pagina si
rompeva. Ora /tournaments/me/registrations restituisce iscrizione e torneo
insieme, solo per chi chiede.
"""
from datetime import date, timedelta


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0], "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, organizer, name, days):
    created = client.post("/api/tournaments", headers=organizer, json={
        "name": name, "format": "Modern", "starts_on": str(date.today() + timedelta(days=days)),
        "start_time": "20:00", "capacity": 16, "entry_fee_cents": 500, "status": "published",
        "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_one_request_returns_my_registrations_with_their_tournaments(client):
    organizer = _register_user(client, "mr-owner@example.com", role="organizer")
    first = _tournament(client, organizer, "Modern del venerdì", 5)
    second = _tournament(client, organizer, "Commander della domenica", 9)
    _tournament(client, organizer, "Torneo a cui non sono iscritto", 12)

    player = _register_user(client, "mr-player@example.com")
    for tid in (first, second):
        assert client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).status_code == 201

    rows = client.get("/api/tournaments/me/registrations", headers=player)
    assert rows.status_code == 200, rows.text
    data = rows.json()
    assert [row["tournament"]["name"] for row in data] == ["Commander della domenica", "Modern del venerdì"]
    assert {row["tournament"]["id"] for row in data} == {first, second}
    assert all(row["registration"]["tournament_id"] == row["tournament"]["id"] for row in data)
    assert data[0]["registration"]["payment_status"] == "pending"
    assert data[0]["tournament"]["registered_players"] == 1

    # Ognuno vede solo le proprie.
    other = _register_user(client, "mr-other@example.com")
    assert client.get("/api/tournaments/me/registrations", headers=other).json() == []
    assert client.get("/api/tournaments/me/registrations").status_code == 401
