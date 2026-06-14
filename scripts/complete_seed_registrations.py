from datetime import UTC, datetime
import sys

from backend.app.db import SessionLocal, create_all
from backend.app.models import Decklist, DecklistStatus, Payment, PaymentStatus, Registration, Tournament, User
from backend.app.services.decklists import validate_decklist


DECKLIST = """4 Lightning Bolt
4 Counterspell
4 Island
4 Mountain
4 Opt
4 Consider
4 Ragavan, Nimble Pilferer
4 Dragon's Rage Channeler
4 Expressive Iteration
4 Steam Vents
4 Spirebluff Canal
4 Polluted Delta
4 Misty Rainforest
4 Murktide Regent
4 Unholy Heat

Sideboard
2 Blood Moon
2 Spell Pierce
2 Mystical Dispute
2 Unlicensed Hearse
2 Engineered Explosives
2 Flusterstorm
3 Surgical Extraction
"""


def main() -> None:
    tournament_name = sys.argv[1] if len(sys.argv) > 1 else "THE GAME"
    create_all()
    paid = 0
    decklists = 0

    with SessionLocal() as db:
        tournament = db.query(Tournament).filter(Tournament.name == tournament_name).one_or_none()
        if not tournament:
            raise SystemExit(f"Torneo non trovato: {tournament_name}")

        validation = validate_decklist(DECKLIST, tournament.format)
        status = DecklistStatus.INVALID if validation.errors else DecklistStatus.VALID
        registrations = (
            db.query(Registration)
            .join(User)
            .filter(Registration.tournament_id == tournament.id, User.email.like("%@test.it"))
            .all()
        )
        for registration in registrations:
            registration.archetype = "Affinity"
            if registration.payment:
                registration.payment.status = PaymentStatus.PAID
                registration.payment.paid_at = registration.payment.paid_at or datetime.now(UTC)
            else:
                db.add(
                    Payment(
                        registration_id=registration.id,
                        provider="sandbox",
                        status=PaymentStatus.PAID,
                        amount_cents=tournament.entry_fee_cents,
                        currency=tournament.currency,
                        provider_checkout_id=f"seed-{registration.id}",
                        provider_payment_id=f"seed-{registration.id}-paid",
                        checkout_url="",
                        paid_at=datetime.now(UTC),
                    )
                )
            paid += 1

            decklist = registration.decklist or Decklist(registration_id=registration.id, raw_text="")
            decklist.raw_text = DECKLIST
            decklist.main_count = validation.main_count
            decklist.side_count = validation.side_count
            decklist.status = status
            decklist.validation_errors = "\n".join(validation.errors)
            db.add(decklist)
            db.add(registration)
            decklists += 1
        db.commit()

    print(f"Completate registrazioni {tournament_name}: {paid} pagamenti paid, {decklists} decklist caricate.")


if __name__ == "__main__":
    main()
