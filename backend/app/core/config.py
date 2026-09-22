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
    # Tre giorni: chi usa il sito resta dentro perché il token si rinnova da solo
    # (POST /auth/refresh, da js/session.js); chi sparisce per giorni rientra.
    access_token_minutes: int = 60 * 24 * 3
    # Giri di PBKDF2-SHA256 per le password nuove; quelle con meno giri si
    # rifanno al login (security.password_needs_rehash).
    password_hash_rounds: int = 200_000
    database_url: str = "sqlite:///./mull2five.db"
    # Cartella della build Vite da servire su "/". La imposta il Dockerfile; in
    # sviluppo resta vuota e le pagine le serve Vite.
    frontend_dist: str | None = None


    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_env: str = "sandbox"
    payment_sandbox_mock: bool = True
    # Quota della piattaforma sui pagamenti con carta che vanno a un negozio con
    # Stripe collegato (0 = tutto al negozio, meno le commissioni di Stripe).
    platform_fee_percent: float = 0.0
    # Importazione dei tornei dal Wizards Event Locator (services/wizards_locator.py):
    # spenta, perché le condizioni d'uso di Wizards vietano la raccolta automatica.
    wizards_locator_enabled: bool = False
    # L'indirizzo pubblico del sito, per sitemap e robots.txt. Vuoto: FRONTEND_URL.
    site_url: str = ""
    # Chi gestisce il sito, per informativa privacy e termini (privacy.html,
    # termini.html): vuoti, le pagine dicono che sono da completare.
    legal_name: str = ""
    legal_email: str = ""
    legal_address: str = ""
    legal_vat_id: str = ""
    # Statistiche delle visite senza cookie né dati personali (routers/site.py).
    analytics_enabled: bool = True

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@mull2five.local"
    # L'invio parte su un thread a parte: la richiesta non aspetta il server SMTP.
    email_async: bool = True
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

    # Il fuso dei negozi: date e orari dei tornei sono locali, non UTC.
    app_timezone: str = "Europe/Rome"

    # I giochi che si possono scegliere, separati da virgola ("all" per tutti).
    # Gli altri ci sono, con formati e spareggi, ma restano spenti finché non
    # si accendono qui.
    enabled_games: str = "mtg"

    # Sotto quest'età non si apre un account da soli: un genitore aggiunge il
    # ragazzo come profilo gestito dal suo (14 anni è il consenso digitale in Italia).
    min_account_age: int = 14


@lru_cache
def get_settings() -> Settings:
    return Settings()
