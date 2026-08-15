"""Modelo de datos del Radar Core.

Invariantes que este esquema encarna:
- `events` es append-only (trigger en ddl.py bloquea UPDATE/DELETE a nivel de DB).
- Ninguna columna puede almacenar PII: no hay teléfono, no hay reporter_ref en claro.
  Solo `reporter_hash` (HMAC irreversible). El outbox de notificaciones guarda la
  ref cifrada, nunca en claro.
- El pin exacto (`pin`) es zona privada: jamás sale en export, acta ni notify.
"""

from __future__ import annotations

import datetime as dt
import uuid

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_events_idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    folio: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)  # need | dispatch | receipt
    payload: Mapped[dict] = mapped_column(JSONB)
    # Zona privada: el pin exacto nunca se publica.
    pin = mapped_column(Geography("POINT", srid=4326), nullable=True)
    pcode: Mapped[str | None] = mapped_column(String(24), index=True)
    reporter_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    payload_fingerprint: Mapped[str] = mapped_column(String(64))
    # Folio que este evento cita (receipt→dispatch) o corrige.
    cita_folio: Mapped[str | None] = mapped_column(String(16), index=True)
    corrige_folio: Mapped[str | None] = mapped_column(String(16), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class GeoDivipola(Base):
    """Polígonos DANE (municipios, centros poblados, veredas) + atributos de priorización."""

    __tablename__ = "geo_divipola"

    pcode: Mapped[str] = mapped_column(String(24), primary_key=True)
    nombre: Mapped[str] = mapped_column(Text)
    nivel: Mapped[str] = mapped_column(String(24))  # municipio | centro_poblado | vereda
    departamento: Mapped[str | None] = mapped_column(Text)
    municipio_pcode: Mapped[str | None] = mapped_column(String(24), index=True)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    poblacion_estimada: Mapped[int | None] = mapped_column(Integer)
    factor_accesibilidad: Mapped[float] = mapped_column(Float, default=1.0)
    priorizado: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class GazetteerEntry(Base):
    """Nombre de lugar → pcode. Alias incluidos. Es lo que hace posible el canal de voz."""

    __tablename__ = "gazetteer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(Text)
    nombre_norm: Mapped[str] = mapped_column(Text, index=True)
    es_alias: Mapped[bool] = mapped_column(Boolean, default=False)
    pcode: Mapped[str] = mapped_column(String(24), index=True)
    nivel: Mapped[str] = mapped_column(String(24))
    nombre_oficial: Mapped[str] = mapped_column(Text)
    municipio_pcode: Mapped[str | None] = mapped_column(String(24))
    municipio_nombre_norm: Mapped[str | None] = mapped_column(Text)


class Reconciliacion(Base):
    __tablename__ = "reconciliaciones"
    __table_args__ = (UniqueConstraint("dispatch_folio", "receipt_folio", name="uq_recon_par"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispatch_folio: Mapped[str] = mapped_column(String(16), index=True)
    receipt_folio: Mapped[str] = mapped_column(String(16), index=True)
    metodo: Mapped[str] = mapped_column(String(24))  # deterministico | probabilistico
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notificacion(Base):
    """Outbox del notificador. El Core nunca envía mensajes directamente:
    decide el cuándo y el qué; la plataforma resuelve el a quién y el cómo."""

    __tablename__ = "notificaciones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Ref del destinatario CIFRADA (Fernet). Nunca en claro, nunca el hash (no es reversible).
    destinatario_cifrado: Mapped[str] = mapped_column(Text)
    plantilla: Mapped[str] = mapped_column(String(48))  # comprobante_listo | alerta_duplicacion | alerta_desfase
    variables: Mapped[dict] = mapped_column(JSONB, default=dict)
    adjunto_url: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(16), default="pendiente", index=True)  # pendiente|enviada|fallida
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    # Clave de negocio para no encolar dos veces la misma notificación.
    clave_unica: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertaInterna(Base):
    """Alertas operativas internas (ej. patrón coordinado, X-08). No bloquean."""

    __tablename__ = "alertas_internas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(48))
    detalle: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
