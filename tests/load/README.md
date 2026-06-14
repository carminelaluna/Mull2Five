# Test di carico — 100 tornei × 1000 giocatori

## Scenario simulato

```
100 organizzatori  → gestiscono tornei, inseriscono risultati, generano round
60.000 giocatori   → vedono pairings, inviano risultati, leggono classifica
10.000 spettatori  → sfogliano tornei pubblici
```

## Prerequisiti

### 1. PostgreSQL (non SQLite per il carico)

SQLite non supporta write concorrenti. Per il load test usa PostgreSQL:

```env
# .env
DATABASE_URL=postgresql+psycopg://arcana:arcana@localhost:5432/arcana_events
```

Avvia PostgreSQL:
```bash
docker compose up db -d
```

### 2. Connection pool SQLAlchemy

In `backend/app/db.py` assicurati di avere:
```python
engine = create_engine(
    settings.database_url,
    pool_size=20,           # connessioni permanenti
    max_overflow=30,        # connessioni extra in burst
    pool_pre_ping=True,     # verifica connessioni stale
    pool_timeout=30,
)
```

### 3. Backend avviato

```bash
./scripts/dev.sh   # oppure: uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Per il load test usa **4 worker** invece di 1:
```bash
gunicorn backend.app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 4. Seed database

```bash
# Seed completo: 100 tornei × 1000 giocatori (≈ 10-15 min)
python tests/load/seeder.py --tournaments 100 --players 1000 --rounds 3

# Seed rapido per test: 10 tornei × 100 giocatori (≈ 1 min)
python tests/load/seeder.py --tournaments 10 --players 100 --rounds 3

# Re-seed (cancella i dati precedenti)
python tests/load/seeder.py --tournaments 100 --players 1000 --wipe
```

Il seeder crea `tokens.json` con i JWT per gli utenti.

### 5. Installa locust

```bash
pip install locust
```

---

## Esecuzione test

### UI interattiva (http://localhost:8089)

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

Poi apri http://localhost:8089 e configura:
- **Number of users**: 500 (o più)
- **Spawn rate**: 50 utenti/sec
- **Host**: http://localhost:8000

### Headless (CI/automazione)

```bash
mkdir -p tests/load/results
locust -f tests/load/locustfile.py \
       --host=http://localhost:8000 \
       --users=500 \
       --spawn-rate=50 \
       --run-time=120s \
       --headless \
       --csv=tests/load/results/run_$(date +%Y%m%d_%H%M)
```

### Makefile shortcuts

```bash
make load-test            # UI interattiva
make load-test-headless   # Headless 50 utenti, 60s
```

---

## Distribuzione utenti (500 totali)

| Tipo | % | N | Comportamento |
|---|---|---|---|
| `OrganizerUser` | 10% | 50 | Gestisce tornei, inserisce risultati, genera round |
| `ActivePlayerUser` | 60% | 300 | Pairings, submit risultati, standings |
| `ReadOnlyPlayerUser` | 20% | 100 | Solo lettura: standings, decklists |
| `SpectatorUser` | 10% | 50 | Sfoglia tornei anonimi |

---

## Bottleneck attesi e soluzioni

### 1. Connessioni DB (SQLAlchemy pool)

**Sintomo**: `QueuePool limit overflow`, timeout su connessioni  
**Soluzione**: Aumentare `pool_size` e `max_overflow` in `db.py`

### 2. Rate limiting (slowapi)

**Sintomo**: HTTP 429 su `/api/auth/login`  
**Soluzione**: Il seeder usa inserimento diretto (bypassa rate limiting). I token JWT durano 7 giorni.

### 3. JWT verification overhead

**Sintomo**: Alta latenza su tutti gli endpoint autenticati  
**Soluzione**: Passare da HS256 a RS256 (evita secret lookup) o usare cache JWT

### 4. SQLite write lock

**Sintomo**: `database is locked` con SQLite  
**Soluzione**: **Usare PostgreSQL** — SQLite non supporta write concorrenti

### 5. N+1 query (standings)

**Sintomo**: `/standings` lento con molti giocatori  
**Soluzione**: Il calcolo standings è in Python (O(N)), potrebbe essere ottimizzato con una view SQL

---

## Target di performance

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `GET /tournaments` | < 50ms | < 200ms | < 500ms |
| `GET /standings` | < 100ms | < 500ms | < 1s |
| `GET /my-pairings` | < 50ms | < 200ms | < 500ms |
| `PATCH /result` | < 100ms | < 300ms | < 1s |
| `POST /rounds` | < 500ms | < 2s | < 5s |
| `GET /health` | < 5ms | < 20ms | < 50ms |

---

## Interpretazione risultati

I file CSV generati contengono:
- `*_stats.csv` — throughput, latenza per endpoint
- `*_stats_history.csv` — andamento nel tempo
- `*_failures.csv` — errori

Metriche chiave da monitorare:
```
RPS (requests/sec) — capacità totale del sistema
p95 latency         — il 95% delle richieste sotto questo valore
Failure rate        — dovrebbe essere < 1%
```
