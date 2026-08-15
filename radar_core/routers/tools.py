"""Tools API — los tres endpoints que invocan los agentes Vozy con @tool_call."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..errors import ErrorEstructurado
from ..schemas import (
    ConsultarFolioResponse,
    CrearEventoRequest,
    CrearEventoResponse,
    ResolverUbicacionRequest,
    ResolverUbicacionResponse,
)
from ..security import hash_reporter, requiere_token
from ..services import eventos as svc_eventos
from ..services import geo as svc_geo
from ..services.actas import generar_acta
from ..services.ratelimit import rate_limiter

router = APIRouter(prefix="/tools", dependencies=[Depends(requiere_token)])


@router.post("/resolver_ubicacion", response_model=ResolverUbicacionResponse)
def resolver_ubicacion(req: ResolverUbicacionRequest, session: Session = Depends(get_session)):
    if req.texto:
        return svc_geo.resolver_texto(req.texto)
    return svc_geo.resolver_pin(session, req.lat, req.lon)


@router.post("/crear_evento", response_model=CrearEventoResponse)
def crear_evento(
    req: CrearEventoRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if not rate_limiter.permitir(hash_reporter(req.reporter_ref)):
        raise ErrorEstructurado(
            codigo="rate_limit",
            motivo="Demasiados eventos en poco tiempo; esperar un momento y reintentar",
            status=429,
        )
    resultado = svc_eventos.crear_evento(session, req)
    if resultado.get("acta_url"):
        # El PDF se genera fuera del request path (P-03); GET /actas la genera
        # perezosamente si aún no existe.
        payload = req.payload or {}
        background.add_task(
            generar_acta,
            resultado["folio"],
            payload.get("pcode"),
            payload.get("nombre_lugar"),
        )
    return resultado


@router.get("/consultar_folio", response_model=ConsultarFolioResponse)
def consultar_folio(folio: str, session: Session = Depends(get_session)):
    # Folio inexistente es un RESULTADO ({existe: false}, 200), no un error (S-26).
    return svc_eventos.consultar_folio(session, folio)
