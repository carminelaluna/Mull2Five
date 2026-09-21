"""
test_import.py — Iscritti da un file: lettura del CSV e import nel torneo.
"""
from datetime import date, timedelta

import pytest

from backend.app.services.player_import import parse_players_csv


def test_excel_in_italian_uses_semicolons_and_italian_headers():
    text = "﻿Nome;Email;ID editore;Pagato\nMario Rossi;mario@example.com;123;sì\nLuca;luca@example.com;;\n"
    players = parse_players_csv(text)
    assert [(p.name, p.email, p.publisher_id, p.paid) for p in players] == [
        ("Mario Rossi", "mario@example.com", "123", True),
        ("Luca", "luca@example.com", "", False),
    ]
    assert [p.line for p in players] == [2, 3]


def test_without_headers_the_email_column_is_found():
    players = parse_players_csv("Anna Bianchi,anna@example.com,999\nPiero,piero@example.com\n")
    assert [(p.name, p.email, p.publisher_id) for p in players] == [
        ("Anna Bianchi", "anna@example.com", "999"), ("Piero", "piero@example.com", ""),
    ]


def test_a_file_without_emails_is_refused():
    with pytest.raises(ValueError):
        parse_players_csv("nome,cognome\nMario,Rossi\n")


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, headers, capacity=3):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": "Torneo importato", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": capacity, "entry_fee_cents": 1000, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


CSV = """email,nome,pagato
gia@example.com,Già Iscritto,
nuovo1@example.com,Nuovo Uno,sì
non-una-email,Sbagliato,
nuovo2@example.com,Nuovo Due,
nuovo1@example.com,Doppione,
nuovo3@example.com,Nuovo Tre,
"""


def test_preview_then_import(client):
    org = _register_user(client, "import-org@example.com", role="organizer")
    tid = _tournament(client, org, capacity=3)
    player = _register_user(client, "gia@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""})

    preview = client.post(f"/api/tournaments/{tid}/import", headers=org, json={"csv_text": CSV})
    assert preview.status_code == 200, preview.text
    outcomes = [(r["email"], r["outcome"]) for r in preview.json()["rows"]]
    assert outcomes == [
        ("gia@example.com", "already"), ("nuovo1@example.com", "added"), ("non-una-email", "error"),
        ("nuovo2@example.com", "added"), ("nuovo1@example.com", "already"), ("nuovo3@example.com", "waitlisted"),
    ]
    # L'anteprima non tocca niente.
    assert len(client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()) == 1

    done = client.post(f"/api/tournaments/{tid}/import", headers=org,
                       json={"csv_text": CSV, "dry_run": False}).json()
    assert (done["added"], done["waitlisted"], done["skipped"]) == (2, 1, 3)
    regs = {r["player_email"]: r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()}
    assert regs["nuovo1@example.com"]["payment_status"] == "paid"      # segnato pagato nel file
    assert regs["nuovo2@example.com"]["payment_status"] != "paid"
    assert regs["nuovo3@example.com"]["waitlisted"] is True
    assert regs["nuovo2@example.com"]["player"]["display_name"] == "Nuovo Due"


def test_suspended_players_are_not_imported(client):
    org = _register_user(client, "import-org2@example.com", role="organizer")
    slug = client.post("/api/organizations/mine", headers=org, json={"name": "Negozio Import"}).json()["slug"]
    tid = _tournament(client, org)
    _register_user(client, "sospeso@example.com")
    client.post(f"/api/organizations/{slug}/suspensions", headers=org,
                json={"email": "sospeso@example.com", "reason": "Ripetute scorrettezze"})
    rows = client.post(f"/api/tournaments/{tid}/import", headers=org,
                       json={"csv_text": "sospeso@example.com", "dry_run": False}).json()["rows"]
    assert rows[0]["outcome"] == "error" and "Sospeso" in rows[0]["detail"]


def test_a_row_without_email_says_so(client):
    org = _register_user(client, "import-org4@example.com", role="organizer")
    tid = _tournament(client, org)
    rows = client.post(f"/api/tournaments/{tid}/import", headers=org,
                       json={"csv_text": "nome;email\nSenza Email;\nCon;con@example.com"}).json()["rows"]
    assert [(r["outcome"], r["detail"]) for r in rows] == [("error", "Manca l'email"), ("added", "")]


def test_only_the_organizer_imports(client):
    org = _register_user(client, "import-org3@example.com", role="organizer")
    tid = _tournament(client, org)
    other = _register_user(client, "import-other@example.com", role="organizer")
    assert client.post(f"/api/tournaments/{tid}/import", headers=other,
                       json={"csv_text": "x@example.com"}).status_code == 404
