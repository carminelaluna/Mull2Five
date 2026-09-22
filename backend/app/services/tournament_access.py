"""
tournament_access.py — Chi può fare cosa su un torneo.

Il ruolo di una persona in un torneo (organizzatore, capojudge, judge) e i
controlli che i router fanno prima di lasciar toccare qualcosa.
"""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload  # noqa: F401

from backend.app.models import (
    Event,
    EventStaff,
    Registration,
    StaffRole,
    Tournament,
    TournamentStaff,
    TournamentStatus,
    User,
)
from backend.app.schemas import (
    StaffOut,
)
from backend.app.services.stores import store_role

# Dal piu forte al piu debole: serve a scegliere quando un utente ha due
# incarichi, uno sul torneo e uno sull'evento che lo contiene.
_STAFF_RANK = {StaffRole.HEAD_JUDGE: 2, StaffRole.JUDGE: 1}


def staff_role(tournament_id: int, user_id: int, db: Session) -> str | None:
    """Incarico giudicante dell'utente su questo torneo, None se non è nello staff.

    Conta anche la nomina sull'evento che contiene il torneo: a un weekend il
    capojudge si nomina una volta e vale su tutte le tappe. Se qualcuno ha due
    incarichi diversi vince il piu alto — una nomina non puo togliere poteri.
    """
    roles = [
        db.scalar(
            select(TournamentStaff.role).where(
                TournamentStaff.tournament_id == tournament_id,
                TournamentStaff.user_id == user_id,
            )
        )
    ]
    event_id = db.scalar(select(Tournament.event_id).where(Tournament.id == tournament_id))
    if event_id:
        roles.append(
            db.scalar(
                select(EventStaff.role).where(
                    EventStaff.event_id == event_id, EventStaff.user_id == user_id
                )
            )
        )
    found = [r for r in roles if r]
    return max(found, key=lambda r: _STAFF_RANK.get(r, 0)) if found else None


def is_tournament_staff(tournament_id: int, user_id: int, db: Session) -> bool:
    return staff_role(tournament_id, user_id, db) is not None


def tournament_role(tournament: Tournament, user: User, db: Session) -> str:
    """Che cosa è questo utente su questo torneo, dal più potente al meno potente."""
    if owns_tournament(tournament, user, db):
        return "organizer"
    role = staff_role(tournament.id, user.id, db)
    if role:
        return role
    is_registered = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.tournament_id == tournament.id,
            Registration.player_id == user.id,
        )
    )
    return "player" if is_registered else "none"


def load_tournament_for_staff(tournament_id: int, user: User, db: Session) -> Tournament:
    """Torneo accessibile da organizzatore proprietario O capojudge O judge.

    Capojudge e judge hanno gli stessi poteri di campo — forzare un risultato, dare
    penalità, allungare il tempo di un tavolo — ma non possono eliminare il torneo
    né vedere i pagamenti (quelli restano dietro load_owned_tournament). Quello che
    distingue il capojudge è la nomina dei judge: vedi load_tournament_for_staff_admin.
    """
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if owns_tournament(tournament, user, db):
        return tournament
    if is_tournament_staff(tournament_id, user.id, db):
        return tournament
    raise HTTPException(status_code=404, detail="Torneo non trovato")


def owns_tournament(tournament: Tournament, user: User, db: Session) -> bool:
    """Proprietario del torneo, dell'evento che lo contiene, o nello staff del
    negozio che lo organizza."""
    if tournament.organizer_id == user.id:
        return True
    if store_role(user.id, tournament.organization_id, db):
        return True
    if not tournament.event_id:
        return False
    return db.scalar(
        select(Event.organizer_id).where(Event.id == tournament.event_id)
    ) == user.id


def load_tournament_for_head_judge(
    tournament_id: int, user: User, db: Session
) -> tuple[Tournament, bool]:
    """Torneo accessibile all'organizzatore proprietario o al capojudge.

    È il livello di chi comanda la sala: comporre lo staff e far scorrere i round.
    I judge semplici restano fuori — arbitrano i tavoli, non decidono la struttura
    del torneo. Il bool dice se chi chiama è il proprietario."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if owns_tournament(tournament, user, db):
        return tournament, True
    if staff_role(tournament_id, user.id, db) == StaffRole.HEAD_JUDGE:
        return tournament, False
    raise HTTPException(status_code=404, detail="Torneo non trovato")


def ensure_tournament_live(tournament: Tournament) -> None:
    """Un torneo chiuso non ha più round da far scorrere: niente timer, niente
    estensioni. Senza questo un restart resuscitava l'ends_at che la chiusura azzera,
    e il display in negozio ripartiva a contare su un torneo finito."""
    if tournament.status in {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Il torneo è chiuso")


def ensure_head_judge_seat_free(
    tournament_id: int, db: Session, exclude_staff_id: int | None = None
) -> None:
    """Di capojudge ce n'è uno solo: la catena di comando deve essere inequivocabile."""
    stmt = select(TournamentStaff.id).where(
        TournamentStaff.tournament_id == tournament_id,
        TournamentStaff.role == StaffRole.HEAD_JUDGE,
    )
    if exclude_staff_id is not None:
        stmt = stmt.where(TournamentStaff.id != exclude_staff_id)
    if db.scalar(stmt):
        raise HTTPException(
            status_code=409,
            detail="C'è già un capojudge: rimuovilo o degradalo a judge prima di nominarne un altro",
        )


def staff_out(staff: TournamentStaff, user: User) -> StaffOut:
    return StaffOut(
        id=staff.id, user_id=user.id, role=staff.role,
        display_name=user.display_name, email=user.email,
    )


def load_owned_tournament(tournament_id: int, organizer: User, db: Session) -> Tournament:
    tournament = db.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(selectinload(Tournament.rounds))  # pairings non servono qui
    )
    if not tournament or not owns_tournament(tournament, organizer, db):
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    return tournament


def load_registration_for_tournament(tournament_id: int, registration_id: int, db: Session) -> Registration:
    registration = db.scalar(
        select(Registration)
        .where(Registration.id == registration_id, Registration.tournament_id == tournament_id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklists),
            selectinload(Registration.decklist_revisions),
            selectinload(Registration.payment),
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")
    return registration
