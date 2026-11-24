"""
test_google_login.py — L'accesso con Google, con un Google finto.

Nessuna chiamata di rete: lo scambio del `code` restituisce un id_token firmato
qui con una chiave RSA dei test, e quella è la chiave pubblica "di Google". La
verifica che gira è quella vera: firma, `aud`, `iss`, scadenza, `nonce`, email
verificata.
"""
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.models import User, UserIdentity
from backend.app.security import create_reset_token
from backend.app.services import google_login

CLIENT_ID = "prova.apps.googleusercontent.com"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeGoogle:
    """Al prossimo scambio del `code` risponde con `next_token`."""

    def __init__(self) -> None:
        self.next_token = ""
        self.exchanged: list[str] = []

    def exchange(self, code: str) -> str:
        self.exchanged.append(code)
        return self.next_token


@pytest.fixture
def google(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "segreto-di-prova")
    fake = FakeGoogle()
    monkeypatch.setattr(google_login, "exchange_code", fake.exchange)
    monkeypatch.setattr(google_login, "_signing_key", lambda token: GOOGLE_KEY.public_key())
    return fake


def id_token(nonce, sub="google-1", email="mario@example.com", verified=True,
             key=GOOGLE_KEY, **overrides):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub,
              "email": email, "email_verified": verified, "name": "Mario Rossi",
              "iat": now, "exp": now + 3600, "nonce": nonce, **overrides}
    return jwt.encode(claims, key, algorithm="RS256")


def begin(client, next_page="", headers=None, path="/api/auth/google/start"):
    """Il primo passo: l'indirizzo di Google, da cui si leggono `state` e `nonce`."""
    response = client.post(path, json={"next": next_page}, headers=headers or {})
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"][0].endswith("/api/auth/google/callback")
    return query["state"][0], query["nonce"][0]


def come_back(client, google, state, token):
    """Google rimanda al callback; la risposta è il rimando a una pagina del sito."""
    google.next_token = token
    response = client.get("/api/auth/google/callback", params={"code": "codice", "state": state},
                          follow_redirects=False)
    assert response.status_code == 303, response.text
    location = urlparse(response.headers["location"])
    return location.path, {k: v[0] for k, v in parse_qs(location.query).items()}


def google_sign_in(client, google, **claims):
    state, nonce = begin(client)
    return come_back(client, google, state, id_token(nonce, **claims))


def register(client, email="mario@example.com", password="password-lunga"):
    response = client.post("/api/auth/register", json={
        "email": email, "display_name": "Mario Rossi", "password": password,
        "age_confirmed": True, "terms_accepted": True})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── Il bottone ────────────────────────────────────────────────────────────

def test_senza_credenziali_il_bottone_non_ce(client):
    assert client.get("/api/auth/rules").json()["google_login"] is False
    assert client.post("/api/auth/google/start", json={}).status_code == 503


def test_con_le_credenziali_il_bottone_ce(client, google):
    assert client.get("/api/auth/rules").json()["google_login"] is True


# ── Nuovo utente ──────────────────────────────────────────────────────────

def test_nuovo_utente_accetta_i_termini_e_poi_rientra(client, google, db_session):
    path, query = google_sign_in(client, google, sub="google-nuovo", email="Nuovo@Example.com")
    assert path == "/login.html" and query["google"] == "registrati"

    pending = client.post("/api/auth/google/finish").json()
    assert pending["access_token"] is None
    assert pending["signup_email"] == "nuovo@example.com"
    assert pending["signup_name"] == "Mario Rossi"

    # Termini ed età si accettano anche con Google.
    refused = client.post("/api/auth/google/complete", json={
        "display_name": "Mario Rossi", "age_confirmed": True, "terms_accepted": False})
    assert refused.status_code == 422
    refused = client.post("/api/auth/google/complete", json={
        "display_name": "Mario Rossi", "age_confirmed": None, "terms_accepted": True})
    assert refused.status_code == 422

    created = client.post("/api/auth/google/complete", json={
        "display_name": "Mario R.", "age_confirmed": True, "terms_accepted": True})
    assert created.status_code == 201, created.text
    me = client.get("/api/auth/me", headers=bearer(created.json()["access_token"])).json()
    assert me["email"] == "nuovo@example.com" and me["display_name"] == "Mario R."

    user = db_session.scalar(select(User).where(User.email == "nuovo@example.com"))
    assert user.password_hash is None and user.terms_accepted_at is not None
    identity = db_session.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id))
    assert (identity.provider, identity.subject) == ("google", "google-nuovo")

    # La seconda volta si entra e basta.
    path, query = google_sign_in(client, google, sub="google-nuovo", email="nuovo@example.com")
    assert query["google"] == "1"
    token = client.post("/api/auth/google/finish").json()
    assert token["linked_existing"] is False
    assert client.get("/api/auth/me", headers=bearer(token["access_token"])).json()["id"] == me["id"]


