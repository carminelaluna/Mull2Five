"""
tickets.py — Le segnalazioni dei giocatori, su due livelli.

Un giocatore apre una segnalazione e sceglie a chi: a **chi organizza** il
torneo (un risultato sbagliato, un pagamento, un profilo da aggiungere) o a
**chi tiene il sito** (un account, una cosa rotta). Sono due destinatari
diversi e due permessi diversi, ed e' per questo che scope sta sulla riga e
non si deduce.

Chi legge una segnalazione: chi l'ha aperta, sempre; poi gli admin se e' per
il sito, o chi gestisce quel torneo se e' per l'organizzatore. Quando ne nasce
una, a loro arriva un'email (`recipients`, dal 25/11/2026): prima lo si
scopriva solo aprendo la pagina.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import (
    Event,
    StoreMember,
    Ticket,
    TicketMessage,
    TicketScope,
    TicketStatus,
    Tournament,
    User,
    UserRole,
)
from backend.app.schemas import TicketCreate, TicketMessageIn, TicketOut
from backend.app.security import get_current_user
from backend.app.services.notifications import notify_ticket_opened
from backend.app.services.stores import managed_tournaments
from backend.app.services.tournament_access import owns_tournament

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


def ticket_out(ticket: Ticket) -> TicketOut:
    return TicketOut(
        id=ticket.id,
        scope=ticket.scope,
        status=ticket.status,
        subject=ticket.subject,
        tournament_id=ticket.tournament_id,
        tournament_name=ticket.tournament.name if ticket.tournament else None,
        opened_by_id=ticket.opened_by_id,
        opened_by_name=ticket.opened_by.display_name if ticket.opened_by else "",
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=[
            {
                "id": m.id,
                "author_id": m.author_id,
                "author_name": m.author.display_name if m.author else "",
                "body": m.body,
                "created_at": m.created_at,
            }
            for m in ticket.messages
        ],
    )


def _loaded(db: Session):
    return select(Ticket).options(
        selectinload(Ticket.messages).selectinload(TicketMessage.author),
        selectinload(Ticket.opened_by),
        selectinload(Ticket.tournament),
    )


def can_read(ticket: Ticket, user: User, db: Session) -> bool:
    if ticket.opened_by_id == user.id:
        return True
    if ticket.scope == TicketScope.ADMIN:
        return user.role == UserRole.ADMIN
    tournament = ticket.tournament
    return bool(tournament) and owns_tournament(tournament, user, db)


def load_ticket(ticket_id: int, user: User, db: Session) -> Ticket:
    ticket = db.scalars(_loaded(db).where(Ticket.id == ticket_id)).first()
    if not ticket or not can_read(ticket, user, db):
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    return ticket


def recipients(ticket: Ticket, db: Session) -> list[User]:
    """A chi arriva l'email di una segnalazione nuova: a chi può leggerla
    (can_read), tranne chi l'ha aperta. Gli admin se è per il sito; se è per un
    torneo, chi lo organizza, chi tiene l'evento che lo contiene e lo staff del
    negozio."""
    if ticket.scope == TicketScope.ADMIN:
        who = User.role == UserRole.ADMIN
    else:
        tournament = ticket.tournament
        if not tournament:
            return []
        ids = {tournament.organizer_id}
        if tournament.event_id:
            ids.add(db.scalar(select(Event.organizer_id).where(Event.id == tournament.event_id)))
        if tournament.organization_id:
            ids.update(db.scalars(select(StoreMember.user_id).where(
                StoreMember.organization_id == tournament.organization_id)))
        ids.discard(None)
        who = User.id.in_(ids)
    return list(db.scalars(
        select(User).where(who, User.is_active.is_(True), User.id != ticket.opened_by_id).order_by(User.id)
    ))


def _tickets_page() -> str:
    settings = get_settings()
    return f"{(settings.site_url or str(settings.frontend_url)).rstrip('/')}/tickets.html"


@router.post("", response_model=TicketOut, status_code=201)
def open_ticket(
    payload: TicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    """Apre una segnalazione. A un organizzatore si scrive a proposito di un
    torneo: senza, non si saprebbe a chi consegnarla."""
    tournament = db.get(Tournament, payload.tournament_id) if payload.tournament_id else None
    if payload.scope == TicketScope.ORGANIZER and not tournament:
        raise HTTPException(status_code=422, detail="Scegli il torneo di cui vuoi parlare")
    if payload.tournament_id and not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")

    ticket = Ticket(
        opened_by_id=user.id,
        scope=payload.scope,
        tournament_id=tournament.id if tournament else None,
        subject=payload.subject.strip(),
    )
    ticket.messages.append(TicketMessage(author_id=user.id, body=payload.body.strip()))
    db.add(ticket)
    db.commit()
    opened = load_ticket(ticket.id, user, db)
    try:
        notify_ticket_opened(opened, recipients(opened, db), _tickets_page())
    except Exception:  # noqa: BLE001 — è già salvata: un'email mancata non la fa sembrare fallita
        logger.exception("Email per la segnalazione %s non partita", opened.id)
    return ticket_out(opened)


@router.get("/mine", response_model=list[TicketOut])
def my_tickets(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TicketOut]:
    """Quelle che ho aperto io."""
    rows = db.scalars(
        _loaded(db).where(Ticket.opened_by_id == user.id).order_by(Ticket.updated_at.desc())
    ).all()
    return [ticket_out(t) for t in rows]


@router.get("/inbox", response_model=list[TicketOut])
def inbox(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TicketOut]:
    """Quelle indirizzate a me: al sito se sono admin, ai miei tornei se organizzo."""
    # managed_tournaments è una condizione, non un elenco: si usa come sottoquery.
    condizioni = [
        Ticket.tournament_id.in_(select(Tournament.id).where(managed_tournaments(user, db)))
    ]
    if user.role == UserRole.ADMIN:
        condizioni.append(Ticket.scope == TicketScope.ADMIN)
    rows = db.scalars(
        _loaded(db).where(or_(*condizioni)).order_by(Ticket.updated_at.desc())
    ).all()
    # Le proprie non sono posta in arrivo: stanno in /mine.
    return [ticket_out(t) for t in rows if t.opened_by_id != user.id]


@router.get("/{ticket_id}", response_model=TicketOut)
def read_ticket(
    ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TicketOut:
    return ticket_out(load_ticket(ticket_id, user, db))


@router.post("/{ticket_id}/messages", response_model=TicketOut)
def reply(
    ticket_id: int,
    payload: TicketMessageIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = load_ticket(ticket_id, user, db)
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Segnalazione chiusa: riaprila per rispondere")
    ticket.messages.append(TicketMessage(author_id=user.id, body=payload.body.strip()))
    # Se risponde chi l'ha aperta torna in attesa, altrimenti è stata risposta.
    ticket.status = TicketStatus.OPEN if ticket.opened_by_id == user.id else TicketStatus.ANSWERED
    ticket.updated_at = datetime.now(UTC)
    db.add(ticket)
    db.commit()
    return ticket_out(load_ticket(ticket_id, user, db))


@router.post("/{ticket_id}/close", response_model=TicketOut)
def close_ticket(
    ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TicketOut:
    ticket = load_ticket(ticket_id, user, db)
    ticket.status = TicketStatus.CLOSED
    ticket.updated_at = datetime.now(UTC)
    db.add(ticket)
    db.commit()
    return ticket_out(load_ticket(ticket_id, user, db))


@router.post("/{ticket_id}/reopen", response_model=TicketOut)
def reopen_ticket(
    ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TicketOut:
    ticket = load_ticket(ticket_id, user, db)
    ticket.status = TicketStatus.OPEN
    ticket.updated_at = datetime.now(UTC)
    db.add(ticket)
    db.commit()
    return ticket_out(load_ticket(ticket_id, user, db))
