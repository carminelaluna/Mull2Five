"""
test_store_closure.py — Il negozio quando chi lo gestiva elimina l'account.

Il negozio nato da solo porta il nome dell'account (25/11/2026). Eliminando
l'account restava fra i negozi pubblici con quel nome: qui si chiude, o passa
allo staff che resta. La migrazione 0017 fa lo stesso sui negozi già rimasti
così.
"""
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.pool import StaticPool

from backend.app.models import Location, Organization, StoreMember, StoreRole, Tournament, User
from backend.app.services.stores import give_stores_to_organizers

BERGAMO = (45.6983, 9.6773)


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _store(client, headers, name="Carte e Draghi"):
    created = client.post("/api/organizations/mine", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["slug"]


def _location(client, headers, slug, name="Sala grande", address="Via Roma 1", city="Bergamo"):
    created = client.post(f"/api/organizations/{slug}/locations", headers=headers, json={
        "name": name, "address": address, "city": city,
        "latitude": BERGAMO[0], "longitude": BERGAMO[1],
    })
    assert created.status_code == 201, created.text
    return created.json()


def _tournament(client, headers, location_id=None):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": "Serata del negozio", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "location_id": location_id,
    })
    assert created.status_code == 201, created.text
    return created.json()


def _add(client, owner, slug, email, role="organizer"):
    added = client.post(f"/api/organizations/{slug}/members", headers=owner,
                        json={"email": email, "role": role})
    assert added.status_code == 201, added.text
    return added.json()


def test_deleting_the_only_organizer_closes_the_store_and_keeps_the_place(client, db_session):
    organizer = _register_user(client, "closure-owner@example.com", role="organizer")
    slug = _store(client, organizer)
    sala = _location(client, organizer, slug)
    tournament_id = _tournament(client, organizer, location_id=sala["id"])["id"]
    org_id = db_session.scalar(select(Organization.id).where(Organization.slug == slug))

    deleted = client.delete("/api/auth/me", headers=organizer)
    assert deleted.status_code == 200, deleted.text

    # Non è più un negozio: né nell'elenco, né alla sua pagina, né nella sitemap.
    assert "Carte e Draghi" not in [o["name"] for o in client.get("/api/organizations").json()]
    assert client.get(f"/api/organizations/{slug}/profile").status_code == 404
    closed = db_session.get(Organization, org_id)
    assert closed.name == "Negozio chiuso"
    assert closed.slug == f"negozio-chiuso-{org_id}"
    assert closed.closed_at is not None
    assert client.get(f"/api/organizations/{closed.slug}/profile").status_code == 404
    sitemap = client.get("/sitemap.xml").text
    assert f"store.html?s={slug}" not in sitemap
    assert f"store.html?s={closed.slug}" not in sitemap

    # Il torneo resta, con il luogo scritto: lo storico non perde dove si giocava.
    body = client.get(f"/api/tournaments/{tournament_id}").json()
    assert body["location_id"] is None
    assert body["venue"] == "Sala grande, Via Roma 1, Bergamo"
    assert (body["latitude"], body["longitude"]) == BERGAMO
    assert db_session.scalar(
        select(func.count(Location.id)).where(Location.organization_id == org_id)
    ) == 0
    assert db_session.scalar(
        select(func.count(StoreMember.id)).where(StoreMember.organization_id == org_id)
    ) == 0

    # Il profilo del negozio non tiene più nome, indirizzo o coordinate di casa.
    assert (closed.description, closed.city, closed.address) == ("", "", "")
    assert (closed.website, closed.logo_url) == ("", "")
    assert (closed.latitude, closed.longitude) == (None, None)
    assert closed.is_premium is False


def test_deleting_the_owner_leaves_the_store_to_the_oldest_member(client, db_session):
    owner = _register_user(client, "closure-owner2@example.com", role="organizer")
    slug = _store(client, owner)
    first = _register_user(client, "closure-first@example.com")
    _register_user(client, "closure-second@example.com")
    _add(client, owner, slug, "closure-first@example.com")
    _add(client, owner, slug, "closure-second@example.com")
    org_id = db_session.scalar(select(Organization.id).where(Organization.slug == slug))
    first_id = db_session.scalar(select(User.id).where(User.email == "closure-first@example.com"))
    second_id = db_session.scalar(select(User.id).where(User.email == "closure-second@example.com"))

    assert client.delete("/api/auth/me", headers=owner).status_code == 200

    org = db_session.get(Organization, org_id)
    assert org.closed_at is None
    assert (org.name, org.slug) == ("Carte e Draghi", slug)
    roles = {
        member.user_id: member.role
        for member in db_session.scalars(
            select(StoreMember).where(StoreMember.organization_id == org_id)
        )
    }
    assert roles == {first_id: StoreRole.OWNER, second_id: StoreRole.ORGANIZER}
    mine = client.get("/api/organizations/mine", headers=first)
    assert mine.status_code == 200
    assert (mine.json()["slug"], mine.json()["my_role"]) == (slug, StoreRole.OWNER)


def test_deleting_a_member_does_not_close_the_store(client):
    owner = _register_user(client, "closure-owner3@example.com", role="organizer")
    slug = _store(client, owner)
    member = _register_user(client, "closure-member@example.com")
    _add(client, owner, slug, "closure-member@example.com")

    assert client.delete("/api/auth/me", headers=member).status_code == 200

    assert client.get(f"/api/organizations/{slug}/profile").status_code == 200
    members = client.get(f"/api/organizations/{slug}/members", headers=owner).json()
    assert [(m["email"], m["role"]) for m in members] == [
        ("closure-owner3@example.com", StoreRole.OWNER),
    ]


