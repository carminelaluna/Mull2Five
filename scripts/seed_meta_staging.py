#!/usr/bin/env python3
"""Dati di prova con liste reali Modern e Standard, per il metashare.

Crea sullo staging:

- 5 tornei Modern e 5 Standard da 32 iscritti, con 5 turni svizzeri e tornei
  conclusi;
- una lista reale presa da MTGTop8 per ogni giocatore, fissa per tutta la lega;
- 2 circuiti, uno per formato.

Riusa i negozi e il pool di giocatori BULK27. Nasconde dall'archivio le liste
finte BULK27 dei formati Modern e Standard, cosi il metashare mostra solo le
liste vere.

Uso:
    python scripts/seed_meta_staging.py
    python scripts/seed_meta_staging.py --decks scripts/data/mtgtop8_decks.json

Il comando e pensato per lo staging. Rifiuta un indirizzo che non contenga
"staging", a meno di --force.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from seed_bulk_staging import (
    Api,
    ApiError,
    complete_tournament,
    ensure_location,
    ensure_store,
    get_registrations,
    login_or_register,
)

BASE_URL = "https://mull2five-staging.onrender.com"
DEFAULT_PASSWORD = "BulkTest2026!"
CODE = "META27"
TOURNAMENTS = 5
ROUNDS = 5
CAPACITY = 32
DEFAULT_DECKS = Path(__file__).parent / "data" / "mtgtop8_decks.json"

CONFIGS: dict[str, dict[str, Any]] = {
    "Modern": {
        "organizer": "bulk.bulk27.drago@example.com",
        "store": "Fumetteria Drago [BULK27]",
        "slug": "fumetteria-drago-bulk27",
        "city": "Milano",
        "location": ("Sede Drago [BULK27]", "Via dei Draghi 12", "Milano", 45.4642, 9.1900),
        "player_start": 1,
        "dates": [date(2026, 10, 6) + timedelta(weeks=i) for i in range(TOURNAMENTS)],
        "league": f"[{CODE}] Lega Modern",
    },
    "Standard": {
        "organizer": "bulk.bulk27.fenice@example.com",
        "store": "Fumetteria Fenice [BULK27]",
        "slug": "fumetteria-fenice-bulk27",
        "city": "Torino",
        "location": ("Sede Fenice [BULK27]", "Corso Fenice 8", "Torino", 45.0703, 7.6869),
        "player_start": 33,
        "dates": [date(2026, 10, 7) + timedelta(weeks=i) for i in range(TOURNAMENTS)],
        "league": f"[{CODE}] Lega Standard",
    },
}


def ensure_tournament(
    api: Api,
    token: str,
    slug: str,
    name: str,
    fmt: str,
    starts_on: date,
    location_id: int,
    city: str,
) -> dict[str, Any]:
    existing = api.get("/api/tournaments", params={"org": slug, "limit": 1000}).json()
    found = next((item for item in existing if item["name"] == name), None)
    if found:
        return found
    response = api.post(
        "/api/tournaments",
        token,
        json={
            "name": name,
            "format": fmt,
            "game": "mtg",
            "location_id": location_id,
            "starts_on": starts_on.isoformat(),
            "start_time": "20:00",
            "capacity": CAPACITY,
            "entry_fee_cents": 0,
            "currency": "EUR",
            "status": "published",
            "structure": "swiss",
            "swiss_rounds": ROUNDS,
            "best_of": 3,
            "event_type": "locals",
            "rules_enforcement_level": "Regular",
            "city": city,
            "decklist_required": True,
            "decklists_public": True,
            "pairings_public": True,
            "standings_public": True,
            "registration_mode": "open",
            "pay_at_event": True,
            "email_notifications_enabled": False,
            "legal_validation_enabled": False,
            "check_in_required": False,
            "self_check_in_enabled": False,
            "late_registration_enabled": False,
            "round_timer_minutes": 50,
            "description": "Dati di prova con liste reali da MTGTop8. Non sono tornei veri.",
        },
    )
    return response.json()


def hide_fake_decklists(api: Api, token: str, slug: str) -> int:
    """Toglie dall'archivio le liste finte BULK27 di Modern e Standard."""
    tournaments = api.get("/api/tournaments", params={"org": slug, "limit": 1000}).json()
    hidden = 0
    for tournament in tournaments:
        if "BULK27" in tournament["name"] and tournament.get("format") in {"Modern", "Standard"}:
            api.patch(
                f"/api/tournaments/{tournament['id']}/controls",
                token,
                json={"decklists_public": False},
            )
            hidden += 1
    return hidden


