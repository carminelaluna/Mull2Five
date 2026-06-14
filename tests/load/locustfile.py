"""
locustfile.py — Test di carico concorrente.

Distribuzione 500 utenti:
  OrganizerUser   10%  →  50 organizzatori  (gestiscono tornei)
  ActivePlayer    60%  → 300 giocatori attivi (pairings, risultati)
  ReadOnlyPlayer  20%  → 100 giocatori passivi (standings)
  SpectatorUser   10%  →  50 anonimi (sfogliano tornei)

Avvio:
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    # oppure headless:
    make load-test-headless
"""

import json
import os
import random

from locust import HttpUser, SequentialTaskSet, TaskSet, between, events, task

# ── Carica token pre-generati dal seeder ─────────────────

_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")
_orgs:    list[dict] = []
_players: list[dict] = []

try:
    with open(_TOKEN_FILE) as f:
        data = json.load(f)
    _orgs    = [e for e in data.get("organizers",    []) if e.get("tournament_id")]
    _players = [e for e in data.get("players_sample",[]) if e.get("tournament_id")]
    print(f"[locust] {len(_orgs)} org, {len(_players)} players con tournament_id")
except FileNotFoundError:
    print("[locust] ⚠ tokens.json non trovato — esegui: python tests/load/seeder.py")

_all_tids: list[int] = []

@events.test_start.add_listener
def on_start(environment, **kwargs):
    """Raccoglie i tournament_id disponibili per gli spettatori anonimi."""
    import httpx
    try:
        r = httpx.get(f"{environment.host}/api/tournaments?status=running", timeout=10)
        if r.status_code == 200:
            items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
            _all_tids.extend(t["id"] for t in items)
            print(f"[locust] {len(_all_tids)} tornei disponibili per spettatori")
    except Exception as e:
        print(f"[locust] ⚠ impossibile caricare tournament_ids: {e}")


def _pick_org()    -> dict | None: return random.choice(_orgs)    if _orgs    else None
def _pick_player() -> dict | None: return random.choice(_players) if _players else None
def _pick_tid()    -> int  | None: return random.choice(_all_tids) if _all_tids else None
def _auth(token: str) -> dict:     return {"Authorization": f"Bearer {token}"}


# ── Helpers per gestione errori ───────────────────────────

def _get(client, url, *, label, token=None, ok=(200,)):
    """GET con gestione graceful degli errori noti."""
    headers = _auth(token) if token else {}
    with client.get(url, headers=headers, name=label, catch_response=True) as r:
        if r.status_code in ok or r.status_code in (404, 409, 422):
            r.success()
        elif r.status_code == 429:
            r.success()   # rate limit: non è un failure del server
        # 500 rimane failure — vogliamo tracciarlo


def _patch(client, url, body, *, label, token, ok=(200,)):
    headers = _auth(token)
    with client.patch(url, json=body, headers=headers, name=label, catch_response=True) as r:
        if r.status_code in ok or r.status_code in (404, 409, 422, 429):
            r.success()


def _post(client, url, body, *, label, token, ok=(200, 201)):
    headers = _auth(token)
    with client.post(url, json=body, headers=headers, name=label, catch_response=True) as r:
        if r.status_code in ok or r.status_code in (404, 409, 422, 429):
            r.success()


# ── Scenario 1: Organizzatore ─────────────────────────────

