"""X-01..X-08 — seguridad y privacidad. El contexto lo exige: conflicto armado,
suplantación activa y falsos censos documentados en la investigación."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text

from radar_core import db as db_mod
from radar_core.config import settings
from radar_core.models import Base, AlertaInterna
from radar_core.security import hash_reporter
from radar_core.seed.loader import cargar_gazetteer, cargar_territorio
from radar_core.services.export import exportar
from radar_core.services.gazetteer import gazetteer
from radar_core.services.notificador import procesar_outbox
from radar_core.services.reconciliacion import reconciliar
from tests.conftest import AUTH, PIN_SAN_PEDRO, crear_evento

pytestmark = pytest.mark.transversal

_CUERPO = {
    "type": "receipt",
    "payload": {"pcode": "27660C01", "categorias": ["agua"], "hogares": 28, "pin": PIN_SAN_PEDRO},
    "reporter_ref": "ref-confidencial-999",
    "idempotency_key": "x-test-1",
}


class TestEsquemaSinPII:
    PROHIBIDAS = ("telefono", "phone", "celular", "cedula", "documento", "email", "correo", "reporter_ref")

    def test_x01_ninguna_columna_capaz_de_pii(self):
        for tabla in Base.metadata.tables.values():
            for col in tabla.columns:
                assert col.name not in self.PROHIBIDAS, f"{tabla.name}.{col.name}"

    def test_x01_la_ref_no_se_persiste_en_claro(self, db):
        crear_evento(db, "dispatch", reporter_ref="ref-confidencial-999")
        for tabla in ("events", "notificaciones"):
            filas = db.execute(text(f"SELECT to_json(t) FROM {tabla} t")).scalars().all()
            volcado = json.dumps(filas, default=str)
            assert "ref-confidencial-999" not in volcado, f"ref en claro en {tabla}"

    def test_x02_logs_sin_ref_ni_coordenadas(self, client, caplog):
        with caplog.at_level(logging.DEBUG):
            client.post("/tools/crear_evento", json=_CUERPO, headers=AUTH)
        texto = caplog.text
        assert "ref-confidencial-999" not in texto
        assert str(PIN_SAN_PEDRO["lat"]) not in texto
        assert str(PIN_SAN_PEDRO["lon"]) not in texto

    def test_x03_hash_irreversible_sin_tabla_de_mapeo(self, db):
        # no existe ninguna tabla cuyo contenido permita volver del hash a la ref
        h = hash_reporter("ref-confidencial-999")
        assert "ref-confidencial-999" not in h
        nombres = {t.name for t in Base.metadata.tables.values()}
        assert not any("ref" in n and "map" in n for n in nombres)
        # y el salt no está en la salida pública
        exportar(db_mod.engine())
        for archivo in Path(settings.export_dir).glob("*"):
            assert settings.reporter_salt not in archivo.read_text(errors="replace")

    def test_x04_errores_sin_detalles_internos(self, client):
        r = client.post(
            "/tools/crear_evento",
            json={**_CUERPO, "payload": {**_CUERPO["payload"], "hogares": "x"}},
            headers=AUTH,
        )
        cuerpo = r.text.lower()
        for filtrado in ("traceback", "sqlalchemy", "psycopg", "file \"", "select "):
            assert filtrado not in cuerpo

    def test_x04_500_generico(self, app, db):
        from fastapi.testclient import TestClient

        @app.get("/_boom")
        def _boom():
            raise RuntimeError("secreto interno: password=hunter2")

        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/_boom")
        assert r.status_code == 500
        assert "hunter2" not in r.text
        assert "Traceback" not in r.text
        assert r.json()["errores"][0]["codigo"] == "error_interno"

    def test_x05_el_pin_solo_vive_en_la_zona_privada(self, db, client):
        # evento con pin exacto
        client.post("/tools/crear_evento", json=_CUERPO, headers=AUTH)
        ds = crear_evento(db, "dispatch", reporter_ref="ref-org")["folio"]
        crear_evento(db, "receipt", payload={"folio_citado": ds, "pin": PIN_SAN_PEDRO}, key="x5b")
        reconciliar(db)
        exportar(db_mod.engine())

        lat, lon = str(PIN_SAN_PEDRO["lat"]), str(PIN_SAN_PEDRO["lon"])
        # export público
        for archivo in Path(settings.export_dir).glob("*"):
            contenido = archivo.read_text(errors="replace")
            assert lat not in contenido and lon not in contenido, archivo.name
        # acta y comprobante
        acta = client.get(f"/actas/{ds}.pdf").content
        comprobante = client.get(f"/comprobantes/{ds}.pdf").content
        for pdf in (acta, comprobante):
            assert lat.encode() not in pdf and lon.encode() not in pdf
        # cuerpo del notify
        capturadas = []

        def handler(request):
            capturadas.append(request.content.decode())
            return httpx.Response(200)

        procesar_outbox(db, transport=httpx.MockTransport(handler))
        for c in capturadas:
            assert lat not in c and lon not in c

    def test_x06_rotacion_de_tokens_en_caliente(self, client):
        original = settings.workspace_tokens
        try:
            settings.rotate_tokens("token-nuevo")
            viejo = client.get("/tools/consultar_folio?folio=DS-1", headers=AUTH)
            assert viejo.status_code == 401
            nuevo = client.get(
                "/tools/consultar_folio?folio=DS-1", headers={"Authorization": "Bearer token-nuevo"}
            )
            assert nuevo.status_code == 200
        finally:
            settings.rotate_tokens(original)

    def test_x06_el_token_no_habilita_lectura_masiva(self, client):
        for ruta in ("/tools/eventos", "/events", "/tools/events", "/api/events"):
            assert client.get(ruta, headers=AUTH).status_code in (404, 405), ruta

    def test_x07_inyeccion_sql_parametrizada(self, client, db):
        r = client.post(
            "/tools/resolver_ubicacion",
            json={"texto": "'; DROP TABLE events; --"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert db.execute(text("SELECT count(*) FROM events")).scalar_one() == 0  # la tabla sigue viva

    def test_x07_html_escapado_en_el_export(self, db):
        cargar_territorio(
            db, pcode="XSS-1", nombre="<script>alert(1)</script>Pueblo", nivel="municipio",
            geometria=None, priorizado=True,
        )
        db.commit()
        try:
            exportar(db_mod.engine())
            html = (Path(settings.export_dir) / "tabla.html").read_text()
            assert "<script>alert(1)</script>" not in html
            assert "&lt;script&gt;" in html
        finally:
            db.execute(text("DELETE FROM geo_divipola WHERE pcode = 'XSS-1'"))
            db.commit()
            exportar(db_mod.engine())

    def test_x08_patron_coordinado_alerta_sin_bloquear(self, db):
        payload = {"pcode": "27660C01", "categorias": ["agua"], "hogares_rango": "6-20"}
        for i in range(settings.patron_coordinado_min_eventos):
            r = crear_evento(db, "need", payload=payload, reporter_ref=f"ref-bot-{i}", key=f"coord-{i}")
            assert r["folio"], "nunca se bloquea automáticamente"
        alertas = db.execute(
            select(AlertaInterna).where(AlertaInterna.tipo == "patron_coordinado")
        ).scalars().all()
        assert alertas, "la ráfaga idéntica desde hashes distintos genera alerta interna"
