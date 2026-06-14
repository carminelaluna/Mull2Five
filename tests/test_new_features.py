"""
test_new_features.py — Test delle funzionalità richieste dal cliente:
password reset, GDPR, display pubblico, iCal, export CSV, stagioni,
leaderboard, staff, report.
"""
from backend.app.security import create_reset_token


def _register_user(client, email, role="player", name=None):
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "display_name": name or email.split("@")[0],
            "password": "supersecret123",
            "role": role,
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "supersecret123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tournament(client, headers, **overrides):
    payload = {
        "name": "Feature Test Open",
        "format": "Modern",
        "starts_on": "2027-05-01",
        "capacity": 16,
        "entry_fee_cents": 1500,
        "currency": "EUR",
        "status": "published",
        "decklist_required": False,
        "pairings_public": True,
        "standings_public": True,
        "pay_stripe": True,   # i test pagano via checkout sandbox Stripe
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ── Password reset ────────────────────────────────────────────


def test_forgot_password_always_200(client):
    """Non rivela se l'email esiste (user enumeration)."""
    response = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert response.status_code == 200


def test_reset_password_flow(client, db_session):
    _register_user(client, "reset-me@example.com")
    from sqlalchemy import select

    from backend.app.models import User
    user = db_session.scalar(select(User).where(User.email == "reset-me@example.com"))

    token = create_reset_token(user)
    response = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "brandnewpassword1"},
    )
    assert response.status_code == 200

    # Vecchia password rifiutata, nuova accettata
    response = client.post(
        "/api/auth/login",
        json={"email": "reset-me@example.com", "password": "supersecret123"},
    )
    assert response.status_code == 401
    response = client.post(
        "/api/auth/login",
        json={"email": "reset-me@example.com", "password": "brandnewpassword1"},
    )
    assert response.status_code == 200


def test_reset_password_bad_token(client):
    response = client.post(
        "/api/auth/reset-password",
        json={"token": "not-a-token", "new_password": "whatever12345"},
    )
    assert response.status_code == 400


# ── GDPR ──────────────────────────────────────────────────────


