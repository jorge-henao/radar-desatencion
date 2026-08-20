"""Esquemas Pydantic del contrato Agente↔Core.

La validación de dominio vive acá, en el Core — nunca se delega al LLM (U-30..34).
`extra="forbid"` y tipos estrictos: `hogares: "como veinte"` se rechaza, no se
coerce en silencio. El enum de categorías se valida server-side (U-33).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Categoria(str, Enum):
    agua = "agua"
    alimentos = "alimentos"
    medicamentos = "medicamentos"
    aseo = "aseo"
    techo = "techo"
    otro = "otro"


class HogaresRango(str, Enum):
    r1_5 = "1-5"
    r6_20 = "6-20"
    r21_50 = "21-50"
    r50_mas = "+50"
    no_se = "no_se"


class Pin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class _PayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pcode: str = Field(min_length=2, max_length=24)
    pin: Pin | None = None
    nombre_lugar: str | None = Field(default=None, max_length=200)
    # Corrección: este evento reemplaza al folio citado. El log nunca se toca.
    corrige_folio: str | None = None


class NeedPayload(_PayloadBase):
    categorias: Annotated[list[Categoria], Field(min_length=1)]
    hogares_rango: HogaresRango


class DispatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categoria: Categoria
    cantidad: StrictInt = Field(gt=0)
    unidad: str = Field(min_length=1, max_length=40)


class DispatchPayload(_PayloadBase):
    items: Annotated[list[DispatchItem], Field(min_length=1)]
    org_nombre: str | None = Field(default=None, max_length=200)
    eta: str | None = Field(default=None, max_length=64)


class ReceiptPayload(_PayloadBase):
    folio_citado: str | None = None
    categorias: Annotated[list[Categoria], Field(min_length=1)]
    hogares: StrictInt = Field(gt=0)


PAYLOADS = {"need": NeedPayload, "dispatch": DispatchPayload, "receipt": ReceiptPayload}


# --- Requests / responses de la Tools API ---


class CrearEventoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["need", "dispatch", "receipt"]
    payload: dict
    reporter_ref: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)


class CrearEventoResponse(BaseModel):
    folio: str
    warnings: list[dict] = []
    acta_url: str | None = None


class ResolverUbicacionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    texto: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _un_solo_modo(self):
        modo_pin = self.lat is not None and self.lon is not None
        modo_texto = self.texto is not None and self.texto.strip() != ""
        if modo_pin == modo_texto:  # ninguno o ambos (S-23)
            raise ValueError("Enviar exactamente un modo: {lat, lon} (pin) o {texto} (nombre de lugar)")
        return self


class Procedencia(BaseModel):
    """Dónde queda una ubicación, sin que el agente tenga que inferirlo (I-13).

    `municipio_pcode` nunca es null cuando hay ubicación: un municipio es su
    propio municipio. `etiqueta` es el string que el agente puede leer tal cual
    al repreguntar — existe para que el LLM no componga la procedencia él mismo.
    """

    municipio_pcode: str | None = None
    municipio_nombre: str | None = None
    departamento_codigo: str | None = None
    departamento_nombre: str | None = None
    etiqueta: str | None = None


class Candidato(Procedencia):
    pcode: str
    nombre_oficial: str
    nivel: str
    confianza: float


class ResolverUbicacionResponse(Procedencia):
    pcode: str | None
    nivel: str | None
    nombre_oficial: str | None
    confianza: float
    candidatos: list[Candidato] = []
    # "fuera_de_cobertura" (I-12) · "sin_candidatos" (U-54) · "ambiguo" (U-51)
    # · "confianza_baja" (U-57): hubo candidatos pero ninguno alcanza el piso.
    motivo: str | None = None


class ConsultarFolioResponse(BaseModel):
    existe: bool
    type: str | None = None
    estado: str | None = None
    resumen: str | None = None
