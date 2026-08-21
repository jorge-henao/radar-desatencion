"""Carga de datos geográficos y del gazetteer.

Los shapefiles DANE traen geometrías inválidas ocasionales: se sanean con
ST_MakeValid AL INGESTAR, nunca en query time (I-03).
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import GazetteerEntry
from ..services.gazetteer import normalizar_texto

_INSERT_GEO = text(
    """
    INSERT INTO geo_divipola
        (pcode, nombre, nivel, departamento, municipio_pcode, geom,
         poblacion_estimada, factor_accesibilidad, priorizado)
    VALUES
        (:pcode, :nombre, :nivel, :departamento, :municipio_pcode,
         ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)), 3)),
         :poblacion_estimada, :factor_accesibilidad, :priorizado)
    ON CONFLICT (pcode) DO UPDATE SET
        nombre = EXCLUDED.nombre,
        nivel = EXCLUDED.nivel,
        departamento = EXCLUDED.departamento,
        municipio_pcode = EXCLUDED.municipio_pcode,
        geom = EXCLUDED.geom,
        poblacion_estimada = EXCLUDED.poblacion_estimada,
        factor_accesibilidad = EXCLUDED.factor_accesibilidad,
        priorizado = EXCLUDED.priorizado
    """
)


def _exigir_municipio(pcode: str, nivel: str, municipio_pcode: str | None) -> None:
    """Un territorio no municipal sin municipio no puede entrar (I-13).

    Falla acá, ruidosamente, y no silenciosamente en el API: si esto pasara, la
    respuesta de resolver_ubicacion tendría un pcode sin procedencia y el agente
    no podría decir dónde queda el lugar que acaba de resolver.
    """
    if nivel != "municipio" and not municipio_pcode:
        raise ValueError(
            f"{pcode} ({nivel}) sin municipio_pcode: toda ubicación no municipal "
            "cuelga de un municipio. Corregir la fuente de datos, no el API."
        )


def cargar_territorio(
    session: Session,
    *,
    pcode: str,
    nombre: str,
    nivel: str,
    geometria: dict | None,
    departamento: str | None = None,
    municipio_pcode: str | None = None,
    poblacion_estimada: int | None = None,
    factor_accesibilidad: float = 1.0,
    priorizado: bool = False,
) -> None:
    _exigir_municipio(pcode, nivel, municipio_pcode)
    session.execute(
        _INSERT_GEO,
        {
            "pcode": pcode,
            "nombre": nombre,
            "nivel": nivel,
            "departamento": departamento,
            "municipio_pcode": municipio_pcode,
            "geojson": json.dumps(geometria) if geometria else None,
            "poblacion_estimada": poblacion_estimada,
            "factor_accesibilidad": factor_accesibilidad,
            "priorizado": priorizado,
        },
    )


def cargar_gazetteer(
    session: Session,
    *,
    nombre: str,
    pcode: str,
    nivel: str,
    nombre_oficial: str | None = None,
    es_alias: bool = False,
    municipio_pcode: str | None = None,
    municipio_nombre: str | None = None,
) -> None:
    _exigir_municipio(pcode, nivel, municipio_pcode)
    session.add(
        GazetteerEntry(
            nombre=nombre,
            nombre_norm=normalizar_texto(nombre),
            es_alias=es_alias,
            pcode=pcode,
            nivel=nivel,
            nombre_oficial=nombre_oficial or nombre,
            municipio_pcode=municipio_pcode,
            municipio_nombre_norm=normalizar_texto(municipio_nombre) if municipio_nombre else None,
        )
    )
