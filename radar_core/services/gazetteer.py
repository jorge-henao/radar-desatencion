"""Resolución de nombre hablado → pcode contra el gazetteer.

El modo texto existe porque en voz no hay pin GPS: llega una transcripción
sucia ("la beredita la cabaña por jamundi, por ahí cerquita"). Fuzzy match
con rapidfuzz, alias, y desambiguación por municipio (U-50..55).

El gazetteer se carga en memoria (P-02/P-09): refresh() tras seed o cambios.
En ese mismo refresh se arma el índice de municipios que da la procedencia
(municipio + departamento) de cualquier pcode — por eso no hace falta ni una
columna nueva ni una query extra en el request path.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import GazetteerEntry

log = logging.getLogger("radar_core")

# Palabras de relleno del habla regional que no aportan al match.
#
# CUIDADO (U-58): esta lista se aplica también a los nombres del catálogo al
# cargarlos (`cargar_gazetteer` normaliza con esta misma función), así que una
# palabra que aparezca en nombres reales de lugar MUTILA el catálogo. Medido
# contra las 32.128 veredas del DANE: "alto" aparece en 780 nombres, "bajo" en
# 391, "rio" en 205, "arriba" en 167, "monte" en 65. Ninguna de esas puede
# entrar aquí. Solo deícticos y muletillas puras — verificar contra el catálogo
# antes de agregar cualquier palabra.
_STOPWORDS = {
    "la", "el", "los", "las", "de", "del", "por", "en", "un", "una", "y", "o",
    "ahi", "alla", "cerca", "cerquita", "como", "que", "queda", "eso", "es",
    "vereda", "veredita", "beredita", "bereda", "corregimiento", "cgto", "vda",
    "municipio", "barrio", "comuna", "sector", "zona", "parte", "lado",
    # Deícticos y muletillas sin contenido locativo (U-56). Verificadas: cero
    # apariciones en los nombres de municipios y veredas del DANE.
    "esa", "esta", "donde", "hora", "horas", "minutos", "finca", "iglesia",
    "puesto", "salida", "subiendo", "bajando", "pasando", "mas", "menos",
    "aca", "pues", "entonces", "digamos", "señor", "senor",
    # Aperturas de turno de habla: "estoy en Montería", "vivo por acá".
    # Verificadas igual que las anteriores. Ojo: "aqui", "si", "no", "mi" y
    # "bueno" NO pueden entrar — aparecen en nombres reales de veredas.
    "estoy", "estamos", "toy", "vivo", "vivimos", "soy", "somos", "vengo",
    "venimos", "yo", "nosotros", "usted", "me", "nos", "mire", "oiga",
    "creo", "ahora", "hoy", "ayer", "alli",
}

# Partículas que no se capitalizan en un topónimo español. `str.title()` produce
# "Valle Del Cauca"; con el departamento ahora expuesto en la respuesta, ese
# string se vuelve audible en el canal de voz (U-59).
_MINUSCULAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "al"}


def titulo_es(texto: str) -> str:
    """Title case respetando partículas: "VALLE DEL CAUCA" → "Valle del Cauca"."""
    partes = texto.strip().lower().split()
    return " ".join(
        p if i and p in _MINUSCULAS else p.capitalize() for i, p in enumerate(partes)
    )


def normalizar_texto(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9ñ\s]", " ", t)
    tokens = [tok for tok in t.split() if tok not in _STOPWORDS]
    return " ".join(tokens)


def score_minimo(texto_norm: str) -> float:
    """Score exigido para auto-resolver, según cuánto texto útil quedó (U-56).

    El score fuzzy es esencialmente un ratio de longitud: "rio" contra "riofrio"
    da exactamente 0.60 sin que el hablante haya nombrado un lugar. Medido contra
    los 1.121 municipios del DANE, 12 de 14 frases de puro relleno resolvían con
    el corte plano de 0.60; con la escala, 2.
    """
    s = get_settings()
    largo = len(texto_norm.replace(" ", ""))
    if largo >= s.geo_residuo_largo:
        return s.geo_min_score_largo
    if largo >= s.geo_residuo_medio:
        return s.geo_min_score_medio
    return s.geo_min_score_corto


def componer_procedencia(
    nombre_oficial: str,
    nivel: str,
    municipio_pcode: str | None,
    municipio_nombre: str | None,
    departamento: str | None,
) -> dict:
    """Los cinco campos de procedencia, en el único formato que existe.

    Modo pin y modo texto leen de fuentes distintas (geo_divipola vs. el índice
    en memoria) pero deben producir exactamente lo mismo para el mismo territorio
    (I-14) — por eso el formato vive acá y no duplicado en cada resolvedor.

    Regla del contrato (I-13): un municipio es su propio municipio, nunca `null`.
    Así el agente no ramifica por `nivel` para saber dónde queda algo.
    """
    codigo_dpto = (
        municipio_pcode[:2] if municipio_pcode and municipio_pcode[:2].isdigit() else None
    )
    partes = [f"{nombre_oficial} ({nivel.replace('_', ' ')})"]
    if municipio_nombre and nivel != "municipio":
        partes.append(municipio_nombre)
    if departamento:
        partes.append(departamento)
    return {
        "municipio_pcode": municipio_pcode,
        "municipio_nombre": municipio_nombre,
        "departamento_codigo": codigo_dpto,
        "departamento_nombre": departamento,
        "etiqueta": ", ".join(partes),
    }


@dataclass
class EntradaGaz:
    nombre_norm: str
    pcode: str
    nivel: str
    nombre_oficial: str
    municipio_pcode: str | None
    municipio_nombre_norm: str | None


class Gazetteer:
    def __init__(self) -> None:
        self._entradas: list[EntradaGaz] = []
        self._municipios: dict[str, str] = {}  # nombre_norm → pcode
        self._meta: dict[str, tuple[str, str | None]] = {}  # pcode mpio → (nombre, dpto)

    def refresh(self, session: Session) -> None:
        filas = session.execute(select(GazetteerEntry)).scalars().all()
        self._entradas = [
            EntradaGaz(
                nombre_norm=f.nombre_norm,
                pcode=f.pcode,
                nivel=f.nivel,
                nombre_oficial=f.nombre_oficial,
                municipio_pcode=f.municipio_pcode,
                municipio_nombre_norm=f.municipio_nombre_norm,
            )
            for f in filas
        ]
        self._municipios = {
            f.nombre_norm: f.pcode for f in filas if f.nivel == "municipio" and not f.es_alias
        }
        self._refrescar_meta(session, filas)

    def _refrescar_meta(self, session: Session, filas) -> None:
        """Índice pcode-de-municipio → (nombre, departamento).

        La fuente autoritativa es geo_divipola, la única tabla con departamento.
        Se completa con las entradas de municipio del propio gazetteer para no
        depender de que los polígonos estén cargados (tests, seeds parciales).
        """
        meta: dict[str, tuple[str, str | None]] = {}
        for f in filas:
            if f.nivel == "municipio" and not f.es_alias:
                meta[f.pcode] = (f.nombre_oficial, None)
        rows = session.execute(
            text("SELECT pcode, nombre, departamento FROM geo_divipola WHERE nivel = 'municipio'")
        ).mappings().all()
        for r in rows:
            dpto = titulo_es(r["departamento"]) if r["departamento"] else None
            meta[r["pcode"]] = (r["nombre"], dpto)
        self._meta = meta

        # Una entrada que no se puede situar nunca resolverá: resolver_texto la
        # filtra antes de decidir. Es un problema de datos, no de request — hay
        # que verlo al sembrar, no descubrirlo en producción. Dos formas de
        # estarlo: colgar de un municipio que no existe, o no colgar de ninguno
        # (filas anteriores al guard de cargar_territorio).
        sin_municipio = [
            f.pcode for f in filas if f.nivel != "municipio" and not f.municipio_pcode
        ]
        if sin_municipio:
            log.warning(
                "gazetteer: %d entradas no municipales sin municipio_pcode; no "
                "podrán resolverse por texto: %s",
                len(sin_municipio),
                sorted(sin_municipio)[:10],
            )
        huerfanas = {
            f.municipio_pcode
            for f in filas
            if f.municipio_pcode and f.municipio_pcode not in meta
        }
        sin_dpto = sorted(pc for pc, (_, d) in meta.items() if not d)
        if sin_dpto:
            log.warning(
                "gazetteer: %d municipios sin departamento en geo_divipola; las "
                "ubicaciones que cuelgan de ellos saldrán con departamento_nombre "
                "en null: %s",
                len(sin_dpto),
                sin_dpto[:10],
            )
        if huerfanas:
            log.warning(
                "gazetteer: %d municipios referenciados sin fila en geo_divipola "
                "(las entradas que cuelgan de ellos no podrán resolverse): %s",
                len(huerfanas),
                sorted(huerfanas)[:10],
            )

    def procedencia(
        self, pcode: str, nivel: str, nombre_oficial: str, municipio_pcode: str | None
    ) -> dict:
        """Procedencia de una entrada del gazetteer, vía el índice en memoria."""
        mpio = municipio_pcode or (pcode if nivel == "municipio" else None)
        nombre_mpio, dpto = self._meta.get(mpio or "", (None, None))
        return componer_procedencia(nombre_oficial, nivel, mpio, nombre_mpio, dpto)

    def _detectar_municipio(self, texto_norm: str) -> str | None:
        """Si el texto contiene el nombre de un municipio, acota la búsqueda (U-55)."""
        for nombre_norm, pcode in self._municipios.items():
            if nombre_norm and nombre_norm in texto_norm:
                return pcode
        return None

    def buscar(self, texto: str, limite: int = 5) -> list[dict]:
        """Retorna candidatos [{pcode, nombre_oficial, nivel, confianza, …}] orden desc.

        El corte de entrada a `candidatos[]` sigue siendo el laxo (0.60): un
        candidato mediocre es material de repregunta, no de descarte. Quien
        decide si se puede auto-resolver es `score_minimo()`, en geo.resolver_texto.

        Nunca lanza: texto basura → lista vacía (U-54).
        """
        texto_norm = normalizar_texto(texto)
        if not texto_norm or not self._entradas:
            return []

        corte = get_settings().geo_min_score_largo
        municipio_ctx = self._detectar_municipio(texto_norm)

        puntajes: dict[str, dict] = {}
        for e in self._entradas:
            # token_set premia subconjuntos ("Palmar" ⊂ "San José del Palmar" da 100):
            # se mezcla con token_sort para que el match que cubre TODO el texto
            # gane sobre el que solo cubre un pedazo.
            score = (
                0.6 * fuzz.token_set_ratio(texto_norm, e.nombre_norm)
                + 0.4 * fuzz.token_sort_ratio(texto_norm, e.nombre_norm)
            ) / 100.0
            if score < corte:
                continue
            # Boost por contexto de municipio (U-55, U-52)
            if municipio_ctx:
                if e.pcode == municipio_ctx and texto_norm != e.nombre_norm:
                    # El municipio citado como referencia: candidato válido pero detrás
                    # del lugar específico mencionado.
                    score *= 0.85
                elif e.municipio_pcode == municipio_ctx:
                    score = min(1.0, score * 1.15)
                elif e.municipio_pcode and e.municipio_pcode != municipio_ctx:
                    score *= 0.70
            actual = puntajes.get(e.pcode)
            if actual is None or score > actual["confianza"]:
                puntajes[e.pcode] = {
                    "pcode": e.pcode,
                    "nombre_oficial": e.nombre_oficial,
                    "nivel": e.nivel,
                    "confianza": round(score, 3),
                    **self.procedencia(e.pcode, e.nivel, e.nombre_oficial, e.municipio_pcode),
                }

        candidatos = sorted(puntajes.values(), key=lambda c: c["confianza"], reverse=True)
        return candidatos[:limite]


gazetteer = Gazetteer()
