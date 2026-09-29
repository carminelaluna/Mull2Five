"""Chi ha creato un tag.

I tag erano di tutti gli organizzatori senza negozio, perché nascevano tutti
nell'organizzazione di default. Ora sono del negozio, e chi il negozio lo apre
deve potersi portare dietro i propri: per sapere quali sono serve l'autore, che
prima non era scritto da nessuna parte.

Revision ID: 0006_tag_author
Revises: 0005_scorekeeper
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_tag_author"
down_revision: str | None = "0005_scorekeeper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "player_tags" not in sa.inspect(bind).get_table_names():
        return
    colonne = {c["name"] for c in sa.inspect(bind).get_columns("player_tags")}
    if "created_by_id" in colonne:
        return

    # Intero secco: SQLite non sa aggiungere un vincolo a una tabella che esiste
    # già, e una migrazione che gira solo su PostgreSQL non è una migrazione. La
    # chiave esterna resta dichiarata nel modello, quindi i database nuovi ce
    # l'hanno; qui conta che la colonna ci sia. Come per `reported_by_user_id`
    # in 0005_scorekeeper.
    op.add_column("player_tags", sa.Column("created_by_id", sa.Integer(), nullable=True))
    # Chi ha creato i tag che esistono già non è scritto da nessuna parte: il
    # primo che li ha assegnati è la stima migliore. Un tag mai assegnato resta
    # senza autore, e chi apre un negozio non se lo porta: è il caso giusto,
    # perché non sappiamo di chi sia.
    op.execute(
        "UPDATE player_tags SET created_by_id = ("
        "SELECT a.assigned_by_id FROM player_tag_assignments a "
        "WHERE a.tag_id = player_tags.id AND a.assigned_by_id IS NOT NULL "
        "ORDER BY a.created_at, a.id LIMIT 1)"
    )


def downgrade() -> None:
    op.drop_column("player_tags", "created_by_id")
