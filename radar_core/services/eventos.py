"""crear_evento y consultar_folio — el corazón del contrato.

- Idempotencia REAL: constraint único en DB sobre idempotency_key. Reintento de
  la plataforma con la misma key → mismo folio, cero eventos nuevos (U-20, I-05, S-10).
  Misma key con payload distinto → se retorna el original + warning (U-21).
- Validación de esquema server-side con error estructurado (U-30..35).
- Duplicado posible (mismo destino/categoría en ventana) → warning, no bloqueo (S-14),
  y alerta de duplicación a la otra organización (épica, paso 4).
- Detección de patrón coordinado → alerta interna, no bloqueo (X-08).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from geoalchemy2.elements import WKTElement
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ErrorEstructurado
from ..folios import generar_folio, normalizar_folio
from ..models import AlertaInterna, Event, Notificacion, Reconciliacion
from ..schemas import PAYLOADS, CrearEventoRequest
from ..security import cifrar_ref, hash_reporter


def _fingerprint(tipo: str, payload: dict) -> str:
    base = json.dumps({"t": tipo, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(base.encode()).hexdigest()


def _validar_payload(tipo: str, payload: dict) -> dict:
    modelo = PAYLOADS[tipo]
    try:
        return modelo.model_validate(payload).model_dump(mode="json", exclude_none=True)
    except ValidationError as e:
        primero = e.errors()[0]
        campo = ".".join(str(p) for p in primero["loc"]) or None
        raise ErrorEstructurado(
            codigo="payload_invalido",
            campo=f"payload.{campo}" if campo else "payload",
            motivo=primero["msg"],
            status=400,
        ) from None


def _categorias_de(tipo: str, payload: dict) -> set[str]:
    if tipo == "dispatch":
        return {i["categoria"] for i in payload.get("items", [])}
    return set(payload.get("categorias", []))


def _detectar_duplicado(session: Session, tipo: str, payload: dict, reporter_hash: str) -> list[dict]:
    """Mismo pcode + intersección de categorías en la ventana → warning (S-14).

    Para dispatch de OTRA organización al mismo destino, además se encola
    alerta_duplicacion (épica paso 4)."""
    s = get_settings()
    corte = dt.datetime.now(dt.UTC) - dt.timedelta(hours=s.ventana_duplicado_horas)
    previos = session.execute(
        select(Event).where(
            Event.type == tipo,
            Event.pcode == payload["pcode"],
            Event.created_at >= corte,
        )
    ).scalars().all()
    cats = _categorias_de(tipo, payload)
    warnings: list[dict] = []
    for p in previos:
        if _categorias_de(tipo, p.payload) & cats:
            warnings.append(
                {
                    "codigo": "posible_duplicado",
                    "motivo": f"Ya existe un evento {tipo} para este destino y categoría en la ventana reciente",
                    "folio_relacionado": p.folio,
                }
            )
            if tipo == "dispatch" and p.reporter_hash != reporter_hash:
                _encolar_notificacion(
                    session,
                    clave=f"dup:{p.folio}:{payload['pcode']}",
                    destinatario_hash_evento=p,
                    plantilla="alerta_duplicacion",
                    variables={"pcode": payload["pcode"], "folio_propio": p.folio},
                )
            break
    return warnings


def _encolar_notificacion(session, clave, destinatario_hash_evento, plantilla, variables, adjunto_url=None):
    """El outbox guarda la ref cifrada. No hay ref en claro: la que viene en el
    request del evento original no se guardó, así que la duplicación notifica
    usando la ref cifrada almacenada en la notificación previa del mismo folio
    si existe; si no, se omite (no hay manera segura de derivarla)."""
    # destinatario_hash_evento es el Event previo: no tenemos su ref en claro.
    # Solo podemos notificar si su acta/notify previo dejó ref cifrada.
    previa = session.execute(
        select(Notificacion).where(Notificacion.variables["folio"].astext == destinatario_hash_evento.folio)
    ).scalars().first()
    if previa is None:
        return
    existe = session.execute(select(Notificacion).where(Notificacion.clave_unica == clave)).scalars().first()
    if existe:
        return
    session.add(
        Notificacion(
            destinatario_cifrado=previa.destinatario_cifrado,
            plantilla=plantilla,
            variables=variables,
            clave_unica=clave,
        )
    )


def _detectar_patron_coordinado(session: Session, fingerprint: str, reporter_hash: str) -> None:
    s = get_settings()
    corte = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=s.patron_coordinado_ventana_min)
    n = session.execute(
        text(
            """
            SELECT count(DISTINCT reporter_hash) FROM events
            WHERE payload_fingerprint = :fp AND created_at >= :corte AND reporter_hash != :rh
            """
        ),
        {"fp": fingerprint, "corte": corte, "rh": reporter_hash},
    ).scalar_one()
    if n + 1 >= s.patron_coordinado_min_eventos:
        session.add(
            AlertaInterna(
                tipo="patron_coordinado",
                detalle={"fingerprint": fingerprint, "reportantes_distintos": n + 1},
            )
        )


def crear_evento(session: Session, req: CrearEventoRequest) -> dict:
    settings = get_settings()
    payload = _validar_payload(req.type, req.payload)
    reporter_hash = hash_reporter(req.reporter_ref)
    fingerprint = _fingerprint(req.type, payload)

    # Idempotencia: ¿la key ya existe? (camino rápido)
    existente = session.execute(
        select(Event).where(Event.idempotency_key == req.idempotency_key)
    ).scalars().first()
    if existente is not None:
        return _respuesta_existente(existente, fingerprint, settings)

    warnings = _detectar_duplicado(session, req.type, payload, reporter_hash)
    _detectar_patron_coordinado(session, fingerprint, reporter_hash)

    folio = generar_folio(session, req.type)
    cita = normalizar_folio(payload.get("folio_citado", "")) if req.type == "receipt" else None
    corrige = normalizar_folio(payload.get("corrige_folio", "")) if payload.get("corrige_folio") else None

    pin = payload.get("pin")
    evento = Event(
        folio=folio,
        type=req.type,
        payload=payload,
        pin=WKTElement(f"POINT({pin['lon']} {pin['lat']})", srid=4326) if pin else None,
        pcode=payload["pcode"],
        reporter_hash=reporter_hash,
        idempotency_key=req.idempotency_key,
        payload_fingerprint=fingerprint,
        cita_folio=cita,
        corrige_folio=corrige,
    )
    session.add(evento)
    try:
        session.commit()
    except IntegrityError:
        # Carrera: otro request con la misma key ganó el insert (I-05, P-05).
        session.rollback()
        ganador = session.execute(
            select(Event).where(Event.idempotency_key == req.idempotency_key)
        ).scalars().first()
        if ganador is None:
            raise ErrorEstructurado(codigo="conflicto", motivo="Conflicto de escritura, reintentar", status=409)
        return _respuesta_existente(ganador, fingerprint, settings)

    acta_url = None
    if req.type == "dispatch":
        acta_url = f"{settings.public_base_url}/actas/{folio}.pdf"
        # La ref cifrada queda en el outbox para el comprobante posterior (comprobante_listo).
        session.add(
            Notificacion(
                destinatario_cifrado=cifrar_ref(req.reporter_ref),
                plantilla="acta_registrada",
                variables={"folio": folio},
                estado="interna",  # ancla de destinatario; no se envía
                clave_unica=f"ancla:{folio}",
            )
        )
        session.commit()

    return {"folio": folio, "warnings": warnings, "acta_url": acta_url}


def _respuesta_existente(evento: Event, fingerprint: str, settings) -> dict:
    warnings = []
    if evento.payload_fingerprint != fingerprint:
        warnings.append(
            {
                "codigo": "idempotency_payload_distinto",
                "motivo": "La idempotency_key ya fue usada con un payload diferente; se retorna el evento original",
                "folio_relacionado": evento.folio,
            }
        )
    acta_url = f"{settings.public_base_url}/actas/{evento.folio}.pdf" if evento.type == "dispatch" else None
    return {"folio": evento.folio, "warnings": warnings, "acta_url": acta_url}


def consultar_folio(session: Session, folio_crudo: str) -> dict:
    folio = normalizar_folio(folio_crudo)
    if folio is None:
        return {"existe": False}
    evento = session.execute(select(Event).where(Event.folio == folio)).scalars().first()
    if evento is None:
        return {"existe": False}
    recon = session.execute(
        select(Reconciliacion).where(
            (Reconciliacion.dispatch_folio == folio) | (Reconciliacion.receipt_folio == folio)
        )
    ).scalars().first()
    estado = "reconciliado" if recon else "registrado"
    cats = sorted(_categorias_de(evento.type, evento.payload))
    resumen = f"{evento.type} · {', '.join(cats)} · {evento.pcode}"
    return {"existe": True, "type": evento.type, "estado": estado, "resumen": resumen}
