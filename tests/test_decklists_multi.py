"""
test_decklists_multi.py — Una lista per segmento di formato.

Il caso normale resta una lista sola (format vuoto). In un evento misto ce n'è
una per porzione, e le due non si sovrascrivono a vicenda.
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


def _tournament_with_player(client):
    org = _register_user(client, "dl-org@example.com", role="organizer")
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Misto Open", "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=5)),
        "capacity": 8, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "decklist_required": True, "pay_at_event": True,
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    player = _register_user(client, "dl-player@example.com")
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player,
                      json={"wizards_account": "DL01"})
    assert reg.status_code == 201, reg.text
    return tid, org, player, reg.json()["id"]


def test_one_list_per_segment(client):
    tid, _, player, _ = _tournament_with_player(client)

    principale = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn",
    })
    assert principale.status_code == 200, principale.text
    assert principale.json()["format"] == ""

    draft = client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "17 Island\n23 Creature Pescata", "archetype": "Sealed pool",
        "format": "Booster Draft",
    })
    assert draft.status_code == 200, draft.text
    assert draft.json()["format"] == "Booster Draft"
    assert draft.json()["id"] != principale.json()["id"], "il segmento ha sovrascritto la principale"

    # Ognuna si rilegge per conto suo.
    letta = client.get(f"/api/tournaments/{tid}/decklist", headers=player).json()
    assert "Lightning Bolt" in letta["raw_text"]
    segmento = client.get(f"/api/tournaments/{tid}/decklist?format=Booster%20Draft",
                          headers=player).json()
    assert "Island" in segmento["raw_text"]


def test_resubmitting_a_segment_overwrites_only_that_one(client):
    tid, _, player, _ = _tournament_with_player(client)
    client.post(f"/api/tournaments/{tid}/decklist", headers=player,
                json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn"})
    client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "17 Island\n23 Creature", "archetype": "Pool", "format": "Booster Draft",
    })

    client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "17 Mountain\n23 Altra Creatura", "archetype": "Pool 2",
        "format": "Booster Draft",
    })

    assert "Lightning Bolt" in client.get(
        f"/api/tournaments/{tid}/decklist", headers=player).json()["raw_text"]
    aggiornata = client.get(f"/api/tournaments/{tid}/decklist?format=Booster%20Draft",
                            headers=player).json()
    assert "Mountain" in aggiornata["raw_text"]


def test_missing_segment_is_404_even_if_the_main_one_exists(client):
    tid, _, player, _ = _tournament_with_player(client)
    client.post(f"/api/tournaments/{tid}/decklist", headers=player,
                json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn"})

    assert client.get(f"/api/tournaments/{tid}/decklist", headers=player).status_code == 200
    assert client.get(f"/api/tournaments/{tid}/decklist?format=Legacy",
                      headers=player).status_code == 404


def test_staff_uploads_a_segment_for_a_player(client):
    """Il deck check al banco vale per il segmento giusto."""
    tid, org, player, reg_id = _tournament_with_player(client)
    caricata = client.post(f"/api/tournaments/{tid}/registrations/{reg_id}/decklist",
                           headers=org, json={
                               "raw_text": "17 Forest\n23 Bestia", "archetype": "Pool",
                               "format": "Booster Draft",
                           })
    assert caricata.status_code == 200, caricata.text
    assert caricata.json()["format"] == "Booster Draft"

    # La principale resta assente: caricare un segmento non ne inventa una.
    assert client.get(f"/api/tournaments/{tid}/decklist", headers=player).status_code == 404


def test_the_main_list_is_what_the_rest_of_the_app_reads(client):
    """Stato iscritto e vista organizzatore guardano ancora la lista principale."""
    tid, org, player, _ = _tournament_with_player(client)
    client.post(f"/api/tournaments/{tid}/decklist", headers=player, json={
        "raw_text": "17 Island\n23 Creature", "archetype": "Pool", "format": "Booster Draft",
    })
    # Solo un segmento: per l'app la lista principale manca ancora.
    assert client.get(f"/api/tournaments/{tid}/my-registration",
                      headers=player).json()["decklist_status"] == "missing"

    client.post(f"/api/tournaments/{tid}/decklist", headers=player,
                json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn"})
    assert client.get(f"/api/tournaments/{tid}/my-registration",
                      headers=player).json()["decklist_status"] != "missing"
    rows = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
    assert "Lightning Bolt" in rows[0]["decklist_raw_text"]
