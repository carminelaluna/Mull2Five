import base64
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import httpx
import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.models import Organization, Payment, Registration

logger = logging.getLogger(__name__)

# Chi sceglie di pagare online ha il posto per questi minuti; se non paga,
# l'iscrizione sparisce. Trenta è il minimo che Stripe accetta per far scadere
# una sessione di pagamento.
PAYMENT_HOLD_MINUTES = 30
# La sessione Stripe scade un minuto dopo (Stripe vuole almeno trenta minuti da
# adesso), e l'iscrizione si toglie solo dopo altri cinque: così nessuno paga
# un posto che nel frattempo è stato tolto.
STRIPE_SESSION_MINUTES = PAYMENT_HOLD_MINUTES + 1
HOLD_GRACE_MINUTES = 5


@dataclass(frozen=True)
class CheckoutSession:
    provider_checkout_id: str
    checkout_url: str
    payee: str = ""      # "stripe:acct_…" / "paypal:email" se l'incasso va al negozio


ONLINE_METHODS = ("pay_stripe", "pay_paypal")


def online_payments_enabled() -> bool:
    return get_settings().online_payments_enabled


def in_person_only(values: dict) -> dict:
    """I metodi di pagamento di un torneo come li vuole il sito.

    Con ONLINE_PAYMENTS_ENABLED spento Stripe e PayPal non si accendono, e chi
    aveva scelto solo quelli paga al banco, l'unico modo che resta. Lo usano
    tutte le strade che salvano un torneo: modulo e modelli, duplica e ripeti,
    import del calendario.
    """
    if online_payments_enabled():
        return values
    removed = [key for key in ONLINE_METHODS if values.get(key)]
    if not removed:
        return values
    cleaned = {**values, **dict.fromkeys(removed, False)}
    if not cleaned.get("pay_at_event"):
        cleaned["pay_at_event"] = True
    return cleaned


def payment_methods(tournament) -> list[str]:
    """Come si può pagare questo torneo adesso, su questo sito.

    Un torneo salvato prima che i pagamenti online si spegnessero può avere
    ancora Stripe o PayPal segnati: con ONLINE_PAYMENTS_ENABLED spento non contano.
    """
    methods = ["at_event"] if tournament.pay_at_event else []
    if online_payments_enabled():
        methods += [name for name, on in (("stripe", tournament.pay_stripe), ("paypal", tournament.pay_paypal)) if on]
    return methods


def entry_fee_now(tournament, today: date | None = None) -> int:
    """Quanto costa iscriversi adesso: la quota early bird finché è aperta, poi
    quella piena.

    Un solo posto dove si decide il prezzo. Il giorno di scadenza è compreso, e
    il giorno è quello del negozio (core/clock), non UTC: alle 00:30 in Italia
    l'early bird di ieri è finito, e per UTC sarebbe ancora aperto.
    """
    if tournament.early_bird_cents is None or tournament.early_bird_until is None:
        return tournament.entry_fee_cents
    oggi = today or local_today()
    return tournament.early_bird_cents if oggi <= tournament.early_bird_until else tournament.entry_fee_cents


def amount_due(registration, tournament=None) -> int:
    """Quanto deve pagare questo iscritto: la quota di adesso, meno il suo codice.

    Il codice resta attaccato all'iscrizione (`discount_code_id`), quindi il
    conto torna uguale anche settimane dopo, anche se intanto quel codice è
    stato esaurito o cancellato: chi si è iscritto con lo sconto lo tiene.
    """
    base = entry_fee_now(tournament or registration.tournament)
    code = getattr(registration, "discount_code", None)
    if code is None:
        return base
    sconto = round(base * code.percent_off / 100) if code.percent_off else code.cents_off
    return max(0, base - sconto)


def platform_fee(amount_cents: int) -> int:
    return round(amount_cents * get_settings().platform_fee_percent / 100)


def store_stripe_account(store: Organization | None) -> str:
    """L'account Stripe del negozio, se è collegato e può già incassare."""
    return store.stripe_account_id if store and store.stripe_account_id and store.stripe_charges_enabled else ""


def cancel_url(tournament_id: int) -> str:
    """Dove torna chi annulla il pagamento: la pagina del torneo, che toglie
    l'iscrizione tenuta per lui e gli dice che non è iscritto."""
    frontend_url = str(get_settings().frontend_url).rstrip("/")
    return f"{frontend_url}/event.html?id={tournament_id}&pagamento=annullato"


