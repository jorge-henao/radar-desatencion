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
from . import vigia as svc_vigia

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
                SELECT m.pcode, m.nombre, m.nivel, m.departamento,
                       concat_ws(', ', coalesce(mun.nombre, m.nombre), m.departamento) AS mun,
                       m.estado,
                       m.dias_sin_recepcion, m.poblacion_estimada AS hogares_estimados,
                       m.faltante_reportado, m.factor_accesibilidad, m.score,
                       ST_AsGeoJSON(ST_Simplify(g.geom::geometry, 0.001)) AS geom
                FROM mv_desatencion m
                JOIN geo_divipola g ON g.pcode = m.pcode
                LEFT JOIN geo_divipola mun ON mun.pcode = g.municipio_pcode
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


def _vista_operativa_payload(engine: Engine, filas: list[dict], generado_el: str) -> dict:
    cfg = svc_vigia.cargar_config()
    territorios = {f["pcode"]: _territorio_base(f) for f in filas}
    with engine.connect() as conn:
        senales = conn.execute(
            text(
                """
                SELECT id::text, pcode, localidad_texto, categorias, cita, url,
                       fuente_nombre, fecha_pub, refuerzos, estado
                FROM senales_medios
                WHERE estado IN ('activa', 'convertida') AND pcode IS NOT NULL
                ORDER BY detectada_at DESC
                """
            )
        ).mappings().all()
        needs = conn.execute(
            text(
                """
                WITH corregidos AS (
                    SELECT DISTINCT corrige_folio AS folio FROM events WHERE corrige_folio IS NOT NULL
                )
                SELECT e.pcode, count(DISTINCT e.reporter_hash) AS n
                FROM events e
                LEFT JOIN corregidos c ON c.folio = e.folio
                WHERE e.type = 'need' AND c.folio IS NULL
                GROUP BY e.pcode
                """
            )
        ).mappings().all()
        ultima = conn.execute(
            text(
                """
                SELECT max(finished_at) FROM vigia_runs
                WHERE finished_at IS NOT NULL AND estado IN ('ok', 'parcial')
                """
            )
        ).scalar()
        revision = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE senal_id IS NOT NULL) AS ubicacion_por_confirmar,
                  count(*) FILTER (WHERE senal_id IS NULL) AS localidades_por_incorporar
                FROM localidades_por_incorporar
                WHERE estado = 'pendiente'
                """
            )
        ).mappings().first()
    for n in needs:
        if n["pcode"] in territorios:
            territorios[n["pcode"]]["procedencia"]["reportes"] = int(n["n"])
    for s in senales:
        if cfg.modo == "reportes" and s["estado"] != "convertida":
            continue
        t = territorios.get(s["pcode"])
        if t is None:
            continue
        cats = s["categorias"] or []
        t["procedencia"]["senales"] += int(s["refuerzos"] or 1)
        t["necesidades"] = sorted(set(t["necesidades"]) | set(cats))
        t["senales"].append(
            {
                "cita": s["cita"],
                "fuente": s["fuente_nombre"],
                "url": s["url"],
                "fecha": s["fecha_pub"].isoformat() if s["fecha_pub"] else None,
                "refuerzos": s["refuerzos"],
                "estado": s["estado"],
            }
        )
    salida = list(territorios.values())
    if cfg.modo == "curado":
        salida = [t for t in salida if t["procedencia"]["senales"] or t["alerta_maxima"]]
    elif cfg.modo == "reportes":
        salida = [t for t in salida if t["procedencia"]["reportes"] or t["alerta_maxima"]]
    salida.sort(key=lambda t: (not t["alerta_maxima"], -t["procedencia"]["reportes"], -t["procedencia"]["senales"], -(t["score"] or 0)))
    payload = {
        "generado": generado_el,
        "vigia": {
            "ultima_pasada": ultima.isoformat() if ultima else None,
            "fuentes_activas": len(cfg.fuentes_activas),
            "senales_activas": sum(1 for t in salida for s in t["senales"] if s["estado"] == "activa"),
            "modo": cfg.modo,
        },
        "territorios": salida,
        "revision": {
            "ubicacion_por_confirmar": int((revision or {}).get("ubicacion_por_confirmar") or 0),
            "localidades_por_incorporar": int((revision or {}).get("localidades_por_incorporar") or 0),
        },
        "mensaje_alerta_ausencia": "sin información: eso ES la alerta",
    }
    return payload


def _vista_operativa_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _vista_operativa_html_bytes(payload: dict) -> bytes:
    tpl = _jinja.get_template("vista_operativa.html")
    return tpl.render(datos=payload).encode("utf-8")


def _territorio_base(f: dict) -> dict:
    necesidades = [c for c in (f.get("faltante_reportado") or "").split(",") if c]
    return {
        "pcode": f["pcode"],
        "nombre": f["nombre"],
        "mun": f.get("mun") or f.get("departamento"),
        "alerta_maxima": f.get("estado") == "alerta_maxima",
        "dias_sin_recepcion": f.get("dias_sin_recepcion"),
        "hogares_est": f.get("hogares_estimados"),
        "necesidades": necesidades,
        "score": float(f["score"]) if f.get("score") is not None else None,
        "procedencia": {"senales": 0, "reportes": 0},
        "senales": [],
        "eventos": [],
    }


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
    vista_operativa = _vista_operativa_payload(engine, filas, generado_el)

    _escribir_atomico(export_dir / "datos.csv", _csv_bytes(filas))
    _escribir_atomico(export_dir / "datos.geojson", _geojson_bytes(filas, generado_el))
    _escribir_atomico(export_dir / "tabla.html", _html_bytes(filas, generado_el))
    _escribir_atomico(export_dir / "vista-operativa.json", _vista_operativa_bytes(vista_operativa))
    _escribir_atomico(export_dir / "vista-operativa.html", _vista_operativa_html_bytes(vista_operativa))
    _escribir_atomico(
        export_dir / "meta.json",
        json.dumps({"generado_el": generado_el, "territorios": len(filas)}).encode(),
    )
    return {"territorios": len(filas), "generado_el": generado_el}
