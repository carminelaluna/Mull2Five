"""
test_registration_fields.py — Domande all'iscrizione decise dall'organizzatore.
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


def _tournament(client, headers):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": "Prerelease", "format": "Sealed",
        "starts_on": str(date.today() + timedelta(days=5)), "start_time": "10:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


QUESTIONS = [
    {"label": "Taglia maglietta", "kind": "choice", "options": ["S", "M", "L"], "required": True},
    {"label": "Con chi vuoi giocare?", "kind": "text"},
    {"label": "Accetto il regolamento", "kind": "checkbox", "required": True},
]


def _setup(client, prefix):
    org = _register_user(client, f"{prefix}-org@example.com", role="organizer")
    tid = _tournament(client, org)
    saved = client.put(f"/api/tournaments/{tid}/fields", headers=org, json=QUESTIONS)
    assert saved.status_code == 200, saved.text
    return org, tid, {f["label"]: f["id"] for f in saved.json()}


def _enroll(client, headers, tid, answers):
    return client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                       json={"wizards_account": "X", "answers": answers})


def test_players_answer_and_the_organizer_reads(client):
    org, tid, ids = _setup(client, "fields1")
    public = client.get(f"/api/tournaments/{tid}/fields").json()
    assert [f["label"] for f in public] == [q["label"] for q in QUESTIONS]

    player = _register_user(client, "fields1-p@example.com")
    answers = {ids["Taglia maglietta"]: "M", ids["Accetto il regolamento"]: True}
    assert _enroll(client, player, tid, answers).status_code == 201

    row = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()[0]
    assert row["answers"] == {str(ids["Taglia maglietta"]): "M", str(ids["Accetto il regolamento"]): "sì"}


def test_required_and_choices_are_checked(client):
    _, tid, ids = _setup(client, "fields2")
    player = _register_user(client, "fields2-p@example.com")
    missing = _enroll(client, player, tid, {ids["Taglia maglietta"]: "M"})
    assert missing.status_code == 422 and "Accetto il regolamento" in missing.json()["detail"]
    wrong = _enroll(client, player, tid, {ids["Taglia maglietta"]: "XXL", ids["Accetto il regolamento"]: True})
    assert wrong.status_code == 422
    unknown = _enroll(client, player, tid, {999999: "?"})
    assert unknown.status_code == 422


def test_the_desk_can_leave_required_answers_empty(client):
    org, tid, _ = _setup(client, "fields3")
    walk_in = client.post(f"/api/tournaments/{tid}/walk-in", headers=org, json={
        "email": "fields3-p@example.com", "display_name": "Al Banco",
    })
    assert walk_in.status_code == 201, walk_in.text


def test_editing_keeps_answers_of_questions_that_stay(client):
    org, tid, ids = _setup(client, "fields4")
    player = _register_user(client, "fields4-p@example.com")
    _enroll(client, player, tid, {ids["Taglia maglietta"]: "L", ids["Accetto il regolamento"]: True})

    # Resta la taglia (con una scelta in più), sparisce il testo libero.
    edited = client.put(f"/api/tournaments/{tid}/fields", headers=org, json=[
        {"id": ids["Accetto il regolamento"], "label": "Accetto il regolamento", "kind": "checkbox", "required": True},
        {"id": ids["Taglia maglietta"], "label": "Taglia", "kind": "choice", "options": ["S", "M", "L", "XL"]},
    ]).json()
    assert [f["label"] for f in edited] == ["Accetto il regolamento", "Taglia"]
    row = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()[0]
    assert row["answers"][str(ids["Taglia maglietta"])] == "L"


def test_only_the_organizer_edits_the_questions(client):
    org, tid, _ = _setup(client, "fields5")
    other = _register_user(client, "fields5-other@example.com", role="organizer")
    assert client.put(f"/api/tournaments/{tid}/fields", headers=other, json=[]).status_code == 404
    # Una scelta con una sola opzione non è una scelta.
    assert client.put(f"/api/tournaments/{tid}/fields", headers=org,
                      json=[{"label": "Colore", "kind": "choice", "options": ["Rosso"]}]).status_code == 422
