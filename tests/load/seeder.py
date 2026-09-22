"""
seeder.py — Pre-popola il database per i test di carico.

Inserisce direttamente nel DB via SQLAlchemy (bypassa la API e il rate limiting).
Crea: 100 organizzatori, 100 tornei, 100.000 giocatori, 100.000 iscrizioni.

Uso:
    cd /path/to/project
    source .venv/bin/activate
    python tests/load/seeder.py [--tournaments 100] [--players 1000] [--wipe]
"""

import argparse
import os

# Aggiunge la root del progetto al path
import sys
import time
from datetime import date

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.app.core.config import get_settings
from backend.app.db import Base
from backend.app.models import (
    Decklist,
    DecklistStatus,
    Pairing,
    Payment,
    PaymentStatus,
    Registration,
    Round,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)
from backend.app.security import create_access_token, hash_password

SAMPLE_DECK = (
    "4 Lightning Bolt\n4 Ragavan, Nimble Pilferer\n4 Murktide Regent\n"
    "4 Dragon's Rage Channeler\n4 Expressive Iteration\n4 Counterspell\n"
    "4 Spell Pierce\n4 Consider\n4 Unholy Heat\n4 Mishra's Bauble\n"
    "3 Ledger Shredder\n3 Memory Deluge\n4 Fiery Islet\n4 Steam Vents\n"
    "4 Scalding Tarn\n2 Island\n2 Mountain\n2 Shivan Reef\n"
    "\nSideboard\n2 Blood Moon\n2 Flusterstorm\n2 Engineered Explosives\n"
    "3 Pyroblast\n2 Alpine Moon\n2 Torpor Orb\n2 Force of Negation"
)
FORMATS    = ["Modern", "Standard", "Pioneer", "Legacy"]
ARCHETYPES = ["Izzet Murktide", "Tron", "Burn", "Yawgmoth", "Living End",
              "Amulet Titan", "UW Control", "Domain Ramp", "Hammer Time", "Cascade Crash"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournaments", type=int, default=100)
    parser.add_argument("--players",     type=int, default=1000)
    parser.add_argument("--wipe",        action="store_true", help="Cancella i dati di load-test esistenti")
    parser.add_argument("--rounds",      type=int, default=3, help="Round pre-generati per torneo")
    args = parser.parse_args()

    settings = get_settings()
    engine   = create_engine(settings.database_url, echo=False)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if args.wipe:
            print("⚠ Cancello i dati di load-test esistenti (rispettando FK)...")
            # PostgreSQL richiede l'eliminazione in ordine figlio → padre
            wipe_sql = [
                # Tabelle figlio di pairings
                "DELETE FROM pairing_result_reports WHERE pairing_id IN (SELECT p.id FROM pairings p JOIN rounds r ON p.round_id = r.id JOIN tournaments t ON r.tournament_id = t.id JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                # Tabelle figlio di rounds/registrations
                "DELETE FROM pairings WHERE round_id IN (SELECT r.id FROM rounds r JOIN tournaments t ON r.tournament_id = t.id JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                "DELETE FROM rounds WHERE tournament_id IN (SELECT t.id FROM tournaments t JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                # Tabelle figlio di registrations
                "DELETE FROM decklists WHERE registration_id IN (SELECT r.id FROM registrations r JOIN users u ON r.player_id = u.id WHERE u.email LIKE '%%@load.test')",
                "DELETE FROM decklist_revisions WHERE registration_id IN (SELECT r.id FROM registrations r JOIN users u ON r.player_id = u.id WHERE u.email LIKE '%%@load.test')",
                "DELETE FROM payments WHERE registration_id IN (SELECT r.id FROM registrations r JOIN users u ON r.player_id = u.id WHERE u.email LIKE '%%@load.test')",
                "DELETE FROM penalties WHERE registration_id IN (SELECT r.id FROM registrations r JOIN users u ON r.player_id = u.id WHERE u.email LIKE '%%@load.test')",
                # Registrations
                "DELETE FROM registrations WHERE player_id IN (SELECT id FROM users WHERE email LIKE '%%@load.test')",
                "DELETE FROM registrations WHERE tournament_id IN (SELECT t.id FROM tournaments t JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                # Tabelle figlio di tournaments
                "DELETE FROM announcements WHERE tournament_id IN (SELECT t.id FROM tournaments t JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                "DELETE FROM invite_codes WHERE tournament_id IN (SELECT t.id FROM tournaments t JOIN users u ON t.organizer_id = u.id WHERE u.email LIKE '%%@load.test')",
                # Tournaments e users
                "DELETE FROM tournaments WHERE organizer_id IN (SELECT id FROM users WHERE email LIKE '%%@load.test')",
                "DELETE FROM users WHERE email LIKE '%%@load.test'",
            ]
            for sql in wipe_sql:
                session.execute(text(sql))
            session.commit()
            print("  Fatto.")

        total_start = time.time()

        print(f"\nCreazione {args.tournaments} organizzatori e tornei...")
        pw_hash = hash_password("loadtest123")
        org_ids = []

        for i in range(args.tournaments):
            # Organizzatore
            org = User(
                email=f"org{i:03d}@load.test",
                display_name=f"Organizer {i+1:03d}",
                role=UserRole.ORGANIZER,
                password_hash=pw_hash,
                is_active=True,
            )
            session.add(org)
            session.flush()
            org_ids.append(org.id)

            # Torneo
            tournament = Tournament(
                organizer_id=org.id,
                name=f"Load Test Tournament {i+1:03d}",
                format=FORMATS[i % len(FORMATS)],
                rules_enforcement_level="Competitive",
                venue=f"Arena {i+1}",
                starts_on=date(2026, 12, 1),
                capacity=args.players + 10,
                entry_fee_cents=2500,
                currency="EUR",
                status=TournamentStatus.RUNNING,
                swiss_rounds=args.rounds,
                pairings_public=True,
                standings_public=True,
                decklists_public=False,
                email_notifications_enabled=False,
                round_timer_minutes=50,
            )
            session.add(tournament)
            session.flush()
            tid = tournament.id

            # Batch giocatori
            t_start = time.time()
            reg_ids  = []
            for j in range(args.players):
                player = User(
                    email=f"t{tid}_p{j:04d}@load.test",
                    display_name=f"Player {j+1:04d}",
                    role=UserRole.PLAYER,
                    password_hash=pw_hash,
                    is_active=True,
                )
                session.add(player)
                session.flush()

                reg = Registration(
                    tournament_id=tid,
                    player_id=player.id,
                    archetype=ARCHETYPES[j % len(ARCHETYPES)],
                    wizards_account=f"{j+1:08d}",
                    checked_in=(j % 3 != 0),
                )
                session.add(reg)
                session.flush()
                reg_ids.append(reg.id)

                # Pagamento
                payment = Payment(
                    registration_id=reg.id,
                    provider="sandbox",
                    status=PaymentStatus.PAID,
                    amount_cents=2500,
                    currency="EUR",
                    provider_checkout_id=f"sandbox_{tid}_{j}",
                    provider_payment_id=f"paid_{tid}_{j}",
                    checkout_url="",
                )
                session.add(payment)

                # Decklist
                decklist = Decklist(
                    registration_id=reg.id,
                    raw_text=SAMPLE_DECK,
                    main_count=61,
                    side_count=15,
                    status=DecklistStatus.VALID,
                )
                session.add(decklist)

            # Round pre-generati
            import random
            rng = random.Random(tid * 42)
            for r_num in range(1, args.rounds + 1):
                shuffled = reg_ids.copy()
                rng.shuffle(shuffled)
                round_obj = Round(
                    tournament_id=tid,
                    number=r_num,
                    phase="swiss",
                    is_published=True,
                )
                session.add(round_obj)
                session.flush()

                results = ["2-0","2-1","1-2","0-2","1-1"]
                for table, k in enumerate(range(0, len(shuffled) - 1, 2), start=1):
                    pa_id = shuffled[k]
                    pb_id = shuffled[k + 1] if k + 1 < len(shuffled) else None
                    res   = rng.choice(results)
                    wins_a = int(res[0]); wins_b = int(res[2])
                    pairing = Pairing(
                        round_id=round_obj.id,
                        table_number=table,
                        player_a_registration_id=pa_id,
                        player_b_registration_id=pb_id,
                        result=res,
                        match_wins_a=wins_a,
                        match_wins_b=wins_b,
                    )
                    session.add(pairing)

            session.commit()
            elapsed = time.time() - t_start
            print(f"  [{i+1:3d}/{args.tournaments}] Torneo {tid:5d}: "
                  f"{args.players} giocatori, {args.rounds} round — {elapsed:.1f}s")

        total = time.time() - total_start
        print(f"\n✓ Seed completato in {total:.1f}s")
        print(f"  Tornei:    {args.tournaments:,}")
        print(f"  Giocatori: {args.tournaments * args.players:,}")
        print(f"  Iscrizioni:{args.tournaments * args.players:,}")
        print(f"  Round:     {args.tournaments * args.rounds:,}")

        # Salva i token per locust
        _write_tokens(session, args.tournaments)


def _write_tokens(session: Session, n_tournaments: int):
    """Genera i JWT e li salva in tokens.json per locustfile.py.

    Ogni organizzatore include tournament_id.
    Ogni giocatore include tournament_id — così locustfile usa sempre
    il torneo giusto per quel giocatore (evita 404 su /my-pairings).
    """
    import json

    from backend.app.security import create_access_token

    tokens = {"organizers": [], "players_sample": []}

    # Recupera organizzatori con i loro tornei
    orgs = session.scalars(
        select(User).where(User.email.like("%@load.test"), User.role == "organizer").limit(n_tournaments)
    ).all()
    for org in orgs:
        # Trova il torneo di questo organizzatore
        tournament = session.scalars(
            select(Tournament).where(Tournament.organizer_id == org.id).limit(1)
        ).first()
        tokens["organizers"].append({
            "email":         org.email,
            "token":         create_access_token(org),
            "tournament_id": tournament.id if tournament else None,
        })

    # Campione di 500 giocatori — ognuno con il proprio tournament_id
    # Usa Registration per sapere esattamente a quale torneo è iscritto
    regs = session.execute(
        select(User, Registration.tournament_id)
        .join(Registration, Registration.player_id == User.id)
        .where(User.email.like("%@load.test"), User.role == "player")
        .limit(500)
    ).all()
    for user, tid in regs:
        tokens["players_sample"].append({
            "email":         user.email,
            "token":         create_access_token(user),
            "tournament_id": tid,         # ← il torneo di questo giocatore
        })

    out = os.path.join(os.path.dirname(__file__), "tokens.json")
    with open(out, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"\n  Token salvati in: {out}")
    print(f"  Organizzatori con token: {len(tokens['organizers'])}")
    print(f"  Giocatori con token:     {len(tokens['players_sample'])}")


if __name__ == "__main__":
    main()
