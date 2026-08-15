"""Seed de demostración: territorios y gazetteer del storyboard de la épica.

Idempotente — se puede correr las veces que haga falta. Para datos DANE
reales usar (cuando exista) el cargador oficial; este seed es solo para
desarrollo local y demos de la colección Bruno.

Uso: poetry run python scripts/seed_demo.py
"""

from __future__ import annotations

from sqlalchemy import text

from radar_core import db, ddl
from radar_core.seed.loader import cargar_gazetteer, cargar_territorio

PCODES_DEMO = ("76364", "76364001", "76364V01", "27660", "27660C01", "76828", "76828V01")


def _cuadro(lon0, lat0, lon1, lat1) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]],
    }


def main() -> None:
    eng = db.engine()
    ddl.init_db(eng)
    with db.session_factory()() as s:
        # geo: upsert por pcode (ON CONFLICT en el loader)
        cargar_territorio(
            s, pcode="76364", nombre="Jamundí", nivel="municipio", departamento="Valle del Cauca",
            geometria=_cuadro(-76.65, 3.15, -76.45, 3.35), poblacion_estimada=5000,
            factor_accesibilidad=1.0, priorizado=True,
        )
        cargar_territorio(
            s, pcode="76364001", nombre="Potrerito", nivel="centro_poblado", departamento="Valle del Cauca",
            municipio_pcode="76364", geometria=_cuadro(-76.60, 3.20, -76.55, 3.25),
            poblacion_estimada=300, priorizado=True,
        )
        cargar_territorio(
            s, pcode="76364V01", nombre="La Cabaña (Jamundí)", nivel="vereda", departamento="Valle del Cauca",
            municipio_pcode="76364", geometria=_cuadro(-76.54, 3.28, -76.52, 3.30),
            poblacion_estimada=40, factor_accesibilidad=0.5, priorizado=True,
        )
        cargar_territorio(
            s, pcode="27660", nombre="San José del Palmar", nivel="municipio", departamento="Chocó",
            geometria=_cuadro(-76.35, 4.90, -76.15, 5.05), poblacion_estimada=4000,
            factor_accesibilidad=0.4, priorizado=True,
        )
        cargar_territorio(
            s, pcode="27660C01", nombre="San Pedro", nivel="centro_poblado", departamento="Chocó",
            municipio_pcode="27660", geometria=_cuadro(-76.26, 4.96, -76.21, 5.01),
            poblacion_estimada=30, factor_accesibilidad=0.3, priorizado=True,
        )
        cargar_territorio(
            s, pcode="76828", nombre="Riofrío", nivel="municipio", departamento="Valle del Cauca",
            geometria=_cuadro(-76.35, 4.10, -76.25, 4.25), poblacion_estimada=2000,
        )
        cargar_territorio(
            s, pcode="76828V01", nombre="La Cabaña (Riofrío)", nivel="vereda", departamento="Valle del Cauca",
            municipio_pcode="76828", geometria=None, poblacion_estimada=25,
        )

        # gazetteer: delete + insert de los pcodes de demo (idempotente)
        s.execute(
            text("DELETE FROM gazetteer WHERE pcode = ANY(:pcodes)"), {"pcodes": list(PCODES_DEMO)}
        )
        cargar_gazetteer(s, nombre="Jamundí", pcode="76364", nivel="municipio")
        cargar_gazetteer(s, nombre="Riofrío", pcode="76828", nivel="municipio")
        cargar_gazetteer(s, nombre="San José del Palmar", pcode="27660", nivel="municipio")
        cargar_gazetteer(
            s, nombre="San José", pcode="27660", nivel="municipio",
            nombre_oficial="San José del Palmar", es_alias=True,
        )
        cargar_gazetteer(
            s, nombre="La Cabaña", pcode="76364V01", nivel="vereda",
            nombre_oficial="La Cabaña (Jamundí)", municipio_pcode="76364", municipio_nombre="Jamundí",
        )
        cargar_gazetteer(
            s, nombre="La Cabaña", pcode="76828V01", nivel="vereda",
            nombre_oficial="La Cabaña (Riofrío)", municipio_pcode="76828", municipio_nombre="Riofrío",
        )
        cargar_gazetteer(
            s, nombre="San Pedro", pcode="27660C01", nivel="centro_poblado",
            nombre_oficial="San Pedro (San José del Palmar)", municipio_pcode="27660",
            municipio_nombre="San José del Palmar",
        )
        cargar_gazetteer(
            s, nombre="Potrerito", pcode="76364001", nivel="centro_poblado",
            municipio_pcode="76364", municipio_nombre="Jamundí",
        )
        s.commit()
        n_geo = s.execute(text("SELECT count(*) FROM geo_divipola")).scalar_one()
        n_gaz = s.execute(text("SELECT count(*) FROM gazetteer")).scalar_one()
    print(f"seed demo listo · geo_divipola: {n_geo} · gazetteer: {n_gaz}")
    print("nota: el servicio recoge el gazetteer al arrancar o vía POST /internal/run_jobs")


if __name__ == "__main__":
    main()
