"""
google_auth.py — Entrare con Google, e unire l'account Google a quello di qui.

Il giro (la parte che parla con Google sta in services/google_login.py):

  POST /auth/google/start     l'indirizzo di Google, più un cookie firmato con
                              `state`, `nonce` e la pagina a cui tornare
  GET  /auth/google/callback  Google torna qui: lo `state` dev'essere quello del
                              cookie, l'id_token dev'essere buono; si sceglie l'account
  POST /auth/google/finish    la pagina di accesso ritira il token di accesso
  POST /auth/google/complete  chi è nuovo accetta termini ed età, e l'account nasce

Il token di accesso non passa mai dall'indirizzo, dove resterebbe nella cronologia:
il callback lo lascia pronto in un cookie HttpOnly che vale due minuti, e la
pagina lo ritira con una chiamata. Il token è quello di sempre (security.py).

Quale account apre Google:
- l'account Google è già collegato a un utente: quell'utente;
- c'è un utente con la stessa email, verificata da Google: si entra in quello e
  Google gli resta collegato, senza doppioni. Se l'account aveva una password gli
  si scrive: se non l'aveva scelta lui (chiunque può aprire un account con
  un'email altrui, che qui non si verifica) la cambi;
- nessuno: la registrazione, con termini ed età come per tutti.
"""
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.db import get_db
from backend.app.models import Organization, User, UserIdentity, UserRole
from backend.app.schemas import (
    GoogleFinishOut,
    GoogleSignupIn,
    GoogleStartIn,
    GoogleStatusOut,
    TokenOut,
)
from backend.app.security import SCARTO_OROLOGIO, create_access_token, get_current_user
from backend.app.services import google_login
from backend.app.services.email import Sender, send_email
from backend.app.services.google_login import GoogleAccount, GoogleLoginError

router = APIRouter(prefix="/auth/google", tags=["auth"])

PROVIDER = "google"
COOKIE = "m2f_google"
COOKIE_PATH = "/api/auth/google"
FLOW_MINUTES = 10      # il tempo per scegliere l'account su Google
RESULT_MINUTES = 2     # il token pronto da ritirare
SIGNUP_MINUTES = 15    # il tempo per completare la registrazione
# `next` arriva dall'indirizzo: solo pagine di questo sito, niente "//altrove" o "javascript:".
_SAFE_NEXT = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_\-./?=&%+]*$")


def safe_next(value: str | None) -> str:
    value = (value or "").strip()
    return value if len(value) <= 300 and _SAFE_NEXT.match(value) else ""


# ── Il cookie del giro ────────────────────────────────────────────────────

def _set_cookie(response: Response, purpose: str, minutes: int, **claims) -> None:
    """Un JWT firmato col segreto del sito. Porta `purpose`, quindi
    get_current_user non lo accetta come token di accesso."""
    settings = get_settings()
    value = jwt.encode(
        {"purpose": purpose, "exp": datetime.now(UTC) + timedelta(minutes=minutes), **claims},
        settings.secret_key, algorithm="HS256",
    )
    response.set_cookie(
        COOKIE, value, max_age=minutes * 60, path=COOKIE_PATH, httponly=True,
        # Lax: il ritorno da Google è una navigazione, e il cookie la segue.
        samesite="lax", secure=str(settings.frontend_url).startswith("https://"),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path=COOKIE_PATH)


def _read_cookie(request: Request) -> dict:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return {}
    try:
        return jwt.decode(raw, get_settings().secret_key, algorithms=["HS256"],
                          leeway=SCARTO_OROLOGIO)
    except jwt.PyJWTError:
        return {}


def _redirect(page: str, **params: str) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value})
    return RedirectResponse(f"/{page}" + (f"?{query}" if query else ""), status_code=303)


# ── Gli account ───────────────────────────────────────────────────────────

def _identity_of(db: Session, user_id: int) -> UserIdentity | None:
    return db.scalar(select(UserIdentity).where(
        UserIdentity.user_id == user_id, UserIdentity.provider == PROVIDER))


def _identity_by_subject(db: Session, subject: str) -> UserIdentity | None:
    return db.scalar(select(UserIdentity).where(
        UserIdentity.provider == PROVIDER, UserIdentity.subject == subject))


def _user_by_email(db: Session, email: str) -> User | None:
    """L'account con quell'email. Ospiti e profili dei minori hanno indirizzi
    finti, ma per sicurezza non si cercano nemmeno."""
    return db.scalar(select(User).where(
        User.email == email, User.is_guest.is_(False), User.guardian_id.is_(None)))


def _attach(db: Session, user: User, account: GoogleAccount) -> None:
    """Collega l'account Google all'utente. Uno per utente, e uno solo utente per account."""
    current = _identity_of(db, user.id)
    if current is not None:
        if current.subject == account.subject:
            return
        raise GoogleLoginError("altro_google")
    owner = _identity_by_subject(db, account.subject)
    if owner is not None and owner.user_id != user.id:
        raise GoogleLoginError("gia_collegato")
    db.add(UserIdentity(user_id=user.id, provider=PROVIDER, subject=account.subject,
                        email=account.email))


