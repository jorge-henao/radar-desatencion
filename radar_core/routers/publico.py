"""Salida pública: actas, comprobantes y export estático.

El export se sirve como archivos estáticos generados por el job: el request
path NUNCA toca la base de datos. Detrás va Cloudflare.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..errors import ErrorEstructurado
from ..folios import normalizar_folio
from ..models import Event, Reconciliacion
from ..services import actas as svc_actas

router = APIRouter()


@router.get("/actas/{nombre}")
def acta(nombre: str, session: Session = Depends(get_session)):
    folio = normalizar_folio(nombre.removesuffix(".pdf"))
    if folio is None:
        raise ErrorEstructurado(codigo="folio_invalido", campo="folio", motivo="Folio no reconocido", status=404)
    ruta = svc_actas.ruta_acta(folio)
    if not ruta.exists():
        # Generación perezosa: verifica que el dispatch exista antes de generar.
        evento = session.execute(select(Event).where(Event.folio == folio)).scalars().first()
        if evento is None or evento.type != "dispatch":
            raise ErrorEstructurado(codigo="no_encontrado", campo="folio", motivo="Acta inexistente", status=404)
        svc_actas.generar_acta(folio, evento.pcode, evento.payload.get("nombre_lugar"))
    return FileResponse(ruta, media_type="application/pdf", filename=f"{folio}.pdf")


@router.get("/comprobantes/{nombre}")
def comprobante(nombre: str, session: Session = Depends(get_session)):
    folio = normalizar_folio(nombre.removesuffix(".pdf"))
    if folio is None:
        raise ErrorEstructurado(codigo="folio_invalido", campo="folio", motivo="Folio no reconocido", status=404)
    ruta = svc_actas.ruta_comprobante(folio)
    if not ruta.exists():
        recon = session.execute(
            select(Reconciliacion).where(Reconciliacion.dispatch_folio == folio)
        ).scalars().first()
        if recon is None:
            raise ErrorEstructurado(
                codigo="no_encontrado", campo="folio", motivo="Comprobante inexistente", status=404
            )
        receipt = session.execute(select(Event).where(Event.folio == recon.receipt_folio)).scalars().first()
        hogares = receipt.payload.get("hogares") if receipt else None
        svc_actas.generar_comprobante(folio, recon.receipt_folio, hogares, recon.metodo)
    return FileResponse(ruta, media_type="application/pdf", filename=f"comprobante-{folio}.pdf")


@router.get("/health")
def health():
    return {"ok": True, "servicio": "radar-core"}
