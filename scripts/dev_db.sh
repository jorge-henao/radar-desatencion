#!/usr/bin/env bash
# PostGIS local para desarrollo y tests.
set -euo pipefail

NAME=radar-postgis
PORT=54329
# Cualquier imagen Postgres 16 con PostGIS sirve. paradedb la incluye y suele
# estar cacheada; postgis/postgis es la canónica.
IMAGE="${RADAR_DB_IMAGE:-postgis/postgis:16-3.4}"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1 \
   && docker image inspect paradedb/paradedb:0.23.2-pg16 >/dev/null 2>&1; then
  IMAGE=paradedb/paradedb:0.23.2-pg16
fi

if docker ps --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "${NAME} ya está corriendo en :${PORT}"
  exit 0
fi

docker rm -f "${NAME}" >/dev/null 2>&1 || true
docker run -d --name "${NAME}" \
  -p ${PORT}:5432 \
  -e POSTGRES_PASSWORD=radar \
  -e POSTGRES_DB=radar \
  "$IMAGE"

echo -n "esperando a que acepte conexiones"
for i in $(seq 1 60); do
  if docker exec "${NAME}" pg_isready -U postgres -d radar >/dev/null 2>&1; then
    echo " · listo en postgresql://postgres:radar@localhost:${PORT}/radar"
    exit 0
  fi
  echo -n "."
  sleep 1
done
echo "timeout esperando a PostGIS" >&2
exit 1
