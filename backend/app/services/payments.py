import base64
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


async def create_paypal_checkout(registration: Registration, store: Organization | None = None) -> CheckoutSession:
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal non è configurato")

    base_url = (
        "https://api-m.sandbox.paypal.com"
        if settings.paypal_env == "sandbox"
        else "https://api-m.paypal.com"
    )
    credentials = f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
    auth_header = base64.b64encode(credentials).decode()

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            f"{base_url}/v1/oauth2/token",
            headers={"Authorization": f"Basic {auth_header}"},
            data={"grant_type": "client_credentials"},
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

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

    base_url = (
        "https://api-m.sandbox.paypal.com"
        if settings.paypal_env == "sandbox"
        else "https://api-m.paypal.com"
    )
    credentials = f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
    auth_header = base64.b64encode(credentials).decode()

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            f"{base_url}/v1/oauth2/token",
            headers={"Authorization": f"Basic {auth_header}"},
            data={"grant_type": "client_credentials"},
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        refund_response = await client.post(
            f"{base_url}/v2/payments/captures/{capture_id}/refund",
            headers={"Authorization": f"Bearer {access_token}"},
            json={},
        )
        refund_response.raise_for_status()
