"""I-01..I-15 — base de datos y resolución geográfica contra PostGIS real."""

import threading
import uuid

import pytest
from sqlalchemy import text

from radar_core import db as db_mod
from tests.conftest import (
    PIN_JAMUNDI,
    PIN_MAR,
    PIN_POTRERITO,
    PIN_SAN_PEDRO,
    crear_evento,
    insertar_evento_directo,
)
from radar_core.seed.loader import cargar_territorio
from radar_core.services.geo import resolver_pin

pytestmark = pytest.mark.integration


class TestAppendOnlyEnDB:
    def test_i01_update_bloqueado_por_trigger(self, db):
        crear_evento(db, "receipt")
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("UPDATE events SET pcode = 'hackeado'"))
        db.rollback()

    def test_i01_delete_bloqueado_por_trigger(self, db):
        crear_evento(db, "receipt")
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("DELETE FROM events"))
        db.rollback()

    def test_i02_correccion_referencia_original_intacto(self, db):
        original = crear_evento(db, "receipt", payload={"hogares": 28})["folio"]
        crear_evento(db, "receipt", payload={"corrige_folio": original, "hogares": 30})
        filas = db.execute(
            text("SELECT folio, corrige_folio, payload->>'hogares' AS hogares FROM events ORDER BY created_at")
        ).mappings().all()
        assert len(filas) == 2
        assert filas[0]["hogares"] == "28"
        assert filas[1]["corrige_folio"] == original

    def test_i03_geometria_invalida_se_sanea_al_ingestar(self, db):
        # Polígono "moño" auto-intersecado, típico de shapefiles con errores
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
        }
        cargar_territorio(
            db, pcode="TEST-INV", nombre="Inválido", nivel="municipio", geometria=bowtie
        )
        db.commit()
        try:
            valido = db.execute(
                text("SELECT ST_IsValid(geom::geometry) FROM geo_divipola WHERE pcode = 'TEST-INV'")
            ).scalar_one()
            assert valido is True, "ST_MakeValid debe aplicarse al ingestar, no en query time"
        finally:
            db.execute(text("DELETE FROM geo_divipola WHERE pcode = 'TEST-INV'"))
            db.commit()

    def test_i05_carrera_misma_key_un_solo_evento(self, db):
        key = f"carrera-{uuid.uuid4()}"
        resultados, errores = [], []

        def worker():
            factory = db_mod.session_factory()
            try:
                with factory() as s:
                    resultados.append(crear_evento(s, "receipt", key=key))
            except Exception as e:  # noqa: BLE001
                errores.append(e)

        hilos = [threading.Thread(target=worker) for _ in range(8)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]

        assert not errores
        assert len({r["folio"] for r in resultados}) == 1
        n = db.execute(text("SELECT count(*) FROM events WHERE idempotency_key = :k"), {"k": key}).scalar_one()
        assert n == 1, "el constraint único en DB es la garantía, no el check de aplicación"


class TestResolucionGeo:
    def test_i10_pin_en_municipio(self, db):
        r = resolver_pin(db, **PIN_JAMUNDI)
        assert r["pcode"] == "76364"
        assert r["nivel"] == "municipio"
        assert r["confianza"] == 1.0

    def test_i11_gana_el_nivel_mas_especifico(self, db):
        # Potrerito está dentro del polígono de Jamundí: debe ganar el centro poblado
        r = resolver_pin(db, **PIN_POTRERITO)
        assert r["pcode"] == "76364001"
        assert r["nivel"] == "centro_poblado"
        pcodes = {c["pcode"] for c in r["candidatos"]}
        assert "76364" in pcodes, "el municipio contenedor queda como candidato"

    def test_i11_pin_del_storyboard_en_san_pedro(self, db):
        r = resolver_pin(db, **PIN_SAN_PEDRO)
        assert r["pcode"] == "27660C01"

    def test_i12_fuera_de_cobertura_estructurado(self, db):
        r = resolver_pin(db, **PIN_MAR)
        assert r["pcode"] is None
        assert r["motivo"] == "fuera_de_cobertura"
        assert r["candidatos"] == []

    def test_i15_priorizado_sin_eventos_en_alerta(self, db):
        from radar_core import ddl

        ddl.refresh_mvs(db_mod.engine(), concurrently=False)
        filas = db.execute(
            text("SELECT pcode, estado FROM mv_desatencion WHERE estado = 'alerta_maxima'")
        ).mappings().all()
        assert {"27660C01", "76364V01"} <= {f["pcode"] for f in filas}
