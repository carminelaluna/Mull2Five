"""
site.py — Le pagine di servizio del sito: robots.txt e sitemap.xml per i motori
di ricerca, i dati di chi gestisce il sito per privacy e termini, e le
statistiche delle visite.

Le statistiche non usano cookie e non salvano IP, user agent né utenti: ogni
pagina vista aggiunge uno a un contatore per giorno, pagina, dominio di
provenienza e tipo di schermo (PageView). Chi ha Do Not Track o Global Privacy
Control attivi non viene contato, e nemmeno i bot. Così non serve il consenso
(vedi cookie.html).
"""
import re
from collections import Counter
from datetime import timedelta
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.cache import cache_get, cache_set
from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.db import get_db
from backend.app.models import (
    Event,
    Organization,
    PageView,
    Season,
    Tournament,
    TournamentStatus,
    User,
)
from backend.app.schemas import (
    AnalyticsCountOut,
    AnalyticsDayOut,
    AnalyticsOut,
    LegalOut,
    PageHitIn,
)
from backend.app.security import require_admin

router = APIRouter(tags=["site"])
api_router = APIRouter(tags=["site"])

# Le pagine riservate: i motori di ricerca non hanno niente da trovarci.
PRIVATE_PAGES = (
    "organizer.html", "control.html", "my-registrations.html", "decks.html", "history.html",
    "timer.html", "display.html", "sandbox-checkout.html", "forgot-password.html",
    "reset-password.html", "grazie.html",
)
PUBLIC_PAGES = (
    "", "events.html", "stores.html", "circuits.html", "decklists.html", "leaderboard.html",
    "login.html", "privacy.html", "termini.html", "cookie.html",
)
SITEMAP_TTL = 3600
# Solo pagine del sito, senza query: player.html?email=… non deve finire nei numeri.
PAGE = re.compile(r"^/[a-z0-9-]{1,40}\.html$")
BOTS = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|facebookexternalhit|curl|wget|python", re.I)


def site_url(request: Request) -> str:
    """L'indirizzo pubblico del sito: SITE_URL, poi FRONTEND_URL, poi quello della richiesta."""
    settings = get_settings()
    if settings.site_url:
        return settings.site_url.rstrip("/")
    configured = str(settings.frontend_url).rstrip("/")
    if "127.0.0.1" not in configured and "localhost" not in configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request) -> Response:
    # Le API restano aperte: le pagine pubbliche si riempiono da lì, e i motori
    # di ricerca che eseguono JavaScript devono poterle leggere.
    lines = ["User-agent: *", "Allow: /", "Disallow: /docs", "Disallow: /redoc"]
    lines += [f"Disallow: /{page}" for page in PRIVATE_PAGES]
    lines += ["", f"Sitemap: {site_url(request)}/sitemap.xml", ""]
    return Response("\n".join(lines), media_type="text/plain")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Session = Depends(get_db)) -> Response:
    base = site_url(request)
    key = f"site:sitemap:{base}"
    body = cache_get(key)
    if body is None:
        body = _sitemap(base, db)
        cache_set(key, body, ttl=SITEMAP_TTL)
    return Response(body, media_type="application/xml")


def _sitemap(base: str, db: Session) -> str:
    """Le pagine pubbliche, i tornei dell'ultimo anno e quelli in arrivo, i
    negozi, i circuiti e le manifestazioni pubbliche."""
    since = local_today() - timedelta(days=365)
    visible = (TournamentStatus.PUBLISHED, TournamentStatus.RUNNING, TournamentStatus.COMPLETED)
    urls = [f"{base}/{page}" for page in PUBLIC_PAGES]
    urls += [f"{base}/event.html?id={tid}" for tid in db.scalars(
        select(Tournament.id).where(Tournament.status.in_(visible), Tournament.starts_on >= since)
        .order_by(Tournament.starts_on.desc()).limit(40_000)
    )]
    urls += [f"{base}/store.html?s={slug}" for slug in db.scalars(select(Organization.slug).order_by(Organization.id))]
    urls += [f"{base}/series.html?c={slug}" for slug in db.scalars(
        select(Season.slug).where(Season.is_public.is_(True), Season.is_active.is_(True), Season.slug.is_not(None))
    )]
    urls += [f"{base}/event-page.html?e={slug}" for slug in db.scalars(select(Event.slug).where(Event.is_public.is_(True)))]
    items = "\n".join(f"  <url><loc>{escape(url)}</loc></url>" for url in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}\n</urlset>\n')


