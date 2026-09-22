# ── Fase 1: build del frontend ─────────────────────────────
# Le pagine si costruiscono qui dentro: il deploy parte dal repository, dove
# frontend/dist non c'è (è in .gitignore).
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Fase 2: backend, che serve anche le pagine ─────────────
FROM python:3.12-slim

# FORWARDED_ALLOW_IPS: davanti c'è il proxy di Render. Senza fidarsi del suo
# X-Forwarded-For ogni visitatore avrebbe lo stesso IP, quello del proxy, e il
# rate limit per IP bloccherebbe tutti insieme.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend/dist \
    FORWARDED_ALLOW_IPS=*

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=frontend /frontend/dist ./frontend/dist
COPY scripts ./scripts

EXPOSE 8000

# Render assegna la porta in $PORT; con docker-compose resta la 8000.
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