def test_a_deleted_account_does_not_get_a_store_at_startup(client, db_session):
    organizer = _register_user(client, "closure-legacy@example.com", role="organizer")
    default = db_session.scalar(select(Organization).where(Organization.is_default.is_(True)))
    person = db_session.scalar(select(User).where(User.email == "closure-legacy@example.com"))
    db_session.add(Tournament(
        name="Serata di prima", format="Modern", organizer_id=person.id,
        organization_id=default.id, starts_on=date.today() + timedelta(days=5),
        capacity=16, rules_enforcement_level="Regular", venue="",
    ))
    db_session.commit()

    assert client.delete("/api/auth/me", headers=organizer).status_code == 200
    assert give_stores_to_organizers(db_session) == 0
    assert db_session.scalar(
        select(func.count(Organization.id)).where(Organization.is_default.is_(False))
    ) == 0


def _revisione(nome: str):
    import importlib.util
    from pathlib import Path

    percorso = Path(__file__).resolve().parent.parent / "migrations" / "versions" / f"{nome}.py"
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_la_migrazione_chiude_i_negozi_gia_rimasti_senza_nessuno():
    """La 0017 fa sui negozi già orfani quello che `close_store` fa da adesso."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://", poolclass=StaticPool)
    meta = sa.MetaData()
    organizations = sa.Table(
        "organizations", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("address", sa.String(240), nullable=False),
        sa.Column("website", sa.String(240), nullable=False),
        sa.Column("logo_url", sa.String(400), nullable=False),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("is_premium", sa.Boolean, nullable=False),
    )
    store_members = sa.Table(
        "store_members", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
    )
    users = sa.Table(
        "users", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    locations = sa.Table(
        "locations", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(240), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
    )
    tournaments = sa.Table(
        "tournaments", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, nullable=True),
        sa.Column("venue", sa.String(180), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
    )
    meta.create_all(engine)

    def org(id, slug, name, default=False):
        return {"id": id, "slug": slug, "name": name, "is_default": default, "description": "",
                "city": "", "address": "", "website": "", "logo_url": "",
                "latitude": None, "longitude": None, "is_premium": False}

    with engine.begin() as connection:
        connection.execute(organizations.insert(), [
            org(1, "mull2five", "Mull2Five", default=True),
            org(2, "negozio-aperto", "Negozio aperto"),
            org(3, "prova-notifiche", "Prova notifiche"),
            org(4, "senza-staff", "Senza staff"),
            org(5, "altro-orfano", "Altro orfano"),
        ])
        connection.execute(users.insert(), [
            {"id": 1, "is_active": False},
            {"id": 2, "is_active": True},
            {"id": 3, "is_active": False},
            {"id": 5, "is_active": False},
            {"id": 6, "is_active": False},
        ])
        connection.execute(store_members.insert(), [
            {"id": 1, "organization_id": 1, "user_id": 1},
            {"id": 2, "organization_id": 2, "user_id": 2},
            {"id": 3, "organization_id": 3, "user_id": 3},
            {"id": 4, "organization_id": 5, "user_id": 5},
            {"id": 5, "organization_id": 5, "user_id": 6},
        ])
        connection.execute(locations.insert(), [
            {"id": 1, "organization_id": 2, "name": "Sede aperta", "address": "Via A 1",
             "city": "Milano", "latitude": 45.46, "longitude": 9.19},
            {"id": 2, "organization_id": 3, "name": "Sala", "address": "Via Roma 1",
             "city": "Pavia", "latitude": 45.18, "longitude": 9.15},
            {"id": 3, "organization_id": 5, "name": "Magazzino", "address": "",
             "city": "", "latitude": None, "longitude": None},
        ])
        connection.execute(tournaments.insert(), [
            {"id": 1, "location_id": 1, "venue": "", "latitude": None, "longitude": None},
            {"id": 2, "location_id": 2, "venue": "", "latitude": None, "longitude": None},
            {"id": 3, "location_id": 2, "venue": "Scritto a mano",
             "latitude": 44.0, "longitude": 10.0},
            {"id": 4, "location_id": 3, "venue": "", "latitude": None, "longitude": None},
        ])

        # Due volte: una revisione che riparte su un database già aggiornato non
        # deve rompere niente.
        for _ in range(2):
            with Operations.context(MigrationContext.configure(connection)):
                _revisione("0017_store_closed_at").upgrade()

        rows = connection.execute(sa.text(
            "SELECT id, name, slug, closed_at FROM organizations ORDER BY id"
        )).all()
        assert [(r.id, r.name, r.closed_at is None) for r in rows] == [
            (1, "Mull2Five", True),
            (2, "Negozio aperto", True),
            (3, "Negozio chiuso", False),
            (4, "Senza staff", True),
            (5, "Negozio chiuso", False),
        ]
        assert rows[2].slug == "negozio-chiuso-3"
        assert rows[4].slug == "negozio-chiuso-5"

        # Le sedi dei negozi chiusi se ne vanno, i tornei tengono il luogo scritto.
        assert connection.execute(sa.text("SELECT id FROM locations ORDER BY id")).scalars().all() == [1]
        place = connection.execute(sa.text(
            "SELECT location_id, venue, latitude, longitude FROM tournaments WHERE id = 2"
        )).one()
        assert (place.location_id, place.venue) == (None, "Sala, Via Roma 1, Pavia")
        assert (place.latitude, place.longitude) == (45.18, 9.15)
        written = connection.execute(sa.text(
            "SELECT location_id, venue, latitude FROM tournaments WHERE id = 3"
        )).one()
        assert (written.location_id, written.venue, written.latitude) == (None, "Scritto a mano", 44.0)
        assert connection.execute(sa.text(
            "SELECT location_id FROM tournaments WHERE id = 1"
        )).scalar() == 1
