"""
notifications.py — La campanella: lo storico delle notifiche di chi è collegato.

Le scrive services/inbox.py, quando il sito dice qualcosa a qualcuno. Qui si
leggono e si segnano come lette. Un genitore vede anche quelle dei profili che
gestisce (`for_name` dice di chi sono): l'iscrizione del figlio la fa lui, e a
lui serve sapere che i turni sono pronti.

L'app chiede `/unread` ogni tanto e scarica solo le notifiche dopo l'ultima che
ha già mostrato (`after_id`): sono le notifiche del telefono. Con Firebase si
registra anche (`/devices`), e il server la sveglia appena ce n'è una.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import DeviceToken, Notification, User
from backend.app.schemas import (
    DeviceIn,
    NotificationOut,
    NotificationsOut,
    NotificationsReadIn,
    UnreadOut,
)
from backend.app.security import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _owners(user: User, db: Session) -> dict[int, str]:
    """Di chi si leggono le notifiche: le proprie, nome vuoto, e quelle dei profili gestiti."""
    owners = {user.id: ""}
    owners.update(db.execute(select(User.id, User.display_name).where(User.guardian_id == user.id)).all())
    return owners


def _unread(owners: dict[int, str], db: Session) -> UnreadOut:
    unread, latest = db.execute(
        select(func.count(Notification.id).filter(Notification.read_at.is_(None)), func.max(Notification.id))
        .where(Notification.user_id.in_(owners))
    ).one()
    return UnreadOut(unread=unread or 0, latest_id=latest or 0)


@router.get("", response_model=NotificationsOut)
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    after_id: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationsOut:
    """Le ultime, dalla più nuova. `after_id` tiene solo quelle arrivate dopo."""
    owners = _owners(user, db)
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id.in_(owners), Notification.id > after_id)
        .order_by(Notification.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        NotificationOut(
            id=row.id, kind=row.kind, context=row.context, title=row.title, body=row.body,
            detail=row.detail, url=row.url, created_at=row.created_at, read=row.read_at is not None,
            for_name=owners.get(row.user_id, ""),
        )
        for row in rows
    ]
    return NotificationsOut(items=items, unread=_unread(owners, db).unread)


@router.get("/unread", response_model=UnreadOut)
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UnreadOut:
    """Il numero sulla campanella: la si chiede a ogni pagina."""
    return _unread(_owners(user, db), db)


@router.post("/read", response_model=UnreadOut)
def mark_read(
    payload: NotificationsReadIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadOut:
    """Segna come lette quelle indicate, o tutte. Quelle di un altro non si toccano:
    l'id che non è suo semplicemente non trova niente."""
    owners = _owners(user, db)
    stmt = update(Notification).where(Notification.user_id.in_(owners), Notification.read_at.is_(None))
    if payload.ids is not None:
        stmt = stmt.where(Notification.id.in_(payload.ids))
    db.execute(stmt.values(read_at=datetime.now(UTC)))
    db.commit()
    return _unread(owners, db)


# Oltre questi telefoni per account, i più vecchi si dimenticano: chi cambia
# telefono non si porta dietro tutti quelli di prima.
MAX_DEVICES = 10


def _account(user: User, request: Request, db: Session) -> User:
    """Il telefono è dell'account, non del profilo per cui il genitore sta agendo."""
    if request.headers.get("X-Act-As") and user.guardian_id:
        return db.get(User, user.guardian_id) or user
    return user


@router.post("/devices", status_code=204)
def register_device(
    payload: DeviceIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """L'app chiede di essere svegliata da Firebase quando arriva una notifica
    (services/fcm.py). Lo stesso telefono con un altro account passa a quello:
    il token è del telefono, e il telefono è di chi c'è dentro adesso."""
    account = _account(user, request, db)
    device = db.scalar(select(DeviceToken).where(DeviceToken.token == payload.token))
    if device is None:
        device = DeviceToken(token=payload.token)
        db.add(device)
    device.user_id = account.id
    device.platform = payload.platform
    # Vale finché vale questa sessione: "Esci da tutti i dispositivi" lo spegne.
    device.token_version = account.token_version or 0
    device.last_seen_at = datetime.now(UTC)
    db.flush()
    extra = db.scalars(
        select(DeviceToken.id).where(DeviceToken.user_id == account.id)
        .order_by(DeviceToken.last_seen_at.desc(), DeviceToken.id.desc()).offset(MAX_DEVICES)
    ).all()
    if extra:
        db.execute(delete(DeviceToken).where(DeviceToken.id.in_(extra)))
    db.commit()
    return Response(status_code=204)


@router.post("/devices/forget", status_code=204)
def forget_device(
    payload: DeviceIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Uscendo dall'app: questo telefono non si sveglia più per questo account."""
    account = _account(user, request, db)
    db.execute(delete(DeviceToken).where(DeviceToken.token == payload.token, DeviceToken.user_id == account.id))
    db.commit()
    return Response(status_code=204)
