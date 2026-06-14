"""
test_infra.py — Feature infrastrutturali: cache/lockout (Redis fallback),
monitoring (/metrics), Web Push (VAPID), multi-tenant (organizations).
"""


def test_health_reports_cache_backend(client):
    body = client.get("/health").json()
    assert body["cache"] in {"redis", "memory"}


def test_metrics_endpoint(client):
    # genera un po' di traffico
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # prometheus_client è installato → deve esserci il nome metrica
    assert "arcana_http_requests_total" in resp.text


def test_vapid_key_endpoint(client):
    resp = client.get("/api/push/vapid-key")
    assert resp.status_code == 200
    body = resp.json()
    # Senza chiavi VAPID configurate, push disabilitato ma endpoint funzionante.
    assert body["enabled"] is False


def test_push_subscribe_requires_auth(client):
    resp = client.post(
        "/api/push/subscribe",
        json={"endpoint": "https://example.com/x", "keys": {"p256dh": "a", "auth": "b"}},
    )
    assert resp.status_code == 401


def test_organizations_listing_public(client):
    resp = client.get("/api/organizations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_cache_is_noop_without_redis():
    """Senza Redis la cache è bypassata (no-op): evita stale per-worker.
    Con Redis reale tornerebbe attiva; qui nei test non c'è Redis."""
    from backend.app.core.cache import cache_get, cache_set
    from backend.app.core.redis import redis_is_real

    cache_set("t:k", {"v": 1}, ttl=30)
    if redis_is_real():
        assert cache_get("t:k") == {"v": 1}
    else:
        assert cache_get("t:k") is None


def test_alerting_disabled_by_default():
    from backend.app.core.alerting import alerting_enabled, send_alert

    # Nessun canale configurato nei test → alerting disabilitato, send_alert no-op.
    assert alerting_enabled() is False
    assert send_alert("k", "subj", "msg") is False


def test_alerting_status_requires_admin(client):
    assert client.get("/api/admin/alerting").status_code == 401


def test_cache_serialization_pydantic_roundtrip():
    """Regressione: la serializzazione cache deve produrre dict rivalidabili, non
    la repr stringa dei modelli Pydantic (altrimenti cache-hit → 500)."""
    import json
    from datetime import datetime

    from backend.app.core.cache import _json_default
    from backend.app.schemas import PairingOut, RoundOut

    rnd = RoundOut(
        id=1, tournament_id=1, number=1, phase="swiss", is_published=True,
        starts_at=datetime(2026, 7, 1, 10, 0), ends_at=datetime(2026, 7, 1, 10, 50),
        pairings=[PairingOut(id=1, table_number=1, player_a="Alice",
                             player_a_registration_id=1, player_b="Bob",
                             player_b_registration_id=2, result="")],
    )
    got = json.loads(json.dumps([rnd], default=_json_default))
    assert isinstance(got[0], dict)
    revalidated = [RoundOut.model_validate(x) for x in got]
    assert revalidated[0].pairings[0].player_a == "Alice"


def test_lockout_counts_failures():
    from backend.app.core import lockout

    email = "lock-test@example.com"
    lockout.reset(email)
    assert lockout.is_locked(email) is False
    for _ in range(lockout.MAX_ATTEMPTS):
        lockout.record_failed(email)
    assert lockout.is_locked(email) is True
    lockout.reset(email)
    assert lockout.is_locked(email) is False
