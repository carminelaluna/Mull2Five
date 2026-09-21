"""
test_judge_hierarchy.py — Catena di comando su un torneo.

Organizzatore → capojudge → judge. L'incarico è per-torneo, non per-account:
lo stesso utente può essere capojudge qui, judge là e giocatore altrove.
"""


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
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tournament(client, headers, **overrides):
    payload = {
        "name": "Judge Hierarchy Open",
        "format": "Modern",
        "starts_on": "2027-06-01",
        "capacity": 8,
        "entry_fee_cents": 1500,
        "currency": "EUR",
        "status": "published",
        "decklist_required": False,
        "pay_stripe": True,
    }
    payload.update(overrides)
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _enroll(client, tid, email):
    """Iscrive e paga un giocatore: solo gli iscritti paganti finiscono nei pairing."""
    headers = _register_user(client, email)
    reg = client.post(
        f"/api/tournaments/{tid}/registrations", json={"wizards_account": email[:8]}, headers=headers
    )
    assert reg.status_code == 201, reg.text
    checkout = client.post(
        f"/api/tournaments/{tid}/checkout", json={"provider": "stripe"}, headers=headers
    )
    assert checkout.status_code == 200, checkout.text
    client.post(f"/api/payments/sandbox/{checkout.json()['id']}/complete")
    return headers, reg.json()["id"]


def _appoint(client, tid, headers, email, role="judge"):
    return client.post(f"/api/tournaments/{tid}/staff", json={"email": email, "role": role}, headers=headers)


def _staffed_tournament(client, **overrides):
    """Torneo con organizzatore, capojudge e judge già nominati."""
    org = _register_user(client, "hier-org@example.com", role="organizer")
    tid = _make_tournament(client, org, **overrides)
    head = _register_user(client, "hier-head@example.com")
    judge = _register_user(client, "hier-judge@example.com")
    assert _appoint(client, tid, org, "hier-head@example.com", "head_judge").status_code == 201
    assert _appoint(client, tid, head, "hier-judge@example.com").status_code == 201
    return tid, org, head, judge


# ── Nomine ────────────────────────────────────────────────────


def test_organizer_appoints_head_judge(client):
    org = _register_user(client, "app-org@example.com", role="organizer")
    tid = _make_tournament(client, org)
    _register_user(client, "app-head@example.com")

    response = _appoint(client, tid, org, "app-head@example.com", "head_judge")
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "head_judge"


