"""
Account lockout dei login, backed da Redis (condiviso tra worker/istanze).

Conta i tentativi falliti per email in una finestra scorrevole. Con Redis reale
il blocco è coerente su tutto il cluster; col fallback in-memory resta per-istanza.
"""
from backend.app.core.redis import get_redis

MAX_ATTEMPTS = 5
WINDOW_SECS = 30 * 60  # 30 minuti

_PREFIX = "lockout:"


def _key(email: str) -> str:
    return _PREFIX + email.lower()


def record_failed(email: str) -> None:
    r = get_redis()
    key = _key(email)
    count = r.incr(key)
    if count == 1:
        # Primo tentativo della finestra: imposta la scadenza.
        r.expire(key, WINDOW_SECS)


def is_locked(email: str) -> bool:
    raw = get_redis().get(_key(email))
    try:
        return int(raw) >= MAX_ATTEMPTS if raw is not None else False
    except (ValueError, TypeError):
        return False


def reset(email: str) -> None:
    get_redis().delete(_key(email))
