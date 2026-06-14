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
echo "  Arcana Events — Deploy $(date '+%Y-%m-%d %H:%M')"
echo "═══════════════════════════════════════"

# ── Backend ───────────────────────────────────────────
if [ "$SKIP_BACKEND" -eq 0 ]; then
  echo ""
  echo "▶ Backend — installazione dipendenze…"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip --quiet
  pip install -e "." --quiet

  echo "▶ Backend — migrazione DB…"
  python -c "from backend.app.db import create_all; create_all()"

  echo "▶ Backend — riavvio servizio systemd…"
  sudo systemctl restart arcana-events && echo "  arcana-events riavviato ✓"
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
