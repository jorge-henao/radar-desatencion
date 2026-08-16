# Radar Core — imagen para Railway
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir poetry poetry-plugin-export

COPY pyproject.toml poetry.lock* ./
RUN poetry export --without dev -f requirements.txt -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

COPY radar_core ./radar_core
COPY vigia.yaml ./vigia.yaml

# Railway inyecta PORT; /health es el healthcheck.
ENV RADAR_EXPORT_DIR=/data/public \
    RADAR_ACTAS_DIR=/data/actas

CMD ["sh", "-c", "uvicorn radar_core.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
