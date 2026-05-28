from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import Payment, PaymentStatus
from backend.app.schemas import SandboxPaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/sandbox/{payment_id}/complete", response_model=SandboxPaymentOut)
def complete_sandbox_payment(payment_id: int, db: Session = Depends(get_db)) -> SandboxPaymentOut:
    settings = get_settings()
    if not settings.payment_sandbox_mock:
        raise HTTPException(status_code=404, detail="Sandbox payments are disabled")
    payment = db.get(Payment, payment_id)
    if not payment or not payment.provider_checkout_id.startswith("sandbox-"):
        raise HTTPException(status_code=404, detail="Sandbox payment not found")
    payment.status = PaymentStatus.PAID
    payment.provider_payment_id = f"{payment.provider_checkout_id}-paid"
    payment.paid_at = datetime.now(UTC)
    db.commit()
    db.refresh(payment)
    return SandboxPaymentOut(id=payment.id, status=payment.status)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        payment = db.scalar(
            select(Payment).where(Payment.provider_checkout_id == session["id"], Payment.provider == "stripe")
        )
        if payment:
            payment.status = PaymentStatus.PAID
            payment.provider_payment_id = session.get("payment_intent") or ""
            payment.paid_at = datetime.now(UTC)
            db.commit()
    return {"status": "ok"}


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    event_type = payload.get("event_type", "")
    resource = payload.get("resource", {})
    if event_type in {"CHECKOUT.ORDER.APPROVED", "PAYMENT.CAPTURE.COMPLETED"}:
        order_id = resource.get("id") or resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        payment = db.scalar(
            select(Payment).where(Payment.provider_checkout_id == order_id, Payment.provider == "paypal")
        )
        if payment:
            payment.status = PaymentStatus.PAID
            payment.provider_payment_id = resource.get("id", "")
            payment.paid_at = datetime.now(UTC)
            db.commit()
    return {"status": "ok"}
