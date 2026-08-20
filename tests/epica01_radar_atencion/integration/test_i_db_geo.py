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
from radar_core.services.geo import resolver_pin, resolver_texto

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

    def test_i13_toda_ubicacion_resuelta_trae_su_procedencia(self, db):
        """Invariante: si hay pcode, hay municipio. Un municipio es su propio municipio.

        Vale para la respuesta y para cada candidato, en los dos modos. Sin esto
        el agente recibe "La Pedrera, vereda" sin poder decir de qué municipio,
        que es justo lo único que sirve para desambiguar por voz.
        """
        respuestas = [
            resolver_pin(db, **PIN_JAMUNDI),      # municipio: se apunta a sí mismo
            resolver_pin(db, **PIN_POTRERITO),    # centro poblado
            resolver_pin(db, **PIN_SAN_PEDRO),
            resolver_texto("La Cabaña, Jamundí"),  # vereda por texto
            resolver_texto("Jamundí"),
        ]
        for r in respuestas:
            assert r["pcode"] is not None, r
            for u in [r] + r["candidatos"]:
                assert u["municipio_pcode"], f"sin municipio: {u}"
                assert u["municipio_nombre"], f"sin nombre de municipio: {u}"
                assert u["departamento_nombre"], f"sin departamento: {u}"
                assert u["departamento_codigo"] == u["municipio_pcode"][:2]
                assert u["etiqueta"] and u["nombre_oficial"] in u["etiqueta"]

    def test_i13_un_municipio_es_su_propio_municipio(self, db):
        r = resolver_pin(db, **PIN_JAMUNDI)
        assert r["nivel"] == "municipio"
        assert r["municipio_pcode"] == r["pcode"] == "76364"
        assert r["municipio_nombre"] == "Jamundí"

    def test_i13_sin_ubicacion_la_procedencia_va_entera_en_null(self, db):
        """Nunca a medias: no existe departamento poblado con municipio en null."""
        for r in (resolver_pin(db, **PIN_MAR), resolver_texto("asdfgh qwerty"),
                  resolver_texto("La Cabaña")):
            assert r["pcode"] is None
            assert r["municipio_pcode"] is None
            assert r["municipio_nombre"] is None
            assert r["departamento_codigo"] is None
            assert r["departamento_nombre"] is None
            assert r["etiqueta"] is None

    def test_i14_pin_y_texto_coinciden_para_el_mismo_territorio(self, db):
        """Los dos modos leen de fuentes distintas y deben converger.

        Pin resuelve contra geo_divipola; texto contra el índice en memoria del
        gazetteer. Si divergen, el mismo lugar tiene dos procedencias según cómo
        se pregunte.
        """
        por_pin = resolver_pin(db, **PIN_SAN_PEDRO)
        por_texto = resolver_texto("corregimiento San Pedro")
        assert por_pin["pcode"] == por_texto["pcode"] == "27660C01"
        for campo in ("municipio_pcode", "municipio_nombre",
                      "departamento_codigo", "departamento_nombre"):
            assert por_pin[campo] == por_texto[campo], campo

    def test_i15_priorizado_sin_eventos_en_alerta(self, db):
        from radar_core import ddl

        ddl.refresh_mvs(db_mod.engine(), concurrently=False)
        filas = db.execute(
            text("SELECT pcode, estado FROM mv_desatencion WHERE estado = 'alerta_maxima'")
        ).mappings().all()
        assert {"27660C01", "76364V01"} <= {f["pcode"] for f in filas}
