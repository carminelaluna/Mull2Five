from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
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
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_existing_schema()


def migrate_existing_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "tournaments" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("tournaments")}
            add_column(connection, columns, "tournaments", "structure", "VARCHAR(32)", "'swiss'")
            add_column(connection, columns, "tournaments", "swiss_rounds", "INTEGER", "0")
            add_column(connection, columns, "tournaments", "top_cut_size", "INTEGER", "8")
            add_column(connection, columns, "tournaments", "check_in_required", "BOOLEAN", "0")
            add_nullable_column(connection, columns, "tournaments", "decklist_deadline", "DATETIME")
            add_column(connection, columns, "tournaments", "self_check_in_enabled", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "late_registration_enabled", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "registration_mode", "VARCHAR(32)", "'open'")
            add_column(connection, columns, "tournaments", "pairings_public", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "standings_public", "BOOLEAN", "1")
            add_column(connection, columns, "tournaments", "round_timer_minutes", "INTEGER", "50")
            add_column(connection, columns, "tournaments", "refund_policy", "TEXT", "''")
            add_column(connection, columns, "tournaments", "invite_code_required", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "email_notifications_enabled", "BOOLEAN", "0")
            add_column(connection, columns, "tournaments", "legal_validation_enabled", "BOOLEAN", "0")

        if "registrations" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("registrations")}
            add_column(connection, columns, "registrations", "dropped", "BOOLEAN", "0")

        if "rounds" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("rounds")}
            add_column(connection, columns, "rounds", "phase", "VARCHAR(32)", "'swiss'")
            add_column(connection, columns, "rounds", "is_published", "BOOLEAN", "1")
            add_nullable_column(connection, columns, "rounds", "starts_at", "DATETIME")
            add_nullable_column(connection, columns, "rounds", "ends_at", "DATETIME")

        if "pairings" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("pairings")}
            add_column(connection, columns, "pairings", "match_wins_a", "INTEGER", "0")
            add_column(connection, columns, "pairings", "match_wins_b", "INTEGER", "0")
            add_column(connection, columns, "pairings", "draws", "INTEGER", "0")

        if "payments" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("payments")}
            add_column(connection, columns, "payments", "refund_reason", "TEXT", "''")
            add_nullable_column(connection, columns, "payments", "refund_requested_at", "DATETIME")


def add_column(
    connection,
    existing_columns: set[str],
    table_name: str,
    column_name: str,
    column_type: str,
    default: str,
) -> None:
    if column_name in existing_columns:
        return
    connection.execute(
        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default} NOT NULL")
    )
    existing_columns.add(column_name)


def add_nullable_column(
    connection,
    existing_columns: set[str],
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    if column_name in existing_columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
    existing_columns.add(column_name)
