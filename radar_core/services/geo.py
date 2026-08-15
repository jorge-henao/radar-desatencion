"""Resolución geográfica: pin GPS → DIVIPOLA (PostGIS) y texto → gazetteer.

Reglas:
- Pin dentro de varios polígonos → gana el nivel más específico (I-11):
  vereda > centro_poblado > municipio.
- Fuera de cobertura → respuesta estructurada, nunca 500 (I-12).
- Texto ambiguo → candidatos[] y confianza bajo umbral: el agente desambigua
  conversacionalmente ("¿La Cabaña de Jamundí o la de Riofrío?") (S-22).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from .gazetteer import gazetteer

_ESPECIFICIDAD = {"vereda": 3, "centro_poblado": 2, "municipio": 1}

_SQL_PIN = text(
    """
    SELECT pcode, nombre, nivel
    FROM geo_divipola
    WHERE geom IS NOT NULL
      AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    """
)


def resolver_pin(session: Session, lat: float, lon: float) -> dict:
    filas = session.execute(_SQL_PIN, {"lat": lat, "lon": lon}).mappings().all()
    if not filas:
        return {
            "pcode": None,
            "nivel": None,
            "nombre_oficial": None,
            "confianza": 0.0,
            "candidatos": [],
            "motivo": "fuera_de_cobertura",
        }
    filas = sorted(filas, key=lambda f: _ESPECIFICIDAD.get(f["nivel"], 0), reverse=True)
    mejor = filas[0]
    return {
        "pcode": mejor["pcode"],
        "nivel": mejor["nivel"],
        "nombre_oficial": mejor["nombre"],
        "confianza": 1.0,
        "candidatos": [
            {"pcode": f["pcode"], "nombre_oficial": f["nombre"], "nivel": f["nivel"], "confianza": 1.0}
            for f in filas
        ],
        "motivo": None,
    }


def resolver_texto(texto: str) -> dict:
    settings = get_settings()
    candidatos = gazetteer.buscar(texto)
    if not candidatos:
        return {
            "pcode": None,
            "nivel": None,
            "nombre_oficial": None,
            "confianza": 0.0,
            "candidatos": [],
            "motivo": "sin_candidatos",
        }
    mejor = candidatos[0]
    # score 1.0 solo ocurre con identidad de tokens ("match exacto"). Un exacto
    # único no es ambiguo aunque haya vecinos fuzzy cerca ("San José del Palmar"
    # no debe frenarse por "Palmar" o "San José de la Montaña"); dos exactos
    # (dos veredas "La Cabaña") sí se desambiguan conversando.
    exacto = mejor["confianza"] >= 0.999
    segundo_exacto = len(candidatos) > 1 and candidatos[1]["confianza"] >= 0.999
    ambiguo = (
        len(candidatos) > 1
        and candidatos[1]["confianza"] >= mejor["confianza"] - 0.12
        and (not exacto or segundo_exacto)
    )
    confianza = mejor["confianza"] if not ambiguo else min(mejor["confianza"], settings.umbral_confianza_geo - 0.01)
    return {
        "pcode": mejor["pcode"] if not ambiguo else None,
        "nivel": mejor["nivel"] if not ambiguo else None,
        "nombre_oficial": mejor["nombre_oficial"] if not ambiguo else None,
        "confianza": round(confianza, 3),
        "candidatos": candidatos,
        "motivo": "ambiguo" if ambiguo else None,
    }
