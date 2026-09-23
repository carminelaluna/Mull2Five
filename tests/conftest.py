"""
conftest.py — Configurazione globale per pytest.

I test backend girano su SQLite (veloce) o su Postgres, se DATABASE_URL punta
la': la CI li esegue su entrambi, perche' in produzione c'e' Postgres.
I load test in tests/load/ vengono esclusi (vedi pyproject.toml).
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Il database dei test sta nella cartella temporanea di sistema, non nel repo.
# Sotto WSL il repo e' su /mnt/c, cioe' il disco Windows: li' SQLite e' lento e i
# lock non sono affidabili, e la suite falliva a caso — test diversi a ogni giro,
# tutti verdi se rilanciati da soli. Spostato il file su disco nativo: 320 verdi
# in 4 minuti e mezzo invece di 3-4 rossi in 8-27 minuti.
# Un file per processo: due pytest insieme non si cancellano le tabelle a vicenda.
# La CI passa il suo DATABASE_URL (SQLite e PostgreSQL), quindi qui non cambia niente.
TEST_DB_PATH = os.path.join(tempfile.gettempdir(), f"m2f_test_{os.getpid()}.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("APP_ENV", "test")
# Centinaia di account nei test: con i giri veri di PBKDF2 la suite durerebbe minuti in più.
os.environ.setdefault("PASSWORD_HASH_ROUNDS", "1000")
# Le email nei test partono subito: così si verifica l'invio, non la coda.
os.environ.setdefault("EMAIL_ASYNC", "false")

from backend.app.core.limiter import limiter  # noqa: E402
from backend.app.db import Base, get_db  # noqa: E402
from backend.app.main import app  # noqa: E402

# Il rate limiting interferisce con i test (tutte le richieste dallo stesso client)
limiter.enabled = False

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# Su Postgres (CI) non esiste check_same_thread: e' roba di SQLite.
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {},
)
TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db_session():
    """Sessione DB su tabelle ricreate da zero — isolamento totale tra i test.

    Niente transaction-rollback annidato: l'app chiama db.commit() liberamente
    (anche più volte per richiesta), quindi il pattern SAVEPOINT non è affidabile.
    """
    from backend.app import models  # noqa: F401 — registra i modelli

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    """TestClient FastAPI con override della sessione DB e cache pulita."""
    from backend.app.core.cache import cache_invalidate

    cache_invalidate("")  # svuota la cache in-memory tra i test

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def all_games(monkeypatch):
    """Gli altri giochi ci sono ma sono spenti (ENABLED_GAMES=mtg): i test che
    li riguardano li accendono solo per sé."""
    from backend.app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "enabled_games", "all")


def pytest_sessionfinish(session, exitstatus):
    """Finita la suite, il database dei test non serve piu."""
    if os.environ.get("DATABASE_URL", "") != f"sqlite:///{TEST_DB_PATH}":
        return
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(TEST_DB_PATH + suffix)
        except OSError:
            pass
