"""
test_decks.py — Regole di mazzo di Magic, legalità, liste salvate e ricerca carte.

Scryfall non si chiama mai davvero: httpx è sostituito da un finto Scryfall che
conosce solo le carte del test.
"""
from datetime import timedelta

import httpx
import pytest

from backend.app.core.clock import local_today
from backend.app.models import SavedDeck
from backend.app.services import decklists
from backend.app.services.decklists import parse_decklist, validate_card_legality, validate_decklist


@pytest.fixture(autouse=True)
def _fresh_card_cache():
    decklists._cards_cache.clear()
    decklists._search_cache.clear()


def _errors(text, fmt="Modern"):
    return validate_decklist(text, fmt).errors


# ── Regole del formato ─────────────────────────────────────────


def test_four_copies_across_main_and_sideboard():
    assert _errors("4 Lightning Bolt\n56 Mountain\n\nSideboard\n1 Lightning Bolt") == [
        "Lightning Bolt: 5 copie fra main e sideboard, al massimo 4.",
    ]
    assert _errors("4 Lightning Bolt\n56 Mountain\n\nSideboard\n4 Pyroblast") == []


def test_basics_and_any_number_cards_have_no_limit():
    assert _errors("30 Relentless Rats\n30 Swamp") == []
    assert _errors("24 Snow-Covered Island\n36 Shadowborn Apostle") == []
    assert _errors("7 Seven Dwarves\n53 Mountain") == []
    assert _errors("8 Seven Dwarves\n52 Mountain") == [
        "Seven Dwarves: 8 copie fra main e sideboard, al massimo 7.",
    ]


def test_limited_needs_forty_cards_and_no_copy_limit():
    assert validate_decklist("17 Island\n23 Creature", "Booster Draft").errors == []
    assert validate_decklist("6 Llanowar Elves\n16 Forest\n17 Bear", "Sealed").errors == [
        "Nel limited il mazzo deve contenere almeno 40 carte.",
    ]


def test_commander_is_singleton_with_exactly_100_cards():
    deck = "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n60 Forest\n38 Island"
    assert validate_decklist(deck, "Commander").errors == []
    doubled = deck.replace("1 Sol Ring", "2 Sol Ring").replace("38 Island", "37 Island")
    assert validate_decklist(doubled, "Commander").errors == ["Sol Ring: 2 copie nel mazzo, al massimo 1."]
    assert validate_decklist("1 Sol Ring\n60 Forest", "Commander").errors == [
        "Commander richiede esattamente 100 carte totali, comandante compreso.",
    ]


def test_arena_and_mtgo_exports_are_read():
    entries = parse_decklist(
        "Deck\n4 Lightning Bolt (2XM) 141\n4x Ragavan, Nimble Pilferer\n2 Fire//Ice\n\n"
        "Sideboard\n2 Pyroblast (ICE) 212 *F*\nSB: 1 Blood Moon"
    )
    assert [(e.section, e.quantity, e.name) for e in entries] == [
        ("main", 4, "Lightning Bolt"), ("main", 4, "Ragavan, Nimble Pilferer"), ("main", 2, "Fire // Ice"),
        ("side", 2, "Pyroblast"), ("side", 1, "Blood Moon"),
    ]


# ── Legalità (finto Scryfall) ──────────────────────────────────


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", decklists.SCRYFALL)
            raise httpx.HTTPStatusError("errore", request=request, response=httpx.Response(self.status_code))


def _card(name, **legalities):
    return {"name": name, "type_line": "Instant", "mana_cost": "{R}",
            "legalities": {"modern": "legal", "vintage": "legal", **legalities}}


def _fake_scryfall(monkeypatch, cards):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append([item["name"] for item in json["identifiers"]])
        known = {alias: card for card in cards for alias in decklists._names_of(card)}
        asked = [item["name"].lower() for item in json["identifiers"]]
        return _Response({
            "data": [known[name] for name in asked if name in known],
            "not_found": [{"name": name} for name in asked if name not in known],
        })

    monkeypatch.setattr(decklists.httpx, "post", fake_post)
    return calls


def test_banned_restricted_and_not_legal_cards(monkeypatch):
    _fake_scryfall(monkeypatch, [
        _card("Lightning Bolt"), _card("Mountain"),
        _card("Mental Misstep", modern="banned"),
        _card("Sol Ring", modern="not_legal", vintage="restricted"),
    ])
    deck = "4 Lightning Bolt\n1 Mental Misstep\n1 Sol Ring\n1 Carta Inventata\n53 Mountain"
    assert validate_card_legality(deck, "Modern") == [
        "Mental Misstep è bandita in Modern.",
        "Sol Ring non è legale in Modern.",
        "Carta non trovata: Carta Inventata",
    ]
    assert validate_card_legality("1 Sol Ring\n59 Mountain", "Vintage") == []
    assert validate_card_legality("2 Sol Ring\n58 Mountain", "Vintage") == [
        "Sol Ring è ristretta in Vintage: al massimo 1 copia.",
    ]


def test_big_lists_are_asked_in_batches_and_cached(monkeypatch):
    names = [f"Card {i}" for i in range(100)]
    calls = _fake_scryfall(monkeypatch, [_card(name) for name in names])
    text = "\n".join(f"1 {name}" for name in names)
    assert validate_card_legality(text, "Modern") == []
    assert [len(batch) for batch in calls] == [75, 25]
    validate_card_legality(text, "Modern")          # la seconda volta risponde la cache
    assert len(calls) == 2


