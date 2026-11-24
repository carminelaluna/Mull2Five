"""
test_terms_promises.py — Quello che i termini d'uso promettono, il sito lo fa.

I termini aggiornati il 24/11/2026 promettono quattro cose che il codice non
faceva:

1. chi annulla più di 24 ore prima e aveva pagato online riceve il rimborso:
   il pagamento veniva segnato "rimborsato", ma Stripe e PayPal non venivano
   chiamati e i soldi restavano dov'erano;
2. le 6 ore per pagare dopo la promozione dalla lista d'attesa valgono solo per
   chi deve pagare online: anche nei tornei al banco o gratuiti il promosso
   tornava in coda ogni 6 ore, veniva ripromosso subito (era sempre il primo) e
   riceveva di nuovo l'email "completa il pagamento";
3. l'early bird vale fino alla data indicata: qui il codice era già giusto
   (conta il giorno in cui si paga, regola confermata il 24/11/2026), e il
   test fissa la regola;
4. i dati dei pagamenti restano per il tempo richiesto dalla legge fiscale:
   eliminare un torneo cancellava anche i pagamenti incassati.
"""
from datetime import UTC, datetime, timedelta

import pytest
import stripe
from sqlalchemy import select

from backend.app.core.clock import local_today
from backend.app.core.config import get_settings
from backend.app.models import Payment, PaymentStatus, Registration, Tournament, TournamentStatus
from backend.app.routers.tournaments import sweep_waitlist_deadlines
from backend.app.services import payments as payments_service
from backend.app.services import registrations as registrations_service


def _utente(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _torneo(client, org, **extra):
    corpo = {
        "name": "Modern del giovedì", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=10)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    corpo.update(extra)
    creato = client.post("/api/tournaments", headers=org, json=corpo)
    assert creato.status_code == 201, creato.text
    return creato.json()["id"]


def _iscrivi(client, tid, player, **corpo):
    risposta = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json=corpo)
    assert risposta.status_code == 201, risposta.text
    return risposta.json()


def _registrazione(db_session, tid, email) -> Registration:
    db_session.expire_all()
    return next(r for r in db_session.scalars(select(Registration).where(Registration.tournament_id == tid))
                if r.player.email == email)


def _pagato_online(db_session, registration_id, provider, provider_payment_id, payee=""):
    """Un pagamento online andato a buon fine, come lo lascia la notifica del fornitore."""
    db_session.add(Payment(
        registration_id=registration_id, provider=provider, status=PaymentStatus.PAID,
        amount_cents=1500, currency="EUR", provider_payment_id=provider_payment_id,
        payee=payee, paid_at=datetime.now(UTC),
    ))
    db_session.commit()


def _annulla(client, tid, player):
    risposta = client.post(f"/api/tournaments/{tid}/my-registration/cancel", headers=player)
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _stato_pagamento(db_session, registration_id):
    db_session.expire_all()
    return db_session.scalar(select(Payment.status).where(Payment.registration_id == registration_id))


# ── 1. Il rimborso dell'annullamento parte davvero ─────────────────────────

@pytest.fixture
def stripe_rimborsi(monkeypatch):
    """Stripe con le chiavi: ogni rimborso chiesto finisce qui."""
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_platform")
    chiesti: list[dict] = []

    def crea(**kwargs):
        if chiesti and chiesti[0] == "rifiuta":
            raise stripe.InvalidRequestError("Charge already refunded", None)
        chiesti.append(kwargs)
        return {"id": "re_test_1", "status": "succeeded"}

    monkeypatch.setattr(stripe.Refund, "create", crea)
    return chiesti


