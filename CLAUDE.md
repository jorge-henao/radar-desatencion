# CLAUDE.md

Guía para Claude Code al trabajar en este repositorio.

## Qué es este proyecto

**Radar de Desatención**: un registro de eventos humanitarios (necesidad / despacho / recepción) con salida pública, que mide **dónde no ha llegado la ayuda** tras el terremoto de Colombia de agosto 2026. La capa conversacional (WhatsApp + voz, sesiones, extracción LLM, PII) la provee la plataforma de agentes de Vozy — **aquí solo se construye el Radar Core** (un servicio en Railway) y se definen los tres agentes Vozy que lo consumen por tool calls.

Lee [docs/architecture.md](docs/architecture.md) antes de tocar cualquier cosa del contrato o del modelo de datos. La investigación de fondo está en [problem_ressearch.md](problem_ressearch.md).

El producto se organiza en tres épicas ([epic_specs/](epic_specs/)): **01 Radar de Atención** (el core — implementada), **02 Radar Ciudadano** (vista narrativa pública + banco de voces + integración Ayudas Pereira — especificada, componentes 9–11) y **03 Radar Operativo** (vista de despacho + agente Vigía de Medios — especificada, componentes 12–14). Antes de implementar algo de las épicas 02/03, lee la épica correspondiente completa: las decisiones marcadas "no re-debatir" ya están tomadas, y los puntos `[FALTA]` son incógnitas reales, no descuidos. Para cualquier front, la spec vinculante es [docs/especificacion_front.md](docs/especificacion_front.md) — ante ambigüedad con el prototipo ([docs/refs_diseno_html/](docs/refs_diseno_html/)), gana la spec.

## Estado del proyecto

Radar Core implementado: Python 3.13 + FastAPI + SQLAlchemy 2 + PostGIS, gestionado con Poetry.

```bash
poetry install                                  # deps (Python 3.13)
./scripts/dev_db.sh                             # PostGIS local (Docker, :54329)
poetry run uvicorn radar_core.main:app --reload # dev server :8000
poetry run pytest                               # suite completa
poetry run pytest -m "unit or service"          # por marcador: unit/integration/service/performance/transversal
```

Estructura: `radar_core/` (app) — `models.py` + `ddl.py` (esquema, trigger append-only, MVs), `schemas.py` (contrato Pydantic), `routers/` (tools + público), `services/` (eventos, geo, gazetteer, reconciliación, export, actas, notificador), `seed/loader.py` (ingesta DANE/gazetteer). Tests en `tests/` mapeados 1:1 a los IDs de docs/test-suite.md, organizados **por épica** (`epica01_radar_atencion/{unit,integration,contrato}/`, `epica02_…`, `epica03_…`) más clasificaciones del sistema completo (`e2e/`, `performance/`, `transversal/`). Los markers de épica (`epica01`..`epica03`, `e2e`) se derivan de la carpeta en el conftest raíz; los de tipo (`unit`, `integration`, `service`, …) van como `pytestmark` en cada módulo.

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

**Componentes especificados, aún no implementados** (épicas 02 y 03):

| # | Componente | Épica | Responsabilidad |
|---|---|---|---|
| 9 | Banco de voces | 02 | Adaptador API Lili Analyze (solo lectura, mapeo configurable) + copia/recorte/transcodificación a MP3 + gate de moderación + tabla `audio_gracias` + tool `buscar_gracias` |
| 10 | Importador de feeds de aliados | 02 | Poller de `acopios.json` (Ayudas Pereira), normalización, degradación automática a fase 0 si el feed cae |
| 11 | Generador de vista ciudadana | 02 | Template Jinja2 según especificacion_front.md: `vista-ciudadana.json` desde el log, plantillas server-side, HTML autocontenido ≤45KB |
| 12 | Vigía de Medios | 03 | Agente LangGraph **dentro del core** (sin dependencias de plataforma) + job del scheduler + `vigia.yaml` + tabla `senales_medios` con dedupe/decaimiento/conversión |
| 13 | Cola de incorporación de localidades | 03 | `localidades_por_incorporar` + enriquecimiento DIVIPOLA/COD-AB + aprobación humana → alta en gazetteer |
| 14 | Vista operativa | 03 | Template Jinja2 + `vista-operativa.json` en el export + filtros client-side + sección de revisión |

## Contrato de la Tools API (la frontera que importa)