@api_router.get("/site/legal", response_model=LegalOut)
def legal() -> LegalOut:
    """Chi gestisce il sito, per le pagine privacy e termini (da LEGAL_* sul server)."""
    settings = get_settings()
    return LegalOut(name=settings.legal_name, email=settings.legal_email, address=settings.legal_address,
                    vat_id=settings.legal_vat_id, complete=bool(settings.legal_name and settings.legal_email))


# ── Statistiche delle visite ─────────────────────────────────────────────

def _not_counted(request: Request) -> bool:
    agent = request.headers.get("user-agent", "")
    return (not agent or bool(BOTS.search(agent))
            or request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1")


def _device(width: int) -> str:
    if width and width < 640:
        return "mobile"
    if width and width < 1024:
        return "tablet"
    return "desktop"


def _count(db: Session, match: dict, entry: int) -> None:
    where = [getattr(PageView, key) == value for key, value in match.items()]
    bump = update(PageView).where(*where).values(views=PageView.views + 1, entries=PageView.entries + entry)
    if db.execute(bump).rowcount == 0:
        db.add(PageView(**match, views=1, entries=entry))
        try:
            db.commit()
            return
        except IntegrityError:   # un'altra richiesta ha appena creato la stessa riga
            db.rollback()
            db.execute(bump)
    db.commit()


@api_router.post("/analytics/hit", status_code=204)
@limiter.limit("60/minute")
def page_hit(request: Request, payload: PageHitIn, db: Session = Depends(get_db)) -> Response:
    """Una pagina vista. Risponde sempre 204: chi non viene contato non lo sa."""
    if not get_settings().analytics_enabled or _not_counted(request):
        return Response(status_code=204)
    path = urlsplit(payload.path).path or "/"
    path = "/index.html" if path == "/" else path
    if not PAGE.match(path):
        return Response(status_code=204)
    host = (urlsplit(payload.referrer).hostname or "").lower().removeprefix("www.")[:120]
    # Dal sito stesso: lo dice il dominio della pagina che manda il conteggio
    # (Origin o Referer della richiesta), anche dietro un proxy.
    sender = request.headers.get("origin") or request.headers.get("referer") or ""
    own = {(urlsplit(url).hostname or "").lower().removeprefix("www.")
           for url in (site_url(request), sender, str(request.url))} - {""}
    internal = host in own
    _count(db, {"day": local_today(), "path": path, "referrer": "" if internal else host,
                "device": _device(payload.width)}, entry=0 if internal else 1)
    return Response(status_code=204)


@api_router.get("/admin/analytics", response_model=AnalyticsOut)
def analytics(
    days: int = Query(30, ge=1, le=365),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AnalyticsOut:
    """Le visite degli ultimi giorni: per giorno, pagine, provenienza e schermi."""
    since = local_today() - timedelta(days=days - 1)
    rows = db.scalars(select(PageView).where(PageView.day >= since)).all()
    per_day: dict = {since + timedelta(days=i): [0, 0] for i in range(days)}
    pages: Counter = Counter()
    referrers: Counter = Counter()
    devices: Counter = Counter()
    for row in rows:
        per_day.setdefault(row.day, [0, 0])
        per_day[row.day][0] += row.views
        per_day[row.day][1] += row.entries
        pages[row.path] += row.views
        if row.entries:
            referrers[row.referrer] += row.entries
        devices[row.device] += row.views

    def top(counter: Counter, n: int) -> list[AnalyticsCountOut]:
        return [AnalyticsCountOut(label=label, count=count) for label, count in counter.most_common(n)]

    return AnalyticsOut(
        enabled=get_settings().analytics_enabled,
        total_views=sum(v for v, _ in per_day.values()),
        total_entries=sum(e for _, e in per_day.values()),
        days=[AnalyticsDayOut(day=day, views=v, entries=e) for day, (v, e) in sorted(per_day.items())],
        pages=top(pages, 15), referrers=top(referrers, 10), devices=top(devices, 3),
    )
