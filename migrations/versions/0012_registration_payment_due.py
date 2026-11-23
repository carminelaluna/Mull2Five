"""Il posto tenuto mentre si paga online.

Chi sceglie Stripe o PayPal all'iscrizione non è iscritto finché non paga: il
posto resta suo fino a `payment_due_by`, poi l'iscrizione sparisce. Nulla sulle
iscrizioni che esistono già, cioè nessun orologio — che è come si comportavano.

Revision ID: 0012_registration_payment_due
Revises: 0011_foreign_key_indexes
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_registration_payment_due"
down_revision: str | None = "0011_foreign_key_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "registrations" not in sa.inspect(bind).get_table_names():
        return
    colonne = {c["name"] for c in sa.inspect(bind).get_columns("registrations")}
    if "payment_due_by" not in colonne:
        op.add_column("registrations", sa.Column("payment_due_by", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("registrations", "payment_due_by")
