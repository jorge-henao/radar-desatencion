"""I-20..I-32 — export estático, notificador y actas."""

import csv
import io
import json

import httpx
import pytest
from sqlalchemy import create_engine, select

from radar_core import db as db_mod
from radar_core.config import settings
from radar_core.models import Notificacion
from radar_core.services.export import COLUMNAS, exportar
from radar_core.services.notificador import procesar_outbox
from radar_core.services.reconciliacion import reconciliar
from tests.conftest import PIN_SAN_PEDRO, crear_evento

pytestmark = pytest.mark.integration


def _leer(nombre):
    from pathlib import Path

    return (Path(settings.export_dir) / nombre).read_bytes()


class TestExport:
    def test_i20_solo_agregados_cero_pii(self, db):
        crear_evento(db, "receipt", reporter_ref="ref-secreta-777")
        exportar(db_mod.engine())
        for archivo in ("datos.csv", "datos.geojson", "tabla.html"):
            contenido = _leer(archivo).decode("utf-8", errors="replace")
            assert str(PIN_SAN_PEDRO["lat"]) not in contenido, f"pin exacto en {archivo}"
            assert str(PIN_SAN_PEDRO["lon"]) not in contenido, f"pin exacto en {archivo}"
            assert "ref-secreta-777" not in contenido
            from radar_core.security import hash_reporter

            assert hash_reporter("ref-secreta-777") not in contenido, f"reporter_hash en {archivo}"

    def test_i21_geojson_valido_un_feature_por_pcode(self, db):
        exportar(db_mod.engine())
        fc = json.loads(_leer("datos.geojson"))
        assert fc["type"] == "FeatureCollection"
        pcodes = [f["properties"]["pcode"] for f in fc["features"]]
        assert len(pcodes) == len(set(pcodes))
        assert "27660C01" in pcodes
        for f in fc["features"]:
            assert set(COLUMNAS) <= set(f["properties"].keys())

    def test_i22_db_caida_no_publica_corrupto(self, db):
        exportar(db_mod.engine())
        antes = _leer("datos.csv")
        engine_muerto = create_engine(
            "postgresql+psycopg://postgres:radar@localhost:9/nada",
            connect_args={"connect_timeout": 1},
        )
        with pytest.raises(Exception):
            exportar(engine_muerto, refresh=False)
        assert _leer("datos.csv") == antes, "el export anterior sigue sirviéndose intacto"

    def test_i23_columnas_estables_entre_corridas(self, db):
        exportar(db_mod.engine())
        primera = next(csv.reader(io.StringIO(_leer("datos.csv").decode())))
        crear_evento(db, "receipt")
        exportar(db_mod.engine())
        segunda = next(csv.reader(io.StringIO(_leer("datos.csv").decode())))
        assert primera == segunda == COLUMNAS


class TestNotificador:
    def _transport_capturador(self, capturadas, fallos_iniciales=0):
        estado = {"intentos": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            estado["intentos"] += 1
            if estado["intentos"] <= fallos_iniciales:
                return httpx.Response(503)
            capturadas.append(json.loads(request.content))
            return httpx.Response(200)

        return httpx.MockTransport(handler)

    def test_i30_comprobante_por_salida_proactiva_con_ref_opaca(self, db):
        ds = crear_evento(db, "dispatch", reporter_ref="ref-fundacion")["folio"]
        crear_evento(db, "receipt", payload={"folio_citado": ds})
        reconciliar(db)

        capturadas = []
        r = procesar_outbox(db, transport=self._transport_capturador(capturadas))
        assert r["enviadas"] == 1
        cuerpo = capturadas[0]
        assert cuerpo["plantilla"] == "comprobante_listo"
        assert cuerpo["reporter_ref"] == "ref-fundacion", "la plataforma resuelve ref→teléfono, no el Core"
        assert cuerpo["adjunto_url"].endswith(f"/comprobantes/{ds}.pdf")
        assert "telefono" not in json.dumps(cuerpo)

    def test_i31_reintento_con_backoff_sin_perder_ni_duplicar(self, db):
        ds = crear_evento(db, "dispatch", reporter_ref="ref-x")["folio"]
        crear_evento(db, "receipt", payload={"folio_citado": ds})
        reconciliar(db)

        capturadas = []
        procesar_outbox(db, transport=self._transport_capturador(capturadas, fallos_iniciales=2))
        assert len(capturadas) == 1, "exactamente una entrega exitosa"
        notif = db.execute(
            select(Notificacion).where(Notificacion.plantilla == "comprobante_listo")
        ).scalars().one()
        assert notif.estado == "enviada"
        assert notif.intentos == 3

        # una segunda pasada no reenvía
        procesar_outbox(db, transport=self._transport_capturador(capturadas))
        assert len(capturadas) == 1

    def test_i31_agotados_los_intentos_queda_fallida(self, db):
        ds = crear_evento(db, "dispatch", reporter_ref="ref-x")["folio"]
        crear_evento(db, "receipt", payload={"folio_citado": ds})
        reconciliar(db)
        procesar_outbox(db, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        notif = db.execute(
            select(Notificacion).where(Notificacion.plantilla == "comprobante_listo")
        ).scalars().one()
        assert notif.estado == "fallida"


class TestActas:
    def test_i32_acta_pdf_accesible(self, db, client):
        from tests.conftest import AUTH

        resp = client.post(
            "/tools/crear_evento",
            json={
                "type": "dispatch",
                "payload": {
                    "pcode": "27660C01",
                    "items": [{"categoria": "agua", "cantidad": 120, "unidad": "bidones"}],
                },
                "reporter_ref": "ref-org",
                "idempotency_key": "acta-i32",
            },
            headers=AUTH,
        )
        acta_url = resp.json()["acta_url"]
        assert acta_url
        descarga = client.get(acta_url.replace("http://testserver", ""))
        assert descarga.status_code == 200
        assert descarga.content.startswith(b"%PDF")
