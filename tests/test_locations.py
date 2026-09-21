"""
test_locations.py — Più sedi per negozio: il torneo sceglie dove si gioca.
"""
from datetime import date, timedelta

MILANO = (45.4642, 9.19)
BERGAMO = (45.6983, 9.6773)


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _organizer_with_store(client, email, store="Carte Bergamo"):
    headers = _register_user(client, email, role="organizer")
    created = client.post("/api/organizations/mine", headers=headers, json={"name": store})
    assert created.status_code == 201, created.text
    return headers, created.json()["slug"]


def _location(client, org, slug, **extra):
    body = {"name": "Sala grande", "address": "Via Roma 1", "city": "Bergamo",
            "latitude": BERGAMO[0], "longitude": BERGAMO[1]}
    body.update(extra)
    created = client.post(f"/api/organizations/{slug}/locations", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _tournament(client, org, **extra):
    body = {
        "name": "Serata in sala", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def test_the_store_lists_its_locations_publicly(client):
    org, slug = _organizer_with_store(client, "loc-org@example.com")
    _location(client, org, slug, name="Negozio")
    _location(client, org, slug, name="Auditorium")
    names = [loc["name"] for loc in client.get(f"/api/organizations/{slug}/locations").json()]
    assert names == ["Auditorium", "Negozio"]
    profile = client.get(f"/api/organizations/{slug}/profile").json()
    assert [loc["label"] for loc in profile["locations"]] == [
        "Auditorium, Via Roma 1, Bergamo", "Negozio, Via Roma 1, Bergamo",
    ]


def test_a_tournament_inherits_place_and_coordinates(client):
    org, slug = _organizer_with_store(client, "loc-org2@example.com")
    sala = _location(client, org, slug)
    created = _tournament(client, org, location_id=sala["id"])
    assert created["venue"] == "Sala grande, Via Roma 1, Bergamo"
    assert created["location_name"] == "Sala grande"

    # La ricerca per distanza lo trova dove si gioca davvero.
    near = client.get(f"/api/tournaments?near_lat={BERGAMO[0]}&near_lng={BERGAMO[1]}&radius_km=5").json()
    assert [t["name"] for t in near] == ["Serata in sala"]
    far = client.get(f"/api/tournaments?near_lat={MILANO[0]}&near_lng={MILANO[1]}&radius_km=5").json()
    assert far == []
    # ...e anche cercandolo per luogo.
    assert len(client.get("/api/tournaments?venue=Bergamo").json()) == 1


def test_a_written_venue_wins_over_the_location(client):
    org, slug = _organizer_with_store(client, "loc-org3@example.com")
    sala = _location(client, org, slug)
    created = _tournament(client, org, location_id=sala["id"], venue="Sala piccola, primo piano")
    assert created["venue"] == "Sala piccola, primo piano"


def test_the_location_can_be_changed_and_removed(client):
    org, slug = _organizer_with_store(client, "loc-org4@example.com")
    sala = _location(client, org, slug)
    tid = _tournament(client, org)["id"]
    patched = client.patch(f"/api/tournaments/{tid}", headers=org, json={"location_id": sala["id"]})
    assert patched.json()["location_name"] == "Sala grande"
    cleared = client.patch(f"/api/tournaments/{tid}", headers=org, json={"location_id": 0})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["location_id"] is None


def test_deleting_a_location_keeps_where_past_tournaments_were_played(client):
    org, slug = _organizer_with_store(client, "loc-org5@example.com")
    sala = _location(client, org, slug)
    tid = _tournament(client, org, location_id=sala["id"])["id"]
    deleted = client.delete(f"/api/organizations/{slug}/locations/{sala['id']}", headers=org)
    assert deleted.status_code == 204
    body = client.get(f"/api/tournaments/{tid}").json()
    assert body["location_id"] is None
    assert body["venue"] == "Sala grande, Via Roma 1, Bergamo"
    assert body["latitude"] == BERGAMO[0]


def test_another_store_cannot_use_or_edit_my_locations(client):
    mine, slug = _organizer_with_store(client, "loc-mine@example.com")
    sala = _location(client, mine, slug)
    theirs, _ = _organizer_with_store(client, "loc-theirs@example.com", store="Altro Negozio")

    refused = client.post("/api/tournaments", headers=theirs, json={
        "name": "Nella sala altrui", "format": "Modern", "location_id": sala["id"],
        "starts_on": str(date.today() + timedelta(days=5)), "capacity": 8,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert refused.status_code == 404
    edit = client.put(f"/api/organizations/{slug}/locations/{sala['id']}", headers=theirs,
                      json={"name": "Presa"})
    assert edit.status_code == 403
