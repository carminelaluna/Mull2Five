from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import HTTPException
from jose import jwt

from backend.app.core.config import get_settings


async def fetch_google_profile(code: str, redirect_uri: str) -> dict[str, str]:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        profile_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()

    return {
        "provider_user_id": profile["sub"],
        "email": profile["email"].lower(),
        "display_name": profile.get("name") or profile["email"].split("@")[0],
    }


async def fetch_apple_profile(code: str, redirect_uri: str) -> dict[str, str]:
    settings = get_settings()
    if not all(
        [
            settings.apple_client_id,
            settings.apple_team_id,
            settings.apple_key_id,
            settings.apple_private_key_path,
        ]
    ):
        raise HTTPException(status_code=503, detail="Apple OAuth is not configured")

    private_key = Path(settings.apple_private_key_path).read_text(encoding="utf-8")
    now = datetime.now(UTC)
    client_secret = jwt.encode(
        {
            "iss": settings.apple_team_id,
            "iat": now,
            "exp": now + timedelta(days=180),
            "aud": "https://appleid.apple.com",
            "sub": settings.apple_client_id,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://appleid.apple.com/auth/token",
            data={
                "client_id": settings.apple_client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        token_response.raise_for_status()
        id_token = token_response.json()["id_token"]

    claims = jwt.get_unverified_claims(id_token)
    email = claims.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Apple did not return an email")
    return {
        "provider_user_id": claims["sub"],
        "email": email.lower(),
        "display_name": email.split("@")[0],
    }