async def start_checkout(registration: Registration, provider: str, db: Session) -> Payment:
    """Apre il pagamento online di un'iscrizione e lo salva, senza committare.

    Lo usano l'iscrizione con pagamento online e il pulsante "Paga" delle
    iscrizioni. Se il fornitore rifiuta, chi chiama annulla tutto (rollback).
    """
    tournament = registration.tournament
    payment = registration.payment or Payment(registration_id=registration.id, provider=provider)
    payment.provider = provider
    payment.amount_cents = amount_due(registration, tournament)
    payment.currency = tournament.currency
    db.add(payment)
    db.flush()

    settings = get_settings()
    keys_missing = (not settings.stripe_secret_key) if provider == "stripe" else (
        not settings.paypal_client_id or not settings.paypal_client_secret)
    if settings.payment_sandbox_mock and keys_missing:
        # Il checkout finto dello sviluppo: niente chiavi, niente soldi.
        frontend_url = str(settings.frontend_url).rstrip("/")
        payment.provider_checkout_id = f"sandbox-{provider}-{payment.id}"
        payment.checkout_url = f"{frontend_url}/sandbox-checkout.html?payment_id={payment.id}&provider={provider}"
        return payment

    # L'incasso va al negozio del torneo, se ha collegato i suoi conti.
    store = db.get(Organization, tournament.organization_id) if tournament.organization_id else None
    session = (
        await create_stripe_checkout(registration, store)
        if provider == "stripe"
        else await create_paypal_checkout(registration, store)
    )
    payment.provider_checkout_id = session.provider_checkout_id
    payment.checkout_url = session.checkout_url
    payment.payee = session.payee
    return payment


def close_stripe_checkout(session_id: str) -> bool:
    """Vero se la pagina di pagamento Stripe non può più incassare: chiusa
    adesso, o già scaduta da sola. Falso se è stata pagata o se Stripe non
    risponde: allora l'iscrizione non va tolta.
    """
    stripe.api_key = get_settings().stripe_secret_key
    try:
        stripe.checkout.Session.expire(session_id)
        return True
    except stripe.StripeError:
        try:
            return stripe.checkout.Session.retrieve(session_id).status == "expired"
        except stripe.StripeError:
            return False


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
        fee = platform_fee(amount_due(registration, tournament))
        if fee:
            intent["application_fee_amount"] = fee
        extra["payment_intent_data"] = intent
        payee = f"stripe:{account}"
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{frontend_url}/grazie.html?t={tournament.id}&pagamento=ok",
        cancel_url=cancel_url(tournament.id),
        # Scade poco dopo il posto tenuto: dopo, questa pagina non incassa più.
        expires_at=int(time.time()) + STRIPE_SESSION_MINUTES * 60,
        line_items=[
            {
                "price_data": {
                    "currency": tournament.currency.lower(),
                    "product_data": {"name": tournament.name},
                    "unit_amount": amount_due(registration, tournament),
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
        "amount": {"currency_code": tournament.currency, "value": f"{amount_due(registration, tournament) / 100:.2f}"},
        "description": tournament.name,
    }
    if store and store.paypal_email:
        unit["payee"] = {"email_address": store.paypal_email}
    return {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        "application_context": {
            # Si paga su PayPal ("Paga ora"), non "Continua" verso un riepilogo nostro:
            # al ritorno l'ordine si incassa e basta.
            "user_action": "PAY_NOW",
            "return_url": f"{frontend_url}/grazie.html?t={tournament.id}&pagamento=ok",
            "cancel_url": cancel_url(tournament.id),
        },
    }


def _paypal_refusal(risposta: httpx.Response, cosa: str) -> HTTPException:
    """PayPal ha detto no: il suo motivo nei log e a chi ha premuto il pulsante.

    Prima diventava un 500 muto, e sullo staging (23/11/2026) "PayPal non va"
    non diceva se erano le credenziali, il beneficiario o altro.
    """
    try:
        corpo = risposta.json()
    except ValueError:
        corpo = {}
    dettagli = corpo.get("details") or [{}]
    motivo = dettagli[0].get("issue") or corpo.get("name") or corpo.get("error") or str(risposta.status_code)
    logger.error("PayPal ha rifiutato %s: HTTP %s %s", cosa, risposta.status_code, risposta.text[:500])
    return HTTPException(status_code=502, detail=f"PayPal ha rifiutato {cosa}: {motivo}")


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
    if risposta.is_error:
        raise _paypal_refusal(risposta, "le credenziali")
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
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        risposta = await client.post(f"{paypal_base_url()}/v2/checkout/orders/{order_id}/capture", headers=headers)
        # Lo incassano in due: il ritorno del giocatore e la notifica di PayPal.
        # Chi arriva secondo trova l'ordine già incassato e lo rilegge.
        if risposta.status_code == 422 and "ORDER_ALREADY_CAPTURED" in risposta.text:
            risposta = await client.get(f"{paypal_base_url()}/v2/checkout/orders/{order_id}", headers=headers)
    risposta.raise_for_status()
    incassi = risposta.json().get("purchase_units", [{}])[0].get("payments", {}).get("captures", [])
    # Solo un incasso concluso: uno "PENDING" (verifiche di PayPal) non è ancora denaro.
    return incassi[0]["id"] if incassi and incassi[0].get("status") == "COMPLETED" else ""


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
        if order_response.is_error:
            raise _paypal_refusal(order_response, "l'ordine")
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
