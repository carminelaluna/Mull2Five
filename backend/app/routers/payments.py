from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.core.config import get_settings
from backend.app.db import get_db
from backend.app.models import Organization, Payment, PaymentStatus, Registration
from backend.app.schemas import SandboxPaymentOut
from backend.app.services.notifications import notify_payment_confirmed
from backend.app.services.payments import capture_paypal_order, paypal_webhook_is_authentic

router = APIRouter(prefix="/payments", tags=["payments"])


def _on_payment_paid(db: Session, payment: Payment) -> None:
    """Un pagamento è appena diventato PAID: la ricevuta al giocatore e via il
    timer che lo rimetterebbe in lista d'attesa."""
    reg = db.scalar(
        select(Registration)
        .where(Registration.id == payment.registration_id)
        .options(joinedload(Registration.player), joinedload(Registration.tournament))
    )
    if not reg:
        return
    reg.promoted_at = None
    db.add(reg)
    db.commit()
    notify_payment_confirmed(reg, payment.amount_cents / 100)


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


def _paypal_payment(db: Session, order_id: str) -> Payment | None:
    if not order_id:
        return None
    return db.scalar(
        select(Payment).where(Payment.provider_checkout_id == order_id, Payment.provider == "paypal")
    )


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    """Le notifiche di PayPal, verificate prima di dar loro retta.

    Due cose mancavano, e insieme facevano entrare i giocatori senza pagare. La
    firma non si controllava, e l'endpoint è pubblico: bastava conoscerne
    l'indirizzo per dichiarare pagata l'iscrizione di chiunque. E
    `CHECKOUT.ORDER.APPROVED` veniva scambiato per un incasso, mentre dice solo
    che il compratore ha dato l'ok: l'ordine nasce con `intent: CAPTURE`, i
    soldi si muovono quando qualcuno li prende — e nessuno li prendeva.
    """
    settings = get_settings()
    if not settings.paypal_webhook_id:
        raise HTTPException(status_code=503, detail="La notifica PayPal non è configurata")
    event = await request.json()
    if not await paypal_webhook_is_authentic(request.headers, event):
        raise HTTPException(status_code=400, detail="Notifica PayPal non valida")

    tipo = event.get("event_type", "")
    resource = event.get("resource", {})

    if tipo == "CHECKOUT.ORDER.APPROVED":
        # Approvato, non incassato: qui si prendono i soldi. Nessun "pagato"
        # ancora — lo dirà la notifica dell'incasso.
        ordine = resource.get("id", "")
        pagamento = _paypal_payment(db, ordine)
        if pagamento and pagamento.status != PaymentStatus.PAID:
            await capture_paypal_order(ordine)
        return {"status": "ok"}

    if tipo == "PAYMENT.CAPTURE.COMPLETED":
        ordine = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id", "")
        pagamento = _paypal_payment(db, ordine)
        # La stessa notifica può arrivare due volte: senza questo controllo il
        # giocatore riceverebbe due ricevute.
        if pagamento and pagamento.status != PaymentStatus.PAID:
            pagamento.status = PaymentStatus.PAID
            # L'identificativo dell'incasso, non quello dell'ordine: è questo
            # che serve per rimborsare.
            pagamento.provider_payment_id = resource.get("id", "")
            pagamento.paid_at = datetime.now(UTC)
            db.commit()
            _on_payment_paid(db, pagamento)
    return {"status": "ok"}
