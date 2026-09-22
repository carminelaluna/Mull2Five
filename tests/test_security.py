"""
test_security.py — Password, token e intestazioni di sicurezza.

Gli hash già salvati (fatti con passlib) restano validi con l'implementazione
della libreria standard; i token portano una versione che il cambio password e
"esci da tutti i dispositivi" fanno scadere; le pagine hanno la loro CSP.
"""
from backend.app.core.config import get_settings
from backend.app.models import User
from backend.app.security import (
    create_reset_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)

# Un hash fatto da passlib (pbkdf2_sha256, 29000 giri) prima di toglierla: finto, per il test.
PASSLIB_HASH = "$pbkdf2-sha256$29000$pHTuvZfSWkupFQKA8J6zVg$Z6qb35f/6bEBpeZHVeh7nDbyqV8Bz5u5TpXZOmkgfcc"


def _register(client, email="sec@example.com", password="supersecret123"):
    client.post("/api/auth/register", json={"email": email, "display_name": "Sec", "password": password})
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_passwords_hashed_by_passlib_still_work():
    assert verify_password("cavallo batteria graffetta", PASSLIB_HASH)
    assert not verify_password("cavallo batteria", PASSLIB_HASH)
    fresh = hash_password("una password nuova")
    assert fresh.startswith("$pbkdf2-sha256$") and verify_password("una password nuova", fresh)
    assert not verify_password("x", None) and not verify_password("x", "$md5$rotto")


def test_old_hashes_are_upgraded_at_login(client, db_session, monkeypatch):
    _register(client, "legacy@example.com")
    user = db_session.query(User).filter_by(email="legacy@example.com").one()
    user.password_hash = PASSLIB_HASH
    db_session.commit()
    monkeypatch.setattr(get_settings(), "password_hash_rounds", 50_000)
    assert password_needs_rehash(PASSLIB_HASH)

    login = client.post("/api/auth/login", json={"email": "legacy@example.com", "password": "cavallo batteria graffetta"})
    assert login.status_code == 200
    db_session.refresh(user)
    assert user.password_hash.startswith("$pbkdf2-sha256$50000$")
    assert verify_password("cavallo batteria graffetta", user.password_hash)


def test_refresh_and_logout_everywhere(client):
    token = _register(client)
    renewed = client.post("/api/auth/refresh", headers=_auth(token))
    assert renewed.status_code == 200
    fresh = renewed.json()["access_token"]
    assert client.get("/api/auth/me", headers=_auth(fresh)).status_code == 200

    assert client.post("/api/auth/logout-all", headers=_auth(fresh)).status_code == 200
    # Tutti i token emessi prima smettono di valere, anche quello appena rinnovato.
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(fresh)).status_code == 401
    again = client.post("/api/auth/login", json={"email": "sec@example.com", "password": "supersecret123"})
    assert client.get("/api/auth/me", headers=_auth(again.json()["access_token"])).status_code == 200


def test_a_reset_link_works_once_and_closes_old_sessions(client, db_session):
    token = _register(client, "reset@example.com")
    user = db_session.query(User).filter_by(email="reset@example.com").one()
    reset = create_reset_token(user)
    # Un token di reset non apre una sessione.
    assert client.get("/api/auth/me", headers=_auth(reset)).status_code == 401

    body = {"token": reset, "new_password": "nuovapassword123"}
    assert client.post("/api/auth/reset-password", json=body).status_code == 200
    assert client.post("/api/auth/reset-password", json={**body, "new_password": "altra-password-9"}).status_code == 400
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    login = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "nuovapassword123"})
    assert login.status_code == 200


def test_security_headers(client):
    page = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert page.headers["strict-transport-security"].startswith("max-age=")
    assert "content-security-policy" not in client.get("/docs").headers   # Swagger usa un CDN
    assert "strict-transport-security" not in client.get("/health").headers   # non su HTTP


def test_social_login_is_gone(client):
    assert client.get("/api/auth/oauth/google/login").status_code == 404
