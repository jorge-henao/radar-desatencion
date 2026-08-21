"""Configuración del Radar Core.

Todo llega por variables de entorno (Railway) con defaults de desarrollo.
Los tokens de workspace son mutables en caliente (rotación sin downtime, X-06).
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADAR_", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:radar@localhost:54329/radar",
    )

    @field_validator("database_url")
    @classmethod
    def _forzar_driver_psycopg(cls, v: str) -> str:
        # Railway/Heroku entregan postgres:// o postgresql://; el driver instalado
        # es psycopg 3 — se normaliza para poder referenciar DATABASE_URL tal cual.
        for prefijo in ("postgres://", "postgresql://"):
            if v.startswith(prefijo):
                return "postgresql+psycopg://" + v[len(prefijo):]
        return v
    # Tokens de workspace separados por coma. Mutables en runtime vía rotate_tokens().
    workspace_tokens: str = Field(default="dev-token")
    # Salt del hash de reporter_ref. NUNCA se versiona ni se exporta (X-03).
    reporter_salt: str = Field(default="dev-salt-cambiar-en-produccion")
    # Clave Fernet para cifrar la ref del destinatario en el outbox de notificaciones.
    # El ref en claro no se persiste en ninguna tabla (X-01).
    fernet_key: str = Field(default="")

    public_base_url: str = Field(default="http://localhost:8000")
    plataforma_notify_url: str = Field(default="http://plataforma.invalid/notify")
    wa_numero_oficial: str = Field(default="+573001112233")

    export_dir: str = Field(default="./var/public")
    actas_dir: str = Field(default="./var/actas")
    vigia_config_path: str = Field(default="./vigia.yaml")
    vigia_llm_provider: str = Field(default="openai")
    vigia_llm_model: str = Field(default="gpt-4.1-mini")
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")

    # Umbrales de dominio
    umbral_confianza_geo: float = Field(default=0.80)
    # Precisión del match por texto (U-56/U-57). El score fuzzy es, en el fondo,
    # un ratio de longitud: "rio" contra "riofrio" da 0.60 sin que el hablante
    # haya nombrado lugar alguno. Cuanto más corto el residuo que queda tras
    # quitar muletillas, más parecido se le exige para auto-resolver.
    geo_residuo_largo: int = Field(default=9)      # caracteres (sin espacios)
    geo_residuo_medio: int = Field(default=6)
    geo_min_score_largo: float = Field(default=0.60)
    geo_min_score_medio: float = Field(default=0.75)
    geo_min_score_corto: float = Field(default=0.92)
    ventana_duplicado_horas: int = Field(default=48)
    ventana_dedup_necesidad_horas: int = Field(default=24)
    desfase_dias: int = Field(default=3)
    ventana_reconciliacion_dias: int = Field(default=10)

    # Rate limiting por reporter_hash
    rate_limit_max: int = Field(default=30)
    rate_limit_ventana_seg: int = Field(default=60)

    # Detección de patrón coordinado (X-08)
    patron_coordinado_min_eventos: int = Field(default=5)
    patron_coordinado_ventana_min: int = Field(default=10)

    # Notificador
    notify_max_intentos: int = Field(default=3)
    notify_backoff_base_seg: float = Field(default=2.0)

    export_interval_seg: int = Field(default=300)

    def tokens(self) -> set[str]:
        return {t.strip() for t in self.workspace_tokens.split(",") if t.strip()}

    def rotate_tokens(self, nuevos: str) -> None:
        """Rotación de tokens en caliente, sin reinicio (X-06)."""
        self.workspace_tokens = nuevos

    def ensure_dirs(self) -> None:
        Path(self.export_dir).mkdir(parents=True, exist_ok=True)
        Path(self.actas_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()


def get_settings() -> Settings:
    return settings
