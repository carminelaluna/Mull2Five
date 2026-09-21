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
from backend.app.models import Organization, Tournament, TournamentStatus, User, UserRole
from backend.app.schemas import OrganizationOut, OrganizationUpdate, StoreProfileOut
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
    return StoreProfileOut(organization=_org_out(org, db), upcoming=upcoming, past=past)


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
    if user.role != UserRole.ADMIN and user.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Puoi modificare solo il tuo negozio")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(org, field, value)
    db.commit()
    db.refresh(org)
    return _org_out(org, db)


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
