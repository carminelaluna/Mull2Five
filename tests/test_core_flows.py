import os
import unittest
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_arcana_events.db"
os.environ["PAYMENT_SANDBOX_MOCK"] = "true"

from fastapi.testclient import TestClient

from backend.app.db import Base, engine
from backend.app.main import app


client = TestClient(app)


def auth(email: str, role: str = "player") -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": "password123",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_event(headers: dict[str, str], **overrides) -> int:
    payload = {
        "name": "Stable RCQ",
        "format": "Modern",
        "starts_on": "2026-06-01",
        "capacity": 16,
        "entry_fee_cents": 1000,
        "status": "published",
        "structure": "swiss_topcut",
        "swiss_rounds": 1,
        "top_cut_size": 2,
        "decklist_required": True,
        "decklist_deadline": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "pairings_public": True,
        "standings_public": True,
        "self_check_in_enabled": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def register_paid_player(tournament_id: int, headers: dict[str, str], suffix: str) -> int:
    response = client.post(
        f"/api/tournaments/{tournament_id}/registrations",
        headers=headers,
        json={"wizards_account": suffix},
    )
    assert response.status_code == 201, response.text
    registration_id = response.json()["id"]
    payment = client.post(
        f"/api/tournaments/{tournament_id}/checkout",
        headers=headers,
        json={"provider": "stripe"},
    )
    assert payment.status_code == 200, payment.text
    complete = client.post(f"/api/payments/sandbox/{payment.json()['id']}/complete")
    assert complete.status_code == 200, complete.text
    deck = "\n".join(
        [
            "4 Lightning Bolt",
            "4 Counterspell",
            "4 Island",
            "4 Mountain",
            "4 Opt",
            "4 Consider",
            "4 Ragavan, Nimble Pilferer",
            "4 Dragon's Rage Channeler",
            "4 Expressive Iteration",
            "4 Steam Vents",
            "4 Spirebluff Canal",
            "4 Polluted Delta",
            "4 Misty Rainforest",
            "4 Murktide Regent",
            "4 Unholy Heat",
            "",
            "Sideboard",
            "2 Blood Moon",
            "2 Spell Pierce",
        ]
    )
    deck_response = client.post(
        f"/api/tournaments/{tournament_id}/decklist",
        headers=headers,
        json={"raw_text": deck, "archetype": "Affinity"},
    )
    assert deck_response.status_code == 200, deck_response.text
    return registration_id


class CoreFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def test_topcut_advances_winners_and_creates_final(self) -> None:
        organizer = auth("org@example.com", "organizer")
        players = [auth(f"p{index}@example.com") for index in range(4)]
        tournament_id = create_event(organizer, top_cut_size=4)
        for index, player in enumerate(players):
            register_paid_player(tournament_id, player, str(index))

        round_one = client.post(f"/api/tournaments/{tournament_id}/start", headers=organizer).json()
        for pairing in round_one["pairings"]:
            result = client.patch(
                f"/api/tournaments/{tournament_id}/pairings/{pairing['id']}/result",
                headers=organizer,
                json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0},
            )
            self.assertEqual(result.status_code, 200, result.text)

        topcut = client.post(f"/api/tournaments/{tournament_id}/rounds", headers=organizer)
        self.assertEqual(topcut.status_code, 200, topcut.text)
        self.assertEqual(topcut.json()["phase"], "topcut")
        for pairing in topcut.json()["pairings"]:
            result = client.patch(
                f"/api/tournaments/{tournament_id}/pairings/{pairing['id']}/result",
                headers=organizer,
                json={"match_wins_a": 2, "match_wins_b": 1, "draws": 0},
            )
            self.assertEqual(result.status_code, 200, result.text)

        final = client.post(f"/api/tournaments/{tournament_id}/rounds", headers=organizer)
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(len(final.json()["pairings"]), 1)

    def test_manual_pairing_rejects_duplicate_players_and_tables(self) -> None:
        organizer = auth("org@example.com", "organizer")
        players = [auth(f"p{index}@example.com") for index in range(4)]
        tournament_id = create_event(organizer)
        registrations = [
            register_paid_player(tournament_id, player, str(index))
            for index, player in enumerate(players)
        ]
        round_one = client.post(f"/api/tournaments/{tournament_id}/start", headers=organizer).json()
        target = round_one["pairings"][0]
        duplicate = round_one["pairings"][1]

        response = client.patch(
            f"/api/tournaments/{tournament_id}/pairings/{target['id']}",
            headers=organizer,
            json={
                "table_number": duplicate["table_number"],
                "player_a_registration_id": target["player_a_registration_id"],
                "player_b_registration_id": target["player_b_registration_id"],
            },
        )
        self.assertEqual(response.status_code, 409)

        response = client.patch(
            f"/api/tournaments/{tournament_id}/pairings/{target['id']}",
            headers=organizer,
            json={
                "table_number": 99,
                "player_a_registration_id": duplicate["player_a_registration_id"],
                "player_b_registration_id": target["player_a_registration_id"],
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_refund_request_and_approval_in_sandbox(self) -> None:
        organizer = auth("org@example.com", "organizer")
        player = auth("player@example.com")
        tournament_id = create_event(organizer)
        register_paid_player(tournament_id, player, "player")
        registrations = client.get(
            f"/api/tournaments/{tournament_id}/registrations",
            headers=organizer,
        ).json()
        payment_id = registrations[0]["payment_id"]

        request = client.post(
            f"/api/tournaments/{tournament_id}/refund-request",
            headers=player,
            json={"reason": "Cannot attend"},
        )
        self.assertEqual(request.status_code, 200, request.text)
        self.assertEqual(request.json()["status"], "refund_requested")

        refund = client.post(
            f"/api/tournaments/{tournament_id}/payments/{payment_id}/refund",
            headers=organizer,
            json={"approve": True},
        )
        self.assertEqual(refund.status_code, 200, refund.text)
        self.assertEqual(refund.json()["status"], "refunded")


if __name__ == "__main__":
    unittest.main()
