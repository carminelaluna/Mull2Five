"""Quando è partito il promemoria del giorno prima.

Il promemoria lo manda un compito che gira ogni ora: senza una data scritta sul
torneo, ogni passaggio rimanderebbe la stessa email a tutti gli iscritti, e un
riavvio del server pure.

Revision ID: 0007_tournament_reminder
Revises: 0006_tag_author
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_tournament_reminder"
down_revision: str | None = "0006_tag_author"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "tournaments" not in sa.inspect(bind).get_table_names():
        return
    colonne = {c["name"] for c in sa.inspect(bind).get_columns("tournaments")}
    if "reminder_sent_at" in colonne:
        return

    # Nulla: i tornei che esistono già non hanno mai ricevuto un promemoria. Quelli
    # di domani lo riceveranno al primo passaggio del compito, che è quel che si
    # vuole; quelli già passati no, perché il compito guarda solo il giorno dopo.
    op.add_column("tournaments", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "reminder_sent_at")
