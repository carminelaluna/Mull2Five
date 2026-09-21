from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mull2Five"
    app_env: str = "development"
    app_url: AnyHttpUrl = "http://127.0.0.1:8000"
    frontend_url: AnyHttpUrl = "http://127.0.0.1:8000"
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    access_token_minutes: int = 60 * 24 * 7
    database_url: str = "sqlite:///./mull2five.db"
    # Cartella della build Vite da servire su "/". La imposta il Dockerfile; in
    # sviluppo resta vuota e le pagine le serve Vite.
    frontend_dist: str | None = None

    google_client_id: str | None = None
    google_client_secret: str | None = None
    apple_client_id: str | None = None
    apple_team_id: str | None = None
    apple_key_id: str | None = None
    apple_private_key_path: str | None = None

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_env: str = "sandbox"
    payment_sandbox_mock: bool = True

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@mull2five.local"
    smtp_use_tls: bool = True

    # Redis: cache distribuita + lockout condiviso tra worker/istanze.
    # Se vuoto o irraggiungibile si usa il fallback in-memory (single-instance).
    redis_url: str | None = None

    # Web Push (VAPID). Genera le chiavi con: `python -m backend.app.core.webpush genkeys`
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:noreply@mull2five.local"

    # Monitoring: protegge /metrics con un token (se impostato).
    metrics_token: str | None = None

    # Alerting: notifica operativa quando qualcosa va storto (DB giù, errori 5xx).
    # Canali opzionali: email a alert_email, e/o Telegram (bot token + chat id).
    alert_email: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # Throttle anti-spam: stesso alert (per chiave) non più di una volta ogni N secondi.
    alert_throttle_secs: int = 300
    # Watchdog: intervallo di self-check del DB (0 = disabilitato).
    watchdog_interval_secs: int = 60

    # Multi-tenant: header che identifica l'organizzazione (negozio) corrente.
    tenant_header: str = "X-Mull2Five-Org"


@lru_cache
def get_settings() -> Settings:
    return Settings()
