"""U-01..U-21 — folios, append-only en la capa de persistencia, idempotencia."""

import re

import pytest
from sqlalchemy.exc import DBAPIError

from radar_core.folios import generar_folio, normalizar_folio
from tests.conftest import crear_evento

pytestmark = pytest.mark.unit


class TestFolios:
    def test_u01_formato_y_unicidad(self, db):
        folios = [generar_folio(db, t) for t in ("need", "dispatch", "receipt")] + [
            generar_folio(db, "dispatch") for _ in range(20)
        ]
        for f in folios:
            assert re.fullmatch(r"(NE|DS|RC)-\d{4,}", f), f
        assert len(set(folios)) == len(folios)

    def test_u02_parseo_tolerante_al_dictado(self):
        assert normalizar_folio("DS-0392") == "DS-0392"
        assert normalizar_folio("ds 0392") == "DS-0392"
        assert normalizar_folio("ds0392") == "DS-0392"
        assert normalizar_folio("  rc - 1204 ") == "RC-1204"
        assert normalizar_folio("XX-1") is None
        assert normalizar_folio("basura") is None
        assert normalizar_folio("") is None


class TestAppendOnly:
    def test_u10_correccion_es_evento_nuevo(self, db):
        original = crear_evento(db, "receipt")["folio"]
        correccion = crear_evento(
            db, "receipt", payload={"corrige_folio": original, "hogares": 30}
        )
        assert correccion["folio"] != original
        from sqlalchemy import select
        from radar_core.models import Event

        filas = db.execute(select(Event).order_by(Event.created_at)).scalars().all()
        assert len(filas) == 2
        assert filas[1].corrige_folio == original
        # el original sigue intacto
        assert filas[0].folio == original
        assert filas[0].payload["hogares"] == 28

    def test_u10_delete_via_orm_rechazado(self, db):
        crear_evento(db, "receipt")
        from sqlalchemy import select
        from radar_core.models import Event

        evento = db.execute(select(Event)).scalars().first()
        db.delete(evento)
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()


class TestIdempotencia:
    def test_u20_misma_key_mismo_folio_sin_duplicar(self, db):
        r1 = crear_evento(db, "receipt", key="conv-1:paso-7")
        r2 = crear_evento(db, "receipt", key="conv-1:paso-7")
        assert r1["folio"] == r2["folio"]
        from sqlalchemy import func, select
        from radar_core.models import Event

        assert db.execute(select(func.count()).select_from(Event)).scalar_one() == 1

    def test_u20_key_nueva_inserta(self, db):
        r1 = crear_evento(db, "receipt", key="conv-1:paso-7")
        r2 = crear_evento(db, "receipt", key="conv-2:paso-7")
        assert r1["folio"] != r2["folio"]

    def test_u21_misma_key_payload_distinto_warning(self, db):
        r1 = crear_evento(db, "receipt", key="conv-9", payload={"hogares": 28})
        r2 = crear_evento(db, "receipt", key="conv-9", payload={"hogares": 99})
        assert r2["folio"] == r1["folio"]
        assert any(w["codigo"] == "idempotency_payload_distinto" for w in r2["warnings"])
        from sqlalchemy import func, select
        from radar_core.models import Event

        assert db.execute(select(func.count()).select_from(Event)).scalar_one() == 1
