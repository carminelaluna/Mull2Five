#!/usr/bin/env python3
"""Dati di prova massivi per lo staging: 2 negozi, 128 giocatori, 10 tornei.

Crea, via API, quello che serve a provare le leghe con numeri veri:

- 2 negozi (fumetterie) con una sede ciascuno;
- un pool di 128 giocatori, riusato fra i tornei;
- 10 tornei da 32 iscritti, su formati diversi, 5 per negozio;
- una decklist valida per ogni iscritto;
- 5 turni svizzeri con risultati casuali, cosi i tornei sono conclusi e le
  classifiche delle leghe hanno qualcosa da sommare.

I dati sono riconoscibili dal codice (default BULK27) in nomi, email e slug.
Le email usano example.com: non esistono e non ricevono posta.

Uso:
    python scripts/seed_bulk_staging.py --code BULK27
    python scripts/seed_bulk_staging.py --code BULK27 --max-tournaments 1

Il comando e pensato per lo staging. Rifiuta un indirizzo che non contenga
"staging", a meno di --force.
"""
from __future__ import annotations

import argparse
import csv
import io
import random
import sys
import time
from collections import deque
from datetime import date, timedelta
from typing import Any

import httpx

BASE_URL = "https://mull2five-staging.onrender.com"
DEFAULT_PASSWORD = "BulkTest2026!"

# Formati del gioco Magic, quelli che lo staging ha accesi.
DRAGO_FORMATS = ("Standard", "Pioneer", "Modern", "Legacy", "Pauper")
FENICE_FORMATS = ("Vintage", "Premodern", "Commander", "Sealed", "Draft")
DRAGO_DATES = tuple(date(2026, 9, 19) + timedelta(weeks=i) for i in range(5))
FENICE_DATES = tuple(date(2026, 9, 20) + timedelta(weeks=i) for i in range(5))

SCORES = ((2, 0), (2, 1), (1, 2), (0, 2), (1, 1), (1, 0), (0, 1), (0, 0))
ROUNDS = 5
PLAYERS = 128
PER_TOURNAMENT = 32
PLAYER_STEP = 12          # ogni torneo parte 12 posti piu avanti nel pool


class ApiError(RuntimeError):
    pass


