import sys

from backend.app.db import SessionLocal, create_all
from backend.app.models import Registration, Tournament, User


def main() -> None:
    tournament_name = sys.argv[1] if len(sys.argv) > 1 else "THE GAME"
    create_all()

    with SessionLocal() as db:
        tournament = db.query(Tournament).filter(Tournament.name == tournament_name).one_or_none()
        if not tournament:
            raise SystemExit(f"Torneo non trovato: {tournament_name}")

        registrations = (
            db.query(Registration)
            .join(User)
            .filter(Registration.tournament_id == tournament.id, User.email.like("%@test.it"))
            .all()
        )
        for registration in registrations:
            registration.checked_in = True
            db.add(registration)
        db.commit()

    print(f"Check-in completato per {len(registrations)} giocatori su {tournament_name}.")


if __name__ == "__main__":
    main()
