"""
test_archive.py — L'archivio pubblico delle liste e il suo metagame.

In archivio vanno solo le liste dei tornei conclusi con classifica e liste
pubbliche; i filtri lavorano su formato, archetipo, carta (nome esatto),
periodo e posizione.
"""
from datetime import timedelta

import pytest

from backend.app.core.clock import local_today
from backend.app.routers import archive

BURN = "4 Lightning Bolt\n4 Lava Spike\n52 Mountain"
TRON = "4 Karn Liberated\n4 Expedition Map\n52 Wastes"
DELVER = "4 Delver of Secrets\n4 Brainstorm\n52 Island"
BURN_LEGACY = "4 Lightning Bolt\n4 Chain Lightning\n52 Mountain"


@pytest.fixture(autouse=True)
def _fresh_standings():
    # Ogni test ha un database nuovo: gli id dei tornei ripartono da 1.
    archive._standings_cache.clear()


def _organizer(client):
    client.post("/api/auth/register", json={
        "email": "archive-org@example.com", "display_name": "Archivio",
        "password": "supersecret123", "role": "organizer",
    })
    login = client.post("/api/auth/login", json={"email": "archive-org@example.com", "password": "supersecret123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _completed(client, org, name, fmt, winner, loser, *, days_ago=10, public=True):
    """Torneo concluso a due giocatori: chi ha la lista `winner` vince 2-0."""
    created = client.post("/api/tournaments", headers=org, json={
        "name": name, "format": fmt, "starts_on": str(local_today() - timedelta(days=days_ago)),
        "capacity": 8, "entry_fee_cents": 1000, "currency": "EUR", "status": "published", "pay_at_event": True,
        "decklist_required": False, "pairings_public": True, "standings_public": public, "decklists_public": public,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    for seat in ("A", "B"):
        walk_in = client.post(f"/api/tournaments/{tid}/walk-in", headers=org,
                              json={"display_name": f"{name} {seat}", "mark_paid": True})
        assert walk_in.status_code == 201, walk_in.text
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text
    pairing = next(p for p in started.json()["pairings"] if p["player_b"])
    ids = []
    for registration_id, (archetype, text) in ((pairing["player_a_registration_id"], winner),
                                               (pairing["player_b_registration_id"], loser)):
        sent = client.post(f"/api/tournaments/{tid}/registrations/{registration_id}/decklist", headers=org,
                           json={"raw_text": text, "archetype": archetype})
        ids.append(sent.json()["id"])
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result", headers=org,
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0})
    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200
    return tid, ids


def _search(client, **params):
    response = client.get("/api/decklists", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_only_public_completed_lists_and_the_filters(client):
    org = _organizer(client)
    _, july = _completed(client, org, "Modern di luglio", "Modern", ("Burn", BURN), ("Tron", TRON))
    _, hidden = _completed(client, org, "Modern privato", "Modern", ("Burn", BURN), ("Tron", TRON), public=False)
    _completed(client, org, "Legacy d'inverno", "Legacy", ("Delver", DELVER), ("Burn", BURN_LEGACY), days_ago=200)

    recent = _search(client)                                  # ultimi 90 giorni
    assert [(d["tournament_name"], d["position"], d["archetype"]) for d in recent["items"]] == [
        ("Modern di luglio", 1, "Burn"), ("Modern di luglio", 2, "Tron"),
    ]
    assert recent["items"][0]["players"] == 2 and recent["items"][0]["record"] == "1/0/0"

    assert _search(client, days=0)["total"] == 4                # il torneo privato non c'è mai
    assert {d["tournament_name"] for d in _search(client, days=0, format="legacy")["items"]} == {"Legacy d'inverno"}
    assert [d["tournament_name"] for d in _search(client, days=0, archetype="burn")["items"]] == [
        "Modern di luglio", "Legacy d'inverno"]
    assert _search(client, days=0, card="lightning bolt")["total"] == 2
    assert _search(client, days=0, card="Bolt")["total"] == 0    # il nome della carta è esatto
    assert [d["archetype"] for d in _search(client, days=0, top=1)["items"]] == ["Burn", "Delver"]

    detail = client.get(f"/api/decklists/{july[0]}").json()
    assert detail["raw_text"] == BURN and detail["position"] == 1
    assert client.get(f"/api/decklists/{hidden[0]}").status_code == 404


def test_metagame_shares_and_most_played_cards(client):
    org = _organizer(client)
    _completed(client, org, "Modern 1", "Modern", ("Burn", BURN), ("Tron", TRON))
    _completed(client, org, "Modern 2", "Modern", ("tron", TRON), ("Burn", BURN))
    _completed(client, org, "Legacy", "Legacy", ("Delver", DELVER), ("Burn", BURN_LEGACY))

    meta = client.get("/api/decklists/meta", params={"format": "Modern", "days": 0}).json()
    assert meta["total_lists"] == 4
    assert [(a["archetype"], a["lists"], a["share"], a["wins"]) for a in meta["archetypes"]] == [
        ("Burn", 2, 50.0, 1), ("Tron", 2, 50.0, 1),           # "tron" e "Tron" sono lo stesso archetipo
    ]
    cards = {c["name"]: c for c in meta["top_cards"]}
    assert (cards["Lightning Bolt"]["lists"], cards["Lightning Bolt"]["share"], cards["Lightning Bolt"]["copies"]) == (2, 50.0, 4.0)
    assert "Mountain" not in cards and "Wastes" not in cards   # le terre base non dicono niente
