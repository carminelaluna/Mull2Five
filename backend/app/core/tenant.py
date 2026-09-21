"""
Risoluzione del tenant (organizzazione) dalla richiesta.

Il negozio corrente è identificato — in ordine — da:
  1. header `X-Mull2Five-Org: <slug>` (configurabile via settings.tenant_header)
  2. query param `?org=<slug>`
Se non specificato o non trovato, si usa l'organizzazione di default.
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import Organization


def resolve_org(request: Request, db: Session = Depends(get_db)) -> Organization | None:
    settings = get_settings()
    slug = request.headers.get(settings.tenant_header) or request.query_params.get("org")
    if slug:
        org = db.scalar(select(Organization).where(Organization.slug == slug))
        if org:
            return org
    return db.scalar(select(Organization).where(Organization.is_default == True))  # noqa: E712
