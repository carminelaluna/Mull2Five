import sys

from backend.app.db import SessionLocal, create_all
from backend.app.models import Registration, Tournament, User


def main() -> None:
    tournament_name = sys.argv[1] if len(sys.argv) > 1 else "THE GAME"
    create_all()
    created = 0
    skipped = 0

    with SessionLocal() as db:
        tournament = db.query(Tournament).filter(Tournament.name == tournament_name).one_or_none()
        if not tournament:
            raise SystemExit(f"Torneo non trovato: {tournament_name}")

        players = db.query(User).filter(User.email.like("%@test.it")).order_by(User.display_name).all()
        existing_player_ids = {
            player_id
            for (player_id,) in db.query(Registration.player_id)
            .filter(Registration.tournament_id == tournament.id)
            .all()
        }

        if len(existing_player_ids) + len(players) > tournament.capacity:
            raise SystemExit(
                f"Capienza insufficiente: {tournament.capacity}, richiesti {len(existing_player_ids) + len(players)}"
            )

        for player in players:
            if player.id in existing_player_ids:
                skipped += 1
                continue
            db.add(
                Registration(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    wizards_account=player.display_name,
                )
            )
            created += 1
        db.commit()

    print(f"Iscrizione completata a {tournament_name}: {created} creati, {skipped} gia iscritti.")


if __name__ == "__main__":
    main()
