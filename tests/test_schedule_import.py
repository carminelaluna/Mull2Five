"""
test_schedule_import.py — Il calendario del negozio da un file.

EventLink non esporta il calendario: il negozio lo carica da un foglio di
calcolo, un torneo per riga. Prima l'anteprima riga per riga, poi i tornei;
ricaricare lo stesso file non crea doppioni.
"""
from datetime import date, timedelta

import pytest

from backend.app.models import Tournament
from backend.app.services.schedule_import import (
    guess_event_type,
    guess_format,
    parse_date,
    parse_fee,
    parse_schedule_csv,
    parse_time,
)


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _store(client, email="calendar-owner@example.com", name="Carte e Draghi"):
    owner = _register_user(client, email, role="organizer")
    slug = client.post("/api/organizations/mine", headers=owner, json={"name": name, "city": "Pavia"}).json()["slug"]
    return owner, slug


def _day(days):
    return (date.today() + timedelta(days=days)).strftime("%d/%m/%Y")


def _calendar():
    return "\n".join([
        "nome;data;ora;formato;quota;posti;tipo;descrizione",
        f"Friday Night Magic;{_day(4)};20:30;Standard;5;24;FNM;Premi in buste",
        f"Draft del sabato;{_day(5)};16.00;Booster Draft;18,00 €;16;;",
        f"FNM Modern;{_day(11)};20:30;;5;;;",                           # formato dal nome
        f"Prerelease di prova;{_day(12)};10:00;Sealed;30;;;",            # tipo dal nome
        f"Vecchio torneo;{_day(-2)};20:30;Standard;5;24;;",               # già passato
        f"Serata senza formato;{_day(6)};20:30;;0;;;",
        f"Friday Night Magic;{_day(4)};20:30;Standard;5;24;FNM;",         # riga ripetuta
    ])


@pytest.mark.parametrize(("text", "expected"), [
    ("2026-10-03", date(2026, 10, 3)), ("03/10/2026", date(2026, 10, 3)), ("3/10/26", date(2026, 10, 3)),
    ("03.10.2026", date(2026, 10, 3)), ("2026-10-03 00:00:00", date(2026, 10, 3)),
])
def test_dates_are_read_day_first(text, expected):
    assert parse_date(text) == expected


def test_times_fees_types_and_formats():
    assert [parse_time(t) for t in ("20:30", "20.30", "20", "8:30 PM", "")] == ["20:30", "20:30", "20:00", "20:30", None]
    assert [parse_fee(f) for f in ("5", "5,00", "€ 5.50", "18,00 €", "gratis", "")] == [500, 500, 550, 1800, 0, 0]
    assert guess_event_type("Pre-release Duskmourn") == "prerelease" and guess_event_type("FNM") == "locals"
    assert guess_format("FNM Modern", ("Standard", "Modern")) == "Modern"
    for bad in ("31/02/2026", "domani"):
        with pytest.raises(ValueError):
            parse_date(bad)
    with pytest.raises(ValueError):
        parse_time("25:00")


def test_the_file_needs_name_and_date_columns():
    with pytest.raises(ValueError):
        parse_schedule_csv("titolo;quando\nFNM;domani")
    # Anche in inglese e con le virgole, come esce da un foglio Google.
    rows = parse_schedule_csv(f"Event Name,Date,Start Time,Format,Entry Fee\nFNM,{_day(3)},7:30 PM,Pioneer,$5\n")
    assert (rows[0].name, rows[0].start_time, rows[0].format, rows[0].entry_fee_cents) == ("FNM", "19:30", "Pioneer", 500)


def test_preview_then_import_the_store_calendar(client, db_session):
    owner, slug = _store(client)
    body = {"csv_text": _calendar(), "capacity": 20}

    preview = client.post("/api/tournaments/import-schedule", headers=owner, json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    outcomes = [(r["line"], r["outcome"], r["detail"]) for r in plan["rows"]]
    assert outcomes == [
        (2, "new", ""), (3, "new", ""), (4, "new", ""), (5, "new", ""),
        (6, "error", "La data è già passata"), (7, "error", "Manca il formato"), (8, "already", "Già in calendario"),
    ]
    assert (plan["new"], plan["skipped"]) == (4, 3)
    assert db_session.query(Tournament).count() == 0          # l'anteprima non crea niente

    done = client.post("/api/tournaments/import-schedule", headers=owner, json={**body, "dry_run": False}).json()
    assert done["new"] == 4
    mine = {t["name"]: t for t in client.get("/api/tournaments/mine", headers=owner).json()}
    assert set(mine) == {"Friday Night Magic", "Draft del sabato", "FNM Modern", "Prerelease di prova"}
    fnm, draft, modern, pre = mine["Friday Night Magic"], mine["Draft del sabato"], mine["FNM Modern"], mine["Prerelease di prova"]
    assert (fnm["start_time"], fnm["entry_fee_cents"], fnm["capacity"], fnm["description"]) == ("20:30", 500, 24, "Premi in buste")
    assert (draft["format"], draft["start_time"], draft["entry_fee_cents"]) == ("Booster Draft", "16:00", 1800)
    assert (modern["format"], modern["capacity"]) == ("Modern", 20)    # posti dal default del dialog
    assert pre["event_type"] == "prerelease"
    assert all(t["status"] == "published" and not t["decklist_required"] and t["rules_enforcement_level"] == "Regular"
               for t in mine.values())
    assert {t["organization_slug"] for t in mine.values()} == {slug}

    # Lo stesso file un'altra volta: niente doppioni.
    again = client.post("/api/tournaments/import-schedule", headers=owner, json={**body, "dry_run": False}).json()
    assert again["new"] == 0 and db_session.query(Tournament).count() == 4


def test_drafts_and_locations(client):
    owner, slug = _store(client, "calendar-owner2@example.com", "Arcana")
    location = client.post(f"/api/organizations/{slug}/locations", headers=owner,
                           json={"name": "Sala grande", "address": "Via Roma 1", "city": "Pavia"}).json()
    csv_text = f"nome;data;formato\nCommander Night;{_day(3)};Commander\n"
    done = client.post("/api/tournaments/import-schedule", headers=owner, json={
        "csv_text": csv_text, "location_id": location["id"], "publish": False, "dry_run": False,
    }).json()
    assert done["new"] == 1
    [t] = client.get("/api/tournaments/mine", headers=owner).json()
    assert t["status"] == "draft" and t["start_time"] is None
    assert t["venue"] == "Sala grande, Via Roma 1, Pavia"          # il luogo arriva dalla sede

    # La sede di un altro negozio no.
    other, _ = _store(client, "calendar-owner3@example.com", "Dadi e Mana")
    refused = client.post("/api/tournaments/import-schedule", headers=other,
                          json={"csv_text": csv_text, "location_id": location["id"]})
    assert refused.status_code == 404


def test_only_organizers_and_readable_files(client):
    player = _register_user(client, "calendar-player@example.com")
    assert client.post("/api/tournaments/import-schedule", headers=player,
                       json={"csv_text": "nome;data\nFNM;01/01/2030"}).status_code == 403
    owner, _ = _store(client, "calendar-owner4@example.com", "Mana Store")
    wrong = client.post("/api/tournaments/import-schedule", headers=owner, json={"csv_text": "a;b\n1;2"})
    assert wrong.status_code == 422 and "nome e data" in wrong.json()["detail"]