def test_il_token_si_ritira_una_volta_sola(client, google):
    register(client)
    google_sign_in(client, google)
    assert client.post("/api/auth/google/finish").json()["access_token"]
    assert client.post("/api/auth/google/finish").status_code == 400


def test_il_cookie_non_e_un_token_di_accesso(client, google):
    register(client)
    google_sign_in(client, google)
    cookie = client.cookies.get("m2f_google")
    assert cookie
    assert client.get("/api/auth/me", headers=bearer(cookie)).status_code == 401


# ── Unione con l'account che c'era ────────────────────────────────────────

def test_utente_con_password_viene_collegato_senza_doppioni(client, google, db_session):
    first = client.get("/api/auth/me", headers=register(client)).json()

    path, query = google_sign_in(client, google, sub="google-mario", email="MARIO@example.com")
    assert path == "/login.html" and query["google"] == "1"
    token = client.post("/api/auth/google/finish").json()
    assert token["linked_existing"] is True
    assert client.get("/api/auth/me", headers=bearer(token["access_token"])).json()["id"] == first["id"]

    assert db_session.scalar(select(func.count(User.id)).where(User.email == "mario@example.com")) == 1
    identity = db_session.scalar(select(UserIdentity).where(UserIdentity.user_id == first["id"]))
    assert identity.subject == "google-mario"
    # La password continua a valere.
    login = client.post("/api/auth/login", json={"email": "mario@example.com", "password": "password-lunga"})
    assert login.status_code == 200


def test_un_account_google_non_si_collega_a_due_utenti(client, google):
    google_sign_in(client, google, sub="google-mario", email="mario@example.com")
    client.post("/api/auth/google/complete", json={
        "display_name": "Mario Rossi", "age_confirmed": True, "terms_accepted": True})

    luigi = register(client, email="luigi@example.com")
    state, nonce = begin(client, headers=luigi, path="/api/auth/google/link")
    path, query = come_back(client, google, state, id_token(nonce, sub="google-mario"))
    assert path == "/my-registrations.html" and query["google_error"] == "gia_collegato"


def test_utente_disattivato_non_entra(client, google, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "mario@example.com"))
    user.is_active = False
    db_session.commit()
    _, query = google_sign_in(client, google)
    assert query["google_error"] == "disattivato"
    assert db_session.scalar(select(func.count(UserIdentity.id))) == 0


# ── Quello che si rifiuta ─────────────────────────────────────────────────

def test_email_non_verificata_rifiutata(client, google, db_session):
    register(client)
    _, query = google_sign_in(client, google, verified=False)
    assert query["google_error"] == "non_verificata"
    # Né collegata a chi c'era, né un account nuovo.
    assert db_session.scalar(select(func.count(UserIdentity.id))) == 0
    assert client.post("/api/auth/google/finish").status_code == 400


def test_state_sbagliato_rifiutato(client, google):
    register(client)
    _, nonce = begin(client)
    _, query = come_back(client, google, "uno-state-inventato", id_token(nonce))
    assert query["google_error"] == "stato"
    assert google.exchanged == []   # il code non si scambia nemmeno


def test_senza_cookie_lo_state_non_vale(client, google):
    register(client)
    state, nonce = begin(client)
    client.cookies.clear()   # il giro l'ha cominciato un altro browser
    _, query = come_back(client, google, state, id_token(nonce))
    assert query["google_error"] == "stato"


def test_nonce_sbagliato_rifiutato(client, google):
    register(client)
    state, _ = begin(client)
    _, query = come_back(client, google, state, id_token("un-nonce-di-un-altro-giro"))
    assert query["google_error"] == "stato"