```
POST /tools/resolver_ubicacion
  in:  { lat, lon } | { texto: "vereda La Cabaña, Jamundí" }
  out: { pcode, nivel: municipio|centro_poblado|vereda, nombre_oficial,
         municipio_pcode, municipio_nombre, departamento_codigo, departamento_nombre,
         etiqueta,                        ← string hablable, listo para repreguntar
         confianza, candidatos[],         ← cada candidato lleva los mismos campos
         motivo }                         ← ambiguo | confianza_baja | sin_candidatos
                                            | fuera_de_cobertura

POST /tools/crear_evento
  in:  { type: need|dispatch|receipt, payload: {...}, reporter_ref, idempotency_key }
  out: { folio, warnings[], acta_url? }        ← acta_url solo para dispatch

GET  /tools/consultar_folio?folio=DS-0392
  out: { existe, type, estado, resumen }

POST /tools/buscar_gracias                      ← épica 02, no implementada aún
  in:  { pcode?, sentimiento?, categorias?[], texto_libre?, aleatorio: bool }
  out: { clip_url_ogg, clip_url_mp3, territorio_nombre, pcode, duracion_s, fecha }
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
9. **Las señales de medios NUNCA entran al log de eventos** (épica 03). El log es exclusivamente hechos de primera mano; las señales del Vigía viven en `senales_medios` y se unen con el log solo en presentación, con procedencia explícita. Toda señal lleva cita textual + URL verificable; sin URL, la señal se descarta. Nunca se publica una localidad sin pcode conciliado.
10. **Audio sin consentimiento explícito jamás es público** (épica 02). El flag de consentimiento es regla dura; sin él, el audio queda solo como evidencia privada del despachador reconciliado. Lili Analyze se consume **exclusivamente por su API de solo lectura** — nunca Elasticsearch/S3 directo, y el Radar nunca invoca el análisis.
11. **El front no inventa — renderiza** (épicas 02/03). Todo string visible proviene del JSON del export, de las plantillas taxativas (P1–P8) o del microcopy fijo (M0–M7) de la spec del front. Prohibido inferir personas, causas, citas o cifras que no estén en los datos.
12. **El Vigía nunca degrada la alerta por ausencia.** Territorio sin eventos NI señales sigue siendo alerta máxima — las señales de medios elevan visibilidad, no reemplazan el silencio como dato.
13. **Toda ubicación resuelta viaja con su procedencia, y nunca se resuelve sin certeza.** Si hay `pcode` hay `municipio_pcode` (un municipio es su propio municipio) y `confianza >= umbral_confianza_geo`. Por debajo del piso se devuelven `candidatos[]` con `motivo` — jamás un pcode adivinado. El piso se escala con la longitud del texto útil: un residuo corto ("rio") hace match alto con cualquier nombre corto sin que el hablante haya nombrado lugar alguno.

## Modelo de datos

```sql
events            -- append-only: folio único, type, payload jsonb validado,
                  -- pin geography (privado), pcode, reporter_hash, created_at
geo_divipola      -- polígonos DANE (municipios + centros poblados)
gazetteer         -- nombre de lugar → pcode, con alias y fuzzy match (habilita voz)
mv_desatencion    -- métrica por pcode
mv_reconciliacion -- estado del match dispatch↔receipt

-- Especificadas (épicas 02/03), aún no implementadas:
audio_gracias     -- banco de voces: source, territorio_pcode (nunca pin), consentimiento
                  -- NOT NULL, estado de moderación, urls original/pública
acopios           -- catálogo de acopios de aliados (feed Ayudas Pereira)
senales_medios    -- señales del Vigía: cita + url NOT NULL, refuerzos, decaimiento,
                  -- estado activa|caducada|descartada|convertida — FUERA del log
