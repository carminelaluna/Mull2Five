"""
test_discovery.py — Ricerca eventi (tipo, REL, formati, periodo, distanza),
profili negozio, circuiti pubblici e tag giocatore.
"""
from datetime import date, timedelta

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
    from jose import jwt

    from backend.app.core.config import get_settings

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
    """Un negozio di default come lo lasciava un database di prima del rebrand."""
    from backend.app.models import Organization

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


def test_tag_lifecycle_and_bulk_assignment(client):
    org = _register_user(client, "tag-org@example.com", role="organizer")
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
    org = _register_user(client, "dup-tag@example.com", role="organizer")
    body = {"name": "Commander", "color": "#d8b465", "description": ""}
    assert client.post("/api/tags", headers=org, json=body).status_code == 201
    assert client.post("/api/tags", headers=org, json=body).status_code == 409


def test_players_cannot_touch_tags(client):
    org = _register_user(client, "owner-tag@example.com", role="organizer")
    tag = client.post("/api/tags", headers=org,
                      json={"name": "Riservato", "color": "#d8b465", "description": ""}).json()
    player = _register_user(client, "curious@example.com")

    assert client.get("/api/tags", headers=player).status_code == 403
    assert client.post(f"/api/tags/{tag['id']}/players", headers=player,
                       json={"user_ids": [1]}).status_code == 403


def test_tags_show_up_on_the_registration_list(client):
    org = _register_user(client, "reglist-org@example.com", role="organizer")
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


def test_tag_of_one_store_is_invisible_to_another(client, db_session):
    """L'etichetta vale dentro il negozio che l'ha creata."""
    from sqlalchemy import select

    from backend.app.models import Organization, User

    other = Organization(slug="altro-negozio", name="Altro Negozio")
    db_session.add(other)
    db_session.commit()

    mine = _register_user(client, "store-a@example.com", role="organizer")
    client.post("/api/tags", headers=mine, json={"name": "Solo mio", "color": "#d8b465",
                                                 "description": ""})

    theirs = _register_user(client, "store-b@example.com", role="organizer")
    rival = db_session.scalar(select(User).where(User.email == "store-b@example.com"))
    rival.organization_id = other.id
    db_session.commit()

    assert client.get("/api/tags", headers=theirs).json() == []