@pytest.mark.parametrize("claims", [
    {"key": OTHER_KEY},                                   # firma non di Google
    {"aud": "un-altro-client.apps.googleusercontent.com"},
    {"iss": "https://accounts.example.com"},
    {"exp": int(time.time()) - 3600},
])
def test_id_token_non_valido_rifiutato(client, google, claims):
    register(client)
    _, query = google_sign_in(client, google, **claims)
    assert query["google_error"] == "rifiutato"


def test_annullato_su_google(client, google):
    state, _ = begin(client, next_page="event.html?id=3")
    response = client.get("/api/auth/google/callback", params={"error": "access_denied", "state": state},
                          follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["google_error"] == ["annullato"] and query["next"] == ["event.html?id=3"]


@pytest.mark.parametrize("next_page", ["https://altrove.example", "//altrove.example",
                                       "javascript:alert(1)", "/assoluto"])
def test_next_solo_relativo(client, google, next_page):
    register(client)
    state, nonce = begin(client, next_page=next_page)
    _, query = come_back(client, google, state, id_token(nonce))
    assert query["google"] == "1" and "next" not in query


# ── Dal profilo: collegare e scollegare ───────────────────────────────────

def test_collega_e_scollega_dal_profilo(client, google):
    headers = register(client)
    assert client.get("/api/auth/google/me", headers=headers).json() == {
        "available": True, "linked": False, "email": "", "has_password": True}

    # Si collega anche un account Google con un'altra email.
    state, nonce = begin(client, headers=headers, path="/api/auth/google/link")
    path, query = come_back(client, google, state,
                            id_token(nonce, sub="google-altro", email="mario.rossi@gmail.com"))
    assert path == "/my-registrations.html" and query["google"] == "collegato"
    status = client.get("/api/auth/google/me", headers=headers).json()
    assert status["linked"] is True and status["email"] == "mario.rossi@gmail.com"
    assert client.post("/api/auth/google/link", headers=headers).status_code == 409

    # Con Google si entra nello stesso account.
    google_sign_in(client, google, sub="google-altro", email="mario.rossi@gmail.com")
    token = client.post("/api/auth/google/finish").json()["access_token"]
    assert client.get("/api/auth/me", headers=bearer(token)).json()["email"] == "mario@example.com"

    unlinked = client.delete("/api/auth/google/me", headers=headers)
    assert unlinked.status_code == 200 and unlinked.json()["linked"] is False
    # Scollegato, quell'account Google non apre più questo account.
    _, query = google_sign_in(client, google, sub="google-altro", email="mario.rossi@gmail.com")
    assert query["google"] == "registrati"


def test_non_si_scollega_lultimo_modo_di_entrare(client, google, db_session):
    google_sign_in(client, google, sub="google-solo", email="solo@example.com")
    token = client.post("/api/auth/google/complete", json={
        "display_name": "Solo Google", "age_confirmed": True, "terms_accepted": True}).json()["access_token"]
    assert client.get("/api/auth/google/me", headers=bearer(token)).json()["has_password"] is False
    assert client.delete("/api/auth/google/me", headers=bearer(token)).status_code == 409

    # Con «Password dimenticata» la password arriva anche a chi è nato con Google.
    user = db_session.scalar(select(User).where(User.email == "solo@example.com"))
    reset = client.post("/api/auth/reset-password", json={
        "token": create_reset_token(user), "new_password": "nuova-password-lunga"})
    assert reset.status_code == 200
    login = client.post("/api/auth/login", json={"email": "solo@example.com",
                                                 "password": "nuova-password-lunga"})
    headers = bearer(login.json()["access_token"])
    assert client.delete("/api/auth/google/me", headers=headers).status_code == 200


def test_collegare_vale_solo_per_il_proprio_account(client, google):
    headers = register(client)
    response = client.post("/api/auth/google/link", headers={**headers, "X-Act-As": "999"})
    assert response.status_code in {400, 403}


def test_eliminare_laccount_toglie_anche_google(client, google, db_session):
    headers = register(client)
    google_sign_in(client, google, sub="google-mario")
    client.post("/api/auth/google/finish")
    export = client.get("/api/auth/me/export", headers=headers).json()
    assert export["linked_accounts"][0]["provider"] == "google"

    assert client.delete("/api/auth/me", headers=headers).status_code == 200
    assert db_session.scalar(select(func.count(UserIdentity.id))) == 0
    _, query = google_sign_in(client, google, sub="google-mario")
    assert query["google"] == "registrati"
