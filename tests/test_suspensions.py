"""
test_suspensions.py — Sospensioni: un negozio tiene fuori un giocatore dai suoi eventi.
"""
from datetime import date, timedelta

from backend.app.core.clock import local_today


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _owner(client, email, store="Carte Pavia"):
    headers = _register_user(client, email, role="organizer")
    slug = client.post("/api/organizations/mine", headers=headers, json={"name": store}).json()["slug"]
    return headers, slug


def _tournament(client, headers):
    created = client.post("/api/tournaments", headers=headers, json={
        "name": "Serata", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=5)), "start_time": "20:00",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _suspend(client, headers, slug, email, **extra):
    return client.post(f"/api/organizations/{slug}/suspensions", headers=headers,
                       json={"email": email, "reason": "Comportamento scorretto al tavolo", **extra})


def _enroll(client, headers, tid):
    return client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                       json={"wizards_account": "X"})


def test_a_suspended_player_cannot_register_at_that_store(client):
    owner, slug = _owner(client, "susp-o1@example.com")
    tid = _tournament(client, owner)
    other, _ = _owner(client, "susp-o2@example.com", store="Altro Negozio")
    elsewhere = _tournament(client, other)

    player = _register_user(client, "susp-p1@example.com")
    until = local_today() + timedelta(days=30)
    assert _suspend(client, owner, slug, "susp-p1@example.com", ends_on=str(until)).status_code == 201

    refused = _enroll(client, player, tid)
    assert refused.status_code == 403
    assert until.strftime("%d/%m/%Y") in refused.json()["detail"]
    # Il motivo resta al negozio: il giocatore sa fino a quando, non cosa c'è scritto.
    assert "scorretto" not in refused.json()["detail"]
    # Negli altri negozi gioca.
    assert _enroll(client, player, elsewhere).status_code == 201


def test_lifting_lets_the_player_back_and_keeps_the_history(client):
    owner, slug = _owner(client, "susp-o3@example.com")
    tid = _tournament(client, owner)
    player = _register_user(client, "susp-p2@example.com")
    suspension = _suspend(client, owner, slug, "susp-p2@example.com").json()
    assert suspension["active"] is True and suspension["ends_on"] is None

    lifted = client.post(f"/api/organizations/{slug}/suspensions/{suspension['id']}/lift", headers=owner)
    assert lifted.status_code == 200
    assert _enroll(client, player, tid).status_code == 201

    history = client.get(f"/api/organizations/{slug}/suspensions", headers=owner).json()
    assert [(s["email"], s["active"]) for s in history] == [("susp-p2@example.com", False)]
    assert history[0]["lifted_at"] is not None
    assert history[0]["created_by_name"] == "susp-o3"


def test_an_expired_suspension_no_longer_blocks(client, db_session):
    from sqlalchemy import select

    from backend.app.models import Organization, Suspension, User

    owner, slug = _owner(client, "susp-o4@example.com")
    tid = _tournament(client, owner)
    player = _register_user(client, "susp-p3@example.com")
    org = db_session.scalar(select(Organization).where(Organization.slug == slug))
    user = db_session.scalar(select(User).where(User.email == "susp-p3@example.com"))
    db_session.add(Suspension(organization_id=org.id, user_id=user.id, reason="Vecchia storia",
                              ends_on=local_today() - timedelta(days=1)))
    db_session.commit()
    assert _enroll(client, player, tid).status_code == 201


def test_the_desk_sees_why(client):
    owner, slug = _owner(client, "susp-o5@example.com")
    tid = _tournament(client, owner)
    _register_user(client, "susp-p4@example.com")
    _suspend(client, owner, slug, "susp-p4@example.com")
    walk_in = client.post(f"/api/tournaments/{tid}/walk-in", headers=owner, json={
        "email": "susp-p4@example.com", "display_name": "Qualcuno", "wizards_account": "X",
    })
    assert walk_in.status_code == 409
    assert "Comportamento scorretto" in walk_in.json()["detail"]


def test_players_already_registered_show_up_in_the_warnings(client):
    owner, slug = _owner(client, "susp-o6@example.com")
    tid = _tournament(client, owner)
    player = _register_user(client, "susp-p5@example.com")
    assert _enroll(client, player, tid).status_code == 201
    _suspend(client, owner, slug, "susp-p5@example.com")

    warnings = client.get(f"/api/tournaments/{tid}/warnings", headers=owner).json()
    flagged = next(w for w in warnings if w["code"] == "suspended_players")
    assert "susp-p5" in flagged["message"]


def test_what_cannot_be_suspended(client):
    owner, slug = _owner(client, "susp-o7@example.com")
    _register_user(client, "susp-staff@example.com", role="organizer")
    client.post(f"/api/organizations/{slug}/members", headers=owner, json={"email": "susp-staff@example.com"})
    assert _suspend(client, owner, slug, "susp-staff@example.com").status_code == 409

    _register_user(client, "susp-p6@example.com")
    assert _suspend(client, owner, slug, "susp-p6@example.com",
                    ends_on=str(local_today() - timedelta(days=1))).status_code == 422
    assert _suspend(client, owner, slug, "susp-p6@example.com").status_code == 201
    assert _suspend(client, owner, slug, "susp-p6@example.com").status_code == 409
    assert _suspend(client, owner, slug, "nessuno@example.com").status_code == 404

    outsider = _register_user(client, "susp-out@example.com", role="organizer")
    assert client.get(f"/api/organizations/{slug}/suspensions", headers=outsider).status_code == 403
