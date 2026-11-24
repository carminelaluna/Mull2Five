import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.gzip import GZipMiddleware

from backend.app.core.alerting import alerting_enabled, send_alert
from backend.app.core.config import LOCAL_ENVS, get_settings
from backend.app.core.limiter import limiter
from backend.app.core.monitoring import metrics_middleware, metrics_response
from backend.app.core.redis import redis_is_real
from backend.app.db import create_all, engine
from backend.app.routers import (
    admin,
    archive,
    auth,
    decks,
    events,
    games,
    google_auth,
    organizations,
    payments,
    public_api,
    push,
    seasons,
    site,
    tags,
    tickets,
    tournament_registrations,
    tournament_rounds,
    tournaments,
)
from backend.app.services import site_watch

settings = get_settings()
logger = logging.getLogger(__name__)
# Anche qui, non solo in prepara_database: uvicorn si può lanciare da solo.
if settings.secret_key_problem():
    raise RuntimeError(settings.secret_key_problem())
# Uvicorn configura solo i suoi logger: senza questo i nostri `logger.exception`
# non arrivavano nei log di Render, e un 500 non lasciava traccia (23/11/2026).
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def _db_watchdog(interval: int) -> None:
    """Self-check periodico del DB: alert quando va giù e quando si riprende."""
    healthy = True
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_ping_db)
            if not healthy:
                healthy = True
                send_alert("db-recovered", "Database tornato raggiungibile",
                           "Il watchdog ha ripristinato la connessione al database.", level="info")
        except Exception as exc:  # noqa: BLE001
            if healthy:
                healthy = False
                send_alert("db-down", "Database non raggiungibile",
                           f"Il watchdog non riesce a contattare il database: {exc}", level="critical")


def _ping_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


async def _waitlist_sweeper(interval: int) -> None:
    """Riaccoda periodicamente i promossi dalla waitlist che non hanno pagato (#32)."""
    from backend.app.db import SessionLocal
    from backend.app.routers.tournaments import sweep_waitlist_deadlines

    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                n = await asyncio.to_thread(sweep_waitlist_deadlines, db)
                if n:
                    logger.info("Waitlist sweeper: riaccodati %d giocatori", n)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel waitlist sweeper")


async def _hold_sweeper(interval: int) -> None:
    """Toglie le iscrizioni con pagamento online non arrivato in tempo."""
    from backend.app.db import SessionLocal
    from backend.app.services.registrations import release_unpaid_holds

    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                n = await asyncio.to_thread(release_unpaid_holds, db)
                if n:
                    logger.info("Pagamenti online non arrivati: tolte %d iscrizioni", n)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel togliere le iscrizioni non pagate")


async def _reminder_sweeper(interval: int) -> None:
    """Manda il promemoria del giorno prima ai tornei che non l'hanno ancora avuto."""
    from backend.app.db import SessionLocal
    from backend.app.services.reminders import send_event_reminders

    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                n = await asyncio.to_thread(send_event_reminders, db)
                if n:
                    logger.info("Promemoria: %d email per i tornei di domani", n)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel promemoria del giorno prima")


async def _mail_watcher(interval: int) -> None:
    """Le email arrivate alle caselle del sito, su Telegram. Il primo giro parte
    subito: prende nota di dove sono arrivate le caselle, e da lì si avvisa."""
    from backend.app.services.mail_watch import MailWatcher

    watcher = MailWatcher()
    while True:
        try:
            await asyncio.to_thread(watcher.check)
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel controllo delle caselle email")
        await asyncio.sleep(interval)


