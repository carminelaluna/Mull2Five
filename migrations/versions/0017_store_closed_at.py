"""I negozi chiusi: quelli rimasti senza nessuno quando l'account se n'è andato.

Una colonna su `organizations`, `closed_at`, vuota per tutti i negozi aperti.
Il negozio nato da solo (25/11/2026) porta il nome dell'account: eliminando
l'account restava fra i negozi con quel nome. Ora `leave_stores` lo chiude, e
qui si chiudono quelli già rimasti così, come farebbe `close_store`: un
negozio che ha uno staff, nessuno dei quali ha ancora un account attivo.

Revision ID: 0017_store_closed_at
Revises: 0016_device_tokens
Create Date: 2026-11-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_store_closed_at"
down_revision: str | None = "0016_device_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORPHANED = """
    is_default = false AND closed_at IS NULL
    AND EXISTS (SELECT 1 FROM store_members m WHERE m.organization_id = organizations.id)
    AND NOT EXISTS (
        SELECT 1 FROM store_members m JOIN users u ON u.id = m.user_id
        WHERE m.organization_id = organizations.id AND u.is_active = true
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    if "organizations" not in sa.inspect(bind).get_table_names():
        return
    existing = {c["name"] for c in sa.inspect(bind).get_columns("organizations")}
    if "closed_at" not in existing:
        # Senza default: PostgreSQL aggiunge la colonna senza riscrivere la tabella.
        op.add_column("organizations", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    # Le sedi dei negozi da chiudere: i tornei tengono scritto dove si giocava,
    # come fa `keep_place` (nome, indirizzo, città e coordinate).
    places = f"SELECT id FROM organizations WHERE {ORPHANED}"
    bind.execute(sa.text(f"""
        UPDATE tournaments SET venue = (SELECT substr(
                                            l.name
                                            || CASE WHEN l.address <> '' THEN ', ' || l.address ELSE '' END
                                            || CASE WHEN l.city <> '' THEN ', ' || l.city ELSE '' END,
                                            1, 180)
                                        FROM locations l WHERE l.id = tournaments.location_id)
        WHERE location_id IN (SELECT id FROM locations WHERE organization_id IN ({places}))
          AND (venue IS NULL OR venue = '')
    """))
    bind.execute(sa.text(f"""
        UPDATE tournaments
        SET latitude = COALESCE(latitude, (SELECT l.latitude FROM locations l
                                            WHERE l.id = tournaments.location_id)),
            longitude = COALESCE(longitude, (SELECT l.longitude FROM locations l
                                             WHERE l.id = tournaments.location_id))
        WHERE location_id IN (SELECT id FROM locations WHERE organization_id IN ({places}))
    """))
    bind.execute(sa.text(f"""
        UPDATE tournaments SET location_id = NULL
        WHERE location_id IN (SELECT id FROM locations WHERE organization_id IN ({places}))
    """))
    bind.execute(sa.text(f"DELETE FROM locations WHERE organization_id IN ({places})"))
    bind.execute(sa.text(f"""
        UPDATE organizations
        SET name = 'Negozio chiuso', slug = 'negozio-chiuso-' || id, description = '', city = '',
            address = '', website = '', logo_url = '', latitude = NULL, longitude = NULL,
            is_premium = false, closed_at = CURRENT_TIMESTAMP
        WHERE {ORPHANED}
    """))


def downgrade() -> None:
    op.drop_column("organizations", "closed_at")
