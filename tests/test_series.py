"""
test_series.py — Tornei ricorrenti: le date, la serie, le modifiche a tutta la serie.
"""
from datetime import date, timedelta

from backend.app.core.clock import local_today
from backend.app.routers.tournaments import series_dates


def test_weekly_and_every_two_weeks():
    friday = date(2026, 10, 2)
    assert series_dates(friday, "weekly", count=3) == [date(2026, 10, 9), date(2026, 10, 16), date(2026, 10, 23)]
    assert series_dates(friday, "biweekly", count=2) == [date(2026, 10, 16), date(2026, 10, 30)]


def test_monthly_keeps_the_nth_weekday():
    second_friday = date(2026, 10, 9)
    assert series_dates(second_friday, "monthly", count=3) == [
        date(2026, 11, 13), date(2026, 12, 11), date(2027, 1, 8),
    ]
    # Il quinto venerdì non c'è in ogni mese: diventa l'ultimo.
    fifth_friday = date(2026, 10, 30)
    assert series_dates(fifth_friday, "monthly", count=2) == [date(2026, 11, 27), date(2026, 12, 25)]


def test_until_and_the_one_year_limit():
    start = date(2026, 10, 2)
    assert series_dates(start, "weekly", until=date(2026, 10, 20)) == [date(2026, 10, 9), date(2026, 10, 16)]
    assert len(series_dates(start, "weekly", until=date(2030, 1, 1))) == 52


def _register_user(client, email, role="player"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": email.split("@")[0],
        "password": "supersecret123", "role": role,
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tournament(client, headers, **extra):
    body = {
        "name": "Venerdì Modern", "format": "Modern", "event_type": "locals",
        "starts_on": str(local_today() + timedelta(days=3)), "start_time": "20:30",
        "capacity": 16, "entry_fee_cents": 500, "currency": "EUR", "status": "published",
        "pay_at_event": True, "decklist_required": False,
    }
    body.update(extra)
    created = client.post("/api/tournaments", headers=headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _owner(client, email):
    headers = _register_user(client, email, role="organizer")
    client.post("/api/organizations/mine", headers=headers, json={"name": f"Negozio {email[:8]}"})
    return headers


def test_repeat_creates_the_series(client):
    org = _owner(client, "series-o1@example.com")
    first = _tournament(client, org, event_type="store_championship")
    preview = client.post(f"/api/tournaments/{first['id']}/repeat/preview", headers=org,
                          json={"frequency": "weekly", "count": 3}).json()
    created = client.post(f"/api/tournaments/{first['id']}/repeat", headers=org,
                          json={"frequency": "weekly", "count": 3})
    assert created.status_code == 201, created.text
    copies = created.json()
    assert [c["starts_on"] for c in copies] == preview["dates"]
    assert {c["series_id"] for c in copies} == {client.get(f"/api/tournaments/{first['id']}").json()["series_id"]}
    assert all(c["organization_slug"] == first["organization_slug"] for c in copies)
    assert all((c["event_type"], c["start_time"], c["registered_players"]) == ("store_championship", "20:30", 0)
               for c in copies)

    # Ripetere di nuovo non crea due tornei nella stessa data.
    again = client.post(f"/api/tournaments/{first['id']}/repeat/preview", headers=org,
                        json={"frequency": "weekly", "count": 4}).json()
    assert len(again["already_there"]) == 3 and len(again["dates"]) == 1


def test_repeat_needs_count_or_until(client):
    org = _owner(client, "series-o2@example.com")
    tid = _tournament(client, org)["id"]
    assert client.post(f"/api/tournaments/{tid}/repeat", headers=org,
                       json={"frequency": "weekly"}).status_code == 422
    assert client.post(f"/api/tournaments/{tid}/repeat", headers=org, json={
        "frequency": "weekly", "until": str(local_today()),
    }).status_code == 422   # nessuna data dopo la prima


def test_changes_can_follow_the_series(client):
    org = _owner(client, "series-o3@example.com")
    first = _tournament(client, org)
    copies = client.post(f"/api/tournaments/{first['id']}/repeat", headers=org,
                         json={"frequency": "weekly", "count": 3}).json()
    second = copies[0]
    # Il terzo della serie ha una quota sua, decisa a parte.
    client.patch(f"/api/tournaments/{copies[2]['id']}", headers=org, json={"entry_fee_cents": 700})

    # Il form manda tutto: cambiano orario e capienza, la quota resta quella del secondo.
    changed = client.patch(f"/api/tournaments/{second['id']}?series=true", headers=org, json={
        "start_time": "21:00", "capacity": 24, "starts_on": second["starts_on"], "entry_fee_cents": 500,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["series_updated"] == 2

    after = {t["id"]: t for t in client.get("/api/tournaments?status=published").json()}
    assert after[first["id"]]["start_time"] == "20:30"          # quello prima resta com'era
    assert after[copies[1]["id"]]["start_time"] == "21:00"
    assert after[copies[2]["id"]]["capacity"] == 24
    # Ognuno tiene la sua data, e quello che qui non è cambiato resta suo.
    assert after[copies[2]["id"]]["starts_on"] == copies[2]["starts_on"]
    assert after[copies[2]["id"]]["entry_fee_cents"] == 700


def test_a_follower_that_cannot_take_the_change_is_listed(client):
    org = _owner(client, "series-o4@example.com")
    first = _tournament(client, org, capacity=4)
    copies = client.post(f"/api/tournaments/{first['id']}/repeat", headers=org,
                         json={"frequency": "weekly", "count": 1}).json()
    for i in range(3):
        player = _register_user(client, f"series-full{i}@example.com")
        client.post(f"/api/tournaments/{copies[0]['id']}/registrations", headers=player,
                    json={"wizards_account": "X"})
    changed = client.patch(f"/api/tournaments/{first['id']}?series=true", headers=org, json={"capacity": 2}).json()
    assert changed["capacity"] == 2
    assert changed["series_updated"] == 0
    assert len(changed["series_skipped"]) == 1 and "capienza" in changed["series_skipped"][0]


def test_duplicate_stays_in_the_store(client):
    org = _owner(client, "series-o5@example.com")
    src = _tournament(client, org, event_type="prerelease")
    copy = client.post(f"/api/tournaments/{src['id']}/duplicate", headers=org).json()
    assert (copy["organization_slug"], copy["event_type"]) == (src["organization_slug"], "prerelease")