def _merge_by_email(db: Session, user: User, account: GoogleAccount) -> bool:
    """Google entra nell'account che ha la sua stessa email. Dice se c'era una password.

    La registrazione con password non verifica l'email: chiunque può aprire un account
    con l'indirizzo di un altro. Google invece l'indirizzo l'ha verificato, quindi chi
    arriva da lì è il padrone dell'email. La password che c'era la toglie, e con lei le
    sessioni aperte e i link di reset già spediti (vanno tutti con `token_version`):
    se era sua, se ne sceglie una nuova con «Password dimenticata».
    """
    _attach(db, user, account)
    if not user.password_hash:
        return False
    user.password_hash = None
    user.token_version = (user.token_version or 0) + 1
    return True


def _tell_about_merge(user: User, account: GoogleAccount) -> None:
    send_email(
        user.email,
        "Mull2Five — Google collegato al tuo account",
        f"Ciao {user.display_name},\n\n"
        f"sei appena entrato in Mull2Five con Google ({account.email}): l'account che "
        "avevi con questa email è lo stesso, e da adesso si apre con Google.\n\n"
        "Per sicurezza abbiamo disattivato la password che aveva l'account e chiuso le "
        "sessioni aperte: un account con password si può aprire anche con l'indirizzo di "
        "un altro, Google invece ci conferma che l'email è tua.\n\n"
        "Se vuoi entrare anche con la password, scegline una nuova con «Password "
        "dimenticata» dalla pagina di accesso.",
        sender=Sender.ACCOUNT,
    )


def own_account(request: Request, user: User = Depends(get_current_user)) -> User:
    """Google si collega e si scollega dal proprio account, non da un profilo gestito."""
    if request.headers.get("X-Act-As"):
        raise HTTPException(status_code=400, detail="Google si collega solo al tuo account")
    return user


def _require_enabled() -> None:
    if not google_login.is_enabled():
        raise HTTPException(status_code=503, detail="L'accesso con Google non è attivo")


def _start(response: Response, next_page: str, link_user: User | None = None) -> dict[str, str]:
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    claims = {"state": state, "nonce": nonce, "next": next_page}
    if link_user is not None:
        claims |= {"link": link_user.id, "tv": link_user.token_version or 0}
    _set_cookie(response, "google-flow", FLOW_MINUTES, **claims)
    return {"authorization_url": google_login.authorization_url(state, nonce)}


# ── Gli endpoint ──────────────────────────────────────────────────────────

@router.post("/start")
@limiter.limit("10/minute")
def start(request: Request, response: Response, payload: GoogleStartIn) -> dict[str, str]:
    """Accesso o registrazione: dove mandare il browser."""
    _require_enabled()
    return _start(response, safe_next(payload.next))


@router.post("/link")
@limiter.limit("10/minute")
def start_link(
    request: Request, response: Response,
    user: User = Depends(own_account), db: Session = Depends(get_db),
) -> dict[str, str]:
    """Dal profilo: collegare Google all'account con cui si è già dentro."""
    _require_enabled()
    if _identity_of(db, user.id):
        raise HTTPException(status_code=409, detail="Google è già collegato al tuo account")
    return _start(response, "", link_user=user)


@router.get("/callback", include_in_schema=False)
@limiter.limit("20/minute")
def callback(
    request: Request, code: str = "", state: str = "", error: str = "",
    db: Session = Depends(get_db),
) -> RedirectResponse:
    flow = _read_cookie(request)
    if flow.get("purpose") != "google-flow":
        response = _redirect("login.html", google_error="stato")
        _clear_cookie(response)
        return response
    linking = "link" in flow
    page = "my-registrations.html" if linking else "login.html"
    next_page = safe_next(flow.get("next"))

    def fail(reason: str) -> RedirectResponse:
        db.rollback()
        response = _redirect(page, google_error=reason, next=next_page)
        _clear_cookie(response)
        return response

    if error:   # ha chiuso la finestra di Google o non ha dato il consenso
        return fail("annullato")
    if not google_login.is_enabled():
        return fail("non_disponibile")
    if not state or not hmac.compare_digest(state, str(flow.get("state", ""))):
        return fail("stato")
    if not code:
        return fail("rifiutato")
    try:
        account = google_login.verify_id_token(google_login.exchange_code(code), flow["nonce"])
        if linking:
            user = db.get(User, flow["link"])
            if not user or not user.is_active or flow.get("tv") != (user.token_version or 0):
                return fail("stato")
            _attach(db, user, account)
            db.commit()
            response = _redirect(page, google="collegato")
            _clear_cookie(response)
            return response
        return _sign_in(db, account, next_page)
    except GoogleLoginError as exc:
        return fail(exc.code)
    except IntegrityError:   # due giri insieme sullo stesso account Google
        return fail("gia_collegato")


