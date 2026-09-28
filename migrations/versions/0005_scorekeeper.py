"""Il referto può arrivare da un judge, non solo da un giocatore.

Lo scorekeeper tiene il tabellone: un judge riporta il risultato dal tavolo e
lui lo conferma prima che entri in classifica. La tabella dei referti in
attesa esisteva già, ma sapeva solo di giocatori: chi propone era per forza
un'iscrizione. Ora può essere anche un utente dello staff.

Revision ID: 0005_scorekeeper
Revises: 0004_tickets
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_scorekeeper"
down_revision: str | None = "0004_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELLA = "pairing_result_reports"


def upgrade() -> None:
    colonne = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABELLA)}
    if "reported_by_user_id" not in colonne:
        op.add_column(TABELLA, sa.Column("reported_by_user_id", sa.Integer(), nullable=True))
    # Chi propone può essere un judge: allora l'iscrizione non c'è.
    with op.batch_alter_table(TABELLA) as batch:
        batch.alter_column("reporter_registration_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    raise NotImplementedError("Le righe con un judge come autore resterebbero senza posto")
