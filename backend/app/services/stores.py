"""
stores.py — Chi lavora per un negozio.

Far parte del negozio è esplicito (StoreMember). L'organization_id sull'account
dice solo per quale negozio si sta lavorando adesso: alla registrazione è il
negozio di default per tutti, quindi da solo non dà nessun diritto.

Il negozio di default è un deposito interno, non un negozio di qualcuno: dal
25/11/2026 chi crea un torneo senza far parte di un negozio ne riceve uno col
suo nome (`working_store`). Prima quei tornei uscivano a nome di "Mull2Five".
"""
import re

from sqlalchemy import ColumnElement, false, or_, select, text
from sqlalchemy.orm import Session

from backend.app.core.clock import local_today
from backend.app.models import (
    Event,
    Organization,
    PlayerTag,
    Season,
    StoreMember,
    StoreRole,
    Suspension,
    Tournament,
    TournamentTemplate,
    User,
    UserRole,
)

# Le parole che l'API usa dopo /organizations/: un negozio con quello slug non
# si raggiungerebbe.
RESERVED_SLUGS = {"mine", "current", "memberships"}

# Quello che un organizzatore crea, e la colonna che dice chi l'ha creato: è
# ciò che lo segue nel negozio che apre.
_OWN_ROWS = (
    (Tournament, Tournament.organizer_id),
    (Event, Event.organizer_id),
    (Season, Season.organizer_id),
    (TournamentTemplate, TournamentTemplate.created_by_id),
    (PlayerTag, PlayerTag.created_by_id),
)


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
    today = local_today()
    return db.scalar(
        select(Suspension).where(
            Suspension.organization_id == organization_id,
            Suspension.user_id == user_id,
            Suspension.lifted_at.is_(None),
            or_(Suspension.ends_on.is_(None), Suspension.ends_on >= today),
        )
    )


# ── Il negozio di chi organizza ──────────────────────────────


def store_slug(name: str, db: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    slug, n = base, 1
    while slug in RESERVED_SLUGS or db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def keep_place(tournament: Tournament) -> None:
    """Stacca il torneo dalla sede tenendo scritto dove si gioca."""
    location = tournament.location
    if not tournament.venue:
        tournament.venue = location.label[:180]
        if tournament.latitude is None:
            tournament.latitude, tournament.longitude = location.latitude, location.longitude
    tournament.location_id = None
    tournament.location = None


def open_store(user: User, name: str, db: Session, city: str = "") -> Organization:
    """Apre un negozio di cui `user` è titolare, e da adesso lavora per quello.
    Quello che aveva creato senza negozio — tornei, eventi, circuiti, modelli e
    tag — viene con lui. Non salva: lo fa chi chiama."""
    org = Organization(slug=store_slug(name, db), name=name.strip(), city=city.strip(), is_default=False)
    db.add(org)
    db.flush()
    db.add(StoreMember(organization_id=org.id, user_id=user.id, role=StoreRole.OWNER))
    homeless = {None, db.scalar(select(Organization.id).where(Organization.is_default.is_(True)))}
    for model, creator in _OWN_ROWS:
        for row in db.scalars(select(model).where(creator == user.id)).all():
            if row.organization_id in homeless:
                row.organization_id = org.id
                # La sede era del negozio di prima: resta scritta, non collegata.
                if model is Tournament and row.location:
                    keep_place(row)
    user.organization_id = org.id
    return org


def own_store(user: User, db: Session) -> int | None:
    """Il negozio per cui si lavora, se c'è: quello scelto sull'account se se ne
    fa parte (all'admin basta averlo scelto), altrimenti il primo di cui si fa
    parte. Il negozio di default non conta: non è di nessuno."""
    current = db.get(Organization, user.organization_id) if user.organization_id else None
    if current and not current.is_default and (
        user.role == UserRole.ADMIN or store_role(user.id, current.id, db)
    ):
        return current.id
    stores = store_ids(user, db)
    return stores[0] if stores else None


def working_store(user: User, db: Session) -> int:
    """Il negozio in cui nasce quello che un organizzatore crea. Chi non ne ha
    uno lo riceve adesso, col nome del suo account: lo cambia dal back-office.
    Non salva: lo fa chi chiama, insieme a quello che sta creando."""
    store_id = own_store(user, db) or open_store(user, user.display_name, db).id
    user.organization_id = store_id
    return store_id


def give_stores_to_organizers(db: Session) -> int:
    """Chi aveva creato qualcosa nel negozio di default senza far parte di
    nessun negozio riceve il suo, come se lo creasse oggi. Gira a ogni avvio:
    dopo la prima volta non trova nessuno. Restituisce quanti negozi ha aperto."""
    if db.bind.dialect.name == "postgresql":
        # Lo stesso lucchetto delle altre semine: due avvii insieme non aprono
        # due negozi alla stessa persona.
        db.execute(text("SELECT pg_advisory_xact_lock(727275)"))
    default_id = db.scalar(select(Organization.id).where(Organization.is_default.is_(True)))
    homeless = [
        select(creator).where(or_(model.organization_id.is_(None), model.organization_id == default_id))
        for model, creator in _OWN_ROWS[:3]
    ]
    people = db.scalars(
        select(User).where(
            User.role.in_([UserRole.ORGANIZER, UserRole.ADMIN]),
            ~select(StoreMember.id).where(StoreMember.user_id == User.id).exists(),
            or_(*(User.id.in_(q) for q in homeless)),
        ).order_by(User.id)
    ).all()
    for person in people:
        open_store(person, person.display_name, db)
    db.commit()
    return len(people)

