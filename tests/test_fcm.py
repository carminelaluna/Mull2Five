"""
test_fcm.py — Le notifiche dell'app all'istante, con Firebase.

Quello che conta: il telefono registrato è dell'account, anche quando il genitore
agisce per il figlio; si sveglia solo finché vale la sessione con cui si è
registrato; a Google non passa il testo della notifica; i token che Google
rifiuta se ne vanno. Google qui è finto (httpx.MockTransport), con una chiave
RSA fatta al momento.
"""
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.app.core.config import get_settings
from backend.app.models import DeviceToken, User, UserRole
from backend.app.services import fcm
from backend.app.services.inbox import notify

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _token(name: str) -> str:
    return f"{name}:APA91b" + "x" * 40


def _user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role})
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _id(db, email) -> int:
    return db.query(User).filter_by(email=email).one().id


def _devices(db) -> dict[str, int]:
    db.expire_all()
    return {d.token: d.user_id for d in db.query(DeviceToken).all()}


def _register(client, headers, token):
    response = client.post("/api/notifications/devices", headers=headers, json={"token": token})
    assert response.status_code == 204, response.text


@pytest.fixture(scope="module")
def keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    account = fcm.ServiceAccount(project_id="m2f-prova", client_email="fcm@m2f-prova.iam.gserviceaccount.com",
                                 private_key=pem, private_key_id="k1", token_uri=TOKEN_URI)
    return account, key.public_key()


class FakeGoogle:
    """Il servizio dei token d'accesso e FCM, quanto basta per vedere cosa gli arriva."""

    def __init__(self, public_key):
        self.public_key = public_key
        self.messages: list[dict] = []
        self.access_tokens = 0
        self.answers: dict[str, tuple[int, dict]] = {}
        self.expire_access = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            form = dict(httpx.QueryParams(request.content.decode()))
            claims = jwt.decode(form["assertion"], self.public_key, algorithms=["RS256"], audience=TOKEN_URI)
            assert claims["scope"] == fcm.SCOPE
            assert claims["iss"] == "fcm@m2f-prova.iam.gserviceaccount.com"
            self.access_tokens += 1
            return httpx.Response(200, json={"access_token": f"ya29.{self.access_tokens}", "expires_in": 3600})
        assert request.url.path == "/v1/projects/m2f-prova/messages:send"
        if self.expire_access:
            self.expire_access = False
            return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}})
        assert request.headers["Authorization"] == f"Bearer ya29.{self.access_tokens}"
        message = json.loads(request.content)["message"]
        self.messages.append(message)
        status, body = self.answers.get(message["token"], (200, {"name": "projects/m2f-prova/messages/1"}))
        return httpx.Response(status, json=body)


@pytest.fixture
def google(keys):
    account, public_key = keys
    fake = FakeGoogle(public_key)
    return fake, fcm.Sender(account, httpx.Client(transport=httpx.MockTransport(fake)))


def test_the_phone_belongs_to_the_account(client, db_session):
    parent = _user(client, "fcm-parent@example.com")
    admin = _user(client, "fcm-admin@example.com", role="organizer")
    db_session.query(User).filter_by(email="fcm-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    child = client.post("/api/admin/profiles", headers=admin, json={
        "guardian_email": "fcm-parent@example.com", "display_name": "Sara"}).json()
    other = _user(client, "fcm-other@example.com")
    parent_id, other_id = _id(db_session, "fcm-parent@example.com"), _id(db_session, "fcm-other@example.com")

    _register(client, parent, _token("a"))
    # Agendo per la figlia il telefono resta del genitore: la sua campanella mostra anche lei.
    _register(client, {**parent, "X-Act-As": str(child["id"])}, _token("b"))
    assert _devices(db_session) == {_token("a"): parent_id, _token("b"): parent_id}

    # Lo stesso telefono con un altro account passa a quello.
    _register(client, other, _token("a"))
    assert _devices(db_session)[_token("a")] == other_id
    # Dimenticarlo lo può solo chi ce l'ha adesso.
    client.post("/api/notifications/devices/forget", headers=parent, json={"token": _token("a")})
    assert _token("a") in _devices(db_session)
    client.post("/api/notifications/devices/forget", headers=other, json={"token": _token("a")})
    assert _devices(db_session) == {_token("b"): parent_id}

    export = client.get("/api/auth/me/export", headers=parent).json()
    assert [d["platform"] for d in export["devices"]] == ["android"]
    assert _token("b") not in json.dumps(export)

    assert client.post("/api/notifications/devices", headers=parent, json={"token": "corto"}).status_code == 422
    assert client.post("/api/notifications/devices", json={"token": _token("c")}).status_code == 401

    assert client.delete("/api/auth/me", headers=parent).status_code == 200
    assert _devices(db_session) == {}


