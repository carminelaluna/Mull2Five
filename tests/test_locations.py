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


def _location(client, org, **extra):
    body = {"name": "Sala grande", "address": "Via Roma 1", "city": "Bergamo",
            "latitude": BERGAMO[0], "longitude": BERGAMO[1]}
    body.update(extra)
    created = client.post("/api/organizations/mull2five/locations", headers=org, json=body)
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
    org = _register_user(client, "loc-org@example.com", role="organizer")
    _location(client, org, name="Negozio")
    _location(client, org, name="Auditorium")
    names = [loc["name"] for loc in client.get("/api/organizations/mull2five/locations").json()]
    assert names == ["Auditorium", "Negozio"]
    profile = client.get("/api/organizations/mull2five/profile").json()
    assert [loc["label"] for loc in profile["locations"]] == [
        "Auditorium, Via Roma 1, Bergamo", "Negozio, Via Roma 1, Bergamo",
    ]


def test_a_tournament_inherits_place_and_coordinates(client):
    org = _register_user(client, "loc-org2@example.com", role="organizer")
    sala = _location(client, org)
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
    org = _register_user(client, "loc-org3@example.com", role="organizer")
    sala = _location(client, org)
    created = _tournament(client, org, location_id=sala["id"], venue="Sala piccola, primo piano")
    assert created["venue"] == "Sala piccola, primo piano"


def test_the_location_can_be_changed_and_removed(client):
    org = _register_user(client, "loc-org4@example.com", role="organizer")
    sala = _location(client, org)
    tid = _tournament(client, org)["id"]
    patched = client.patch(f"/api/tournaments/{tid}", headers=org, json={"location_id": sala["id"]})
    assert patched.json()["location_name"] == "Sala grande"
    cleared = client.patch(f"/api/tournaments/{tid}", headers=org, json={"location_id": 0})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["location_id"] is None


def test_deleting_a_location_keeps_where_past_tournaments_were_played(client):
    org = _register_user(client, "loc-org5@example.com", role="organizer")
    sala = _location(client, org)
    tid = _tournament(client, org, location_id=sala["id"])["id"]
    deleted = client.delete(f"/api/organizations/mull2five/locations/{sala['id']}", headers=org)
    assert deleted.status_code == 204
    body = client.get(f"/api/tournaments/{tid}").json()
    assert body["location_id"] is None
    assert body["venue"] == "Sala grande, Via Roma 1, Bergamo"
    assert body["latitude"] == BERGAMO[0]


def test_another_store_cannot_use_or_edit_my_locations(client, db_session):
    from sqlalchemy import select

    from backend.app.models import Organization, User

    other = Organization(slug="altro-negozio", name="Altro Negozio")
    db_session.add(other)
    db_session.commit()

    mine = _register_user(client, "loc-mine@example.com", role="organizer")
    sala = _location(client, mine)

    theirs = _register_user(client, "loc-theirs@example.com", role="organizer")
    rival = db_session.scalar(select(User).where(User.email == "loc-theirs@example.com"))
    rival.organization_id = other.id
    db_session.commit()

    refused = client.post("/api/tournaments", headers=theirs, json={
        "name": "Nella sala altrui", "format": "Modern", "location_id": sala["id"],
        "starts_on": str(date.today() + timedelta(days=5)), "capacity": 8,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert refused.status_code == 404
    edit = client.put(f"/api/organizations/mull2five/locations/{sala['id']}", headers=theirs,
                      json={"name": "Presa"})
    assert edit.status_code == 403


def test_the_backoffice_opens_the_organizers_own_store(client, db_session):
    from sqlalchemy import select

    from backend.app.models import Organization, User

    other = Organization(slug="secondo-negozio", name="Secondo Negozio")
    db_session.add(other)
    db_session.commit()
    headers = _register_user(client, "loc-second@example.com", role="organizer")
    user = db_session.scalar(select(User).where(User.email == "loc-second@example.com"))
    user.organization_id = other.id
    db_session.commit()
    assert client.get("/api/organizations/mine", headers=headers).json()["slug"] == "secondo-negozio"
