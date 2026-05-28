from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Arcana Events"
    app_env: str = "development"
    app_url: AnyHttpUrl = "http://127.0.0.1:8000"
    frontend_url: AnyHttpUrl = "http://127.0.0.1:8000"
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    access_token_minutes: int = 60 * 24 * 7
    database_url: str = "sqlite:///./arcana_events.db"

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
    smtp_from_email: str = "noreply@arcana-events.local"
    smtp_use_tls: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