def import_players(
    api: Api, token: str, tournament_id: int, players: list[tuple[str, str]]
) -> dict[str, Any]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["email", "name"])
    for email, name in players:
        writer.writerow([email, name])
    response = api.post(
        f"/api/tournaments/{tournament_id}/import",
        token,
        json={"csv_text": buffer.getvalue(), "mark_paid": True, "dry_run": False},
    )
    return response.json()


def normalize(text: str) -> str:
    return "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())


def ensure_decklists(
    api: Api,
    token: str,
    tournament_id: int,
    registrations: list[dict[str, Any]],
    mapping: dict[str, dict[str, Any]],
) -> int:
    written = 0
    for registration in registrations:
        email = registration["player_email"].lower()
        deck = mapping.get(email)
        if not deck:
            raise ApiError(f"torneo {tournament_id}: {email} non ha una lista assegnata")
        current = registration.get("decklist_raw_text") or ""
        if (
            registration.get("decklist_status") == "valid"
            and registration.get("archetype") == deck["archetype"]
            and normalize(current) == normalize(deck["raw_text"])
        ):
            continue
        api.post(
            f"/api/tournaments/{tournament_id}/registrations/{registration['id']}/decklist",
            token,
            json={"raw_text": deck["raw_text"], "archetype": deck["archetype"]},
        )
        written += 1
    return written


def ensure_league(
    api: Api,
    token: str,
    name: str,
    tournament_ids: list[int],
    starts_on: date,
    ends_on: date,
) -> dict[str, Any]:
    mine = api.get("/api/seasons/mine", token).json()
    season = next((item for item in mine if item["name"] == name), None)
    if season:
        print(f"  circuito esistente: {name} (id {season['id']})", flush=True)
    else:
        response = api.post(
            "/api/seasons",
            token,
            json={
                "name": name,
                "description": "Circuito di prova con liste reali da MTGTop8. Non sono tornei veri.",
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat(),
                "points_win": 3,
                "points_draw": 1,
                "points_participation": 1,
                "points_champion_bonus": 5,
                "points_undefeated_bonus": 3,
                "drop_worst_scores": 1,
                "drop_above_tournaments": 4,
                "is_public": True,
            },
        )
        season = response.json()
        print(f"  circuito creato: {name} (id {season['id']})", flush=True)
    api.post(
        f"/api/seasons/{season['id']}/tournaments",
        token,
        json={"tournament_ids": tournament_ids},
    )
    return season


