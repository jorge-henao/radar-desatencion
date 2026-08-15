"""DDL que SQLAlchemy no expresa: triggers, secuencias y vistas materializadas.

- Trigger append-only sobre `events`: UPDATE/DELETE bloqueados A NIVEL DE DB (I-01),
  no por convención de código. Las correcciones son eventos nuevos.
- `mv_desatencion`: territorio priorizado SIN eventos = `alerta_maxima`, nunca NULL
  ni excluido (U-40/I-15). El silencio es el dato.
- Ambas MVs tienen índice único → REFRESH MATERIALIZED VIEW CONCURRENTLY (P-08).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import Base

_DDL = [
    "CREATE EXTENSION IF NOT EXISTS postgis",
    "CREATE SEQUENCE IF NOT EXISTS folio_seq START 100",
    # --- append-only sobre events ---
    """
    CREATE OR REPLACE FUNCTION events_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'events es append-only: % no permitido. Las correcciones son eventos nuevos.', TG_OP
            USING ERRCODE = 'raise_exception';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_events_append_only ON events",
    """
    CREATE TRIGGER trg_events_append_only
        BEFORE UPDATE OR DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION events_append_only()
    """,
    # --- índices geo ---
    "CREATE INDEX IF NOT EXISTS idx_geo_divipola_geom ON geo_divipola USING GIST (geom)",
    "CREATE INDEX IF NOT EXISTS idx_events_pin ON events USING GIST (pin)",
    # --- mv_desatencion ---
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_desatencion AS
    WITH corregidos AS (
        SELECT DISTINCT corrige_folio AS folio FROM events WHERE corrige_folio IS NOT NULL
    ),
    vigentes AS (
        SELECT e.* FROM events e LEFT JOIN corregidos c ON c.folio = e.folio
        WHERE c.folio IS NULL
    ),
    ultima_recepcion AS (
        SELECT pcode, max(created_at) AS ultima
        FROM vigentes WHERE type = 'receipt' GROUP BY pcode
    ),
    necesidades AS (
        SELECT pcode,
               count(DISTINCT reporter_hash) AS reportantes,
               array_agg(DISTINCT cat) AS faltante
        FROM (
            SELECT pcode, reporter_hash, jsonb_array_elements_text(payload->'categorias') AS cat
            FROM vigentes WHERE type = 'need'
        ) n
        GROUP BY pcode
    )
    SELECT
        g.pcode,
        g.nombre,
        g.nivel,
        g.departamento,
        g.poblacion_estimada,
        g.factor_accesibilidad,
        CASE WHEN ur.ultima IS NULL THEN NULL
             ELSE floor(extract(epoch FROM (now() - ur.ultima)) / 86400)::int
        END AS dias_sin_recepcion,
        CASE WHEN ur.ultima IS NULL THEN 'alerta_maxima' ELSE 'con_registro' END AS estado,
        coalesce(n.reportantes, 0) AS reportantes_necesidad,
        coalesce(array_to_string(n.faltante, ','), '') AS faltante_reportado,
        CASE WHEN ur.ultima IS NULL THEN NULL
             ELSE (floor(extract(epoch FROM (now() - ur.ultima)) / 86400)
                   * coalesce(g.poblacion_estimada, 1)
                   / greatest(g.factor_accesibilidad, 0.01))
        END AS score,
        now() AS calculado_el
    FROM geo_divipola g
    LEFT JOIN ultima_recepcion ur ON ur.pcode = g.pcode
    LEFT JOIN necesidades n ON n.pcode = g.pcode
    WHERE g.priorizado
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_desatencion_pcode ON mv_desatencion (pcode)",
    # --- mv_reconciliacion ---
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_reconciliacion AS
    SELECT
        d.folio AS dispatch_folio,
        d.pcode,
        d.created_at AS despachado_el,
        r.receipt_folio,
        r.metodo,
        (r.receipt_folio IS NOT NULL) AS reconciliado
    FROM events d
    LEFT JOIN reconciliaciones r ON r.dispatch_folio = d.folio
    WHERE d.type = 'dispatch'
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_recon_folio ON mv_reconciliacion (dispatch_folio, receipt_folio)",
]


def init_db(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for stmt in _DDL:
            conn.execute(text(stmt))


def refresh_mvs(eng: Engine, concurrently: bool = True) -> None:
    """CONCURRENTLY: el refresh no bloquea tool calls (P-08)."""
    modo = "CONCURRENTLY " if concurrently else ""
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW {modo}mv_desatencion"))
        conn.execute(text(f"REFRESH MATERIALIZED VIEW {modo}mv_reconciliacion"))


def drop_all(eng: Engine) -> None:
    """Solo para tests."""
    with eng.begin() as conn:
        conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS mv_desatencion CASCADE"))
        conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS mv_reconciliacion CASCADE"))
        conn.execute(text("DROP SEQUENCE IF EXISTS folio_seq CASCADE"))
    Base.metadata.drop_all(eng)
