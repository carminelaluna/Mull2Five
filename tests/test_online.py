"""
test_online.py — Tornei online: piattaforma, nome in gioco e link della stanza.

Su MTG Arena gli avversari si cercano con l'Arena ID ("Nome#12345"): il torneo
lo chiede all'iscrizione e lo mostra all'avversario. Il link della stanza
(Discord, SpellTable) lo vedono solo gli iscritti e lo staff.
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


def _online(client, org, **extra):
    body = {
        "name": "Arena Cup", "format": "Standard", "starts_on": str(local_today() + timedelta(days=4)),
        "start_time": "21:00", "capacity": 16, "entry_fee_cents": 500, "currency": "EUR",
        "status": "published", "pay_at_event": True, "decklist_required": False, "pairings_public": True,
        "is_online": True, "online_platform": "arena", "online_link": "https://discord.gg/mull2five",
    }
    body.update(extra)
    return client.post("/api/tournaments", headers=org, json=body)


def test_an_online_tournament_asks_for_the_arena_id(client):
    org = _register_user(client, "online-org@example.com", role="organizer")
    created = _online(client, org)
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    assert (created.json()["is_online"], created.json()["online_platform"]) == (True, "arena")
    assert client.get(f"/api/tournaments/{tid}").json()["online_link"] == ""      # non è pubblico

    player = _register_user(client, "online-player@example.com")
    missing = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})
    assert missing.status_code == 422 and "Arena ID" in missing.json()["detail"]
    wrong = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"game_handle": "Mario"})
    assert wrong.status_code == 422 and "Nome#12345" in wrong.json()["detail"]

    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"game_handle": " Mario#12345 "})
    assert reg.status_code == 201, reg.text
    assert (reg.json()["game_handle"], reg.json()["online_link"]) == ("Mario#12345", "https://discord.gg/mull2five")
    mine = next(t for t in client.get("/api/tournaments/mine", headers=player).json() if t["id"] == tid)
    assert mine["online_link"] == "https://discord.gg/mull2five"
    assert client.get("/api/auth/me/handles", headers=player).json() == {"arena": "Mario#12345"}

    moved = client.put(f"/api/tournaments/{tid}/my-handle", headers=player, json={"game_handle": "Luigi#54321"})
    assert moved.status_code == 200 and moved.json()["game_handle"] == "Luigi#54321"


def test_online_rules_and_search(client):
    org = _register_user(client, "online-org2@example.com", role="organizer")
    assert _online(client, org, online_platform="xbox").status_code == 422
    assert _online(client, org, online_link="javascript:alert(1)").status_code == 422

    at_the_store = _online(client, org, name="Modern al negozio", is_online=False).json()
    assert (at_the_store["is_online"], at_the_store["online_platform"]) == (False, "")
    online = _online(client, org).json()
    found = client.get("/api/tournaments", params={"online": "true"}).json()
    assert [t["id"] for t in found] == [online["id"]]

    # Dalle impostazioni si passa al negozio: piattaforma e link se ne vanno.
    changed = client.patch(f"/api/tournaments/{online['id']}", headers=org, json={"is_online": False})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["is_online"], changed.json()["online_platform"]) == (False, "")


def test_opponents_see_each_others_names_in_game(client):
    org = _register_user(client, "online-org3@example.com", role="organizer")
    tid = _online(client, org).json()["id"]
    players = []
    for name, handle in (("anna", "Anna#11111"), ("bruno", "Bruno#22222")):
        headers = _register_user(client, f"online-{name}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers, json={"game_handle": handle}).json()
        client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid", headers=org)
        players.append(headers)
    assert client.post(f"/api/tournaments/{tid}/start", headers=org).status_code == 200

    pairing = client.get(f"/api/tournaments/{tid}/my-pairings", headers=players[0]).json()[0]["pairings"][0]
    assert {pairing["player_a_handle"], pairing["player_b_handle"]} == {"Anna#11111", "Bruno#22222"}
    # Negli abbinamenti che vedono tutti i nomi in gioco non compaiono.
    shared = client.get(f"/api/tournaments/{tid}/rounds", headers=players[1]).json()[0]["pairings"][0]
    assert shared["player_a_handle"] == "" and shared["player_b_handle"] == ""
