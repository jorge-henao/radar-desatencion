import json
import datetime as dt
from pathlib import Path

import pytest

from radar_core.config import settings
from radar_core.models import VigiaRun
from radar_core.security import hash_reporter
from radar_core.services import vigia
from radar_core.services.export import exportar
from tests.conftest import PIN_SAN_PEDRO
from tests.conftest import AUTH, crear_evento

pytestmark = pytest.mark.service


FUENTE = vigia.FuenteVigia(id="eltiempo", url="https://eltiempo.test", confianza=0.8)


def _leer_vista():
    return json.loads(Path(settings.export_dir, "vista-operativa.json").read_text())


def test_s3_01_dia_cero_curado_poblado_con_barra_vigia(db, engine):
    vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua", "medicamentos"],
            "cita": "las familias de San Pedro completan varios dias sin agua potable",
            "url": "https://eltiempo.test/san-pedro",
            "fecha_publicacion": "2026-08-14",
        },
        FUENTE,
    )
    vigia.registrar_run(db, {"fuentes": {"eltiempo": {"senales": 1}}})
    exportar(engine)
    vista = _leer_vista()
    assert vista["vigia"]["modo"] == "curado"
    assert vista["vigia"]["senales_activas"] == 1
    fila = next(t for t in vista["territorios"] if t["pcode"] == "27660C01")
    assert fila["procedencia"]["senales"] == 1
    assert fila["senales"][0]["url"] == "https://eltiempo.test/san-pedro"


def test_s3_01_ultima_pasada_ignora_runs_omitidos_por_cadencia(db, engine):
    pasada_real = dt.datetime(2026, 8, 15, 10, 0, tzinfo=dt.UTC)
    omitida = dt.datetime(2026, 8, 16, 10, 0, tzinfo=dt.UTC)
    db.add(VigiaRun(estado="ok", resumen={}, finished_at=pasada_real))
    db.add(VigiaRun(estado="omitido", resumen={"omitido_por_cadencia": True}, finished_at=omitida))
    db.commit()
    exportar(engine)
    vista = _leer_vista()
    assert vista["vigia"]["ultima_pasada"] == pasada_real.isoformat()


def test_s3_02_cero_senales_cero_reportes_no_vacio(db, engine):
    exportar(engine)
    vista = _leer_vista()
    assert vista["territorios"]
    assert all(t["alerta_maxima"] for t in vista["territorios"])
    assert vista["mensaje_alerta_ausencia"] == "sin información: eso ES la alerta"


def test_s3_02_curado_conserva_alerta_por_ausencia_aunque_haya_senales(db, engine):
    vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "San Pedro sigue sin agua.",
            "url": "https://eltiempo.test/san-pedro",
        },
        FUENTE,
    )
    exportar(engine)
    vista = _leer_vista()
    sin_senal = [t for t in vista["territorios"] if t["pcode"] != "27660C01"]
    assert sin_senal
    assert all(t["alerta_maxima"] for t in sin_senal)


def test_s3_03_mixto_reportes_como_capa_principal(db, engine, tmp_path):
    cfg = tmp_path / "vigia.yaml"
    cfg.write_text("vista_operativa:\n  modo: mixto\n")
    original = settings.vigia_config_path
    settings.vigia_config_path = str(cfg)
    try:
        vigia.registrar_senal(
            db,
            {
                "localidad_texto": "San Pedro, San José del Palmar",
                "categorias": ["agua"],
                "cita": "San Pedro sigue sin agua.",
                "url": "https://eltiempo.test/san-pedro",
            },
            FUENTE,
        )
        crear_evento(db, "need", payload={"pcode": "27660C01", "categorias": ["agua"]})
        exportar(engine)
    finally:
        settings.vigia_config_path = original
    fila = next(t for t in _leer_vista()["territorios"] if t["pcode"] == "27660C01")
    assert fila["procedencia"] == {"senales": 1, "reportes": 1}
    assert fila["senales"][0]["estado"] == "convertida"


def test_s3_04_y_s3_05_procedencia_y_evidencia_visible(db, engine):
    vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "San Pedro reporta falta de agua.",
            "url": "https://eltiempo.test/san-pedro",
            "fecha_publicacion": "2026-08-14",
        },
        FUENTE,
    )
    exportar(engine)
    fila = next(t for t in _leer_vista()["territorios"] if t["pcode"] == "27660C01")
    assert set(fila["procedencia"]) == {"senales", "reportes"}
    evidencia = fila["senales"][0]
    assert evidencia["cita"] == "San Pedro reporta falta de agua."
    assert evidencia["fuente"] == "Eltiempo"
    assert evidencia["fecha"] == "2026-08-14"
    assert evidencia["url"].startswith("https://")


def test_s3_06_html_operativo_autocontenido_y_escapado(db, engine):
    vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "<script>alert(1)</script> San Pedro reporta falta de agua.",
            "url": "https://eltiempo.test/san-pedro",
            "fecha_publicacion": "2026-08-14",
        },
        FUENTE,
    )
    exportar(engine)
    html = Path(settings.export_dir, "vista-operativa.html").read_text()
    assert "<title>Radar Operativo</title>" in html
    assert '<script id="datos" type="application/json">' in html
    assert "departamento" in html
    assert "procedencia" in html
    assert "<script>alert(1)</script>" not in html
    assert "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e" in html


def test_s3_06_vista_operativa_sin_pii_pin_ni_senales_no_publicables(db, engine):
    crear_evento(
        db,
        "need",
        payload={"pcode": "27660C01", "categorias": ["agua"], "pin": PIN_SAN_PEDRO},
        reporter_ref="ref-operativa-secreta",
    )
    revision = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "La Cabaña",
            "categorias": ["techo"],
            "cita": "La Cabaña pide techo retenido.",
            "url": "https://eltiempo.test/revision",
        },
        FUENTE,
    )
    descartada = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "Potrerito, Jamundí",
            "categorias": ["agua"],
            "cita": "Potrerito descartada por operador.",
            "url": "https://eltiempo.test/descartada",
        },
        FUENTE,
    )
    assert revision.estado == "revision"
    assert vigia.descartar_senal(db, descartada.id, "cmgrd")

    exportar(engine)
    contenido = Path(settings.export_dir, "vista-operativa.json").read_text()
    assert "ref-operativa-secreta" not in contenido
    assert hash_reporter("ref-operativa-secreta") not in contenido
    assert str(PIN_SAN_PEDRO["lat"]) not in contenido
    assert str(PIN_SAN_PEDRO["lon"]) not in contenido
    assert "La Cabaña pide techo retenido" not in contenido
    assert "Potrerito descartada por operador" not in contenido


def test_internal_run_jobs_y_descartar_senal(client, db):
    senal = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "San Pedro reporta falta de agua.",
            "url": "https://eltiempo.test/san-pedro",
        },
        FUENTE,
    )
    run = client.post("/internal/run_jobs", headers=AUTH)
    assert run.status_code == 200
    assert run.json()["vigia"]["run_id"]
    assert run.json()["vigia"]["estado"] in {"ok", "parcial", "omitido"}
    invalida = client.post("/internal/senales/no-es-uuid/descartar", headers=AUTH, json={"operador": "cmgrd"})
    assert invalida.status_code == 200
    assert invalida.json() == {"ok": False}
    descarte = client.post(f"/internal/senales/{senal.id}/descartar", headers=AUTH, json={"operador": "cmgrd"})
    assert descarte.status_code == 200
    assert descarte.json() == {"ok": True}
