"""S-01..S-26 — contrato de la Tools API desde la perspectiva del agente Vozy."""

import pytest

from radar_core.config import settings
from tests.conftest import AUTH, PIN_MAR, PIN_SAN_PEDRO

pytestmark = pytest.mark.service

RECEIPT_BODY = {
    "type": "receipt",
    "payload": {"pcode": "27660C01", "categorias": ["agua"], "hogares": 28, "pin": PIN_SAN_PEDRO},
    "reporter_ref": "ref-jac",
    "idempotency_key": "conv-77:paso-9",
}

DISPATCH_BODY = {
    "type": "dispatch",
    "payload": {
        "pcode": "27660C01",
        "items": [
            {"categoria": "alimentos", "cantidad": 80, "unidad": "kits"},
            {"categoria": "agua", "cantidad": 120, "unidad": "bidones"},
        ],
        "org_nombre": "Acopio Pereira",
        "eta": "15 ago p.m.",
    },
    "reporter_ref": "ref-fundacion",
    "idempotency_key": "conv-80:paso-4",
}


class TestAuth:
    def test_s01_sin_token(self, client):
        r = client.post("/tools/crear_evento", json=RECEIPT_BODY)
        assert r.status_code == 401
        assert r.json()["errores"][0]["codigo"] == "no_autenticado"

    def test_s01_token_invalido_sin_efectos(self, client, db):
        r = client.post("/tools/crear_evento", json=RECEIPT_BODY, headers={"Authorization": "Bearer malo"})
        assert r.status_code == 401
        from sqlalchemy import text

        assert db.execute(text("SELECT count(*) FROM events")).scalar_one() == 0

    def test_s02_json_malformado_400_no_500(self, client):
        r = client.post(
            "/tools/crear_evento", content=b"{esto no es json", headers={**AUTH, "Content-Type": "application/json"}
        )
        assert r.status_code == 400
        assert "errores" in r.json()

    def test_s03_errores_consumibles_por_el_agente(self, client):
        cuerpo = {**RECEIPT_BODY, "payload": {**RECEIPT_BODY["payload"], "hogares": "como veinte"}}
        r = client.post("/tools/crear_evento", json=cuerpo, headers=AUTH)
        assert r.status_code == 400
        error = r.json()["errores"][0]
        assert set(error) >= {"codigo", "campo", "motivo"}
        assert "hogares" in error["campo"]
        assert error["motivo"], "el motivo alimenta la repregunta del agente"


class TestCrearEvento:
    def test_s10_reintento_de_la_plataforma(self, client, db):
        r1 = client.post("/tools/crear_evento", json=RECEIPT_BODY, headers=AUTH)
        r2 = client.post("/tools/crear_evento", json=RECEIPT_BODY, headers=AUTH)  # timeout percibido → retry
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["folio"] == r2.json()["folio"]
        from sqlalchemy import text

        assert db.execute(text("SELECT count(*) FROM events")).scalar_one() == 1

    def test_s11_happy_path_receipt_consultable(self, client):
        folio = client.post("/tools/crear_evento", json=RECEIPT_BODY, headers=AUTH).json()["folio"]
        assert folio.startswith("RC-")
        consulta = client.get(f"/tools/consultar_folio?folio={folio}", headers=AUTH).json()
        assert consulta["existe"] is True
        assert consulta["type"] == "receipt"

    def test_s12_dispatch_devuelve_acta_url(self, client):
        r = client.post("/tools/crear_evento", json=DISPATCH_BODY, headers=AUTH).json()
        assert r["acta_url"] and r["folio"] in r["acta_url"]
        assert client.get(r["acta_url"].replace("http://testserver", "")).status_code == 200

    def test_s12_receipt_no_lleva_acta(self, client):
        r = client.post("/tools/crear_evento", json=RECEIPT_BODY, headers=AUTH).json()
        assert r["acta_url"] is None

    def test_s13_categoria_inventada_por_el_llm(self, client, db):
        cuerpo = {**RECEIPT_BODY, "payload": {**RECEIPT_BODY["payload"], "categorias": ["mercaditos"]}}
        r = client.post("/tools/crear_evento", json=cuerpo, headers=AUTH)
        assert r.status_code == 400
        from sqlalchemy import text

        assert db.execute(text("SELECT count(*) FROM events")).scalar_one() == 0

    def test_s14_duplicado_advierte_no_bloquea(self, client):
        client.post("/tools/crear_evento", json=DISPATCH_BODY, headers=AUTH)
        segundo = {**DISPATCH_BODY, "idempotency_key": "conv-81:paso-4"}
        r = client.post("/tools/crear_evento", json=segundo, headers=AUTH)
        assert r.status_code == 200, "advertir, no bloquear"
        assert any(w["codigo"] == "posible_duplicado" for w in r.json()["warnings"])

    def test_s15_el_esquema_no_acepta_datos_prohibidos(self, client):
        for campo, valor in (("cedula", "123"), ("telefono", "300123"), ("cuenta_bancaria", "x")):
            cuerpo = {
                **RECEIPT_BODY,
                "idempotency_key": f"pii-{campo}",
                "payload": {**RECEIPT_BODY["payload"], campo: valor},
            }
            r = client.post("/tools/crear_evento", json=cuerpo, headers=AUTH)
            assert r.status_code == 400, f"el payload jamás acepta {campo}"

    def test_s16_rate_limit_por_hash_sin_afectar_a_otros(self, client):
        original = settings.rate_limit_max
        try:
            settings.rate_limit_max = 3
            for i in range(3):
                cuerpo = {**RECEIPT_BODY, "idempotency_key": f"rl-{i}"}
                assert client.post("/tools/crear_evento", json=cuerpo, headers=AUTH).status_code == 200
            bloqueado = client.post(
                "/tools/crear_evento", json={**RECEIPT_BODY, "idempotency_key": "rl-4"}, headers=AUTH
            )
            assert bloqueado.status_code == 429
            assert bloqueado.json()["errores"][0]["codigo"] == "rate_limit"
            otro = {**RECEIPT_BODY, "reporter_ref": "ref-distinta", "idempotency_key": "rl-otro"}
            assert client.post("/tools/crear_evento", json=otro, headers=AUTH).status_code == 200
        finally:
            settings.rate_limit_max = original


