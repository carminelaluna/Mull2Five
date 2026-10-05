"""
test_templates.py — I modelli di torneo.

Un modello è fatto per essere riusato mesi dopo: deve portarsi dietro le
impostazioni ma **non** la data, e non deve finire sotto gli occhi di un altro
negozio — dentro ci sono sede, quota e metodi di pagamento.
"""
from datetime import timedelta

from backend.app.core.clock import local_today


def _register_user(client, email, role="organizer"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, org):
    created = client.post("/api/tournaments", headers=org, json={
        "name": "FNM Modern", "format": "Modern",
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "20:30",
        "capacity": 32, "entry_fee_cents": 1500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False, "venue": "Il Covo del Drago",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_a_template_keeps_the_settings_and_not_the_date(client):
    org = _register_user(client, "modelli-org@example.com")
    tid = _tournament(client, org)

    salvato = client.post("/api/tournaments/templates", headers=org,
                          json={"name": "FNM di sempre", "from_tournament_id": tid})
    assert salvato.status_code == 201, salvato.text
    modello = salvato.json()
    assert modello["name"] == "FNM di sempre"
    impostazioni = modello["payload"]
    assert impostazioni["format"] == "Modern"
    assert impostazioni["capacity"] == 32
    assert impostazioni["entry_fee_cents"] == 1500
    assert impostazioni["start_time"] == "20:30"
    assert impostazioni["venue"] == "Il Covo del Drago"
    assert impostazioni["name"] == "FNM Modern"
    # La data no: è l'unica cosa che cambia ogni volta.
    assert "starts_on" not in impostazioni

    elenco = client.get("/api/tournaments/templates", headers=org)
    # "templates" non dev'essere scambiato per l'identificativo di un torneo.
    assert elenco.status_code == 200, elenco.text
    assert [m["name"] for m in elenco.json()] == ["FNM di sempre"]


def test_templates_do_not_cross_the_counter(client):
    mio = _register_user(client, "modelli-mio@example.com")
    altrui = _register_user(client, "modelli-altrui@example.com")
    tid = _tournament(client, mio)
    modello = client.post("/api/tournaments/templates", headers=mio,
                          json={"name": "Solo mio", "from_tournament_id": tid}).json()

    assert client.get("/api/tournaments/templates", headers=altrui).json() == []
    # E non si cancella il modello di un altro.
    assert client.delete(f"/api/tournaments/templates/{modello['id']}", headers=altrui).status_code == 404

    assert client.delete(f"/api/tournaments/templates/{modello['id']}", headers=mio).status_code == 204
    assert client.get("/api/tournaments/templates", headers=mio).json() == []


def test_a_template_is_born_from_a_tournament_of_yours(client):
    mio = _register_user(client, "modelli-mio2@example.com")
    altrui = _register_user(client, "modelli-altrui2@example.com")
    tid = _tournament(client, mio)
    rubato = client.post("/api/tournaments/templates", headers=altrui,
                         json={"name": "Non tuo", "from_tournament_id": tid})
    assert rubato.status_code in (403, 404), rubato.text
