from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Payment, Tournament, User
from backend.app.schemas import PaymentOut, TournamentOut, UserOut
from backend.app.security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


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
