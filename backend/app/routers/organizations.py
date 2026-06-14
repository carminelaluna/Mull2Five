"""
Router organizzazioni (multi-tenant). Elenco pubblico dei negozi e org corrente.
La creazione è riservata agli admin.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.tenant import resolve_org
from backend.app.db import get_db
from backend.app.models import Organization, User
from backend.app.schemas import OrganizationOut
from backend.app.security import require_admin

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


@router.get("", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return db.scalars(select(Organization).order_by(Organization.name)).all()


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
