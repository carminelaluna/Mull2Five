#!/usr/bin/env bash
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

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

