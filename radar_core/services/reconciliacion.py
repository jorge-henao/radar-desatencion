"""Reconciliación DISPATCH↔RECEIPT — corre en batch, fuera de toda conversación.

Dos niveles (I-16, I-17):
- Determinístico: el receipt cita el folio del dispatch (el acta viajó con el camión).
- Probabilístico: sin folio, match por pcode + intersección de categorías + ventana
  temporal — SIEMPRE marcado como tal, distinguible del determinístico.

Además:
- Dispatch sin receipt tras el umbral → alerta_desfase (I-18).
- Al reconciliar → comprobante_listo con el comprobante PDF (I-30, épica paso 7).
- Un receipt citando folio inexistente no rompe el batch (I-19).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Event, Notificacion, Reconciliacion


def _reconciliados(session: Session) -> tuple[set[str], set[str]]:
    filas = session.execute(select(Reconciliacion)).scalars().all()
    return {f.dispatch_folio for f in filas}, {f.receipt_folio for f in filas}


def _cats(evento: Event) -> set[str]:
    if evento.type == "dispatch":
        return {i["categoria"] for i in evento.payload.get("items", [])}
    return set(evento.payload.get("categorias", []))


def reconciliar(session: Session) -> dict:
    """Corre una pasada completa. Retorna contadores para observabilidad."""
    s = get_settings()
    dispatches = session.execute(select(Event).where(Event.type == "dispatch")).scalars().all()
    receipts = session.execute(select(Event).where(Event.type == "receipt")).scalars().all()
    disp_matcheados, rec_matcheados = _reconciliados(session)
    por_folio = {d.folio: d for d in dispatches}

    n_det = n_prob = n_desfase = 0
    no_matcheados: list[str] = []

    # Nivel 1: determinístico por folio citado
    for r in receipts:
        if r.folio in rec_matcheados:
            continue
        if r.cita_folio:
            d = por_folio.get(r.cita_folio)
            if d is None:
                no_matcheados.append(r.folio)  # folio inexistente: a la cola, no rompe (I-19)
                continue
            session.add(Reconciliacion(dispatch_folio=d.folio, receipt_folio=r.folio, metodo="deterministico"))
            disp_matcheados.add(d.folio)
            rec_matcheados.add(r.folio)
            _notificar_comprobante(session, d, r)
            n_det += 1

    # Nivel 2: probabilístico, marcado
    ventana = dt.timedelta(days=s.ventana_reconciliacion_dias)
    for r in receipts:
        if r.folio in rec_matcheados or r.cita_folio:
            continue
        candidatos = [
            d
            for d in dispatches
            if d.folio not in disp_matcheados
            and d.pcode == r.pcode
            and (_cats(d) & _cats(r))
            and d.created_at <= r.created_at <= d.created_at + ventana
        ]
        if candidatos:
            d = min(candidatos, key=lambda x: abs((r.created_at - x.created_at).total_seconds()))
            session.add(Reconciliacion(dispatch_folio=d.folio, receipt_folio=r.folio, metodo="probabilistico"))
            disp_matcheados.add(d.folio)
            rec_matcheados.add(r.folio)
            _notificar_comprobante(session, d, r)
            n_prob += 1
        else:
            no_matcheados.append(r.folio)

    # Desfase: dispatch declarado sin recepción tras N días (I-18)
    corte = dt.datetime.now(dt.UTC) - dt.timedelta(days=s.desfase_dias)
    for d in dispatches:
        if d.folio in disp_matcheados or d.created_at > corte:
            continue
        _encolar_para_folio(
            session,
            folio_ancla=d.folio,
            clave=f"desfase:{d.folio}",
            plantilla="alerta_desfase",
            variables={"folio": d.folio, "pcode": d.pcode, "dias": s.desfase_dias},
        )
        n_desfase += 1

    session.commit()
    return {
        "deterministicos": n_det,
        "probabilisticos": n_prob,
        "desfases": n_desfase,
        "no_matcheados": no_matcheados,
    }


def _notificar_comprobante(session: Session, dispatch: Event, receipt: Event) -> None:
    s = get_settings()
    _encolar_para_folio(
        session,
        folio_ancla=dispatch.folio,
        clave=f"comprobante:{dispatch.folio}:{receipt.folio}",
        plantilla="comprobante_listo",
        variables={
            "folio": dispatch.folio,
            "receipt_folio": receipt.folio,
            "hogares": receipt.payload.get("hogares"),
        },
        adjunto_url=f"{s.public_base_url}/comprobantes/{dispatch.folio}.pdf",
    )


def _encolar_para_folio(session, folio_ancla, clave, plantilla, variables, adjunto_url=None):
    """Notifica al reporter del dispatch usando su ref cifrada (guardada como ancla
    al crear el evento). Sin ancla no hay destinatario recuperable — se omite."""
    ancla = session.execute(
        select(Notificacion).where(Notificacion.clave_unica == f"ancla:{folio_ancla}")
    ).scalars().first()
    if ancla is None:
        return
    ya = session.execute(select(Notificacion).where(Notificacion.clave_unica == clave)).scalars().first()
    if ya is not None:
        return
    session.add(
        Notificacion(
            destinatario_cifrado=ancla.destinatario_cifrado,
            plantilla=plantilla,
            variables=variables,
            adjunto_url=adjunto_url,
            clave_unica=clave,
        )
    )
