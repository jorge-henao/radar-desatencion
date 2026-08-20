"""U-56..U-59 — precisión del match por texto y salud de la normalización.

Estos casos existen porque la suite U-50..U-55 no podía detectar el problema que
los motiva: corre contra el catálogo de 8 entradas del storyboard, y los falsos
positivos del fuzzy match son un fenómeno de densidad. Medidos contra los 1.121
municipios reales del DANE, 12 de 14 frases de puro relleno resolvían a un pcode.
"""

import pytest

from radar_core.config import settings
from radar_core.seed.loader import _exigir_municipio
from radar_core.services.gazetteer import _STOPWORDS, normalizar_texto, titulo_es
from radar_core.services.geo import resolver_texto

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _seed(geo_semilla):
    yield


# Frases que un hablante dice cuando NO sabe dónde está. Ninguna nombra un lugar;
# todas dejan un residuo corto tras quitar muletillas, y ese residuo hace match
# con nombres cortos del catálogo ("rio"→Río Iró, "esa"→La Mesa, "monte"→Piamonte).
FRASES_SIN_LUGAR = [
    "por ahí cerquita del río",
    "no sé bien",
    "mmm este",
    "por allá lejos",
    "en la parte de arriba",
    "al lado del puente",
    "cerca de la escuela",
    "donde el señor",
    "eso queda por el monte",
    "aquí en la casa",
    "por el lado de abajo",
    "en la vereda esa",
    "como a una hora",
    "por la carretera",
    "más arriba de la finca",
    "pasando el puesto de salud",
]

# Transcripciones sucias reales que SÍ nombran un lugar: el control positivo que
# impide "arreglar" U-56 volviendo el resolvedor inútilmente estricto.
CON_LUGAR = [
    ("estoy en montería", "23001"),
    ("por ahí por buenaventura", "76109"),
    ("eso queda en santa rosa de cabal", "66682"),
    ("puerto tejada", "19573"),
    ("dosquebradas", "66170"),
    ("el aguilla", "76243"),          # typo fonético
    ("monteriaa", "23001"),           # alargamiento de vocal
]


class TestPrecisionDelMatchPorTexto:
    def test_u56_el_relleno_no_resuelve_a_un_lugar(self, catalogo_denso):
        resueltas = {
            f: (r["pcode"], r["nombre_oficial"], r["confianza"])
            for f in FRASES_SIN_LUGAR
            if (r := resolver_texto(f))["pcode"] is not None
        }
        assert not resueltas, f"frases sin lugar que resolvieron a un pcode: {resueltas}"

    def test_u56_el_relleno_sigue_siendo_material_de_repregunta(self, catalogo_denso):
        """No resolver no es lo mismo que romper: el agente debe poder seguir."""
        for frase in FRASES_SIN_LUGAR:
            r = resolver_texto(frase)
            assert r["motivo"] in {"sin_candidatos", "confianza_baja", "ambiguo"}, frase
            assert r["confianza"] < settings.umbral_confianza_geo, frase

    @pytest.mark.parametrize("texto,pcode", CON_LUGAR)
    def test_u56_control_positivo_lo_sucio_pero_real_sigue_resolviendo(
        self, catalogo_denso, texto, pcode
    ):
        r = resolver_texto(texto)
        assert r["pcode"] == pcode, f"{texto!r} → {r['nombre_oficial']} ({r['confianza']})"

    def test_u57_bajo_el_piso_no_se_elige_pero_se_ofrece(self, catalogo_denso):
        """Un candidato mediocre no se auto-resuelve; se devuelve para repreguntar.

        "kibdo" es Quibdó mal dictado: parecido suficiente para ofrecerlo, no
        para darlo por bueno. U-51 cubre el caso ambiguo (dos candidatos parejos);
        este cubre el otro, el de un único candidato flojo.
        """
        r = resolver_texto("kibdo")
        assert r["pcode"] is None
        assert r["motivo"] == "confianza_baja"
        assert r["candidatos"], "sin candidatos el agente no tiene qué preguntar"
        assert r["candidatos"][0]["pcode"] == "27001"
        assert r["confianza"] < settings.umbral_confianza_geo

    def test_u57_nunca_se_auto_resuelve_bajo_el_umbral(self, catalogo_denso):
        """Invariante: si hay pcode, la confianza alcanzó el umbral de dominio."""
        for texto in FRASES_SIN_LUGAR + [t for t, _ in CON_LUGAR] + ["kibdo", "la cabaña"]:
            r = resolver_texto(texto)
            if r["pcode"] is not None:
                assert r["confianza"] >= settings.umbral_confianza_geo, texto


