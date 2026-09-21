"""
Router tag giocatore — etichette che il negozio applica ai propri clienti.

Servono a due cose: filtrare gli iscritti in back-office ("chi sono i nuovi?")
e mandare annunci mirati a un sottoinsieme invece che a tutti. Il tag vive dentro
l'organizzazione che l'ha creato: lo stesso utente può essere "Habitué" da un
negozio e sconosciuto da un altro.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import Organization, PlayerTag, PlayerTagAssignment, User
from backend.app.schemas import PlayerTagIn, PlayerTagOut, TagAssignIn, UserOut
from backend.app.security import require_organizer

router = APIRouter(prefix="/tags", tags=["tags"])


def org_id_for(user: User, db: Session) -> int:
    """L'organizzazione per cui l'utente sta lavorando."""
    if user.organization_id:
        return user.organization_id
    default = db.scalar(select(Organization.id).where(Organization.is_default.is_(True)))
    if not default:
        raise HTTPException(status_code=409, detail="Nessuna organizzazione configurata")
    return default


def _tag_out(tag: PlayerTag, db: Session) -> PlayerTagOut:
    count = db.scalar(
        select(func.count(PlayerTagAssignment.id)).where(PlayerTagAssignment.tag_id == tag.id)
    ) or 0
    return PlayerTagOut.model_validate(tag).model_copy(update={"player_count": count})


def _load_tag(tag_id: int, organizer: User, db: Session) -> PlayerTag:
    tag = db.get(PlayerTag, tag_id)
    if not tag or tag.organization_id != org_id_for(organizer, db):
        raise HTTPException(status_code=404, detail="Tag non trovato")
    return tag


@router.get("", response_model=list[PlayerTagOut])
def list_tags(
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[PlayerTagOut]:
    tags = db.scalars(
        select(PlayerTag)
        .where(PlayerTag.organization_id == org_id_for(organizer, db))
        .order_by(PlayerTag.name)
    ).all()
    return [_tag_out(t, db) for t in tags]


@router.post("", response_model=PlayerTagOut, status_code=201)
def create_tag(
    payload: PlayerTagIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> PlayerTagOut:
    org_id = org_id_for(organizer, db)
    name = payload.name.strip()
    if db.scalar(
        select(PlayerTag.id).where(PlayerTag.organization_id == org_id, PlayerTag.name == name)
    ):
        raise HTTPException(status_code=409, detail="Esiste già un tag con questo nome")
    tag = PlayerTag(
        organization_id=org_id, name=name, color=payload.color, description=payload.description
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _tag_out(tag, db)


@router.patch("/{tag_id}", response_model=PlayerTagOut)
def update_tag(
    tag_id: int,
    payload: PlayerTagIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> PlayerTagOut:
    tag = _load_tag(tag_id, organizer, db)
    name = payload.name.strip()
    clash = db.scalar(
        select(PlayerTag.id).where(
            PlayerTag.organization_id == tag.organization_id,
            PlayerTag.name == name,
            PlayerTag.id != tag.id,
        )
    )
    if clash:
        raise HTTPException(status_code=409, detail="Esiste già un tag con questo nome")
    tag.name, tag.color, tag.description = name, payload.color, payload.description
    db.commit()
    db.refresh(tag)
    return _tag_out(tag, db)


@router.delete("/{tag_id}", status_code=204)
def delete_tag(
    tag_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    # Le assegnazioni cadono col tag: l'etichetta sparisce, i giocatori restano.
    db.delete(_load_tag(tag_id, organizer, db))
    db.commit()


@router.get("/{tag_id}/players", response_model=list[UserOut])
def list_tagged_players(
    tag_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[User]:
    _load_tag(tag_id, organizer, db)
    assignments = db.scalars(
        select(PlayerTagAssignment)
        .where(PlayerTagAssignment.tag_id == tag_id)
        .options(joinedload(PlayerTagAssignment.user))
    ).all()
    return [a.user for a in assignments if a.user]


@router.post("/{tag_id}/players", response_model=PlayerTagOut)
def assign_tag(
    tag_id: int,
    payload: TagAssignIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> PlayerTagOut:
    """Assegna il tag a uno o più giocatori. Chi ce l'ha già viene ignorato, così
    la stessa chiamata si può ripetere senza effetti collaterali."""
    tag = _load_tag(tag_id, organizer, db)
    existing = set(db.scalars(
        select(PlayerTagAssignment.user_id).where(PlayerTagAssignment.tag_id == tag.id)
    ).all())
    valid = set(db.scalars(select(User.id).where(User.id.in_(payload.user_ids))).all())
    for user_id in valid - existing:
        db.add(PlayerTagAssignment(tag_id=tag.id, user_id=user_id, assigned_by_id=organizer.id))
    db.commit()
    return _tag_out(tag, db)


@router.delete("/{tag_id}/players/{user_id}", status_code=204)
def unassign_tag(
    tag_id: int,
    user_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> None:
    tag = _load_tag(tag_id, organizer, db)
    assignment = db.scalar(
        select(PlayerTagAssignment).where(
            PlayerTagAssignment.tag_id == tag.id, PlayerTagAssignment.user_id == user_id
        )
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Il giocatore non ha questo tag")
    db.delete(assignment)
    db.commit()


def tags_for_users(user_ids: list[int], org_id: int, db: Session) -> dict[int, list[PlayerTagOut]]:
    """Tag per utente, in una query sola: serve a decorare la lista iscritti
    senza una query per riga."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(PlayerTagAssignment.user_id, PlayerTag)
        .join(PlayerTag, PlayerTag.id == PlayerTagAssignment.tag_id)
        .where(PlayerTagAssignment.user_id.in_(user_ids), PlayerTag.organization_id == org_id)
    ).all()
    out: dict[int, list[PlayerTagOut]] = {}
    for user_id, tag in rows:
        out.setdefault(user_id, []).append(PlayerTagOut.model_validate(tag))
    return out
