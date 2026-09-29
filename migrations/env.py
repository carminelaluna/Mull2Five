"""
env.py — Come Alembic si collega al database.

L'indirizzo arriva dalle impostazioni dell'app (DATABASE_URL), così una
migrazione si applica allo stesso database che usa il sito. I modelli servono
ad `alembic revision --autogenerate` e al confronto in CI.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app import models  # noqa: F401 — registra le tabelle su Base
from backend.app.db import DATABASE_URL, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `DATABASE_URL` e non `settings.database_url`: è lo stesso indirizzo, ma col
# driver normalizzato — `postgresql://` da solo manderebbe Alembic a cercare
# psycopg2, che questo progetto non installa.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def non_aspettare_i_lock(connection) -> None:
    """Un `ALTER TABLE` che non ottiene il lock deve fallire, non appendersi.

    Il 29/09/2026 una transazione lasciata aperta dall'istanza precedente ha
    bloccato l'`ALTER TABLE` di una migrazione. Le migrazioni girano dentro
    l'avvio e uvicorn apre la porta solo dopo: da fuori si vedeva un servizio
    che non parte, e il deploy è scaduto due volte prima che si capisse.
    Cinque secondi, poi la migrazione fallisce dicendo cosa sta aspettando.

    `LOCAL`: vale per la transazione della migrazione e sparisce al commit, così
    non resta appiccicato alla connessione che l'app rimette nel pool.
    """
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Se chi chiama ha già una connessione aperta (l'avvio dell'app), si usa quella.
    connection = config.attributes.get("connection", None)
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            non_aspettare_i_lock(connection)
            context.run_migrations()
        return

    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as conn:
        # SQLite non sa cambiare una colonna al volo: batch mode riscrive la tabella.
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            non_aspettare_i_lock(conn)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