async def _site_watch(interval: int) -> None:
    """Il controllo da GitHub che non passa più, e il database vicino al limite."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(site_watch.check)
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel controllo del sito")


async def _heartbeat(interval: int) -> None:
    """Il battito verso Healthchecks.io: se smette, l'avviso arriva da fuori.

    Il primo aspetta un minuto: all'avvio la porta non è ancora aperta, e
    durante un deploy il dominio risponde ancora con l'istanza vecchia."""
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(site_watch.heartbeat)
        except Exception:  # noqa: BLE001
            logger.exception("Errore nel battito verso Healthchecks.io")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inizializza il DB e avvia il watchdog di alerting."""
    from backend.app.services.mail_watch import mail_watch_enabled

    create_all()
    tasks: list[asyncio.Task] = []
    if settings.watchdog_interval_secs > 0:
        tasks.append(asyncio.create_task(_db_watchdog(settings.watchdog_interval_secs)))
    if settings.mail_watch_interval_secs > 0 and mail_watch_enabled():
        tasks.append(asyncio.create_task(_mail_watcher(settings.mail_watch_interval_secs)))
    if settings.watchdog_interval_secs > 0 and alerting_enabled():
        tasks.append(asyncio.create_task(_site_watch(600)))
    if settings.heartbeat_url and settings.heartbeat_interval_secs > 0:
        tasks.append(asyncio.create_task(_heartbeat(settings.heartbeat_interval_secs)))
    # Sweeper waitlist ogni 10 minuti (riaccoda i promossi non paganti scaduti).
    tasks.append(asyncio.create_task(_waitlist_sweeper(600)))
    # Ogni due minuti: chi ha scelto di pagare online e non ha pagato non è iscritto.
    tasks.append(asyncio.create_task(_hold_sweeper(120)))
    # Promemoria ogni ora: cerca i tornei di domani che non l'hanno ancora avuto.
    tasks.append(asyncio.create_task(_reminder_sweeper(3600)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Cattura le eccezioni non gestite (500): logga, manda un alert e risponde JSON.
    Throttled per (metodo, path) così un endpoint rotto non genera spam infinito."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    logger.exception("Errore non gestito su %s %s", request.method, path)
    send_alert(
        f"5xx:{request.method}:{path}",
        f"Errore 500 su {request.method} {path}",
        f"{type(exc).__name__}: {exc}",
        level="error",
    )
    return JSONResponse(status_code=500, content={"detail": "Errore interno del server"})


def is_duplicate(exc: IntegrityError) -> bool:
    """La riga esiste già: un vincolo di unicità, non un altro guasto.

    PostgreSQL lo dice col codice 23505 (psycopg lo mette in `sqlstate`),
    SQLite solo a parole.
    """
    if getattr(exc.orig, "sqlstate", None) == "23505":
        return True
    return "UNIQUE constraint failed" in str(exc.orig)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Un doppio clic, o due persone che fanno la stessa cosa nello stesso istante.

    Il secondo "Genera turno" o la stessa iscrizione inviata due volte arrivano
    al vincolo di unicità del database, che fa il suo lavoro: la seconda riga
    non nasce. Prima però la risposta era un 500 "Errore interno" e un avviso
    su Telegram per un guasto che non c'era. Ora è un 409 che dice cosa fare.
    Gli altri vincoli violati (una chiave esterna, un campo obbligatorio) sono
    difetti veri e restano un 500 con l'avviso.
    """
    if not is_duplicate(exc):
        return await unhandled_exception_handler(request, exc)
    route = request.scope.get("route")
    logger.warning("Riga doppia su %s %s: %s", request.method,
                   getattr(route, "path", request.url.path), exc.orig)
    return JSONResponse(status_code=409, content={
        "detail": "Già fatto: la richiesta è arrivata due volte, o qualcun altro l'ha "
                  "appena fatta. Ricarica la pagina per vedere com'è adesso.",
    })


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Errori di validazione (422): trasforma la lista Pydantic in un messaggio
    leggibile (string), così il frontend può mostrarlo direttamente in `detail`
    invece di "[object Object]"."""
    parts = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        field = ".".join(loc) or "campo"
        parts.append(f"{field}: {err.get('msg', 'valore non valido')}")
    detail = "; ".join(parts) or "Dati non validi"
    return JSONResponse(status_code=422, content={"detail": detail})


if settings.app_env == "development":
    # In sviluppo accettiamo tutte le origini (Vite, Postman, browser diretto)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(settings.frontend_url), str(settings.app_url)],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# La Content-Security-Policy: script solo dal sito (la build non ne ha di inline),
# stili anche negli attributi style, immagini anche da fuori (loghi dei negozi,
# carte di Scryfall), chiamate solo al sito e a Nominatim. Se passa un'iniezione
# di HTML, uno script esterno non parte. /docs usa gli script di un CDN: lì no.
CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self' https://nominatim.openstreetmap.org",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))
NO_CSP = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]       = "geolocation=(self), camera=(), microphone=(), payment=()"
    # `robots.txt` chiede di non visitare; questa dice di non indicizzare, ed è
    # l'unica che tiene fuori una pagina raggiunta da un link esterno. Su una
    # copia — staging, sviluppo — devono valere entrambe.
    if settings.is_copy:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if not request.url.path.startswith(NO_CSP):
        response.headers["Content-Security-Policy"] = CSP
    # HSTS solo su HTTPS (Render mette il protocollo vero in X-Forwarded-Proto).
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


# Middleware metriche Prometheus (timing + conteggio richieste)
app.middleware("http")(metrics_middleware)

# Comprime le risposte (JSON e pagine) sopra 1KB: ultimo add_middleware, quindi
# il più esterno — comprime quello che esce da tutti gli altri, header compresi.
app.add_middleware(GZipMiddleware, minimum_size=1000)


_STATIC_ROOT_PATHS = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json",
                       "/robots.txt", "/sitemap.xml")


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    """Cache del browser per i file che serve StaticFiles (non le rotte /api).

    Gli asset in /assets/ hanno l'hash del contenuto nel nome (build Vite): se
    cambiano, cambia il nome, quindi si possono cache-are per sempre. Le pagine
    HTML e tutto il resto (icone, font, sw.js) non hanno hash: una build nuova
    deve vedersi subito, quindi restano senza cache lunga."""
    response = await call_next(request)
    if not settings.frontend_dist or request.url.path.startswith("/api/"):
        return response
    if request.url.path in _STATIC_ROOT_PATHS:
        return response
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


# Le richieste che non si spostano: API e webhook (Stripe e PayPal mandano POST
# all'indirizzo che conoscono, e un 301 su un POST non lo seguono), e i controlli
# di Render, che interrogano il servizio col suo nome interno.
_STAYS_ON_ANY_HOST = ("/api/", "/health", "/metrics")


@app.middleware("http")
async def redirect_to_site_domain(request: Request, call_next):
    """Chi arriva da `*.onrender.com` passa al dominio del sito (SITE_URL).

    Con un dominio vero l'indirizzo di Render resta raggiungibile, e i link
    vecchi — QR stampati, messaggi nei gruppi — continuano a portare lì: così
    arrivano alla pagina giusta sul dominio nuovo, e i motori di ricerca
    tengono un indirizzo solo. Sullo staging SITE_URL è l'indirizzo di Render
    stesso, quindi non si sposta niente.
    """
    target = urlsplit(settings.site_url)
    host = request.headers.get("host", "").split(":")[0].lower()
    if (
        target.hostname
        and host.endswith(".onrender.com")
        and host != target.hostname
        and request.method in ("GET", "HEAD")
        and not request.url.path.startswith(_STAYS_ON_ANY_HOST)
    ):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(
            f"{target.scheme}://{target.netloc}{request.url.path}{query}", status_code=301)
    return await call_next(request)


app.include_router(auth.router, prefix="/api")
app.include_router(google_auth.router, prefix="/api")
app.include_router(tournaments.router, prefix="/api")
# Dopo quello principale: le rotte del torneo in corso sono tutte più
# specifiche, e l'ordine di inclusione decide chi risponde.
app.include_router(tournament_rounds.router, prefix="/api")
app.include_router(tournament_registrations.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(seasons.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tags.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(games.router, prefix="/api")
app.include_router(decks.router, prefix="/api")
app.include_router(archive.router, prefix="/api")
app.include_router(public_api.router, prefix="/api")
app.include_router(site.api_router, prefix="/api")
app.include_router(site.router)   # robots.txt e sitemap.xml, alla radice


_NON_ANCORA = object()
_ATTESA: object | str | None = _NON_ANCORA


def _revisione_attesa() -> str | None:
    """L'ultima revisione che questo codice si porta dietro."""
    global _ATTESA
    if _ATTESA is _NON_ANCORA:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            root = Path(__file__).resolve().parents[2]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            _ATTESA = ScriptDirectory.from_config(config).get_current_head()
        except Exception:  # noqa: BLE001 — saperlo è un di più, non deve far cadere /health
            _ATTESA = None
    return _ATTESA


