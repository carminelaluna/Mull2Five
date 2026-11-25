"""
test_inbox.py — La campanella: lo storico di quello che il sito ha detto a qualcuno.

Quello che conta: arriva anche con le email del torneo spente (l'interruttore è
sulle email), arriva a chi deve e a nessun altro, un genitore vede quelle del
figlio, e "letta" la segna solo chi la possiede.
"""
from datetime import UTC, datetime, timedelta

from backend.app.core.clock import local_today
from backend.app.models import Notification, User, UserRole
from backend.app.services.inbox import KEEP_DAYS, notify, prune


def _user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role})
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org, **fields):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "Serata della campanella", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=2)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
        "email_notifications_enabled": False, **fields})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _bell(client, headers, **params):
    response = client.get("/api/notifications", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(client, headers):
    return [(n["kind"], n["detail"]) for n in _bell(client, headers)["items"]]


def test_a_tournament_rings_the_bell_even_with_its_emails_off(client):
    org = _user(client, "bell-org@example.com", role="organizer")
    tid = _tournament(client, org)
    players = []
    for i in range(2):
        player = _user(client, f"bell-p{i}@example.com")
        reg = client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={}).json()
        client.post(f"/api/tournaments/{tid}/registrations/{reg['id']}/mark-paid", headers=org)
        players.append(player)

    first = _bell(client, players[0])
    assert first["unread"] == 1
    note = first["items"][0]
    assert (note["kind"], note["context"], note["url"], note["read"]) == (
        "registered", "Serata della campanella", f"/event.html?id={tid}", False)

    round1 = client.post(f"/api/tournaments/{tid}/start", headers=org).json()
    for p in round1["pairings"]:
        if p.get("player_b_registration_id"):
            client.patch(f"/api/tournaments/{tid}/pairings/{p['id']}/result", headers=org,
                         json={"match_wins_a": 2, "match_wins_b": 0})
    assert client.post(f"/api/tournaments/{tid}/rounds?force=true", headers=org).status_code == 200
    announced = client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Pizza", "body": "Arriva alle 22.", "send_email": False})
    assert announced.status_code == 201, announced.text

    for player in players:
        # Dalla più nuova: l'annuncio, il turno 2, l'inizio, l'iscrizione.
        assert _kinds(client, player) == [
            ("announcement", ""), ("pairings", "2"), ("started", ""), ("registered", "")]
    latest = _bell(client, players[1])["items"][0]
    assert (latest["title"], latest["body"]) == ("Pizza", "Arriva alle 22.")
    # Chi organizza non è iscritto: la sua campanella resta muta.
    assert _bell(client, org)["items"] == []


def test_only_the_owner_marks_a_notification_as_read(client):
    org = _user(client, "bell-org2@example.com", role="organizer")
    tid = _tournament(client, org)
    mine = _user(client, "bell-mine@example.com")
    other = _user(client, "bell-other@example.com")
    for player in (mine, other):
        client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})
    theirs = _bell(client, other)["items"][0]["id"]

    # Il suo id dal mio account non trova niente.
    assert client.post("/api/notifications/read", headers=mine, json={"ids": [theirs]}).json()["unread"] == 1
    assert _bell(client, other)["unread"] == 1

    counter = client.get("/api/notifications/unread", headers=mine).json()
    assert counter["unread"] == 1 and counter["latest_id"] > 0
    assert client.post("/api/notifications/read", headers=mine, json={}).json()["unread"] == 0
    assert _bell(client, mine)["items"][0]["read"] is True
    # L'app scarica solo quelle dopo l'ultima che ha mostrato.
    assert _bell(client, mine, after_id=counter["latest_id"])["items"] == []
    assert client.get("/api/notifications", headers={}).status_code == 401


def test_a_parent_sees_what_happens_to_the_child(client, db_session):
    org = _user(client, "bell-org3@example.com", role="organizer")
    tid = _tournament(client, org)
    parent = _user(client, "bell-parent@example.com")
    admin = _user(client, "bell-admin@example.com", role="organizer")
    db_session.query(User).filter_by(email="bell-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    child = client.post("/api/admin/profiles", headers=admin, json={
        "guardian_email": "bell-parent@example.com", "display_name": "Luca"}).json()

    as_child = {**parent, "X-Act-As": str(child["id"])}
    assert client.post(f"/api/tournaments/{tid}/registrations", headers=as_child, json={}).status_code == 201

    note = _bell(client, parent)["items"][0]
    assert (note["kind"], note["for_name"]) == ("registered", "Luca")
    assert client.post("/api/notifications/read", headers=parent, json={"ids": [note["id"]]}).json()["unread"] == 0


def test_a_ticket_answer_reaches_the_other_side(client, db_session):
    admin = _user(client, "bell-admin2@example.com", role="organizer")
    db_session.query(User).filter_by(email="bell-admin2@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    player = _user(client, "bell-ticket@example.com")

    ticket = client.post("/api/tickets", headers=player, json={
        "scope": "admin", "subject": "Non entro", "body": "La password non va."}).json()
    note = _bell(client, admin)["items"][0]
    assert (note["kind"], note["title"], note["body"]) == ("ticket_new", "Non entro", "La password non va.")

    client.post(f"/api/tickets/{ticket['id']}/messages", headers=admin, json={"body": "Prova adesso."})
    note = _bell(client, player)["items"][0]
    assert (note["kind"], note["title"], note["body"]) == ("ticket_reply", "Non entro", "Prova adesso.")
    # Chi risponde non avvisa se stesso.
    assert _kinds(client, admin) == [("ticket_new", "")]

    client.post(f"/api/tickets/{ticket['id']}/messages", headers=player, json={"body": "Funziona."})
    assert _kinds(client, admin) == [("ticket_reply", ""), ("ticket_new", "")]


def test_the_day_before_reminder_rings_even_without_the_email(client, db_session):
    from backend.app.services.reminders import send_event_reminders

    org = _user(client, "bell-org4@example.com", role="organizer")
    tid = _tournament(client, org, starts_on=str(local_today() + timedelta(days=1)))
    player = _user(client, "bell-tomorrow@example.com")
    client.post(f"/api/tournaments/{tid}/registrations", headers=player, json={})

    assert send_event_reminders(db_session) == 0      # nessuna email: le ha spente l'organizzatore
    assert _kinds(client, player)[0] == ("reminder", "20:30")
    send_event_reminders(db_session)                  # gira ogni ora: una volta sola
    assert [kind for kind, _ in _kinds(client, player)].count("reminder") == 1


def test_old_notifications_go_away_and_deleting_the_account_takes_them(client, db_session):
    player = _user(client, "bell-old@example.com")
    user_id = db_session.query(User).filter_by(email="bell-old@example.com").one().id
    assert notify(db_session, [user_id, None, user_id], "reminder", context="Vecchio") == 1
    assert notify(db_session, [user_id], "reminder", context="Nuovo") == 1
    old = db_session.query(Notification).filter_by(user_id=user_id, context="Vecchio").one()
    old.created_at = datetime.now(UTC) - timedelta(days=KEEP_DAYS + 1)
    db_session.commit()

    assert prune(db_session) >= 1
    assert [n["context"] for n in _bell(client, player)["items"]] == ["Nuovo"]
    assert client.get("/api/auth/me/export", headers=player).json()["notifications"][0]["context"] == "Nuovo"

    assert client.delete("/api/auth/me", headers=player).status_code == 200
    db_session.expire_all()
    assert db_session.query(Notification).filter_by(user_id=user_id).count() == 0
