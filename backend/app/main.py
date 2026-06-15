import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from backend.app.core.alerting import send_alert
from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.core.monitoring import metrics_middleware, metrics_response
from backend.app.core.redis import redis_is_real
from backend.app.db import create_all, engine
from backend.app.routers import admin, auth, organizations, payments, push, seasons, tournaments

settings = get_settings()
logger = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inizializza il DB e avvia il watchdog di alerting."""
    create_all()
    tasks: list[asyncio.Task] = []
    if settings.watchdog_interval_secs > 0:
        tasks.append(asyncio.create_task(_db_watchdog(settings.watchdog_interval_secs)))
    # Sweeper waitlist ogni 10 minuti (riaccoda i promossi non paganti scaduti).
    tasks.append(asyncio.create_task(_waitlist_sweeper(600)))
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    return response


# Middleware metriche Prometheus (timing + conteggio richieste)
app.middleware("http")(metrics_middleware)


app.include_router(auth.router, prefix="/api")
app.include_router(tournaments.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(seasons.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """Health check profondo: verifica DB e backend cache (Redis o memoria)."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "cache": "redis" if redis_is_real() else "memory",
    }


@app.get("/metrics")
def metrics(request: Request):
    """Metriche Prometheus. Se METRICS_TOKEN è impostato, richiede ?token=..."""
    if settings.metrics_token:
        if request.query_params.get("token") != settings.metrics_token:
            raise HTTPException(status_code=403, detail="Invalid metrics token")
    return metrics_response()


@app.get("/")
def root() -> dict:
    return {
        "message": "Manabind API",
        "docs":     "/docs",
        "frontend": "http://localhost:5173",
    }
