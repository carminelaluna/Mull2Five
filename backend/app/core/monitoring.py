"""
Monitoring: metriche Prometheus + middleware di timing.

Espone counters/histogram standard (richieste, latenza, errori) e l'endpoint
/metrics nel formato testuale Prometheus. Se prometheus_client non è installato,
le funzioni diventano no-op così l'app resta avviabile.
"""
from __future__ import annotations

import time

from starlette.requests import Request
from starlette.responses import Response

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _ENABLED = True
except Exception:  # noqa: BLE001 — dipendenza opzionale
    _ENABLED = False


if _ENABLED:
    REQUEST_COUNT = Counter(
        "manabind_http_requests_total",
        "Totale richieste HTTP",
        ["method", "path", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "manabind_http_request_duration_seconds",
        "Durata richieste HTTP in secondi",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    )


def _route_template(request: Request) -> str:
    """Usa il path-template della route (/tournaments/{id}) per evitare
    esplosione di label (cardinalità) sui path con id variabili."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


async def metrics_middleware(request: Request, call_next):
    if not _ENABLED:
        return await call_next(request)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        path = _route_template(request)
        elapsed = time.perf_counter() - start
        REQUEST_COUNT.labels(request.method, path, str(status)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)


def metrics_response() -> Response:
    if not _ENABLED:
        return Response("prometheus_client non installato\n", media_type="text/plain")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def monitoring_enabled() -> bool:
    return _ENABLED
