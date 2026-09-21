"""
conftest.py — Configurazione globale per pytest.

I test backend usano SQLite in-memory per isolare ogni sessione.
I load test in tests/load/ vengono esclusi (vedi pyproject.toml).
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Forza SQLite in-memory per i test
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("APP_ENV", "test")

from backend.app.core.limiter import limiter  # noqa: E402
from backend.app.db import Base, get_db  # noqa: E402
from backend.app.main import app  # noqa: E402

# Il rate limiting interferisce con i test (tutte le richieste dallo stesso client)
limiter.enabled = False

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
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

