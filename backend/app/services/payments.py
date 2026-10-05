import base64
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
import stripe
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.models import Organization, Registration


@dataclass(frozen=True)
class CheckoutSession:
    provider_checkout_id: str
    checkout_url: str
    payee: str = ""      # "stripe:acct_…" / "paypal:email" se l'incasso va al negozio


def platform_fee(amount_cents: int) -> int:
    return round(amount_cents * get_settings().platform_fee_percent / 100)


def store_stripe_account(store: Organization | None) -> str:
    """L'account Stripe del negozio, se è collegato e può già incassare."""
    return store.stripe_account_id if store and store.stripe_account_id and store.stripe_charges_enabled else ""


async def create_stripe_checkout(registration: Registration, store: Organization | None = None) -> CheckoutSession:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe non è configurato")

    tournament = registration.tournament
    frontend_url = str(settings.frontend_url).rstrip("/")
    stripe.api_key = settings.stripe_secret_key
    extra: dict = {}
    payee = ""
    account = store_stripe_account(store)
    if account:
        # Destination charge: l'incasso va al negozio; la piattaforma tiene la sua quota, se c'è.
        intent: dict = {"transfer_data": {"destination": account}}
        fee = platform_fee(tournament.entry_fee_cents)
        if fee:
            intent["application_fee_amount"] = fee
        extra["payment_intent_data"] = intent
        payee = f"stripe:{account}"
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{frontend_url}/grazie.html?t={tournament.id}&pagamento=ok",
        cancel_url=f"{frontend_url}/my-registrations.html?pagamento=annullato",
        line_items=[
            {
                "price_data": {
                    "currency": tournament.currency.lower(),
                    "product_data": {"name": tournament.name},
                    "unit_amount": tournament.entry_fee_cents,
                },
                "quantity": 1,
            }
        ],
        metadata={"registration_id": registration.id, "tournament_id": tournament.id},
        **extra,
    )
    return CheckoutSession(provider_checkout_id=session.id, checkout_url=session.url, payee=payee)


def paypal_order_body(registration: Registration, store: Organization | None) -> dict:
    """L'ordine PayPal: se il negozio ha la sua email PayPal, l'incasso va lì (payee)."""
    settings = get_settings()
    tournament = registration.tournament
    frontend_url = str(settings.frontend_url).rstrip("/")
    unit: dict = {
        "reference_id": str(registration.id),
        "amount": {"currency_code": tournament.currency, "value": f"{tournament.entry_fee_cents / 100:.2f}"},
        "description": tournament.name,
    }
    if store and store.paypal_email:
        unit["payee"] = {"email_address": store.paypal_email}
    return {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        "application_context": {
            "return_url": f"{frontend_url}/grazie.html?t={tournament.id}&pagamento=ok",
            "cancel_url": f"{frontend_url}/my-registrations.html?pagamento=annullato",
        },
    }


def paypal_base_url() -> str:
    """Sandbox o produzione, secondo `PAYPAL_ENV`."""
    return ("https://api-m.sandbox.paypal.com"
            if get_settings().paypal_env == "sandbox"
            else "https://api-m.paypal.com")


async def paypal_access_token(client: httpx.AsyncClient) -> str:
    """Un token da spendere subito, con le credenziali dell'applicazione."""
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal non è configurato")
    credenziali = f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
    risposta = await client.post(
        f"{paypal_base_url()}/v1/oauth2/token",
        headers={"Authorization": f"Basic {base64.b64encode(credenziali).decode()}"},
        data={"grant_type": "client_credentials"},
    )
    risposta.raise_for_status()
    return risposta.json()["access_token"]


async def paypal_webhook_is_authentic(headers: Mapping[str, str], event: dict) -> bool:
    """Chiede a PayPal se quella notifica l'ha mandata davvero lui.

    L'endpoint delle notifiche è pubblico: senza questa domanda, chiunque ne
    conosca l'indirizzo può dichiarare pagata l'iscrizione di chiunque. La firma
    si verifica contro l'identificativo del webhook, che sta nel cruscotto di
    PayPal e che il server non pubblica mai.
    """
    settings = get_settings()
    if not settings.paypal_webhook_id:
        return False
    intestazioni = {
        "auth_algo": headers.get("paypal-auth-algo", ""),
        "cert_url": headers.get("paypal-cert-url", ""),
        "transmission_id": headers.get("paypal-transmission-id", ""),
        "transmission_sig": headers.get("paypal-transmission-sig", ""),
        "transmission_time": headers.get("paypal-transmission-time", ""),
    }
    if not all(intestazioni.values()):
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        token = await paypal_access_token(client)
        risposta = await client.post(
            f"{paypal_base_url()}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}"},
            json={**intestazioni, "webhook_id": settings.paypal_webhook_id, "webhook_event": event},
        )
    risposta.raise_for_status()
    return risposta.json().get("verification_status") == "SUCCESS"


async def capture_paypal_order(order_id: str) -> str:
    """Incassa un ordine approvato, e restituisce l'identificativo dell'incasso.

    L'ordine nasce con `intent: CAPTURE`: l'approvazione del compratore **non**
    muove i soldi, serve questa chiamata. Finché mancava, un'iscrizione
    risultava pagata e il negozio non vedeva un euro. L'identificativo che torna
    serve anche a rimborsare: quello dell'ordine non basta.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        token = await paypal_access_token(client)
        risposta = await client.post(
            f"{paypal_base_url()}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    risposta.raise_for_status()
    incassi = risposta.json().get("purchase_units", [{}])[0].get("payments", {}).get("captures", [])
    return incassi[0]["id"] if incassi else ""


async def create_paypal_checkout(registration: Registration, store: Organization | None = None) -> CheckoutSession:
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal non è configurato")

    base_url = paypal_base_url()
    async with httpx.AsyncClient(timeout=20) as client:
        access_token = await paypal_access_token(client)

        order_response = await client.post(
            f"{base_url}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {access_token}"},
            json=paypal_order_body(registration, store),
        )
        order_response.raise_for_status()
        order = order_response.json()

    approve_url = next(
        (link["href"] for link in order.get("links", []) if link.get("rel") == "approve"),
        "",
    )
    payee = f"paypal:{store.paypal_email}" if store and store.paypal_email else ""
    return CheckoutSession(provider_checkout_id=order["id"], checkout_url=approve_url, payee=payee)


async def refund_paypal_capture(capture_id: str) -> None:
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal non è configurato")
    if not capture_id:
        raise HTTPException(status_code=409, detail="Manca l'identificativo dell'incasso PayPal")

    base_url = paypal_base_url()
    async with httpx.AsyncClient(timeout=20) as client:
        access_token = await paypal_access_token(client)

        refund_response = await client.post(
            f"{base_url}/v2/payments/captures/{capture_id}/refund",
            headers={"Authorization": f"Bearer {access_token}"},
            json={},
        )
        refund_response.raise_for_status()
