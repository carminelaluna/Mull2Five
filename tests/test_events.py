"""
test_events.py — Contenitore Event: tappe, ereditarietà dei ruoli, Day 2 e
segmenti a formato diverso.
"""
from datetime import date, timedelta


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tournament(client, headers, name="Tappa", **overrides):
    payload = {
        "name": name, "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=3)),
        "capacity": 8, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "decklist_required": False, "pay_stripe": True, "standings_public": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _make_event(client, headers, name="Weekend di prova"):
    created = client.post("/api/events", headers=headers, json={
        "name": name, "description": "Main event e side event",
        "venue": "Negozio di prova", "starts_on": str(date.today() + timedelta(days=3)),
        "ends_on": str(date.today() + timedelta(days=4)),
    })
    assert created.status_code == 201, created.text
    return created.json()


# ── Anagrafica e tappe ────────────────────────────────────────


def test_event_collects_its_tournaments(client):
    org = _register_user(client, "ev-org@example.com", role="organizer")
    event = _make_event(client, org)
    assert event["slug"] == "weekend-di-prova"
    assert event["tournament_count"] == 0

    main = _make_tournament(client, org, "Main Event")
    side = _make_tournament(client, org, "Side Event")
    for tid in (main, side):
        attached = client.post(f"/api/events/{event['id']}/tournaments/{tid}", headers=org)
        assert attached.status_code == 200, attached.text
    assert attached.json()["tournament_count"] == 2

    public = client.get(f"/api/events/by-slug/{event['slug']}")
    assert public.status_code == 200, public.text
    assert {t["name"] for t in public.json()["tournaments"]} == {"Main Event", "Side Event"}

    # Il torneo sa a quale evento appartiene.
    assert client.get(f"/api/tournaments/{main}").json()["event_slug"] == "weekend-di-prova"

    detached = client.delete(f"/api/events/{event['id']}/tournaments/{side}", headers=org)
    assert detached.status_code == 200
    assert detached.json()["tournament_count"] == 1


def test_only_your_own_tournaments_join_your_event(client):
    """L'evento raccoglie i propri tornei, non se li appropria."""
    org = _register_user(client, "ev-mine@example.com", role="organizer")
    altro = _register_user(client, "ev-other@example.com", role="organizer")
    event = _make_event(client, org)
    estraneo = _make_tournament(client, altro, "Torneo altrui")

    refused = client.post(f"/api/events/{event['id']}/tournaments/{estraneo}", headers=org)
    assert refused.status_code == 404, refused.text


def test_private_event_has_no_public_page(client):
    org = _register_user(client, "ev-priv@example.com", role="organizer")
    event = _make_event(client, org, "Interno")
    client.patch(f"/api/events/{event['id']}", headers=org, json={"is_public": False})

    assert client.get(f"/api/events/by-slug/{event['slug']}").status_code == 404
    assert "interno" not in {e["slug"] for e in client.get("/api/events/public").json()}


def test_event_slugs_do_not_collide(client):
    org = _register_user(client, "ev-slug@example.com", role="organizer")
    assert _make_event(client, org, "Weekend")["slug"] == "weekend"
    assert _make_event(client, org, "Weekend")["slug"] == "weekend-2"


# ── Ereditarietà dei ruoli ────────────────────────────────────


def test_event_head_judge_rules_every_tournament(client):
    """È il punto dell'Event: a un weekend il capojudge si nomina una volta."""
    org = _register_user(client, "ev-staff-org@example.com", role="organizer")
    event = _make_event(client, org)
    main = _make_tournament(client, org, "Main")
    side = _make_tournament(client, org, "Side")
    client.post(f"/api/events/{event['id']}/tournaments/{main}", headers=org)
    client.post(f"/api/events/{event['id']}/tournaments/{side}", headers=org)

    capo = _register_user(client, "ev-capo@example.com")
    nominato = client.post(f"/api/events/{event['id']}/staff", headers=org,
                           json={"email": "ev-capo@example.com", "role": "head_judge"})
    assert nominato.status_code == 201, nominato.text

    # Senza nominarlo su nessuna tappa, è capojudge su entrambe.
    for tid in (main, side):
        assert client.get(f"/api/tournaments/{tid}/my-role", headers=capo).json() == {
            "role": "head_judge", "can_manage_judges": True,
        }

    # E può nominare judge sulla singola tappa.
    _register_user(client, "ev-judge@example.com")
    assert client.post(f"/api/tournaments/{main}/staff", headers=capo,
                       json={"email": "ev-judge@example.com", "role": "judge"}).status_code == 201


def test_a_tournament_role_never_lowers_an_event_role(client):
    """Con due incarichi vince il più alto: nominare judge su una tappa non può
    togliere a un capojudge i poteri che ha sull'evento."""
    org = _register_user(client, "ev-rank-org@example.com", role="organizer")
    event = _make_event(client, org)
    tid = _make_tournament(client, org, "Tappa")
    client.post(f"/api/events/{event['id']}/tournaments/{tid}", headers=org)

    capo = _register_user(client, "ev-rank@example.com")
    client.post(f"/api/events/{event['id']}/staff", headers=org,
                json={"email": "ev-rank@example.com", "role": "head_judge"})
    client.post(f"/api/tournaments/{tid}/staff", headers=org,
                json={"email": "ev-rank@example.com", "role": "judge"})

    assert client.get(f"/api/tournaments/{tid}/my-role", headers=capo).json()["role"] == "head_judge"


def test_one_head_judge_per_event(client):
    org = _register_user(client, "ev-one-org@example.com", role="organizer")
    event = _make_event(client, org)
    for email in ("ev-a@example.com", "ev-b@example.com"):
        _register_user(client, email)
    assert client.post(f"/api/events/{event['id']}/staff", headers=org,
                       json={"email": "ev-a@example.com", "role": "head_judge"}).status_code == 201
    assert client.post(f"/api/events/{event['id']}/staff", headers=org,
                       json={"email": "ev-b@example.com", "role": "head_judge"}).status_code == 409


def test_event_staff_is_not_public(client):
    org = _register_user(client, "ev-closed-org@example.com", role="organizer")
    event = _make_event(client, org)
    estraneo = _register_user(client, "ev-nosy@example.com", role="organizer")

    assert client.get(f"/api/events/{event['id']}/staff", headers=estraneo).status_code == 404
    assert client.post(f"/api/events/{event['id']}/staff", headers=estraneo,
                       json={"email": "ev-closed-org@example.com"}).status_code == 404


# ── Day 2 ─────────────────────────────────────────────────────


def _enroll(client, tid, email, archetype):
    headers = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                      json={"wizards_account": email[:8]})
    assert reg.status_code == 201, reg.text
    checkout = client.post(f"/api/tournaments/{tid}/checkout", headers=headers,
                           json={"provider": "stripe"})
    client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")
    client.post(f"/api/tournaments/{tid}/decklist", headers=headers,
                json={"raw_text": "4 Lightning Bolt\n56 Mountain", "archetype": archetype})
    return reg.json()["id"]