class OrganizerTasks(SequentialTaskSet):
    token: str = ""
    tid:   int | None = None

    def on_start(self):
        entry = _pick_org()
        if entry:
            self.token = entry["token"]
            self.tid   = entry["tournament_id"]

    @task
    def view_tournament(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}",
             label="/api/tournaments/{id} [ORG]", token=self.token)

    @task
    def view_registrations(self):
        if not self.tid: return
        # Usa paginazione — non caricare tutti i 1000 iscritti in una volta
        _get(self.client, f"/api/tournaments/{self.tid}/registrations?page=1&page_size=50",
             label="/api/tournaments/{id}/registrations [ORG]", token=self.token)

    @task
    def view_standings(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}/standings",
             label="/api/tournaments/{id}/standings [ORG]", token=self.token)

    @task
    def view_and_set_result(self):
        """Legge i round e inserisce un risultato pendente."""
        if not self.tid: return
        with self.client.get(
            f"/api/tournaments/{self.tid}/rounds",
            headers=_auth(self.token),
            name="/api/tournaments/{id}/rounds [ORG]",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.success(); return
            rounds = r.json() or []
            for rnd in reversed(rounds):
                for p in rnd.get("pairings", []):
                    if not p.get("result") and p.get("player_b"):
                        res = random.choice(["2-0","2-1","1-2","0-2","1-1"])
                        ma, mb = int(res[0]), int(res[2])
                        _patch(
                            self.client,
                            f"/api/tournaments/{self.tid}/pairings/{p['id']}/result",
                            {"match_wins_a": ma, "match_wins_b": mb, "draws": 0},
                            label="/api/pairings/{id}/result [ORG]",
                            token=self.token,
                        )
                        return

    @task
    def try_generate_round(self):
        if not self.tid: return
        _post(self.client, f"/api/tournaments/{self.tid}/rounds", {},
              label="/api/tournaments/{id}/rounds [ORG generate]",
              token=self.token, ok=(200, 201))


# ── Scenario 2: Giocatore attivo ──────────────────────────

class ActivePlayerTasks(SequentialTaskSet):
    token: str = ""
    tid:   int | None = None

    def on_start(self):
        entry = _pick_player()
        if entry:
            self.token = entry["token"]
            self.tid   = entry["tournament_id"]  # torneo corretto per questo giocatore

    @task(4)
    def check_my_pairings(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}/my-pairings",
             label="/api/tournaments/{id}/my-pairings [PLAYER]",
             token=self.token, ok=(200, 404))

    @task(2)
    def check_standings(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}/standings",
             label="/api/tournaments/{id}/standings [PLAYER]", token=self.token)

    @task(1)
    def submit_result(self):
        """Invia il risultato — recupera prima l'id del pairing."""
        if not self.tid: return
        with self.client.get(
            f"/api/tournaments/{self.tid}/my-pairings",
            headers=_auth(self.token),
            name="/api/my-pairings [prefetch for result]",
            catch_response=True,
        ) as r:
            if r.status_code != 200: r.success(); return
            rounds = r.json() or []
            for rnd in reversed(rounds):
                for p in rnd.get("pairings", []):
                    if not p.get("report_score"):
                        res = random.choice(["2-0","2-1","1-2","0-2","1-1"])
                        ma, mb = int(res[0]), int(res[2])
                        _patch(
                            self.client,
                            f"/api/tournaments/{self.tid}/pairings/{p['id']}/player-result",
                            {"match_wins_a": ma, "match_wins_b": mb, "draws": 0},
                            label="/api/pairings/{id}/player-result [PLAYER]",
                            token=self.token,
                        )
                        return

    @task(1)
    def my_registration(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}/my-registration",
             label="/api/tournaments/{id}/my-registration [PLAYER]",
             token=self.token, ok=(200, 404))


# ── Scenario 3: Giocatore passivo ─────────────────────────

class ReadOnlyPlayerTasks(TaskSet):
    token: str = ""
    tid:   int | None = None

    def on_start(self):
        entry = _pick_player()
        if entry:
            self.token = entry["token"]
            self.tid   = entry["tournament_id"]

    @task(5)
    def standings(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}/standings",
             label="/api/tournaments/{id}/standings [READ-ONLY]", token=self.token)

    @task(2)
    def tournament_info(self):
        if not self.tid: return
        _get(self.client, f"/api/tournaments/{self.tid}",
             label="/api/tournaments/{id} [READ-ONLY]")

    @task(1)
    def browse(self):
        _get(self.client, "/api/tournaments?status=running",
             label="/api/tournaments?running [READ-ONLY]")


# ── Scenario 4: Spettatore anonimo ───────────────────────

class SpectatorTasks(TaskSet):
    @task(3)
    def browse(self):
        _get(self.client, "/api/tournaments?status=published,running",
             label="/api/tournaments [ANON]")

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def random_tournament(self):
        tid = _pick_tid()
        if tid:
            _get(self.client, f"/api/tournaments/{tid}",
                 label="/api/tournaments/{id} [ANON]")


# ── User classes ──────────────────────────────────────────

class OrganizerUser(HttpUser):
    weight    = 1
    wait_time = between(5, 15)   # organizzatori aggiornano ogni 5-15s (realistico)
    tasks     = [OrganizerTasks]

class ActivePlayerUser(HttpUser):
    weight    = 6
    wait_time = between(3, 8)    # giocatori ricontrollano ogni 3-8s durante il round
    tasks     = [ActivePlayerTasks]

class ReadOnlyPlayerUser(HttpUser):
    weight    = 2
    wait_time = between(5, 15)   # spettatori controllano standings ogni 5-15s
    tasks     = [ReadOnlyPlayerTasks]

class SpectatorUser(HttpUser):
    weight    = 1
    wait_time = between(5, 20)   # anonimi sfogliano lentamente
    tasks     = [SpectatorTasks]
