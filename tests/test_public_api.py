"""
test_public_api.py — L'API pubblica del negozio, con le sue chiavi.

La chiave la crea il titolare, si vede una volta sola e dà accesso in sola
lettura ai tornei del suo negozio, senza dati personali.
"""
from datetime import date, timedelta


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _store_with_tournament(client, email, store_name):
    owner = _register_user(client, email, role="organizer")
    slug = client.post("/api/organizations/mine", headers=owner, json={"name": store_name, "city": "Pavia"}).json()["slug"]
    tournament = client.post("/api/tournaments", headers=owner, json={
        "name": f"Modern da {store_name}", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }).json()
    return owner, slug, tournament["id"]


def test_the_owner_creates_a_key_that_is_shown_once(client):
    owner, slug, _ = _store_with_tournament(client, "api-owner@example.com", "Carte e Draghi")
    created = client.post(f"/api/organizations/{slug}/api-keys", headers=owner, json={"name": "Sito del negozio"})
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    assert key.startswith("m2f_") and created.json()["prefix"] == key[:12]

    listed = client.get(f"/api/organizations/{slug}/api-keys", headers=owner).json()
    assert [(k["name"], k["prefix"]) for k in listed] == [("Sito del negozio", key[:12])]
    assert "key" not in listed[0]                                    # dopo non si vede più

    staff = _register_user(client, "api-staff@example.com", role="organizer")
    client.post(f"/api/organizations/{slug}/members", headers=owner, json={"email": "api-staff@example.com", "role": "organizer"})
    assert client.post(f"/api/organizations/{slug}/api-keys", headers=staff, json={"name": "Mia"}).status_code == 403


def test_a_key_reads_only_its_store_and_no_personal_data(client):
    owner, slug, tid = _store_with_tournament(client, "api-owner2@example.com", "Arcana")
    _, _, other_tid = _store_with_tournament(client, "api-owner3@example.com", "Dadi e Mana")
    key = client.post(f"/api/organizations/{slug}/api-keys", headers=owner, json={"name": "Overlay"}).json()["key"]
    api = {"X-API-Key": key}

    for i in range(2):
        client.post(f"/api/tournaments/{tid}/walk-in", headers=owner,
                    json={"display_name": f"Giocatore {i}", "wizards_account": "123"})
    assert client.post(f"/api/tournaments/{tid}/start", headers=owner).status_code == 200

    assert [t["id"] for t in client.get("/api/v1/tournaments", headers=api).json()] == [tid]
    assert client.get(f"/api/v1/tournaments/{other_tid}", headers=api).status_code == 404

    players = client.get(f"/api/v1/tournaments/{tid}/players", headers=api).json()
    assert {p["name"] for p in players} == {"Giocatore 0", "Giocatore 1"}
    assert not {"email", "wizards_account", "payment_status"} & set(players[0])

    pairings = client.get(f"/api/v1/tournaments/{tid}/pairings", headers=api).json()
    assert pairings["round"] == 1 and len(pairings["pairings"]) == 1
    assert len(client.get(f"/api/v1/tournaments/{tid}/standings", headers=api).json()) == 2

    assert client.get("/api/v1/tournaments").status_code == 401
    assert client.get("/api/v1/tournaments", headers={"X-API-Key": "m2f_sbagliata"}).status_code == 401
    listed = client.get(f"/api/organizations/{slug}/api-keys", headers=owner).json()[0]
    assert listed["last_used_at"]
    assert client.delete(f"/api/organizations/{slug}/api-keys/{listed['id']}", headers=owner).status_code == 204
    assert client.get("/api/v1/tournaments", headers=api).status_code == 401    # revocata
