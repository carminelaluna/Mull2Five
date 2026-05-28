import base64
from dataclasses import dataclass

import httpx
import stripe
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.models import Registration


@dataclass(frozen=True)
class CheckoutSession:
    provider_checkout_id: str
    checkout_url: str


async def create_stripe_checkout(registration: Registration) -> CheckoutSession:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    tournament = registration.tournament
    frontend_url = str(settings.frontend_url).rstrip("/")
    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{frontend_url}/?payment=success",
        cancel_url=f"{frontend_url}/?payment=cancelled",
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
    )
    return CheckoutSession(provider_checkout_id=session.id, checkout_url=session.url)


async def create_paypal_checkout(registration: Registration) -> CheckoutSession:
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal is not configured")

    base_url = (
        "https://api-m.sandbox.paypal.com"
        if settings.paypal_env == "sandbox"
        else "https://api-m.paypal.com"
    )
    frontend_url = str(settings.frontend_url).rstrip("/")
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

        tournament = registration.tournament
        order_response = await client.post(
            f"{base_url}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": str(registration.id),
                        "amount": {
                            "currency_code": tournament.currency,
                            "value": f"{tournament.entry_fee_cents / 100:.2f}",
                        },
                        "description": tournament.name,
                    }
                ],
                "application_context": {
                    "return_url": f"{frontend_url}/?payment=success",
                    "cancel_url": f"{frontend_url}/?payment=cancelled",
                },
            },
        )
        order_response.raise_for_status()
        order = order_response.json()

    approve_url = next(
        (link["href"] for link in order.get("links", []) if link.get("rel") == "approve"),
        "",
    )
    return CheckoutSession(provider_checkout_id=order["id"], checkout_url=approve_url)


async def refund_paypal_capture(capture_id: str) -> None:
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise HTTPException(status_code=503, detail="PayPal is not configured")
    if not capture_id:
        raise HTTPException(status_code=409, detail="PayPal capture id is missing")

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
