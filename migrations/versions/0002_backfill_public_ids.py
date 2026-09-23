"""Un identificativo pubblico agli account che non ce l'hanno.

Lo faceva db.py a ogni avvio, insieme alle altre migrazioni scritte a mano.
Quelle sono state tolte — lo schema lo descrivono i modelli e lo applica
Alembic — ma questa tocca i dati e non si ricava dai modelli: va eseguita una
volta per database, ed e' esattamente quello che fa una revisione.

Sui database vivi non trova niente da fare: il riempimento e' gia' avvenuto.
Serve a quelli ripristinati da un backup vecchio.

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


def upgrade() -> None:
    connection = op.get_bind()
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
