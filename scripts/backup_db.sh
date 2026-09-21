#!/usr/bin/env bash
# backup_db.sh — Backup automatico del database PostgreSQL con retention.
#
# Esegue pg_dump (formato custom, compresso), salva in BACKUP_DIR con timestamp
# e rimuove i backup più vecchi di RETENTION_DAYS. Pensato per essere lanciato
# da cron o dal profilo "backup" di docker-compose. Online i backup li fa
# .github/workflows/backup.yml.
#
# Variabili (override via env o .env):
#   DATABASE_URL     URL SQLAlchemy/psql (postgresql://user:pass@host:port/db)
#   BACKUP_DIR       cartella di destinazione (default: ./backups)
#   RETENTION_DAYS   giorni di conservazione (default: 14)
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DATABASE_URL="${DATABASE_URL:-}"

if [[ -z "$DATABASE_URL" ]]; then
  # Prova a leggerla da .env se presente
  if [[ -f .env ]]; then
    DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- || true)"
  fi
fi

if [[ -z "$DATABASE_URL" ]]; then
  echo "ERRORE: DATABASE_URL non impostata." >&2
  exit 1
fi

# pg_dump non capisce il driver SQLAlchemy (postgresql+psycopg://): normalizza.
PG_URL="${DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"

if [[ "$PG_URL" == sqlite* ]]; then
  echo "Database SQLite: backup non necessario (file singolo). Skip." >&2
  exit 0
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/mull2five_${STAMP}.dump"

echo "→ Backup in $OUT"
pg_dump --format=custom --no-owner --no-privileges --dbname="$PG_URL" --file="$OUT"

# Verifica integrità minima (il file deve esistere e non essere vuoto)
if [[ ! -s "$OUT" ]]; then
  echo "ERRORE: dump vuoto, rimuovo." >&2
  rm -f "$OUT"
  exit 1
fi

echo "→ Retention: rimuovo backup più vecchi di ${RETENTION_DAYS} giorni"
find "$BACKUP_DIR" -name 'mull2five_*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "✓ Backup completato ($(du -h "$OUT" | cut -f1))"