def test_gdpr_export_and_delete(client):
    headers = _register_user(client, "gdpr@example.com")

    response = client.get("/api/auth/me/export", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "gdpr@example.com"
    assert "registrations" in data

    response = client.delete("/api/auth/me", headers=headers)
    assert response.status_code == 200

    # Login non più possibile (account anonimizzato e disattivato)
    response = client.post(
        "/api/auth/login",
        json={"email": "gdpr@example.com", "password": "supersecret123"},
    )
    assert response.status_code == 401


# ── Display pubblico, iCal, export ────────────────────────────


def test_public_display_no_auth(client):
    org = _register_user(client, "disp-org@example.com", role="organizer")
    tid = _make_tournament(client, org)

    response = client.get(f"/api/tournaments/{tid}/public-display")   # nessun token
    assert response.status_code == 200
    data = response.json()
    assert data["tournament_name"] == "Feature Test Open"
    assert data["round_number"] is None          # nessun round ancora
    assert isinstance(data["standings"], list)


def test_ical_endpoints(client):
    org = _register_user(client, "ical-org@example.com", role="organizer")
    tid = _make_tournament(client, org, name="iCal Open")

    response = client.get(f"/api/tournaments/{tid}/ical")
    assert response.status_code == 200
    assert "text/calendar" in response.headers["content-type"]
    assert "BEGIN:VCALENDAR" in response.text
    assert "iCal Open" in response.text

    response = client.get("/api/tournaments/calendar/feed.ics")
    assert response.status_code == 200
    assert "iCal Open" in response.text


def test_export_csv_requires_owner(client):
    org = _register_user(client, "csv-org@example.com", role="organizer")
    tid = _make_tournament(client, org)

    response = client.get(f"/api/tournaments/{tid}/export.csv", headers=org)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "## Iscritti" in response.text

    other = _register_user(client, "csv-other@example.com", role="organizer")
    response = client.get(f"/api/tournaments/{tid}/export.csv", headers=other)
    assert response.status_code == 404           # non è il suo torneo


# ── Stagioni e leaderboard ────────────────────────────────────


def test_season_and_leaderboard(client):
    org = _register_user(client, "season-org@example.com", role="organizer")

    response = client.post(
        "/api/seasons",
        json={"name": "Season Test Q1", "points_win": 3, "points_draw": 1},
        headers=org,
    )
    assert response.status_code == 201, response.text
    season_id = response.json()["id"]

    tid = _make_tournament(client, org)
    response = client.post(f"/api/seasons/{season_id}/tournaments/{tid}", headers=org)
    assert response.status_code == 200
    assert response.json()["tournament_count"] == 1

    # Leaderboard pubblica (vuota: nessun risultato)
    response = client.get(f"/api/seasons/{season_id}/leaderboard")
    assert response.status_code == 200

    # Lista stagioni pubblica
    response = client.get("/api/seasons")
    assert response.status_code == 200
    assert any(s["name"] == "Season Test Q1" for s in response.json())


# ── Pagamenti: metodi accettati + checkout ────────────────────


def test_checkout_respects_enabled_providers(client):
    org = _register_user(client, "pay-org@example.com", role="organizer")
    # Torneo che accetta solo Stripe online (no PayPal, no al banco)
    tid = _make_tournament(
        client, org, pay_at_event=False, pay_stripe=True, pay_paypal=False
    )

    player = _register_user(client, "pay-player@example.com")
    reg = client.post(
        f"/api/tournaments/{tid}/registrations",
        json={"wizards_account": "12340000"},
        headers=player,
    )
    assert reg.status_code == 201
    assert reg.json()["payment_status"] == "pending"

    # PayPal non abilitato → 409
    response = client.post(
        f"/api/tournaments/{tid}/checkout", json={"provider": "paypal"}, headers=player
    )
    assert response.status_code == 409

    # Stripe abilitato → checkout sandbox con URL
    response = client.post(
        f"/api/tournaments/{tid}/checkout", json={"provider": "stripe"}, headers=player
    )
    assert response.status_code == 200, response.text
    payment = response.json()
    assert payment["checkout_url"]
    payment_id = payment["id"]

    # Completa il pagamento sandbox → iscrizione pagata
    done = client.post(f"/api/payments/sandbox/{payment_id}/complete")
    assert done.status_code == 200
    assert done.json()["status"] == "paid"

    my = client.get(f"/api/tournaments/{tid}/my-registration", headers=player)
    assert my.json()["payment_status"] == "paid"


def test_tournament_exposes_payment_methods(client):
    org = _register_user(client, "paymethods-org@example.com", role="organizer")
    tid = _make_tournament(
        client, org, pay_at_event=True, pay_stripe=False, pay_paypal=True
    )
    t = client.get(f"/api/tournaments/{tid}").json()
    assert t["pay_at_event"] is True
    assert t["pay_stripe"] is False
    assert t["pay_paypal"] is True


# ── Back-office: mark-paid (contanti) + walk-in ───────────────


def test_mark_registration_paid_cash(client):
    org = _register_user(client, "cash-org@example.com", role="organizer")
    tid = _make_tournament(client, org)
    player = _register_user(client, "cash-player@example.com")
    reg = client.post(f"/api/tournaments/{tid}/registrations",
                      json={"wizards_account": "1"}, headers=player)
    rid = reg.json()["id"]
    assert reg.json()["payment_status"] == "pending"

    r = client.post(f"/api/tournaments/{tid}/registrations/{rid}/mark-paid", headers=org)
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "paid"


def test_walk_in_registration_by_organizer(client):
    org = _register_user(client, "walk-org@example.com", role="organizer")
    tid = _make_tournament(client, org)

    # Iscrive un giocatore nuovo (account creato al volo) e lo segna pagato
    r = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "walkin@example.com", "display_name": "Walk In", "mark_paid": True,
    })
    assert r.status_code == 201, r.text
    assert r.json()["payment_status"] == "paid"
    assert r.json()["player_email"] == "walkin@example.com"

    # Doppione rifiutato
    r = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "walkin@example.com", "display_name": "Walk In",
    })
    assert r.status_code == 409


# ── Timer round/tavolo online ─────────────────────────────────


def _start_tournament_with_round(client, org, **t_overrides):
    """Crea un torneo, iscrive+paga 2 giocatori e genera il round 1."""
    tid = _make_tournament(client, org, capacity=4, **t_overrides)
    for i in range(2):
        h = _register_user(client, f"timer-p{i}-{tid}@example.com")
        client.post(f"/api/tournaments/{tid}/registrations",
                    json={"wizards_account": f"900{i}"}, headers=h)
        co = client.post(f"/api/tournaments/{tid}/checkout",
                         json={"provider": "stripe"}, headers=h)
        client.post(f"/api/payments/sandbox/{co.json()['id']}/complete")
    start = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert start.status_code == 200, start.text
    return tid, start.json()


