"""Le regole dei circuiti: bonus imbattuto e scarti.

Tre colonne su `seasons`: il bonus a chi vince tutti i match di un torneo, e lo
scarto dei punteggi di tappa peggiori quando il circuito ha più di tanti tornei.
Sui circuiti che esistono già valgono zero bonus e zero scarti: la classifica
resta quella di prima.

Revision ID: 0014_season_scoring
Revises: 0013_user_identities
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_season_scoring"
down_revision: str | None = "0013_user_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = {
    "points_undefeated_bonus": "0",
    "drop_worst_scores": "0",
    "drop_above_tournaments": "4",
}


def upgrade() -> None:
    bind = op.get_bind()
    if "seasons" not in sa.inspect(bind).get_table_names():
        return
    existing = {c["name"] for c in sa.inspect(bind).get_columns("seasons")}
    # Una costante come default: PostgreSQL aggiunge la colonna senza riscrivere
    # la tabella, e le righe che ci sono la leggono già valorizzata.
    for name, default in COLUMNS.items():
        if name not in existing:
            op.add_column("seasons", sa.Column(name, sa.Integer(), nullable=False, server_default=default))


def downgrade() -> None:
    for name in reversed(list(COLUMNS)):
        op.drop_column("seasons", name)
