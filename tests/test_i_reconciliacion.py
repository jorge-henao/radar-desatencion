"""I-16..I-19 — reconciliación DISPATCH↔RECEIPT en batch."""

import pytest
from sqlalchemy import select, text

from radar_core.models import Notificacion, Reconciliacion
from radar_core.services.reconciliacion import reconciliar
from tests.conftest import crear_evento, insertar_evento_directo

pytestmark = pytest.mark.integration

DISPATCH_P = {"pcode": "27660C01", "items": [{"categoria": "agua", "cantidad": 120, "unidad": "bidones"}]}
RECEIPT_P = {"pcode": "27660C01", "categorias": ["agua"], "hogares": 28}


def test_i16_deterministico_por_folio_citado(db):
    ds = crear_evento(db, "dispatch", reporter_ref="ref-org")["folio"]
    crear_evento(db, "receipt", payload={"folio_citado": ds.lower().replace("-", " ")})  # dictado sucio
    resultado = reconciliar(db)
    assert resultado["deterministicos"] == 1
    par = db.execute(select(Reconciliacion)).scalars().one()
    assert par.dispatch_folio == ds
    assert par.metodo == "deterministico"


def test_i17_probabilistico_marcado(db):
    ds = insertar_evento_directo(db, tipo="dispatch", pcode="27660C01", payload=DISPATCH_P, hace_dias=2, con_ancla=True)
    insertar_evento_directo(db, tipo="receipt", pcode="27660C01", payload=RECEIPT_P, hace_dias=1)
    resultado = reconciliar(db)
    assert resultado["probabilisticos"] == 1
    par = db.execute(select(Reconciliacion)).scalars().one()
    assert par.dispatch_folio == ds
    assert par.metodo == "probabilistico", "el match sin folio SIEMPRE queda marcado como probabilístico"


def test_i17_sin_interseccion_de_categorias_no_matchea(db):
    insertar_evento_directo(db, tipo="dispatch", pcode="27660C01", payload=DISPATCH_P, hace_dias=2)
    insertar_evento_directo(
        db, tipo="receipt", pcode="27660C01",
        payload={"pcode": "27660C01", "categorias": ["techo"], "hogares": 5}, hace_dias=1,
    )
    assert reconciliar(db)["probabilisticos"] == 0


def test_i18_dispatch_sin_receipt_genera_desfase(db):
    ds = insertar_evento_directo(db, tipo="dispatch", pcode="27660C01", payload=DISPATCH_P, hace_dias=5, con_ancla=True)
    resultado = reconciliar(db)
    assert resultado["desfases"] == 1
    alerta = db.execute(
        select(Notificacion).where(Notificacion.plantilla == "alerta_desfase")
    ).scalars().one()
    assert alerta.variables["folio"] == ds
    assert alerta.estado == "pendiente"


def test_i18_dispatch_reciente_no_alerta(db):
    insertar_evento_directo(db, tipo="dispatch", pcode="27660C01", payload=DISPATCH_P, hace_dias=1, con_ancla=True)
    assert reconciliar(db)["desfases"] == 0


def test_i19_folio_inexistente_no_rompe_el_batch(db):
    crear_evento(db, "receipt", payload={"folio_citado": "DS-9999"})
    ds = crear_evento(db, "dispatch")["folio"]
    crear_evento(db, "receipt", payload={"folio_citado": ds}, reporter_ref="ref-otro", key="k-otro")
    resultado = reconciliar(db)
    assert resultado["deterministicos"] == 1
    assert len(resultado["no_matcheados"]) == 1


def test_i16_idempotente_segunda_pasada(db):
    ds = crear_evento(db, "dispatch")["folio"]
    crear_evento(db, "receipt", payload={"folio_citado": ds})
    reconciliar(db)
    resultado2 = reconciliar(db)
    assert resultado2["deterministicos"] == 0
    n = db.execute(text("SELECT count(*) FROM reconciliaciones")).scalar_one()
    assert n == 1
