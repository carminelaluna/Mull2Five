"""L'accesso con Google.

Una tabella nuova: l'account Google collegato a un utente, riconosciuto dal suo
`sub` (che non cambia se cambia l'email). Gli utenti che ci sono restano come
sono: chi ha la password continua a entrare con quella.

Revision ID: 0013_user_identities
Revises: 0012_registration_payment_due
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_identities"
down_revision: str | None = "0012_registration_payment_due"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # All'avvio `create_all` (db.py) crea dal modello le tabelle che mancano prima
    # di Alembic: di solito questa la trova già fatta, uguale a quella qui sotto.
    if "user_identities" in sa.inspect(bind).get_table_names():
        return
    # La chiave esterna qui c'è: su una tabella nuova la CREATE TABLE la porta con
    # sé sia su SQLite sia su PostgreSQL, e cancellare un utente deve portarsi via
    # i suoi collegamenti.
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
