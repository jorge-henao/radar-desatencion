"""Actas de despacho y comprobantes de entrega — PDF con folio + QR.

El acta viaja físicamente con el camión: lleva el folio, el número oficial y
un QR `wa.me/<num>?text=DS-0392` (U-61, épica paso 5). Cada entrega siembra
un reportante.

La generación es perezosa + en background: NUNCA en el request path de
crear_evento (P-03).
"""

from __future__ import annotations

import io
from pathlib import Path

import qrcode
from fpdf import FPDF

from ..config import get_settings


def qr_payload(folio: str) -> str:
    s = get_settings()
    numero = s.wa_numero_oficial.lstrip("+")
    return f"https://wa.me/{numero}?text={folio}"


def _qr_png(folio: str) -> bytes:
    img = qrcode.make(qr_payload(folio)).get_image()
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _pdf_base(titulo: str, folio: str, lineas: list[str]) -> bytes:
    s = get_settings()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, titulo, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 28)
    pdf.cell(0, 16, folio, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    for linea in lineas:
        pdf.cell(0, 8, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.image(io.BytesIO(_qr_png(folio)), w=60)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"WhatsApp oficial: {s.wa_numero_oficial} - escanee el QR para confirmar la recepcion")
    return bytes(pdf.output())


def ruta_acta(folio: str) -> Path:
    return Path(get_settings().actas_dir) / f"{folio}.pdf"


def ruta_comprobante(folio: str) -> Path:
    return Path(get_settings().actas_dir) / f"comprobante-{folio}.pdf"


def generar_acta(folio: str, pcode: str | None = None, destino_nombre: str | None = None) -> Path:
    """Idempotente: si ya existe, no regenera."""
    destino = ruta_acta(folio)
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    lineas = ["Acta de despacho - Radar de Desatencion"]
    if destino_nombre or pcode:
        lineas.append(f"Destino: {destino_nombre or ''} ({pcode or 's/d'})")
    lineas.append("Imprima esta acta y enviela con el camion: con ella la comunidad confirma la recepcion.")
    destino.write_bytes(_pdf_base("ACTA DE DESPACHO", folio, lineas))
    return destino


def generar_comprobante(dispatch_folio: str, receipt_folio: str, hogares: int | None, metodo: str) -> Path:
    destino = ruta_comprobante(dispatch_folio)
    destino.parent.mkdir(parents=True, exist_ok=True)
    nivel = "confirmacion independiente + folio citado" if metodo == "deterministico" else "match probabilistico"
    lineas = [
        "Comprobante de entrega - reconciliado",
        f"Despacho: {dispatch_folio}",
        f"Recepcion: {receipt_folio}" + (f" - ~{hogares} hogares" if hogares else ""),
        f"Nivel: {nivel}",
    ]
    destino.write_bytes(_pdf_base("COMPROBANTE DE ENTREGA", dispatch_folio, lineas))
    return destino
