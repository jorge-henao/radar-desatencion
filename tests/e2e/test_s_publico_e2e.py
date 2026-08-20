"""S-30..S-42 — salida pública para consumidores externos y ciclos punta a punta."""

import csv
import datetime as dt
import io
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from radar_core import db as db_mod
from radar_core.config import settings
from radar_core.security import hash_reporter
from radar_core.services.actas import qr_payload
from radar_core.services.export import COLUMNAS, HXL_TAGS, exportar
from radar_core.services.reconciliacion import reconciliar
from tests.conftest import AUTH, PIN_SAN_PEDRO, crear_evento, insertar_evento_directo

pytestmark = pytest.mark.service


def _export_dir() -> Path:
    return Path(settings.export_dir)


class TestSalidaPublica:
    def test_s30_auditoria_pii_en_los_tres_artefactos(self, db):
        crear_evento(db, "receipt", reporter_ref="ref-super-secreta")
        crear_evento(db, "need", reporter_ref="ref-super-secreta", key="k2")
        exportar(db_mod.engine())
        prohibidos = [
            "ref-super-secreta",
            hash_reporter("ref-super-secreta"),
            str(PIN_SAN_PEDRO["lat"]),
            str(PIN_SAN_PEDRO["lon"]),
            settings.reporter_salt,
            "+573001112233",
        ]
        for archivo in ("datos.csv", "datos.geojson", "tabla.html", "meta.json"):
            contenido = (_export_dir() / archivo).read_text(errors="replace")
            for p in prohibidos:
                assert p not in contenido, f"'{p}' filtrado en {archivo}"

    def test_s31_csv_parseable_hxl_y_completo(self, db, client):
        exportar(db_mod.engine())
        r = client.get("/public/datos.csv")
        assert r.status_code == 200
        filas = list(csv.reader(io.StringIO(r.text)))
        assert filas[0] == COLUMNAS
        assert filas[1] == HXL_TAGS
        pcodes = {f[0] for f in filas[2:]}
        # todos los priorizados presentes, incluidos los de alerta_maxima
        assert {"27660C01", "76364V01", "27660", "76364", "76364001"} <= pcodes

    def test_s32_geojson_renderizable(self, db, client):
        exportar(db_mod.engine())
        fc = json.loads(client.get("/public/datos.geojson").text)
        assert fc["type"] == "FeatureCollection"
        con_geometria = [f for f in fc["features"] if f["geometry"]]
        assert con_geometria, "features con geometría para el visor"
        for f in con_geometria:
            assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
            assert f["properties"]["pcode"]

    def test_s33_frescura_del_export(self, db, client):
        exportar(db_mod.engine())
        meta = json.loads(client.get("/public/meta.json").text)
        generado = dt.datetime.fromisoformat(meta["generado_el"])
        assert (dt.datetime.now(dt.UTC) - generado).total_seconds() < 300
        assert meta["generado_el"] in client.get("/public/tabla.html").text

    def test_s34_qr_del_acta_apunta_al_canal(self, db, client):
        folio = crear_evento(db, "dispatch")["folio"]
        payload = qr_payload(folio)
        assert payload.startswith("https://wa.me/")
        assert f"text={folio}" in payload
        consulta = client.get(f"/tools/consultar_folio?folio={folio}", headers=AUTH).json()
        assert consulta["existe"] is True


