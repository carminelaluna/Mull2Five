"""
test_profiles_and_guests.py — Minori gestiti da un genitore, ospiti senza account, età minima.
"""
from datetime import timedelta

from backend.app.core.clock import local_today


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Pauper per ragazzi", "format": "Pauper",
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "16:00",
        "capacity": 16, "entry_fee_cents": 500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_minimum_age_at_signup(client):
    assert client.get("/api/auth/rules").json() == {"min_account_age": 14}
    refused = client.post("/api/auth/register", json={
        "email": "piccolo@example.com", "display_name": "Piccolo", "password": "supersecret123",
        "age_confirmed": False,
    })
    assert refused.status_code == 422 and "genitore" in refused.json()["detail"]


def _admin(client, db_session, email="prof-admin@example.com"):
    """Un admin: i profili dei minori li crea lui, su richiesta del genitore."""
    from backend.app.models import User, UserRole

    headers = _register_user(client, email, role="organizer")
    db_session.query(User).filter_by(email=email).one().role = UserRole.ADMIN
    db_session.commit()
    return headers


def _profilo(client, admin, genitore_email, nome):
    creato = client.post("/api/admin/profiles", headers=admin,
                         json={"guardian_email": genitore_email, "display_name": nome})
    assert creato.status_code == 201, creato.text
    return creato.json()


def test_a_parent_registers_and_follows_the_child(client, db_session):
    org = _register_user(client, "prof-org@example.com", role="organizer")
    tid = _tournament(client, org)
    parent = _register_user(client, "genitore@example.com")

    child = _profilo(client, _admin(client, db_session), "genitore@example.com", "Luca Rossi")
    assert [p["display_name"] for p in client.get("/api/auth/me/profiles", headers=parent).json()] == ["Luca Rossi"]

    as_child = {**parent, "X-Act-As": str(child["id"])}
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=as_child, json={"wizards_account": ""})
    assert reg.status_code == 201, reg.text
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=as_child).status_code == 200
    assert [t["id"] for t in client.get("/api/tournaments/mine", headers=as_child).json()] == [tid]
    # Il genitore, da sé, non è iscritto.
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=parent).status_code == 404

    row = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()[0]
    assert (row["player_kind"], row["guardian_name"], row["guardian_email"]) == (
        "profile", "genitore", "genitore@example.com")

    # Chi ha già giocato resta nello storico.
    assert client.delete(f"/api/auth/me/profiles/{child['id']}", headers=parent).status_code == 409
    export = client.get("/api/auth/me/export", headers=parent).json()
    assert export["managed_profiles"][0]["tournaments"] == [tid]


def test_only_the_parent_acts_for_the_child(client, db_session):
    parent = _register_user(client, "genitore2@example.com")
    admin = _admin(client, db_session, "prof-admin2@example.com")
    child = _profilo(client, admin, "genitore2@example.com", "Anna")
    stranger = _register_user(client, "estraneo@example.com")
    assert client.get("/api/auth/me", headers={**stranger, "X-Act-As": str(child["id"])}).status_code == 403
    # I profili li crea solo un admin: il genitore chiede, non si serve da solo.
    assert client.post("/api/admin/profiles", headers=parent,
                       json={"guardian_email": "genitore2@example.com",
                             "display_name": "Nipote"}).status_code == 403
    # Senza tornei giocati si può togliere.
    assert client.delete(f"/api/auth/me/profiles/{child['id']}", headers=parent).status_code == 204


def test_a_guest_plays_without_an_account(client):
    org = _register_user(client, "guest-org@example.com", role="organizer")
    tid = _tournament(client, org)
    walk_in = client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                          json={"display_name": "Ospite della serata"})
    assert walk_in.status_code == 201, walk_in.text
    assert walk_in.json()["player_kind"] == "guest"
    assert walk_in.json()["player_email"].endswith(".invalid")


def test_no_email_goes_to_invalid_addresses(monkeypatch):
    from backend.app.core.config import get_settings
    from backend.app.services import email

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")

    def refuse(*args, **kwargs):
        raise AssertionError("non deve connettersi")

    monkeypatch.setattr(email.smtplib, "SMTP", refuse)
    assert email.send_email("guest-1@guests.mull2five.invalid", "x", "y") is False