class TestResolverUbicacion:
    def test_s20_modo_pin(self, client):
        r = client.post("/tools/resolver_ubicacion", json=PIN_SAN_PEDRO, headers=AUTH)
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["pcode"] == "27660C01"
        assert cuerpo["confianza"] >= 0.99

    def test_s20_pin_fuera_de_cobertura(self, client):
        r = client.post("/tools/resolver_ubicacion", json=PIN_MAR, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["motivo"] == "fuera_de_cobertura"

    def test_s21_modo_texto_nombre_unico(self, client):
        r = client.post("/tools/resolver_ubicacion", json={"texto": "corregimiento San Pedro"}, headers=AUTH)
        assert r.json()["pcode"] == "27660C01"

    def test_s22_ambiguo_para_desambiguar_conversando(self, client):
        r = client.post("/tools/resolver_ubicacion", json={"texto": "la vereda La Cabaña"}, headers=AUTH)
        cuerpo = r.json()
        assert cuerpo["pcode"] is None
        assert cuerpo["confianza"] < settings.umbral_confianza_geo
        assert len(cuerpo["candidatos"]) >= 2  # "¿La Cabaña de Jamundí o la de Riofrío?"

    def test_s23_modos_invalidos(self, client):
        for cuerpo in ({}, {"lat": 4.9, "lon": -76.2, "texto": "San Pedro"}, {"lat": 4.9}):
            r = client.post("/tools/resolver_ubicacion", json=cuerpo, headers=AUTH)
            assert r.status_code == 400, cuerpo


class TestConsultarFolio:
    def test_s25_existente_precarga_recepcion(self, client):
        folio = client.post("/tools/crear_evento", json=DISPATCH_BODY, headers=AUTH).json()["folio"]
        r = client.get(f"/tools/consultar_folio?folio={folio}", headers=AUTH).json()
        assert r == {
            "existe": True,
            "type": "dispatch",
            "estado": "registrado",
            "resumen": r["resumen"],
        }
        assert "27660C01" in r["resumen"]

    def test_s26_inexistente_es_resultado_no_error(self, client):
        r = client.get("/tools/consultar_folio?folio=DS-9999", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["existe"] is False

    def test_s26_typo_de_dictado(self, client):
        folio = client.post("/tools/crear_evento", json=DISPATCH_BODY, headers=AUTH).json()["folio"]
        sucio = folio.replace("-", " ").lower()
        r = client.get(f"/tools/consultar_folio?folio={sucio}", headers=AUTH).json()
        assert r["existe"] is True
        basura = client.get("/tools/consultar_folio?folio=zz@@", headers=AUTH)
        assert basura.status_code == 200
        assert basura.json()["existe"] is False
