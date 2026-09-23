"""
db.py — Il collegamento al database, e lo schema.

Lo schema lo descrivono i modelli (models.py) e lo applica Alembic: qui non si
scrive più nessuna ALTER TABLE a mano. Fino al 23 settembre 2026 c'erano 170
righe che rincorrevano lo schema a ogni avvio; sono state tolte dopo aver
verificato che un database creato con quelle e uno creato dai soli modelli
escono identici, su SQLite e su PostgreSQL.

Resta di questo file: l'engine con il suo pool, la sessione per le richieste,
l'allineamento ad Alembic allo startup, la RLS di Supabase (non è una
migrazione: vale anche per le tabelle che arriveranno) e i due seed.
"""
import os
from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import DateTime, TypeDecorator, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings


class UtcDateTime(TypeDecorator):
    """DateTime che torna sempre timezone-aware in UTC.

    SQLite non conserva il fuso: scrive l'ora di muro e la rilegge naive. Pydantic
    la serializza senza offset e il browser la interpreta come ora locale — un round
    da 50 minuti avviato da Roma partiva da -70 (50 meno le 2 ore di CEST).
    Su PostgreSQL le `timestamptz` arrivano già aware e passano di qui intatte.
    """

    impl = DateTime
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

settings = get_settings()

# ── Engine con connection pooling ottimizzato per il carico ──────────────────
# SQLite: non supporta write concorrenti → pool size 1 in sviluppo
# PostgreSQL: pool configurabile per carichi elevati

_is_sqlite = settings.database_url.startswith("sqlite")

connect_args = {"check_same_thread": False} if _is_sqlite else {}

_WORKERS = int(os.environ.get("WEB_CONCURRENCY", 1))

# Con N worker Gunicorn, ogni worker ha il suo pool separato.
# Budget totale: 80 connessioni (PostgreSQL default max_connections=100, 20 riservati).
# Per worker: 80 // N connessioni massime, suddivise tra pool base e overflow.
# Esempio: 4 worker → 20/worker → pool_size=10, max_overflow=10 → 80 connessioni totali

_per_worker   = max(5, 80 // _WORKERS)   # connessioni budget per worker

# DB_POOL_SIZE sostituisce il calcolo: un PostgreSQL gestito (Supabase, piano
# gratuito) regge molte meno delle 80 connessioni previste qui.
if "DB_POOL_SIZE" in os.environ:
    _pool_size    = int(os.environ["DB_POOL_SIZE"])
    _max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", _pool_size))
else:
    _pool_size    = _per_worker // 2          # pool sempre aperto
    _max_overflow = _per_worker - _pool_size  # burst temporaneo

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_timeout=30,
    pool_recycle=1800,
)

# Ottimizzazioni SQLite per sviluppo locale
if _is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")    # Write-Ahead Logging
        cursor.execute("PRAGMA synchronous=NORMAL")  # Bilanciamento durabilità/perf
        cursor.execute("PRAGMA cache_size=-64000")   # 64 MB cache
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_alembic(database_was_empty: bool = False) -> None:
    """Porta il database all'ultima revisione Alembic.

    Tre casi, e vanno distinti:
      - già timbrato: si applicano le revisioni che mancano;
      - database vuoto fino a un attimo fa: le tabelle le ha appena fatte
        create_all dai modelli, quindi è già all'ultima revisione e si timbra
        head senza eseguire niente;
      - database che esisteva prima di Alembic (uno ripristinato da un backup
        vecchio): si timbra la revisione di partenza, che descrive lo schema, e
        si applicano le successive — che possono toccare anche i dati, come il
        riempimento dei public_id.
    """
    import logging
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            if "alembic_version" in inspect(connection).get_table_names():
                command.upgrade(config, "head")
            elif database_was_empty:
                command.stamp(config, "head")
            else:
                command.stamp(config, "0001_baseline")
                command.upgrade(config, "head")
    except Exception as exc:   # noqa: BLE001 — il sito parte comunque, ma si sa
        logging.getLogger(__name__).error("Migrazioni non applicate: %s", exc)


def create_all() -> None:
    # Retry con backoff: allo startup (es. subito dopo `docker-compose up`) il DB
    # può non essere ancora pronto. Senza retry tutti i worker Gunicorn crashano
    # in blocco con "connection refused". Riproviamo invece di morire al primo errore.
    import logging
    import time

    from sqlalchemy.exc import OperationalError

    from backend.app import models  # noqa: F401

    last_error: Exception | None = None
    for attempt in range(1, 11):
        try:
            with engine.begin() as connection:
                # Prima di creare: se non c'era niente, lo schema che nasce ora è
                # già l'ultimo, e le revisioni non hanno nulla da recuperare.
                was_empty = not inspect(connection).get_table_names()
            Base.metadata.create_all(bind=engine)
            sync_alembic(database_was_empty=was_empty)
            # Dopo le migrazioni: una revisione può aver creato tabelle nuove,
            # e anche quelle vanno chiuse alla REST di Supabase.
            apply_row_level_security()
            seed_default_organization()
            seed_store_owners()
            return
        except OperationalError as exc:
            last_error = exc
            wait = min(attempt * 0.5, 3.0)
            logging.getLogger(__name__).warning(
                "DB non raggiungibile (tentativo %d/10), riprovo tra %.1fs...", attempt, wait
            )
            time.sleep(wait)
    raise RuntimeError("Impossibile connettersi al database allo startup") from last_error




