"""
Router organizzazioni (multi-tenant). Elenco pubblico dei negozi e org corrente.
La creazione è riservata agli admin.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from backend.app.core.tenant import resolve_org
from backend.app.db import get_db
from backend.app.models import Location, Organization, Tournament, TournamentStatus, User, UserRole
from backend.app.schemas import (
    LocationIn,
    LocationOut,
    OrganizationOut,
    OrganizationUpdate,
    StoreProfileOut,
)
from backend.app.security import require_admin, require_organizer

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def _org_out(org: Organization, db: Session) -> OrganizationOut:
    from datetime import UTC, datetime

    from sqlalchemy import func

    today = datetime.now(UTC).date()
    counts = db.execute(
        select(
            func.sum(case((Tournament.starts_on >= today, 1), else_=0)),
            func.sum(case((Tournament.starts_on < today, 1), else_=0)),
        ).where(
            Tournament.organization_id == org.id,
            Tournament.status != TournamentStatus.CANCELLED,
        )
    ).first()
    return OrganizationOut.model_validate(org).model_copy(update={
        "upcoming_count": int(counts[0] or 0),
        "past_count": int(counts[1] or 0),
    })


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    near_lat: float | None = None,
    near_lng: float | None = None,
    radius_km: float | None = None,
    premium_only: bool = False,
    db: Session = Depends(get_db),
) -> list[OrganizationOut]:
    """Elenco pubblico dei negozi, con conteggi e distanza opzionale."""
    stmt = select(Organization)
    if premium_only:
        stmt = stmt.where(Organization.is_premium.is_(True))
    orgs = [_org_out(o, db) for o in db.scalars(stmt.order_by(Organization.name)).all()]
    if near_lat is None or near_lng is None:
        return orgs
    from backend.app.routers.tournaments import haversine_km

    located = []
    for o in orgs:
        if o.latitude is None or o.longitude is None:
            continue
        distance = haversine_km(near_lat, near_lng, o.latitude, o.longitude)
        if radius_km is not None and distance > radius_km:
            continue
        located.append(o.model_copy(update={"distance_km": round(distance, 1)}))
    located.sort(key=lambda o: o.distance_km or 0)
    return located


@router.get("/{slug}/profile", response_model=StoreProfileOut)
def store_profile(slug: str, db: Session = Depends(get_db)) -> StoreProfileOut:
    """Pagina pubblica del negozio: anagrafica, prossimi eventi e albo d'oro."""
    from datetime import UTC, datetime

    from backend.app.routers.tournaments import tournament_with_counts

    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if not org:
        raise HTTPException(status_code=404, detail="Negozio non trovato")
    today = datetime.now(UTC).date()
    base = select(Tournament).where(
        Tournament.organization_id == org.id,
        Tournament.status != TournamentStatus.CANCELLED,
    )
    upcoming = tournament_with_counts(
        base.where(Tournament.starts_on >= today).order_by(Tournament.starts_on.asc()).limit(20), db
    )
    past = tournament_with_counts(
        base.where(Tournament.starts_on < today).order_by(Tournament.starts_on.desc()).limit(20), db
    )
    return StoreProfileOut(organization=_org_out(org, db), upcoming=upcoming, past=past,
                           locations=_locations_of(org, db))


def can_manage_store(user: User, org: Organization) -> bool:
    """Chi può curare il negozio: il suo organizzatore, o un admin."""
    return user.role == UserRole.ADMIN or user.organization_id == org.id


@router.patch("/{slug}", response_model=OrganizationOut)
def update_organization(
    slug: str,
    payload: OrganizationUpdate,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """L'organizzatore cura il profilo del proprio negozio; l'admin quello di tutti."""
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if not org:
        raise HTTPException(status_code=404, detail="Negozio non trovato")
    if not can_manage_store(user, org):
        raise HTTPException(status_code=403, detail="Puoi modificare solo il tuo negozio")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(org, field, value)
    db.commit()
    db.refresh(org)
    return _org_out(org, db)


@router.get("/mine", response_model=OrganizationOut)
def my_organization(user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> OrganizationOut:
    """Il negozio per cui lavora chi è collegato: quello che cura dal backoffice."""
    from backend.app.routers.tags import org_id_for

    return _org_out(db.get(Organization, org_id_for(user, db)), db)


@router.get("/current", response_model=OrganizationOut)
def current_organization(org: Organization = Depends(resolve_org)) -> Organization:
    if not org:
        raise HTTPException(status_code=404, detail="Nessuna organizzazione configurata")
    return org


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: dict,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Organization:
    name = (payload.get("name") or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Nome organizzazione troppo corto")
    slug = _slugify(payload.get("slug") or name)
    if db.scalar(select(Organization).where(Organization.slug == slug)):
        raise HTTPException(status_code=409, detail="Slug già in uso")
    org = Organization(slug=slug, name=name, is_default=False)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


# ── Sedi ──────────────────────────────────────────────────────


def _store(slug: str, db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if not org:
        raise HTTPException(status_code=404, detail="Negozio non trovato")
    return org


def _managed_store(slug: str, user: User, db: Session) -> Organization:
    org = _store(slug, db)
    if not can_manage_store(user, org):
        raise HTTPException(status_code=403, detail="Puoi modificare solo il tuo negozio")
    return org


def _locations_of(org: Organization, db: Session) -> list[Location]:
    return list(db.scalars(
        select(Location).where(Location.organization_id == org.id).order_by(Location.name)
    ).all())


def _store_location(org: Organization, location_id: int, db: Session) -> Location:
    location = db.get(Location, location_id)
    if not location or location.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Sede non trovata")
    return location


@router.get("/{slug}/locations", response_model=list[LocationOut])
def list_locations(slug: str, db: Session = Depends(get_db)) -> list[Location]:
    """Le sedi del negozio: pubbliche, come l'indirizzo."""
    return _locations_of(_store(slug, db), db)


@router.post("/{slug}/locations", response_model=LocationOut, status_code=201)
def create_location(
    slug: str,
    payload: LocationIn,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Location:
    org = _managed_store(slug, user, db)
    location = Location(organization_id=org.id, **payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.put("/{slug}/locations/{location_id}", response_model=LocationOut)
def update_location(
    slug: str,
    location_id: int,
    payload: LocationIn,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> Location:
    location = _store_location(_managed_store(slug, user, db), location_id, db)
    for field, value in payload.model_dump().items():
        setattr(location, field, value)
    db.commit()
    db.refresh(location)
    _forget_tournaments()
    return location


@router.delete("/{slug}/locations/{location_id}", status_code=204)
def delete_location(
    slug: str,
    location_id: int,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    """Toglie una sede. I tornei che la usavano tengono scritto dove si sono
    giocati: lo storico non deve perdere il luogo."""
    location = _store_location(_managed_store(slug, user, db), location_id, db)
    for tournament in db.scalars(select(Tournament).where(Tournament.location_id == location.id)).all():
        if not tournament.venue:
            tournament.venue = location.label[:180]
            if tournament.latitude is None:
                tournament.latitude, tournament.longitude = location.latitude, location.longitude
        tournament.location_id = None
    db.delete(location)
    db.commit()
    _forget_tournaments()


def _forget_tournaments() -> None:
    """Le liste in cache mostrano ancora la sede vecchia: via."""
    from backend.app.core.cache import cache_invalidate

    cache_invalidate("tournaments:")
