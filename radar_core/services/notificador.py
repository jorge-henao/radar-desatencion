"""Notificador — procesa el outbox contra la API de salida proactiva de la plataforma.

El Core decide el *cuándo* y el *qué*; la plataforma resuelve el *a quién*
(ref → teléfono) y el *cómo* (canal, plantilla, ventana de 24 h). El Core
JAMÁS envía mensajes directamente (I-30).

Reintentos con backoff exponencial; una notificación se marca `enviada` solo
tras 2xx — no se pierde ni se duplica (I-31).
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..security import descifrar_ref
from ..models import Notificacion


def procesar_outbox(session: Session, transport: httpx.BaseTransport | None = None) -> dict:
    s = get_settings()
    pendientes = session.execute(
        select(Notificacion).where(Notificacion.estado == "pendiente")
    ).scalars().all()

    enviadas = fallidas = 0
    with httpx.Client(transport=transport, timeout=10.0) as client:
        for n in pendientes:
            ok = _enviar(client, n, s)
            if ok:
                n.estado = "enviada"
                enviadas += 1
            else:
                n.estado = "fallida" if n.intentos >= s.notify_max_intentos else "pendiente"
                fallidas += 1
            session.commit()
    return {"enviadas": enviadas, "fallidas": fallidas}


def _enviar(client: httpx.Client, n: Notificacion, s) -> bool:
    cuerpo = {
        # La ref viaja a la plataforma (que es quien la resuelve); nunca se loguea.
        "reporter_ref": descifrar_ref(n.destinatario_cifrado),
        "plantilla": n.plantilla,
        "variables": n.variables,
        "notificacion_id": str(n.id),  # idempotencia del lado de la plataforma
    }
    if n.adjunto_url:
        cuerpo["adjunto_url"] = n.adjunto_url

    for intento in range(s.notify_max_intentos):
        n.intentos += 1
        try:
            resp = client.post(s.plataforma_notify_url, json=cuerpo)
            if 200 <= resp.status_code < 300:
                return True
        except httpx.HTTPError:
            pass
        if intento < s.notify_max_intentos - 1 and s.notify_backoff_base_seg > 0:
            time.sleep(s.notify_backoff_base_seg * (2**intento))
    return False
