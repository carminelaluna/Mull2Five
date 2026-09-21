"""
test_announcement_targeting.py — Annunci a un sottoinsieme di iscritti.

Un annuncio senza tag è per tutti, come è sempre stato. Con dei tag è per chi ne
porta almeno uno, e per nessun altro: né via email, né aprendo la pagina del torneo.
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


def _tournament(client, org, name="Serata Modern"):
    created = client.post("/api/tournaments", headers=org, json={
        "name": name, "format": "Modern",
        "starts_on": str(date.today() + timedelta(days=3)),
        "capacity": 32, "entry_fee_cents": 0, "currency": "EUR", "status": "published",
        "pay_at_event": True,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _enroll(client, tid, email):
    headers = _register_user(client, email)
    reg = client.post(f"/api/tournaments/{tid}/registrations", headers=headers,
                      json={"wizards_account": email[:8]})
    assert reg.status_code == 201, reg.text
    return headers


def _tag(client, org, name):
    created = client.post("/api/tags", headers=org, json={"name": name, "color": "#d8b465"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _player_ids(client, tid, org, emails):
    """Gli id degli iscritti, che servono per assegnare i tag."""
    rows = client.get(f"/api/tournaments/{tid}/registrations", headers=org).json()
    by_email = {r["player_email"]: r["player_id"] for r in rows}
    return [by_email[e] for e in emails]


def _titles(client, tid, headers):
    response = client.get(f"/api/tournaments/{tid}/announcements", headers=headers)
    assert response.status_code == 200, response.text
    return [a["title"] for a in response.json()]


def _sala(client):
    """Un torneo con due iscritti, di cui uno etichettato "Nuovi"."""
    org = _register_user(client, "ann-org@example.com", role="organizer")
    tid = _tournament(client, org)
    nuovo = _enroll(client, tid, "ann-nuovo@example.com")
    veterano = _enroll(client, tid, "ann-vet@example.com")
    tag_id = _tag(client, org, "Nuovi")
    ids = _player_ids(client, tid, org, ["ann-nuovo@example.com"])
    assert client.post(f"/api/tags/{tag_id}/players", headers=org,
                       json={"user_ids": ids}).status_code == 200
    return tid, org, nuovo, veterano, tag_id


def test_an_announcement_without_tags_is_for_everyone(client):
    tid, org, nuovo, veterano, _ = _sala(client)
    assert client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Si comincia alle 20", "body": "Tavoli pronti",
    }).status_code == 201

    assert _titles(client, tid, nuovo) == ["Si comincia alle 20"]
    assert _titles(client, tid, veterano) == ["Si comincia alle 20"]


def test_a_targeted_announcement_reaches_only_the_tagged(client):
    tid, org, nuovo, veterano, tag_id = _sala(client)
    created = client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Tutorial alle 19:30", "body": "Per chi è alla prima serata",
        "tag_ids": [tag_id],
    })
    assert created.status_code == 201, created.text
    assert created.json()["audience"] == "Nuovi"

    assert _titles(client, tid, nuovo) == ["Tutorial alle 19:30"]
    assert _titles(client, tid, veterano) == [], "il veterano legge un annuncio non suo"
    # L'organizzatore vede tutto quello che ha mandato, mirato o no.
    assert _titles(client, tid, org) == ["Tutorial alle 19:30"]


def test_several_tags_are_a_union_not_an_intersection(client):
    """Chi porta uno solo dei tag scelti è comunque fra i destinatari."""
    tid, org, nuovo, veterano, nuovi = _sala(client)
    commander = _tag(client, org, "Commander")
    ids = _player_ids(client, tid, org, ["ann-vet@example.com"])
    client.post(f"/api/tags/{commander}/players", headers=org, json={"user_ids": ids})

    created = client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Due gruppi", "body": "Vale per entrambi", "tag_ids": [nuovi, commander],
    })
    assert created.status_code == 201, created.text
    assert created.json()["audience"] == "Commander, Nuovi"
    assert _titles(client, tid, nuovo) == ["Due gruppi"]
    assert _titles(client, tid, veterano) == ["Due gruppi"]


def test_the_audience_is_counted_before_the_announcement_is_written(client):
    tid, org, _, _, tag_id = _sala(client)

    tutti = client.get(f"/api/tournaments/{tid}/announcements/audience", headers=org)
    assert tutti.status_code == 200, tutti.text
    conteggio = lambda r: {k: r.json()[k] for k in ("recipients", "total", "label")}  # noqa: E731
    assert conteggio(tutti) == {"recipients": 2, "total": 2, "label": ""}

    mirato = client.get(f"/api/tournaments/{tid}/announcements/audience",
                        headers=org, params={"tag_ids": [tag_id]})
    assert conteggio(mirato) == {"recipients": 1, "total": 2, "label": "Nuovi"}


def test_a_tag_of_another_store_cannot_be_used(client, db_session):
    """I clienti etichettati da un altro negozio non sono una platea disponibile."""
    from sqlalchemy import select

    from backend.app.models import Organization, User

    tid, org, _, _, _ = _sala(client)
    altra = Organization(slug="negozio-rivale", name="Negozio Rivale")
    db_session.add(altra)
    db_session.commit()
    rivale = _register_user(client, "ann-altro-org@example.com", role="organizer")
    utente = db_session.scalar(select(User).where(User.email == "ann-altro-org@example.com"))
    utente.organization_id = altra.id
    db_session.commit()
    suo_tag = _tag(client, rivale, "Clienti suoi")

    rifiutato = client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Non dovrebbe partire", "body": "...", "tag_ids": [suo_tag],
    })
    assert rifiutato.status_code == 404, rifiutato.text


def test_deleting_the_tag_does_not_make_the_announcement_public(client):
    """La platea è fissata all'invio: cancellare l'etichetta non allarga il pubblico."""
    tid, org, nuovo, veterano, tag_id = _sala(client)
    client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Solo per i nuovi", "body": "Riservato", "tag_ids": [tag_id],
    })
    assert client.delete(f"/api/tags/{tag_id}", headers=org).status_code == 204

    assert _titles(client, tid, veterano) == [], "cancellare il tag ha scoperto l'annuncio"
    assert _titles(client, tid, nuovo) == ["Solo per i nuovi"]


def test_who_enrolls_later_reads_the_open_announcements_only(client):
    tid, org, _, _, tag_id = _sala(client)
    client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Per i nuovi", "body": "Riservato", "tag_ids": [tag_id],
    })
    client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Per tutti", "body": "Aperto",
    })

    ritardatario = _enroll(client, tid, "ann-tardi@example.com")
    assert _titles(client, tid, ritardatario) == ["Per tutti"]


def test_an_empty_audience_is_allowed_but_nobody_reads_it(client):
    """Un tag che nessun iscritto porta: l'annuncio si crea e resta senza lettori."""
    tid, org, nuovo, veterano, _ = _sala(client)
    vuoto = _tag(client, org, "Mai assegnato")

    created = client.post(f"/api/tournaments/{tid}/announcements", headers=org, json={
        "title": "Nel vuoto", "body": "...", "tag_ids": [vuoto],
    })
    assert created.status_code == 201, created.text
    assert _titles(client, tid, nuovo) == []
    assert _titles(client, tid, veterano) == []
