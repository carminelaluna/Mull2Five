from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import User, UserRole

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return bool(password_hash) and pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": str(user.id), "email": user.email, "role": user.role, "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_reset_token(user: User) -> str:
    """Token monouso per il reset password — scade in 30 minuti."""
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=30)
    payload = {"sub": str(user.id), "purpose": "password-reset", "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_reset_token(token: str) -> int | None:
    """Restituisce lo user_id se il token di reset è valido, altrimenti None."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("purpose") != "password-reset":
            return None
        return int(payload.get("sub", "0"))
    except (JWTError, ValueError):
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", "0"))
    except (JWTError, ValueError):
        raise credentials_error from None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_organizer(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ORGANIZER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Organizer account required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin account required")
    return user
