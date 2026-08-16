# Radar Core — ambiente local
#
#   make up      → DB + seed demo + servicio en background (:8000)
#   make down    → baja servicio y base de datos
#   make dev     → servicio en foreground con hot reload (Ctrl+C para salir)
#   make docker-rebuild → reconstruye imagen Docker y sube el servicio (:8000)
#   make e2e     → corre la colección Bruno de punta a punta (requiere `make up`)
#   make test    → suite completa de pruebas
#
SHELL := /bin/bash
PORT ?= 8000
export RADAR_DATABASE_URL ?= postgresql+psycopg://postgres:radar@localhost:54329/radar
export RADAR_WORKSPACE_TOKENS ?= dev-token
# en dev el notify apunta a un host inexistente: sin esperas de backoff
export RADAR_NOTIFY_BACKOFF_BASE_SEG ?= 0
export RADAR_NOTIFY_MAX_INTENTOS ?= 1
export RADAR_PUBLIC_BASE_URL ?= http://localhost:$(PORT)

PIDFILE := var/radar.pid
LOGFILE := var/radar.log
DOCKER_IMAGE ?= radar-core:local
DOCKER_CONTAINER ?= radar-core-local
DOCKER_DATABASE_URL ?= postgresql+psycopg://postgres:radar@host.docker.internal:54329/radar

.PHONY: up down dev db-up db-down seed status logs docker-build docker-up docker-rebuild docker-down test test-perf e2e

up: db-up seed
	@mkdir -p var
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "el servicio ya corre (pid $$(cat $(PIDFILE)))"; \
	else \
		nohup poetry run uvicorn radar_core.main:app --port $(PORT) > $(LOGFILE) 2>&1 & echo $$! > $(PIDFILE); \
		for i in $$(seq 1 30); do curl -sf http://localhost:$(PORT)/health >/dev/null 2>&1 && break; sleep 1; done; \
	fi
	@curl -sf http://localhost:$(PORT)/health >/dev/null || (echo "el servicio no levantó — ver $(LOGFILE)" && exit 1)
	@echo "Radar Core arriba → http://localhost:$(PORT)"
	@echo "  token:   Authorization: Bearer $(RADAR_WORKSPACE_TOKENS)"
	@echo "  público: http://localhost:$(PORT)/public/tabla.html"
	@echo "  logs:    make logs · bajar: make down"

down:
	@if [ -f $(PIDFILE) ]; then kill $$(cat $(PIDFILE)) 2>/dev/null || true; rm -f $(PIDFILE); echo "servicio detenido"; fi
	@pkill -f "uvicorn radar_core.main:app" 2>/dev/null || true
	@$(MAKE) -s db-down

dev: db-up seed
	./scripts/dev.sh

db-up:
	@./scripts/dev_db.sh

db-down:
	@docker rm -f radar-postgis >/dev/null 2>&1 && echo "base de datos detenida" || true

docker-build:
	@docker build -t $(DOCKER_IMAGE) .

docker-up: db-up docker-build
	@docker rm -f $(DOCKER_CONTAINER) >/dev/null 2>&1 || true
	@docker run -d --name $(DOCKER_CONTAINER) \
		-p $(PORT):8000 \
		-e PORT=8000 \
		-e RADAR_DATABASE_URL="$(DOCKER_DATABASE_URL)" \
		-e RADAR_WORKSPACE_TOKENS="$(RADAR_WORKSPACE_TOKENS)" \
		-e RADAR_NOTIFY_BACKOFF_BASE_SEG="$(RADAR_NOTIFY_BACKOFF_BASE_SEG)" \
		-e RADAR_NOTIFY_MAX_INTENTOS="$(RADAR_NOTIFY_MAX_INTENTOS)" \
		-e RADAR_PUBLIC_BASE_URL="$(RADAR_PUBLIC_BASE_URL)" \
		$(DOCKER_IMAGE) >/dev/null
	@for i in $$(seq 1 30); do curl -sf http://localhost:$(PORT)/health >/dev/null 2>&1 && break; sleep 1; done
	@curl -sf http://localhost:$(PORT)/health >/dev/null || (echo "el contenedor no levantó — ver: docker logs $(DOCKER_CONTAINER)" && exit 1)
	@echo "Radar Core Docker arriba → http://localhost:$(PORT)"
	@echo "  imagen:  $(DOCKER_IMAGE)"
	@echo "  logs:    docker logs -f $(DOCKER_CONTAINER) · bajar: make docker-down"

docker-rebuild: docker-up

docker-down:
	@docker rm -f $(DOCKER_CONTAINER) >/dev/null 2>&1 && echo "contenedor detenido" || true

seed:
	@poetry run python scripts/seed_demo.py

status:
	@docker ps --filter name=radar-postgis --format 'db:       {{.Status}}' || true
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "servicio: arriba (pid $$(cat $(PIDFILE)))"; \
	else echo "servicio: abajo"; fi

logs:
	@tail -f $(LOGFILE)

test:
	poetry run pytest

test-perf:
	RADAR_PERF_FULL=1 poetry run pytest -m performance

# Requiere la CLI de Bruno (npx la baja la primera vez)
e2e:
	cd bruno && npx --yes @usebruno/cli run . -r --env local
