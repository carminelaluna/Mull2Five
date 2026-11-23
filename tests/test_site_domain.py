"""
test_site_domain.py — Dall'indirizzo di Render al dominio del sito.

Con un dominio vero, chi apre un link vecchio su mull2five.onrender.com deve
arrivare alla stessa pagina sul dominio. Le API e i webhook invece no: Stripe e
PayPal mandano POST all'indirizzo che hanno, e un redirect li perderebbe.
"""
import pytest

from backend.app.core.config import get_settings

RENDER = {"host": "mull2five.onrender.com"}


@pytest.fixture
def domain(monkeypatch):
    monkeypatch.setattr(get_settings(), "site_url", "https://mull2five.it")


def test_page_on_render_moves_to_the_domain(client, domain):
    response = client.get("/event.html?id=7", headers=RENDER, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "https://mull2five.it/event.html?id=7"


def test_home_on_render_moves_to_the_domain(client, domain):
    response = client.get("/", headers=RENDER, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "https://mull2five.it/"


@pytest.mark.parametrize("path", ["/api/events/public", "/health"])
def test_api_and_health_stay_on_render(client, domain, path):
    response = client.get(path, headers=RENDER, follow_redirects=False)
    assert response.status_code == 200


def test_webhook_posts_are_not_redirected(client, domain):
    """Un POST su /api/ arriva al suo endpoint, qualunque cosa risponda."""
    response = client.post("/api/payments/paypal/webhook", headers=RENDER, json={},
                           follow_redirects=False)
    assert response.status_code != 301


def test_the_domain_itself_is_not_redirected(client, domain):
    response = client.get("/health", headers={"host": "mull2five.it"}, follow_redirects=False)
    assert response.status_code == 200
    response = client.get("/", headers={"host": "mull2five.it"}, follow_redirects=False)
    assert response.status_code != 301


def test_staging_on_its_own_render_address_stays(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "site_url", "https://mull2five-staging.onrender.com")
    response = client.get("/", headers={"host": "mull2five-staging.onrender.com"},
                          follow_redirects=False)
    assert response.status_code != 301


def test_without_site_url_nothing_moves(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "site_url", "")
    response = client.get("/", headers=RENDER, follow_redirects=False)
    assert response.status_code != 301
