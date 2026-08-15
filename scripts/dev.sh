#!/usr/bin/env bash
# Levanta el Radar Core completo en local: DB (Docker) + servicio con hot reload.
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/dev_db.sh

export RADAR_DATABASE_URL="${RADAR_DATABASE_URL:-postgresql+psycopg://postgres:radar@localhost:54329/radar}"
export RADAR_WORKSPACE_TOKENS="${RADAR_WORKSPACE_TOKENS:-dev-token}"
export RADAR_NOTIFY_BACKOFF_BASE_SEG="${RADAR_NOTIFY_BACKOFF_BASE_SEG:-0}"
export RADAR_NOTIFY_MAX_INTENTOS="${RADAR_NOTIFY_MAX_INTENTOS:-1}"

poetry run python scripts/seed_demo.py

echo
echo "Radar Core → http://localhost:8000"
echo "  salud:    curl http://localhost:8000/health"
echo "  público:  http://localhost:8000/public/tabla.html"
echo "  token:    Authorization: Bearer ${RADAR_WORKSPACE_TOKENS}"
echo
exec poetry run uvicorn radar_core.main:app --reload --port "${PORT:-8000}"