def _revisione_applicata() -> str | None:
    """La revisione che il database dice di avere. None se Alembic non l'ha mai toccato."""
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        return None


@app.get("/health")
def health(request: Request) -> dict:
    """Database, cache, e cosa sta girando davvero.

    Le ultime due voci sono nate da una giornata persa: il 29/09/2026, per sapere
    quale commit fosse in produzione, si è dovuto dedurlo dal nome di un file
    JavaScript, e per sapere se una migrazione era passata bisognava entrare nel
    back-office. Ora sono due domande a cui risponde una `curl`.

    Lo schema rimasto indietro degrada lo stato: una migrazione che fallisce non
    ferma l'avvio — `sync_alembic` la annota e basta — quindi senza questo il sito
    sembrerebbe sano mentre certi endpoint danno 500. Un database che Alembic non
    ha mai toccato (sviluppo, test) non è "indietro": è un altro caso.

    Il controllo da GitHub passa da qui ogni cinque minuti: se smette, il sito lo
    dice (services/site_watch.py).
    """
    if request.headers.get("user-agent", "").startswith(site_watch.STATUS_CHECK_AGENT):
        site_watch.status_check.seen()
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    applicata = _revisione_applicata() if db_ok else None
    attesa = _revisione_attesa()
    schema_indietro = bool(applicata and attesa and applicata != attesa)
    return {
        "status": "ok" if db_ok and not schema_indietro else "degraded",
        "database": "ok" if db_ok else "error",
        "cache": "redis" if redis_is_real() else "memory",
        "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7] or "sconosciuto",
        "schema": {"applicata": applicata, "attesa": attesa, "indietro": schema_indietro},
    }


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Metriche Prometheus, solo per chi ha METRICS_TOKEN.

    Il token arriva come `Authorization: Bearer …` (quello che manda Prometheus)
    o come `?token=…`. Senza METRICS_TOKEN le metriche si vedono solo sul
    proprio computer e nei test: fino al 24/11/2026 in produzione erano aperte a
    tutti, con memoria, processi e il traffico di ogni pagina.
    """
    expected = settings.metrics_token
    if not expected:
        if settings.app_env.strip().lower() not in LOCAL_ENVS:
            raise HTTPException(status_code=404, detail="Not Found")
        return metrics_response()
    header = request.headers.get("authorization", "")
    given = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Token delle metriche non valido")
    return metrics_response()


# In produzione le pagine del sito le serve questo stesso processo: un indirizzo
# solo per pagine e API, senza CORS e senza proxy davanti. In sviluppo
# FRONTEND_DIST non c'è, le pagine le serve Vite e la radice resta il JSON di sempre.
if settings.frontend_dist:
    _frontend_dist = Path(settings.frontend_dist)
    if not _frontend_dist.is_dir():
        # Meglio non partire che partire senza pagine: il deploy fallisce e lo dice.
        raise RuntimeError(f"FRONTEND_DIST={_frontend_dist} non esiste: manca la build del frontend")
    # Montata per ultima, così /api, /health e /docs restano alle loro rotte.
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def root() -> dict:
        return {
            "message": "Mull2Five API",
            "docs":     "/docs",
            "frontend": "http://localhost:5173",
        }
