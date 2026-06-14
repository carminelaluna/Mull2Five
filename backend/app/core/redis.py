"""
Client Redis unificato con fallback in-memory.

Tutta l'app usa `get_redis()`. In produzione (REDIS_URL impostato e raggiungibile)
restituisce un client Redis reale, condiviso tra worker Gunicorn e istanze multiple.
In sviluppo o se Redis è giù, restituisce un finto client thread-safe che vive nel
processo: l'API resta funzionante (cache locale, lockout per-istanza) senza crash.

Espone il sottoinsieme di comandi che ci serve: get/set(ex)/delete/incr/expire/
keys/ping, più un helper scan_prefix per invalidare per prefisso.
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


class _InMemoryRedis:
    """Fallback minimale, API-compatibile con i comandi che usiamo."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = Lock()

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] is not None and time.monotonic() >= item[1]:
            self._data.pop(key, None)
            return False
        return True

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data[key][0] if self._alive(key) else None

    def set(self, key: str, value: Any, ex: float | None = None) -> bool:
        with self._lock:
            self._data[key] = (str(value), time.monotonic() + ex if ex else None)
            return True

    def delete(self, *keys: str) -> int:
        with self._lock:
            return sum(self._data.pop(k, None) is not None for k in keys)

    def incr(self, key: str) -> int:
        with self._lock:
            cur = int(self._data[key][0]) if self._alive(key) else 0
            cur += 1
            exp = self._data[key][1] if key in self._data else None
            self._data[key] = (str(cur), exp)
            return cur

    def expire(self, key: str, seconds: float) -> bool:
        with self._lock:
            if not self._alive(key):
                return False
            self._data[key] = (self._data[key][0], time.monotonic() + seconds)
            return True

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.rstrip("*")
        with self._lock:
            return [k for k in list(self._data) if self._alive(k) and k.startswith(prefix)]

    def ping(self) -> bool:
        return True


_client: Any | None = None
_is_real = False


def get_redis() -> Any:
    """Restituisce il client Redis (reale o in-memory). Singleton per processo."""
    global _client, _is_real
    if _client is not None:
        return _client

    settings = get_settings()
    if settings.redis_url:
        try:
            import redis  # import locale: dipendenza opzionale

            client = redis.Redis.from_url(
                settings.redis_url, decode_responses=True, socket_connect_timeout=2
            )
            client.ping()
            _client, _is_real = client, True
            logger.info("Redis connesso: %s", settings.redis_url)
            return _client
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis non disponibile (%s) — uso fallback in-memory", exc)

    _client, _is_real = _InMemoryRedis(), False
    return _client


def redis_is_real() -> bool:
    get_redis()
    return _is_real


def scan_prefix(prefix: str) -> list[str]:
    return get_redis().keys(f"{prefix}*")
