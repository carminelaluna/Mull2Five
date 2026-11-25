"""
test_own_store.py — Il negozio che nasce da solo (25/11/2026).

Chi organizzava senza negozio finiva nel negozio di default, e i suoi tornei
uscivano "Organizzato da Fumetteria X · Mull2Five", con Mull2Five fra i
negozi. Ora il primo torneo, evento o circuito gli apre un negozio col nome
del suo account, e chi aveva già creato qualcosa lo riceve all'avvio.
"""
from datetime import date, timedelta

from sqlalchemy import select

from backend.app.models import Organization, Tournament, User, UserRole
from backend.app.services.stores import give_stores_to_organizers


def _user(client, email, name, role="organizer"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": name, "password": "supersecret123", "role": role})
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, headers, name="Serata"):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": name, "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()


def _stores(client):
    return [o["slug"] for o in client.get("/api/organizations").json()]


def test_the_first_tournament_opens_a_store_named_after_the_organizer(client):
    org = _user(client, "os-fx@example.com", "Fumetteria X")
    assert client.get("/api/organizations/mine", headers=org).status_code == 404

    first = _tournament(client, org)
    assert (first["organization_slug"], first["organization_name"]) == ("fumetteria-x", "Fumetteria X")
    mine = client.get("/api/organizations/mine", headers=org).json()
    assert (mine["slug"], mine["my_role"]) == ("fumetteria-x", "owner")
    # Il secondo va nello stesso negozio: non se ne apre un altro.
    assert _tournament(client, org, "Seconda serata")["organization_slug"] == "fumetteria-x"
    # Fra i negozi c'è il suo, e non quello di default.
    assert _stores(client) == ["fumetteria-x"]


def test_staff_create_in_their_store_without_opening_another(client):
    owner = _user(client, "os-owner@example.com", "Titolare")
    slug = client.post("/api/organizations/mine", headers=owner,
                       json={"name": "Carte e Draghi", "city": "Pavia"}).json()["slug"]
    helper = _user(client, "os-help@example.com", "Aiutante")
    assert client.post(f"/api/organizations/{slug}/members", headers=owner,
                       json={"email": "os-help@example.com", "role": "organizer"}).status_code == 201

    assert _tournament(client, helper)["organization_slug"] == slug
    assert _stores(client) == [slug]


def test_an_event_or_a_circuit_opens_the_store_too(client):
    org = _user(client, "os-toy@example.com", "ToyStore")
    event = client.post("/api/events", headers=org, json={
        "name": "Weekend Modern", "starts_on": str(date.today() + timedelta(days=9))})
    assert event.status_code == 201, event.text
    assert event.json()["organization_slug"] == "toystore"

    other = _user(client, "os-lega@example.com", "Lega Pavese")
    season = client.post("/api/seasons", headers=other, json={"name": "Lega d'inverno"})
    assert season.status_code == 201, season.text
    assert season.json()["organization_slug"] == "lega-pavese"


def test_a_preview_of_the_calendar_opens_nothing(client):
    org = _user(client, "os-cal@example.com", "Calendario")
    day = (date.today() + timedelta(days=4)).strftime("%d/%m/%Y")
    body = {"csv_text": f"nome;data;formato\nFNM;{day};Modern\n", "venue": "Sala", "city": "Pavia"}

    preview = client.post("/api/tournaments/import-schedule", headers=org, json=body)
    assert preview.status_code == 200, preview.text
    assert client.get("/api/organizations/mine", headers=org).status_code == 404

    done = client.post("/api/tournaments/import-schedule", headers=org, json={**body, "dry_run": False})
    assert done.json()["new"] == 1
    assert client.get("/api/organizations/mine", headers=org).json()["slug"] == "calendario"


def test_an_admin_without_a_store_is_offered_to_open_one(client, db_session):
    """L'admin gestisce qualunque negozio, ma quello di default non è suo: senza
    questo il back-office gli mostrava "Mull2Five" al posto di "Apri il negozio"."""
    admin = _user(client, "os-admin@example.com", "Fumetteria X")
    db_session.scalar(select(User).where(User.email == "os-admin@example.com")).role = UserRole.ADMIN
    db_session.commit()

    assert client.get("/api/organizations/mine", headers=admin).status_code == 404
    assert _tournament(client, admin)["organization_slug"] == "fumetteria-x"
    assert client.get("/api/organizations/mine", headers=admin).json()["my_role"] == "owner"


def test_who_organized_before_gets_a_store_at_startup(client, db_session):
    """I tornei nati nel negozio di default prima del 25/11/2026 passano al
    negozio nuovo del loro organizzatore. Una volta sola: dopo non trova nessuno."""
    _user(client, "os-old@example.com", "Fumetteria X")
    _user(client, "os-idle@example.com", "Senza tornei")
    _user(client, "os-player@example.com", "Giocatore", role="player")
    default = db_session.scalar(select(Organization).where(Organization.is_default.is_(True)))
    organizer = db_session.scalar(select(User).where(User.email == "os-old@example.com"))
    old = Tournament(
        name="Alpha", format="Modern", organizer_id=organizer.id, organization_id=default.id,
        starts_on=date.today() + timedelta(days=3), capacity=16, rules_enforcement_level="Regular", venue="")
    db_session.add(old)
    db_session.commit()

    # Solo chi ha creato qualcosa: chi non ha tornei e i giocatori restano come sono.
    assert give_stores_to_organizers(db_session) == 1
    body = client.get(f"/api/tournaments/{old.id}").json()
    assert (body["organization_slug"], body["organization_name"]) == ("fumetteria-x", "Fumetteria X")
    assert give_stores_to_organizers(db_session) == 0
    assert _stores(client) == ["fumetteria-x"]
