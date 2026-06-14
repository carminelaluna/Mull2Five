"""
Router Web Push: chiave pubblica VAPID, subscribe/unsubscribe del browser.
Le notifiche vengono inviate dal backend (annunci, nuovo round) via core.webpush.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.webpush import public_key, push_enabled
from backend.app.db import get_db
from backend.app.models import PushSubscription, User
from backend.app.schemas import PushSubscriptionIn, VapidKeyOut
from backend.app.security import get_current_user

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/vapid-key", response_model=VapidKeyOut)
def get_vapid_key() -> VapidKeyOut:
    return VapidKeyOut(public_key=public_key(), enabled=push_enabled())


@router.post("/subscribe", status_code=201)
def subscribe(
    payload: PushSubscriptionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing:
        existing.user_id = user.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
            )
        )
    db.commit()
    return {"status": "subscribed"}


@router.post("/unsubscribe", status_code=200)
def unsubscribe(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    endpoint = payload.get("endpoint", "")
    sub = db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id
        )
    )
    if sub:
        db.delete(sub)
        db.commit()
    return {"status": "unsubscribed"}
