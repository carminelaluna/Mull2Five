"""
Router eventi — il contenitore dei tornei che si svolgono insieme.

Un weekend con main event e side event, una convention: i tornei restano
oggetti a sé (hanno iscritti, round, classifica propri) ma condividono staff,
pagina pubblica e calendario. Chi è nominato capojudge sull'evento lo è su
tutte le tappe: vedi `staff_role` in routers/tournaments.py.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import (
    Event,
    EventStaff,
    Organization,
    StaffRole,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)
from backend.app.schemas import (
    EventCreate,
    EventOut,
    EventOwnerOut,
    EventPublicOut,
    EventUpdate,
    StaffIn,
    StaffOut,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.stores import store_ids, store_role
from backend.app.services.warnings import event_warnings

router = APIRouter(prefix="/events", tags=["events"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "evento"


def _unique_slug(name: str, db: Session) -> str:
    base = _slugify(name)
    slug, n = base, 2
    while db.scalar(select(Event.id).where(Event.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _event_out(event: Event, db: Session) -> EventOut:
    count = db.scalar(
        select(func.count(Tournament.id)).where(Tournament.event_id == event.id)
    ) or 0
    org_slug = db.scalar(
        select(Organization.slug).where(Organization.id == event.organization_id)
    ) if event.organization_id else None
    return EventOut.model_validate(event).model_copy(
        update={"tournament_count": count, "organization_slug": org_slug}
    )


def _event_owner_out(event: Event, db: Session) -> EventOwnerOut:
    """La manifestazione per chi la organizza: i dati pubblici piu gli avvisi."""
    stages = db.scalars(
        select(Tournament).where(
            Tournament.event_id == event.id, Tournament.status != TournamentStatus.CANCELLED
        )
    ).all()
    return EventOwnerOut(
        **_event_out(event, db).model_dump(), warnings=event_warnings(event, list(stages))
    )


def _check_period(starts_on, ends_on) -> None:
    """Un periodo che finisce prima di cominciare non ha una lettura legittima:
    qui si blocca, non si avvisa."""
    if ends_on and ends_on < starts_on:
        raise HTTPException(status_code=422, detail="La data di fine è prima di quella di inizio")


def load_owned_event(event_id: int, user: User, db: Session) -> Event:
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    if (event.organizer_id != user.id and user.role != UserRole.ADMIN
            and not store_role(user.id, event.organization_id, db)):
        raise HTTPException(status_code=404, detail="Evento non trovato")
    return event


@router.post("", response_model=EventOwnerOut, status_code=201)
def create_event(
    payload: EventCreate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> EventOwnerOut:
    _check_period(payload.starts_on, payload.ends_on)
    event = Event(
        organizer_id=organizer.id,
        organization_id=organizer.organization_id,
        slug=_unique_slug(payload.name, db),
        name=payload.name,
        description=payload.description,
        venue=payload.venue,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        is_public=payload.is_public,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_owner_out(event, db)


@router.get("/mine", response_model=list[EventOwnerOut])
def my_events(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[EventOwnerOut]:
    # I propri e quelli dei negozi per cui si lavora.
    stores = store_ids(organizer, db)
    mine = Event.organizer_id == organizer.id
    events = db.scalars(
        select(Event).where(or_(mine, Event.organization_id.in_(stores)) if stores else mine)
        .order_by(Event.starts_on.desc())
    ).all()
    return [_event_owner_out(e, db) for e in events]


@router.get("/public", response_model=list[EventOut])
def list_public_events(db: Session = Depends(get_db)) -> list[EventOut]:
    events = db.scalars(
        select(Event).where(Event.is_public.is_(True)).order_by(Event.starts_on.desc())
    ).all()
    return [_event_out(e, db) for e in events]


@router.get("/by-slug/{slug}", response_model=EventPublicOut)
def public_event(slug: str, db: Session = Depends(get_db)) -> EventPublicOut:
    """Pagina pubblica dell'evento: il programma di tutte le tappe."""
    from backend.app.routers.tournaments import tournament_with_counts

    event = db.scalar(select(Event).where(Event.slug == slug))
    if not event or not event.is_public:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    tournaments = tournament_with_counts(
        select(Tournament)
        .where(Tournament.event_id == event.id, Tournament.status != TournamentStatus.CANCELLED)
        .order_by(Tournament.starts_on.asc()),
        db,
    )
    return EventPublicOut(event=_event_out(event, db), tournaments=tournaments)


