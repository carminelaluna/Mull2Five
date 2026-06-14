#!/usr/bin/env bash
# Backend dev server — esegui da WSL dalla root del progetto
# Il frontend Vite va avviato separatamente: cd frontend && npm run dev
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

# Libera la porta se già occupata
fuser -k 8000/tcp 2>/dev/null || true

uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
