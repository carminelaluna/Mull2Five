"""
fcm.py — Le notifiche del telefono all'istante, con Firebase Cloud Messaging.

L'app Android chiede da sola le notifiche nuove ogni quindici minuti
(notify/Inbox.kt). Con Firebase il server la sveglia subito: le manda un
messaggio senza testo, "c'è qualcosa nella campanella", e l'app scarica le
notifiche nuove come fa il giro dei quindici minuti. A Google non passa niente
di quello che c'è scritto: la frase la compone l'app, nella lingua del telefono.

Si accende con FCM_SERVICE_ACCOUNT, il JSON della chiave dell'account di
servizio del progetto Firebase (docs/android.md). Senza, `wake` non fa niente e
l'app resta col giro dei quindici minuti.

L'invio gira in un thread a parte, uno solo: chi chiama sta servendo una
richiesta, e per ogni telefono Google vuole una chiamata.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models import DeviceToken, User

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
# Il messaggio: niente testo, solo la sveglia. collapse_key fa sì che a un
# telefono spento per ore ne arrivi uno solo, non uno per notifica.
MESSAGE = {"data": {"campanella": "1"}, "android": {"priority": "HIGH", "collapse_key": "campanella", "ttl": "86400s"}}
# Le risposte di Google che vogliono dire "questo token non serve più".
_GONE_CODES = {"UNREGISTERED", "SENDER_ID_MISMATCH"}


@dataclass(frozen=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str
    private_key_id: str
    token_uri: str


@lru_cache(maxsize=2)
def _parse(raw: str) -> ServiceAccount | None:
    try:
        data = json.loads(raw)
        return ServiceAccount(
            project_id=data["project_id"],
            client_email=data["client_email"],
            private_key=data["private_key"],
            private_key_id=data.get("private_key_id", ""),
            token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        )
    except (ValueError, KeyError, TypeError):
        logger.error("FCM_SERVICE_ACCOUNT non è il JSON di una chiave di servizio: "
                     "le notifiche dell'app restano ogni 15 minuti")
        return None


def service_account() -> ServiceAccount | None:
    raw = (get_settings().fcm_service_account or "").strip()
    return _parse(raw) if raw else None


def enabled() -> bool:
    return service_account() is not None


class Sender:
    """Parla con Google: il token d'accesso (un'ora) lo tiene finché vale."""

    def __init__(self, account: ServiceAccount, client: httpx.Client | None = None):
        self.account = account
        self.client = client or httpx.Client(timeout=10)
        self._access: str | None = None
        self._expires = 0.0

    def access_token(self, renew: bool = False) -> str:
        if renew or not self._access or time.time() > self._expires - 60:
            now = int(time.time())
            account = self.account
            assertion = jwt.encode(
                {"iss": account.client_email, "scope": SCOPE, "aud": account.token_uri,
                 "iat": now, "exp": now + 3600},
                account.private_key,
                algorithm="RS256",
                headers={"kid": account.private_key_id} if account.private_key_id else None,
            )
            response = self.client.post(account.token_uri, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
            })
            response.raise_for_status()
            body = response.json()
            self._access = body["access_token"]
            self._expires = time.time() + int(body.get("expires_in", 3600))
        return self._access

    def send(self, device_token: str) -> str:
        """Sveglia un telefono: 'sent', 'gone' (il token va tolto) o 'error'."""
        url = SEND_URL.format(project=self.account.project_id)
        payload = {"message": {"token": device_token, **MESSAGE}}
        for renew in (False, True):   # un 401 vuol dire token d'accesso scaduto: uno nuovo e si riprova
            response = self.client.post(url, json=payload,
                                        headers={"Authorization": f"Bearer {self.access_token(renew)}"})
            if response.status_code != 401:
                break
        if response.is_success:
            return "sent"
        if response.status_code == 404 or _error_codes(response) & _GONE_CODES:
            return "gone"
        logger.warning("FCM: risposta %s, %s", response.status_code, response.text[:300])
        return "error"


def _error_codes(response: httpx.Response) -> set[str]:
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return set()
    return {d.get("errorCode", "") for d in details if isinstance(d, dict)}


def deliver(db: Session, user_ids: Iterable[int], sender: Sender) -> int:
    """Sveglia i telefoni di `user_ids` e dei genitori che ne gestiscono il
    profilo: la campanella del genitore mostra anche le loro. Toglie i token che
    Google non riconosce più e quelli di sessioni chiuse. Ritorna quanti ne ha
    svegliati."""
    ids = set(user_ids)
    if not ids:
        return 0
    ids |= set(db.scalars(select(User.guardian_id).where(User.id.in_(ids), User.guardian_id.is_not(None))))
    current = DeviceToken.token_version == func.coalesce(User.token_version, 0)
    rows = db.execute(
        select(DeviceToken.id, DeviceToken.token, current.label("current"))
        .join(User, User.id == DeviceToken.user_id)
        .where(DeviceToken.user_id.in_(ids), User.is_active.is_(True))
    ).all()
    stale = [row.id for row in rows if not row.current]
    sent = 0
    for row in rows:
        if not row.current:
            continue
        result = sender.send(row.token)
        if result == "sent":
            sent += 1
        elif result == "gone":
            stale.append(row.id)
    if stale:
        db.execute(delete(DeviceToken).where(DeviceToken.id.in_(stale)))
        db.commit()
    return sent


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fcm")
_sender: Sender | None = None


def _sender_for(account: ServiceAccount) -> Sender:
    global _sender
    if _sender is None or _sender.account != account:
        _sender = Sender(account)
    return _sender


def _deliver_now(user_ids: list[int]) -> None:
    from backend.app.db import SessionLocal

    account = service_account()
    if account is None:
        return
    try:
        with SessionLocal() as db:
            deliver(db, user_ids, _sender_for(account))
    except Exception:  # noqa: BLE001 — il giro dei quindici minuti recupera
        logger.exception("FCM: invio non riuscito a %d persone", len(user_ids))


def wake(user_ids: Iterable[int]) -> None:
    """Chi ha una notifica nuova: i suoi telefoni si sveglieranno. Non aspetta."""
    ids = sorted(set(user_ids))
    if ids and enabled():
        _executor.submit(_deliver_now, ids)
