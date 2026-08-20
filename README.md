# Radar de Desatención

**Un registro de eventos con salida pública que mide dónde NO ha llegado la ayuda humanitaria** — no dónde ocurrió el daño.

Contexto: terremoto de Colombia, 10 de agosto de 2026 (Mw 7.4, San José del Palmar, Chocó). Todo el ecosistema de respuesta mide daño y oferta; nadie mide desatención. La consecuencia documentada (México 2017, Kermanshah 2017, Nepal 2015) es un bucle de retroalimentación: *sin señal/vía → no hay reporte → no hay censo → no hay asignación → no llega ayuda*.

> **Tesis:** en suministros no falta oferta (hay 565.000 canastas en país), falta **señal de demanda granular** y **registro de flujos de última milla**. El Radar registra qué se despachó, qué se recibió y — sobre todo — qué territorios llevan N días sin recibir nada.

---

## Qué es (y qué no es)

| Es | No es |
|---|---|
| Un **log de eventos** append-only (necesidad, despacho, recepción) georreferenciado a DIVIPOLA | Otro mapa de daños (HOT/OSM ya lo hacen) |
| Una **métrica de desatención** por territorio: días sin entrega × población × accesibilidad | Otro directorio de acopios (Cuidar a Colombia, Ayudas Pereira) |
| Una **salida pública estática** (tabla, CSV/HXL, GeoJSON) para despachadores e instituciones | Un canal de recaudo ni un registro de desaparecidos |
| Actas de despacho con folio + QR verificable | Una app — el intake es conversacional (WhatsApp y voz) |

## Arquitectura en una línea

La capa conversacional completa (canales WhatsApp/voz, sesiones, máquina de estados, extracción LLM, PII) **la provee la plataforma de agentes de Vozy**. Se construyen **dos cosas**: el **Radar Core** (un servicio en Railway) y **tres agentes** en la plataforma Vozy.

```
Ciudadano/Promotora ──WhatsApp/Voz──► Plataforma Vozy (existente)
                                        · radar-recepcion  (RECEIPT)
                                        · radar-despacho   (DISPATCH)
                                        · radar-necesidad  (NEED)
                                              │ @tool_call (HTTP síncrono)
                                              ▼
                                      RADAR CORE (a construir)
                                        · Tools API: resolver_ubicacion,
                                          crear_evento, consultar_folio
                                        · Jobs: reconciliación, export
                                        · Generador de actas PDF+QR
                                        · PostgreSQL + PostGIS
                                              │ cada 5 min
                                              ▼
                                      Salida pública estática
                                        tabla.html · datos.csv (HXL) · geojson
```

Detalle completo: [docs/architecture.md](docs/architecture.md)

## Los endpoints del contrato

```
POST /tools/resolver_ubicacion   pin GPS o nombre hablado → pcode DIVIPOLA + confianza
POST /tools/crear_evento         evento normalizado + idempotency_key → folio (+ acta para dispatch)
GET  /tools/consultar_folio      folio → existe, tipo, estado, resumen
POST /tools/buscar_gracias       (épica 02) filtros pcode/sentimiento/categoría → clip de audio aprobado
```

Y una salida proactiva: el Core llama a `POST {plataforma}/notify` con una referencia opaca — decide *cuándo* y *qué* notificar; la plataforma resuelve *a quién* y *cómo*.

## Invariantes de diseño (no negociables)

1. **El PII nunca entra al Radar.** El teléfono vive solo en la plataforma Vozy; el Core solo ve `reporter_ref` opaco, que hashea y no puede revertir.
2. **El log es append-only.** Las correcciones son eventos nuevos que referencian el folio corregido. El log nunca se toca.
3. **Captura con pin exacto, publicación agregada a pcode.** Sin excepciones — un mapa público de dónde hay ayuda es también un mapa de bienes robables en zonas de conflicto.
4. **Idempotencia en el Core, no en el agente.** La plataforma puede reintentar un tool call; `idempotency_key` garantiza un solo evento.
5. **La validación de dominio no se delega al LLM.** El Core valida contra esquema y rechaza con error estructurado; el agente traduce el rechazo a una repregunta.
6. **Sin eventos = alerta máxima, no NULL.** El silencio de un territorio es el dato principal, no un vacío.
7. **La salida pública no toca la base de datos en lectura** — es estática, regenerada cada 5 minutos.

## El canal de voz es el caso difícil

En voz no hay pin GPS: la ubicación llega como nombre hablado transcrito ("la vereda La Cabaña, por Jamundí"). Por eso `resolver_ubicacion` tiene modo texto contra un **gazetteer** (centros poblados DANE + veredas curadas para los 10–15 municipios priorizados) con score de confianza y desambiguación conversacional. Es el constraint dominante del territorio: la promotora con señal 2G llama, habla, y el evento entra igual.

## Las tres épicas

El producto está organizado en tres épicas ([epic_specs/](epic_specs/)); la primera está implementada, las otras dos están especificadas y cerradas para implementación:

| Épica | Qué agrega | Estado |
|---|---|---|
| [01 · Radar de Atención](epic_specs/epica01_radar_atencion.md) | El core: log de eventos, Tools API, gazetteer, reconciliación, actas, export estático (componentes 1–8) | ✅ Implementada |
| [02 · Radar Ciudadano](epic_specs/epica02_radar_ciudadano.md) | Cierre del lazo con el donante: vista pública narrativa (scrollytelling de 5 actos), banco de voces de agradecimiento (WhatsApp + Lili Analyze vía API), integración con Ayudas Pereira en 3 fases activables por configuración, tool `buscar_gracias` (componentes 9–11) | 📋 Especificada |
| [03 · Radar Operativo](epic_specs/epica03_radar_operativo.md) | Vista de despacho (U2/U3) con arranque en frío resuelto: agente **Vigía de Medios** (LangGraph dentro del core) que extrae señales estructuradas de medios confiables — con cita + URL, conciliadas al gazetteer, **nunca dentro del log de eventos** — y cola de incorporación de localidades (componentes 12–14) | 📋 Especificada |

