"""I modelli di torneo.

Le impostazioni di un torneo messe da parte col loro nome, per ricominciare da
lì mesi dopo, quando il torneo da duplicare non si trova più.

Revision ID: 0008_tournament_templates
Revises: 0007_tournament_reminder
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_tournament_templates"
down_revision: str | None = "0007_tournament_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "tournament_templates" in sa.inspect(bind).get_table_names():
        return
    # Niente chiavi esterne dichiarate qui: restano nel modello, come in
    # 0005_scorekeeper e 0006_tag_author. Su una tabella nuova si potrebbero
    # mettere, ma così questa migrazione è la stessa su SQLite e PostgreSQL.
    op.create_table(
        "tournament_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tournament_templates_organization_id", "tournament_templates", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tournament_templates_organization_id", table_name="tournament_templates")
    op.drop_table("tournament_templates")
