"""
test_api_smoke.py — Smoke test dell'API: endpoint principali su DB pulito.

Usa le fixture di conftest.py (SQLite isolato + TestClient).
"""


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["cache"] in {"redis", "memory"}


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Manabind" in response.json()["message"]


def test_list_tournaments_empty(client):
    response = client.get("/api/tournaments")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_register_and_login(client):
    payload = {
        "email": "smoke@example.com",
        "display_name": "Smoke Tester",
        "password": "supersecret123",
        "role": "organizer",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code in (200, 201), response.text

    response = client.post(
        "/api/auth/login",
        json={"email": "smoke@example.com", "password": "supersecret123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert token

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "smoke@example.com"


def test_login_wrong_password(client):
    client.post(
        "/api/auth/register",
        json={
            "email": "wrongpw@example.com",
            "display_name": "Wrong PW",
            "password": "correctpassword1",
        },
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "wrongpw@example.com", "password": "wrongpassword999"},
    )
    assert response.status_code == 401


def test_tournament_crud(client):
    # Registra organizzatore
    client.post(
        "/api/auth/register",
        json={
            "email": "org-crud@example.com",
            "display_name": "Org CRUD",
            "password": "supersecret123",
            "role": "organizer",
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "org-crud@example.com", "password": "supersecret123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Crea torneo
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Smoke Test Open",
            "format": "Modern",
            "starts_on": "2027-01-15",
            "capacity": 32,
            "entry_fee_cents": 1500,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    tournament_id = response.json()["id"]

    # Leggi torneo
    response = client.get(f"/api/tournaments/{tournament_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Smoke Test Open"

    # Elimina torneo
    response = client.delete(f"/api/tournaments/{tournament_id}", headers=headers)
    assert response.status_code == 204

    response = client.get(f"/api/tournaments/{tournament_id}")
    assert response.status_code == 404
