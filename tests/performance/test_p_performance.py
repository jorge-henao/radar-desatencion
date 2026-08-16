"""P-01..P-09 — presupuestos de latencia y concurrencia.

Un tool call síncrono bloquea una conversación de voz: el silencio al teléfono
es el peor UX posible y dispara reintentos de la plataforma.

Duraciones largas (P-06) corren acortadas por defecto; RADAR_PERF_FULL=1 las
ejecuta al tamaño completo de la suite.
"""

import json
import os
import statistics
import threading
import time
import uuid

import pytest
from sqlalchemy import text

from radar_core import db as db_mod
from radar_core.config import settings
from radar_core.services import export
from radar_core.services.geo import resolver_texto
from tests.conftest import AUTH, PIN_SAN_PEDRO, crear_evento

pytestmark = pytest.mark.performance

FULL = os.environ.get("RADAR_PERF_FULL") == "1"


def _p95(muestras):
    muestras = sorted(muestras)
    return muestras[int(len(muestras) * 0.95) - 1]


def _medir(fn, n=40):
    tiempos = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        tiempos.append(time.perf_counter() - t0)
    return _p95(tiempos)


class TestLatencia:
    def test_p01_resolver_pin_p95(self, client):
        def llamada():
            r = client.post("/tools/resolver_ubicacion", json=PIN_SAN_PEDRO, headers=AUTH)
            assert r.status_code == 200

        assert _medir(llamada) <= 0.5, "point-in-polygon indexado: ≤500 ms p95"

    def test_p02_resolver_texto_fuzzy_p95(self, client):
        def llamada():
            r = client.post(
                "/tools/resolver_ubicacion",
                json={"texto": "la beredita la cabaña por jamundi"},
                headers=AUTH,
            )
            assert r.status_code == 200

        assert _medir(llamada) <= 1.5, "voz tolera ~2 s de pausa: ≤1.5 s p95"

    def test_p03_crear_evento_p95_sin_pdf_en_el_camino(self, client):
        tiempos = []

        def llamada(i):
            cuerpo = {
                "type": "dispatch",
                "payload": {
                    "pcode": "27660C01",
                    "items": [{"categoria": "agua", "cantidad": 10, "unidad": "bidones"}],
                },
                "reporter_ref": f"ref-perf-{i}",
                "idempotency_key": f"p03-{i}",
            }
            t0 = time.perf_counter()
            r = client.post("/tools/crear_evento", json=cuerpo, headers=AUTH)
            tiempos.append(time.perf_counter() - t0)
            assert r.status_code == 200

        for i in range(40):
            llamada(i)
        assert _p95(tiempos) <= 1.0, "el PDF del acta se genera fuera del request path"

    def test_p04_consultar_folio_p95(self, client, db):
        folio = crear_evento(db, "dispatch")["folio"]

        def llamada():
            r = client.get(f"/tools/consultar_folio?folio={folio}", headers=AUTH)
            assert r.status_code == 200

        assert _medir(llamada) <= 0.3


class TestConcurrencia:
    def test_p05_carrera_idempotencia_50_concurrentes(self, db):
        key = f"p05-{uuid.uuid4()}"
        resultados, errores = [], []
        arranque = threading.Barrier(50)

        def worker():
            factory = db_mod.session_factory()
            try:
                arranque.wait(timeout=30)
                with factory() as s:
                    resultados.append(crear_evento(s, "receipt", key=key, reporter_ref=f"r-{uuid.uuid4()}"))
            except Exception as e:  # noqa: BLE001
                errores.append(e)

        hilos = [threading.Thread(target=worker) for _ in range(50)]
        t0 = time.perf_counter()
        [h.start() for h in hilos]
        [h.join(timeout=60) for h in hilos]
        duracion = time.perf_counter() - t0

        assert not errores, errores[:3]
        assert len(resultados) == 50
        assert len({r["folio"] for r in resultados}) == 1, "50 respuestas idénticas"
        n = db.execute(text("SELECT count(*) FROM events WHERE idempotency_key = :k"), {"k": key}).scalar_one()
        assert n == 1
        assert duracion < 30, "sin deadlocks"

    def test_p06_rafaga_sostenida_sin_degradar(self, client):
        duracion_seg = 300 if FULL else 15
        objetivo_rps = 20
        tiempos, errores = [], []
        lock = threading.Lock()
        fin = time.monotonic() + duracion_seg

        def worker(wid):
            i = 0
            while time.monotonic() < fin:
                cuerpo = {
                    "type": "receipt",
                    "payload": {"pcode": "27660C01", "categorias": ["agua"], "hogares": 5},
                    "reporter_ref": f"ref-w{wid}-{i}",  # reporters distintos: el rate limit no aplica
                    "idempotency_key": f"p06-{wid}-{i}",
                }
                t0 = time.perf_counter()
                r = client.post("/tools/crear_evento", json=cuerpo, headers=AUTH)
                dt_ = time.perf_counter() - t0
                with lock:
                    tiempos.append(dt_)
                    if r.status_code != 200:
                        errores.append(r.status_code)
                i += 1
                time.sleep(max(0.0, (4 / objetivo_rps) - dt_))  # 4 workers ≈ 20 rps agregados

        hilos = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]

        assert not errores
        assert len(tiempos) >= duracion_seg * 10, "throughput sostenido"
        assert _p95(tiempos) <= 1.0, f"p95 degradado: {_p95(tiempos):.3f}s"

    def test_p08_refresh_concurrente_no_bloquea_tool_calls(self, client, db):
        from radar_core import ddl

        ddl.refresh_mvs(db_mod.engine(), concurrently=False)  # asegura MV poblada
        detener = threading.Event()
        errores = []

        def refrescar():
            while not detener.is_set():
                try:
                    ddl.refresh_mvs(db_mod.engine(), concurrently=True)
                except Exception as e:  # noqa: BLE001
                    errores.append(e)

        hilo = threading.Thread(target=refrescar)
        hilo.start()
        try:
            tiempos = []
            for i in range(30):
                cuerpo = {
                    "type": "receipt",
                    "payload": {"pcode": "76364", "categorias": ["agua"], "hogares": 3},
                    "reporter_ref": f"ref-p08-{i}",
                    "idempotency_key": f"p08-{i}",
                }
                t0 = time.perf_counter()
                assert client.post("/tools/crear_evento", json=cuerpo, headers=AUTH).status_code == 200
                tiempos.append(time.perf_counter() - t0)
        finally:
            detener.set()
            hilo.join(timeout=30)
        assert not errores
        assert _p95(tiempos) <= 1.0, "las escrituras no esperan al refresh"


