from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.core.lockout import is_locked, record_failed
from backend.app.core.lockout import reset as lockout_reset
from backend.app.db import get_db
from backend.app.models import OAuthAccount, Registration, User, UserRole
from backend.app.schemas import (
    ForgotPasswordIn,
    LoginIn,
    ResetPasswordIn,
    TokenOut,
    UserCreate,
    UserOut,
)
from backend.app.security import (
    create_access_token,
    create_reset_token,
    get_current_user,
    hash_password,
    verify_password,
    verify_reset_token,
)
from backend.app.services.email import send_email
from backend.app.services.oauth import fetch_apple_profile, fetch_google_profile

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)) -> TokenOut:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    role = payload.role if payload.role in {UserRole.PLAYER, UserRole.ORGANIZER} else UserRole.PLAYER
    from backend.app.models import Organization
    default_org = db.scalar(select(Organization).where(Organization.is_default == True))  # noqa: E712
    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        role=role,
        password_hash=hash_password(payload.password),
        organization_id=default_org.id if default_org else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user))


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    email = payload.email.lower()

    if is_locked(email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporaneamente bloccato dopo troppi tentativi falliti. Riprova tra 30 minuti.",
        )

    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(payload.password, user.password_hash):
        record_failed(email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    lockout_reset(email)   # reset contatore su login riuscito
    return TokenOut(access_token=create_access_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(
    request: Request, payload: ForgotPasswordIn, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Invia un'email con il link di reset. Risponde sempre 200 per non
    rivelare se l'email è registrata (user enumeration)."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user and user.is_active:
        token = create_reset_token(user)
        reset_url = f"{str(settings.frontend_url).rstrip('/')}/reset-password.html?token={token}"
        send_email(
            user.email,
            "Mull2Five — Reimposta la tua password",
            f"Ciao {user.display_name},\n\n"
            f"per reimpostare la password apri questo link (valido 30 minuti):\n{reset_url}\n\n"
            "Se non hai richiesto tu il reset, ignora questa email.",
        )
    return {"detail": "Se l'email è registrata riceverai le istruzioni per il reset."}


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(
    request: Request, payload: ResetPasswordIn, db: Session = Depends(get_db)
) -> dict[str, str]:
    user_id = verify_reset_token(payload.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    lockout_reset(user.email)   # sblocca eventuale lockout precedente
    return {"detail": "Password aggiornata. Ora puoi accedere."}


@router.get("/me/export")
def export_my_data(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """GDPR: esporta tutti i dati personali dell'utente in JSON."""
    registrations = db.scalars(
        select(Registration).where(Registration.player_id == user.id)
    ).all()
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
        },
        "registrations": [
            {
                "tournament_id": reg.tournament_id,
                "archetype": reg.archetype,
                "wizards_account": reg.wizards_account,
                "checked_in": reg.checked_in,
                "dropped": reg.dropped,
                "waitlisted": reg.waitlisted,
                "created_at": reg.created_at.isoformat(),
            }
            for reg in registrations
        ],
    }


@router.delete("/me", status_code=200)
def delete_my_account(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    """GDPR: anonimizza l'account. I risultati storici dei tornei restano
    (integrità delle classifiche) ma senza dati personali."""
    user.email = f"deleted-{user.id}@anon.invalid"
    user.display_name = "Utente eliminato"
    user.password_hash = None
    user.is_active = False
    # Rimuove i dati personali dalle iscrizioni
    for reg in db.scalars(select(Registration).where(Registration.player_id == user.id)):
        reg.wizards_account = ""
    db.commit()
    return {"detail": "Account eliminato. I tuoi dati personali sono stati rimossi."}


@router.get("/oauth/{provider}/login")
def oauth_login(provider: str):
    settings = get_settings()
    redirect_uri = f"{settings.app_url}/api/auth/oauth/{provider}/callback"
    if provider == "google":
        if not settings.google_client_id:
            raise HTTPException(status_code=503, detail="Google OAuth is not configured")
        params = urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "access_type": "offline",
                "prompt": "select_account",
            }
        )
        return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}
    if provider == "apple":
        if not settings.apple_client_id:
            raise HTTPException(status_code=503, detail="Apple OAuth is not configured")
        params = urlencode(
            {
                "client_id": settings.apple_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code id_token",
                "scope": "name email",
                "response_mode": "form_post",
            }
        )
        return {"authorization_url": f"https://appleid.apple.com/auth/authorize?{params}"}
    raise HTTPException(status_code=404, detail="Unsupported OAuth provider")


@router.api_route("/oauth/{provider}/callback", methods=["GET", "POST"])
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    data = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        data.update(dict(form))
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")

    redirect_uri = f"{settings.app_url}/api/auth/oauth/{provider}/callback"
    if provider == "google":
        profile = await fetch_google_profile(code, redirect_uri)
    elif provider == "apple":
        profile = await fetch_apple_profile(code, redirect_uri)
    else:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider")

    account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == profile["provider_user_id"],
        )
    )
    if account:
        user = account.user
    else:
        user = db.scalar(select(User).where(User.email == profile["email"]))
        if not user:
            user = User(
                email=profile["email"],
                display_name=profile["display_name"],
                role=UserRole.PLAYER,
            )
            db.add(user)
            db.flush()
        db.add(
            OAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_user_id=profile["provider_user_id"],
            )
        )
        db.commit()
        db.refresh(user)

    token = create_access_token(user)
    return RedirectResponse(f"{str(settings.frontend_url).rstrip('/')}?token={token}")
