"""
test_saved_deck_to_tournament.py — Una lista di "Le mie liste" mandata a un torneo.

Dalla pagina del torneo la si sceglie già iscrivendosi, o dopo da iscritto: il
client manda il testo della lista salvata a POST /tournaments/{id}/decklist.
Due cose che la pagina dà per scontate:

- rileggendo l'iscrizione subito dopo, la lista c'è. `/my-registration` sta in
  cache dieci secondi, e l'invio non la svuotava: la pagina ricaricata diceva
  ancora "manca la lista";
- chi sceglie la lista e poi non paga online sparisce dal torneo, lista
  compresa, e può iscriversi di nuovo.
"""
from datetime import timedelta

import pytest

from backend.app.core import cache
from backend.app.core.clock import local_today

DECK = "4 Lightning Bolt\n4 Ragavan, Nimble Pilferer\n52 Mountain\n\nSideboard\n2 Blood Moon"


@pytest.fixture
def cache_accesa(monkeypatch):
    """La cache come con Redis: nei test non c'è, e senza è spenta del tutto.
    Basta il ripiego in memoria, che `cache_invalidate` svuota allo stesso modo."""
    monkeypatch.setattr(cache, "redis_is_real", lambda: True)
    cache.cache_invalidate("")
    yield
    cache.cache_invalidate("")


def _utente(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _torneo(client, org, **extra):
    corpo = {
        "name": "Modern del giovedì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=4)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "pay_stripe": True, "pay_paypal": True, "decklist_required": True,
    }
    corpo.update(extra)
    creato = client.post("/api/tournaments", headers=org, json=corpo)
    assert creato.status_code == 201, creato.text
    return creato.json()["id"]


def _lista_salvata(client, player):
    salvata = client.post("/api/decks", headers=player, json={
        "name": "Burn del giovedì", "format": "Modern", "archetype": "Burn", "raw_text": DECK,
    })
    assert salvata.status_code == 201, salvata.text
    return salvata.json()


def _invia(client, tid, player, deck):
    return client.post(f"/api/tournaments/{tid}/decklist", headers=player,
                       json={"raw_text": deck["raw_text"], "archetype": deck["archetype"], "format": ""})


def test_the_sent_list_shows_up_at_once(client, cache_accesa):
    org = _utente(client, "lista-subito-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "lista-subito@example.com")
    deck = _lista_salvata(client, player)
    assert client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                       json={"payment_method": "at_event"}).status_code == 201
    # La pagina del torneo ha appena letto l'iscrizione: ora è in cache.
    prima = client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()
    assert prima["decklist_status"] == "missing"
    # E il back-office ha appena letto gli iscritti.
    assert client.get(f"/api/tournaments/{tid}/registrations", headers=org).status_code == 200

    inviata = _invia(client, tid, player, deck)

    assert inviata.status_code == 200, inviata.text
    dopo = client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()
    assert dopo["decklist_status"] != "missing"
    assert dopo["decklist_formats"] == [""]
    assert dopo["archetype"] == "Burn"
    riga = next(r for r in client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
                if r["id"] == dopo["id"])
    assert riga["decklist_raw_text"] == DECK


def test_the_organizer_upload_shows_up_for_the_player_at_once(client, cache_accesa):
    org = _utente(client, "lista-org-carica@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "lista-org-carica-p@example.com")
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                      json={"payment_method": "at_event"}).json()
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()["decklist_status"] == "missing"

    caricata = client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/decklist", headers=org,
                           json={"raw_text": DECK, "archetype": "Burn"})

    assert caricata.status_code == 200, caricata.text
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()["decklist_status"] != "missing"


def test_an_unpaid_hold_goes_away_with_its_list(client):
    org = _utente(client, "lista-non-pagata-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "lista-non-pagata@example.com")
    deck = _lista_salvata(client, player)
    # Sceglie la lista nel modulo e paga online: la lista parte prima di andare a pagare.
    assert client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                       json={"payment_method": "paypal"}).status_code == 201
    assert _invia(client, tid, player, deck).status_code == 200

    tolto = client.post(f"/api/tournaments/{tid}/my-registration/abandon-payment", headers=player)

    assert tolto.json() == {"released": True}
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).status_code == 404
    assert client.get(f"/api/tournaments/{tid}/decklist", headers=player).status_code == 404
    # Riprova al banco: iscritto da capo, senza la lista di prima.
    di_nuovo = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                           json={"payment_method": "at_event"})
    assert di_nuovo.status_code == 201, di_nuovo.text
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()["decklist_status"] == "missing"
    # La lista salvata invece resta tra le sue.
    assert [d["name"] for d in client.get("/api/decks", headers=player).json()] == ["Burn del giovedì"]