def test_cancelling_a_stripe_payment_in_time_refunds_it_at_stripe(client, db_session, stripe_rimborsi):
    org = _utente(client, "rimb-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_stripe=True)
    player = _utente(client, "rimb-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    _pagato_online(db_session, rid, "stripe", "pi_test_1")

    annullata = _annulla(client, tid, player)

    assert stripe_rimborsi == [{"payment_intent": "pi_test_1"}], "Stripe non è stato chiamato: i soldi non tornano"
    assert annullata["refunded"] is True
    assert _stato_pagamento(db_session, rid) == PaymentStatus.REFUNDED


def test_a_store_stripe_payment_takes_back_the_transfer_too(client, db_session, stripe_rimborsi):
    org = _utente(client, "rimb2-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_stripe=True)
    player = _utente(client, "rimb2-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    _pagato_online(db_session, rid, "stripe", "pi_test_2", payee="stripe:acct_negozio")

    _annulla(client, tid, player)

    assert stripe_rimborsi == [{"payment_intent": "pi_test_2", "reverse_transfer": True,
                                "refund_application_fee": True}]


def test_cancelling_a_paypal_payment_in_time_refunds_the_capture(client, db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_sandbox_mock", False)
    monkeypatch.setattr(settings, "paypal_client_id", "id-di-prova")
    monkeypatch.setattr(settings, "paypal_client_secret", "segreto-di-prova")
    rimborsati: list[str] = []

    async def rimborsa(capture_id):
        rimborsati.append(capture_id)

    monkeypatch.setattr(payments_service, "refund_paypal_capture", rimborsa)
    org = _utente(client, "rimb3-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "rimb3-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    _pagato_online(db_session, rid, "paypal", "CAPTURE-1")

    annullata = _annulla(client, tid, player)

    assert rimborsati == ["CAPTURE-1"], "PayPal non è stato chiamato: i soldi non tornano"
    assert annullata["refunded"] is True
    assert _stato_pagamento(db_session, rid) == PaymentStatus.REFUNDED


def test_when_stripe_refuses_the_refund_it_stays_requested_and_says_so(client, db_session, stripe_rimborsi):
    stripe_rimborsi.append("rifiuta")
    org = _utente(client, "rimb4-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_stripe=True)
    player = _utente(client, "rimb4-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    _pagato_online(db_session, rid, "stripe", "pi_test_3")

    annullata = _annulla(client, tid, player)

    assert _stato_pagamento(db_session, rid) == PaymentStatus.REFUND_REQUESTED
    assert (annullata["refunded"], annullata["refund_requested"]) == (False, True)


def test_a_desk_payment_is_not_refunded_by_itself(client, db_session):
    """Al banco i soldi li ha il negozio: il rimborso lo decide l'organizzatore,
    come dicono i termini. Il sito non può dire "rimborsato"."""
    org = _utente(client, "rimb5-org@example.com", role="organizer")
    tid = _torneo(client, org)
    player = _utente(client, "rimb5-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org).status_code == 200

    annullata = _annulla(client, tid, player)

    assert _stato_pagamento(db_session, rid) == PaymentStatus.REFUND_REQUESTED
    assert (annullata["refunded"], annullata["refund_requested"]) == (False, True)


# ── 2. Le 6 ore valgono solo per chi deve pagare online ────────────────────

@pytest.fixture
def email_inviate(monkeypatch):
    inviate: list[tuple[str, str, str]] = []

    def invia(to, subject, body, **kwargs):
        inviate.append((to, subject, body))
        return True

    monkeypatch.setattr(registrations_service, "send_email", invia)
    return inviate


@pytest.mark.parametrize("quota", [1500, 0], ids=["al banco", "gratuito"])
def test_who_pays_at_the_desk_is_not_put_on_a_clock(client, db_session, email_inviate, quota):
    org = _utente(client, f"coda-org-{quota}@example.com", role="organizer")
    tid = _torneo(client, org, capacity=2, entry_fee_cents=quota)
    primo = _utente(client, f"coda-a-{quota}@example.com")
    _iscrivi(client, tid, primo, payment_method="at_event")
    _iscrivi(client, tid, _utente(client, f"coda-x-{quota}@example.com"), payment_method="at_event")
    secondo = _utente(client, f"coda-b-{quota}@example.com")
    assert _iscrivi(client, tid, secondo)["waitlisted"] is True

    _annulla(client, tid, primo)

    [(destinatario, _, testo)] = email_inviate
    assert destinatario == f"coda-b-{quota}@example.com"
    assert "pagamento" not in testo, "al banco o gratis non c'è niente da pagare entro 6 ore"
    promosso = _registrazione(db_session, tid, f"coda-b-{quota}@example.com")
    assert promosso.waitlisted is False
    # Passano sette ore: resta dentro, e nessuna email nuova.
    if promosso.promoted_at:
        promosso.promoted_at = datetime.now(UTC) - timedelta(hours=7)
        db_session.commit()
    assert sweep_waitlist_deadlines(db_session) == 0
    assert _registrazione(db_session, tid, f"coda-b-{quota}@example.com").waitlisted is False
    assert len(email_inviate) == 1


def _coda_online(client, db_session, prefisso):
    """Un torneo da due posti che si paga solo online, pieno, con due in lista
    d'attesa; il primo della lista è stato promosso sette ore fa e non ha pagato."""
    org = _utente(client, f"{prefisso}-org@example.com", role="organizer")
    tid = _torneo(client, org, capacity=2, pay_at_event=False, pay_stripe=True)
    for lettera in "axbc":
        player = _utente(client, f"{prefisso}-{lettera}@example.com")
        _iscrivi(client, tid, player, payment_method="stripe")
    for lettera in "ax":   # i due dentro hanno pagato; poi il primo si ritira
        _registrazione(db_session, tid, f"{prefisso}-{lettera}@example.com").payment_due_by = None
        db_session.commit()
    _registrazione(db_session, tid, f"{prefisso}-a@example.com").dropped = True
    db_session.commit()
    promosso = _registrazione(db_session, tid, f"{prefisso}-b@example.com")
    promosso.waitlisted = False
    promosso.promoted_at = datetime.now(UTC) - timedelta(hours=7)
    db_session.commit()
    return tid


def test_who_must_pay_online_and_does_not_lets_the_next_one_in(client, db_session, email_inviate):
    tid = _coda_online(client, db_session, "online")

    assert sweep_waitlist_deadlines(db_session) == 1

    assert _registrazione(db_session, tid, "online-b@example.com").waitlisted is True
    assert _registrazione(db_session, tid, "online-c@example.com").waitlisted is False, \
        "il posto passa al successivo, non torna a chi non ha pagato"
    [(destinatario, _, testo)] = email_inviate
    assert destinatario == "online-c@example.com" and "pagamento" in testo


def test_the_clock_stops_once_the_tournament_is_not_open_anymore(client, db_session, email_inviate):
    tid = _coda_online(client, db_session, "chiuso")
    db_session.get(Tournament, tid).status = TournamentStatus.COMPLETED
    db_session.commit()

    assert sweep_waitlist_deadlines(db_session) == 0

    assert _registrazione(db_session, tid, "chiuso-b@example.com").waitlisted is False
    assert email_inviate == []


# ── 3. L'early bird conta il giorno in cui si paga ─────────────────────────
# Regola scelta il 24/11/2026: "vale fino alla data indicata" vuol dire pagando
# entro quella data. Chi si iscrive in tempo e paga al banco dopo, paga la piena.

def test_the_early_bird_counts_the_day_you_pay_not_the_day_you_sign_up(client, db_session, monkeypatch):
    org = _utente(client, "eb-org@example.com", role="organizer")
    tid = _torneo(client, org, entry_fee_cents=2500, early_bird_cents=1500,
                  early_bird_until=str(local_today() + timedelta(days=3)))
    player = _utente(client, "eb-a@example.com")
    rid = _iscrivi(client, tid, player, payment_method="at_event")["id"]
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()["amount_due_cents"] == 1500

    # Cinque giorni dopo l'early bird è finito, anche per chi si era iscritto in
    # tempo: la pagina, il suo conto e il banco dicono la stessa cifra.
    monkeypatch.setattr(payments_service, "local_today", lambda: local_today() + timedelta(days=5))
    assert client.get(f"/api/tournaments/{tid}").json()["entry_fee_now_cents"] == 2500
    assert client.get(f"/api/tournaments/{tid}/my-registration", headers=player).json()["amount_due_cents"] == 2500
    pagata = client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org)
    assert pagata.status_code == 200, pagata.text
    db_session.expire_all()
    assert db_session.scalar(select(Payment.amount_cents).where(Payment.registration_id == rid)) == 2500


# ── 4. Un torneo con pagamenti incassati non perde le ricevute ─────────────

def test_deleting_a_tournament_keeps_the_payments_collected(client, db_session):
    org = _utente(client, "ricevute-org@example.com", role="organizer")
    tid = _torneo(client, org)
    walkin = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "ricevute-a@example.com", "display_name": "Ha pagato", "mark_paid": True,
    })
    assert walkin.status_code == 201, walkin.text

    eliminato = client.delete(f"/api/tournaments/{tid}", headers=org)

    db_session.expire_all()
    incassi = db_session.scalars(select(Payment).where(Payment.registration_id == walkin.json()["id"])).all()
    assert [p.amount_cents for p in incassi] == [1500], "la ricevuta di un incasso non può sparire"
    # Il torneo non si cancella: si annulla, e la risposta dice com'è andata ai soldi.
    assert eliminato.status_code == 200, eliminato.text
    assert eliminato.json() == {"status": "cancelled", "refunded": 0, "refund_requested": 1}
    assert db_session.get(Tournament, tid).status == TournamentStatus.CANCELLED
    assert tid not in [t["id"] for t in client.get("/api/tournaments").json()]


def test_a_tournament_where_no_money_moved_is_still_deleted(client, db_session):
    org = _utente(client, "vuoto-org@example.com", role="organizer")
    tid = _torneo(client, org)
    _iscrivi(client, tid, _utente(client, "vuoto-a@example.com"), payment_method="at_event")

    assert client.delete(f"/api/tournaments/{tid}", headers=org).status_code == 204

    db_session.expire_all()
    assert db_session.get(Tournament, tid) is None


def test_a_cancelled_tournament_shows_only_to_who_was_still_registered(client, db_session):
    """Annullato invece che cancellato: chi era ancora iscritto lo vede tra i
    suoi tornei come annullato; chi aveva già annullato non se lo ritrova."""
    org = _utente(client, "annullato-org@example.com", role="organizer")
    tid = _torneo(client, org)
    rimasto = _utente(client, "annullato-a@example.com")
    rid = _iscrivi(client, tid, rimasto, payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org).status_code == 200
    andato = _utente(client, "annullato-b@example.com")
    rid_b = _iscrivi(client, tid, andato, payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid_b}/mark-paid", headers=org).status_code == 200
    _annulla(client, tid, andato)

    assert client.delete(f"/api/tournaments/{tid}", headers=org).status_code == 200

    def miei(player):
        return [(r["tournament"]["id"], r["tournament"]["status"])
                for r in client.get("/api/tournaments/me/registrations", headers=player).json()]

    assert miei(rimasto) == [(tid, "cancelled")]
    assert miei(andato) == []


# ── 4b. Chi ha pagato un torneo annullato viene avvisato, e il rimborso parte ─
# Regola scelta il 24/11/2026: come quando annulla il giocatore. Online sul conto
# della piattaforma il rimborso parte subito; al banco, sul PayPal del negozio,
# se il fornitore rifiuta o a torneo iniziato resta da decidere all'organizzatore.
# L'email parte sempre, anche con le email del torneo spente.

@pytest.fixture
def avvisi(monkeypatch):
    """Le email della cancellazione: a chi, cosa e da quale casella."""
    from backend.app.services import notifications

    inviate: list[tuple[str, str, str, object]] = []

    def invia(to, subject, body, html_body=None, sender=None):
        inviate.append((to, subject, body, sender))
        return True

    monkeypatch.setattr(notifications, "send_email", invia)
    return inviate


def _per(avvisi, email):
    trovate = [(soggetto, testo, casella) for a, soggetto, testo, casella in avvisi if a == email]
    assert len(trovate) == 1, f"{email}: {avvisi}"
    return trovate[0]


def test_a_cancelled_tournament_refunds_online_and_tells_everyone(client, db_session, stripe_rimborsi, avvisi):
    org = _utente(client, "annulla-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_stripe=True, capacity=3)   # email del torneo spente: è il default
    online = _utente(client, "annulla-online@example.com")
    rid_online = _iscrivi(client, tid, online, payment_method="at_event")["id"]
    _pagato_online(db_session, rid_online, "stripe", "pi_annullato")
    banco = _utente(client, "annulla-banco@example.com")
    rid_banco = _iscrivi(client, tid, banco, payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid_banco}/mark-paid", headers=org).status_code == 200
    _iscrivi(client, tid, _utente(client, "annulla-dapagare@example.com"), payment_method="at_event")
    assert _iscrivi(client, tid, _utente(client, "annulla-attesa@example.com"))["waitlisted"] is True

    eliminato = client.delete(f"/api/tournaments/{tid}", headers=org)

    assert stripe_rimborsi == [{"payment_intent": "pi_annullato"}], "Stripe non è stato chiamato"
    assert _stato_pagamento(db_session, rid_online) == PaymentStatus.REFUNDED
    assert _stato_pagamento(db_session, rid_banco) == PaymentStatus.REFUND_REQUESTED
    assert eliminato.json() == {"status": "cancelled", "refunded": 1, "refund_requested": 1}
    soggetto, testo, casella = _per(avvisi, "annulla-online@example.com")
    assert "annullato" in soggetto and "rimborso è partito" in testo and casella == "payments"
    assert "richiesta di rimborso" in _per(avvisi, "annulla-banco@example.com")[1]
    for chi in ("annulla-dapagare@example.com", "annulla-attesa@example.com"):
        assert "rimborso" not in _per(avvisi, chi)[1]
    assert len(avvisi) == 4


def test_after_the_start_no_refund_leaves_by_itself(client, db_session, stripe_rimborsi, avvisi):
    org = _utente(client, "iniziato-org@example.com", role="organizer")
    tid = _torneo(client, org, pay_stripe=True)
    rid_a = _iscrivi(client, tid, _utente(client, "iniziato-a@example.com"), payment_method="at_event")["id"]
    _pagato_online(db_session, rid_a, "stripe", "pi_iniziato")
    rid_b = _iscrivi(client, tid, _utente(client, "iniziato-b@example.com"), payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid_b}/mark-paid", headers=org).status_code == 200
    assert client.post(f"/api/tournaments/{tid}/start", headers=org).status_code == 200

    eliminato = client.delete(f"/api/tournaments/{tid}", headers=org)

    assert stripe_rimborsi == []
    assert _stato_pagamento(db_session, rid_a) == PaymentStatus.REFUND_REQUESTED
    assert len(avvisi) == 2
    assert eliminato.json() == {"status": "cancelled", "refunded": 0, "refund_requested": 2}


def test_who_had_left_but_paid_is_refunded_and_told_too(client, db_session, stripe_rimborsi, avvisi):
    """Annullata a meno di 24 ore dall'inizio, la quota restava al negozio; ma se
    il torneo non si gioca, torna anche a lui. Chi era andato via senza pagare no."""
    org = _utente(client, "andato-org@example.com", role="organizer")
    tid = _torneo(client, org)
    pagato = _utente(client, "andato-pagato@example.com")
    rid = _iscrivi(client, tid, pagato, payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org).status_code == 200
    _registrazione(db_session, tid, "andato-pagato@example.com").dropped = True   # ritirato senza rimborso
    db_session.commit()

    client.delete(f"/api/tournaments/{tid}", headers=org)

    assert _stato_pagamento(db_session, rid) == PaymentStatus.REFUND_REQUESTED
    assert "richiesta di rimborso" in _per(avvisi, "andato-pagato@example.com")[1]


def test_deleting_a_cancelled_tournament_again_sends_nothing(client, db_session, avvisi):
    org = _utente(client, "due-volte-org@example.com", role="organizer")
    tid = _torneo(client, org)
    rid = _iscrivi(client, tid, _utente(client, "due-volte-a@example.com"), payment_method="at_event")["id"]
    assert client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org).status_code == 200
    client.delete(f"/api/tournaments/{tid}", headers=org)
    avvisi.clear()

    di_nuovo = client.delete(f"/api/tournaments/{tid}", headers=org)

    assert avvisi == []
    assert di_nuovo.json() == {"status": "cancelled", "refunded": 0, "refund_requested": 0}
