"""
test_concurrency.py — Quando due richieste arrivano nello stesso istante.

Con gente vera succede: l'ultimo posto di un torneo atteso preso da due persone
insieme, un "Genera turno" premuto due volte. E alcune difese che valgono solo
fuori dal proprio computer: /metrics chiuso, SECRET_KEY non di default.
"""
import asyncio
import sqlite3
import threading

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.app.core.config import Settings, get_settings
from backend.app.db import engine, get_db
from backend.app.main import app, integrity_error_handler, is_duplicate
from backend.app.models import Registration, User, UserRole


def _register(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0], "password": "supersecret123",
        "role": role, "age_confirmed": True, "terms_accepted": True,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── L'ultimo posto ────────────────────────────────────────────────────────

@pytest.mark.skipif(engine.dialect.name != "postgresql",
                    reason="Il lock è un FOR UPDATE: SQLite non lo conosce e mette già in fila le scritture")
def test_two_players_racing_for_the_last_seat_do_not_both_get_in(client, monkeypatch):
    """Due iscrizioni all'ultimo posto nello stesso istante: entra una, l'altra
    va in lista d'attesa.

    Le due richieste si aspettano a vicenda subito dopo aver contato i posti.
    Senza lock arrivano lì tutte e due, contano un posto libero a testa ed
    entrano entrambe. Con il lock la seconda è ferma prima di contare: la prima
    aspetta invano, va avanti da sola, e la seconda conta i posti dopo di lei.
    """
    from backend.app.routers import tournament_registrations as router

    org = _register(client, "race-org@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Ultimo posto", "format": "Modern", "starts_on": "2027-06-01",
        "capacity": 2, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    first = client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                        json={"email": "race-seated@example.com", "display_name": "Seduto"})
    assert first.status_code == 201, first.text
    racers = [_register(client, f"race-{i}@example.com") for i in range(2)]

    meeting = threading.Barrier(2, timeout=3)
    original = router.check_not_suspended

    def wait_for_the_other(*args, **kwargs):
        try:
            meeting.wait()
        except threading.BrokenBarrierError:
            pass   # l'altra è ferma al lock: si va avanti da soli
        return original(*args, **kwargs)

    monkeypatch.setattr(router, "check_not_suspended", wait_for_the_other)
    # Una sessione per richiesta, come in produzione: quella condivisa della
    # fixture non regge due thread.
    app.dependency_overrides.pop(get_db, None)

    answers: list[int] = []

    def register(headers):
        response = TestClient(app).post(f"/api/tournaments/{tid}/registrations",
                                        headers=headers, json={})
        answers.append(response.status_code)

    threads = [threading.Thread(target=register, args=(h,)) for h in racers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert answers == [201, 201]
    with Session(engine) as db:
        active = db.scalar(select(func.count(Registration.id)).where(
            Registration.tournament_id == tid, Registration.waitlisted.is_(False)))
        waiting = db.scalar(select(func.count(Registration.id)).where(
            Registration.tournament_id == tid, Registration.waitlisted.is_(True)))
    assert (active, waiting) == (2, 1)


# ── Il doppio clic ────────────────────────────────────────────────────────

class _PgError(Exception):
    """L'errore di psycopg, con il suo codice."""

    def __init__(self, sqlstate: str):
        super().__init__(f"sqlstate {sqlstate}")
        self.sqlstate = sqlstate


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/x", "headers": [],
                    "query_string": b""})


def test_a_unique_violation_is_recognised_on_both_databases():
    assert is_duplicate(IntegrityError("INSERT", {}, _PgError("23505")))
    assert is_duplicate(IntegrityError(
        "INSERT", {}, sqlite3.IntegrityError("UNIQUE constraint failed: rounds.tournament_id, rounds.number")))
    assert not is_duplicate(IntegrityError("INSERT", {}, _PgError("23503")))   # chiave esterna
    assert not is_duplicate(IntegrityError(
        "INSERT", {}, sqlite3.IntegrityError("NOT NULL constraint failed: users.email")))


def test_a_duplicate_answers_409_and_a_real_fault_stays_500(monkeypatch):
    alerts = []
    monkeypatch.setattr("backend.app.main.send_alert", lambda *a, **k: alerts.append(a))

    doppio = asyncio.run(integrity_error_handler(_request(), IntegrityError("INSERT", {}, _PgError("23505"))))
    assert doppio.status_code == 409
    assert "due volte" in doppio.body.decode()
    assert alerts == []   # un doppio clic non è un guasto: niente Telegram

    guasto = asyncio.run(integrity_error_handler(_request(), IntegrityError("INSERT", {}, _PgError("23502"))))
    assert guasto.status_code == 500
    assert len(alerts) == 1


def test_a_duplicate_row_through_an_endpoint_is_a_409(client):
    """Dalla richiesta alla risposta: la seconda riga uguale non nasce, e chi
    ha cliccato legge cosa è successo invece di "Errore interno"."""

    def two_identical_users(db: Session = Depends(get_db)):
        for _ in range(2):
            db.add(User(email="doppio@example.com", display_name="Doppio",
                        role=UserRole.PLAYER, password_hash=None, is_active=True))
            db.flush()

    app.add_api_route("/api/__prova-doppio", two_identical_users, methods=["POST"])
    try:
        response = client.post("/api/__prova-doppio")
    finally:
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", "") != "/api/__prova-doppio"]
    assert response.status_code == 409, response.text
    assert "due volte" in response.json()["detail"]


# ── /metrics ──────────────────────────────────────────────────────────────

def test_metrics_are_closed_outside_a_local_machine_without_a_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "metrics_token", None)
    assert client.get("/metrics").status_code == 404


def test_metrics_open_only_with_the_right_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "metrics_token", "token-delle-metriche")
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"Authorization": "Bearer sbagliato"}).status_code == 403
    assert client.get("/metrics?token=sbagliato").status_code == 403
    ok = client.get("/metrics", headers={"Authorization": "Bearer token-delle-metriche"})
    assert ok.status_code == 200
    assert "mull2five_http_requests_total" in ok.text
    assert client.get("/metrics?token=token-delle-metriche").status_code == 200


# ── SECRET_KEY ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env", ["production", "staging", "prod"])
@pytest.mark.parametrize("key", ["dev-secret-change-me", "change-me-with-a-long-random-value"])
def test_a_public_secret_key_is_refused_online(env, key):
    assert Settings(app_env=env, secret_key=key).secret_key_problem()


@pytest.mark.parametrize("env", ["development", "test", "local"])
def test_the_default_secret_key_is_fine_on_your_own_computer(env):
    assert Settings(app_env=env, secret_key="dev-secret-change-me").secret_key_problem() is None


def test_a_real_secret_key_passes():
    assert Settings(app_env="production",
                    secret_key="y7Qe2vLk9Rt4Wm1Zp8Xc5Bn3Hd6Jf0Ga").secret_key_problem() is None


def test_the_deploy_stops_before_the_migrations_with_a_public_key(monkeypatch):
    from backend.app import prepara_database

    monkeypatch.setattr(prepara_database, "get_settings",
                        lambda: Settings(app_env="production", secret_key="dev-secret-change-me"))

    def must_not_run():
        raise AssertionError("le migrazioni non dovevano partire")

    monkeypatch.setattr(prepara_database, "create_all", must_not_run)
    assert prepara_database.main() == 1