def test_more_than_ten_phones_forget_the_oldest(client, db_session):
    player = _user(client, "fcm-many@example.com")
    for i in range(12):
        _register(client, player, _token(f"t{i:02d}"))
    assert sorted(_devices(db_session)) == [_token(f"t{i:02d}") for i in range(2, 12)]


def test_a_notification_wakes_the_phones_of_who_gets_it(client, db_session, monkeypatch):
    woken: list[list[int]] = []
    monkeypatch.setattr(fcm, "wake", lambda ids: woken.append(sorted(ids)))
    _user(client, "fcm-wake@example.com")
    player_id = _id(db_session, "fcm-wake@example.com")
    notify(db_session, [player_id, None, player_id], "started", context="Serata")
    assert woken == [[player_id]]


def test_without_firebase_nothing_is_sent(monkeypatch):
    submitted = []
    monkeypatch.setattr(fcm._executor, "submit", lambda *args: submitted.append(args))
    settings = get_settings()
    monkeypatch.setattr(settings, "fcm_service_account", None)
    fcm.wake([1, 2])
    monkeypatch.setattr(settings, "fcm_service_account", "{non è json")
    assert not fcm.enabled()
    fcm.wake([1, 2])
    assert submitted == []

    monkeypatch.setattr(settings, "fcm_service_account", json.dumps({
        "project_id": "m2f-prova", "client_email": "fcm@m2f-prova.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\n...", "private_key_id": "k1"}))
    fcm.wake([2, 1, 2])
    assert [args[1] for args in submitted] == [[1, 2]]


def test_google_gets_a_wake_up_without_the_text(client, db_session, google):
    fake, sender = google
    parent = _user(client, "fcm-wakeup-parent@example.com")
    admin = _user(client, "fcm-wakeup-admin@example.com", role="organizer")
    db_session.query(User).filter_by(email="fcm-wakeup-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    child = client.post("/api/admin/profiles", headers=admin, json={
        "guardian_email": "fcm-wakeup-parent@example.com", "display_name": "Marco"}).json()
    player = _user(client, "fcm-wakeup-player@example.com")
    _register(client, parent, _token("genitore"))
    _register(client, player, _token("giocatore"))

    # Una notifica per il figlio sveglia il telefono del genitore.
    assert fcm.deliver(db_session, [child["id"]], sender) == 1
    assert [m["token"] for m in fake.messages] == [_token("genitore")]
    message = fake.messages[0]
    assert message["data"] == {"campanella": "1"}
    assert "notification" not in message
    assert message["android"]["priority"] == "HIGH"

    assert fcm.deliver(db_session, [_id(db_session, "fcm-wakeup-player@example.com")], sender) == 1
    # Il token d'accesso si chiede una volta e si riusa.
    assert fake.access_tokens == 1


def test_logging_out_everywhere_stops_the_phone(client, db_session, google):
    fake, sender = google
    player = _user(client, "fcm-logout@example.com")
    _register(client, player, _token("vecchio"))
    assert client.post("/api/auth/logout-all", headers=player).status_code == 200

    assert fcm.deliver(db_session, [_id(db_session, "fcm-logout@example.com")], sender) == 0
    assert fake.messages == []
    assert _devices(db_session) == {}


def test_tokens_google_does_not_know_go_away(client, db_session, google):
    fake, sender = google
    player = _user(client, "fcm-gone@example.com")
    for name in ("buono", "disinstallato", "guasto"):
        _register(client, player, _token(name))
    fake.answers[_token("disinstallato")] = (404, {"error": {"status": "NOT_FOUND", "details": [
        {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}]}})
    fake.answers[_token("guasto")] = (503, {"error": {"status": "UNAVAILABLE"}})

    assert fcm.deliver(db_session, [_id(db_session, "fcm-gone@example.com")], sender) == 1
    # Il 503 è di Google, non del telefono: quel token resta.
    assert sorted(_devices(db_session)) == [_token("buono"), _token("guasto")]


def test_an_expired_access_token_is_renewed(client, db_session, google):
    fake, sender = google
    player = _user(client, "fcm-renew@example.com")
    _register(client, player, _token("rinnovo"))
    sender.access_token()
    fake.expire_access = True

    assert fcm.deliver(db_session, [_id(db_session, "fcm-renew@example.com")], sender) == 1
    assert fake.access_tokens == 2