@router.patch("/{event_id}", response_model=EventOwnerOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> EventOwnerOut:
    event = load_owned_event(event_id, organizer, db)
    changes = payload.model_dump(exclude_unset=True)
    # Il periodo si controlla sui valori finali: cambiare solo l'inizio puo
    # scavalcare una fine gia salvata.
    _check_period(changes.get("starts_on") or event.starts_on,
                  changes["ends_on"] if "ends_on" in changes else event.ends_on)
    for field, value in changes.items():
        # ends_on si puo svuotare (la manifestazione torna di un giorno); gli
        # altri campi a null vogliono dire "non toccare".
        if value is not None or field == "ends_on":
            setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return _event_owner_out(event, db)


@router.post("/{event_id}/tournaments/{tournament_id}", response_model=EventOwnerOut)
def attach_tournament(
    event_id: int,
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> EventOwnerOut:
    """Aggiunge una tappa all'evento. Il torneo dev'essere già tuo: l'evento
    raccoglie i propri tornei, non se li appropria.

    Una tappa fuori dal periodo si aggancia lo stesso — un side event il giorno
    prima puo avere senso — e lo dice l'avviso nella risposta."""
    event = load_owned_event(event_id, organizer, db)
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.organizer_id != organizer.id:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    tournament.event_id = event.id
    db.commit()
    return _event_owner_out(event, db)


@router.delete("/{event_id}/tournaments/{tournament_id}", response_model=EventOwnerOut)
def detach_tournament(
    event_id: int,
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> EventOwnerOut:
    event = load_owned_event(event_id, organizer, db)
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.event_id != event.id:
        raise HTTPException(status_code=404, detail="Torneo non nell'evento")
    tournament.event_id = None
    db.commit()
    return _event_owner_out(event, db)


# ── Staff dell'evento ─────────────────────────────────────────

def _staff_out(staff: EventStaff, user: User) -> StaffOut:
    return StaffOut(
        id=staff.id, user_id=user.id, role=staff.role,
        display_name=user.display_name, email=user.email,
    )


@router.get("/{event_id}/staff", response_model=list[StaffOut])
def list_event_staff(
    event_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[StaffOut]:
    load_owned_event(event_id, organizer, db)
    members = db.scalars(
        select(EventStaff)
        .where(EventStaff.event_id == event_id)
        .options(joinedload(EventStaff.user))
    ).all()
    ordered = sorted(members, key=lambda m: (m.role != StaffRole.HEAD_JUDGE, m.id))
    return [_staff_out(m, m.user) for m in ordered]


@router.post("/{event_id}/staff", response_model=StaffOut, status_code=201)
def add_event_staff(
    event_id: int,
    payload: StaffIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> StaffOut:
    """Nomina valida su tutte le tappe. Di capojudge ne vale uno per evento,
    come sul singolo torneo: la catena di comando resta una."""
    event = load_owned_event(event_id, organizer, db)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Nessun utente registrato con questa email")
    if user.id == event.organizer_id:
        raise HTTPException(status_code=409, detail="È già l'organizzatore dell'evento")
    if db.scalar(select(EventStaff.id).where(
        EventStaff.event_id == event_id, EventStaff.user_id == user.id
    )):
        raise HTTPException(status_code=409, detail="Utente già nello staff dell'evento")
    if payload.role == StaffRole.HEAD_JUDGE and db.scalar(select(EventStaff.id).where(
        EventStaff.event_id == event_id, EventStaff.role == StaffRole.HEAD_JUDGE
    )):
        raise HTTPException(
            status_code=409,
            detail="C'è già un capojudge sull'evento: rimuovilo prima di nominarne un altro",
        )
    staff = EventStaff(event_id=event_id, user_id=user.id, role=payload.role)
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return _staff_out(staff, user)


@router.delete("/{event_id}/staff/{staff_id}", status_code=204)
def remove_event_staff(
    event_id: int,
    staff_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    load_owned_event(event_id, organizer, db)
    staff = db.get(EventStaff, staff_id)
    if not staff or staff.event_id != event_id:
        raise HTTPException(status_code=404, detail="Staff member not found")
    db.delete(staff)
    db.commit()


@router.get("/{event_id}/role")
def my_event_role(
    event_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Che cosa è chi chiama su questo evento, per la UI."""
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    if event.organizer_id == user.id or store_role(user.id, event.organization_id, db):
        return {"role": "organizer"}
    role = db.scalar(
        select(EventStaff.role).where(
            EventStaff.event_id == event_id, EventStaff.user_id == user.id
        )
    )
    return {"role": role or "none"}
