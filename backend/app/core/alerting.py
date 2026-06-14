"""
Alerting operativo: notifica quando qualcosa va storto (DB giù, errori 5xx).

Canali (tutti opzionali, configurati via env):
  - Email   → settings.alert_email (riusa il servizio SMTP esistente)
  - Telegram → settings.telegram_bot_token + telegram_chat_id

Caratteristiche:
  - Throttle anti-spam per "chiave" via Redis (coerente tra worker/istanze):
    lo stesso alert non parte più di una volta ogni `alert_throttle_secs`.
  - Fire-and-forget: l'invio non blocca la richiesta (gira in un thread).
  - No-op se nessun canale è configurato.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from backend.app.core.config import get_settings
from backend.app.core.redis import get_redis

logger = logging.getLogger(__name__)

_THROTTLE_PREFIX = "alert:throttle:"


def alerting_enabled() -> bool:
    s = get_settings()
    return bool(s.alert_email or (s.telegram_bot_token and s.telegram_chat_id))


def _should_send(key: str, throttle_secs: int) -> bool:
    """True se non abbiamo già inviato questo alert di recente. Atomico via Redis."""
    if throttle_secs <= 0:
        return True
    r = get_redis()
    tkey = _THROTTLE_PREFIX + key
    # incr+expire: il primo nella finestra ottiene 1 (invia), gli altri >1 (skip).
    count = r.incr(tkey)
    if count == 1:
        r.expire(tkey, throttle_secs)
        return True
    return False


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alert Telegram non inviato: %s", exc)


def _send_email_alert(to: str, subject: str, body: str) -> None:
    from backend.app.services.email import send_email

    try:
        send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alert email non inviato: %s", exc)


def _dispatch(subject: str, message: str) -> None:
    s = get_settings()
    if s.alert_email:
        _send_email_alert(s.alert_email, subject, message)
    if s.telegram_bot_token and s.telegram_chat_id:
        _send_telegram(s.telegram_bot_token, s.telegram_chat_id, f"{subject}\n\n{message}")


def send_alert(key: str, subject: str, message: str, *, level: str = "error") -> bool:
    """Invia un alert sui canali configurati (throttled per `key`).
    Ritorna True se l'alert è stato accodato, False se soppresso/disabilitato.
    Non solleva mai: l'alerting non deve mai rompere il flusso chiamante.
    """
    try:
        s = get_settings()
        if not alerting_enabled():
            return False
        if not _should_send(key, s.alert_throttle_secs):
            return False
        full_subject = f"[Manabind {level.upper()}] {subject}"
        logger.warning("ALERT %s: %s — %s", level, subject, message)
        # Fire-and-forget: non blocchiamo il chiamante.
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _dispatch, full_subject, message)
        except RuntimeError:
            # Nessun event loop (contesto sincrono): invia inline.
            _dispatch(full_subject, message)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_alert fallito: %s", exc)
        return False
