"""Gli indici sulle chiavi esterne che le pagine usano per cercare.

PostgreSQL non indicizza da solo le chiavi esterne: senza indice, trovare gli
abbinamenti di un giocatore, le penalità di un torneo o i tornei di un
organizzatore vuol dire leggere tutta la tabella. Con pochi tornei non si vede,
con qualche migliaio di abbinamenti sì. Restano fuori le colonne di registro
("creato da", "tolto da"), su cui nessuna schermata cerca.

Tabelle piccole e indici semplici: il lock dura un attimo, e se qualcuno lo
tiene più a lungo lock_timeout (migrations/env.py) fa fallire il deploy invece
di bloccarlo.

Revision ID: 0011_foreign_key_indexes
Revises: 0010_discount_codes
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_foreign_key_indexes"
down_revision: str | None = "0010_discount_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDICI = (
    ("events", "organizer_id"),
    ("users", "organization_id"),
    ("tournaments", "organizer_id"),
    ("tournaments", "season_id"),
    ("registrations", "discount_code_id"),
    ("decklist_revisions", "registration_id"),
    ("pairings", "player_a_registration_id"),
    ("pairings", "player_b_registration_id"),
    ("pairing_result_reports", "pairing_id"),
    ("announcements", "tournament_id"),
    ("penalties", "tournament_id"),
    ("penalties", "registration_id"),
)


def upgrade() -> None:
    ispettore = sa.inspect(op.get_bind())
    tabelle = set(ispettore.get_table_names())
    for tabella, colonna in INDICI:
        if tabella not in tabelle:
            continue
        nome = f"ix_{tabella}_{colonna}"
        if nome not in {i["name"] for i in ispettore.get_indexes(tabella)}:
            op.create_index(nome, tabella, [colonna])


def downgrade() -> None:
    for tabella, colonna in reversed(INDICI):
        op.drop_index(f"ix_{tabella}_{colonna}", table_name=tabella)
