from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import Organization, Payment, PaymentStatus, Registration
from backend.app.schemas import SandboxPaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])


def _on_payment_paid(db: Session, payment: Payment) -> None:
    """Dopo che un pagamento diventa PAID: invia la ricevuta email (#45) e ferma
    il timer di pagamento della waitlist (#32). Non solleva mai."""
    try:
        reg = db.scalar(
            select(Registration)
            .where(Registration.id == payment.registration_id)
            .options(joinedload(Registration.player), joinedload(Registration.tournament))
        )
        if not reg:
            return
        reg.promoted_at = None   # ha pagato: conferma promozione dalla waitlist
        db.add(reg)
        db.commit()
        from backend.app.services.notifications import notify_payment_confirmed
        notify_payment_confirmed(reg, payment.amount_cents / 100)
    except Exception:  # noqa: BLE001
        pass


@router.post("/sandbox/{payment_id}/complete", response_model=SandboxPaymentOut)
def complete_sandbox_payment(payment_id: int, db: Session = Depends(get_db)) -> SandboxPaymentOut:
    settings = get_settings()
    if not settings.payment_sandbox_mock:
        raise HTTPException(status_code=404, detail="I pagamenti di prova sono spenti")
    payment = db.get(Payment, payment_id)
    if not payment or not payment.provider_checkout_id.startswith("sandbox-"):
        raise HTTPException(status_code=404, detail="Pagamento di prova non trovato")
    payment.status = PaymentStatus.PAID
    payment.provider_payment_id = f"{payment.provider_checkout_id}-paid"
    payment.paid_at = datetime.now(UTC)
    db.commit()
    db.refresh(payment)
    _on_payment_paid(db, payment)
    return SandboxPaymentOut(id=payment.id, status=payment.status)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="La notifica Stripe non è configurata")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Notifica Stripe non valida") from exc

    if event["type"] == "account.updated":
        # L'account di un negozio: può incassare o no (verifiche Stripe in sospeso).
        account = event["data"]["object"]
        store = db.scalar(select(Organization).where(Organization.stripe_account_id == account["id"]))
        if store:
            store.stripe_charges_enabled = bool(account.get("charges_enabled"))
            db.commit()

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
            _on_payment_paid(db, payment)
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
            _on_payment_paid(db, payment)
    return {"status": "ok"}