def verify_meta(api: Api, fmt: str, slug: str, expected: dict[str, int]) -> None:
    meta = api.get(
        "/api/decklists/meta",
        params={"format": fmt, "store": slug, "days": 90},
    ).json()
    total = meta["total_lists"]
    print(f"\n  {fmt}: {total} liste in archivio, {len(meta['archetypes'])} archetipi", flush=True)
    for row in meta["archetypes"]:
        wanted = expected.get(row["archetype"], 0) * TOURNAMENTS
        marker = "" if row["lists"] == wanted else f"  (attese {wanted})"
        print(
            f"    {row['lists']:>3}  {row['share']:>5.1f}%  {row['archetype']}{marker}",
            flush=True,
        )
    print("  carte piu giocate:", flush=True)
    for card in meta["top_cards"][:8]:
        print(
            f"    {card['lists']:>3} liste  {card['share']:>5.1f}%  "
            f"{card['copies']:>4.1f} copie  {card['name']}",
            flush=True,
        )
    if total != CAPACITY * TOURNAMENTS:
        print(f"  ATTENZIONE: attese {CAPACITY * TOURNAMENTS} liste", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--decks", type=Path, default=DEFAULT_DECKS)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--per-minute", type=int, default=180)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if "staging" not in args.base_url and not args.force:
        print("FERMO: l'indirizzo non contiene 'staging'. Usa --force solo se sai cosa stai facendo.")
        return 2
    if not args.decks.exists():
        print(f"FERMO: non trovo {args.decks}")
        return 2

    decks = json.loads(args.decks.read_text(encoding="utf-8"))
    for fmt in CONFIGS:
        if len(decks.get(fmt, [])) != CAPACITY:
            print(f"FERMO: {fmt} ha {len(decks.get(fmt, []))} liste, attese {CAPACITY}")
            return 2

    api = Api(args.base_url, args.per_minute)
    summary: list[tuple[str, str, list[int], dict[str, Any]]] = []
    hidden_stores: set[str] = set()
    try:
        for fmt, config in CONFIGS.items():
            print(f"\n== {fmt} ==", flush=True)
            token = login_or_register(
                api, config["organizer"], config["store"], args.password
            )
            slug = ensure_store(api, token, config["store"], config["city"])
            location_id = ensure_location(api, token, slug, *config["location"])
            print(f"  negozio: {slug}, sede: {location_id}", flush=True)

            if slug not in hidden_stores:
                hidden = hide_fake_decklists(api, token, slug)
                print(f"  liste finte BULK27 nascoste: {hidden}", flush=True)
                hidden_stores.add(slug)

            players = [
                (f"bulk.bulk27.p{index:03d}@example.com", f"Bulk Player {index:03d}")
                for index in range(
                    config["player_start"], config["player_start"] + CAPACITY
                )
            ]
            mapping = {
                email: decks[fmt][index] for index, (email, _) in enumerate(players)
            }
            tournament_ids: list[int] = []

            for index, starts_on in enumerate(config["dates"]):
                name = f"[{CODE}] {fmt} #{index + 1}"
                tournament = ensure_tournament(
                    api, token, slug, name, fmt, starts_on, location_id, config["city"]
                )
                tournament_id = tournament["id"]
                print(
                    f"\n  {name} (id {tournament_id}, {tournament['status']})",
                    flush=True,
                )

                if tournament["status"] == "completed":
                    print("    gia concluso, salto", flush=True)
                    tournament_ids.append(tournament_id)
                    continue
                if tournament["status"] not in {"published", "running"}:
                    print(f"    stato {tournament['status']}, salto", flush=True)
                    continue

                if tournament["status"] == "published":
                    imported = import_players(api, token, tournament_id, players)
                    print(
                        f"    iscritti: {imported['added']} aggiunti, "
                        f"{imported['waitlisted']} in attesa, {imported['skipped']} saltati",
                        flush=True,
                    )
                else:
                    print("    gia avviato, riprendo i turni", flush=True)

                registrations = get_registrations(api, token, tournament_id)
                if len(registrations) != CAPACITY:
                    raise ApiError(
                        f"torneo {tournament_id}: {len(registrations)} iscritti, "
                        f"attesi {CAPACITY}"
                    )
                written = ensure_decklists(
                    api, token, tournament_id, registrations, mapping
                )
                print(
                    f"    liste: {written} scritte, "
                    f"{CAPACITY - written} gia a posto",
                    flush=True,
                )

                complete_tournament(api, token, tournament)
                tournament_ids.append(tournament_id)

            season = ensure_league(
                api,
                token,
                config["league"],
                tournament_ids,
                config["dates"][0],
                config["dates"][-1],
            )
            summary.append((fmt, slug, tournament_ids, season))

        print("\n== Metashare ==", flush=True)
        for fmt, slug, _ids, _season in summary:
            expected: dict[str, int] = {}
            for deck in decks[fmt]:
                expected[deck["archetype"]] = expected.get(deck["archetype"], 0) + 1
            verify_meta(api, fmt, slug, expected)
    finally:
        api.close()

    print("\n== Riepilogo ==", flush=True)
    for fmt, slug, ids, season in summary:
        print(
            f"  {fmt}: tornei {ids}, circuito {season['id']} ({season['name']}) "
            f"su {slug}",
            flush=True,
        )
    print(
        f"\nListe reali: {args.decks}\n"
        f"Codice: {CODE}\n"
        f"Password organizzatori: {args.password}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
