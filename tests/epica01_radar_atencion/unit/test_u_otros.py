"""U-60..U-62 — hash de identidad, QR del acta, etiquetas HXL."""

import pytest

from radar_core.config import settings
from radar_core.security import cifrar_ref, descifrar_ref, hash_reporter
from radar_core.services.actas import generar_acta, qr_payload
from radar_core.services.export import COLUMNAS, HXL_TAGS

pytestmark = pytest.mark.unit


class TestIdentidad:
    def test_u60_hash_deterministico_con_salt(self):
        h1 = hash_reporter("ref-abc")
        h2 = hash_reporter("ref-abc")
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_u60_salt_cambia_el_hash(self):
        h1 = hash_reporter("ref-abc")
        original = settings.reporter_salt
        try:
            settings.reporter_salt = "otro-salt"
            assert hash_reporter("ref-abc") != h1
        finally:
            settings.reporter_salt = original

    def test_u60_hash_no_contiene_la_ref(self):
        assert "ref-abc" not in hash_reporter("ref-abc")

    def test_u60_cifrado_roundtrip_y_opaco(self):
        token = cifrar_ref("ref-abc")
        assert "ref-abc" not in token
        assert descifrar_ref(token) == "ref-abc"


class TestQR:
    def test_u61_contenido_del_qr(self):
        payload = qr_payload("DS-0392")
        numero = settings.wa_numero_oficial.lstrip("+")
        assert payload == f"https://wa.me/{numero}?text=DS-0392"

    def test_u61_acta_pdf_generada(self, tmp_path):
        original = settings.actas_dir
        try:
            settings.actas_dir = str(tmp_path)
            ruta = generar_acta("DS-0392", "27660C01", "San Pedro")
            contenido = ruta.read_bytes()
            assert contenido.startswith(b"%PDF")
            assert len(contenido) > 1000
        finally:
            settings.actas_dir = original


class TestHXL:
    def test_u62_tags_alineados_con_columnas(self):
        assert len(HXL_TAGS) == len(COLUMNAS)
        assert all(t.startswith("#") for t in HXL_TAGS)
        assert "#geo+code" in HXL_TAGS
