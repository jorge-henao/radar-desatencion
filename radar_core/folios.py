"""Folios: generación y normalización.

Formato `XX-NNNN` (NE-0847, DS-0392, RC-1204) — únicos, citables por voz y por QR.
La numeración sale de una secuencia de Postgres (seguro bajo concurrencia, U-01).
El parseo tolera el dictado por voz: `ds 0392`, `DS-0392`, `ds0392` (U-02).
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIJOS = {"need": "NE", "dispatch": "DS", "receipt": "RC"}

_FOLIO_RE = re.compile(r"^\s*([A-Za-z]{2})[\s\-_]*0*(\d{1,10})\s*$")


def generar_folio(session: Session, tipo: str) -> str:
    prefijo = PREFIJOS[tipo]
    n = session.execute(text("SELECT nextval('folio_seq')")).scalar_one()
    return f"{prefijo}-{int(n):04d}"


def normalizar_folio(crudo: str) -> str | None:
    """`ds 0392` / `ds0392` / `DS-0392` → `DS-0392`. None si no parsea."""
    if not crudo:
        return None
    m = _FOLIO_RE.match(crudo)
    if not m:
        return None
    prefijo, numero = m.group(1).upper(), int(m.group(2))
    if prefijo not in PREFIJOS.values():
        return None
    return f"{prefijo}-{numero:04d}"
