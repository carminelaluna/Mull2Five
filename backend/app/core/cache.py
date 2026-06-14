"""
Cache con TTL per endpoint read-heavy, backed da Redis.

Se REDIS_URL non è configurato (o Redis è giù) il client ripiega su una cache
in-memory thread-safe: stessa API, nessun crash. I valori sono serializzati in JSON.
"""
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from backend.app.core.redis import get_redis, redis_is_real, scan_prefix

_PREFIX = "cache:"


def _json_default(obj: Any) -> Any:
    """Serializza i tipi non-JSON in modo che sopravvivano al round-trip.

    IMPORTANTE: i modelli Pydantic diventano dict (model_dump), NON la loro repr.
    Altrimenti sul cache-hit l'endpoint restituirebbe stringhe invece di oggetti
    e FastAPI solleverebbe ResponseValidationError. mode="json" rende anche
    datetime/Enum stringhe, così json.loads ricostruisce dict puliti che il
    response_model è in grado di rivalidare.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def cache_get(key: str) -> Any | None:
    # Senza Redis la cache è in-memory PER-WORKER: con più worker Gunicorn
    # l'invalidazione non si propaga e si servono dati stale (es. pagamento
    # segnato ma non aggiornato, risultati non visibili). Quindi è un no-op
    # finché non c'è un backend condiviso (Redis). Vedi core/redis.py.
    if not redis_is_real():
        return None
    raw = get_redis().get(_PREFIX + key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def cache_set(key: str, value: Any, ttl: float = 5.0) -> None:
    if not redis_is_real():
        return
    try:
        payload = json.dumps(value, default=_json_default)
    except (TypeError, ValueError):
        return
    get_redis().set(_PREFIX + key, payload, ex=ttl)


def cache_invalidate(prefix: str) -> None:
    """Invalida tutte le chiavi che iniziano con prefix."""
    keys = scan_prefix(_PREFIX + prefix)
    if keys:
        get_redis().delete(*keys)


def cache_stats() -> dict:
    keys = scan_prefix(_PREFIX)
    return {"total": len(keys), "backend": "redis" if redis_is_real() else "memory"}
