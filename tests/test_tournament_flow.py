"""
test_tournament_flow.py — Test del flusso torneo completo end-to-end (via API).

Copre il percorso critico dell'app:
  organizzatore crea torneo → giocatori si iscrivono e pagano →
  start → pairing Swiss → risultati → round successivo (no-rematch) →
  standings con tiebreaker → chiusura.
"""
import pytest


def _register_user(client, email, role="player", name=None):
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "display_name": name or email.split("@")[0],
            "password": "supersecret123",
            "role": role,
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "supersecret123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def tournament(client):
    """Torneo pubblicato con 8 giocatori iscritti e paganti."""
    org_headers = _register_user(client, "flow-org@example.com", role="organizer")

    response = client.post(
        "/api/tournaments",
        json={
            "name": "Flow Test Open",
            "format": "Modern",
            "starts_on": "2027-03-01",
            "capacity": 16,
            "entry_fee_cents": 1000,
            "currency": "EUR",
            "status": "published",
            "swiss_rounds": 3,
            "pairings_public": True,
            "standings_public": True,
            "decklist_required": False,
            "pay_stripe": True,
        },
        headers=org_headers,
    )
    assert response.status_code == 201, response.text
    tid = response.json()["id"]

    players = []
    for i in range(8):
        headers = _register_user(client, f"flow-p{i}@example.com")
        reg = client.post(
            f"/api/tournaments/{tid}/registrations",
            json={"wizards_account": f"0000000{i}"},
            headers=headers,
        )
        assert reg.status_code == 201, reg.text
        reg_id = reg.json()["id"]

        # Pagamento sandbox: crea checkout e completalo
        checkout = client.post(
            f"/api/tournaments/{tid}/checkout",
            json={"provider": "stripe"},
            headers=headers,
        )
        assert checkout.status_code == 200, checkout.text
        payment_id = checkout.json()["id"]
        complete = client.post(f"/api/payments/sandbox/{payment_id}/complete")
        assert complete.status_code == 200, complete.text

        players.append({"headers": headers, "registration_id": reg_id})

    return {"id": tid, "org": org_headers, "players": players}


def _report_all_results(client, tid, org_headers, round_data):
    """L'organizzatore inserisce 2-1 per il giocatore A su ogni tavolo."""
    for pairing in round_data["pairings"]:
        if not pairing["player_b"]:          # BYE: risultato automatico
            continue
        response = client.patch(
            f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
            json={"match_wins_a": 2, "match_wins_b": 1, "draws": 0},
            headers=org_headers,
        )
        assert response.status_code == 200, response.text


def test_full_swiss_flow(client, tournament):
    tid = tournament["id"]
    org = tournament["org"]

    # ── Start: genera il round 1 ──────────────────────────────
    response = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert response.status_code == 200, response.text
    round1 = response.json()
    assert round1["number"] == 1
    assert len(round1["pairings"]) == 4          # 8 giocatori → 4 tavoli, no BYE

    # Ogni giocatore appare esattamente una volta
    seen = []
    for pairing in round1["pairings"]:
        seen.append(pairing["player_a_registration_id"])
        seen.append(pairing["player_b_registration_id"])
    assert len(seen) == len(set(seen)) == 8

    # ── Round 2 bloccato finché mancano risultati ─────────────
    response = client.post(f"/api/tournaments/{tid}/rounds", headers=org)
    assert response.status_code == 409

    # ── Risultati round 1 → round 2 ───────────────────────────
    _report_all_results(client, tid, org, round1)
    response = client.post(f"/api/tournaments/{tid}/rounds", headers=org)
    assert response.status_code == 200, response.text
    round2 = response.json()
    assert round2["number"] == 2

    # No-rematch: nessuna coppia del round 1 si ripete nel round 2
    def pair_keys(round_data):
        return {
            tuple(sorted((p["player_a_registration_id"], p["player_b_registration_id"])))
            for p in round_data["pairings"]
            if p["player_b_registration_id"]
        }
    assert pair_keys(round1).isdisjoint(pair_keys(round2))

    # ── Standings: punteggi e ordinamento coerenti ────────────
    _report_all_results(client, tid, org, round2)
    response = client.get(f"/api/tournaments/{tid}/standings", headers=org)
    assert response.status_code == 200
    standings = response.json()
    assert len(standings) == 8

    points = [row["points"] for row in standings]
    assert points == sorted(points, reverse=True)      # ordinati per punti
    assert max(points) == 6                            # 2 vittorie da 3 punti
    assert [row["position"] for row in standings] == list(range(1, 9))

    # ── Vista giocatore: my-pairings e risultato bloccato ─────
    player = tournament["players"][0]
    response = client.get(f"/api/tournaments/{tid}/my-pairings", headers=player["headers"])
    assert response.status_code == 200
    my_rounds = response.json()
    assert len(my_rounds) == 2                         # presente in entrambi i round
    for rnd in my_rounds:
        assert len(rnd["pairings"]) == 1               # solo il proprio tavolo

    # Il risultato del round 1 è bloccato (esiste un round successivo)
    r1_pairing = my_rounds[0]["pairings"][0]
    response = client.patch(
        f"/api/tournaments/{tid}/pairings/{r1_pairing['id']}/result",
        json={"match_wins_a": 0, "match_wins_b": 2, "draws": 0},
        headers=org,
    )
    assert response.status_code == 409

    # ── Chiusura ──────────────────────────────────────────────
    response = client.post(f"/api/tournaments/{tid}/close", headers=org)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    # Le iscrizioni a torneo chiuso vengono rifiutate
    late = _register_user(client, "flow-late@example.com")
    response = client.post(
        f"/api/tournaments/{tid}/registrations",
        json={"wizards_account": "99999999"},
        headers=late,
    )
    assert response.status_code == 404


