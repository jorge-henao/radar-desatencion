"""Carga de datos geográficos DANE reales al Radar Core.

Fuentes (descargadas en data/dane/ — ver README):
  - MGN2023_MPIO_POLITICO.zip  → municipios (todos, polígonos + gazetteer)
  - MGN2023_CLASE.zip          → centros poblados (solo priorizados; la capa
                                 trae polígono y código pero NO nombre)
  - shp_CRVeredas_2024.zip     → veredas (solo priorizados; trae NOMBRE_VER
                                 y SEUDONIMOS → alias del gazetteer)

La curaduría (qué municipios se priorizan, población, accesibilidad vial)
vive en scripts/priorizados.json — editable, con fuentes humanas.

Idempotente: upsert por pcode en geo_divipola; delete+insert por pcode en
gazetteer. Tras cargar con el servicio corriendo: POST /internal/run_jobs.

Uso:
  poetry run python scripts/seed_dane.py                 # todo
  poetry run python scripts/seed_dane.py --solo municipios|centros|veredas
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import shapefile  # pyshp
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar_core import db, ddl  # noqa: E402
from radar_core.seed.loader import cargar_gazetteer, cargar_territorio  # noqa: E402
from radar_core.services.gazetteer import titulo_es  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data" / "dane"
EXTRA = DATA / "extracted"

ZIP_MUNICIPIOS = DATA / "MGN2023_MPIO_POLITICO.zip"
ZIP_CLASE = DATA / "MGN2023_CLASE.zip"
ZIP_VEREDAS = DATA / "shp_CRVeredas_2024.zip"
CURADURIA = Path(__file__).resolve().parent / "priorizados.json"

LOTE_COMMIT = 200


def _abrir(shp: Path) -> shapefile.Reader:
    """Respeta el encoding declarado en el .cpg del shapefile (MGN es UTF-8)."""
    cpg = shp.with_suffix(".cpg")
    encoding = "utf-8"
    if cpg.exists():
        declarado = cpg.read_text().strip().lower()
        if "1252" in declarado or "8859" in declarado or "latin" in declarado:
            encoding = "latin-1"
    return shapefile.Reader(str(shp), encoding=encoding)


def _alias_valido(alias: str) -> bool:
    """SEUDONIMOS trae basura ('1', '-'): solo alias con contenido real."""
    a = alias.strip()
    return len(a) >= 3 and not a.isdigit()


def _extraer(zip_path: Path) -> Path:
    """Extrae el zip (una vez) y retorna la ruta del .shp."""
    destino = EXTRA / zip_path.stem
    if not destino.exists():
        print(f"  extrayendo {zip_path.name}…")
        destino.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(destino)
    shp = next(destino.rglob("*.shp"))
    return shp


def _verificar_crs(shp: Path, primera_geom: dict) -> None:
    """El loader asume grados (4326/MAGNA-SIRGAS geográfico, diferencia <1 m).
    Si el shapefile viniera proyectado en metros, abortar con instrucción."""

    def _coords_planas(geom):
        c = geom["coordinates"]
        while isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)):
            c = c[0]
        return c

    x = _coords_planas(primera_geom)
    if not (-180 <= x[0] <= 180):
        raise SystemExit(
            f"{shp.name}: coordenadas fuera de rango geográfico ({x[0]:.1f}). "
            "El shapefile está proyectado — reproyectar antes: "
            f"ogr2ogr -t_srs EPSG:4326 salida.shp {shp}"
        )


def _cargar_curaduria() -> dict[str, dict]:
    cur = json.loads(CURADURIA.read_text())
    cur.pop("_comentario", None)
    return cur


def _limpiar_gazetteer(session, pcodes: list[str]) -> None:
    if pcodes:
        session.execute(text("DELETE FROM gazetteer WHERE pcode = ANY(:p)"), {"p": pcodes})


def cargar_municipios(session, priorizados: dict) -> None:
    print("• municipios (país completo)…")
    shp = _extraer(ZIP_MUNICIPIOS)
    reader = _abrir(shp)
    campos = [f[0] for f in reader.fields[1:]]
    pcodes, n = [], 0
    for i, sr in enumerate(reader.iterShapeRecords()):
        rec = dict(zip(campos, sr.record))
        geom = sr.shape.__geo_interface__
        if i == 0:
            _verificar_crs(shp, geom)
        pcode = str(rec["mpio_cdpmp"]).strip()
        cur = priorizados.get(pcode)
        cargar_territorio(
            session,
            pcode=pcode,
            nombre=titulo_es(str(rec["mpio_cnmbr"])),
            nivel="municipio",
            departamento=titulo_es(str(rec["dpto_cnmbr"])),
            geometria=geom,
            poblacion_estimada=cur.get("poblacion_estimada") if cur else None,
            factor_accesibilidad=cur.get("factor_accesibilidad", 1.0) if cur else 1.0,
            priorizado=bool(cur),
        )
        pcodes.append(pcode)
        n += 1
        if n % LOTE_COMMIT == 0:
            session.commit()
            print(f"    {n} municipios…", flush=True)
    session.commit()
    _limpiar_gazetteer(session, pcodes)
    reader = _abrir(shp)
    for sr in reader.iterRecords():
        rec = dict(zip(campos, sr))
        cargar_gazetteer(
            session,
            nombre=titulo_es(str(rec["mpio_cnmbr"])),
            pcode=str(rec["mpio_cdpmp"]).strip(),
            nivel="municipio",
        )
    session.commit()
    print(f"  ✓ {n} municipios ({sum(1 for p in pcodes if p in priorizados)} priorizados)")


def cargar_centros_poblados(session, priorizados: dict) -> None:
    """Capa Clase: clas_ccdgo == '2' es centro poblado. Sin nombre en la capa —
    el polígono mejora la resolución de pines; el nombre queda genérico hasta
    cruzar con la tabla DIVIPOLA de centros poblados."""
    print("• centros poblados (solo municipios priorizados)…")
    shp = _extraer(ZIP_CLASE)
    reader = _abrir(shp)
    campos = [f[0] for f in reader.fields[1:]]
    pcodes, n = [], 0
    for i, sr in enumerate(reader.iterShapeRecords()):
        rec = dict(zip(campos, sr.record))
        if str(rec["clas_ccdgo"]).strip() != "2":
            continue
        mpio = str(rec["mpio_cdpmp"]).strip()
        if mpio not in priorizados:
            continue
        geom = sr.shape.__geo_interface__
        if n == 0:
            _verificar_crs(shp, geom)
        pcode = str(rec["clas_ccnct"]).strip()
        cur = priorizados[mpio]
        cargar_territorio(
            session,
            pcode=pcode,
            nombre=f"Centro poblado {pcode}",  # nombre real pendiente de DIVIPOLA-CP
            nivel="centro_poblado",
            municipio_pcode=mpio,
            geometria=geom,
            factor_accesibilidad=cur.get("factor_accesibilidad", 1.0),
            priorizado=True,
        )
        pcodes.append(pcode)
        n += 1
    session.commit()
    print(f"  ✓ {n} centros poblados (sin gazetteer: la capa Clase no trae nombres)")


def cargar_veredas(session, priorizados: dict) -> None:
    print("• veredas (solo municipios priorizados)…")
    shp = _extraer(ZIP_VEREDAS)
    reader = _abrir(shp)
    campos = [f[0] for f in reader.fields[1:]]
    entradas, n = [], 0
    for sr in reader.iterShapeRecords():
        rec = dict(zip(campos, sr.record))
        mpio = str(rec["DPTOMPIO"]).strip()
        if mpio not in priorizados:
            continue
        geom = sr.shape.__geo_interface__
        if n == 0:
            _verificar_crs(shp, geom)
        pcode = f"V{str(rec['CODIGO_VER']).strip()}"
        nombre = titulo_es(str(rec["NOMBRE_VER"]))
        cur = priorizados[mpio]
        cargar_territorio(
            session,
            pcode=pcode,
            nombre=nombre,
            nivel="vereda",
            municipio_pcode=mpio,
            geometria=geom,
            factor_accesibilidad=cur.get("factor_accesibilidad", 1.0),
            priorizado=True,
        )
        seudonimos = [
            s.strip()
            for s in str(rec.get("SEUDONIMOS") or "").replace(";", ",").split(",")
            if _alias_valido(s)
        ]
        entradas.append((nombre, pcode, mpio, seudonimos))
        n += 1
        if n % LOTE_COMMIT == 0:
            session.commit()
            print(f"    {n} veredas…", flush=True)
    session.commit()

    _limpiar_gazetteer(session, [e[1] for e in entradas])
    nombres_mpio = {
        p: d["nombre"].split("(")[0].strip() for p, d in priorizados.items()
    }
    for nombre, pcode, mpio, seudonimos in entradas:
        cargar_gazetteer(
            session, nombre=nombre, pcode=pcode, nivel="vereda",
            municipio_pcode=mpio, municipio_nombre=nombres_mpio.get(mpio),
        )
        for alias in seudonimos:
            cargar_gazetteer(
                session, nombre=alias, pcode=pcode, nivel="vereda", nombre_oficial=nombre,
                es_alias=True, municipio_pcode=mpio, municipio_nombre=nombres_mpio.get(mpio),
            )
    session.commit()
    n_alias = sum(len(e[3]) for e in entradas)
    print(f"  ✓ {n} veredas · {n_alias} alias de SEUDONIMOS al gazetteer")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solo", choices=["municipios", "centros", "veredas"], default=None)
    args = parser.parse_args()

    faltantes = [z.name for z in (ZIP_MUNICIPIOS, ZIP_CLASE, ZIP_VEREDAS) if not z.exists()]
    if faltantes:
        raise SystemExit(f"Faltan archivos en data/dane/: {faltantes} — ver README para descargarlos")

    priorizados = _cargar_curaduria()
    print(f"curaduría: {len(priorizados)} municipios priorizados ({CURADURIA.name})")

    eng = db.engine()
    ddl.init_db(eng)
    with db.session_factory()() as s:
        if args.solo in (None, "municipios"):
            cargar_municipios(s, priorizados)
        if args.solo in (None, "centros"):
            cargar_centros_poblados(s, priorizados)
        if args.solo in (None, "veredas"):
            cargar_veredas(s, priorizados)
        total_geo = s.execute(text("SELECT count(*) FROM geo_divipola")).scalar_one()
        total_gaz = s.execute(text("SELECT count(*) FROM gazetteer")).scalar_one()
    print(f"\nlisto · geo_divipola: {total_geo} · gazetteer: {total_gaz}")
    print("recordá refrescar el servicio: POST /internal/run_jobs (o reiniciarlo)")


if __name__ == "__main__":
    main()
