"""U-50..U-55 — gazetteer: el canal de voz llega como transcripción sucia."""

import pytest

from radar_core.config import settings
from radar_core.services.geo import resolver_texto

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _seed(geo_semilla):
    yield


def test_u50_match_exacto_municipio():
    r = resolver_texto("Jamundí")
    assert r["pcode"] == "76364"
    assert r["nivel"] == "municipio"
    assert r["confianza"] >= settings.umbral_confianza_geo


def test_u51_ambiguo_nunca_elige_en_silencio():
    r = resolver_texto("La Cabaña")
    assert r["pcode"] is None, "con dos candidatas parejas no se decide solo"
    assert r["confianza"] < settings.umbral_confianza_geo
    pcodes = {c["pcode"] for c in r["candidatos"]}
    assert {"76364V01", "76828V01"} <= pcodes


def test_u52_transcripcion_sucia():
    r = resolver_texto("la beredita la cabaña por jamundi, por ahí cerquita")
    assert r["pcode"] == "76364V01"
    assert r["confianza"] >= settings.umbral_confianza_geo


def test_u53_alias_resuelve_canonico():
    r = resolver_texto("San José")
    assert r["pcode"] == "27660"
    assert r["nombre_oficial"] == "San José del Palmar"


def test_u54_basura_no_lanza():
    r = resolver_texto("asdfgh qwerty")
    assert r["pcode"] is None
    assert r["candidatos"] == []
    assert r["confianza"] == 0.0


def test_u55_municipio_desambigua_y_sube_confianza():
    ambiguo = resolver_texto("La Cabaña")
    acotado = resolver_texto("La Cabaña, Jamundí")
    assert acotado["pcode"] == "76364V01"
    assert acotado["confianza"] > ambiguo["confianza"]
