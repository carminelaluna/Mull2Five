from datetime import datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import Organization, Payment, Tournament, User, UserRole
from backend.app.schemas import (
    AdminProfileIn,
    LocatorImportIn,
    LocatorImportOut,
    LocatorStatusOut,
    PaymentOut,
    ProfileOut,
    TournamentOut,
    UserOut,
)
from backend.app.security import require_admin
from backend.app.services import wizards_locator

router = APIRouter(prefix="/admin", tags=["admin"])



@router.get("/wizards-locator", response_model=LocatorStatusOut)
def locator_status(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> LocatorStatusOut:
    def imported(model) -> int:
        return db.scalar(select(func.count(model.id)).where(model.source == wizards_locator.SOURCE)) or 0

    return LocatorStatusOut(enabled=get_settings().wizards_locator_enabled,
                            imported_tournaments=imported(Tournament), imported_stores=imported(Organization))


@router.post("/wizards-locator/import", response_model=LocatorImportOut)
def locator_import(payload: LocatorImportIn, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)) -> LocatorImportOut:
    """I tornei di Magic intorno a una città, dal Wizards Event Locator.
    Spenta finché non si imposta WIZARDS_LOCATOR_ENABLED: vedi services/wizards_locator.py."""
    city = payload.city.strip()
    try:
        events = wizards_locator.fetch_events(city, payload.distance_km, payload.max_pages)
    except wizards_locator.LocatorDisabled as exc:
        raise HTTPException(status_code=409, detail="Importazione dal Wizards Locator spenta sul server (WIZARDS_LOCATOR_ENABLED)") from exc
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Il Wizards Locator non ha risposto come previsto") from exc
    report = wizards_locator.import_events(events, db, city)
    return LocatorImportOut(fetched=report.fetched, created=report.created, updated=report.updated,
                            cancelled=report.cancelled, skipped=report.skipped, stores_created=report.stores_created)


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return db.scalars(select(User).order_by(User.created_at.desc())).all()


@router.get("/tournaments", response_model=list[TournamentOut])
def list_all_tournaments(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TournamentOut]:
    tournaments = db.scalars(select(Tournament).order_by(Tournament.created_at.desc())).all()
    return [
        TournamentOut.model_validate(tournament).model_copy(
            update={"registered_players": len(tournament.registrations)}
        )
        for tournament in tournaments
    ]


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[Payment]:
    return db.scalars(select(Payment).order_by(Payment.created_at.desc())).all()



@router.get("/alerting")
def alerting_status(admin: User = Depends(require_admin)) -> dict:
    """Stato dei canali di alerting configurati."""
    from backend.app.core.alerting import alerting_enabled
    from backend.app.core.config import get_settings

    s = get_settings()
    return {
        "enabled": alerting_enabled(),
        "email": bool(s.alert_email),
        "telegram": bool(s.telegram_bot_token and s.telegram_chat_id),
        "watchdog_interval_secs": s.watchdog_interval_secs,
    }


@router.post("/alerting/test", status_code=200)
def test_alert(admin: User = Depends(require_admin)) -> dict:
    """Invia un alert di prova sui canali configurati (bypassa il throttle)."""
    from backend.app.core.alerting import alerting_enabled, send_alert

    if not alerting_enabled():
        raise HTTPException(status_code=400, detail="Nessun canale di alerting configurato")
    sent = send_alert(
        f"test:{datetime.utcnow().isoformat()}",  # chiave unica → mai throttled
        "Alert di prova",
        f"Test richiesto da {admin.email}. Se lo ricevi, l'alerting funziona.",
        level="info",
    )
    return {"status": "sent" if sent else "suppressed"}


@router.post("/profiles", response_model=ProfileOut, status_code=201)
def create_managed_profile(
    payload: AdminProfileIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Crea il profilo di un minore per chi lo gestirà.

    Non si crea più da soli dal proprio profilo: il genitore apre una
    segnalazione al sito e arriva qui, così qualcuno guarda chi sta chiedendo
    cosa prima che nasca un account per un minore.
    """
    from backend.app.routers.auth import MAX_PROFILES, _profile_out

    guardian = db.scalar(select(User).where(User.email == payload.guardian_email.lower()))
    if not guardian:
        raise HTTPException(status_code=404, detail="Account non trovato")
    if guardian.guardian_id or guardian.is_guest:
        raise HTTPException(status_code=409, detail="Un profilo gestito non ne gestisce altri")
    quanti = db.scalar(
        select(func.count(User.id)).where(User.guardian_id == guardian.id, User.is_active.is_(True))
    ) or 0
    if quanti >= MAX_PROFILES:
        raise HTTPException(status_code=409, detail=f"Al massimo {MAX_PROFILES} profili per account")

    profile = User(
        email=f"profile-{uuid4().hex}@profiles.mull2five.invalid",
        display_name=payload.display_name.strip(),
        role=UserRole.PLAYER,
        password_hash=None,
        guardian_id=guardian.id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile, db)
