"""I codici sconto sulla quota.

Una tabella di codici per torneo, e sull'iscrizione il codice usato: il conto al
pagamento dev'essere lo stesso che il giocatore ha visto iscrivendosi, anche
settimane dopo e anche se intanto il codice è stato esaurito o tolto.

Revision ID: 0010_discount_codes
Revises: 0009_early_bird
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_discount_codes"
down_revision: str | None = "0009_early_bird"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    ispettore = sa.inspect(bind)
    if "discount_codes" not in ispettore.get_table_names():
        # Le chiavi esterne restano dichiarate nel modello, come in 0008: così la
        # migrazione è la stessa su SQLite e PostgreSQL. L'unicità del codice
        # dentro il torneo invece sta qui: è l'unica cosa che impedisce due
        # "SCONTO20" sullo stesso evento anche con due richieste insieme.
        op.create_table(
            "discount_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("percent_off", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cents_off", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_uses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tournament_id", "code", name="uq_discount_codes_tournament_code"),
        )
        op.create_index("ix_discount_codes_tournament_id", "discount_codes", ["tournament_id"])

    if "registrations" in ispettore.get_table_names():
        colonne = {c["name"] for c in ispettore.get_columns("registrations")}
        if "discount_code_id" not in colonne:
            op.add_column("registrations", sa.Column("discount_code_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("registrations", "discount_code_id")
    op.drop_index("ix_discount_codes_tournament_id", table_name="discount_codes")
    op.drop_table("discount_codes")
