"""Radar Core — app FastAPI.

Optimizado para Railway: puerto por env PORT, /health como healthcheck,
jobs (reconciliación + export + outbox) en un loop asyncio del propio proceso.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import db, ddl
from .config import get_settings
from .errors import registrar_manejadores
from .routers import admin, publico, tools
from .services.gazetteer import gazetteer

# Logging de acceso propio: método, ruta y status — NUNCA cuerpos, refs ni
# coordenadas (X-02).
log = logging.getLogger("radar_core")


async def _loop_jobs(app: FastAPI) -> None:
    from .services.notificador import procesar_outbox
    from .services.reconciliacion import reconciliar
    from .services import export

    s = get_settings()
    while True:
        await asyncio.sleep(s.export_interval_seg)
        try:
            factory = db.session_factory()
            with factory() as session:
                reconciliar(session)
                procesar_outbox(session)
            await asyncio.to_thread(export.exportar, db.engine())
        except Exception:
            log.exception("fallo en ciclo de jobs; el export anterior sigue vigente")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.ensure_dirs()
    ddl.init_db(db.engine())
    with db.session_factory()() as session:
        gazetteer.refresh(session)
    try:
        # Export inicial: la salida pública existe desde el arranque.
        from .services import export

        export.exportar(db.engine())
    except Exception:
        log.exception("export inicial falló; el loop de jobs lo reintentará")
    tarea = asyncio.create_task(_loop_jobs(app))
    yield
    tarea.cancel()


def create_app(with_jobs: bool = True) -> FastAPI:
    app = FastAPI(title="Radar Core", docs_url=None, redoc_url=None, lifespan=lifespan if with_jobs else None)
    registrar_manejadores(app)

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        response = await call_next(request)
        # Solo método, path y status. La query string puede llevar folios (ok)
        # pero jamás se loguean cuerpos ni headers (X-02).
        log.info("%s %s %s", request.method, request.url.path, response.status_code)
        return response

    app.include_router(tools.router)
    app.include_router(publico.router)
    app.include_router(admin.router)

    s = get_settings()
    s.ensure_dirs()
    app.mount("/public", StaticFiles(directory=s.export_dir, html=True), name="public")
    return app


app = create_app()