def apply_row_level_security() -> None:
    """RLS su tutte le tabelle, a ogni avvio.

    Non e' una migrazione ed e' per questo che non sta in Alembic: vale anche
    per le tabelle che una revisione futura aggiungera', e ripeterla non costa
    niente. Su SQLite non esiste.
    """
    if _is_sqlite:
        return
    with engine.begin() as connection:
        # Con piu' worker Gunicorn partono tutti insieme: il lock (rilasciato al
        # commit) fa passare uno alla volta.
        connection.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        enable_row_level_security(connection)


def enable_row_level_security(connection) -> None:
    """RLS attiva su ogni tabella dello schema, senza nessuna policy.

    Supabase espone lo schema public via REST ai ruoli anon e authenticated:
    senza RLS chi ha la chiave pubblica del progetto leggerebbe le tabelle,
    utenti compresi. Con la RLS attiva e nessuna policy quei ruoli non vedono
    niente. L'app non ne risente: si collega col ruolo che ha creato le
    tabelle, e il proprietario la RLS non la subisce (salvo FORCE).
    Su un PostgreSQL qualunque non cambia nulla, e ripeterla è innocuo.
    """
    for table in inspect(connection).get_table_names():
        connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))




DEFAULT_ORG_SLUG = "mull2five"
# Lo slug che il negozio di default aveva prima del rebrand: i database creati
# allora vengono aggiornati una volta sola, in seed_default_organization.
LEGACY_DEFAULT_ORG_SLUG = "arcana"


def seed_store_owners() -> None:
    """Prima dello staff, far parte di un negozio voleva dire averlo come
    organization_id. Chi organizzava così per un negozio vero ne diventa
    titolare, una volta sola: solo i negozi ancora senza staff. Il negozio di
    default resta fuori: alla registrazione ci finiscono tutti."""
    with engine.begin() as connection:
        if not _is_sqlite:
            connection.execute(text("SELECT pg_advisory_xact_lock(727275)"))
        connection.execute(
            text(
                "INSERT INTO store_members (organization_id, user_id, role, created_at) "
                "SELECT u.organization_id, u.id, 'owner', CURRENT_TIMESTAMP "
                "FROM users u JOIN organizations o ON o.id = u.organization_id "
                "WHERE o.is_default = :no AND u.role IN ('organizer', 'admin') "
                "AND NOT EXISTS (SELECT 1 FROM store_members m WHERE m.organization_id = o.id)"
            ),
            {"no": False if not _is_sqlite else 0},
        )


def seed_default_organization() -> None:
    """Crea l'organizzazione di default (se assente) e collega utenti/tornei orfani.
    Serializzato con lo stesso advisory lock delle migrazioni su PostgreSQL."""
    with engine.begin() as connection:
        if not _is_sqlite:
            connection.execute(text("SELECT pg_advisory_xact_lock(727275)"))
        inspector = inspect(connection)
        if "organizations" not in inspector.get_table_names():
            return
        row = connection.execute(
            text("SELECT id FROM organizations WHERE is_default = :d"),
            {"d": True if not _is_sqlite else 1},
        ).first()
        if row is None:
            connection.execute(
                text(
                    "INSERT INTO organizations (slug, name, is_default, created_at) "
                    "VALUES (:s, :n, :d, CURRENT_TIMESTAMP)"
                ),
                {"s": DEFAULT_ORG_SLUG, "n": "Mull2Five", "d": True if not _is_sqlite else 1},
            )
            row = connection.execute(
                text("SELECT id FROM organizations WHERE slug = :s"), {"s": DEFAULT_ORG_SLUG}
            ).first()
        org_id = row[0]
        # Rebrand: il negozio di default nasceva con lo slug vecchio, che compare
        # negli indirizzi pubblici (store.html?s=...). Lo si rinomina se nessun
        # altro negozio ha già preso quello nuovo.
        connection.execute(
            text(
                "UPDATE organizations SET slug = :new WHERE id = :o AND slug = :old "
                "AND NOT EXISTS (SELECT 1 FROM organizations WHERE slug = :new)"
            ),
            {"new": DEFAULT_ORG_SLUG, "old": LEGACY_DEFAULT_ORG_SLUG, "o": org_id},
        )
        # Backfill: tutto ciò che non ha ancora un'organizzazione finisce nel default.
        for table in ("users", "tournaments"):
            if table in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns(table)}
                if "organization_id" in cols:
                    connection.execute(
                        text(f"UPDATE {table} SET organization_id = :o WHERE organization_id IS NULL"),
                        {"o": org_id},
                    )








