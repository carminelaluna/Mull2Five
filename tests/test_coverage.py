"""
test_coverage.py — Metagame pubblico e correttezza del win rate.
"""
from datetime import date, timedelta


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make(client, headers, **overrides):
    payload = {
        "name": "Coverage Open", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=1)),
        "capacity": 16, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "decklist_required": False, "pairings_public": True, "standings_public": True,
        "pay_stripe": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _enroll(client, tid, email, archetype):
    """L'archetipo non si passa all'iscrizione: lo fissa l'invio della lista."""
    headers = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                      json={"wizards_account": email[:8]})
    assert reg.status_code == 201, reg.text
    checkout = client.post(f"/api/tournaments/{tid}/checkout", headers=headers,
                           json={"provider": "stripe"})
    client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")
    deck = client.post(f"/api/tournaments/{tid}/decklist", headers=headers, json={
        "raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": archetype,
    })
    assert deck.status_code == 200, deck.text
    return reg.json()["id"]


def _played_tournament(client, **overrides):
    """Due giocatori, un archetipo ciascuno, una partita decisa.

    Due soli giocatori perche cosi si sa chi ha vinto: con quattro l'abbinamento
    svizzero potrebbe mettere lo stesso archetipo ai due lati del tavolo e il
    test non direbbe piu niente sull'ordine dei campi.
    """
    org = _register_user(client, "cov-org@example.com", role="organizer")
    tid = _make(client, org, **overrides)
    _enroll(client, tid, "cov-a@example.com", "Murktide")
    _enroll(client, tid, "cov-b@example.com", "Burn")
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text

    pairing = started.json()["pairings"][0]
    client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result", headers=org,
                 json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0})
    # L'archetipo e il nome del giocatore: qui si risale a chi ha vinto.
    nomi = {"cov-a": "Murktide", "cov-b": "Burn"}
    vincente = nomi[pairing["player_a"]]
    perdente = nomi[pairing["player_b"]]
    return tid, org, vincente, perdente


def test_public_meta_needs_a_closed_tournament(client):
    tid, org, _, _ = _played_tournament(client)
    assert client.get(f"/api/tournaments/{tid}/public-meta").status_code == 404

    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200
    public = client.get(f"/api/tournaments/{tid}/public-meta")
    assert public.status_code == 200, public.text
    assert {row["archetype"] for row in public.json()} == {"Burn", "Murktide"}


def test_public_meta_follows_the_standings_switch(client):
    """Gli archetipi stanno già nella classifica pubblica: se quella è nascosta,
    non devono uscire da qui."""
    tid, org, _, _ = _played_tournament(client, standings_public=False)
    client.post(f"/api/tournaments/{tid}/close", headers=org)
    assert client.get(f"/api/tournaments/{tid}/public-meta").status_code == 404


def test_win_rate_counts_losses_not_draws(client):
    """Il record è "vittorie/sconfitte/pareggi": letto in altro ordine le
    sconfitte sparivano dal denominatore e il win rate saliva a 100%."""
    tid, org, arch_vince, arch_perde = _played_tournament(client)
    client.post(f"/api/tournaments/{tid}/close", headers=org)

    rows = {row["archetype"]: row for row in client.get(f"/api/tournaments/{tid}/public-meta").json()}
    vincente, perdente = rows[arch_vince], rows[arch_perde]

    assert (vincente["wins"], vincente["losses"], vincente["draws"]) == (1, 0, 0), vincente
    assert vincente["win_rate"] == 100.0
    assert (perdente["wins"], perdente["losses"], perdente["draws"]) == (0, 1, 0), perdente
    assert perdente["win_rate"] == 0.0


def test_meta_stats_stay_private_while_running(client):
    tid, org, _, _ = _played_tournament(client)
    player = _register_user(client, "cov-nosy@example.com")
    assert client.get(f"/api/tournaments/{tid}/meta-stats", headers=player).status_code == 403
    assert client.get(f"/api/tournaments/{tid}/meta-stats", headers=org).status_code == 200
