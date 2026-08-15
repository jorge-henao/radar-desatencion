# CLAUDE.md

Guía para Claude Code al trabajar en este repositorio.

## Qué es este proyecto

**Radar de Desatención**: un registro de eventos humanitarios (necesidad / despacho / recepción) con salida pública, que mide **dónde no ha llegado la ayuda** tras el terremoto de Colombia de agosto 2026. La capa conversacional (WhatsApp + voz, sesiones, extracción LLM, PII) la provee la plataforma de agentes de Vozy — **aquí solo se construye el Radar Core** (un servicio en Railway) y se definen los tres agentes Vozy que lo consumen por tool calls.

Lee [docs/architecture.md](docs/architecture.md) antes de tocar cualquier cosa del contrato o del modelo de datos. La investigación de fondo está en [problem_ressearch.md](problem_ressearch.md).

## Estado del proyecto

Radar Core implementado: Python 3.13 + FastAPI + SQLAlchemy 2 + PostGIS, gestionado con Poetry.

```bash
poetry install                                  # deps (Python 3.13)
./scripts/dev_db.sh                             # PostGIS local (Docker, :54329)
poetry run uvicorn radar_core.main:app --reload # dev server :8000
poetry run pytest                               # suite completa
poetry run pytest -m "unit or service"          # por marcador: unit/integration/service/performance/transversal
```

Estructura: `radar_core/` (app) — `models.py` + `ddl.py` (esquema, trigger append-only, MVs), `schemas.py` (contrato Pydantic), `routers/` (tools + público), `services/` (eventos, geo, gazetteer, reconciliación, export, actas, notificador), `seed/loader.py` (ingesta DANE/gazetteer). Tests en `tests/` mapeados 1:1 a los IDs de docs/test-suite.md.

## Componentes del Radar Core

| Componente | Responsabilidad |
|---|---|
| Tools API | 3 endpoints HTTP síncronos que invocan los agentes Vozy |
| Log de eventos | Tabla `events` append-only en Postgres — la fuente de verdad |
| Servicio geo | Pin → DIVIPOLA (PostGIS + shapefiles DANE); texto → pcode (gazetteer, para voz) |
| Reconciliación | Match DISPATCH↔RECEIPT en batch: determinístico por folio, probabilístico marcado |
| Generador de actas | PDF con folio + QR (`wa.me/<num>?text=DS-0392`) |
| Export estático | tabla.html + CSV/HXL + GeoJSON cada 5 min |
| Notificador | Decide cuándo avisar; llama a `POST {plataforma}/notify` con referencia opaca |

## Contrato de la Tools API (la frontera que importa)

```
POST /tools/resolver_ubicacion
  in:  { lat, lon } | { texto: "vereda La Cabaña, Jamundí" }
  out: { pcode, nivel: municipio|centro_poblado, nombre_oficial, confianza, candidatos[] }

POST /tools/crear_evento
  in:  { type: need|dispatch|receipt, payload: {...}, reporter_ref, idempotency_key }
  out: { folio, warnings[], acta_url? }        ← acta_url solo para dispatch

GET  /tools/consultar_folio?folio=DS-0392
  out: { existe, type, estado, resumen }
```

Autenticación: token de workspace. Los errores de validación se devuelven **estructurados** (código + campo + motivo) para que el agente los traduzca a repreguntas.

## Invariantes — violarlos es un bug, sin importar qué pida el ticket

1. **PII nunca entra al Core.** No existe columna, log, ni traza con teléfonos. La única identidad que cruza la frontera es `reporter_ref` (opaco, provisto por la plataforma); el Core lo hashea para rate limiting y detección de patrones, y no puede resolverlo de vuelta.
2. **`events` es append-only.** Nunca escribir UPDATE ni DELETE sobre esa tabla. Las correcciones son eventos nuevos que referencian el folio corregido.
3. **Zona privada / zona pública.** El pin exacto (`pin geography`) es zona privada. Todo lo público se agrega a `pcode` — jamás exportar coordenadas exactas ni nada re-identificable.
4. **Idempotencia por `idempotency_key`** (conversación + paso). Reintento con la misma key → mismo folio, cero eventos duplicados. Es responsabilidad del Core, no del agente.
5. **Validación de dominio en el Core, nunca delegada al LLM.** Esquema por tipo de evento; el enum de categorías (`agua|alimentos|medicamentos|aseo|techo|otro`) se valida server-side.
6. **`mv_desatencion`: sin eventos = `alerta_maxima`, nunca NULL.** El silencio es el dato.
7. **El export estático no lee de la DB en el request path** — se regenera por job y se sirve detrás de Cloudflare.
8. **El Core nunca envía mensajes directamente.** Notificaciones solo vía la API de salida proactiva de la plataforma.

## Modelo de datos

```sql
events            -- append-only: folio único, type, payload jsonb validado,
                  -- pin geography (privado), pcode, reporter_hash, created_at
geo_divipola      -- polígonos DANE (municipios + centros poblados)
gazetteer         -- nombre de lugar → pcode, con alias y fuzzy match (habilita voz)
mv_desatencion    -- métrica por pcode
mv_reconciliacion -- estado del match dispatch↔receipt
```

No hay tablas de conversaciones ni de mensajes — la sesión es problema de la plataforma.

## Stack y convenciones

- **DB:** PostgreSQL + PostGIS. Shapefiles DANE (DIVIPOLA) como base geográfica.
- **Deploy:** Railway (servicio) + Cloudflare (salida estática).
- **Folios:** formato `DS-NNNN` (ej. `DS-0392`), únicos, citables por voz y por QR.
- **Idioma:** dominio, documentación y mensajes de error orientados al agente en **español**. Código (identificadores) en el idioma que establezca el primer módulo — mantener consistencia.
- **Datos públicos:** CSV con etiquetas HXL; GeoJSON válido; nombres de columna estables (son contrato con consumidores externos).

## Reglas de los agentes Vozy (por diseño de flujo, no por prompt)

- Jamás pedir cédula ni datos bancarios.
- El flujo de necesidad abre con disclaimer hardcodeado: "esto NO garantiza que llegue una entrega".
- Si `confianza < umbral` en `resolver_ubicacion` → desambiguar entre `candidatos[]` antes de crear el evento.

## Testing

La suite de casos está en [docs/test-suite.md](docs/test-suite.md). Prioridades al implementar:

1. Los tests de **invariantes** (PII, append-only, agregación pública, idempotencia) son bloqueantes — se escriben junto con la primera versión de cada componente, no después.
2. Los tests de contrato de la Tools API simulan al agente Vozy como consumidor (incluye reintentos y payloads malformados por el LLM).
3. Presupuesto de latencia: los tool calls son **síncronos dentro de una conversación de voz** — ver umbrales en la suite.

## Trampas conocidas

- `resolver_ubicacion` modo texto recibe **transcripciones sucias** de voz ("la cabaña por jamundí, por ahí cerquita"). El gazetteer con fuzzy match y el campo `candidatos[]` existen por eso — no asumir texto limpio.
- La plataforma **reintenta tool calls** ante timeouts: cualquier endpoint de escritura sin idempotencia real produce eventos duplicados en producción.
- Un `receipt` puede citar un folio inexistente o con typo (dictado por voz) — `consultar_folio` debe distinguir "no existe" de error, y el flujo debe continuar sin folio (match probabilístico posterior).
- Los shapefiles DANE tienen polígonos con geometrías inválidas ocasionales — sanear al cargar (`ST_MakeValid`), no en query time.
