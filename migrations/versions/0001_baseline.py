"""Lo schema di partenza, come i modelli lo descrivono oggi.

Il database in produzione esiste già: al primo avvio viene solo "timbrato" con
questa revisione (backend/app/db.py), senza toccare niente. Su un database
vuoto invece crea tutte le tabelle. Da qui in poi ogni cambiamento allo schema
è una revisione nuova: `alembic revision --autogenerate -m "..."`.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-22
"""
from collections.abc import Sequence

from alembic import op

from backend.app.db import Base

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Non si torna indietro dallo schema iniziale: sarebbe cancellare tutto.
    raise NotImplementedError("La revisione di partenza non si annulla")
