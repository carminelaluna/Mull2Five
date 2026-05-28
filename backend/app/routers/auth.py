from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import OAuthAccount, User, UserRole
from backend.app.schemas import LoginIn, TokenOut, UserCreate, UserOut
from backend.app.security import create_access_token, get_current_user, hash_password, verify_password
from backend.app.services.oauth import fetch_apple_profile, fetch_google_profile

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> TokenOut:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    role = payload.role if payload.role in {UserRole.PLAYER, UserRole.ORGANIZER} else UserRole.PLAYER
    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        role=role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return TokenOut(access_token=create_access_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


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
