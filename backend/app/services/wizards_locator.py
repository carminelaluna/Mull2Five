"""
Importazione dei tornei di Magic dal Wizards Store & Event Locator.

Il Locator (locator.wizards.com) non ha un'API pubblica: le sue pagine leggono
i dati da `search.data`, nel formato turbo-stream di Remix, che qui si decodifica.
ATTENZIONE: le condizioni d'uso di Wizards (company.wizards.com/legal/terms,
§2.2) vietano la raccolta automatica di dati dai loro siti. Per questo
l'importazione è spenta finché non si imposta WIZARDS_LOCATOR_ENABLED=true, e
la si avvia a mano (admin o riga di comando), una città alla volta, con una
pausa fra le richieste. Prima di accenderla in produzione conviene chiedere
il permesso a Wizards (WPN).

Cosa entra: tornei "vetrina" (si trovano nella ricerca e sulla mappa, ma
l'iscrizione si fa presso il negozio, col link al Locator) e i negozi che li
organizzano, con nome, indirizzo e sito. Email e telefoni no: sono spesso
dati personali di chi gestisce il negozio.
"""
import argparse
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.cache import cache_invalidate
from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.models import (
    Organization,
    RegistrationMode,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)

LOCATOR = "https://locator.wizards.com"
SOURCE = "wizards"
PAGE_SIZE = 100
PAUSE_SECONDS = 1.5
HEADERS = {"User-Agent": "Mull2Five/1.0 (+https://mull2five.onrender.com)", "Accept": "*/*"}
IMPORT_USER_EMAIL = "wizards-locator@mull2five.invalid"

# ── Il formato turbo-stream ──────────────────────────────────────────────
# Un array piatto: gli oggetti hanno chiavi "_N" (N = posizione del nome della
# chiave) e valori che sono posizioni nell'array; i negativi sono costanti
# (-5 null, -7 undefined, gli altri numeri speciali).
_SPECIAL = {-1: None, -2: math.nan, -3: -math.inf, -4: -0.0, -5: None, -6: math.inf, -7: None}
_TYPED = {"D", "U", "R", "Y", "E", "B"}   # data, URL, regex, simbolo, errore, bigint: basta il valore


def decode_turbo_stream(text: str):
    """Il primo blocco di una risposta turbo-stream, come oggetti Python."""
    flat = json.loads(text.split("\n", 1)[0])
    seen: dict[int, object] = {}

    def value(index):
        if not isinstance(index, int) or isinstance(index, bool):
            return index
        if index < 0:
            return _SPECIAL.get(index)
        if index in seen:
            return seen[index]
        raw = flat[index]
        if isinstance(raw, list):
            if raw and isinstance(raw[0], str) and raw[0] in _TYPED and len(raw) <= 3:
                seen[index] = raw[1]
                return raw[1]
            out: list = []
            seen[index] = out
            out.extend(value(item) for item in raw)
            return out
        if isinstance(raw, dict):
            obj: dict = {}
            seen[index] = obj
            for key, item in raw.items():
                obj[flat[int(key[1:])]] = value(item)
            return obj
        seen[index] = raw
        return raw

    return value(0)


# ── Scaricare ────────────────────────────────────────────────────────────

class LocatorDisabled(RuntimeError):
    pass


def fetch_events(city: str, distance_km: int = 50, max_pages: int = 5) -> list[dict]:
    """Gli eventi di Magic intorno a una città, pagina per pagina, con una pausa fra le richieste."""
    if not get_settings().wizards_locator_enabled:
        raise LocatorDisabled("Importazione dal Wizards Locator spenta (WIZARDS_LOCATOR_ENABLED)")
    events: list[dict] = []
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(PAUSE_SECONDS)
        response = httpx.get(f"{LOCATOR}/search.data", headers=HEADERS, timeout=20, params={
            "query": city, "searchType": "magic-events", "sortBy": "date", "sortDirection": "Asc",
            "distance": distance_km, "page": page, "pageSize": PAGE_SIZE,
        })
        response.raise_for_status()
        search = decode_turbo_stream(response.text)["routes/($lang).search"]["data"]["events"]["advancedSearchEvents"]
        events.extend(search.get("events") or [])
        total = (search.get("pageInfo") or {}).get("totalResults") or 0
        if page * PAGE_SIZE >= total:
            break
    return events


