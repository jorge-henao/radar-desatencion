"""U-30..U-35 — validación de esquema por tipo de evento, server-side."""

import pytest

from radar_core.errors import ErrorEstructurado
from tests.conftest import crear_evento

pytestmark = pytest.mark.unit


def _rechaza(db, tipo, payload):
    with pytest.raises(ErrorEstructurado) as exc:
        crear_evento(db, tipo, payload=payload)
    e = exc.value
    assert e.codigo == "payload_invalido"
    assert e.campo and e.campo.startswith("payload")
    assert e.motivo
    return e


class TestNeed:
    def test_u30_valido(self, db):
        r = crear_evento(db, "need")
        assert r["folio"].startswith("NE-")

    def test_u30_invalido_sin_categorias(self, db):
        _rechaza(db, "need", {"categorias": []})

    def test_u30_rango_invalido(self, db):
        _rechaza(db, "need", {"hogares_rango": "muchos"})


class TestDispatch:
    def test_u31_valido(self, db):
        r = crear_evento(db, "dispatch")
        assert r["folio"].startswith("DS-")

    def test_u31_item_sin_cantidad_positiva(self, db):
        _rechaza(db, "dispatch", {"items": [{"categoria": "agua", "cantidad": 0, "unidad": "bidones"}]})

    def test_u31_sin_destino(self, db):
        with pytest.raises(ErrorEstructurado):
            crear_evento(db, "dispatch", payload={"pcode": ""})


class TestReceipt:
    def test_u32_valido_con_folio_citado_opcional(self, db):
        r1 = crear_evento(db, "receipt")
        assert r1["folio"].startswith("RC-")
        r2 = crear_evento(db, "receipt", payload={"folio_citado": "DS-0392"})
        assert r2["folio"].startswith("RC-")

    def test_u32_hogares_negativo(self, db):
        _rechaza(db, "receipt", {"hogares": -3})


class TestDominio:
    def test_u33_categoria_fuera_del_enum(self, db):
        # "normalizada" por el LLM pero inexistente: se rechaza server-side
        e = _rechaza(db, "receipt", {"categorias": ["viveres"]})
        assert "payload" in e.campo

    def test_u34_tipo_incorrecto_no_se_coerce(self, db):
        e = _rechaza(db, "receipt", {"hogares": "como veinte"})
        assert "hogares" in e.campo

    def test_u34_campos_extra_inyectados(self, db):
        _rechaza(db, "receipt", {"telefono_contacto": "3001234567"})

    def test_u35_reporter_ref_obligatorio(self, db):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            crear_evento(db, "receipt", reporter_ref="")
