"""Allinea ai modelli un database pre-Alembic, e riempie i public_id.

Due cose, in quest'ordine, perche' la seconda ha bisogno della prima.

1. Il recupero. Fino al 23 settembre 2026 db.py rincorreva lo schema a ogni
   avvio con ALTER TABLE scritte a mano. Quel codice e' stato tolto, ma un
   database fermo a prima puo' avere meno colonne di quante i modelli ne
   dichiarino: qui si guarda cosa manca e si aggiunge. Su un database gia'
   allineato non fa niente.

   E' il passo che mancava al primo tentativo: la produzione era ferma a un
   commit precedente e non aveva mai visto users.public_id, quindi partiva e
   poi falliva ogni query sugli utenti.

2. Il riempimento dei public_id, che tocca i dati e non si ricava dai modelli.

Revision ID: 0002_backfill_public_ids
Revises: 0001_baseline
Create Date: 2026-09-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.models import new_public_id

revision: str = "0002_backfill_public_ids"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _catch_up_schema(connection) -> None:
    """Aggiunge quello che i modelli dichiarano e il database non ha."""
    from backend.app.db import Base

    # Tabelle mancanti (con i loro indici): le fa SQLAlchemy.
    Base.metadata.create_all(bind=connection, checkfirst=True)

    inspector = sa.inspect(connection)
    esistenti = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in esistenti:
            continue
        colonne = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in colonne:
                continue
            op.add_column(table.name, _addable(column))
        indici = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in indici:
                op.create_index(index.name, table.name,
                                [c.name for c in index.columns], unique=index.unique)


def _addable(column: sa.Column) -> sa.Column:
    """La colonna come si puo' aggiungere a una tabella che ha gia' righe.

    NOT NULL senza un valore di partenza verrebbe rifiutata: si prende quello
    del modello, e se non c'e' si usa lo zero del tipo.
    """
    default = column.server_default
    if default is None and not column.nullable:
        value = getattr(column.default, "arg", None) if column.default is not None else None
        if callable(value) or value is None:
            value = {"String": "", "Text": "", "Integer": 0, "Boolean": False,
                     "Float": 0.0}.get(type(column.type).__name__)
        if value is not None:
            default = sa.text("false" if value is False else
                              "true" if value is True else
                              f"'{value}'" if isinstance(value, str) else str(value))
    return sa.Column(column.name, column.type, nullable=column.nullable, server_default=default)


def upgrade() -> None:
    connection = op.get_bind()
    _catch_up_schema(connection)
    rows = connection.execute(
        sa.text("SELECT id FROM users WHERE public_id IS NULL OR public_id = ''")
    ).fetchall()
    for (user_id,) in rows:
        connection.execute(
            sa.text("UPDATE users SET public_id = :pid WHERE id = :id"),
            {"pid": new_public_id(), "id": user_id},
        )


def downgrade() -> None:
    # Svuotare i public_id romperebbe i link ai profili gia' in giro.
    raise NotImplementedError("Gli identificativi pubblici non si tolgono")