class TestPuntaAPunta:
    def test_s40_ciclo_completo_del_storyboard(self, db, client):
        """dispatch (acta) → receipt citando folio → reconciliación → export."""
        # San Pedro arranca en alerta máxima
        exportar(db_mod.engine())
        antes = json.loads((_export_dir() / "datos.geojson").read_text())
        estado_antes = next(
            f["properties"] for f in antes["features"] if f["properties"]["pcode"] == "27660C01"
        )
        assert estado_antes["estado"] == "alerta_maxima"

        # Paso 4: la coordinadora declara el despacho
        ds = client.post(
            "/tools/crear_evento",
            json={
                "type": "dispatch",
                "payload": {
                    "pcode": "27660C01",
                    "items": [
                        {"categoria": "alimentos", "cantidad": 80, "unidad": "kits"},
                        {"categoria": "agua", "cantidad": 120, "unidad": "bidones"},
                    ],
                },
                "reporter_ref": "ref-fundacion",
                "idempotency_key": "sb-4",
            },
            headers=AUTH,
        ).json()
        assert ds["acta_url"]

        # Paso 6: el presidente de la JAC confirma con el acta en la mano
        rc = client.post(
            "/tools/crear_evento",
            json={
                "type": "receipt",
                "payload": {
                    "folio_citado": ds["folio"].lower().replace("-", " "),
                    "pcode": "27660C01",
                    "categorias": ["agua", "alimentos"],
                    "hogares": 28,
                    "pin": PIN_SAN_PEDRO,
                },
                "reporter_ref": "ref-jac",
                "idempotency_key": "sb-6",
            },
            headers=AUTH,
        ).json()

        # Paso 7: reconciliación y cierre
        resultado = reconciliar(db)
        assert resultado["deterministicos"] == 1
        exportar(db_mod.engine())
        despues = json.loads((_export_dir() / "datos.geojson").read_text())
        estado_despues = next(
            f["properties"] for f in despues["features"] if f["properties"]["pcode"] == "27660C01"
        )
        assert estado_despues["estado"] == "con_registro"
        assert estado_despues["dias_sin_recepcion"] == 0, "el contador de San Pedro vuelve a cero"

        consulta = client.get(f"/tools/consultar_folio?folio={ds['folio']}", headers=AUTH).json()
        assert consulta["estado"] == "reconciliado"
        comprobante = client.get(f"/comprobantes/{ds['folio']}.pdf")
        assert comprobante.status_code == 200
        assert comprobante.content.startswith(b"%PDF")
        assert rc["folio"].startswith("RC-")

    def test_s41_ciclo_voz_con_desambiguacion(self, db, client):
        r1 = client.post("/tools/resolver_ubicacion", json={"texto": "la cabaña"}, headers=AUTH).json()
        assert r1["pcode"] is None and len(r1["candidatos"]) >= 2
        # el agente repregunta y el usuario confirma "la de Jamundí"
        r2 = client.post(
            "/tools/resolver_ubicacion", json={"texto": "la cabaña de jamundí"}, headers=AUTH
        ).json()
        assert r2["pcode"] == "76364V01"
        rc = client.post(
            "/tools/crear_evento",
            json={
                "type": "receipt",
                "payload": {"pcode": r2["pcode"], "categorias": ["agua"], "hogares": 12},
                "reporter_ref": "ref-promotora",
                "idempotency_key": "voz-1",
            },
            headers=AUTH,
        ).json()
        assert rc["folio"].startswith("RC-")
        exportar(db_mod.engine())
        fila = db.execute(
            text("SELECT estado FROM mv_desatencion WHERE pcode = '76364V01'")
        ).scalar_one()
        assert fila == "con_registro"

    def test_s42_correccion_reflejada_log_intacto(self, db):
        # receipt registrado en el pcode equivocado hace 3 días
        equivocado = insertar_evento_directo(
            db, tipo="receipt", pcode="76364001",
            payload={"pcode": "76364001", "categorias": ["agua"], "hogares": 10}, hace_dias=3,
        )
        # corrección: era en San Pedro
        crear_evento(
            db, "receipt",
            payload={"pcode": "27660C01", "corrige_folio": equivocado, "categorias": ["agua"], "hogares": 10},
        )
        exportar(db_mod.engine())
        filas = {
            f["pcode"]: f
            for f in [
                dict(r)
                for r in db.execute(text("SELECT pcode, estado FROM mv_desatencion")).mappings().all()
            ]
        }
        assert filas["27660C01"]["estado"] == "con_registro"
        assert filas["76364001"]["estado"] == "alerta_maxima", "el evento corregido ya no cuenta ahí"
        n = db.execute(text("SELECT count(*) FROM events")).scalar_one()
        assert n == 2, "el log conserva ambos eventos: nunca se toca"
