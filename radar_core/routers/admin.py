"""Endpoints operativos internos (mismo token de workspace).

`run_jobs` ejecuta a demanda el ciclo que en producción corre cada 5 minutos:
Vigía de Medios → reconciliación → outbox de notificaciones → export estático.
Útil para demos, colecciones de API (Bruno) y operación manual.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import engine, get_session
from ..security import requiere_token
from ..services import export
from ..services import vigia as svc_vigia
from ..services.gazetteer import gazetteer
from ..services.notificador import procesar_outbox
from ..services.reconciliacion import reconciliar

router = APIRouter(prefix="/internal", dependencies=[Depends(requiere_token)])


class DescartarSenalRequest(BaseModel):
    operador: str = Field(min_length=1, max_length=120)


@router.post("/run_jobs")
def run_jobs(
    forzar_vigia: bool = Query(False, description="Reintenta Vigía aunque no haya cumplido cadencia."),
    session: Session = Depends(get_session),
):
    gazetteer.refresh(session)  # recoge seeds/cambios del gazetteer sin reiniciar
    cfg = svc_vigia.cargar_config()
    caducadas = svc_vigia.caducar_senales(session, cfg.caducidad_dias)
    run_vigia = svc_vigia.ejecutar_vigia(session, config=cfg, forzar=forzar_vigia)
    resultado_recon = reconciliar(session)
    resultado_outbox = procesar_outbox(session)
    resultado_export = export.exportar(engine())
    return {
        "vigia": {
            "caducadas": caducadas,
            "modo": cfg.modo,
            "run_id": str(run_vigia.id),
            "estado": run_vigia.estado,
            "forzado": forzar_vigia,
        },
        "reconciliacion": resultado_recon,
        "outbox": resultado_outbox,
        "export": resultado_export,
    }


@router.post("/senales/{senal_id}/descartar")
def descartar_senal(senal_id: str, req: DescartarSenalRequest, session: Session = Depends(get_session)):
    ok = svc_vigia.descartar_senal(session, senal_id, req.operador)
    return {"ok": ok}
