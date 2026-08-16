import json
import pytest
from pathlib import Path
import httpx
from sqlalchemy import select

from radar_core.config import settings
from radar_core.models import Event, LocalidadPorIncorporar, SenalMedio, VigiaDocumento
from radar_core.services import vigia
from radar_core.services.export import exportar

pytestmark = pytest.mark.integration


FUENTE = vigia.FuenteVigia(id="ungrd", url="https://ungrd.test", tipo="oficial", confianza=0.95)


def test_i3_01_conciliacion_y_cola_de_localidades(db):
    visible = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "San Pedro reporta necesidad urgente de agua.",
            "url": "https://ungrd.test/1",
        },
        FUENTE,
    )
    retenida = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "La Cabaña",
            "categorias": ["techo"],
            "cita": "La Cabaña pide materiales para techo.",
            "url": "https://ungrd.test/2",
        },
        FUENTE,
    )
    sin_match = vigia.registrar_senal(
        db,
        {
            "localidad_texto": "caserio sin coordenadas",
            "categorias": ["alimentos"],
            "cita": "El caserio sin coordenadas solicita alimentos.",
            "url": "https://ungrd.test/3",
        },
        FUENTE,
    )
    assert visible.pcode == "27660C01"
    assert retenida.estado == "revision"
    assert retenida.pcode is None
    assert sin_match is None
    principales = db.execute(select(SenalMedio).where(SenalMedio.estado == "activa")).scalars().all()
    assert [s.pcode for s in principales] == ["27660C01"]
    assert db.execute(select(LocalidadPorIncorporar)).scalars().all()


def test_i3_03_frontera_con_log_y_export_auditoria(db, engine):
    vigia.registrar_senal(
        db,
        {
            "localidad_texto": "San Pedro, San José del Palmar",
            "categorias": ["agua"],
            "cita": "San Pedro reporta necesidad urgente de agua.",
            "url": "https://ungrd.test/1",
        },
        FUENTE,
    )
    assert db.execute(select(Event)).scalars().all() == []
    exportar(engine)
    csv_publico = Path(settings.export_dir, "datos.csv").read_text()
    assert "ungrd.test" not in csv_publico


def test_i3_04_run_completo_con_fuente_fixture(db):
    cfg = vigia.ConfigVigia(fuentes=(FUENTE,))
    llm = vigia.LLMVigiaConfig(provider="openai", model="gpt-test", api_key="sk-test")

    def handler(request):
        if str(request.url) == "https://ungrd.test":
            return httpx.Response(200, text="San Pedro, San José del Palmar, reporta necesidad urgente de agua.")
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "senales": [
                            {
                                "localidad_texto": "San Pedro, San José del Palmar",
                                "categorias": ["agua"],
                                "cita": "San Pedro reporta necesidad urgente de agua.",
                                "fecha_publicacion": "2026-08-14",
                            }
                        ]
                    }
                )
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = vigia.ejecutar_vigia(db, config=cfg, client=client, llm_config=llm, forzar=True)

    assert run.estado == "ok"
    assert run.resumen["procesadas"] == 1
    assert run.resumen["senales_extraidas"] == 1
    assert run.resumen["senales_persistidas"] == 1
    assert db.execute(select(SenalMedio).where(SenalMedio.fuente_id == "ungrd")).scalars().one()
    assert db.execute(select(VigiaDocumento).where(VigiaDocumento.fuente_id == "ungrd")).scalars().one()
    assert vigia.ultima_pasada(db) == run.finished_at

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        segunda = vigia.ejecutar_vigia(db, config=cfg, client=client, llm_config=llm, forzar=True)
    assert segunda.resumen["omitidas_por_hash"] == 1

    omitida = vigia.ejecutar_vigia(db, config=cfg, llm_config=llm)
    assert omitida.estado == "omitido"
    assert omitida.resumen["omitido_por_cadencia"] is True


def test_i3_05_fuente_caida_queda_en_log_sin_abortar(db):
    fuente_ok = FUENTE
    fuente_caida = vigia.FuenteVigia(id="medio_caido", url="https://caido.test", confianza=0.7)
    cfg = vigia.ConfigVigia(fuentes=(fuente_ok, fuente_caida))
    llm = vigia.LLMVigiaConfig(provider="openai", model="gpt-test", api_key="sk-test")

    def handler(request):
        if str(request.url) == "https://caido.test":
            return httpx.Response(503, text="no disponible")
        if str(request.url) == "https://ungrd.test":
            return httpx.Response(200, text="San Pedro reporta necesidad urgente de agua.")
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "senales": [
                            {
                                "localidad_texto": "San Pedro, San José del Palmar",
                                "categorias": ["agua"],
                                "cita": "San Pedro reporta necesidad urgente de agua.",
                            }
                        ]
                    }
                )
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = vigia.ejecutar_vigia(db, config=cfg, client=client, llm_config=llm, forzar=True)

    assert run.estado == "parcial"
    assert run.resumen["fuentes"]["medio_caido"]["error"]
    assert run.resumen["fuentes"]["ungrd"]["persistidas"] == 1


def test_i3_05_sin_api_key_degrada_sin_abortar(db):
    cfg = vigia.ConfigVigia(fuentes=(FUENTE,))
    run = vigia.ejecutar_vigia(db, config=cfg)
    assert run.estado == "parcial"
    assert "Falta configurar" in run.resumen["error"]
