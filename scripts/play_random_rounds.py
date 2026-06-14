import random
import sys

from backend.app.db import SessionLocal, create_all
from backend.app.models import Pairing, Round, Tournament, TournamentStatus
from backend.app.routers.tournaments import create_round_for_tournament, ensure_latest_round_has_results


SCORES = [(2, 0), (2, 1), (1, 2), (0, 2), (1, 1), (1, 0), (0, 1), (0, 0)]


def main() -> None:
    tournament_name = sys.argv[1] if len(sys.argv) > 1 else "THE GAME"
    target_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    random.seed(seed)

    create_all()
    with SessionLocal() as db:
        tournament = db.query(Tournament).filter(Tournament.name == tournament_name).one_or_none()
        if not tournament:
            raise SystemExit(f"Torneo non trovato: {tournament_name}")
        if tournament.status in {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}:
            tournament.status = TournamentStatus.RUNNING
            db.add(tournament)
            db.commit()

        while db.query(Round).filter(Round.tournament_id == tournament.id).count() < target_rounds:
            fill_open_rounds(tournament.id, db)
            ensure_latest_round_has_results(tournament.id, db)
            db.refresh(tournament)
            create_round_for_tournament(tournament, db)
            db.refresh(tournament)

        rounds = (
            db.query(Round)
            .filter(Round.tournament_id == tournament.id)
            .order_by(Round.number)
            .limit(target_rounds)
            .all()
        )
        updated = 0
        for round_obj in rounds:
            updated += fill_round(round_obj.id, db)

        print(f"{tournament_name}: completati {len(rounds)} turni, risultati aggiornati {updated}.")


def fill_open_rounds(tournament_id: int, db) -> int:
    rounds = db.query(Round).filter(Round.tournament_id == tournament_id).order_by(Round.number).all()
    return sum(fill_round(round_obj.id, db) for round_obj in rounds)


def fill_round(round_id: int, db) -> int:
    updated = 0
    pairings = (
        db.query(Pairing)
        .filter(Pairing.round_id == round_id)
        .order_by(Pairing.table_number)
        .all()
    )
    for pairing in pairings:
        if pairing.result:
            continue
        if not pairing.player_b_registration_id:
            pairing.result = "A"
            pairing.match_wins_a = 2
            pairing.match_wins_b = 0
            pairing.draws = 0
            db.add(pairing)
            updated += 1
            continue
        a_wins, b_wins = random.choice(SCORES)
        pairing.match_wins_a = a_wins
        pairing.match_wins_b = b_wins
        pairing.draws = 0
        if a_wins > b_wins:
            pairing.result = "A"
        elif b_wins > a_wins:
            pairing.result = "B"
        else:
            pairing.result = "D"
        db.add(pairing)
        updated += 1
    db.commit()
    return updated


if __name__ == "__main__":
    main()