def _sign_in(db: Session, account: GoogleAccount, next_page: str) -> RedirectResponse:
    identity = _identity_by_subject(db, account.subject)
    merged = False
    if identity is not None:
        user = db.get(User, identity.user_id)
    else:
        user = _user_by_email(db, account.email)
        if user is None:
            response = _redirect("login.html", google="registrati", next=next_page)
            _set_cookie(response, "google-signup", SIGNUP_MINUTES,
                        gsub=account.subject, email=account.email, name=account.name)
            return response
        if user.is_active:
            had_password = _merge_by_email(db, user, account)
            db.commit()
            merged = True
            if had_password:
                _tell_about_merge(user, account)
    if user is None or not user.is_active:
        raise GoogleLoginError("disattivato")
    response = _redirect("login.html", google="1", next=next_page)
    _set_cookie(response, "google-login", RESULT_MINUTES,
                uid=user.id, tv=user.token_version or 0, merged=merged)
    return response


@router.post("/finish", response_model=GoogleFinishOut)
def finish(request: Request, response: Response, db: Session = Depends(get_db)) -> GoogleFinishOut:
    """Di ritorno da Google: il token di accesso, o i dati per completare la registrazione."""
    claims = _read_cookie(request)
    if claims.get("purpose") == "google-signup":
        return GoogleFinishOut(signup_email=claims.get("email"), signup_name=claims.get("name"))
    expired = HTTPException(status_code=400, detail="L'accesso con Google è scaduto: riprova")
    if claims.get("purpose") != "google-login":
        raise expired
    user = db.get(User, int(claims.get("uid", 0)))
    if not user or not user.is_active or claims.get("tv") != (user.token_version or 0):
        raise expired
    _clear_cookie(response)   # il token si ritira una volta
    return GoogleFinishOut(access_token=create_access_token(user),
                           linked_existing=bool(claims.get("merged")))


@router.post("/complete", response_model=TokenOut, status_code=201)
@limiter.limit("5/minute")
def complete_signup(
    request: Request, response: Response, payload: GoogleSignupIn, db: Session = Depends(get_db),
) -> TokenOut:
    """Chi entra con Google per la prima volta: l'account nasce qui, con termini ed età."""
    claims = _read_cookie(request)
    if claims.get("purpose") != "google-signup":
        raise HTTPException(status_code=400, detail="La registrazione con Google è scaduta: riprova")
    if payload.age_confirmed is not True:
        raise HTTPException(
            status_code=422,
            detail=f"Per aprire un account servono almeno {get_settings().min_account_age} anni: "
                   "un genitore può aggiungerti come profilo dal suo account.",
        )
    if payload.terms_accepted is not True:
        raise HTTPException(status_code=422, detail="Per aprire un account accetta i termini e l'informativa privacy")
    account = GoogleAccount(subject=str(claims["gsub"]), email=str(claims["email"]),
                            name=str(claims.get("name", "")))
    try:
        identity = _identity_by_subject(db, account.subject)
        # Nel frattempo l'account può essere nato da un'altra scheda, o con la password.
        user = db.get(User, identity.user_id) if identity else _user_by_email(db, account.email)
        merged = False
        if user is None:
            role = payload.role if payload.role in {UserRole.PLAYER, UserRole.ORGANIZER} else UserRole.PLAYER
            default_org = db.scalar(select(Organization).where(Organization.is_default.is_(True)))
            user = User(
                email=account.email,
                display_name=payload.display_name.strip(),
                role=role,
                password_hash=None,   # se la vuole, la sceglie con «Password dimenticata»
                organization_id=default_org.id if default_org else None,
                terms_accepted_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
        if not user.is_active:
            raise GoogleLoginError("disattivato")
        if identity is None:
            merged = _merge_by_email(db, user, account)
        db.commit()
    except (GoogleLoginError, IntegrityError):
        db.rollback()
        raise HTTPException(status_code=409, detail="Questo account Google è già collegato a un altro account") from None
    db.refresh(user)
    if merged:
        _tell_about_merge(user, account)
    _clear_cookie(response)
    return TokenOut(access_token=create_access_token(user))


@router.get("/me", response_model=GoogleStatusOut)
def google_status(user: User = Depends(own_account), db: Session = Depends(get_db)) -> GoogleStatusOut:
    """Per il profilo: se Google è collegato, e se c'è anche la password."""
    identity = _identity_of(db, user.id)
    return GoogleStatusOut(available=google_login.is_enabled(), linked=identity is not None,
                           email=identity.email if identity else "",
                           has_password=bool(user.password_hash))


@router.delete("/me", response_model=GoogleStatusOut)
def unlink(user: User = Depends(own_account), db: Session = Depends(get_db)) -> GoogleStatusOut:
    identity = _identity_of(db, user.id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Google non è collegato al tuo account")
    if not user.password_hash:
        raise HTTPException(
            status_code=409,
            detail="Prima di scollegare Google scegli una password: senza, non avresti più modo di entrare",
        )
    db.delete(identity)
    db.commit()
    return google_status(user, db)
