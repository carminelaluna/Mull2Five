"""
Web Push (VAPID): invio notifiche push ai browser iscritti.

- `generate_vapid_keys()` / `python -m backend.app.core.webpush genkeys` per le chiavi.
- `send_push(subscription, payload)` invia una notifica; gli endpoint scaduti (404/410)
  vengono segnalati al chiamante per la rimozione.
Se pywebpush non è installato o le chiavi VAPID non sono configurate, le funzioni
diventano no-op (l'app resta avviabile, semplicemente non invia push).
"""
from __future__ import annotations

import json
import logging

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    from pywebpush import WebPushException, webpush

    _AVAILABLE = True
except Exception:  # noqa: BLE001 — dipendenza opzionale
    _AVAILABLE = False


def push_enabled() -> bool:
    s = get_settings()
    return _AVAILABLE and bool(s.vapid_public_key and s.vapid_private_key)


def public_key() -> str | None:
    return get_settings().vapid_public_key


def send_push(subscription_info: dict, payload: dict) -> str:
    """Invia una push. Ritorna: 'sent' | 'gone' (endpoint da rimuovere) | 'skipped' | 'error'."""
    if not push_enabled():
        return "skipped"
    s = get_settings()
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": s.vapid_subject},
            timeout=10,
        )
        return "sent"
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.warning("Web push fallita: %s", exc)
        return "error"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web push errore: %s", exc)
        return "error"


def generate_vapid_keys() -> dict[str, str]:
    """Genera una coppia di chiavi VAPID (base64url) per .env."""
    from py_vapid import Vapid01

    v = Vapid01()
    v.generate_keys()
    return {
        "public_key": v.public_key_urlsafe_base64(),
        "private_key": v.private_key_urlsafe_base64(),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "genkeys":
        keys = generate_vapid_keys()
        print("VAPID_PUBLIC_KEY=" + keys["public_key"])
        print("VAPID_PRIVATE_KEY=" + keys["private_key"])
    else:
        print("Uso: python -m backend.app.core.webpush genkeys")
