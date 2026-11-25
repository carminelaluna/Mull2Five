"""I telefoni da svegliare con Firebase quando arriva una notifica.

Una tabella nuova: una riga per ogni app che si è registrata con il token che
Firebase le ha dato (services/fcm.py). Le tabelle che ci sono non si toccano.

Revision ID: 0016_device_tokens
Revises: 0015_notifications
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_device_tokens"
down_revision: str | None = "0015_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # All'avvio `create_all` (db.py) crea dal modello le tabelle che mancano prima
    # di Alembic: di solito questa la trova già fatta, uguale a quella qui sotto.
    if "device_tokens" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="android"),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token", name="uq_device_tokens_token"),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_device_tokens_user_id", table_name="device_tokens")
    op.drop_table("device_tokens")
