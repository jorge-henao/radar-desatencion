"""Errores estructurados del contrato Agente↔Core.

Todo rechazo lleva {codigo, campo, motivo} — suficiente para que el agente
formule una repregunta sin lógica adicional (S-03). Nunca se filtran
stack traces ni SQL (X-04).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorEstructurado(Exception):
    def __init__(self, codigo: str, motivo: str, campo: str | None = None, status: int = 400):
        self.codigo = codigo
        self.campo = campo
        self.motivo = motivo
        self.status = status
        super().__init__(motivo)

    def detalle(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "campo": self.campo, "motivo": self.motivo}


def _errores_pydantic(exc: RequestValidationError) -> list[dict[str, Any]]:
    errores = []
    for e in exc.errors():
        campo = ".".join(str(p) for p in e["loc"] if p not in ("body",))
        errores.append(
            {
                "codigo": "validacion",
                "campo": campo or None,
                "motivo": e["msg"],
            }
        )
    return errores


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorEstructurado)
    async def _estructurado(request: Request, exc: ErrorEstructurado):
        return JSONResponse(status_code=exc.status, content={"errores": [exc.detalle()]})

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        # JSON malformado o esquema inválido → 400 estructurado, no 422 crudo ni 500 (S-02)
        return JSONResponse(status_code=400, content={"errores": _errores_pydantic(exc)})

    @app.exception_handler(Exception)
    async def _interno(request: Request, exc: Exception):
        # Jamás exponer detalles internos (X-04)
        return JSONResponse(
            status_code=500,
            content={"errores": [{"codigo": "error_interno", "campo": None, "motivo": "Error interno"}]},
        )
