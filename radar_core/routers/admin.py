"""Endpoints operativos internos (mismo token de workspace).

`run_jobs` ejecuta a demanda el ciclo que en producción corre cada 5 minutos:
reconciliación → outbox de notificaciones → export estático. Útil para demos,
colecciones de API (Bruno) y operación manual.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import engine, get_session
from ..security import requiere_token
from ..services import export
from ..services.gazetteer import gazetteer
from ..services.notificador import procesar_outbox
from ..services.reconciliacion import reconciliar

router = APIRouter(prefix="/internal", dependencies=[Depends(requiere_token)])


@router.post("/run_jobs")
def run_jobs(session: Session = Depends(get_session)):
    gazetteer.refresh(session)  # recoge seeds/cambios del gazetteer sin reiniciar
    resultado_recon = reconciliar(session)
    resultado_outbox = procesar_outbox(session)
    resultado_export = export.exportar(engine())
    return {
        "reconciliacion": resultado_recon,
        "outbox": resultado_outbox,
        "export": resultado_export,
    }
