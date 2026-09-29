"""La città del torneo, separata dal luogo.

Prima "Luogo" era un campo solo ("Tana del Drago, via Roma 1, Milano") e la città
non si poteva né cercare né proporre. Ora sono due campi: il luogo e la città.

Revision ID: 0003_tournament_city
Revises: 0002_backfill_public_ids
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tournament_city"
down_revision: str | None = "0002_backfill_public_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELLE = ("tournaments", "events")


def upgrade() -> None:
    esistenti = set(sa.inspect(op.get_bind()).get_table_names())
    for tabella in TABELLE:
        if tabella in esistenti:
            colonne = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabella)}
            if "city" not in colonne:
                op.add_column(tabella, sa.Column("city", sa.String(120), nullable=False,
                                                 server_default=""))


def downgrade() -> None:
    for tabella in TABELLE:
        op.drop_column(tabella, "city")