class Api:
    """Client con un tetto di richieste al minuto e ritentativi mirati."""

    def __init__(self, base_url: str, per_minute: int = 180) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=60.0,
            headers={"User-Agent": "Mull2Five-bulk-seed/1.0"},
        )
        self.per_minute = per_minute
        self.times: deque[float] = deque()

    def close(self) -> None:
        self.client.close()

    def _wait(self) -> None:
        now = time.monotonic()
        while self.times and now - self.times[0] > 60.0:
            self.times.popleft()
        if len(self.times) >= self.per_minute:
            sleep_for = 60.0 - (now - self.times[0]) + 0.5
            if sleep_for > 0:
                print(f"    ... {sleep_for:.0f}s per il limite di richieste", flush=True)
                time.sleep(sleep_for)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        ok: tuple[int, ...] = (200, 201),
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for attempt in range(7):
            self._wait()
            self.times.append(time.monotonic())
            response = self.client.request(method, path, headers=headers, **kwargs)
            if response.status_code in ok:
                return response
            if response.status_code == 429:
                retry = response.headers.get("Retry-After")
                wait = float(retry) if retry and retry.isdigit() else 60.0
                print(f"    ... 429 su {method} {path}: aspetto {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            if response.status_code >= 500:
                wait = min(2 ** attempt, 20)
                print(f"    ... {response.status_code} su {method} {path}: riprovo fra {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise ApiError(f"{method} {path} -> {response.status_code}: {response.text[:600]}")
        raise ApiError(f"{method} {path}: troppi tentativi")

    def get(self, path: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, token=token, **kwargs)

    def post(self, path: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, token=token, **kwargs)

    def patch(self, path: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, token=token, **kwargs)


def login_or_register(api: Api, email: str, name: str, password: str) -> str:
    response = api.request(
        "POST", "/api/auth/login", json={"email": email, "password": password},
        ok=(200, 401, 404),
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    response = api.request(
        "POST", "/api/auth/register",
        json={
            "email": email,
            "display_name": name,
            "password": password,
            "role": "organizer",
            "age_confirmed": True,
            "terms_accepted": True,
        },
        ok=(201, 409),
    )
    if response.status_code == 201:
        return response.json()["access_token"]
    # 409: esiste gia. Se la password e quella di questo script, l'accesso va.
    response = api.request(
        "POST", "/api/auth/login", json={"email": email, "password": password}, ok=(200,)
    )
    return response.json()["access_token"]


def ensure_store(api: Api, token: str, name: str, city: str) -> str:
    memberships = api.get("/api/organizations/memberships", token).json()
    found = next((m for m in memberships if m["name"] == name), None)
    if found:
        api.post(f"/api/organizations/{found['slug']}/use", token)
        return found["slug"]
    response = api.post("/api/organizations/mine", token, json={"name": name, "city": city})
    return response.json()["slug"]


def ensure_location(
    api: Api, token: str, slug: str, name: str, address: str, city: str,
    latitude: float, longitude: float,
) -> int:
    locations = api.get(f"/api/organizations/{slug}/locations").json()
    found = next((item for item in locations if item["name"] == name), None)
    if found:
        return found["id"]
    response = api.post(
        f"/api/organizations/{slug}/locations", token,
        json={
            "name": name, "address": address, "city": city,
            "latitude": latitude, "longitude": longitude,
        },
    )
    return response.json()["id"]


def ensure_tournament(
    api: Api, token: str, slug: str, name: str, fmt: str, starts_on: date,
    location_id: int, city: str,
) -> dict[str, Any]:
    existing = api.get("/api/tournaments", params={"org": slug, "limit": 1000}).json()
    found = next((item for item in existing if item["name"] == name), None)
    if found:
        return found
    response = api.post(
        "/api/tournaments", token,
        json={
            "name": name,
            "format": fmt,
            "game": "mtg",
            "location_id": location_id,
            "starts_on": starts_on.isoformat(),
            "start_time": "20:00",
            "capacity": PER_TOURNAMENT,
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
            "description": "Dati di prova massivi. Non sono tornei veri.",
        },
    )
    return response.json()


def import_players(api: Api, token: str, tournament_id: int, players: list[dict[str, str]]) -> dict[str, Any]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["email", "name"])
    for player in players:
        writer.writerow([player["email"], player["name"]])
    response = api.post(
        f"/api/tournaments/{tournament_id}/import", token,
        json={"csv_text": buffer.getvalue(), "mark_paid": True, "dry_run": False},
    )
    return response.json()


def get_registrations(api: Api, token: str, tournament_id: int) -> list[dict[str, Any]]:
    return api.get(
        f"/api/tournaments/{tournament_id}/registrations", token,
        params={"page_size": 200},
    ).json()


def constructed_decklist(fmt: str, seed: int) -> str:
    rng = random.Random(seed)
    names = [f"{fmt} Test Card {i:02d}" for i in range(1, 16)]
    rng.shuffle(names)
    lines = [f"4 {name}" for name in names]
    side = [f"1 {fmt} Side Card {i:02d}" for i in range(1, 16)]
    return "\n".join(lines + ["", "Sideboard"] + side)


def limited_decklist(fmt: str, seed: int) -> str:
    rng = random.Random(seed)
    cards = [f"{fmt} Pool Card {i:02d}" for i in range(1, 24)]
    rng.shuffle(cards)
    lines = [f"1 {name}" for name in cards]
    lines += ["9 Island", "8 Mountain"]
    return "\n".join(lines)


def commander_decklist(fmt: str, seed: int) -> str:
    rng = random.Random(seed)
    cards = [f"{fmt} Commander Card {i:03d}" for i in range(1, 100)]
    rng.shuffle(cards)
    lines = [f"1 {name}" for name in cards]
    lines.append("1 Commander Test")
    return "\n".join(lines)


def decklist_for(fmt: str, seed: int) -> str:
    if fmt == "Commander":
        return commander_decklist(fmt, seed)
    if fmt in {"Sealed", "Draft"}:
        return limited_decklist(fmt, seed)
    return constructed_decklist(fmt, seed)


def ensure_decklist(api: Api, token: str, tournament_id: int, registration: dict[str, Any], fmt: str) -> bool:
    if registration.get("decklist_id") and registration.get("decklist_status") == "valid":
        return False
    raw = decklist_for(fmt, registration["id"])
    api.post(
        f"/api/tournaments/{tournament_id}/registrations/{registration['id']}/decklist",
        token,
        json={"raw_text": raw, "archetype": f"{fmt} test"},
    )
    return True


def get_rounds(api: Api, token: str, tournament_id: int) -> list[dict[str, Any]]:
    return api.get(f"/api/tournaments/{tournament_id}/rounds", token).json()


def fill_results(api: Api, token: str, tournament_id: int, rnd: dict[str, Any], rng: random.Random) -> int:
    filled = 0
    for pairing in rnd["pairings"]:
        if pairing.get("result") or not pairing.get("player_b_registration_id"):
            continue
        a, b = rng.choice(SCORES)
        api.patch(
            f"/api/tournaments/{tournament_id}/pairings/{pairing['id']}/result", token,
            json={"match_wins_a": a, "match_wins_b": b, "draws": 0},
        )
        filled += 1
    return filled


def complete_tournament(api: Api, token: str, tournament: dict[str, Any]) -> None:
    tournament_id = tournament["id"]
    status = tournament["status"]
    if status == "completed":
        print(f"    torneo {tournament_id}: gia concluso", flush=True)
        return
    if status == "published":
        api.post(f"/api/tournaments/{tournament_id}/start", token)
    elif status != "running":
        print(f"    torneo {tournament_id}: stato {status}, salto", flush=True)
        return

    rng = random.Random(tournament_id)
    while True:
        rounds = get_rounds(api, token, tournament_id)
        if not rounds:
            raise ApiError(f"torneo {tournament_id}: nessun turno dopo l'avvio")
        current = rounds[-1]
        filled = fill_results(api, token, tournament_id, current, rng)
        print(
            f"    torneo {tournament_id}: turno {current['number']}/{ROUNDS}, "
            f"{filled} risultati",
            flush=True,
        )
        if len(rounds) >= ROUNDS:
            api.post(f"/api/tournaments/{tournament_id}/close", token)
            print(f"    torneo {tournament_id}: concluso", flush=True)
            return
        api.post(f"/api/tournaments/{tournament_id}/rounds", token)


def player_pool(code: str) -> list[dict[str, str]]:
    return [
        {"email": f"bulk.{code.lower()}.p{i:03d}@example.com", "name": f"Bulk Player {i:03d}"}
        for i in range(1, PLAYERS + 1)
    ]


def players_for(pool: list[dict[str, str]], tournament_index: int) -> list[dict[str, str]]:
    start = tournament_index * PLAYER_STEP
    return [pool[(start + offset) % PLAYERS] for offset in range(PER_TOURNAMENT)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--code", default="BULK27", help="codice nei nomi e nelle email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="password degli organizzatori")
    parser.add_argument("--max-tournaments", type=int, default=0, help="fermati dopo N tornei (0 = tutti)")
    parser.add_argument("--per-minute", type=int, default=180, help="tetto di richieste al minuto")
    parser.add_argument("--force", action="store_true", help="accetta anche un indirizzo non staging")
    args = parser.parse_args()

    if "staging" not in args.base_url and not args.force:
        print("FERMO: l'indirizzo non contiene 'staging'. Usa --force solo se sai cosa stai facendo.")
        return 2

    code = args.code.strip().upper()
    if not code:
        print("FERMO: il codice non puo essere vuoto.")
        return 2

    api = Api(args.base_url, args.per_minute)
    pool = player_pool(code)
    organizers = (
        {
            "email": f"bulk.{code.lower()}.drago@example.com",
            "name": f"Fumetteria Drago [{code}]",
            "store": f"Fumetteria Drago [{code}]",
            "city": "Milano",
            "location": (f"Sede Drago [{code}]", "Via dei Draghi 12", "Milano", 45.4642, 9.1900),
            "formats": DRAGO_FORMATS,
            "dates": DRAGO_DATES,
            "prefix": "Drago",
        },
        {
            "email": f"bulk.{code.lower()}.fenice@example.com",
            "name": f"Fumetteria Fenice [{code}]",
            "store": f"Fumetteria Fenice [{code}]",
            "city": "Torino",
            "location": (f"Sede Fenice [{code}]", "Corso Fenice 8", "Torino", 45.0703, 7.6869),
            "formats": FENICE_FORMATS,
            "dates": FENICE_DATES,
            "prefix": "Fenice",
        },
    )

    created = 0
    summary: list[dict[str, Any]] = []
    try:
        for organizer in organizers:
            print(f"\n== {organizer['store']} ==", flush=True)
            token = login_or_register(api, organizer["email"], organizer["name"], args.password)
            slug = ensure_store(api, token, organizer["store"], organizer["city"])
            print(f"  negozio: {slug}", flush=True)
            location_id = ensure_location(api, token, slug, *organizer["location"])
            print(f"  sede: {location_id}", flush=True)

            for index, fmt in enumerate(organizer["formats"]):
                if args.max_tournaments and created >= args.max_tournaments:
                    break
                name = f"[{code}] {organizer['prefix']} #{index + 1} - {fmt}"
                tournament = ensure_tournament(
                    api, token, slug, name, fmt, organizer["dates"][index], location_id,
                    organizer["city"],
                )
                tournament_id = tournament["id"]
                print(f"\n  {name} (id {tournament_id}, {tournament['status']})", flush=True)

                if tournament["status"] == "completed":
                    print("    gia concluso, salto", flush=True)
                    summary.append({"id": tournament_id, "name": name, "format": fmt, "store": slug})
                    created += 1
                    continue

                if tournament["status"] == "published":
                    selected = players_for(pool, created)
                    imported = import_players(api, token, tournament_id, selected)
                    print(
                        f"    iscritti: {imported['added']} aggiunti, "
                        f"{imported['waitlisted']} in attesa, {imported['skipped']} saltati",
                        flush=True,
                    )

                    registrations = get_registrations(api, token, tournament_id)
                    if len(registrations) != PER_TOURNAMENT:
                        raise ApiError(
                            f"torneo {tournament_id}: {len(registrations)} iscritti, "
                            f"attesi {PER_TOURNAMENT}"
                        )
                    written = sum(
                        ensure_decklist(api, token, tournament_id, registration, fmt)
                        for registration in registrations
                    )
                    print(
                        f"    decklist: {written} scritte, "
                        f"{len(registrations) - written} gia valide",
                        flush=True,
                    )
                elif tournament["status"] == "running":
                    print("    gia avviato, riprendo i turni", flush=True)
                else:
                    print(f"    stato {tournament['status']}, salto", flush=True)
                    continue

                complete_tournament(api, token, tournament)
                summary.append({"id": tournament_id, "name": name, "format": fmt, "store": slug})
                created += 1
            if args.max_tournaments and created >= args.max_tournaments:
                break
    finally:
        api.close()

    print("\n== Riepilogo ==", flush=True)
    for item in summary:
        print(f"  {item['id']:>4}  {item['format']:<10}  {item['name']}", flush=True)
    print(
        f"\nGiocatori nel pool: {PLAYERS} (email @example.com)\n"
        f"Tornei creati/ripresi in questo giro: {len(summary)}\n"
        f"Password organizzatori: {args.password}\n"
        f"Codice: {code}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
