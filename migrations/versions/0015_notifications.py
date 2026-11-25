"""Lo storico delle notifiche, quello della campanella.

Una tabella nuova: una riga per ogni cosa che il sito ha detto a qualcuno
(iscrizione, pagamento, turno, annuncio, segnalazione). La legge la campanella
del sito e la legge l'app, che la mostra fra le notifiche del telefono. Le
tabelle che ci sono non si toccano.

Revision ID: 0015_notifications
Revises: 0014_season_scoring
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_notifications"
down_revision: str | None = "0014_season_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # All'avvio `create_all` (db.py) crea dal modello le tabelle che mancano prima
    # di Alembic: di solito questa la trova già fatta, uguale a quella qui sotto.
    if "notifications" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("context", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("url", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    # La campanella chiede sempre "le ultime di questa persona": user_id davanti
    # serve anche da indice della chiave esterna.
    op.create_index("idx_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
