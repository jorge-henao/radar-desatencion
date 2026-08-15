"""Fixtures compartidos de la suite.

Requiere el PostGIS de pruebas: ./scripts/dev_db.sh
(postgresql://postgres:radar@localhost:54329/radar)
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from radar_core import db as db_mod
from radar_core import ddl
from radar_core.config import settings
from radar_core.main import create_app
from radar_core.models import Event, Notificacion
from radar_core.schemas import CrearEventoRequest
from radar_core.security import cifrar_ref, hash_reporter
from radar_core.seed.loader import cargar_gazetteer, cargar_territorio
from radar_core.services import eventos as svc_eventos
from radar_core.services.gazetteer import gazetteer
from radar_core.services.ratelimit import rate_limiter

# Base PROPIA de la suite (radar_test): los tests truncan y siembran datos
# sintéticos — jamás deben tocar la base de desarrollo (radar), que puede
# tener los datos DANE reales cargados por scripts/seed_dane.py.
TEST_DB_URL = "postgresql+psycopg://postgres:radar@localhost:54329/radar_test"
_ADMIN_DB_URL = "postgresql+psycopg://postgres:radar@localhost:54329/radar"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# Pin del storyboard: cgto. San Pedro, San José del Palmar (Chocó)
PIN_SAN_PEDRO = {"lat": 4.9861, "lon": -76.2340}
PIN_JAMUNDI = {"lat": 3.22, "lon": -76.62}
PIN_POTRERITO = {"lat": 3.22, "lon": -76.57}
PIN_MAR = {"lat": 2.0, "lon": -80.0}


def _cuadro(lon0, lat0, lon1, lat1) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]],
    }


def _asegurar_db_test() -> None:
    from sqlalchemy import create_engine

    admin = create_engine(_ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'radar_test'")
        ).scalar()
        if not existe:
            conn.execute(text("CREATE DATABASE radar_test"))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _configurar():
    _asegurar_db_test()
    settings.database_url = TEST_DB_URL
    settings.workspace_tokens = TOKEN
    settings.reporter_salt = "salt-de-pruebas"
    settings.fernet_key = ""
    settings.notify_backoff_base_seg = 0.0
    settings.plataforma_notify_url = "http://plataforma.test/notify"
    settings.public_base_url = "http://testserver"
    db_mod.reset_engine()
    yield


@pytest.fixture(scope="session")
def engine(_configurar, tmp_path_factory):
    settings.export_dir = str(tmp_path_factory.mktemp("public"))
    settings.actas_dir = str(tmp_path_factory.mktemp("actas"))
    eng = db_mod.engine()
    ddl.drop_all(eng)
    ddl.init_db(eng)
    return eng


@pytest.fixture(scope="session")
def geo_semilla(engine):
    """Territorios sintéticos con la topología del storyboard."""
    factory = db_mod.session_factory()
    with factory() as s:
        # Valle del Cauca
        cargar_territorio(
            s, pcode="76364", nombre="Jamundí", nivel="municipio", departamento="Valle del Cauca",
            geometria=_cuadro(-76.65, 3.15, -76.45, 3.35), poblacion_estimada=5000,
            factor_accesibilidad=1.0, priorizado=True,
        )
        cargar_territorio(
            s, pcode="76364001", nombre="Potrerito", nivel="centro_poblado", departamento="Valle del Cauca",
            municipio_pcode="76364", geometria=_cuadro(-76.60, 3.20, -76.55, 3.25),
            poblacion_estimada=300, priorizado=True,
        )
        cargar_territorio(
            s, pcode="76364V01", nombre="La Cabaña (Jamundí)", nivel="vereda", departamento="Valle del Cauca",
            municipio_pcode="76364", geometria=_cuadro(-76.54, 3.28, -76.52, 3.30),
            poblacion_estimada=40, factor_accesibilidad=0.5, priorizado=True,
        )
        # Chocó
        cargar_territorio(
            s, pcode="27660", nombre="San José del Palmar", nivel="municipio", departamento="Chocó",
            geometria=_cuadro(-76.35, 4.90, -76.15, 5.05), poblacion_estimada=4000,
            factor_accesibilidad=0.4, priorizado=True,
        )
        cargar_territorio(
            s, pcode="27660C01", nombre="San Pedro", nivel="centro_poblado", departamento="Chocó",
            municipio_pcode="27660", geometria=_cuadro(-76.26, 4.96, -76.21, 5.01),
            poblacion_estimada=30, factor_accesibilidad=0.3, priorizado=True,
        )
        # Riofrío (no priorizado — solo para ambigüedad del gazetteer)
        cargar_territorio(
            s, pcode="76828", nombre="Riofrío", nivel="municipio", departamento="Valle del Cauca",
            geometria=_cuadro(-76.35, 4.10, -76.25, 4.25), poblacion_estimada=2000,
        )
        cargar_territorio(
            s, pcode="76828V01", nombre="La Cabaña (Riofrío)", nivel="vereda", departamento="Valle del Cauca",
            municipio_pcode="76828", geometria=None, poblacion_estimada=25,
        )

        cargar_gazetteer(s, nombre="Jamundí", pcode="76364", nivel="municipio")
        cargar_gazetteer(s, nombre="Riofrío", pcode="76828", nivel="municipio")
        cargar_gazetteer(
            s, nombre="San José del Palmar", pcode="27660", nivel="municipio",
        )
        cargar_gazetteer(
            s, nombre="San José", pcode="27660", nivel="municipio",
            nombre_oficial="San José del Palmar", es_alias=True,
        )
        cargar_gazetteer(
            s, nombre="La Cabaña", pcode="76364V01", nivel="vereda",
            nombre_oficial="La Cabaña (Jamundí)", municipio_pcode="76364", municipio_nombre="Jamundí",
        )
        cargar_gazetteer(
            s, nombre="La Cabaña", pcode="76828V01", nivel="vereda",
            nombre_oficial="La Cabaña (Riofrío)", municipio_pcode="76828", municipio_nombre="Riofrío",
        )
        cargar_gazetteer(
            s, nombre="San Pedro", pcode="27660C01", nivel="centro_poblado",
            nombre_oficial="San Pedro (San José del Palmar)", municipio_pcode="27660",
            municipio_nombre="San José del Palmar",
        )
        cargar_gazetteer(s, nombre="Potrerito", pcode="76364001", nivel="centro_poblado",
                         municipio_pcode="76364", municipio_nombre="Jamundí")
        s.commit()
        gazetteer.refresh(s)
    return True


@pytest.fixture()
def db(engine, geo_semilla):
    """Sesión limpia por test: trunca todo lo transaccional (los seeds geo quedan)."""
    factory = db_mod.session_factory()
    with factory() as s:
        s.execute(text("TRUNCATE events, reconciliaciones, notificaciones, alertas_internas"))
        s.commit()
    rate_limiter.reset()
    with factory() as s:
        yield s


@pytest.fixture()
def app(engine):
    return create_app(with_jobs=False)


@pytest.fixture()
def client(app, db):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- helpers ---


def crear_evento(session, tipo="receipt", payload=None, reporter_ref="ref-u1", key=None, **extra):
    base = {
        "need": {
            "pcode": "27660C01",
            "categorias": ["agua", "alimentos"],
            "hogares_rango": "21-50",
            "pin": PIN_SAN_PEDRO,
        },
        "dispatch": {
            "pcode": "27660C01",
            "items": [{"categoria": "agua", "cantidad": 120, "unidad": "bidones"}],
            "org_nombre": "Acopio Pereira",
        },
        "receipt": {
            "pcode": "27660C01",
            "categorias": ["agua"],
            "hogares": 28,
            "pin": PIN_SAN_PEDRO,
        },
    }[tipo]
    if payload:
        base = {**base, **payload}
    req = CrearEventoRequest(
        type=tipo,
        payload=base,
        reporter_ref=reporter_ref,
        idempotency_key=key or f"conv-{uuid.uuid4()}",
        **extra,
    )
    return svc_eventos.crear_evento(session, req)


def insertar_evento_directo(
    session,
    *,
    tipo,
    pcode,
    payload,
    reporter_ref="ref-directo",
    hace_dias=0,
    folio=None,
    cita_folio=None,
    con_ancla=False,
):
    """Inserta un evento con created_at en el pasado (INSERT permitido; UPDATE no)."""
    from radar_core.folios import generar_folio

    f = folio or generar_folio(session, tipo)
    session.add(
        Event(
            folio=f,
            type=tipo,
            payload=payload,
            pcode=pcode,
            reporter_hash=hash_reporter(reporter_ref),
            idempotency_key=f"directo-{uuid.uuid4()}",
            payload_fingerprint=f"fp-{uuid.uuid4()}",
            cita_folio=cita_folio,
            created_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=hace_dias),
        )
    )
    if con_ancla:
        session.add(
            Notificacion(
                destinatario_cifrado=cifrar_ref(reporter_ref),
                plantilla="acta_registrada",
                variables={"folio": f},
                estado="interna",
                clave_unica=f"ancla:{f}",
            )
        )
    session.commit()
    return f