localidades_por_incorporar -- cola de conciliación de localidades → alta en gazetteer
```

No hay tablas de conversaciones ni de mensajes — la sesión es problema de la plataforma.

## Stack y convenciones

- **DB:** PostgreSQL + PostGIS. Shapefiles DANE (DIVIPOLA) como base geográfica.
- **Deploy:** Railway (servicio) + Cloudflare (salida estática).
- **Folios:** formato `DS-NNNN` (ej. `DS-0392`), únicos, citables por voz y por QR.
- **Idioma:** dominio, documentación y mensajes de error orientados al agente en **español**. Código (identificadores) en el idioma que establezca el primer módulo — mantener consistencia.
- **Datos públicos:** CSV con etiquetas HXL; GeoJSON válido; nombres de columna estables (son contrato con consumidores externos).
- **Front (épicas 02/03, decisión cerrada):** cero servicios nuevos, cero Node, cero framework — Jinja2 en el export + vanilla JS + mapa SVG autocontenido; archivo único ≤45KB que funciona offline. Identidad: claro = A · Registro civil, oscuro = E · Tinta profunda (`prefers-color-scheme`, sin toggle). Semántica dura: teal = confirmado, ámbar = espera, `--alerta` solo para alerta máxima. Ningún color hardcodeado fuera de `:root`.
- **Configuración sobre deploy:** las capacidades condicionales (fases Ayudas Pereira, moderación auto/manual/híbrido, modos de la vista operativa, fuentes del Vigía en `vigia.yaml`) se encienden/apagan por configuración, nunca desplegando código. La degradación ante fallas de dependencias externas es automática.

## Reglas de los agentes Vozy (por diseño de flujo, no por prompt)

- Jamás pedir cédula ni datos bancarios.
- El flujo de necesidad abre con disclaimer hardcodeado: "esto NO garantiza que llegue una entrega".
- Si `confianza < umbral` en `resolver_ubicacion` → desambiguar entre `candidatos[]` antes de crear el evento.

## Testing

La suite de casos está en [docs/test-suite.md](docs/test-suite.md), cubre las tres épicas (IDs `U-/I-/S-` para la 01, `U2-/I2-/S2-` y `U3-/I3-/S3-` para las especificadas, `E-` para los escenarios inter-épicas) y espeja la estructura de `tests/`. Prioridades al implementar:

1. Los tests de **invariantes** (PII, append-only, agregación pública, idempotencia — y en las épicas nuevas: consentimiento, señales fuera del log, solo-lectura de Analyze) son bloqueantes — se escriben junto con la primera versión de cada componente, no después.
2. Las pruebas se escriben **desde el punto de vista de los sistemas que se integran**: el agente Vozy (reintentos, payloads malformados por el LLM), el visitante web, el API de Analyze simulado, el feed de aliados, las fuentes de medios (incluido contenido adversarial con inyección de prompt).
3. Presupuesto de latencia: los tool calls son **síncronos dentro de una conversación de voz** — ver umbrales en la suite (aplica también a `buscar_gracias`).
4. Al implementar componentes de las épicas 02/03, crear la subestructura espejo (`unit/`, `integration/`, `contrato/`) dentro de su carpeta — ver los README en `tests/epica02_radar_ciudadano/` y `tests/epica03_radar_operativo/`.

## Trampas conocidas

- `resolver_ubicacion` modo texto recibe **transcripciones sucias** de voz ("la cabaña por jamundí, por ahí cerquita"). El gazetteer con fuzzy match y el campo `candidatos[]` existen por eso — no asumir texto limpio.
- La lista `_STOPWORDS` del gazetteer **se aplica también al catálogo** al cargarlo, así que agregar una palabra que aparezca en nombres reales mutila el índice en silencio: `alto` está en 780 nombres de vereda del DANE, `bajo` en 391, `rio` en 205. Medir contra los shapefiles antes de agregar cualquier palabra — U-58 es el guard.
- El score fuzzy es, en el fondo, un **ratio de longitud**: `"rio"` contra `"riofrio"` da exactamente 0.60. Por eso el piso para auto-resolver se escala con la longitud del residuo (`score_minimo`) y no es un corte plano.
- La plataforma **reintenta tool calls** ante timeouts: cualquier endpoint de escritura sin idempotencia real produce eventos duplicados en producción.
- Un `receipt` puede citar un folio inexistente o con typo (dictado por voz) — `consultar_folio` debe distinguir "no existe" de error, y el flujo debe continuar sin folio (match probabilístico posterior).
- Los shapefiles DANE tienen polígonos con geometrías inválidas ocasionales — sanear al cargar (`ST_MakeValid`), no en query time.
- Las MVs calculan días con `floor()` contra `now()` **de Postgres**. En tests, cualquier `created_at` sintético debe derivarse del reloj de la DB (`SELECT now()`), nunca del reloj del host: el contenedor Docker puede ir milisegundos detrás y los "hace N días" exactos caen justo en la frontera del floor — falla intermitente que solo aparece con la suite completa.
