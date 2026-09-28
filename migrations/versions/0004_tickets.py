"""Le segnalazioni dei giocatori, su due livelli.

Una segnalazione va a chi organizza il torneo oppure a chi tiene il sito: sono
due destinatari diversi, e il giocatore sceglie quale aprendo la segnalazione.

Revision ID: 0004_tickets
Revises: 0003_tournament_city
Create Date: 2026-09-28
"""
from collections.abc import Sequence

from alembic import op

from backend.app.db import Base

revision: str = "0004_tickets"
down_revision: str | None = "0003_tournament_city"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tabelle nuove: le disegna il modello, non serve riscriverle qui.
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables["tickets"], Base.metadata.tables["ticket_messages"]],
        checkfirst=True,
    )


def downgrade() -> None:
    op.drop_table("ticket_messages")
    op.drop_table("tickets")
