"""Export estático — tabla.html, datos.csv (HXL), datos.geojson.

- Solo agregados por pcode: CERO pins, CERO hashes, CERO payload crudo (I-20, S-30).
- Escritura atómica (tmp + os.replace): si la DB está caída el job falla con
  alerta y el export anterior sigue sirviéndose — nunca se publica un archivo
  vacío o corrupto (I-22).
- Columnas del CSV estables entre corridas: son contrato con consumidores
  externos (I-23). Etiquetas HXL en la segunda fila (U-62).
- La salida pública se sirve estática: el request path jamás toca la DB.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..config import get_settings
from .. import ddl

# Contrato con consumidores externos: NO cambiar nombres ni orden (I-23).
COLUMNAS = [
    "pcode",
    "nombre",
    "nivel",
    "departamento",
    "estado",
    "dias_sin_recepcion",
    "hogares_estimados",
    "faltante_reportado",
    "factor_accesibilidad",
    "score",
]

HXL_TAGS = [
    "#geo+code",
    "#loc+name",
    "#loc+type",
    "#adm1+name",
    "#status",
    "#indicator+dias_sin_recepcion",
    "#population+hogares",
    "#need+list",
    "#access+factor",
    "#indicator+score",
]

_jinja = Environment(
    loader=PackageLoader("radar_core", "templates"),
    autoescape=select_autoescape(["html"]),  # X-07
)


def _filas(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                """
                SELECT m.pcode, m.nombre, m.nivel, m.departamento, m.estado,
                       m.dias_sin_recepcion, m.poblacion_estimada AS hogares_estimados,
                       m.faltante_reportado, m.factor_accesibilidad, m.score,
                       ST_AsGeoJSON(ST_Simplify(g.geom::geometry, 0.001)) AS geom
                FROM mv_desatencion m
                JOIN geo_divipola g ON g.pcode = m.pcode
                ORDER BY (m.estado = 'alerta_maxima') DESC, m.score DESC NULLS LAST
                """
            )
        ).mappings().all()
    return [dict(f) for f in filas]


def _escribir_atomico(destino: Path, contenido: bytes) -> None:
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    tmp.write_bytes(contenido)
    os.replace(tmp, destino)


def _csv_bytes(filas: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNAS)
    w.writerow(HXL_TAGS)
    for f in filas:
        w.writerow([f.get(c, "") if f.get(c) is not None else "" for c in COLUMNAS])
    return buf.getvalue().encode("utf-8")


def _geojson_bytes(filas: list[dict], generado_el: str) -> bytes:
    features = []
    for f in filas:
        props = {c: f.get(c) for c in COLUMNAS}
        geom = json.loads(f["geom"]) if f.get("geom") else None
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    fc = {
        "type": "FeatureCollection",
        "metadata": {"generado_el": generado_el, "fuente": "Radar de Desatencion"},
        "features": features,
    }
    return json.dumps(fc, ensure_ascii=False).encode("utf-8")


def _html_bytes(filas: list[dict], generado_el: str) -> bytes:
    tpl = _jinja.get_template("tabla.html")
    return tpl.render(filas=filas, columnas=COLUMNAS, generado_el=generado_el).encode("utf-8")


def exportar(engine: Engine, refresh: bool = True) -> dict:
    """Corre el export completo. Ante error de DB lanza — el export previo queda intacto."""
    s = get_settings()
    export_dir = Path(s.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    if refresh:
        try:
            ddl.refresh_mvs(engine)
        except Exception:
            # Primer refresh (MV nunca poblada) no admite CONCURRENTLY
            ddl.refresh_mvs(engine, concurrently=False)

    filas = _filas(engine)  # si la DB está caída, esto lanza y no se toca nada (I-22)
    generado_el = dt.datetime.now(dt.UTC).isoformat()

    _escribir_atomico(export_dir / "datos.csv", _csv_bytes(filas))
    _escribir_atomico(export_dir / "datos.geojson", _geojson_bytes(filas, generado_el))
    _escribir_atomico(export_dir / "tabla.html", _html_bytes(filas, generado_el))
    _escribir_atomico(
        export_dir / "meta.json",
        json.dumps({"generado_el": generado_el, "territorios": len(filas)}).encode(),
    )
    return {"territorios": len(filas), "generado_el": generado_el}
