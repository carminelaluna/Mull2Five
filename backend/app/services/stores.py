"""
stores.py — Chi lavora per un negozio.

Far parte del negozio è esplicito (StoreMember). L'organization_id sull'account
dice solo per quale negozio si sta lavorando adesso: alla registrazione è il
negozio di default per tutti, quindi da solo non dà nessun diritto.
"""
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.orm import Session

from backend.app.models import StoreMember, StoreRole, Suspension, Tournament, User, UserRole


def store_role(user_id: int, organization_id: int | None, db: Session) -> str | None:
    """Il ruolo nel negozio, o None per chi non ne fa parte."""
    if organization_id is None:
        return None
    return db.scalar(
        select(StoreMember.role).where(
            StoreMember.organization_id == organization_id, StoreMember.user_id == user_id
        )
    )


def store_ids(user: User, db: Session) -> list[int]:
    """I negozi di cui si fa parte."""
    return list(db.scalars(select(StoreMember.organization_id).where(StoreMember.user_id == user.id)))


def can_manage_store(user: User, organization_id: int, db: Session) -> bool:
    """Profilo, sedi e tornei del negozio: chiunque ne faccia parte, e l'admin."""
    return user.role == UserRole.ADMIN or store_role(user.id, organization_id, db) is not None


def is_store_owner(user: User, organization_id: int, db: Session) -> bool:
    """Decidere chi fa parte dello staff spetta al titolare."""
    return user.role == UserRole.ADMIN or store_role(user.id, organization_id, db) == StoreRole.OWNER


def managed_tournaments(user: User, db: Session) -> ColumnElement[bool]:
    """Condizione per i tornei che si gestiscono: i propri e quelli dei propri negozi."""
    stores = store_ids(user, db)
    in_store = Tournament.organization_id.in_(stores) if stores else false()
    return or_(Tournament.organizer_id == user.id, in_store)


def active_suspension(user_id: int, organization_id: int | None, db: Session) -> Suspension | None:
    """La sospensione che oggi tiene il giocatore fuori dagli eventi del negozio."""
    if organization_id is None:
        return None
    today = datetime.now(UTC).date()
    return db.scalar(
        select(Suspension).where(
            Suspension.organization_id == organization_id,
            Suspension.user_id == user_id,
            Suspension.lifted_at.is_(None),
            or_(Suspension.ends_on.is_(None), Suspension.ends_on >= today),
        )
    )

