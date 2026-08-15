"""Resolución de nombre hablado → pcode contra el gazetteer.

El modo texto existe porque en voz no hay pin GPS: llega una transcripción
sucia ("la beredita la cabaña por jamundi, por ahí cerquita"). Fuzzy match
con rapidfuzz, alias, y desambiguación por municipio (U-50..55).

El gazetteer se carga en memoria (P-02/P-09): refresh() tras seed o cambios.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GazetteerEntry

# Palabras de relleno del habla regional que no aportan al match.
_STOPWORDS = {
    "la", "el", "los", "las", "de", "del", "por", "en", "un", "una", "y", "o",
    "ahi", "alla", "cerca", "cerquita", "como", "que", "queda", "eso", "es",
    "vereda", "veredita", "beredita", "bereda", "corregimiento", "cgto", "vda",
    "municipio", "barrio", "comuna", "sector", "zona", "parte", "lado",
}


def normalizar_texto(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9ñ\s]", " ", t)
    tokens = [tok for tok in t.split() if tok not in _STOPWORDS]
    return " ".join(tokens)


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

    def _detectar_municipio(self, texto_norm: str) -> str | None:
        """Si el texto contiene el nombre de un municipio, acota la búsqueda (U-55)."""
        for nombre_norm, pcode in self._municipios.items():
            if nombre_norm and nombre_norm in texto_norm:
                return pcode
        return None

    def buscar(self, texto: str, limite: int = 5) -> list[dict]:
        """Retorna candidatos [{pcode, nombre_oficial, nivel, confianza}] orden desc.

        Nunca lanza: texto basura → lista vacía (U-54).
        """
        texto_norm = normalizar_texto(texto)
        if not texto_norm or not self._entradas:
            return []

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
            if score < 0.60:
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
                }

        candidatos = sorted(puntajes.values(), key=lambda c: c["confianza"], reverse=True)
        return candidatos[:limite]


gazetteer = Gazetteer()
