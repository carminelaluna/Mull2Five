import os
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings

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
            Base.metadata.create_all(bind=engine)
            migrate_existing_schema()
            seed_default_organization()
            return
        except OperationalError as exc:
            last_error = exc
            wait = min(attempt * 0.5, 3.0)
            logging.getLogger(__name__).warning(
                "DB non raggiungibile (tentativo %d/10), riprovo tra %.1fs...", attempt, wait
            )
            time.sleep(wait)
    raise RuntimeError("Impossibile connettersi al database allo startup") from last_error


def migrate_existing_schema() -> None:
    with engine.begin() as connection:
        # Con più worker Gunicorn, tutti eseguono le migrazioni in parallelo allo
        # startup: senza serializzazione si scatena una race ("column already exists")
        # e su PostgreSQL un singolo DDL fallito aborta l'intera transazione.
        # Un advisory lock a livello di transazione (auto-rilasciato al commit) fa sì
        # che un solo worker alla volta esegua le migrazioni; gli altri attendono e
        # poi trovano le colonne già presenti. Su SQLite è un no-op.
        if not _is_sqlite:
            connection.execute(text("SELECT pg_advisory_xact_lock(727274)"))

        inspector = inspect(connection)
        if "tournaments" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("tournaments")}
            add_column(connection, columns, "tournaments", "structure",                "VARCHAR(32)", "'swiss'")
            add_column(connection, columns, "tournaments", "swiss_rounds",             "INTEGER",     "0")
            add_column(connection, columns, "tournaments", "top_cut_size",             "INTEGER",     "8")
            add_column(connection, columns, "tournaments", "check_in_required",        "BOOLEAN",     "0")
            add_nullable_column(connection, columns, "tournaments", "decklist_deadline", "DATETIME")
            add_column(connection, columns, "tournaments", "self_check_in_enabled",    "BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "late_registration_enabled","BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "registration_mode",        "VARCHAR(32)", "'open'")
            add_column(connection, columns, "tournaments", "pairings_public",          "BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "standings_public",         "BOOLEAN",     "1")
            add_column(connection, columns, "tournaments", "decklists_public",         "BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "round_timer_minutes",      "INTEGER",     "50")
            add_column(connection, columns, "tournaments", "refund_policy",            "TEXT",        "''")
            add_column(connection, columns, "tournaments", "invite_code_required",     "BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "email_notifications_enabled","BOOLEAN",   "0")
            add_column(connection, columns, "tournaments", "legal_validation_enabled", "BOOLEAN",     "0")
            add_column(connection, columns, "tournaments", "description",              "TEXT",        "''")
            add_nullable_column(connection, columns, "tournaments", "season_id", "INTEGER")
            add_column(connection, columns, "tournaments", "pay_at_event", "BOOLEAN", "1")
            add_column(connection, columns, "tournaments", "pay_stripe",   "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "pay_paypal",   "BOOLEAN", "0")
            add_nullable_column(connection, columns, "tournaments", "organization_id", "INTEGER")
            add_nullable_column(connection, columns, "tournaments", "start_time", "VARCHAR(5)")

        if "users" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("users")}
            add_nullable_column(connection, columns, "users", "organization_id", "INTEGER")

        if "registrations" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("registrations")}
            add_column(connection, columns, "registrations", "dropped",    "BOOLEAN", "0")
            add_column(connection, columns, "registrations", "waitlisted", "BOOLEAN", "0")
            add_nullable_column(connection, columns, "registrations", "promoted_at", "DATETIME")

        if "rounds" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("rounds")}
            add_column(connection, columns, "rounds", "phase",        "VARCHAR(32)", "'swiss'")
            add_column(connection, columns, "rounds", "is_published", "BOOLEAN",     "1")
            add_nullable_column(connection, columns, "rounds", "starts_at", "DATETIME")
            add_nullable_column(connection, columns, "rounds", "ends_at",   "DATETIME")

        if "pairings" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("pairings")}
            add_column(connection, columns, "pairings", "match_wins_a", "INTEGER", "0")
            add_column(connection, columns, "pairings", "match_wins_b", "INTEGER", "0")
            add_column(connection, columns, "pairings", "draws",        "INTEGER", "0")
            add_column(connection, columns, "pairings", "extra_seconds","INTEGER", "0")

        if "payments" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("payments")}
            add_column(connection, columns, "payments", "refund_reason", "TEXT", "''")
            add_nullable_column(connection, columns, "payments", "refund_requested_at", "DATETIME")

        # Indici per le query più frequenti durante il carico
        _ensure_index(connection, "idx_registrations_tournament", "registrations", "tournament_id")
        _ensure_index(connection, "idx_registrations_player",     "registrations", "player_id")
        _ensure_index(connection, "idx_pairings_round",           "pairings",      "round_id")
        _ensure_index(connection, "idx_rounds_tournament",        "rounds",        "tournament_id")
        _ensure_index(connection, "idx_payments_registration",    "payments",      "registration_id")
        _ensure_index(connection, "idx_decklists_registration",   "decklists",     "registration_id")


DEFAULT_ORG_SLUG = "arcana"


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
                {"s": DEFAULT_ORG_SLUG, "n": "Manabind", "d": True if not _is_sqlite else 1},
            )
            row = connection.execute(
                text("SELECT id FROM organizations WHERE slug = :s"), {"s": DEFAULT_ORG_SLUG}
            ).first()
        org_id = row[0]
        # Backfill: tutto ciò che non ha ancora un'organizzazione finisce nel default.
        for table in ("users", "tournaments"):
            if table in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns(table)}
                if "organization_id" in cols:
                    connection.execute(
                        text(f"UPDATE {table} SET organization_id = :o WHERE organization_id IS NULL"),
                        {"o": org_id},
                    )


def add_column(connection, existing_columns, table_name, column_name, column_type, default):
    if column_name in existing_columns:
        return
    # PostgreSQL è severo sui tipi del DEFAULT: per le colonne BOOLEAN non accetta
    # 0/1 (validi solo su SQLite) e richiede false/true. Normalizziamo qui così le
    # stesse migrazioni funzionano su entrambi i database.
    if column_type.upper() == "BOOLEAN":
        default = {"0": "false", "1": "true"}.get(str(default), default)
    connection.execute(
        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default} NOT NULL")
    )
    existing_columns.add(column_name)


def add_nullable_column(connection, existing_columns, table_name, column_name, column_type):
    if column_name in existing_columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
    existing_columns.add(column_name)


def _ensure_index(connection, index_name: str, table_name: str, column: str) -> None:
    """Crea un indice solo se non esiste già (SQLite e PostgreSQL compatible)."""
    import logging
    try:
        connection.execute(
            text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column})")
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback per DB che non supportano IF NOT EXISTS — non bloccante
        logging.getLogger(__name__).warning("Could not create index %s: %s", index_name, exc)
