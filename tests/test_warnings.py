"""
test_warnings.py — Avvisi all'organizzatore.

Il sistema accetta queste configurazioni perché possono avere senso, ma quasi
sempre sono sviste: vanno dette a chi organizza, e solo a lui.
"""
from datetime import date, datetime, timedelta

import pytest

from backend.app.core.clock import local_today

TODAY = local_today()


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def org(client):
    return _register_user(client, "warn-org@example.com", role="organizer")


def _tournament(client, org, days=10, **extra):
    body = {
        "name": extra.pop("name", "Serata"), "format": "Modern",
        "starts_on": str(TODAY + timedelta(days=days)), "start_time": "20:00",
        "capacity": 32, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "rules_enforcement_level": "Regular",
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _codes(items):
    return [w["code"] for w in items]


def _warnings(client, org, tid):
    response = client.get(f"/api/tournaments/{tid}/warnings", headers=org)
    assert response.status_code == 200, response.text
    return response.json()


def _event(client, org, start_in=10, length=1, **extra):
    body = {"name": "Weekend di prova", "starts_on": str(TODAY + timedelta(days=start_in)),
            "ends_on": str(TODAY + timedelta(days=start_in + length)), "is_public": True}
    body.update(extra)
    created = client.post("/api/events", headers=org, json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


# ── Tappa fuori periodo ───────────────────────────────────────


def test_a_stage_outside_the_period_is_attached_with_a_warning(client, org):
    eid = _event(client, org, start_in=10, length=1)          # giorni 10 e 11
    dentro = _tournament(client, org, days=11, name="Main event")
    fuori = _tournament(client, org, days=30, name="Side sperduto")

    ok = client.post(f"/api/events/{eid}/tournaments/{dentro}", headers=org)
    assert ok.status_code == 200, ok.text
    assert _codes(ok.json()["warnings"]) == []

    # Non è un blocco: si aggancia, e la risposta dice quale tappa è fuori.
    agganciato = client.post(f"/api/events/{eid}/tournaments/{fuori}", headers=org)
    assert agganciato.status_code == 200, agganciato.text
    avvisi = agganciato.json()["warnings"]
    assert _codes(avvisi) == ["stage_outside_period"]
    assert avvisi[0]["tournament_id"] == fuori
    assert agganciato.json()["tournament_count"] == 2

    # Lo stesso avviso lo vede il torneo, dall'interno.
    assert "outside_event_period" in _codes(_warnings(client, org, fuori))
    assert "outside_event_period" not in _codes(_warnings(client, org, dentro))


def test_an_event_without_end_date_lasts_one_day(client, org):
    eid = _event(client, org, start_in=10, ends_on=None)
    giorno_dopo = _tournament(client, org, days=11)
    response = client.post(f"/api/events/{eid}/tournaments/{giorno_dopo}", headers=org)
    assert _codes(response.json()["warnings"]) == ["stage_outside_period"]


def test_widening_the_period_clears_the_warning(client, org):
    eid = _event(client, org, start_in=10, length=0)
    tid = _tournament(client, org, days=12)
    client.post(f"/api/events/{eid}/tournaments/{tid}", headers=org)

    allargato = client.patch(f"/api/events/{eid}", headers=org,
                             json={"ends_on": str(TODAY + timedelta(days=12))})
    assert allargato.status_code == 200, allargato.text
    assert allargato.json()["warnings"] == []


def test_a_period_ending_before_it_starts_is_refused(client, org):
    rovescio = client.post("/api/events", headers=org, json={
        "name": "Al contrario", "starts_on": str(TODAY + timedelta(days=5)),
        "ends_on": str(TODAY + timedelta(days=3)),
    })
    assert rovescio.status_code == 422

    eid = _event(client, org, start_in=10, length=2)
    # Cambiare solo l'inizio non deve poter scavalcare una fine già salvata.
    oltre = client.patch(f"/api/events/{eid}", headers=org,
                         json={"starts_on": str(TODAY + timedelta(days=20))})
    assert oltre.status_code == 422


def test_the_end_date_can_be_cleared(client, org):
    eid = _event(client, org, start_in=10, length=2)
    svuotata = client.patch(f"/api/events/{eid}", headers=org, json={"ends_on": None})
    assert svuotata.status_code == 200, svuotata.text
    assert svuotata.json()["ends_on"] is None
    # Gli altri campi a null restano "non toccare".
    intatto = client.patch(f"/api/events/{eid}", headers=org, json={"name": None})
    assert intatto.json()["name"] == "Weekend di prova"


def test_a_public_event_without_stages_is_flagged(client, org):
    eid = _event(client, org, is_public=True)
    mine = client.get("/api/events/mine", headers=org).json()
    evento = next(e for e in mine if e["id"] == eid)
    assert [(w["code"], w["level"]) for w in evento["warnings"]] == [("public_without_stages", "info")]


def test_warnings_never_reach_the_public(client, org):
    eid = _event(client, org, start_in=10, length=0)
    tid = _tournament(client, org, days=40)
    client.post(f"/api/events/{eid}/tournaments/{tid}", headers=org)
    slug = client.get("/api/events/mine", headers=org).json()[0]["slug"]

    assert all("warnings" not in e for e in client.get("/api/events/public").json())
    assert "warnings" not in client.get(f"/api/events/by-slug/{slug}").json()["event"]

    player = _register_user(client, "warn-curioso@example.com")
    assert client.get(f"/api/tournaments/{tid}/warnings", headers=player).status_code in (403, 404)


# ── Avvisi del singolo torneo ─────────────────────────────────


def test_a_tournament_that_never_started(client, org):
    tid = _tournament(client, org, days=-3)
    assert "missed_start" in _codes(_warnings(client, org, tid))


def test_online_payment_without_credentials(client, org):
    # Nei test non ci sono chiavi Stripe: il checkout fallirebbe.
    tid = _tournament(client, org, entry_fee_cents=1500, pay_stripe=True, pay_at_event=True)
    avvisi = {w["code"]: w for w in _warnings(client, org, tid)}
    assert "online_payment_unavailable" in avvisi
    assert "solo al banco" in avvisi["online_payment_unavailable"]["message"]

    solo_online = _tournament(client, org, entry_fee_cents=1500, pay_stripe=True, pay_at_event=False)
    messaggio = {w["code"]: w for w in _warnings(client, org, solo_online)}
    assert "Nessuno potrà pagare" in messaggio["online_payment_unavailable"]["message"]

    # Gratis non c'è niente da pagare, quindi niente da avvisare.
    gratis = _tournament(client, org, entry_fee_cents=0, pay_stripe=True)
    assert "online_payment_unavailable" not in _codes(_warnings(client, org, gratis))


def test_decklist_deadline_after_the_start(client, org):
    tid = _tournament(client, org, days=5)
    dopo = datetime.combine(TODAY + timedelta(days=6), datetime.min.time()).isoformat() + "Z"
    assert client.patch(f"/api/tournaments/{tid}/controls", headers=org,
                        json={"decklist_deadline": dopo}).status_code == 200
    assert "decklist_deadline_after_start" in _codes(_warnings(client, org, tid))


def _enroll(client, tid, email, with_list):
    headers = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                      json={"wizards_account": email[:8]})
    assert reg.status_code == 201, reg.text
    if with_list:
        sent = client.post(f"/api/tournaments/{tid}/decklist", headers=headers,
                           json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": "Burn"})
        assert sent.status_code == 200, sent.text


def test_missing_decklists_only_close_to_the_start(client, org):
    vicino = _tournament(client, org, days=1, decklist_required=True, name="Domani")
    lontano = _tournament(client, org, days=10, decklist_required=True, name="Fra dieci giorni")
    for tid in (vicino, lontano):
        _enroll(client, tid, f"warn-a{tid}@example.com", with_list=True)
        _enroll(client, tid, f"warn-b{tid}@example.com", with_list=False)

    avvisi = {w["code"]: w for w in _warnings(client, org, vicino)}
    assert avvisi["missing_decklists"]["message"].startswith("1 iscritti su 2")
    # Dieci giorni prima è normale che manchino: nessun sollecito.
    assert "missing_decklists" not in _codes(_warnings(client, org, lontano))


def test_head_judge_note_goes_away_once_appointed(client, org):
    tid = _tournament(client, org, rules_enforcement_level="Competitive")
    avvisi = _warnings(client, org, tid)
    assert [(w["code"], w["level"]) for w in avvisi] == [("no_head_judge", "info")]

    _register_user(client, "warn-hj@example.com")
    nominato = client.post(f"/api/tournaments/{tid}/staff", headers=org,
                           json={"email": "warn-hj@example.com", "role": "head_judge"})
    assert nominato.status_code == 201, nominato.text
    assert _warnings(client, org, tid) == []


def test_an_event_head_judge_covers_its_stages(client, org):
    eid = _event(client, org, start_in=10, length=0)
    tid = _tournament(client, org, rules_enforcement_level="Competitive")
    client.post(f"/api/events/{eid}/tournaments/{tid}", headers=org)
    _register_user(client, "warn-evhj@example.com")
    client.post(f"/api/events/{eid}/staff", headers=org,
                json={"email": "warn-evhj@example.com", "role": "head_judge"})
    assert "no_head_judge" not in _codes(_warnings(client, org, tid))


def test_regular_rel_needs_no_head_judge(client, org):
    tid = _tournament(client, org, rules_enforcement_level="Regular")
    assert _warnings(client, org, tid) == []


def test_all_my_warnings_in_one_call(client, org):
    pulito = _tournament(client, org, name="Tutto a posto")
    vecchio = _tournament(client, org, days=-2, name="Mai partito")
    concluso = _tournament(client, org, days=-5, name="Chiuso")
    assert client.post(f"/api/tournaments/{concluso}/close", headers=org).status_code == 200

    tutti = client.get("/api/tournaments/warnings/mine", headers=org)
    assert tutti.status_code == 200, tutti.text
    per_torneo = {int(k): _codes(v) for k, v in tutti.json().items()}
    assert "missed_start" in per_torneo[vecchio]
    assert pulito not in per_torneo, "un torneo senza avvisi non deve comparire"
    assert concluso not in per_torneo, "un torneo concluso non ha più niente da correggere"


# ── Email degli annunci ───────────────────────────────────────


def test_the_announcement_form_knows_if_email_will_leave(client, org, monkeypatch):
    from backend.app.core.config import get_settings

    tid = _tournament(client, org)

    def stato():
        return client.get(f"/api/tournaments/{tid}/announcements/audience",
                          headers=org).json()["email_status"]

    assert stato() == "no_smtp"

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    assert stato() == "tournament_off"

    # Prima non c'era un modo di accenderle: ora sta nei controlli del torneo.
    acceso = client.patch(f"/api/tournaments/{tid}/controls", headers=org,
                          json={"email_notifications_enabled": True})
    assert acceso.status_code == 200, acceso.text
    assert stato() == "ok"