# ── Tradurre un evento del Locator in un torneo ─────────────────────────

_FORMATS = {"booster draft": "Draft", "sealed deck": "Sealed", "sealed": "Sealed"}
_REL = {"COMPETITIVE": "Competitive", "PROFESSIONAL": "Professional"}
_STRUCTURE = {"SWISS": "swiss", "SINGLE_ELIMINATION": "single_elimination", "PLAYER_LIST_ONLY": "registration_only"}


def _event_type(tags: list[str]) -> str:
    joined = " ".join(tags or []).lower()
    if "prerelease" in joined:
        return "prerelease"
    if "store_championship" in joined:
        return "store_championship"
    if "qualifier" in joined or "rcq" in joined:
        return "rcq"
    return "locals"


def _local_start(event: dict) -> datetime | None:
    raw = event.get("scheduledStartTime") or ""
    if not raw:
        return None
    moment = datetime.fromisoformat(re.sub(r"\.\d+", "", raw).replace("Z", "+00:00"))
    return moment.astimezone(ZoneInfo(event.get("timeZone") or "Europe/Rome"))


def event_url(event_id: str, city: str) -> str:
    return f"{LOCATOR}/search?query={quote(city)}&searchType=magic-events&eventId={quote(event_id)}"


def _generic_site(url: str) -> bool:
    """Molti negozi mettono come sito una pagina di Wizards: non dice niente di loro.
    E si tiene solo un link http(s): finisce in un href."""
    return not url.lower().startswith(("http://", "https://")) or "wizards.com" in url


