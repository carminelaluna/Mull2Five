"""
test_wizards_locator.py — I tornei vetrina importati dal Wizards Event Locator.

Il Locator risponde in turbo-stream (Remix): qui le risposte sono costruite a
mano con dati inventati, e nessuna richiesta esce dal test. L'importazione è
spenta di default; i negozi entrano senza email né telefono.
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.core.config import get_settings
from backend.app.models import Organization, Tournament, TournamentStatus, User, UserRole
from backend.app.services import wizards_locator


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _admin(client, db_session, email="locator-admin@example.com"):
    headers = _register_user(client, email, role="organizer")
    user = db_session.query(User).filter_by(email=email).one()
    user.role = UserRole.ADMIN
    db_session.commit()
    return headers


def turbo_stream(value) -> str:
    """Codifica un oggetto come fa turbo-stream: un array piatto di riferimenti."""
    flat: list = []

    def put(item):
        if item is None:
            return -5
        index = len(flat)
        flat.append(None)
        if isinstance(item, dict):
            obj = {}
            for key, val in item.items():
                flat.append(key)
                key_ref = f"_{len(flat) - 1}"
                obj[key_ref] = put(val)
            flat[index] = obj
        elif isinstance(item, list):
            flat[index] = [put(x) for x in item]
        else:
            flat[index] = item
        return index

    put(value)
    return json.dumps(flat) + "\n"


def _start(days):
    return f"{(date.today() + timedelta(days=days)).isoformat()}T18:30:00.0000000Z"


def _event(event_id, days, *, store_id="st-1", title="Friday Night Magic", fmt="Standard", **extra):
    event = {
        "id": event_id, "title": title, "status": "SCHEDULED", "capacity": 16,
        "description": "Evento di prova.", "isOnline": False,
        "latitude": 45.46, "longitude": 9.19,
        "pairingType": "SWISS", "requiredTeamSize": 1, "rulesEnforcementLevel": "REGULAR",
        "scheduledStartTime": _start(days), "timeZone": "Europe/Rome",
        "tags": ["magic:_the_gathering", "standard"],
        "entryFee": {"amount": 500, "currency": "EUR"},
        "eventFormat": {"name": fmt},
        "emailAddress": "organizzatore@example.invalid",
        "organization": {
            "id": store_id, "name": "Negozio di Prova", "isPremium": True,
            "website": "https://negozio.example.invalid", "phoneNumber": "+39 000 0000000",
            "emailAddress": "titolare@example.invalid",
            "address": "Via dei Test 1", "city": "Milano", "postalCode": "20100",
        },
    }
    event.update(extra)
    return event


def _page(events, total=None):
    return turbo_stream({"routes/($lang).search": {"data": {"events": {"advancedSearchEvents": {
        "events": events, "pageInfo": {"page": 1, "pageSize": 100, "totalResults": len(events) if total is None else total},
    }}}}})


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def locator(monkeypatch):
    """Il Locator acceso e finto: `pages` sono le risposte, `calls` le richieste fatte."""
    monkeypatch.setattr(get_settings(), "wizards_locator_enabled", True)
    monkeypatch.setattr(wizards_locator, "PAUSE_SECONDS", 0)
    state = {"pages": [], "calls": []}

    def fake_get(url, **kwargs):
        state["calls"].append((url, kwargs["params"]))
        return FakeResponse(state["pages"][len(state["calls"]) - 1])

    monkeypatch.setattr(wizards_locator.httpx, "get", fake_get)
    return state


def test_decode_turbo_stream():
    # Riferimenti, costanti negative e valori tipizzati (una data) come nelle risposte vere.
    raw = '[{"_1":2,"_3":4,"_5":6},"a",[7,-5],"b",["D",1700000000000],"c",{"_1":7},"x"]\n[]\n'
    assert wizards_locator.decode_turbo_stream(raw) == {"a": ["x", None], "b": 1700000000000, "c": {"a": "x"}}
    data = {"one": [1, 2.5, None, True], "two": {"nested": "ok"}}
    assert wizards_locator.decode_turbo_stream(turbo_stream(data)) == data


def test_fetch_events_reads_every_page(locator):
    first = [_event(f"e{i}", 3) for i in range(100)]
    locator["pages"] = [_page(first, total=130), _page([_event("e100", 4)], total=130)]
    events = wizards_locator.fetch_events("Milano", 30, max_pages=5)
    assert len(events) == 101 and len(locator["calls"]) == 2
    url, params = locator["calls"][1]
    assert url == "https://locator.wizards.com/search.data"
    assert (params["query"], params["distance"], params["page"], params["searchType"]) == ("Milano", 30, 2, "magic-events")


def test_the_admin_imports_showcase_tournaments(client, db_session, locator):
    admin = _admin(client, db_session)
    locator["pages"] = [_page([
        _event("ev-1", 5),
        _event("ev-2", 9, title="Draft del sabato", fmt="Booster Draft", tags=["magic:_the_gathering", "booster_draft"]),
        _event("ev-old", -3),                     # già passato
        _event("ev-cancelled", 6, status="CANCELLED"),
    ])]
    report = client.post("/api/admin/wizards-locator/import", headers=admin, json={"city": "Milano", "distance_km": 30})
    assert report.status_code == 200, report.text
    assert report.json() == {"fetched": 4, "created": 2, "updated": 0, "cancelled": 0, "skipped": 2, "stores_created": 1}

    fnm = db_session.query(Tournament).filter_by(external_id="ev-1").one()
    draft = db_session.query(Tournament).filter_by(external_id="ev-2").one()
    local = datetime.fromisoformat(_start(5)[:19] + "+00:00").astimezone(ZoneInfo("Europe/Rome"))
    assert (fnm.starts_on, fnm.start_time) == (local.date(), local.strftime("%H:%M"))   # l'ora di Roma, non UTC
    assert (draft.format, fnm.format, fnm.entry_fee_cents, fnm.capacity) == ("Draft", "Standard", 500, 16)
    assert fnm.registration_mode == "closed" and fnm.status == TournamentStatus.PUBLISHED

    detail = client.get(f"/api/tournaments/{fnm.id}").json()
    assert detail["source"] == "wizards"
    assert detail["external_url"].startswith("https://locator.wizards.com/search?") and "eventId=ev-1" in detail["external_url"]
    assert detail["organization_name"] == "Negozio di Prova"
    assert detail["venue"] == "Negozio di Prova, Via dei Test 1, 20100 Milano"

    # Il negozio entra senza contatti personali: niente email né telefono.
    store = db_session.query(Organization).filter_by(source="wizards", external_id="st-1").one()
    assert store.is_premium and store.website == "https://negozio.example.invalid"
    stored = " ".join(str(v) for obj in (store, fnm, draft) for v in vars(obj).values())
    assert "titolare@" not in stored and "organizzatore@" not in stored and "+39 000" not in stored

    # Ci si iscrive presso il negozio, non qui.
    player = _register_user(client, "locator-player@example.com")
    assert client.post(f"/api/tournaments/{fnm.id}/registrations", headers=player, json={}).status_code >= 400

    status = client.get("/api/admin/wizards-locator", headers=admin).json()
    assert status == {"enabled": True, "imported_tournaments": 2, "imported_stores": 1}


def test_a_new_import_updates_and_cancels(client, db_session, locator):
    admin = _admin(client, db_session)
    locator["pages"] = [
        _page([_event("ev-1", 5), _event("ev-2", 9)]),
        _page([_event("ev-1", 5, title="FNM — Modern", capacity=24), _event("ev-1", 5)]),   # ev-2 sparito
    ]
    client.post("/api/admin/wizards-locator/import", headers=admin, json={"city": "Milano"})
    report = client.post("/api/admin/wizards-locator/import", headers=admin, json={"city": "Milano"}).json()
    assert (report["created"], report["updated"], report["cancelled"], report["stores_created"]) == (0, 1, 1, 0)

    assert db_session.query(Tournament).filter_by(source="wizards").count() == 2
    fnm = db_session.query(Tournament).filter_by(external_id="ev-1").one()
    assert (fnm.name, fnm.capacity) == ("FNM — Modern", 24)
    assert db_session.query(Tournament).filter_by(external_id="ev-2").one().status == TournamentStatus.CANCELLED


def test_the_import_is_off_by_default_and_admin_only(client, db_session):
    admin = _admin(client, db_session)
    assert client.get("/api/admin/wizards-locator", headers=admin).json()["enabled"] is False
    assert client.post("/api/admin/wizards-locator/import", headers=admin, json={"city": "Milano"}).status_code == 409

    organizer = _register_user(client, "locator-organizer@example.com", role="organizer")
    assert client.post("/api/admin/wizards-locator/import", headers=organizer, json={"city": "Milano"}).status_code == 403
    assert client.get("/api/admin/wizards-locator").status_code == 401


def test_only_real_store_sites_are_kept():
    assert not wizards_locator._generic_site("https://negozio.example.invalid")
    assert wizards_locator._generic_site("https://magic.wizards.com/it/products")   # una pagina di Wizards
    assert wizards_locator._generic_site("javascript:alert(1)")                      # finirebbe in un href
    assert wizards_locator._generic_site("")
