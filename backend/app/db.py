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


def sync_alembic() -> None:
    """Porta il database all'ultima revisione Alembic.

    Un database che non ha mai visto Alembic (quello di produzione di oggi, o
    uno appena creato da create_all) viene solo timbrato con la revisione di
    partenza: lo schema c'è già. Dalla prossima revisione in poi si applica
    davvero, e le colonne nuove non si aggiungono più a mano.
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
            else:
                command.stamp(config, "head")
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
            Base.metadata.create_all(bind=engine)
            migrate_existing_schema()
            sync_alembic()
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
            # I tornei preesistenti sono serate di negozio finche non si dice altro.
            add_column(connection, columns, "tournaments", "event_type", "VARCHAR(40)", "'locals'")
            add_nullable_column(connection, columns, "tournaments", "latitude",  "FLOAT")
            add_nullable_column(connection, columns, "tournaments", "longitude", "FLOAT")
            add_nullable_column(connection, columns, "tournaments", "event_id", "INTEGER")
            add_column(connection, columns, "tournaments", "game", "VARCHAR(20)", "'mtg'")
            add_nullable_column(connection, columns, "tournaments", "location_id", "INTEGER")
            add_nullable_column(connection, columns, "tournaments", "series_id", "INTEGER")
            add_column(connection, columns, "tournaments", "pod_size", "INTEGER", "0")
            add_column(connection, columns, "tournaments", "team_size", "INTEGER", "1")
            add_column(connection, columns, "tournaments", "is_online", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "online_platform", "VARCHAR(30)", "''")
            add_column(connection, columns, "tournaments", "online_link", "VARCHAR(300)", "''")
            add_column(connection, columns, "tournaments", "sanction_id", "VARCHAR(60)", "''")
            add_column(connection, columns, "tournaments", "invites", "INTEGER", "0")
            add_column(connection, columns, "tournaments", "source", "VARCHAR(20)", "''")
            add_column(connection, columns, "tournaments", "external_id", "VARCHAR(40)", "''")
            add_column(connection, columns, "tournaments", "external_url", "VARCHAR(400)", "''")
            add_column(connection, columns, "tournaments", "best_of", "INTEGER", "3")
            add_column(connection, columns, "tournaments", "allow_intentional_draws", "BOOLEAN", "1")

        if "users" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("users")}
            add_nullable_column(connection, columns, "users", "organization_id", "INTEGER")
            add_nullable_column(connection, columns, "users", "guardian_id", "INTEGER")
            add_column(connection, columns, "users", "is_guest", "BOOLEAN", "0")
            add_nullable_column(connection, columns, "users", "terms_accepted_at", "TIMESTAMP WITH TIME ZONE")
            add_column(connection, columns, "users", "token_version", "INTEGER", "0")
            add_column(connection, columns, "users", "public_id", "VARCHAR(16)", "''")
            _fill_public_ids(connection)

        if "registrations" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("registrations")}
            add_column(connection, columns, "registrations", "dropped",    "BOOLEAN", "0")
            add_column(connection, columns, "registrations", "waitlisted", "BOOLEAN", "0")
            add_nullable_column(connection, columns, "registrations", "promoted_at", "DATETIME")
            add_column(connection, columns, "registrations", "prize_note", "VARCHAR(240)", "''")
            add_column(connection, columns, "registrations", "byes", "INTEGER", "0")
            add_nullable_column(connection, columns, "registrations", "fixed_table", "INTEGER")
            add_nullable_column(connection, columns, "registrations", "pod", "INTEGER")
            add_nullable_column(connection, columns, "registrations", "pod_seat", "INTEGER")
            add_nullable_column(connection, columns, "registrations", "team_id", "INTEGER")
            add_nullable_column(connection, columns, "registrations", "team_seat", "INTEGER")
            add_column(connection, columns, "registrations", "game_handle", "VARCHAR(80)", "''")
            add_nullable_column(connection, columns, "registrations", "prize_given_at", "TIMESTAMP WITH TIME ZONE")
            add_nullable_column(connection, columns, "registrations", "prize_given_by_id", "INTEGER")
            add_column(connection, columns, "registrations", "day2", "BOOLEAN", "0")

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

        if "organizations" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("organizations")}
            add_column(connection, columns, "organizations", "description", "TEXT", "''")
            add_column(connection, columns, "organizations", "city",        "VARCHAR(120)", "''")
            add_column(connection, columns, "organizations", "address",     "VARCHAR(240)", "''")
            add_column(connection, columns, "organizations", "website",     "VARCHAR(240)", "''")
            add_column(connection, columns, "organizations", "logo_url",    "VARCHAR(400)", "''")
            add_nullable_column(connection, columns, "organizations", "latitude",  "FLOAT")
            add_nullable_column(connection, columns, "organizations", "longitude", "FLOAT")
            add_column(connection, columns, "organizations", "is_premium",  "BOOLEAN", "0")
            add_column(connection, columns, "organizations", "stripe_account_id", "VARCHAR(64)", "''")
            add_column(connection, columns, "organizations", "stripe_charges_enabled", "BOOLEAN", "0")
            add_column(connection, columns, "organizations", "paypal_email", "VARCHAR(254)", "''")
            add_column(connection, columns, "organizations", "source", "VARCHAR(20)", "''")
            add_column(connection, columns, "organizations", "external_id", "VARCHAR(40)", "''")

        if "seasons" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("seasons")}
            add_nullable_column(connection, columns, "seasons", "organization_id", "INTEGER")
            add_nullable_column(connection, columns, "seasons", "slug", "VARCHAR(120)")
            add_column(connection, columns, "seasons", "description", "TEXT", "''")
            add_nullable_column(connection, columns, "seasons", "starts_on", "DATE")
            add_nullable_column(connection, columns, "seasons", "ends_on", "DATE")
            add_column(connection, columns, "seasons", "points_participation",  "INTEGER", "0")
            add_column(connection, columns, "seasons", "points_champion_bonus", "INTEGER", "0")
            add_nullable_column(connection, columns, "seasons", "qualification_threshold", "INTEGER")
            add_column(connection, columns, "seasons", "is_public", "BOOLEAN", "1")

        if "rounds" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("rounds")}
            add_nullable_column(connection, columns, "rounds", "format", "VARCHAR(80)")

        if "tournament_staff" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("tournament_staff")}
            # Lo staff pre-esistente era piatto: diventa judge, il capojudge lo
            # nomina l'organizzatore.
            add_column(connection, columns, "tournament_staff", "role", "VARCHAR(32)", "'judge'")

        if "pairings" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("pairings")}
            add_nullable_column(connection, columns, "pairings", "assigned_judge_id", "INTEGER")
            add_column(connection, columns, "pairings", "table_status", "VARCHAR(20)", "'playing'")

        if "announcements" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("announcements")}
            add_column(connection, columns, "announcements", "targeted", "BOOLEAN", "0")
            add_column(connection, columns, "announcements", "audience", "VARCHAR(240)", "''")

        if "payments" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("payments")}
            add_column(connection, columns, "payments", "refund_reason", "TEXT", "''")
            add_nullable_column(connection, columns, "payments", "refund_requested_at", "DATETIME")
            add_column(connection, columns, "payments", "payee", "VARCHAR(300)", "''")

        # Indici per le query più frequenti durante il carico
        _ensure_index(connection, "idx_registrations_tournament", "registrations", "tournament_id")
        _ensure_index(connection, "idx_registrations_player",     "registrations", "player_id")
        _ensure_index(connection, "idx_pairings_round",           "pairings",      "round_id")
        _ensure_index(connection, "idx_rounds_tournament",        "rounds",        "tournament_id")
        _ensure_index(connection, "idx_payments_registration",    "payments",      "registration_id")
        _ensure_index(connection, "idx_decklists_registration",   "decklists",     "registration_id")
        migrate_decklists_per_format(connection)
        _ensure_index(connection, "idx_tournament_staff_user",    "tournament_staff", "user_id")
        _ensure_index(connection, "idx_tournaments_event_type",   "tournaments",   "event_type")
        _ensure_index(connection, "idx_announcement_recipients_user",
                      "announcement_recipients", "user_id")

        if not _is_sqlite:
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


def migrate_decklists_per_format(connection) -> None:
    """Toglie lo unique su decklists.registration_id per permettere una lista
    per segmento di formato.

    SQLite non sa eliminare un vincolo dichiarato nella CREATE TABLE: l'unica
    strada e ricostruire la tabella e ricopiare le righe. Su PostgreSQL basta
    scambiare i vincoli. In entrambi i casi le liste esistenti diventano la
    lista principale (format vuoto), che e quello che gia erano.
    """
    inspector = inspect(connection)
    if "decklists" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("decklists")}
    if "format" in columns:
        return   # gia migrata

    if not _is_sqlite:
        connection.execute(text(
            "ALTER TABLE decklists ADD COLUMN format VARCHAR(80) NOT NULL DEFAULT ''"))
        # Nome che PostgreSQL genera da solo per un unique=True di colonna.
        connection.execute(text(
            "ALTER TABLE decklists DROP CONSTRAINT IF EXISTS decklists_registration_id_key"))
        connection.execute(text(
            "ALTER TABLE decklists ADD CONSTRAINT uq_decklists_registration_format "
            "UNIQUE (registration_id, format)"))
        return

    # SQLite: tabella nuova, copia, scambio. Le foreign key restano spente per
    # tutta l'operazione, altrimenti eliminare la vecchia tabella le farebbe
    # scattare sulle righe che la referenziano.
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql("""
        CREATE TABLE decklists_migrated (
            id INTEGER NOT NULL PRIMARY KEY,
            registration_id INTEGER NOT NULL,
            format VARCHAR(80) NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL,
            main_count INTEGER NOT NULL,
            side_count INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL,
            validation_errors TEXT NOT NULL,
            submitted_at DATETIME NOT NULL,
            UNIQUE (registration_id, format),
            FOREIGN KEY(registration_id) REFERENCES registrations (id) ON DELETE CASCADE
        )
    """)
    connection.exec_driver_sql("""
        INSERT INTO decklists_migrated
            (id, registration_id, format, raw_text, main_count, side_count,
             status, validation_errors, submitted_at)
        SELECT id, registration_id, '', raw_text, main_count, side_count,
               status, validation_errors, submitted_at
        FROM decklists
    """)
    copiate = connection.exec_driver_sql("SELECT COUNT(*) FROM decklists_migrated").scalar()
    originali = connection.exec_driver_sql("SELECT COUNT(*) FROM decklists").scalar()
    if copiate != originali:
        # Meglio interrompere con la tabella vecchia intatta che perdere liste.
        raise RuntimeError(
            f"Migrazione decklists interrotta: copiate {copiate} righe su {originali}")
    connection.exec_driver_sql("DROP TABLE decklists")
    connection.exec_driver_sql("ALTER TABLE decklists_migrated RENAME TO decklists")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_decklists_registration ON decklists (registration_id)")
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


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


def _fill_public_ids(connection) -> None:
    """Un identificativo pubblico agli account che non ce l'hanno ancora."""
    from backend.app.models import new_public_id

    rows = connection.execute(text("SELECT id FROM users WHERE public_id IS NULL OR public_id = ''")).fetchall()
    for (user_id,) in rows:
        connection.execute(
            text("UPDATE users SET public_id = :pid WHERE id = :id"),
            {"pid": new_public_id(), "id": user_id},
        )


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