def _slug(name: str, db: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "negozio"
    slug, n = base, 1
    while slug in {"mine", "current", "memberships"} or db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def import_user(db: Session) -> User:
    """L'"organizzatore" dei tornei importati: un account di sistema, senza accesso."""
    user = db.scalar(select(User).where(User.email == IMPORT_USER_EMAIL))
    if not user:
        user = User(email=IMPORT_USER_EMAIL, display_name="Wizards Event Locator", role=UserRole.ORGANIZER,
                    password_hash=None, is_active=False)
        db.add(user)
        db.flush()
    return user


@dataclass
class ImportReport:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    skipped: int = 0
    stores_created: int = 0
    seen_ids: set[str] = field(default_factory=set)


def _store_for(event: dict, db: Session, report: ImportReport) -> Organization:
    info = event.get("organization") or {}
    store_id = str(info.get("id") or "")
    store = db.scalar(select(Organization).where(Organization.source == SOURCE, Organization.external_id == store_id))
    street = (info.get("address") or "").strip()
    town = " ".join(p for p in ((info.get("postalCode") or "").strip(), (info.get("city") or "").strip()) if p)
    website = (info.get("website") or "").strip()
    fields = {
        "name": (info.get("name") or "Negozio").strip()[:160],
        "city": (info.get("city") or "").strip()[:120],
        "address": ", ".join(p for p in (street, town) if p)[:240],
        "website": "" if _generic_site(website) else website[:240],
        "is_premium": bool(info.get("isPremium")),
    }
    if store is None:
        store = Organization(slug=_slug(fields["name"], db), is_default=False, source=SOURCE, external_id=store_id,
                             latitude=event.get("latitude"), longitude=event.get("longitude"), **fields)
        db.add(store)
        db.flush()
        report.stores_created += 1
    else:
        for key, val in fields.items():
            setattr(store, key, val)
        if store.latitude is None and event.get("latitude") is not None:
            store.latitude, store.longitude = event["latitude"], event["longitude"]
    return store


def import_events(events: list[dict], db: Session, city: str = "") -> ImportReport:
    """Crea o aggiorna i tornei vetrina. Un torneo futuro di un negozio visto in
    questa importazione che non compare più sul Locator viene annullato."""
    report = ImportReport(fetched=len(events))
    organizer = import_user(db)
    today = local_today()
    stores_seen: set[int] = set()
    for event in events:
        external_id = str(event.get("id") or "")
        if external_id in report.seen_ids:   # lo stesso evento su due pagine
            continue
        start = _local_start(event)
        if (not external_id or start is None or start.date() < today
                or event.get("status") not in (None, "SCHEDULED") or not (event.get("organization") or {}).get("id")):
            report.skipped += 1
            continue
        store = _store_for(event, db, report)
        stores_seen.add(store.id)
        report.seen_ids.add(external_id)
        fmt = ((event.get("eventFormat") or {}).get("name") or "Magic").strip()
        fee = event.get("entryFee") or {}
        values = {
            "name": (event.get("title") or fmt).strip()[:180],
            "format": _FORMATS.get(fmt.lower(), fmt)[:80],
            "game": "mtg",
            "event_type": _event_type(event.get("tags") or []),
            "rules_enforcement_level": _REL.get(event.get("rulesEnforcementLevel") or "", "Regular"),
            "structure": _STRUCTURE.get(event.get("pairingType") or "", "swiss"),
            "team_size": min(max(int(event.get("requiredTeamSize") or 1), 1), 3),
            "starts_on": start.date(),
            "start_time": start.strftime("%H:%M"),
            "capacity": max(int(event.get("capacity") or 0), 0),
            "entry_fee_cents": max(int(fee.get("amount") or 0), 0),
            "currency": (fee.get("currency") or "EUR")[:3],
            "description": (event.get("description") or "").strip()[:4000],
            "is_online": bool(event.get("isOnline")),
            "latitude": event.get("latitude"),
            "longitude": event.get("longitude"),
            "venue": ", ".join(p for p in (store.name, store.address) if p)[:180],
            "external_url": event_url(external_id, city or store.city or "Italia"),
            "organization_id": store.id,
            "status": TournamentStatus.PUBLISHED,
        }
        tournament = db.scalar(select(Tournament).where(Tournament.source == SOURCE, Tournament.external_id == external_id))
        if tournament is None:
            db.add(Tournament(
                **values, source=SOURCE, external_id=external_id, organizer_id=organizer.id,
                registration_mode=RegistrationMode.CLOSED, decklist_required=False, pay_at_event=True,
                standings_public=False,
            ))
            report.created += 1
        else:
            for key, val in values.items():
                setattr(tournament, key, val)
            report.updated += 1
    if stores_seen:
        gone = db.scalars(select(Tournament).where(
            Tournament.source == SOURCE, Tournament.organization_id.in_(stores_seen),
            Tournament.starts_on >= today, Tournament.status == TournamentStatus.PUBLISHED,
            Tournament.external_id.not_in(report.seen_ids),
        )).all()
        for tournament in gone:
            tournament.status = TournamentStatus.CANCELLED
            report.cancelled += 1
    db.commit()
    cache_invalidate("tournaments:")
    return report


def main() -> None:
    """python -m backend.app.services.wizards_locator --city Milano --distance 50"""
    parser = argparse.ArgumentParser(description="Importa i tornei di Magic dal Wizards Event Locator")
    parser.add_argument("--city", required=True, action="append", help="Città (si può ripetere)")
    parser.add_argument("--distance", type=int, default=50, help="Raggio in km")
    parser.add_argument("--pages", type=int, default=5, help="Pagine da 100 eventi al massimo, per città")
    args = parser.parse_args()
    from backend.app.db import SessionLocal

    for city in args.city:
        with SessionLocal() as db:
            report = import_events(fetch_events(city, args.distance, args.pages), db, city)
        print(f"{city}: {report.fetched} letti, {report.created} nuovi, {report.updated} aggiornati, "
              f"{report.cancelled} annullati, {report.skipped} saltati, {report.stores_created} negozi nuovi")
        time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    main()
