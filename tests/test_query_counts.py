"""
test_query_counts.py — Gli elenchi non devono fare una query per riga.

Si contano le query di una richiesta con pochi tornei e con molti: se il numero
cresce con i tornei, da qualche parte c'è un giro che interroga il database a
ogni elemento (N+1). Sul sito vero è la ricerca eventi, fino a 500 tornei.
"""
from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import event

from backend.app.db import engine
from backend.app.models import User, UserRole


def _login(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournaments(client, org, how_many, start=0):
    for i in range(start, start + how_many):
        created = client.post("/api/tournaments", headers=org, json={
            "name": f"Torneo {i}", "format": "Modern",
            "starts_on": str(date.today() + timedelta(days=3 + i)), "start_time": "20:00",
            "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
            "pay_at_event": True, "decklist_required": False,
        })
        assert created.status_code == 201, created.text


@contextmanager
def _counting():
    statements = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count)


def _queries(client, db_session, url, headers=None):
    # Nei test la sessione è una sola per tutte le richieste: senza svuotarla
    # gli oggetti già letti non costerebbero query, e il conto mentirebbe.
    db_session.expunge_all()
    with _counting() as statements:
        response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return len(statements), response.json()


def _grows(client, db_session, org, url, headers=None):
    _tournaments(client, org, 2)
    few, rows = _queries(client, db_session, url, headers)
    assert len(rows) >= 2
    _tournaments(client, org, 6, start=2)
    many, rows = _queries(client, db_session, url, headers)
    assert len(rows) >= 8
    return few, many


def test_public_search_does_not_query_per_tournament(client, db_session):
    org = _login(client, "conta-ricerca@example.com", role="organizer")
    few, many = _grows(client, db_session, org, "/api/tournaments")
    assert many == few, f"2 tornei: {few} query, 8 tornei: {many}"


def test_admin_tournament_list_does_not_load_every_registration(client, db_session):
    org = _login(client, "conta-org@example.com", role="organizer")
    admin = _login(client, "conta-admin@example.com")
    db_session.query(User).filter_by(email="conta-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    few, many = _grows(client, db_session, org, "/api/admin/tournaments", admin)
    assert many == few, f"2 tornei: {few} query, 8 tornei: {many}"


def test_admin_tournament_list_counts_registrations(client, db_session):
    org = _login(client, "conta-iscritti-org@example.com", role="organizer")
    admin = _login(client, "conta-iscritti-admin@example.com")
    db_session.query(User).filter_by(email="conta-iscritti-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    _tournaments(client, org, 1)
    tournament_id = client.get("/api/tournaments").json()[0]["id"]
    for n in range(3):
        player = _login(client, f"conta-iscritto-{n}@example.com")
        registered = client.post(f"/api/tournaments/{tournament_id}/registrations", headers=player, json={})
        assert registered.status_code == 201, registered.text
    row = next(t for t in client.get("/api/admin/tournaments", headers=admin).json() if t["id"] == tournament_id)
    assert row["registered_players"] == 3
