"""
google_login.py — La parte dell'accesso con Google che parla con Google.

OpenID Connect, flusso "authorization code" lato server:
1. il sito manda il browser da Google con `state` e `nonce` inventati sul momento
   (authorization_url);
2. Google lo rimanda indietro con un `code`, che il server scambia con un
   id_token chiedendolo direttamente a Google, con il segreto del client
   (exchange_code);
3. l'id_token si verifica (verify_id_token): firma con le chiavi pubbliche di
   Google, `aud` uguale al nostro client, `iss` di Google, non scaduto, `nonce`
   uguale a quello del punto 1, email verificata da Google.

Chi entra, e in quale account, lo decide routers/google_auth.py.
"""
import hmac
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from backend.app.core.config import get_settings
from backend.app.security import SCARTO_OROLOGIO

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class GoogleLoginError(Exception):
    """L'accesso non è andato: `code` dice perché, e la pagina lo spiega."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GoogleAccount:
    subject: str   # il `sub`: chi è la persona per Google, non cambia con l'email
    email: str
    name: str


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    settings = get_settings()
    return settings.google_redirect_uri or (
        f"{str(settings.frontend_url).rstrip('/')}/api/auth/google/callback"
    )


def authorization_url(state: str, nonce: str) -> str:
    params = {
        "client_id": get_settings().google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        # Chi ha più account Google sceglie quale usare, invece di entrare col primo.
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> str:
    """L'id_token in cambio del `code`, chiesto a Google da server a server."""
    settings = get_settings()
    try:
        response = httpx.post(TOKEN_URL, timeout=10, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
    except httpx.HTTPError:
        raise GoogleLoginError("rifiutato") from None
    if response.status_code != 200:
        raise GoogleLoginError("rifiutato")
    id_token = response.json().get("id_token")
    if not id_token:
        raise GoogleLoginError("rifiutato")
    return id_token


_jwks_client: jwt.PyJWKClient | None = None


def _signing_key(id_token: str):
    """La chiave pubblica di Google che ha firmato il token (le chiavi si tengono un'ora)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_jwk_set=True, lifespan=3600, timeout=10)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, nonce: str) -> GoogleAccount:
    try:
        claims = jwt.decode(
            id_token,
            _signing_key(id_token),
            algorithms=["RS256"],
            audience=get_settings().google_client_id,
            issuer=ISSUERS,
            leeway=SCARTO_OROLOGIO,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]},
        )
    except jwt.PyJWTError:
        raise GoogleLoginError("rifiutato") from None
    # Il nonce lega il token a questo giro: un id_token rubato altrove non entra.
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleLoginError("stato")
    email = str(claims.get("email", "")).strip().lower()
    # Solo un'email che Google ha verificato può aprire, o unirsi a, un account di qui.
    if not email or claims.get("email_verified") not in (True, "true"):
        raise GoogleLoginError("non_verificata")
    name = str(claims.get("name") or "").strip()[:160]
    return GoogleAccount(subject=str(claims["sub"]), email=email,
                         name=name if len(name) >= 2 else email.split("@")[0][:160])
