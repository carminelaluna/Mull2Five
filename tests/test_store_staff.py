"""
test_store_staff.py — Staff del negozio: più account sugli stessi tornei.
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


def _tournament(client, headers, name="Serata del negozio"):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": name, "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()


def _store(client, headers, name="Carte e Draghi"):
    created = client.post("/api/organizations/mine", headers=headers, json={"name": name, "city": "Pavia"})
    assert created.status_code == 201, created.text
    return created.json()["slug"]


def _add(client, owner, slug, email, role="organizer"):
    return client.post(f"/api/organizations/{slug}/members", headers=owner,
                       json={"email": email, "role": role})


def test_without_a_store_there_is_nothing_to_manage(client):
    org = _register_user(client, "staff-none@example.com", role="organizer")
    assert client.get("/api/organizations/mine", headers=org).status_code == 404


def test_opening_a_store_brings_along_the_tournaments_so_far(client):
    owner = _register_user(client, "staff-owner@example.com", role="organizer")
    tid = _tournament(client, owner)["id"]
    slug = _store(client, owner)
    assert slug == "carte-e-draghi"

    mine = client.get("/api/organizations/mine", headers=owner).json()
    assert (mine["slug"], mine["my_role"]) == (slug, "owner")
    assert client.get(f"/api/tournaments/{tid}").json()["organization_slug"] == slug
    # Un altro negozio con lo stesso nome prende uno slug suo.
    other = _register_user(client, "staff-owner2@example.com", role="organizer")
    assert _store(client, other) == "carte-e-draghi-2"


def test_staff_manage_every_tournament_of_the_store(client):
    owner = _register_user(client, "staff-o3@example.com", role="organizer")
    slug = _store(client, owner)
    tid = _tournament(client, owner)["id"]

    # Chi viene aggiunto era solo un giocatore: ora apre il backoffice del negozio.
    _register_user(client, "staff-helper@example.com")
    added = _add(client, owner, slug, "staff-helper@example.com")
    assert added.status_code == 201, added.text
    helper = _register_user(client, "staff-helper@example.com")   # nuovo token, nuovo ruolo
    assert client.get("/api/organizations/mine", headers=helper).json()["slug"] == slug

    renamed = client.patch(f"/api/tournaments/{tid}", headers=helper, json={"name": "Serata dello staff"})
    assert renamed.status_code == 200, renamed.text
    listed = {t["id"]: t for t in client.get("/api/tournaments/mine", headers=helper).json()}
    assert listed[tid]["can_manage"] is True

    # I suoi tornei nuovi sono del negozio, e il titolare li gestisce.
    own = _tournament(client, helper, name="Torneo dell'aiutante")
    assert own["organization_slug"] == slug
    assert client.patch(f"/api/tournaments/{own['id']}", headers=owner,
                        json={"capacity": 20}).status_code == 200


def test_outsiders_cannot_touch_the_store(client):
    owner = _register_user(client, "staff-o4@example.com", role="organizer")
    slug = _store(client, owner)
    tid = _tournament(client, owner)["id"]
    outsider = _register_user(client, "staff-out@example.com", role="organizer")
    assert client.patch(f"/api/tournaments/{tid}", headers=outsider, json={"name": "Presa"}).status_code == 404
    assert client.get(f"/api/organizations/{slug}/members", headers=outsider).status_code == 403
    assert client.patch(f"/api/organizations/{slug}", headers=outsider,
                        json={"description": "Presa"}).status_code == 403


def test_only_the_owner_decides_the_staff(client):
    owner = _register_user(client, "staff-o5@example.com", role="organizer")
    slug = _store(client, owner)
    _register_user(client, "staff-a@example.com", role="organizer")
    _register_user(client, "staff-b@example.com", role="organizer")
    assert _add(client, owner, slug, "staff-a@example.com").status_code == 201
    staff_a = _register_user(client, "staff-a@example.com", role="organizer")
    assert _add(client, staff_a, slug, "staff-b@example.com").status_code == 403

    assert _add(client, owner, slug, "nessuno@example.com").status_code == 404
    assert _add(client, owner, slug, "staff-a@example.com").status_code == 409
    roles = {m["email"]: m["role"] for m in client.get(f"/api/organizations/{slug}/members", headers=staff_a).json()}
    assert roles == {"staff-o5@example.com": "owner", "staff-a@example.com": "organizer"}


def test_the_store_never_stays_without_an_owner(client):
    owner = _register_user(client, "staff-o6@example.com", role="organizer")
    slug = _store(client, owner)
    me = client.get("/api/auth/me", headers=owner).json()["id"]
    assert client.delete(f"/api/organizations/{slug}/members/{me}", headers=owner).status_code == 409
    assert client.patch(f"/api/organizations/{slug}/members/{me}", headers=owner,
                        json={"role": "organizer"}).status_code == 409

    # Con un secondo titolare, il primo può farsi da parte.
    _register_user(client, "staff-o7@example.com", role="organizer")
    assert _add(client, owner, slug, "staff-o7@example.com", role="owner").status_code == 201
    assert client.delete(f"/api/organizations/{slug}/members/{me}", headers=owner).status_code == 204
    assert client.get("/api/organizations/mine", headers=owner).status_code == 404


def test_removed_staff_lose_access(client):
    owner = _register_user(client, "staff-o8@example.com", role="organizer")
    slug = _store(client, owner)
    tid = _tournament(client, owner)["id"]
    _register_user(client, "staff-gone@example.com", role="organizer")
    member = _add(client, owner, slug, "staff-gone@example.com").json()
    gone = _register_user(client, "staff-gone@example.com", role="organizer")
    assert client.patch(f"/api/tournaments/{tid}", headers=gone, json={"name": "Ancora mio"}).status_code == 200

    assert client.delete(f"/api/organizations/{slug}/members/{member['user_id']}", headers=owner).status_code == 204
    assert client.patch(f"/api/tournaments/{tid}", headers=gone, json={"name": "Non più"}).status_code == 404


def test_switching_between_stores(client):
    owner_a = _register_user(client, "staff-oa@example.com", role="organizer")
    slug_a = _store(client, owner_a, name="Negozio A")
    owner_b = _register_user(client, "staff-ob@example.com", role="organizer")
    slug_b = _store(client, owner_b, name="Negozio B")
    assert _add(client, owner_b, slug_b, "staff-oa@example.com").status_code == 201

    stores = client.get("/api/organizations/memberships", headers=owner_a).json()
    assert [(s["slug"], s["role"], s["current"]) for s in stores] == [
        (slug_a, "owner", True), (slug_b, "organizer", False),
    ]
    assert client.post(f"/api/organizations/{slug_b}/use", headers=owner_a).status_code == 200
    assert _tournament(client, owner_a)["organization_slug"] == slug_b
    stranger = _register_user(client, "staff-nope@example.com", role="organizer")
    assert client.post(f"/api/organizations/{slug_b}/use", headers=stranger).status_code == 403


def test_a_tournament_leaving_for_the_new_store_keeps_its_place(client, db_session):
    """La sede era del negozio di default: il torneo che passa al negozio nuovo
    tiene scritto dove si gioca."""
    from sqlalchemy import select

    from backend.app.models import Location, Organization

    default = db_session.scalar(select(Organization).where(Organization.is_default.is_(True)))
    hall = Location(organization_id=default.id, name="Sala comune", city="Milano",
                    latitude=45.46, longitude=9.19)
    db_session.add(hall)
    db_session.commit()

    owner = _register_user(client, "staff-o9@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=owner, json={
        "name": "Serata in sala comune", "format": "Modern", "location_id": hall.id,
        "starts_on": str(date.today() + timedelta(days=5)), "capacity": 8,
        "entry_fee_cents": 0, "currency": "EUR", "status": "published", "pay_at_event": True,
    })
    assert created.status_code == 201, created.text
    _store(client, owner)
    body = client.get(f"/api/tournaments/{created.json()['id']}").json()
    assert (body["location_id"], body["venue"], body["latitude"]) == (None, "Sala comune, Milano", 45.46)


def test_staff_see_what_the_organizer_sees(client):
    """Iscritti e classifica non pubblica di un torneo del collega."""
    owner = _register_user(client, "staff-o10@example.com", role="organizer")
    slug = _store(client, owner)
    tid = _tournament(client, owner)["id"]
    client.patch(f"/api/tournaments/{tid}/controls", headers=owner, json={"standings_public": False})
    player = _register_user(client, "staff-p10@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": "X"})

    _register_user(client, "staff-c10@example.com", role="organizer")
    _add(client, owner, slug, "staff-c10@example.com")
    colleague = _register_user(client, "staff-c10@example.com", role="organizer")
    listed = client.get(f"/api/tournaments/{tid}/registrations", headers=colleague)
    assert listed.status_code == 200, listed.text
    assert [r["player_email"] for r in listed.json()] == ["staff-p10@example.com"]

