"""
test_registration_qr.py — Il QR che porta all'iscrizione di un torneo.
"""
from datetime import timedelta

from backend.app.core.clock import local_today
from backend.app.services.registration_qr import qr_image, registration_url


def _organizer(client):
    client.post("/api/auth/register", json={
        "email": "qr-org@example.com", "display_name": "Negozio QR",
        "password": "supersecret123", "role": "organizer",
        "age_confirmed": True, "terms_accepted": True,
    })
    login = client.post("/api/auth/login", json={"email": "qr-org@example.com", "password": "supersecret123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Modern del venerdì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=5)), "start_time": "20:30",
        "capacity": 24, "entry_fee_cents": 800, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_il_qr_porta_alla_pagina_del_torneo_con_l_iscrizione_aperta(client, monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "site_url", "https://mull2five.it/")
    tid = _tournament(client, _organizer(client))
    url = f"https://mull2five.it/event.html?id={tid}&iscriviti=1"
    assert registration_url("https://mull2five.it/", tid) == url

    svg = client.get(f"/api/tournaments/{tid}/registration-qr.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    # Stesso indirizzo, stesso disegno: il QR codifica proprio quell'URL.
    assert svg.content == qr_image(url, "svg")

    png = client.get(f"/api/tournaments/{tid}/registration-qr.png?download=1")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert png.content == qr_image(url, "png")
    assert f'filename="iscrizione-torneo-{tid}.png"' in png.headers["content-disposition"]


def test_senza_accesso_e_solo_per_tornei_veri(client):
    tid = _tournament(client, _organizer(client))
    # Pubblico, come la pagina a cui porta.
    assert client.get(f"/api/tournaments/{tid}/registration-qr.svg").status_code == 200
    assert client.get(f"/api/tournaments/{tid}/registration-qr.gif").status_code == 404
    assert client.get("/api/tournaments/999999/registration-qr.svg").status_code == 404