def test_scryfall_down_and_formats_without_legality(monkeypatch):
    def down(*args, **kwargs):
        raise httpx.ConnectError("giù")

    monkeypatch.setattr(decklists.httpx, "post", down)
    assert validate_card_legality("4 Lightning Bolt", "Modern") == [
        "Validazione Scryfall non disponibile: riprova più tardi.",
    ]
    assert validate_card_legality("4 Lightning Bolt", "Booster Draft") == []   # niente da chiedere


# ── API ────────────────────────────────────────────────────────


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_saved_decks_belong_to_their_owner(client):
    player = _register_user(client, "deck-owner@example.com")
    body = {"name": "  Burn  ", "format": "Modern", "archetype": "Burn",
            "raw_text": "4 Lightning Bolt\n56 Mountain\n\nSideboard\n5 Lightning Bolt"}
    created = client.post("/api/decks", headers=player, json=body)
    assert created.status_code == 201, created.text
    deck = created.json()
    assert (deck["name"], deck["main_count"], deck["side_count"]) == ("Burn", 60, 5)
    assert deck["errors"] == ["Lightning Bolt: 9 copie fra main e sideboard, al massimo 4."]

    updated = client.put(f"/api/decks/{deck['id']}", headers=player,
                         json={**body, "raw_text": "4 Lightning Bolt\n56 Mountain"})
    assert updated.status_code == 200 and updated.json()["errors"] == []
    assert [d["name"] for d in client.get("/api/decks", headers=player).json()] == ["Burn"]

    other = _register_user(client, "deck-other@example.com")
    assert client.get("/api/decks", headers=other).json() == []
    assert client.put(f"/api/decks/{deck['id']}", headers=other, json={"name": "Mia"}).status_code == 404
    assert client.delete(f"/api/decks/{deck['id']}", headers=other).status_code == 404

    assert client.get("/api/auth/me/export", headers=player).json()["saved_decks"][0]["name"] == "Burn"
    assert client.delete(f"/api/decks/{deck['id']}", headers=player).status_code == 204
    assert client.get("/api/decks", headers=player).json() == []


def test_deleting_the_account_deletes_its_decks(client, db_session):
    player = _register_user(client, "deck-gone@example.com")
    client.post("/api/decks", headers=player, json={"name": "Burn", "raw_text": "4 Lightning Bolt"})
    assert client.delete("/api/auth/me", headers=player).status_code == 200
    assert db_session.query(SavedDeck).count() == 0


def test_validate_endpoint_checks_rules_and_legality(client, monkeypatch):
    _fake_scryfall(monkeypatch, [_card("Lightning Bolt"), _card("Mountain"), _card("Mental Misstep", modern="banned")])
    player = _register_user(client, "deck-check@example.com")
    body = {"raw_text": "4 Lightning Bolt\n1 Mental Misstep\n55 Mountain", "format": "Modern"}
    offline = client.post("/api/decks/validate", headers=player, json=body).json()
    assert offline == {"main_count": 60, "side_count": 0, "status": "valid", "errors": []}
    online = client.post("/api/decks/validate", headers=player, json={**body, "legality": True}).json()
    assert online["errors"] == ["Mental Misstep è bandita in Modern."]
    assert client.post("/api/decks/validate", json=body).status_code == 401


def test_card_search_and_lookup(client, monkeypatch):
    player = _register_user(client, "deck-search@example.com")
    asked = []

    def fake_get(url, params, headers, timeout):
        asked.append(params["q"])
        return _Response({"data": ["Lightning Bolt", "Lightning Helix"]})

    monkeypatch.setattr(decklists.httpx, "get", fake_get)
    assert client.get("/api/cards/search?q=light", headers=player).json() == {
        "names": ["Lightning Bolt", "Lightning Helix"]}
    client.get("/api/cards/search?q=LIGHT", headers=player)
    assert asked == ["light"]                               # la seconda risponde la cache
    assert client.get("/api/cards/search?q=l", headers=player).json() == {"names": []}
    assert client.get("/api/cards/search?q=light&game=lorcana", headers=player).status_code == 501

    _fake_scryfall(monkeypatch, [
        {"name": "Delver of Secrets // Insectile Aberration", "legalities": {},
         "type_line": "Creature — Human Wizard // Creature — Human Insect",
         "card_faces": [
             {"name": "Delver of Secrets", "mana_cost": "{U}", "type_line": "Creature — Human Wizard",
              "image_uris": {"normal": "https://img.example/delver.jpg"}},
             {"name": "Insectile Aberration", "mana_cost": "", "type_line": "Creature — Human Insect"},
         ]},
        _card("Lightning Bolt"),
    ])
    cards = client.post("/api/cards/lookup", headers=player,
                        json={"names": ["Delver of Secrets", "Lightning Bolt", "Nope"]}).json()
    assert [(c["name"], c["category"], c["mana_cost"], c["found"]) for c in cards] == [
        ("Delver of Secrets // Insectile Aberration", "creature", "{U}", True),
        ("Lightning Bolt", "instant", "{R}", True),
        ("Nope", "other", "", False),
    ]
    assert cards[0]["image"] == "https://img.example/delver.jpg"


def test_a_segment_list_follows_its_own_format(client):
    """In un evento misto la lista del draft si controlla come limited, non come Modern."""
    org = _register_user(client, "deck-seg-org@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Misto", "format": "Modern", "starts_on": str(local_today() + timedelta(days=5)),
        "capacity": 8, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "decklist_required": True, "pay_at_event": True,
    })
    tid = created.json()["id"]
    player = _register_user(client, "deck-seg-player@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={"wizards_account": ""})
    draft = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "17 Island\n23 Creature", "archetype": "Pool", "format": "Booster Draft"})
    assert draft.json()["status"] == "valid", draft.text