class TestSaludDeLaNormalizacion:
    # Palabras que aparecen en nombres reales del DANE — el número es cuántas
    # veredas las usan. Si alguna entra a _STOPWORDS, el catálogo pierde el token
    # distintivo de esos nombres al cargarlos, en silencio.
    EN_NOMBRES_REALES = {
        "alto": 780, "bajo": 391, "centro": 212, "rio": 205, "loma": 180,
        "arriba": 167, "abajo": 123, "quebrada": 112, "puente": 67, "monte": 65,
        "casa": 30, "carretera": 5, "escuela": 4, "colegio": 3,
    }

    def test_u58_ninguna_palabra_de_nombres_reales_es_stopword(self):
        intrusas = {p: n for p, n in self.EN_NOMBRES_REALES.items() if p in _STOPWORDS}
        assert not intrusas, (
            f"stopwords que mutilan nombres reales del catálogo: {intrusas}. "
            "La misma lista normaliza el catálogo al cargarlo."
        )

    @pytest.mark.parametrize(
        "nombre,token",
        [
            ("Alto Baudó", "baudo"), ("Bajo Baudó", "baudo"),
            ("Puente Nacional", "puente"), ("Río Viejo", "rio"),
            ("El Colegio", "colegio"), ("La Mesa", "mesa"),
            ("Paz de Río", "rio"), ("Río Iró", "rio"),
        ],
    )
    def test_u58_los_nombres_reales_conservan_su_token_distintivo(self, nombre, token):
        assert token in normalizar_texto(nombre).split(), f"{nombre} → {normalizar_texto(nombre)!r}"

    def test_u58_ningun_nombre_del_catalogo_normaliza_a_vacio(self, catalogo_denso):
        """Un nombre que normaliza a vacío es inalcanzable por voz."""
        import csv

        from tests.conftest import FIXTURES

        with (FIXTURES / "municipios_muestra.csv").open(encoding="utf-8") as f:
            vacios = [fila["nombre"] for fila in csv.DictReader(f) if not normalizar_texto(fila["nombre"])]
        assert not vacios, f"nombres inalcanzables por voz: {vacios}"

    @pytest.mark.parametrize(
        "crudo,esperado",
        [
            ("VALLE DEL CAUCA", "Valle del Cauca"),
            ("SAN JOSE DEL PALMAR", "San Jose del Palmar"),
            ("NORTE DE SANTANDER", "Norte de Santander"),
            ("BOGOTÁ, D.C.", "Bogotá, D.c."),
            ("LA GUAJIRA", "La Guajira"),
        ],
    )
    def test_u59_title_case_respeta_particulas(self, crudo, esperado):
        """`str.title()` da "Valle Del Cauca"; el departamento ahora se lee en voz."""
        assert titulo_es(crudo) == esperado


class TestSeedExigeProcedencia:
    def test_territorio_no_municipal_sin_municipio_falla_ruidoso(self):
        """Preferible romper el seed que servir un pcode sin procedencia (I-13)."""
        with pytest.raises(ValueError, match="sin municipio_pcode"):
            _exigir_municipio("76364V01", "vereda", None)
        with pytest.raises(ValueError, match="sin municipio_pcode"):
            _exigir_municipio("76364001", "centro_poblado", None)

    def test_un_municipio_no_necesita_colgar_de_otro(self):
        _exigir_municipio("76364", "municipio", None)
