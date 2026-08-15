"""Autenticación por token de workspace y manejo de identidad opaca.

- El teléfono NO existe en el Radar. La única identidad que cruza la frontera
  es `reporter_ref` (opaco, emitido por la plataforma).
- El Core lo hashea (HMAC-SHA256 con salt de servicio) para rate limiting y
  detección de patrones; el hash no es reversible y no hay tabla de mapeo (X-03).
- Para notificar, el outbox guarda la ref cifrada (Fernet) — nunca en claro (X-01).
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet
from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import ErrorEstructurado

_fernet_cache: dict[str, Fernet] = {}


def _fernet(settings: Settings) -> Fernet:
    key = settings.fernet_key
    if not key:
        # Derivada del salt en desarrollo; en producción RADAR_FERNET_KEY es obligatoria.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.reporter_salt.encode()).digest()).decode()
    if key not in _fernet_cache:
        _fernet_cache[key] = Fernet(key)
    return _fernet_cache[key]


def hash_reporter(reporter_ref: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return hmac.new(s.reporter_salt.encode(), reporter_ref.encode(), hashlib.sha256).hexdigest()


def cifrar_ref(reporter_ref: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return _fernet(s).encrypt(reporter_ref.encode()).decode()


def descifrar_ref(token: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return _fernet(s).decrypt(token.encode()).decode()


async def requiere_token(request: Request, settings: Settings = Depends(get_settings)) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ErrorEstructurado(
            codigo="no_autenticado", motivo="Falta el token de workspace (Authorization: Bearer)", status=401
        )
    token = auth[7:].strip()
    if token not in settings.tokens():
        raise ErrorEstructurado(codigo="token_invalido", motivo="Token de workspace inválido", status=401)
    return token