def test_day2_flags_and_conversion(client):
    org = _register_user(client, "ev-d2-org@example.com", role="organizer")
    tid = _make_tournament(client, org, "Big Event", decklist_required=True)
    burn = [_enroll(client, tid, f"ev-burn{i}@example.com", "Burn") for i in range(2)]
    murk = [_enroll(client, tid, f"ev-murk{i}@example.com", "Murktide") for i in range(2)]

    # Passano entrambi i Murktide e un solo Burn.
    rows = client.post(f"/api/tournaments/{tid}/day2", headers=org,
                       json={"registration_ids": murk + burn[:1]})
    assert rows.status_code == 200, rows.text
    per_arch = {r["archetype"]: r for r in rows.json()}
    assert per_arch["Murktide"]["day2"] == 2 and per_arch["Murktide"]["conversion"] == 100.0
    assert per_arch["Burn"]["day2"] == 1 and per_arch["Burn"]["conversion"] == 50.0

    # La lista sostituisce: rimandarne una più corta corregge l'import.
    corretta = client.post(f"/api/tournaments/{tid}/day2", headers=org,
                           json={"registration_ids": murk})
    per_arch = {r["archetype"]: r for r in corretta.json()}
    assert per_arch["Burn"]["day2"] == 0


def test_day2_refuses_registrations_of_another_tournament(client):
    org = _register_user(client, "ev-d2-bad@example.com", role="organizer")
    tid = _make_tournament(client, org, "Uno")
    altro = _make_tournament(client, org, "Due")
    estraneo = _enroll(client, altro, "ev-stray@example.com", "Burn")

    refused = client.post(f"/api/tournaments/{tid}/day2", headers=org,
                          json={"registration_ids": [estraneo]})
    assert refused.status_code == 422, refused.text


# ── Segmenti a formato diverso ────────────────────────────────


def test_round_can_carry_its_own_format(client):
    org = _register_user(client, "ev-fmt-org@example.com", role="organizer")
    tid = _make_tournament(client, org, "Misto", format="Modern")
    for i in range(2):
        _enroll(client, tid, f"ev-fmt-p{i}@example.com", "Burn")
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text
    rid = started.json()["id"]

    assert started.json()["format"] is None   # nullo = il formato del torneo

    segmented = client.patch(f"/api/tournaments/{tid}/rounds/{rid}/format", headers=org,
                             json={"format": "Booster Draft"})
    assert segmented.status_code == 200, segmented.text
    assert segmented.json()["format"] == "Booster Draft"

    cleared = client.patch(f"/api/tournaments/{tid}/rounds/{rid}/format", headers=org,
                           json={"format": ""})
    assert cleared.json()["format"] is None
