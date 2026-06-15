#!/usr/bin/env bash
# deploy.sh — Deployment automatico in produzione Linux
# Uso: ./scripts/deploy.sh [--skip-frontend] [--skip-backend]
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_FRONTEND=0
SKIP_BACKEND=0
for arg in "$@"; do
  [ "$arg" = "--skip-frontend" ] && SKIP_FRONTEND=1
  [ "$arg" = "--skip-backend"  ] && SKIP_BACKEND=1
done

echo "═══════════════════════════════════════"
echo "  Manabind — Deploy $(date '+%Y-%m-%d %H:%M')"
echo "═══════════════════════════════════════"

# ── Backend ───────────────────────────────────────────
if [ "$SKIP_BACKEND" -eq 0 ]; then
  echo ""
  echo "▶ Backend — installazione dipendenze…"
  if [ ! -f ".env" ]; then
    echo "ERRORE: .env mancante. Copia .env.example in .env e configura DATABASE_URL/SECRET_KEY prima del deploy." >&2
    exit 1
  fi

  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip --quiet
  pip install -e "." --quiet

  echo "▶ Backend — migrazione DB…"
  python -c "from backend.app.db import create_all; create_all()"

  echo "▶ Backend — riavvio servizio systemd…"
  sudo systemctl restart manabind && echo "  manabind riavviato ✓"

  echo "▶ Backend — health check locale…"
  if ! curl --fail --silent --show-error http://127.0.0.1:8000/health >/tmp/manabind-health.json; then
    echo "ERRORE: backend non raggiungibile su 127.0.0.1:8000. Ultimi log:" >&2
    sudo journalctl -u manabind -n 80 --no-pager >&2 || true
    exit 1
  fi
  cat /tmp/manabind-health.json
  echo ""
fi

# ── Frontend ──────────────────────────────────────────
if [ "$SKIP_FRONTEND" -eq 0 ]; then
  echo ""
  echo "▶ Frontend — build Vite…"
  cd frontend
  npm ci --silent
  npm run build
  cd ..
  echo "  Build completato → frontend/dist/ ✓"
fi

# ── Nginx ─────────────────────────────────────────────
echo ""
echo "▶ Nginx — reload configurazione…"
sudo nginx -t && sudo systemctl reload nginx && echo "  nginx ricaricato ✓"

echo ""
echo "✓ Deploy completato."