def test_round_timer_restart_and_extend(client):
    org = _register_user(client, "timer-org@example.com", role="organizer")
    tid, round1 = _start_tournament_with_round(client, org)

    # Restart: imposta una scadenza
    r = client.post(f"/api/tournaments/{tid}/timer/restart", json={"minutes": 50}, headers=org)
    assert r.status_code == 200, r.text
    ends1 = client.get(f"/api/tournaments/{tid}/public-display").json()["round_ends_at"]
    assert ends1 is not None

    # Extend: la scadenza si sposta più avanti
    r = client.post(f"/api/tournaments/{tid}/timer/extend", json={"minutes": 10}, headers=org)
    assert r.status_code == 200, r.text
    ends2 = client.get(f"/api/tournaments/{tid}/public-display").json()["round_ends_at"]
    assert ends2 > ends1


def test_table_timer_extension(client):
    org = _register_user(client, "table-org@example.com", role="organizer")
    tid, round1 = _start_tournament_with_round(client, org)
    client.post(f"/api/tournaments/{tid}/timer/restart", json={"minutes": 50}, headers=org)
    pairing_id = round1["pairings"][0]["id"]

    r = client.patch(f"/api/tournaments/{tid}/pairings/{pairing_id}/extend",
                     json={"minutes": 5}, headers=org)
    assert r.status_code == 200, r.text

    display = client.get(f"/api/tournaments/{tid}/public-display").json()
    table = next(p for p in display["pairings"] if p["table_number"] == round1["pairings"][0]["table_number"])
    assert table["extra_seconds"] == 300
    assert table["ends_at"] > display["round_ends_at"]   # tavolo finisce dopo il round


def test_staff_can_extend_table_timer(client):
    org = _register_user(client, "tstaff-org@example.com", role="organizer")
    tid, round1 = _start_tournament_with_round(client, org)
    judge = _register_user(client, "tstaff-judge@example.com")
    client.post(f"/api/tournaments/{tid}/staff", json={"email": "tstaff-judge@example.com"}, headers=org)

    pairing_id = round1["pairings"][0]["id"]
    r = client.patch(f"/api/tournaments/{tid}/pairings/{pairing_id}/extend",
                     json={"minutes": 3}, headers=judge)
    assert r.status_code == 200, r.text   # lo staff/judge può estendere il tavolo


# ── Staff ─────────────────────────────────────────────────────


def test_staff_can_report_results_but_not_delete(client):
    org = _register_user(client, "staff-org@example.com", role="organizer")
    tid = _make_tournament(client, org, capacity=4)

    # Iscrivi e paga 2 giocatori
    for i in range(2):
        headers = _register_user(client, f"staff-p{i}@example.com")
        reg = client.post(
            f"/api/tournaments/{tid}/registrations",
            json={"wizards_account": f"5555000{i}"},
            headers=headers,
        )
        assert reg.status_code == 201
        checkout = client.post(
            f"/api/tournaments/{tid}/checkout", json={"provider": "stripe"}, headers=headers
        )
        client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")

    # Invita lo staff (deve essere un utente registrato)
    judge_headers = _register_user(client, "judge@example.com")
    response = client.post(
        f"/api/tournaments/{tid}/staff", json={"email": "judge@example.com"}, headers=org
    )
    assert response.status_code == 201, response.text
    staff_id = response.json()["id"]

    # Start del torneo (solo organizzatore)
    response = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert response.status_code == 200
    pairing = response.json()["pairings"][0]

    # Lo staff inserisce il risultato ✓
    response = client.patch(
        f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
        json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0},
        headers=judge_headers,
    )
    assert response.status_code == 200, response.text

    # Lo staff NON può eliminare il torneo ✗ (non è organizer → 403)
    response = client.delete(f"/api/tournaments/{tid}", headers=judge_headers)
    assert response.status_code in (403, 404)

    # Lo staff NON può vedere gli iscritti con i pagamenti ✗
    response = client.get(f"/api/tournaments/{tid}/registrations", headers=judge_headers)
    assert response.status_code in (403, 404)

    # Rimozione staff
    response = client.delete(f"/api/tournaments/{tid}/staff/{staff_id}", headers=org)
    assert response.status_code == 204


# ── Report ────────────────────────────────────────────────────


def test_reports_mine(client):
    org = _register_user(client, "report-org@example.com", role="organizer")
    tid = _make_tournament(client, org, entry_fee_cents=2000)

    headers = _register_user(client, "report-p1@example.com")
    client.post(
        f"/api/tournaments/{tid}/registrations",
        json={"wizards_account": "777"},
        headers=headers,
    )
    checkout = client.post(
        f"/api/tournaments/{tid}/checkout", json={"provider": "stripe"}, headers=headers
    )
    client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")

    response = client.get("/api/tournaments/reports/mine", headers=org)
    assert response.status_code == 200, response.text
    report = next(r for r in response.json() if r["tournament_id"] == tid)
    assert report["registrations"] == 1
    assert report["paid_count"] == 1
    assert report["revenue_cents"] == 2000
