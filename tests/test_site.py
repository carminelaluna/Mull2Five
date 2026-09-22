"""
test_site.py — Le pagine di servizio del sito: robots.txt, sitemap.xml, i dati
legali, le statistiche delle visite senza cookie, i termini accettati alla
registrazione e il ritorno dal pagamento sulla pagina di ringraziamento.
"""
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from backend.app.core.config import get_settings
from backend.app.models import PageView, Registration, User, UserRole

BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}


def _register_user(client, email, role="player", **extra):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role, **extra,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _store_with_tournaments(client):
    owner = _register_user(client, "site-owner@example.com", role="organizer")
    slug = client.post("/api/organizations/mine", headers=owner, json={"name": "Carte e Draghi", "city": "Pavia"}).json()["slug"]
    ids = {}
    for name, status in (("Modern pubblico", "published"), ("Bozza segreta", "draft")):
        created = client.post("/api/tournaments", headers=owner, json={
            "name": name, "format": "Modern", "starts_on": str(date.today() + timedelta(days=5)),
            "start_time": "20:00", "capacity": 16, "entry_fee_cents": 500, "status": status,
            "decklist_required": False,
        })
        assert created.status_code == 201, created.text
        ids[status] = created.json()["id"]
    return owner, slug, ids


def test_robots_hides_private_pages_and_points_to_the_sitemap(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and robots.headers["content-type"].startswith("text/plain")
    text = robots.text
    assert "Disallow: /organizer.html" in text and "Disallow: /my-registrations.html" in text
    assert "Sitemap: http://testserver/sitemap.xml" in text
    assert "Disallow: /api" not in text          # le pagine pubbliche si riempiono dalle API


def test_the_sitemap_lists_public_pages_tournaments_and_stores(client):
    _, slug, ids = _store_with_tournaments(client)
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200 and "xml" in sitemap.headers["content-type"]
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = {loc.text for loc in ET.fromstring(sitemap.text).findall("s:url/s:loc", ns)}
    assert "http://testserver/events.html" in urls and "http://testserver/privacy.html" in urls
    assert f"http://testserver/event.html?id={ids['published']}" in urls
    assert f"http://testserver/event.html?id={ids['draft']}" not in urls
    assert f"http://testserver/store.html?s={slug}" in urls
    assert not any("organizer.html" in url or "player.html" in url for url in urls)


def test_legal_details_come_from_the_settings(client, monkeypatch):
    assert client.get("/api/site/legal").json()["complete"] is False
    settings = get_settings()
    monkeypatch.setattr(settings, "legal_name", "Mull2Five di Esempio")
    monkeypatch.setattr(settings, "legal_email", "privacy@example.com")
    legal = client.get("/api/site/legal").json()
    assert legal == {"name": "Mull2Five di Esempio", "email": "privacy@example.com", "address": "",
                     "vat_id": "", "complete": True}


def test_visits_are_counted_without_personal_data(client, db_session):
    hit = lambda body, headers=BROWSER: client.post("/api/analytics/hit", json=body, headers=headers)  # noqa: E731
    assert hit({"path": "/", "referrer": "https://www.google.com/search?q=magic", "width": 390}).status_code == 204
    hit({"path": "/events.html", "referrer": "http://testserver/index.html", "width": 390})       # navigazione interna
    hit({"path": "/player.html?email=mario@example.com", "referrer": "", "width": 1400})          # la query non si salva
    hit({"path": "/events.html", "referrer": "", "width": 1400}, {**BROWSER, "DNT": "1"})          # Do Not Track
    hit({"path": "/events.html", "referrer": "", "width": 1400}, {**BROWSER, "Sec-GPC": "1"})     # Global Privacy Control
    hit({"path": "/events.html", "referrer": "", "width": 1400}, {"User-Agent": "Googlebot/2.1"})  # un bot
    hit({"path": "/../../etc/passwd", "referrer": "", "width": 1400})                             # non è una pagina

    rows = {(r.path, r.referrer, r.device): (r.views, r.entries) for r in db_session.query(PageView).all()}
    assert rows == {
        ("/index.html", "google.com", "mobile"): (1, 1),
        ("/events.html", "", "mobile"): (1, 0),
        ("/player.html", "", "desktop"): (1, 1),
    }
    stored = " ".join(f"{r.path} {r.referrer}" for r in db_session.query(PageView).all())
    assert "mario" not in stored and "q=magic" not in stored

    hit({"path": "/", "referrer": "https://google.com/", "width": 390})
    assert db_session.query(PageView).filter_by(path="/index.html").one().views == 2


def test_only_admins_read_the_statistics(client, db_session):
    client.post("/api/analytics/hit", json={"path": "/", "referrer": "https://google.com/", "width": 390}, headers=BROWSER)
    player = _register_user(client, "site-player@example.com")
    assert client.get("/api/admin/analytics", headers=player).status_code == 403

    admin = _register_user(client, "site-admin@example.com", role="organizer")
    db_session.query(User).filter_by(email="site-admin@example.com").one().role = UserRole.ADMIN
    db_session.commit()
    stats = client.get("/api/admin/analytics?days=7", headers=admin).json()
    assert (stats["total_views"], stats["total_entries"], len(stats["days"])) == (1, 1, 7)
    assert stats["pages"] == [{"label": "/index.html", "count": 1}]
    assert stats["referrers"] == [{"label": "google.com", "count": 1}]
    assert stats["devices"] == [{"label": "mobile", "count": 1}]


def test_signing_up_records_the_accepted_terms(client, db_session):
    refused = client.post("/api/auth/register", json={
        "email": "no-terms@example.com", "display_name": "Senza", "password": "supersecret123", "terms_accepted": False,
    })
    assert refused.status_code == 422 and "termini" in refused.json()["detail"]

    headers = _register_user(client, "terms@example.com", terms_accepted=True)
    assert db_session.query(User).filter_by(email="terms@example.com").one().terms_accepted_at is not None
    assert client.get("/api/auth/me/export", headers=headers).json()["user"]["terms_accepted_at"]


def test_paying_online_comes_back_to_the_thank_you_page(client, db_session):
    from backend.app.services.payments import paypal_order_body

    owner, _, ids = _store_with_tournaments(client)
    player = _register_user(client, "site-payer@example.com")
    client.post(f"/api/tournaments/{ids['published']}/registrations", headers=player, json={})
    registration = db_session.query(Registration).filter_by(tournament_id=ids["published"]).one()
    context = paypal_order_body(registration, None)["application_context"]
    assert context["return_url"].endswith(f"/grazie.html?t={ids['published']}&pagamento=ok")
    assert context["cancel_url"].endswith("/my-registrations.html?pagamento=annullato")


def test_internal_navigation_behind_a_proxy_is_not_a_new_visit(client, db_session):
    # Le pagine su un dominio (qui localhost:5173), l'API dietro un proxy su un altro.
    headers = {**BROWSER, "Origin": "http://localhost:5173"}
    client.post("/api/analytics/hit", json={"path": "/events.html", "referrer": "http://localhost:5173/", "width": 1400},
                headers=headers)
    row = db_session.query(PageView).one()
    assert (row.referrer, row.views, row.entries) == ("", 1, 0)


def test_unique_visitors_are_counted_without_storing_the_ip(client, db_session):
    from backend.app.models import AnalyticsDay, VisitorDay

    page = {"path": "/", "referrer": "https://google.com/", "width": 390}
    hit = lambda headers: client.post("/api/analytics/hit", json=page, headers=headers)  # noqa: E731
    visitor = {**BROWSER, "X-Forwarded-For": "203.0.113.7"}
    hit(visitor)
    hit(visitor)                                   # stessa persona, stesso giorno: una sola
    hit({**BROWSER, "X-Forwarded-For": "203.0.113.9"})

    day = db_session.query(AnalyticsDay).one()
    assert day.visitors == 2 and day.salt                # il segreto di oggi c'è
    codes = [row.code for row in db_session.query(VisitorDay).all()]
    assert len(codes) == 2 and all(len(code) == 32 for code in codes)
    assert not any("203.0.113" in code for code in codes)   # l'IP non si salva


def test_hits_from_other_sites_are_ignored(client, db_session):
    from backend.app.models import PageView

    client.post("/api/analytics/hit", headers={**BROWSER, "Origin": "https://sito-furbo.example"},
                json={"path": "/", "referrer": "https://sito-furbo.example/", "width": 390})
    assert db_session.query(PageView).count() == 0
