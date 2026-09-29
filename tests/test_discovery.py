"""
test_discovery.py — Ricerca eventi (tipo, REL, formati, periodo, distanza),
profili negozio, circuiti pubblici e tag giocatore.
"""
from datetime import date, timedelta

import jwt

from backend.app.core.config import get_settings

# Duomo di Milano e Mole Antonelliana: ~126 km in linea d'aria.
MILANO = (45.4642, 9.1900)
TORINO = (45.0703, 7.6869)


def _register_user(client, email, role="player", name=None):
    client.post("/api/auth/register", json={
        "email": email, "display_name": name or email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _user_id(headers) -> int:
    """L'id sta nel claim `sub` del token: evita di indovinare la numerazione."""
    token = headers["Authorization"].split()[1]
    return int(jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["sub"])


def _make(client, headers, **overrides):
    payload = {
        "name": "Discovery Open", "format": "Modern", "starts_on": str(date.today() + timedelta(days=7)),
        "capacity": 16, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "decklist_required": False, "pay_at_event": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _search(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = client.get(f"/api/tournaments?{query}")
    assert response.status_code == 200, response.text
    return response.json()


# ── Ricerca eventi ────────────────────────────────────────────


def test_event_type_defaults_to_locals(client):
    org = _register_user(client, "disc-org@example.com", role="organizer")
    tid = _make(client, org)
    assert client.get(f"/api/tournaments/{tid}").json()["event_type"] == "locals"


def test_filter_by_event_type_and_rel(client):
    org = _register_user(client, "types-org@example.com", role="organizer")
    _make(client, org, name="Serata Locals", event_type="locals", rules_enforcement_level="Regular")
    _make(client, org, name="RCQ di Primavera", event_type="rcq", rules_enforcement_level="Competitive")
    _make(client, org, name="Store Champs", event_type="store_championship",
          rules_enforcement_level="Competitive")

    assert [t["name"] for t in _search(client, event_types="rcq")] == ["RCQ di Primavera"]
    competitive = {t["name"] for t in _search(client, rel="Competitive")}
    assert competitive == {"RCQ di Primavera", "Store Champs"}
    both = {t["name"] for t in _search(client, event_types="rcq,store_championship")}
    assert both == {"RCQ di Primavera", "Store Champs"}


def test_filter_by_multiple_formats(client):
    org = _register_user(client, "fmt-org@example.com", role="organizer")
    for fmt in ("Modern", "Legacy", "Commander"):
        _make(client, org, name=f"Serata {fmt}", format=fmt)

    found = {t["format"] for t in _search(client, formats="Modern,Commander")}
    assert found == {"Modern", "Commander"}


def test_filter_by_day_window(client):
    org = _register_user(client, "days-org@example.com", role="organizer")
    _make(client, org, name="Questa settimana", starts_on=str(date.today() + timedelta(days=3)))
    _make(client, org, name="Fra tre mesi", starts_on=str(date.today() + timedelta(days=90)))

    assert [t["name"] for t in _search(client, days=14)] == ["Questa settimana"]
    assert len(_search(client, days=180)) == 2


def test_filter_by_distance_sorts_by_proximity(client):
    org = _register_user(client, "geo-org@example.com", role="organizer")
    _make(client, org, name="Torneo a Milano", latitude=MILANO[0], longitude=MILANO[1])
    _make(client, org, name="Torneo a Torino", latitude=TORINO[0], longitude=TORINO[1])
    _make(client, org, name="Torneo senza coordinate")

    near = _search(client, near_lat=MILANO[0], near_lng=MILANO[1], radius_km=50)
    assert [t["name"] for t in near] == ["Torneo a Milano"]
    assert near[0]["distance_km"] == 0.0

    wide = _search(client, near_lat=MILANO[0], near_lng=MILANO[1], radius_km=200)
    assert [t["name"] for t in wide] == ["Torneo a Milano", "Torneo a Torino"]
    assert 100 < wide[1]["distance_km"] < 150, wide[1]["distance_km"]

    # Senza coordinate un torneo non può entrare in una ricerca per distanza.
    assert "Torneo senza coordinate" not in {t["name"] for t in wide}


def test_tournament_inherits_store_coordinates(client, db_session):
    """Un torneo senza coordinate proprie usa quelle del negozio."""
    from sqlalchemy import select

    from backend.app.models import Organization

    org_row = db_session.scalar(select(Organization).where(Organization.is_default.is_(True)))
    org_row.latitude, org_row.longitude = MILANO
    db_session.commit()

    organizer = _register_user(client, "inherit-org@example.com", role="organizer")
    _make(client, organizer, name="Serata del negozio")

    near = _search(client, near_lat=MILANO[0], near_lng=MILANO[1], radius_km=10)
    assert [t["name"] for t in near] == ["Serata del negozio"]


# ── Profilo negozio ───────────────────────────────────────────


def test_store_profile_splits_upcoming_and_past(client):
    org = _register_user(client, "store-org@example.com", role="organizer")
    _make(client, org, name="Prossimo", starts_on=str(date.today() + timedelta(days=5)))
    _make(client, org, name="Passato", starts_on=str(date.today() - timedelta(days=5)))

    profile = client.get("/api/organizations/mull2five/profile")
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert [t["name"] for t in body["upcoming"]] == ["Prossimo"]
    assert [t["name"] for t in body["past"]] == ["Passato"]
    assert body["organization"]["upcoming_count"] == 1
    assert body["organization"]["past_count"] == 1


def test_organizer_edits_only_his_own_store(client):
    org = _register_user(client, "edit-store@example.com", role="organizer")
    # Il negozio di default non è di nessuno: ci finiscono tutti alla registrazione.
    assert client.patch("/api/organizations/mull2five", headers=org,
                        json={"description": "Preso"}).status_code == 403

    slug = client.post("/api/organizations/mine", headers=org, json={"name": "Negozio di prova"}).json()["slug"]
    updated = client.patch(f"/api/organizations/{slug}", headers=org, json={
        "description": "Il negozio di prova", "city": "Milano",
        "latitude": MILANO[0], "longitude": MILANO[1],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["city"] == "Milano"

    listed = client.get("/api/organizations?near_lat=45.4642&near_lng=9.19&radius_km=5").json()
    assert [o["slug"] for o in listed] == ["negozio-di-prova"]
    assert listed[0]["distance_km"] == 0.0


def _default_org_with_slug(db_session, slug):
    """Un negozio di default come lo lasciava un database di prima del rebrand.

    Il default lo semina già la fixture: qui si riparte da zero, perché è
    proprio la semina che si sta verificando."""
    from backend.app.models import Organization

    for vecchio in db_session.query(Organization).filter_by(is_default=True).all():
        db_session.delete(vecchio)
    db_session.commit()
    org = Organization(slug=slug, name="Mull2Five", is_default=True)
    db_session.add(org)
    db_session.commit()
    return org


def test_the_old_default_store_slug_is_renamed_once(db_session):
    """I database creati prima del rebrand avevano il negozio di default su
    "arcana": all'avvio diventa "mull2five", e ripetere l'avvio non cambia nulla."""
    from backend.app.db import LEGACY_DEFAULT_ORG_SLUG, seed_default_organization

    org = _default_org_with_slug(db_session, LEGACY_DEFAULT_ORG_SLUG)
    seed_default_organization()
    seed_default_organization()
    db_session.refresh(org)
    assert org.slug == "mull2five"


def test_the_rename_never_steals_a_slug_already_taken(db_session):
    from backend.app.db import LEGACY_DEFAULT_ORG_SLUG, seed_default_organization
    from backend.app.models import Organization

    vecchio = _default_org_with_slug(db_session, LEGACY_DEFAULT_ORG_SLUG)
    db_session.add(Organization(slug="mull2five", name="Un altro negozio", is_default=False))
    db_session.commit()

    seed_default_organization()
    db_session.refresh(vecchio)
    assert vecchio.slug == LEGACY_DEFAULT_ORG_SLUG, "due negozi con lo stesso slug"


def test_unknown_store_is_404(client):
    assert client.get("/api/organizations/non-esiste/profile").status_code == 404


# ── Circuiti ──────────────────────────────────────────────────


def test_series_gets_a_public_page(client):
    org = _register_user(client, "series-org@example.com", role="organizer")
    created = client.post("/api/seasons", headers=org,
                          json={"name": "Circuito Lombardo 2027", "points_win": 3, "points_draw": 1})
    assert created.status_code == 201, created.text
    season = created.json()
    assert season["slug"] == "circuito-lombardo-2027"

    tid = _make(client, org, name="Tappa 1")
    assert client.post(f"/api/seasons/{season['id']}/tournaments/{tid}", headers=org).status_code == 200

    updated = client.patch(f"/api/seasons/{season['id']}", headers=org, json={
        "description": "Sei tappe da gennaio a giugno",
        "starts_on": "2027-01-01", "ends_on": "2027-06-30",
        "points_champion_bonus": 3, "qualification_threshold": 20,
    })
    assert updated.status_code == 200, updated.text

    public = client.get("/api/seasons/by-slug/circuito-lombardo-2027")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["season"]["qualification_threshold"] == 20
    assert [t["name"] for t in body["tournaments"]] == ["Tappa 1"]

    assert "circuito-lombardo-2027" in {s["slug"] for s in client.get("/api/seasons/public").json()}


def test_private_series_is_not_public(client):
    org = _register_user(client, "priv-org@example.com", role="organizer")
    season = client.post("/api/seasons", headers=org, json={"name": "Interno", "points_win": 3,
                                                            "points_draw": 1}).json()
    client.patch(f"/api/seasons/{season['id']}", headers=org, json={"is_public": False})

    assert client.get("/api/seasons/by-slug/interno").status_code == 404
    assert "interno" not in {s["slug"] for s in client.get("/api/seasons/public").json()}


def test_series_slugs_do_not_collide(client):
    org = _register_user(client, "slug-org@example.com", role="organizer")
    body = {"name": "Circuito", "points_win": 3, "points_draw": 1}
    first = client.post("/api/seasons", headers=org, json=body).json()
    second = client.post("/api/seasons", headers=org, json=body).json()
    assert first["slug"] == "circuito"
    assert second["slug"] == "circuito-2"


# ── Tag giocatore ─────────────────────────────────────────────


def _store_organizer(client, email):
    """Un organizzatore col suo negozio: i tag sono del negozio."""
    headers = _register_user(client, email, role="organizer")
    opened = client.post("/api/organizations/mine", headers=headers,
                         json={"name": f"Negozio {email.split('@')[0]}"})
    assert opened.status_code == 201, opened.text
    return headers


def _shared_space_tag(db_session, creator, name="Nuovi"):
    """Un tag nel negozio di default, come quando chi non aveva un negozio li creava lì."""
    from sqlalchemy import select

    from backend.app.models import Organization, PlayerTag

    default = db_session.scalar(select(Organization).where(Organization.is_default.is_(True)))
    tag = PlayerTag(organization_id=default.id, name=name, created_by_id=_user_id(creator))
    db_session.add(tag)
    db_session.commit()
    return tag.id


def test_tag_lifecycle_and_bulk_assignment(client):
    org = _store_organizer(client, "tag-org@example.com")
    players = [_register_user(client, f"tagged{i}@example.com") for i in range(2)]

    created = client.post("/api/tags", headers=org,
                          json={"name": "Nuovi", "color": "#3ba55d", "description": "Prima volta"})
    assert created.status_code == 201, created.text
    tag_id = created.json()["id"]
    assert created.json()["player_count"] == 0

    ids = [_user_id(h) for h in players]
    assigned = client.post(f"/api/tags/{tag_id}/players", headers=org, json={"user_ids": ids})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["player_count"] == 2

    # Ripetere la stessa assegnazione non duplica nulla.
    again = client.post(f"/api/tags/{tag_id}/players", headers=org, json={"user_ids": ids})
    assert again.json()["player_count"] == 2

    assert len(client.get(f"/api/tags/{tag_id}/players", headers=org).json()) == 2
    assert client.delete(f"/api/tags/{tag_id}/players/{ids[0]}", headers=org).status_code == 204
    assert client.get("/api/tags", headers=org).json()[0]["player_count"] == 1

    assert client.delete(f"/api/tags/{tag_id}", headers=org).status_code == 204
    assert client.get("/api/tags", headers=org).json() == []


def test_duplicate_tag_name_is_refused(client):
    org = _store_organizer(client, "dup-tag@example.com")
    body = {"name": "Commander", "color": "#d8b465", "description": ""}
    assert client.post("/api/tags", headers=org, json=body).status_code == 201
    assert client.post("/api/tags", headers=org, json=body).status_code == 409


def test_players_cannot_touch_tags(client):
    org = _store_organizer(client, "owner-tag@example.com")
    tag = client.post("/api/tags", headers=org,
                      json={"name": "Riservato", "color": "#d8b465", "description": ""}).json()
    player = _register_user(client, "curious@example.com")

    assert client.get("/api/tags", headers=player).status_code == 403
    assert client.post(f"/api/tags/{tag['id']}/players", headers=player,
                       json={"user_ids": [1]}).status_code == 403


def test_tags_show_up_on_the_registration_list(client):
    org = _store_organizer(client, "reglist-org@example.com")
    tid = _make(client, org, entry_fee_cents=0)
    player = _register_user(client, "reglist-player@example.com")
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                      json={"wizards_account": "R1"})
    assert reg.status_code == 201, reg.text

    tag = client.post("/api/tags", headers=org,
                      json={"name": "Habitue", "color": "#d8b465", "description": ""}).json()
    client.post(f"/api/tags/{tag['id']}/players", headers=org,
                json={"user_ids": [reg.json()["player_id"]]})

    rows = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
    assert [t["name"] for t in rows[0]["tags"]] == ["Habitue"]


def test_tag_of_one_store_is_invisible_to_another(client):
    """L'etichetta vale dentro il negozio che l'ha creata."""
    mine = _store_organizer(client, "store-a@example.com")
    tag = client.post("/api/tags", headers=mine,
                      json={"name": "Solo mio", "color": "#d8b465", "description": ""}).json()

    theirs = _store_organizer(client, "store-b@example.com")
    assert client.get("/api/tags", headers=theirs).json() == []
    assert client.get(f"/api/tags/{tag['id']}/players", headers=theirs).status_code == 404
    assert client.delete(f"/api/tags/{tag['id']}", headers=theirs).status_code == 404


def test_organizers_without_a_store_cannot_see_each_others_tags(client, db_session):
    """Alla registrazione tutti finiscono nel negozio di default: se i tag fossero
    suoi, ogni organizzatore senza negozio vedrebbe, assegnerebbe e cancellerebbe
    quelli degli altri. Senza negozio non se ne creano e non se ne vedono."""
    first = _register_user(client, "solo-a@example.com", role="organizer")
    second = _register_user(client, "solo-b@example.com", role="organizer")
    tag_id = _shared_space_tag(db_session, first)
    player = _user_id(_register_user(client, "solo-player@example.com"))

    refused = client.post("/api/tags", headers=second,
                          json={"name": "Commander", "color": "#d8b465", "description": ""})
    assert refused.status_code == 403
    assert "negozio" in refused.json()["detail"]
    assert client.get("/api/tags", headers=second).status_code == 403
    assert client.get(f"/api/tags/{tag_id}/players", headers=second).status_code == 403
    assert client.post(f"/api/tags/{tag_id}/players", headers=second,
                       json={"user_ids": [player]}).status_code == 403
    assert client.delete(f"/api/tags/{tag_id}", headers=second).status_code == 403

    # Chi l'ha creato lo ritrova aprendo il negozio, non prima.
    assert client.get("/api/tags", headers=first).status_code == 403


def test_opening_a_store_brings_along_the_tags_created_before(client, db_session):
    first = _register_user(client, "carry-a@example.com", role="organizer")
    second = _register_user(client, "carry-b@example.com", role="organizer")
    mine = _shared_space_tag(db_session, first, name="Habitue")
    _shared_space_tag(db_session, second, name="Commander")

    client.post("/api/organizations/mine", headers=first, json={"name": "Negozio A"})
    assert [t["name"] for t in client.get("/api/tags", headers=first).json()] == ["Habitue"]
    assert client.get(f"/api/tags/{mine}/players", headers=first).status_code == 200

    # Il negozio di un altro non si porta via i tag di nessuno.
    client.post("/api/organizations/mine", headers=second, json={"name": "Negozio B"})
    assert [t["name"] for t in client.get("/api/tags", headers=second).json()] == ["Commander"]


def _revisione(nome: str):
    """Il corpo di una revisione Alembic, per eseguirlo a mano su una connessione."""
    import importlib.util
    from pathlib import Path

    percorso = Path(__file__).resolve().parent.parent / "migrations" / "versions" / f"{nome}.py"
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_existing_tags_are_credited_to_whoever_first_assigned_them(db_session):
    """Prima non si scriveva chi creava un tag: la migrazione lo attribuisce a chi
    l'ha assegnato per primo, così se lo porta nel negozio che apre."""
    from datetime import datetime

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    from backend.app.db import engine

    # player_tags com'era prima della colonna created_by_id. Disegnata con
    # SQLAlchemy invece che con un CREATE TABLE scritto a mano: il tipo delle
    # date lo rende il dialetto, e questa prova deve valere anche su PostgreSQL,
    # dove "DATETIME" non esiste.
    prima = sa.MetaData()
    tag = sa.Table(
        "player_tags", prima,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("color", sa.String(9), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    assegnazioni = sa.Table(
        "player_tag_assignments", prima,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("tag_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("assigned_by_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    with engine.begin() as connection:
        prima.drop_all(connection, checkfirst=True)
        prima.create_all(connection)
        connection.execute(tag.insert(), [
            {"id": 1, "organization_id": 1, "name": "Nuovi", "color": "#d8b465",
             "description": "", "created_at": datetime(2026, 1, 1)},
            {"id": 2, "organization_id": 1, "name": "Mai usato", "color": "#d8b465",
             "description": "", "created_at": datetime(2026, 1, 1)},
        ])
        # Il primo per data e' il 7, non il primo per id: la migrazione deve
        # ordinare per created_at. Il 52 non ha autore e non deve vincere.
        connection.execute(assegnazioni.insert(), [
            {"id": 1, "tag_id": 1, "user_id": 50, "assigned_by_id": 8,
             "created_at": datetime(2026, 2, 1)},
            {"id": 2, "tag_id": 1, "user_id": 51, "assigned_by_id": 7,
             "created_at": datetime(2026, 1, 15)},
            {"id": 3, "tag_id": 1, "user_id": 52, "assigned_by_id": None,
             "created_at": datetime(2026, 1, 10)},
        ])

    # Due volte: `sync_alembic` la esegue una sola volta, ma una revisione che
    # riparte su un database già aggiornato non deve rompere niente.
    for _ in range(2):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _revisione("0006_tag_author").upgrade()

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, created_by_id FROM player_tags ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1, 7), (2, None)]
