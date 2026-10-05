"""La quota early bird.

Chi si iscrive presto paga meno, e il negozio sa prima quanta gente avrà. Due
colonne: la quota ridotta e l'ultimo giorno in cui vale. Nulle tutt'e due sui
tornei che esistono già, cioè nessuno sconto — che è come si comportavano.

Revision ID: 0009_early_bird
Revises: 0008_tournament_templates
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_early_bird"
down_revision: str | None = "0008_tournament_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "tournaments" not in sa.inspect(bind).get_table_names():
        return
    colonne = {c["name"] for c in sa.inspect(bind).get_columns("tournaments")}
    if "early_bird_cents" not in colonne:
        op.add_column("tournaments", sa.Column("early_bird_cents", sa.Integer(), nullable=True))
    if "early_bird_until" not in colonne:
        op.add_column("tournaments", sa.Column("early_bird_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "early_bird_until")
    op.drop_column("tournaments", "early_bird_cents")
