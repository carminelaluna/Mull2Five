.PHONY: install dev docker-up docker-down lint test db-up db-wait db-down \
        fe-install fe-dev fe-build fe-test fe-test-run fe-e2e \
        load-test load-test-headless

# Docker Compose v1 (docker-compose) o v2 (docker compose): rileva quale è disponibile
COMPOSE := $(shell command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo "docker compose")
# Nome del container DB generato da compose (cartella_servizio_indice)
DB_CONTAINER := tournamentorganizer-db-1

# ── Database (PostgreSQL via Docker) ─────────────────

# Avvia il container PostgreSQL se non è già in esecuzione.
db-up:
	$(COMPOSE) up -d db

# Attende che PostgreSQL accetti connessioni (evita il crash dei worker allo startup).
db-wait: db-up
	@echo "In attesa che PostgreSQL sia pronto..."
	@for i in $$(seq 1 30); do \
	  docker exec $(DB_CONTAINER) pg_isready -U mull2five -d mull2five >/dev/null 2>&1 \
	    && echo "PostgreSQL pronto." && exit 0; \
	  sleep 1; \
	done; \
	echo "PostgreSQL non risponde dopo 30s." && exit 1

db-down:
	$(COMPOSE) stop db

# ── Backend ──────────────────────────────────────────

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

# dev dipende da db-wait: il DB è garantito su prima dell'avvio.
dev: db-wait
	. .venv/bin/activate && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

lint:
	. .venv/bin/activate && ruff check backend

test:
	. .venv/bin/activate && pytest

# ── Frontend (da eseguire dalla root) ────────────────

fe-install:
	cd frontend && npm install

fe-dev:
	cd frontend && npm run dev

fe-build:
	cd frontend && npm run build

fe-test:
	cd frontend && npm run test

fe-test-run:
	cd frontend && npm run test:run

fe-e2e:
	cd frontend && npm run e2e

# ── Load test (richiede backend in esecuzione) ────────────

load-test:
	. .venv/bin/activate && locust -f tests/load/locustfile.py \
	  --host=http://localhost:8000

load-test-headless:
	mkdir -p tests/load/results
	. .venv/bin/activate && locust -f tests/load/locustfile.py \
	  --host=http://localhost:8000 \
	  --users=500 --spawn-rate=50 --run-time=120s --headless \
	  --csv=tests/load/results/run_$(shell date +%Y%m%d_%H%M)

load-seed:
	. .venv/bin/activate && python tests/load/seeder.py \
	  --tournaments 100 --players 1000 --rounds 3

load-seed-quick:
	. .venv/bin/activate && python tests/load/seeder.py \
	  --tournaments 10 --players 100 --rounds 3

load-seed-wipe:
	. .venv/bin/activate && python tests/load/seeder.py \
	  --tournaments 100 --players 1000 --wipe

# ── Docker ───────────────────────────────────────────

docker-up:
	$(COMPOSE) up --build

docker-down:
	$(COMPOSE) down