class TestVolumen:
    @pytest.fixture()
    def volumen_30_dias(self, db):
        """~400 pcodes priorizados y ~50k eventos de un mes de emergencia."""
        db.execute(
            text(
                """
                INSERT INTO geo_divipola (pcode, nombre, nivel, departamento, poblacion_estimada,
                                          factor_accesibilidad, priorizado, geom)
                SELECT 'PERF-' || i, 'Territorio ' || i, 'vereda', 'Perf', 100, 1.0, true,
                       ST_Multi(ST_MakeEnvelope(-75 + (i % 40) * 0.01, 6 + (i / 40) * 0.01,
                                                -75 + (i % 40) * 0.01 + 0.005, 6 + (i / 40) * 0.01 + 0.005, 4326))
                FROM generate_series(1, 400) AS i
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO events (id, folio, type, payload, pcode, reporter_hash,
                                    idempotency_key, payload_fingerprint, created_at)
                SELECT gen_random_uuid(),
                       'RC-P' || i,
                       CASE WHEN i % 3 = 0 THEN 'need' WHEN i % 3 = 1 THEN 'dispatch' ELSE 'receipt' END,
                       CASE WHEN i % 3 = 0 THEN '{"categorias": ["agua"], "hogares_rango": "6-20"}'::jsonb
                            WHEN i % 3 = 1 THEN '{"items": [{"categoria": "agua", "cantidad": 5, "unidad": "kits"}]}'::jsonb
                            ELSE '{"categorias": ["agua"], "hogares": 8}'::jsonb
                       END,
                       'PERF-' || (1 + i % 400),
                       md5('rep' || (i % 900)),
                       'perf-key-' || i,
                       md5('fp' || i),
                       now() - (i % 30) * interval '1 day'
                FROM generate_series(1, 50000) AS i
                """
            )
        )
        db.commit()
        yield
        db.execute(text("TRUNCATE events"))
        db.execute(text("DELETE FROM geo_divipola WHERE pcode LIKE 'PERF-%'"))
        db.commit()
        from radar_core import ddl

        ddl.refresh_mvs(db_mod.engine(), concurrently=False)
        export.exportar(db_mod.engine())

    def test_p07_export_de_un_mes_bajo_2_minutos(self, volumen_30_dias):
        t0 = time.perf_counter()
        resultado = export.exportar(db_mod.engine())
        duracion = time.perf_counter() - t0
        assert resultado["territorios"] >= 400
        assert duracion < 120, f"export tardó {duracion:.1f}s (ventana de 5 min)"
        fc = json.loads((__import__("pathlib").Path(settings.export_dir) / "datos.geojson").read_text())
        assert len(fc["features"]) >= 400

    def test_p09_gazetteer_a_escala_de_85_municipios(self, db):
        from radar_core.seed.loader import cargar_gazetteer
        from radar_core.services.gazetteer import gazetteer

        for m in range(85):
            cargar_gazetteer(db, nombre=f"Municipio Escala {m}", pcode=f"ESC-M{m}", nivel="municipio")
            for v in range(30):
                cargar_gazetteer(
                    db, nombre=f"Vereda {m}-{v} Escala", pcode=f"ESC-{m}-{v}", nivel="vereda",
                    municipio_pcode=f"ESC-M{m}", municipio_nombre=f"Municipio Escala {m}",
                )
        db.commit()
        try:
            gazetteer.refresh(db)
            tiempos = []
            for _ in range(30):
                t0 = time.perf_counter()
                r = resolver_texto("la beredita la cabaña por jamundi")
                tiempos.append(time.perf_counter() - t0)
            assert r["pcode"] == "76364V01", "la precisión no se degrada con el volumen"
            assert _p95(tiempos) <= 1.5, f"p95 {_p95(tiempos):.3f}s con ~2.6k entradas"
        finally:
            db.execute(text("DELETE FROM gazetteer WHERE pcode LIKE 'ESC-%'"))
            db.commit()
            gazetteer.refresh(db)