def test_staff_defaults_to_judge(client):
    """Le chiamate senza `role` restano judge: nessuno diventa capojudge per sbaglio."""
    org = _register_user(client, "def-org@example.com", role="organizer")
    tid = _make_tournament(client, org)
    _register_user(client, "def-judge@example.com")

    response = client.post(
        f"/api/tournaments/{tid}/staff", json={"email": "def-judge@example.com"}, headers=org
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "judge"


def test_head_judge_appoints_judges(client):
    tid, _, head, _ = _staffed_tournament(client)
    _register_user(client, "hier-judge2@example.com")

    response = _appoint(client, tid, head, "hier-judge2@example.com")
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "judge"


def test_head_judge_cannot_appoint_a_peer(client):
    tid, _, head, _ = _staffed_tournament(client)
    _register_user(client, "hier-rival@example.com")

    response = _appoint(client, tid, head, "hier-rival@example.com", "head_judge")
    assert response.status_code == 403, response.text


def test_judge_cannot_appoint_anyone(client):
    tid, _, _, judge = _staffed_tournament(client)
    _register_user(client, "hier-outsider@example.com")

    response = _appoint(client, tid, judge, "hier-outsider@example.com")
    assert response.status_code == 404, response.text


def test_only_one_head_judge_per_tournament(client):
    tid, org, _, _ = _staffed_tournament(client)
    _register_user(client, "hier-second-head@example.com")

    response = _appoint(client, tid, org, "hier-second-head@example.com", "head_judge")
    assert response.status_code == 409, response.text


def test_organizer_promotes_and_demotes(client):
    tid, org, head, judge = _staffed_tournament(client)
    staff = client.get(f"/api/tournaments/{tid}/staff", headers=org).json()
    head_id = next(m["id"] for m in staff if m["role"] == "head_judge")
    judge_id = next(m["id"] for m in staff if m["role"] == "judge")

    # Il posto è occupato: la promozione passa solo dopo aver degradato il titolare.
    blocked = client.patch(
        f"/api/tournaments/{tid}/staff/{judge_id}", json={"role": "head_judge"}, headers=org
    )
    assert blocked.status_code == 409, blocked.text

    demoted = client.patch(
        f"/api/tournaments/{tid}/staff/{head_id}", json={"role": "judge"}, headers=org
    )
    assert demoted.status_code == 200, demoted.text
    promoted = client.patch(
        f"/api/tournaments/{tid}/staff/{judge_id}", json={"role": "head_judge"}, headers=org
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "head_judge"

    # Il vecchio capojudge ora è un judge: niente più nomine.
    assert _appoint(client, tid, head, "hier-org@example.com").status_code == 404


def test_organizer_account_gives_no_power_on_someone_else_tournament(client):
    """Un capojudge che ha anche un account organizer passa require_organizer: a
    fermarlo deve essere la proprietà del torneo, non il ruolo dell'account."""
    tid, _, _, _ = _staffed_tournament(client)
    staff_list_url = f"/api/tournaments/{tid}/staff"

    outsider = _register_user(client, "hier-other-org@example.com", role="organizer")
    assert _appoint(client, tid, outsider, "hier-org@example.com").status_code == 404
    assert client.get(staff_list_url, headers=outsider).status_code == 404

    # Stesso utente, ma nominato capojudge qui: ora può nominare judge.
    org = _register_user(client, "hier-org@example.com")
    head_org = _register_user(client, "hier-head-org@example.com", role="organizer")
    tid2 = _make_tournament(client, org, name="Secondo Torneo")
    assert _appoint(client, tid2, org, "hier-head-org@example.com", "head_judge").status_code == 201
    _register_user(client, "hier-j3@example.com")
    assert _appoint(client, tid2, head_org, "hier-j3@example.com").status_code == 201

    # ...ma non può promuovere: la PATCH resta dell'organizzatore.
    judge_id = next(
        m["id"] for m in client.get(f"/api/tournaments/{tid2}/staff", headers=head_org).json()
        if m["role"] == "judge"
    )
    blocked = client.patch(
        f"/api/tournaments/{tid2}/staff/{judge_id}", json={"role": "head_judge"}, headers=head_org
    )
    assert blocked.status_code == 404, blocked.text


def test_head_judge_cannot_promote(client):
    tid, org, head, _ = _staffed_tournament(client)
    staff = client.get(f"/api/tournaments/{tid}/staff", headers=org).json()
    judge_id = next(m["id"] for m in staff if m["role"] == "judge")

    response = client.patch(
        f"/api/tournaments/{tid}/staff/{judge_id}", json={"role": "head_judge"}, headers=head
    )
    assert response.status_code == 403, response.text


# ── Rimozioni ─────────────────────────────────────────────────


def test_head_judge_removes_judge_but_not_himself(client):
    tid, org, head, _ = _staffed_tournament(client)
    staff = client.get(f"/api/tournaments/{tid}/staff", headers=head).json()
    head_id = next(m["id"] for m in staff if m["role"] == "head_judge")
    judge_id = next(m["id"] for m in staff if m["role"] == "judge")

    assert client.delete(f"/api/tournaments/{tid}/staff/{head_id}", headers=head).status_code == 403
    assert client.delete(f"/api/tournaments/{tid}/staff/{judge_id}", headers=head).status_code == 204
    assert client.delete(f"/api/tournaments/{tid}/staff/{head_id}", headers=org).status_code == 204


# ── Struttura del torneo ──────────────────────────────────────


def test_head_judge_runs_the_rounds_but_the_judge_does_not(client):
    """In sala è il capojudge a mandare avanti i turni; il judge arbitra i tavoli."""
    tid, org, head, judge = _staffed_tournament(client)
    for i in range(4):
        _enroll(client, tid, f"round-p{i}@example.com")
    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert round1.status_code == 200, round1.text
    for pairing in round1.json()["pairings"]:
        if pairing.get("player_b"):
            client.patch(f"/api/tournaments/{tid}/pairings/{pairing['id']}/result",
                         json={"match_wins_a": 2, "match_wins_b": 0, "draws": 0}, headers=judge)

    assert client.post(f"/api/tournaments/{tid}/rounds", headers=judge).status_code == 404
    generated = client.post(f"/api/tournaments/{tid}/rounds", headers=head)
    assert generated.status_code == 200, generated.text
    assert generated.json()["number"] == 2


def test_head_judge_can_regenerate_the_round(client):
    """Rigenerazione con un assente segnato: tocca anche il ramo che scrive l'audit."""
    tid, org, head, judge = _staffed_tournament(client)
    registrations = [_enroll(client, tid, f"regen-p{i}@example.com")[1] for i in range(4)]
    assert client.post(f"/api/tournaments/{tid}/start", headers=org).status_code == 200

    payload = {"drop_registration_ids": [registrations[0]]}
    assert client.post(f"/api/tournaments/{tid}/rounds/regenerate", headers=judge,
                       json=payload).status_code == 404
    regenerated = client.post(f"/api/tournaments/{tid}/rounds/regenerate", headers=head,
                              json=payload)
    assert regenerated.status_code == 200, regenerated.text
    # Tre giocatori restanti: un tavolo piu un bye.
    assert len(regenerated.json()["pairings"]) == 2


def test_closing_the_tournament_stays_with_the_organizer(client):
    """Aprire i round al capojudge non gli dà anche la chiusura."""
    tid, org, head, _ = _staffed_tournament(client)
    for i in range(2):
        _enroll(client, tid, f"close-p{i}@example.com")
    client.post(f"/api/tournaments/{tid}/start", headers=org)

    assert client.post(f"/api/tournaments/{tid}/close", headers=head).status_code in (403, 404)
    assert client.post(f"/api/tournaments/{tid}/close", headers=org).status_code == 200


# ── Visibilità ────────────────────────────────────────────────


def test_staff_list_shows_head_judge_first(client):
    tid, _, _, judge = _staffed_tournament(client)

    # Anche il judge legge la lista: deve sapere a chi escalare un ruling.
    response = client.get(f"/api/tournaments/{tid}/staff", headers=judge)
    assert response.status_code == 200, response.text
    assert [m["role"] for m in response.json()] == ["head_judge", "judge"]


def test_staff_tournament_shows_in_mine(client):
    tid, _, head, judge = _staffed_tournament(client)

    for headers in (head, judge):
        mine = client.get("/api/tournaments/mine", headers=headers)
        assert mine.status_code == 200, mine.text
        assert tid in [t["id"] for t in mine.json()]


def test_staff_sees_unpublished_pairings(client):
    """Con i pairing nascosti al pubblico il judge deve comunque vedere i tavoli."""
    tid, org, head, judge = _staffed_tournament(client, pairings_public=False)
    for i in range(2):
        _enroll(client, tid, f"hier-p{i}@example.com")
    started = client.post(f"/api/tournaments/{tid}/start", headers=org)
    assert started.status_code == 200, started.text

    for headers in (head, judge):
        rounds = client.get(f"/api/tournaments/{tid}/rounds", headers=headers)
        assert rounds.status_code == 200, rounds.text
        assert rounds.json(), "lo staff non vede i round"

    outsider = _register_user(client, "hier-nobody@example.com")
    assert client.get(f"/api/tournaments/{tid}/rounds", headers=outsider).json() == []


def test_judge_reads_back_penalties(client):
    tid, org, _, judge = _staffed_tournament(client)
    player, registration_id = _enroll(client, tid, "hier-penalized@example.com")

    created = client.post(
        f"/api/tournaments/{tid}/penalties",
        json={"registration_id": registration_id, "kind": "warning", "note": "slow play", "is_private": True},
        headers=judge,
    )
    assert created.status_code == 201, created.text

    listed = client.get(f"/api/tournaments/{tid}/penalties", headers=judge)
    assert listed.status_code == 200, listed.text
    assert [p["note"] for p in listed.json()] == ["slow play"]

    # Un giocatore qualunque non legge le penalità altrui.
    assert client.get(f"/api/tournaments/{tid}/penalties", headers=player).status_code == 404


def test_staff_reads_announcements(client):
    tid, org, head, judge = _staffed_tournament(client)
    assert client.post(
        f"/api/tournaments/{tid}/announcements",
        json={"title": "Round 1", "body": "Si comincia", "send_email": False},
        headers=org,
    ).status_code == 201

    for headers in (head, judge):
        response = client.get(f"/api/tournaments/{tid}/announcements", headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1


# ── my-role ───────────────────────────────────────────────────


def test_my_role_reports_the_whole_chain(client):
    tid, org, head, judge = _staffed_tournament(client)
    player, _ = _enroll(client, tid, "hier-player@example.com")
    outsider = _register_user(client, "hier-stranger@example.com")

    expected = {
        "organizer": (org, True),
        "head_judge": (head, True),
        "judge": (judge, False),
        "player": (player, False),
        "none": (outsider, False),
    }
    for role, (headers, can_manage) in expected.items():
        response = client.get(f"/api/tournaments/{tid}/my-role", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"role": role, "can_manage_judges": can_manage}
