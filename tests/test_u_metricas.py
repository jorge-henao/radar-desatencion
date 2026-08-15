"""U-40..U-42 — métrica de desatención. El silencio es el dato."""

import pytest
from sqlalchemy import text

from radar_core import ddl
from radar_core import db as db_mod
from tests.conftest import insertar_evento_directo

pytestmark = pytest.mark.unit


def _mv(db, pcode):
    ddl.refresh_mvs(db_mod.engine(), concurrently=False)
    fila = db.execute(
        text("SELECT * FROM mv_desatencion WHERE pcode = :p"), {"p": pcode}
    ).mappings().first()
    return fila


RECEIPT_PAYLOAD = {"pcode": "27660C01", "categorias": ["agua"], "hogares": 10}
DISPATCH_PAYLOAD = {"pcode": "27660C01", "items": [{"categoria": "agua", "cantidad": 1, "unidad": "kit"}]}
NEED_PAYLOAD = {"pcode": "27660C01", "categorias": ["agua"], "hogares_rango": "6-20"}


def test_u40_sin_eventos_alerta_maxima_no_null(db):
    fila = _mv(db, "27660C01")
    assert fila is not None, "el pcode priorizado sin eventos DEBE aparecer en la métrica"
    assert fila["estado"] == "alerta_maxima"
    # nunca se excluye ni se confunde con 0 días
    assert fila["dias_sin_recepcion"] is None


def test_u41_dispatch_no_resetea_solo_receipt(db):
    insertar_evento_directo(db, tipo="receipt", pcode="27660C01", payload=RECEIPT_PAYLOAD, hace_dias=5)
    insertar_evento_directo(db, tipo="dispatch", pcode="27660C01", payload=DISPATCH_PAYLOAD, hace_dias=0)
    fila = _mv(db, "27660C01")
    assert fila["estado"] == "con_registro"
    assert fila["dias_sin_recepcion"] == 5, "el dispatch de hoy no cuenta: solo la recepción confirma"


def test_u41_receipt_mas_reciente_gana(db):
    insertar_evento_directo(db, tipo="receipt", pcode="27660C01", payload=RECEIPT_PAYLOAD, hace_dias=9)
    insertar_evento_directo(db, tipo="receipt", pcode="27660C01", payload=RECEIPT_PAYLOAD, hace_dias=2)
    assert _mv(db, "27660C01")["dias_sin_recepcion"] == 2


def test_u42_necesidades_repetidas_no_inflan(db):
    insertar_evento_directo(db, tipo="need", pcode="27660C01", payload=NEED_PAYLOAD, reporter_ref="ref-a")
    insertar_evento_directo(db, tipo="need", pcode="27660C01", payload=NEED_PAYLOAD, reporter_ref="ref-a")
    insertar_evento_directo(db, tipo="need", pcode="27660C01", payload=NEED_PAYLOAD, reporter_ref="ref-a")
    fila = _mv(db, "27660C01")
    assert fila["reportantes_necesidad"] == 1, "misma persona repitiendo no es más necesidad"
    insertar_evento_directo(db, tipo="need", pcode="27660C01", payload=NEED_PAYLOAD, reporter_ref="ref-b")
    fila = _mv(db, "27660C01")
    assert fila["reportantes_necesidad"] == 2, "reportantes distintos sí suman intensidad"
    assert "agua" in fila["faltante_reportado"]
