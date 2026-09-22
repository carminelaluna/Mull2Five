"""
Router organizzazioni (multi-tenant). Elenco pubblico dei negozi e org corrente.
Un organizzatore apre il proprio negozio e ne decide lo staff; l'admin
li vede e li crea tutti.
"""
import re
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from backend.app.core.clock import local_today
from backend.app.core.tenant import resolve_org
from backend.app.db import get_db
from backend.app.models import (
    ApiKey,
    Event,
    Location,
    Organization,
    StoreMember,
    StoreRole,
    Suspension,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)
from backend.app.schemas import (
    ApiKeyCreatedOut,
    ApiKeyIn,
    ApiKeyOut,
    LocationIn,
    LocationOut,
    OrganizationOut,
    OrganizationUpdate,
    StoreCreate,
    StoreMemberIn,
    StoreMemberOut,
    StoreMemberRoleIn,
    StoreMembershipOut,
    StoreProfileOut,
    SuspensionIn,
    SuspensionOut,
)
from backend.app.security import get_current_user, require_admin, require_organizer
from backend.app.services.api_keys import SHOWN_CHARS, hash_key, new_key
from backend.app.services.stores import (
    active_suspension,
    can_manage_store,
    is_store_owner,
    store_role,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def _org_out(org: Organization, db: Session) -> OrganizationOut:
    from sqlalchemy import func

    today = local_today()
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
    from backend.app.routers.tournaments import tournament_with_counts

    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if not org:
        raise HTTPException(status_code=404, detail="Negozio non trovato")
    today = local_today()
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
    if not can_manage_store(user, org.id, db):
        raise HTTPException(status_code=403, detail="Puoi modificare solo il tuo negozio")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(org, field, value)
    db.commit()
    db.refresh(org)
    return _org_out(org, db)


@router.get("/mine", response_model=OrganizationOut)
def my_organization(user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> OrganizationOut:
    """Il negozio per cui lavora chi è collegato: quello che cura dal backoffice.
    404 finché non ne ha uno: il negozio di default non è di nessuno."""
    org = db.get(Organization, user.organization_id) if user.organization_id else None
    role = store_role(user.id, org.id, db) if org else None
    if org and not role and user.role == UserRole.ADMIN:
        role = StoreRole.OWNER
    if not org or not role:
        raise HTTPException(status_code=404, detail="Non fai ancora parte di un negozio")
    return _org_out(org, db).model_copy(update={"my_role": role})


RESERVED_SLUGS = {"mine", "current", "memberships"}


@router.post("/mine", response_model=OrganizationOut, status_code=201)
def create_my_store(
    payload: StoreCreate,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """Apre il proprio negozio: chi lo crea ne è il titolare. I tornei e gli
    eventi organizzati finora senza negozio vengono con lui."""
    base = _slugify(payload.name)
    slug, n = base, 1
    while slug in RESERVED_SLUGS or db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    org = Organization(slug=slug, name=payload.name.strip(), city=payload.city.strip(), is_default=False)
    db.add(org)
    db.flush()
    db.add(StoreMember(organization_id=org.id, user_id=user.id, role=StoreRole.OWNER))

    default_id = db.scalar(select(Organization.id).where(Organization.is_default.is_(True)))
    homeless = (None, default_id)
    for model in (Tournament, Event):
        for row in db.scalars(select(model).where(model.organizer_id == user.id)).all():
            if row.organization_id in homeless:
                row.organization_id = org.id
                # La sede era del negozio di prima: resta scritta, non collegata.
                if model is Tournament and row.location:
                    _keep_place(row)
    user.organization_id = org.id
    db.commit()
    _forget_tournaments()
    return _org_out(org, db).model_copy(update={"my_role": StoreRole.OWNER})


@router.get("/memberships", response_model=list[StoreMembershipOut])
def my_memberships(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[StoreMembershipOut]:
    """I negozi per cui si lavora, per passare dall'uno all'altro."""
    rows = db.execute(
        select(Organization, StoreMember.role)
        .join(StoreMember, StoreMember.organization_id == Organization.id)
        .where(StoreMember.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return [
        StoreMembershipOut(slug=org.slug, name=org.name, role=role, current=org.id == user.organization_id)
        for org, role in rows
    ]


@router.post("/{slug}/use", response_model=OrganizationOut)
def use_store(slug: str, user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> OrganizationOut:
    """Lavora per questo negozio: i tornei nuovi nascono qui."""
    org = _store(slug, db)
    role = store_role(user.id, org.id, db)
    if not role:
        raise HTTPException(status_code=403, detail="Non fai parte dello staff di questo negozio")
    user.organization_id = org.id
    db.commit()
    return _org_out(org, db).model_copy(update={"my_role": role})


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
    if not can_manage_store(user, org.id, db):
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
        _keep_place(tournament)
    db.delete(location)
    db.commit()
    _forget_tournaments()


# ── Chiavi dell'API pubblica ──────────────────────────────
# Le crea e le revoca il titolare: danno i dati del negozio a un altro programma.

MAX_API_KEYS = 10


def _key_owner_store(slug: str, user: User, db: Session) -> Organization:
    org = _store(slug, db)
    if not is_store_owner(user, org.id, db):
        raise HTTPException(status_code=403, detail="Le chiavi API le gestisce il titolare del negozio")
    return org


def _api_key_out(key: ApiKey, db: Session) -> ApiKeyOut:
    author = db.get(User, key.created_by_id) if key.created_by_id else None
    return ApiKeyOut(id=key.id, name=key.name, prefix=key.prefix, created_at=key.created_at,
                     last_used_at=key.last_used_at, created_by=author.display_name if author else None)


@router.get("/{slug}/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(slug: str, user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    org = _key_owner_store(slug, user, db)
    keys = db.scalars(select(ApiKey).where(ApiKey.organization_id == org.id, ApiKey.revoked_at.is_(None))
                      .order_by(ApiKey.created_at, ApiKey.id)).all()
    return [_api_key_out(key, db) for key in keys]


@router.post("/{slug}/api-keys", response_model=ApiKeyCreatedOut, status_code=201)
def create_api_key(
    slug: str, payload: ApiKeyIn, user: User = Depends(require_organizer), db: Session = Depends(get_db),
) -> ApiKeyCreatedOut:
    """Una chiave nuova: la risposta è l'unica volta che si vede in chiaro."""
    org = _key_owner_store(slug, user, db)
    active = db.scalars(select(ApiKey.id).where(ApiKey.organization_id == org.id, ApiKey.revoked_at.is_(None))).all()
    if len(active) >= MAX_API_KEYS:
        raise HTTPException(status_code=409, detail=f"Al massimo {MAX_API_KEYS} chiavi attive: revocane una")
    raw = new_key()
    key = ApiKey(organization_id=org.id, created_by_id=user.id, name=payload.name.strip(),
                 prefix=raw[:SHOWN_CHARS], key_hash=hash_key(raw))
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeyCreatedOut(**_api_key_out(key, db).model_dump(), key=raw)


@router.delete("/{slug}/api-keys/{key_id}", status_code=204)
def revoke_api_key(slug: str, key_id: int, user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> None:
    org = _key_owner_store(slug, user, db)
    key = db.get(ApiKey, key_id)
    if not key or key.organization_id != org.id or key.revoked_at:
        raise HTTPException(status_code=404, detail="Chiave non trovata")
    key.revoked_at = datetime.now(UTC)
    db.commit()


def _keep_place(tournament: Tournament) -> None:
    """Stacca il torneo dalla sede tenendo scritto dove si gioca."""
    location = tournament.location
    if not tournament.venue:
        tournament.venue = location.label[:180]
        if tournament.latitude is None:
            tournament.latitude, tournament.longitude = location.latitude, location.longitude
    tournament.location_id = None
    tournament.location = None


def _forget_tournaments() -> None:
    """Le liste in cache mostrano ancora la sede vecchia: via."""
    from backend.app.core.cache import cache_invalidate

    cache_invalidate("tournaments:")


# ── Staff del negozio ─────────────────────────────────────────


def _owned_store(slug: str, user: User, db: Session) -> Organization:
    org = _store(slug, db)
    if not is_store_owner(user, org.id, db):
        raise HTTPException(status_code=403, detail="Lo staff lo decide il titolare del negozio")
    return org


def _member(org: Organization, user_id: int, db: Session) -> StoreMember:
    member = db.scalar(
        select(StoreMember).where(StoreMember.organization_id == org.id, StoreMember.user_id == user_id)
    )
    if not member:
        raise HTTPException(status_code=404, detail="Non fa parte dello staff")
    return member


def _other_owners(org: Organization, user_id: int, db: Session) -> int:
    return len(db.scalars(
        select(StoreMember.id).where(
            StoreMember.organization_id == org.id,
            StoreMember.role == StoreRole.OWNER,
            StoreMember.user_id != user_id,
        )
    ).all())


def _member_out(member: StoreMember) -> StoreMemberOut:
    return StoreMemberOut(
        user_id=member.user_id, display_name=member.user.display_name, email=member.user.email,
        role=member.role, created_at=member.created_at,
    )


@router.get("/{slug}/members", response_model=list[StoreMemberOut])
def list_members(slug: str, user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> list[StoreMemberOut]:
    org = _managed_store(slug, user, db)
    members = db.scalars(
        select(StoreMember).where(StoreMember.organization_id == org.id).order_by(StoreMember.created_at)
    ).all()
    return [_member_out(m) for m in members]


@router.post("/{slug}/members", response_model=StoreMemberOut, status_code=201)
def add_member(
    slug: str,
    payload: StoreMemberIn,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> StoreMemberOut:
    """Aggiunge allo staff un account che esiste già. Chi era solo giocatore
    diventa organizzatore: senza, il backoffice non gli si aprirebbe."""
    org = _owned_store(slug, user, db)
    person = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not person:
        raise HTTPException(status_code=404, detail="Nessun account con questa email: deve prima registrarsi")
    if store_role(person.id, org.id, db):
        raise HTTPException(status_code=409, detail="Fa già parte dello staff")
    member = StoreMember(organization_id=org.id, user_id=person.id, role=payload.role)
    db.add(member)
    if person.role == UserRole.PLAYER:
        person.role = UserRole.ORGANIZER
    # Chi non lavorava ancora per nessun negozio comincia da questo.
    if not store_role(person.id, person.organization_id, db):
        person.organization_id = org.id
    db.commit()
    db.refresh(member)
    return _member_out(member)


@router.patch("/{slug}/members/{user_id}", response_model=StoreMemberOut)
def change_member_role(
    slug: str,
    user_id: int,
    payload: StoreMemberRoleIn,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> StoreMemberOut:
    org = _owned_store(slug, user, db)
    member = _member(org, user_id, db)
    if member.role == StoreRole.OWNER and payload.role != StoreRole.OWNER and not _other_owners(org, user_id, db):
        raise HTTPException(status_code=409, detail="Il negozio resterebbe senza titolare")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    return _member_out(member)


@router.delete("/{slug}/members/{user_id}", status_code=204)
def remove_member(
    slug: str,
    user_id: int,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    """Toglie qualcuno dallo staff; ognuno può anche andarsene da sé. I tornei
    che ha creato restano al negozio."""
    org = _store(slug, db)
    if user_id != user.id and not is_store_owner(user, org.id, db):
        raise HTTPException(status_code=403, detail="Lo staff lo decide il titolare del negozio")
    member = _member(org, user_id, db)
    if member.role == StoreRole.OWNER and not _other_owners(org, user_id, db):
        raise HTTPException(status_code=409, detail="Il negozio resterebbe senza titolare")
    person = member.user
    db.delete(member)
    db.flush()
    if person.organization_id == org.id:
        # Torna al negozio di default, o a un altro di cui fa ancora parte.
        other = db.scalar(select(StoreMember.organization_id).where(StoreMember.user_id == person.id))
        person.organization_id = other or db.scalar(
            select(Organization.id).where(Organization.is_default.is_(True))
        )
    db.commit()


# ── Sospensioni ──────────────────────────────────────────────


def _suspension_out(suspension: Suspension, today: date) -> SuspensionOut:
    return SuspensionOut(
        id=suspension.id, user_id=suspension.user_id,
        display_name=suspension.user.display_name, email=suspension.user.email,
        reason=suspension.reason, ends_on=suspension.ends_on, created_at=suspension.created_at,
        created_by_name=suspension.created_by.display_name if suspension.created_by else None,
        lifted_at=suspension.lifted_at, active=suspension.is_active(today),
    )


@router.get("/{slug}/suspensions", response_model=list[SuspensionOut])
def list_suspensions(slug: str, user: User = Depends(require_organizer), db: Session = Depends(get_db)) -> list[SuspensionOut]:
    """Tutte, anche quelle finite o revocate: lo storico serve a decidere la prossima."""
    org = _managed_store(slug, user, db)
    today = local_today()
    rows = [_suspension_out(s, today) for s in db.scalars(
        select(Suspension).where(Suspension.organization_id == org.id).order_by(Suspension.created_at.desc())
    ).all()]
    return sorted(rows, key=lambda s: not s.active)   # prima quelle in corso


@router.post("/{slug}/suspensions", response_model=SuspensionOut, status_code=201)
def suspend_player(
    slug: str,
    payload: SuspensionIn,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SuspensionOut:
    """Esclude un giocatore dagli eventi del negozio. Le iscrizioni che ha già
    restano: l'organizzatore le vede segnalate negli avvisi del torneo e decide."""
    org = _managed_store(slug, user, db)
    person = (db.get(User, payload.user_id) if payload.user_id
              else db.scalar(select(User).where(User.email == payload.email.lower())))
    if not person:
        raise HTTPException(status_code=404, detail="Nessun account con questa email")
    today = local_today()
    if payload.ends_on and payload.ends_on < today:
        raise HTTPException(status_code=422, detail="La fine della sospensione è già passata")
    if store_role(person.id, org.id, db):
        raise HTTPException(status_code=409, detail="Fa parte dello staff del negozio")
    if active_suspension(person.id, org.id, db):
        raise HTTPException(status_code=409, detail="È già sospeso: revoca quella in corso per cambiarla")
    suspension = Suspension(
        organization_id=org.id, user_id=person.id, reason=payload.reason.strip(),
        ends_on=payload.ends_on, created_by_id=user.id,
    )
    db.add(suspension)
    db.commit()
    db.refresh(suspension)
    return _suspension_out(suspension, today)


@router.post("/{slug}/suspensions/{suspension_id}/lift", response_model=SuspensionOut)
def lift_suspension(
    slug: str,
    suspension_id: int,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> SuspensionOut:
    org = _managed_store(slug, user, db)
    suspension = db.get(Suspension, suspension_id)
    if not suspension or suspension.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Sospensione non trovata")
    today = local_today()
    if not suspension.is_active(today):
        raise HTTPException(status_code=409, detail="Non è più in corso")
    suspension.lifted_at = datetime.now(UTC)
    suspension.lifted_by_id = user.id
    db.commit()
    db.refresh(suspension)
    return _suspension_out(suspension, today)