### Principios del front (épicas 02 y 03)

- **El front no inventa — renderiza.** Todo string visible proviene del JSON del export, de plantillas taxativas (P1–P8) o de microcopy fijo (M0–M7). Spec completa: [docs/especificacion_front.md](docs/especificacion_front.md); prototipo funcional autocontenido: [docs/refs_diseno_html/radar-ciudadano-historia.html](docs/refs_diseno_html/radar-ciudadano-historia.html).
- **Identidad visual cerrada:** modo claro = *A · Registro civil*, modo oscuro = *E · Tinta profunda*, por `prefers-color-scheme`. Semántica dura: teal = confirmado, ámbar = espera, rojo solo para alerta máxima.
- **Stack cerrado:** cero servicios nuevos, cero Node, cero framework — Jinja2 en el export + vanilla JS + mapa SVG autocontenido; archivo único ≤45KB tras Cloudflare, funciona offline.
- **Procedencia siempre visible** (épica 03): señal de medios ≠ reporte ciudadano ≠ evento con folio; nunca se mezclan sin etiqueta, y el territorio en silencio conserva la alerta máxima.

## Cómo correrlo

Radar Core está implementado en **Python 3.13 + FastAPI + SQLAlchemy 2** (Poetry), con PostgreSQL + PostGIS.

```bash
poetry install   # requiere Python 3.13

make up          # DB (Docker) + seed demo + servicio en background (:8000)
make e2e         # colección Bruno de punta a punta (23 requests, storyboard completo)
make down        # baja servicio y base de datos
make dev         # alternativa: servicio en foreground con hot reload

make test        # suite completa (ver docs/test-suite.md)
poetry run pytest -m epica01   # por épica — también: epica02, epica03, e2e
poetry run pytest -m unit      # por tipo — también: integration, service, performance, transversal
```

Las pruebas están organizadas **por épica** (unitarias, integración y contrato de cada una) más clasificaciones del sistema completo (`tests/e2e/`, `tests/performance/`, `tests/transversal/`), y se escriben desde el punto de vista de los sistemas que se integran con el Radar (agentes Vozy, visitante web, Lili Analyze, feed de aliados, fuentes de medios).

La colección [bruno/](bruno/) recorre todos los casos de uso en el orden natural del storyboard (necesidad → despacho → acta → recepción → reconciliación → comprobante → salida pública) y se puede abrir en la app de Bruno o correr con `make e2e`.

Deploy: [Dockerfile](Dockerfile) + [railway.toml](railway.toml) (healthcheck en `/health`, puerto por env `PORT`). Las variables `RADAR_*` requeridas están documentadas en `railway.toml`.

## Estado y orden de construcción

**Fase actual: épica 01 (Radar Core) implementada, cubierta por la suite de pruebas y con datos DANE reales cargados.** Épicas 02 y 03 especificadas y cerradas para implementación. Pendiente: agentes en la plataforma Vozy, prueba de punta a punta con un despachador real, e implementación de los componentes 9–14.

| Orden | Entregable |
|---|---|
| ✅ | Core: `crear_evento` + `resolver_ubicacion` + `consultar_folio` + log + folios + actas PDF+QR |
| ✅ | Reconciliación + notificador + export estático + gazetteer con datos DANE reales |
| ✅ | Ambiente local (make + Bruno) y endpoint operativo `run_jobs` |
| ⏳ | Agentes Vozy (`radar_recepcion`, `radar_despacho`, `radar_necesidad`) · número WhatsApp + voz |
| 📋 | Épica 03 — Vigía de Medios + vista operativa (el primer dominó de adopción: útil desde el día cero) |
| 📋 | Épica 02 — vista ciudadana narrativa + banco de voces + integración Ayudas Pereira |

## Documentación

- [docs/architecture.md](docs/architecture.md) — arquitectura v2, contrato Agente↔Core, modelo de datos, decisiones abiertas
- [epic_specs/](epic_specs/) — las tres épicas: [01 Radar de Atención](epic_specs/epica01_radar_atencion.md), [02 Radar Ciudadano](epic_specs/epica02_radar_ciudadano.md), [03 Radar Operativo](epic_specs/epica03_radar_operativo.md)
- [docs/especificacion_front.md](docs/especificacion_front.md) — spec de implementación del front narrativo: contrato JSON, tokens de diseño, plantillas P1–P8, microcopy M0–M7, mapa SVG, protocolo de verificación
- [docs/refs_diseno_html/](docs/refs_diseno_html/) — prototipos de referencia (scrollytelling autocontenido, 0 dependencias)
- [problem_ressearch.md](problem_ressearch.md) — investigación de fondo: diagnóstico, casos comparados (FOREC, Haití, Nepal, Verificado19S), mapa de actores, cuñas de diferenciación
- [docs/aboutsimilarprojects.md](docs/aboutsimilarprojects.md) — deslinde con Ayudas Pereira (primera milla vs. última milla)
- [docs/test-suite.md](docs/test-suite.md) — suite de casos de prueba (unitarias, integración, servicio, performance)
- [CLAUDE.md](CLAUDE.md) — guía para desarrollo asistido con Claude Code

---

*Las cifras de la emergencia citadas en la investigación tienen corte al 14 de agosto de 2026 y cambian a diario — verificar contra UNGRD y OCHA antes de usarlas.*