def test_player_result_confirm_flow(client, tournament):
    """Giocatore A propone il risultato, B lo conferma → diventa definitivo."""
    tid = tournament["id"]
    org = tournament["org"]

    response = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert response.status_code == 200
    pairing = next(p for p in response.json()["pairings"] if p["player_b"])

    by_reg = {p["registration_id"]: p for p in tournament["players"]}
    player_a = by_reg[pairing["player_a_registration_id"]]
    player_b = by_reg[pairing["player_b_registration_id"]]

    # A invia 2-0
    response = client.patch(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result",
        json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0},
        headers=player_a["headers"],
    )
    assert response.status_code == 200, response.text

    # A non può confermare il proprio risultato
    response = client.post(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result/confirm",
        headers=player_a["headers"],
    )
    assert response.status_code == 409

    # B conferma → risultato definitivo
    response = client.post(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result/confirm",
        headers=player_b["headers"],
    )
    assert response.status_code == 200
    final = next(p for p in response.json()["pairings"] if p["id"] == pairing["id"])
    assert final["result"] == "A"
    assert final["match_wins_a"] == 2

    # Nessuno può più cambiare un risultato definitivo
    response = client.patch(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/player-result",
        json={"match_wins_a": 0, "match_wins_b": 2, "draws": 0},
        headers=player_b["headers"],
    )
    assert response.status_code == 409


def test_capacity_limit(client):
    """Le iscrizioni oltre la capienza finiscono in lista d'attesa."""
    org = _register_user(client, "cap-org@example.com", role="organizer")
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Capacity Test",
            "format": "Standard",
            "starts_on": "2027-04-01",
            "capacity": 2,
            "entry_fee_cents": 0,
            "currency": "EUR",
            "status": "published",
        },
        headers=org,
    )
    tid = response.json()["id"]

    for i in range(2):
        headers = _register_user(client, f"cap-p{i}@example.com")
        response = client.post(
            f"/api/tournaments/{tid}/registrations",
            json={"wizards_account": f"1111111{i}"},
            headers=headers,
        )
        assert response.status_code == 201

    # Il terzo iscritto su capienza 2 va in lista d'attesa
    overflow = _register_user(client, "cap-overflow@example.com")
    response = client.post(
        f"/api/tournaments/{tid}/registrations",
        json={"wizards_account": "22222222"},
        headers=overflow,
    )
    assert response.status_code == 201
    assert response.json()["waitlisted"] is True

    # Un iscritto attivo fa drop → il waitlisted viene promosso
    first = client.post(
        "/api/auth/login",
        json={"email": "cap-p0@example.com", "password": "supersecret123"},
    )
    first_headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    response = client.post(f"/api/tournaments/{tid}/my-registration/drop", headers=first_headers)
    assert response.status_code == 200
    assert response.json()["dropped"] is True

    response = client.get(f"/api/tournaments/{tid}/my-registration", headers=overflow)
    assert response.status_code == 200
    assert response.json()["waitlisted"] is False   # promosso dalla waitlist
