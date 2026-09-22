"""
security.py — Password, token di accesso e permessi.

Le password: PBKDF2-SHA256 della libreria standard, nello stesso formato di
passlib ($pbkdf2-sha256$giri$sale$hash, base64 con "." al posto di "+"), così
gli hash già salvati restano validi. Al login un hash con meno giri di quelli
attuali si rifà (password_needs_rehash).

I token: JWT HS256 con PyJWT. Portano la versione dei token dell'utente (tv):
cambiare password o uscire da tutti i dispositivi la aumenta, e i token vecchi
smettono di valere prima della scadenza.
"""
import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
HASH_SCHEME = "pbkdf2-sha256"


# ── Password ─────────────────────────────────────────────────────────────

def _ab64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").rstrip("=").replace("+", ".")


def _ab64_decode(text: str) -> bytes:
    text = text.replace(".", "+")
    return base64.b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    rounds = get_settings().password_hash_rounds
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"${HASH_SCHEME}${rounds}${_ab64_encode(salt)}${_ab64_encode(digest)}"


def _parse_hash(password_hash: str) -> tuple[int, bytes, bytes] | None:
    parts = password_hash.split("$")
    if len(parts) != 5 or parts[1] != HASH_SCHEME:
        return None
    try:
        return int(parts[2]), _ab64_decode(parts[3]), _ab64_decode(parts[4])
    except ValueError:
        return None


def verify_password(password: str, password_hash: str | None) -> bool:
    parsed = _parse_hash(password_hash or "")
    if parsed is None:
        return False
    rounds, salt, expected = parsed
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=len(expected))
    return hmac.compare_digest(digest, expected)


def password_needs_rehash(password_hash: str | None) -> bool:
    parsed = _parse_hash(password_hash or "")
    return parsed is not None and parsed[0] < get_settings().password_hash_rounds


# ── Token ────────────────────────────────────────────────────────────────

def create_access_token(user: User) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": str(user.id), "email": user.email, "role": user.role, "pid": user.public_id or "",
               "tv": user.token_version or 0, "iat": datetime.now(UTC), "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_reset_token(user: User) -> str:
    """Token monouso per il reset password — scade in 30 minuti."""
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=30)
    payload = {"sub": str(user.id), "purpose": "password-reset", "tv": user.token_version or 0, "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_reset_token(token: str) -> tuple[int, int] | None:
    """(user_id, versione dei token) se il token di reset è valido, altrimenti None."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("purpose") != "password-reset":
            return None
        return int(payload.get("sub", "0")), int(payload.get("tv", 0))
    except (jwt.PyJWTError, ValueError):
        return None


def get_current_user(
    request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Accesso non valido o scaduto: accedi di nuovo",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", "0"))
        version = int(payload.get("tv", 0))
    except (jwt.PyJWTError, ValueError):
        raise credentials_error from None
    if payload.get("purpose"):   # un token di reset non apre la sessione
        raise credentials_error
    user = db.get(User, user_id)
    if not user or not user.is_active or version != (user.token_version or 0):
        raise credentials_error
    # Un genitore agisce per il profilo che gestisce: iscriverlo, pagarlo,
    # consegnarne la lista. Vale solo per i suoi profili.
    acting = request.headers.get("X-Act-As")
    if acting:
        profile = db.get(User, int(acting)) if acting.isdigit() else None
        if not profile or profile.guardian_id != user.id or not profile.is_active:
            raise HTTPException(status_code=403, detail="Non gestisci questo profilo")
        return profile
    return user


def require_organizer(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ORGANIZER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Serve un account da organizzatore")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Serve un account da amministratore")
    return user
