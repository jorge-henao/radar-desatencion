"""Resolución geográfica: pin GPS → DIVIPOLA (PostGIS) y texto → gazetteer.

Reglas:
- Pin dentro de varios polígonos → gana el nivel más específico (I-11):
  vereda > centro_poblado > municipio.
- Fuera de cobertura → respuesta estructurada, nunca 500 (I-12).
- Texto ambiguo → candidatos[] y confianza bajo umbral: el agente desambigua
  conversacionalmente ("¿La Cabaña de Jamundí o la de Riofrío?") (S-22).
- Toda ubicación resuelta viaja con su procedencia: municipio y departamento,
  en la respuesta y en cada candidato (I-13). El agente nunca tiene que inferir
  dónde queda un lugar a partir del pcode.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from .gazetteer import componer_procedencia, gazetteer, normalizar_texto, score_minimo, titulo_es

_ESPECIFICIDAD = {"vereda": 3, "centro_poblado": 2, "municipio": 1}

_VACIO = {
    "municipio_pcode": None,
    "municipio_nombre": None,
    "departamento_codigo": None,
    "departamento_nombre": None,
    "etiqueta": None,
}

# El self-join trae el municipio del territorio en la misma consulta: un municipio
# se apunta a sí mismo, y el departamento sale de la fila del municipio (en los
# datos DANE reales las veredas y centros poblados lo tienen NULL).
_SQL_PIN = text(
    """
    WITH tocados AS (
        SELECT pcode, nombre, nivel, departamento,
               coalesce(municipio_pcode,
                        CASE WHEN nivel = 'municipio' THEN pcode END) AS mpio_pcode
        FROM geo_divipola
        WHERE geom IS NOT NULL
          AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    )
    SELECT t.pcode, t.nombre, t.nivel, t.mpio_pcode,
           m.nombre AS mpio_nombre,
           coalesce(m.departamento, t.departamento) AS dpto
    FROM tocados t
    LEFT JOIN geo_divipola m ON m.pcode = t.mpio_pcode AND m.nivel = 'municipio'
    """
)


def _tiene_procedencia(u: dict) -> bool:
    """El contrato promete municipio; sin nombre de municipio no sirve para repreguntar."""
    return bool(u.get("municipio_pcode") and u.get("municipio_nombre"))


def _sin_ubicacion(motivo: str) -> dict:
    return {
        "pcode": None,
        "nivel": None,
        "nombre_oficial": None,
        **_VACIO,
        "confianza": 0.0,
        "candidatos": [],
        "motivo": motivo,
    }


def resolver_pin(session: Session, lat: float, lon: float) -> dict:
    filas = session.execute(_SQL_PIN, {"lat": lat, "lon": lon}).mappings().all()
    if not filas:
        return _sin_ubicacion("fuera_de_cobertura")
    filas = sorted(filas, key=lambda f: _ESPECIFICIDAD.get(f["nivel"], 0), reverse=True)

    def candidato(f) -> dict:
        return {
            "pcode": f["pcode"],
            "nombre_oficial": f["nombre"],
            "nivel": f["nivel"],
            "confianza": 1.0,
            **componer_procedencia(
                f["nombre"],
                f["nivel"],
                f["mpio_pcode"],
                f["mpio_nombre"],
                titulo_es(f["dpto"]) if f["dpto"] else None,
            ),
        }

    candidatos = [candidato(f) for f in filas]
    # El LEFT JOIN no falla cerrado: una fila no municipal cuyo municipio no
    # exista (o que tenga municipio_pcode NULL — hay filas así de seeds viejos,
    # el guard del loader solo frena las nuevas) saldría con pcode y confianza
    # 1.0 pero sin procedencia, violando el invariante. Se degrada al nivel más
    # específico que SÍ la tenga: el pin casi siempre cae también en el polígono
    # del municipio, así que la respuesta pierde precisión, no validez.
    completos = [c for c in candidatos if _tiene_procedencia(c)]
    if not completos:
        return _sin_ubicacion("procedencia_incompleta")
    mejor = completos[0]
    return {
        "pcode": mejor["pcode"],
        "nivel": mejor["nivel"],
        "nombre_oficial": mejor["nombre_oficial"],
        "municipio_pcode": mejor["municipio_pcode"],
        "municipio_nombre": mejor["municipio_nombre"],
        "departamento_codigo": mejor["departamento_codigo"],
        "departamento_nombre": mejor["departamento_nombre"],
        "etiqueta": mejor["etiqueta"],
        "confianza": 1.0,
        "candidatos": completos,
        "motivo": None,
    }


def resolver_texto(texto: str) -> dict:
    settings = get_settings()
    crudos = gazetteer.buscar(texto)
    if not crudos:
        return _sin_ubicacion("sin_candidatos")
    # Un candidato que no se puede situar no se ofrece: si el agente lo eligiera,
    # crearía un evento con un pcode del que no puede decir dónde queda — el
    # agujero que este contrato existe para cerrar. Se filtra ANTES de decidir,
    # así que un segundo candidato sano puede ganar cuando el primero está roto.
    candidatos = [c for c in crudos if _tiene_procedencia(c)]
    if not candidatos:
        return _sin_ubicacion("procedencia_incompleta")
    mejor = candidatos[0]
    # score 1.0 solo ocurre con identidad de tokens ("match exacto"). Un exacto
    # único no es ambiguo aunque haya vecinos fuzzy cerca ("San José del Palmar"
    # no debe frenarse por "Palmar" o "San José de la Montaña"); dos exactos
    # (dos veredas "La Cabaña") sí se desambiguan conversando.
    exacto = mejor["confianza"] >= 0.999
    segundo_exacto = len(candidatos) > 1 and candidatos[1]["confianza"] >= 0.999

    # Piso para auto-resolver (U-56/U-57): el umbral de dominio, y además el
    # escalado por longitud del residuo — un residuo de tres letras ("rio") hace
    # match alto con cualquier nombre corto sin que se haya nombrado un lugar.
    piso = max(score_minimo(normalizar_texto(texto)), settings.umbral_confianza_geo)

    # Hay ambigüedad cuando el segundo candidato es una alternativa de verdad, no
    # solo cuando está cerca: con un catálogo denso siempre hay alguien a 0.10 de
    # distancia ("Montelíbano" detrás de "Montería"), y tratar eso como empate
    # bloquea respuestas correctas. Si el segundo no alcanza el piso, no era
    # elegible por sí mismo y por tanto no compite.
    ambiguo = (
        len(candidatos) > 1
        and candidatos[1]["confianza"] >= mejor["confianza"] - 0.12
        and candidatos[1]["confianza"] >= piso
        and (not exacto or segundo_exacto)
    )
    if ambiguo:
        return {
            "pcode": None,
            "nivel": None,
            "nombre_oficial": None,
            **_VACIO,
            "confianza": round(min(mejor["confianza"], settings.umbral_confianza_geo - 0.01), 3),
            "candidatos": candidatos,
            "motivo": "ambiguo",
        }

    # Por debajo del piso se devuelven los candidatos igual: es material de
    # repregunta, no un error.
    #
    # `confianza` de nivel superior es la confianza EN LA RESOLUCIÓN, no el score
    # del mejor candidato: devolver 0.84 junto a `pcode: null` le diría al agente
    # "estoy seguro" y "no sé" en la misma respuesta. El score crudo sigue visible
    # en cada candidato, que es donde sirve para ordenar la repregunta.
    if mejor["confianza"] < piso:
        return {
            "pcode": None,
            "nivel": None,
            "nombre_oficial": None,
            **_VACIO,
            "confianza": round(min(mejor["confianza"], settings.umbral_confianza_geo - 0.01), 3),
            "candidatos": candidatos,
            "motivo": "confianza_baja",
        }

    return {
        "pcode": mejor["pcode"],
        "nivel": mejor["nivel"],
        "nombre_oficial": mejor["nombre_oficial"],
        "municipio_pcode": mejor["municipio_pcode"],
        "municipio_nombre": mejor["municipio_nombre"],
        "departamento_codigo": mejor["departamento_codigo"],
        "departamento_nombre": mejor["departamento_nombre"],
        "etiqueta": mejor["etiqueta"],
        "confianza": mejor["confianza"],
        "candidatos": candidatos,
        "motivo": None,
    }
