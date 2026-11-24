from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mull2Five"
    # "production" è il sito vero; qualunque altro valore — "development",
    # "staging", "test" — è una copia, e una copia non va né indicizzata dai
    # motori di ricerca né scambiata per l'originale da chi ci capita.
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
    # L'identificativo del webhook, dal cruscotto PayPal. Senza non si può
    # verificare che una notifica venga davvero da PayPal, e quell'endpoint è
    # pubblico: chiunque potrebbe dichiarare pagata un'iscrizione. Se manca, le
    # notifiche vengono rifiutate.
    paypal_webhook_id: str | None = None
    payment_sandbox_mock: bool = True
    # Spento, si paga solo al banco: Stripe e PayPal non si scelgono, non si
    # mostrano e il checkout li rifiuta (services/payments.py, `in_person_only`).
    # Spento in produzione finché i pagamenti online non sono passati dal legale;
    # lo staging li tiene accesi per provarli.
    online_payments_enabled: bool = True
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

    # Accesso con Google (services/google_login.py): le credenziali OAuth del
    # progetto nella Google Cloud Console. Senza entrambe il bottone non compare.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # L'indirizzo a cui Google rimanda dopo l'accesso, registrato tale e quale
    # nella console. Vuoto: FRONTEND_URL + /api/auth/google/callback.
    google_redirect_uri: str = ""

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@mull2five.local"
    # Caselle a parte per l'accesso (reset password, invito a sceglierla) e per i
    # pagamenti (services/email.py, `Sender`). Vuote, si usa quella generale; un
    # indirizzo senza credenziali sue usa quelle generali (Brevo: una chiave, più
    # mittenti), con credenziali sue entra come sé stesso (una casella register.it).
    smtp_account_from_email: str | None = None
    smtp_account_username: str | None = None
    smtp_account_password: str | None = None
    smtp_payments_from_email: str | None = None
    smtp_payments_username: str | None = None
    smtp_payments_password: str | None = None
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
    # Le email che arrivano alle caselle del sito (quelle di SMTP_*), avvisate su
    # Telegram (services/mail_watch.py). Senza IMAP_HOST o senza Telegram è spento.
    # register.it: pop.securemail.pro, porta 993 (mail.securemail.pro rifiuta l'accesso).
    imap_host: str | None = None
    imap_port: int = 993
    mail_watch_interval_secs: int = 60
    # Il controllo da GitHub (scripts/stato_sito.py) che non passa da tante ore:
    # nessuno avvisa più se il sito cade, e di solito è fermo anche il backup.
    # Solo con Telegram; 0 = spento (services/site_watch.py).
    status_check_alert_hours: int = 3
    # Il piano gratuito di Supabase arriva a 500 MB: oltre questa soglia si avvisa,
    # una volta al giorno. 0 = spento.
    db_size_alert_mb: int = 400

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

    @property
    def is_copy(self) -> bool:
        """Una copia del sito: staging, sviluppo, test. Non va indicizzata.

        Elencate per nome, invece di dedurle da `app_env != "production"`: se un
        giorno la produzione dicesse "prod", dedurne "è una copia" toglierebbe
        il sito vero dai motori di ricerca, e si recupera in settimane. Uno
        staging indicizzato per sbaglio è un fastidio. Nel dubbio, si indicizza.
        """
        return self.app_env.strip().lower() in {"development", "dev", "staging", "stage",
                                                "test", "preview", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
