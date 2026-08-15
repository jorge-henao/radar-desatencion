# Suite de casos de prueba — Radar Core

> **Perspectiva:** el Radar Core se prueba desde el punto de vista de sus consumidores reales:
> los **tres agentes Vozy** (que lo invocan por tool calls síncronos, con reintentos y datos
> sucios de LLM/voz) y las **aplicaciones externas** que consumen la salida pública
> (despachadores, instituciones, herramientas tipo Ayudas Pereira) y la API de notificación.
>
> Convención de IDs: `U-` unitaria · `I-` integración · `S-` servicio/contrato · `P-` performance · `X-` transversal (seguridad/privacidad).
> Prioridad: **P0** = bloqueante (protege un invariante), **P1** = core, **P2** = robustez.
>
> **Ejecución:** la suite está implementada en `tests/` con los IDs en los nombres de cada test
> (`poetry run pytest`, previa `./scripts/dev_db.sh`). P-06 corre acortada por defecto (15 s);
> `RADAR_PERF_FULL=1` la ejecuta a los 5 minutos completos de la especificación.

---

## 0. Matriz de riesgo → cobertura

| Invariante / riesgo | Casos que lo protegen |
|---|---|
| PII nunca entra al Core | X-01..X-04 |
| `events` append-only | U-10, I-01, I-02 |
| Publicación agregada a pcode (nunca pin) | X-05, I-20, S-30 |
| Idempotencia real ante reintentos de la plataforma | U-20, I-05, S-10..S-12, P-05 |
| Validación de dominio en el Core, no en el LLM | U-30..U-34, S-13..S-15 |
| Sin eventos = alerta_maxima, no NULL | U-40, I-15 |
| Voz: transcripción sucia → pcode correcto o desambiguación | U-50..U-55, S-20..S-23 |
| Latencia compatible con conversación de voz | P-01..P-04 |
| Export estático correcto y sin dependencia de DB en lectura | I-20..I-23, S-30..S-33 |
| Notificador nunca envía directo / usa ref opaca | I-30, X-03 |

---

## 1. Pruebas unitarias (U)

### Folios e idempotencia

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-01 | P1 | Generación de folio | Formato `DS-NNNN`, único, monotónico o no-colisionante bajo concurrencia |
| U-02 | P2 | Folio citable por voz | Sin caracteres ambiguos al dictado; parseo tolera `ds 0392`, `DS-0392`, `ds0392` |
| U-10 | P0 | Capa de persistencia de `events` | No expone operación de UPDATE/DELETE; una corrección produce un evento nuevo con referencia al folio corregido |
| U-20 | P0 | Resolución de `idempotency_key` | Misma key → retorna el evento/folio original sin insertar; key nueva → inserta |
| U-21 | P1 | Key igual con payload distinto | Se retorna el evento original y se marca discrepancia en `warnings[]` (nunca dos eventos) |

### Validación de esquema por tipo de evento

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-30 | P0 | Payload `need` válido / inválido | Válido pasa; inválido rechaza con error estructurado `{codigo, campo, motivo}` |
| U-31 | P0 | Payload `dispatch` válido / inválido | Ídem; incluye destino (pcode) y categorías |
| U-32 | P0 | Payload `receipt` válido / inválido | Ídem; `folio_citado` opcional |
| U-33 | P0 | Categoría fuera del enum (`agua\|alimentos\|medicamentos\|aseo\|techo\|otro`) | Rechazo server-side aunque el agente la haya "normalizado" — no se confía en el LLM |
| U-34 | P1 | Campos extra / tipos incorrectos inyectados por el LLM (`hogares: "como veinte"`) | Rechazo estructurado por campo, no error 500 ni coerción silenciosa |
| U-35 | P1 | `reporter_ref` ausente o vacío | Rechazo — es obligatorio en todo `crear_evento` |

### Métrica de desatención

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-40 | P0 | pcode sin ningún evento | Métrica = `alerta_maxima`, jamás NULL ni excluido del resultado |
| U-41 | P1 | Cálculo días-desde-última-entrega | Usa el último `receipt` reconciliado del pcode, no el último `dispatch` |
| U-42 | P2 | Decaimiento/dedup de eventos `need` repetidos | Reportes repetidos del mismo reporter_hash+pcode no inflan la métrica |

### Geo y gazetteer (el caso difícil: voz)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-50 | P0 | Match exacto: "Jamundí" | pcode del municipio, `confianza` alta, nivel `municipio` |
| U-51 | P0 | Match ambiguo: "La Cabaña" (existe en Jamundí y Riofrío) | `candidatos[]` con ambos, `confianza` bajo umbral — nunca elegir uno silenciosamente |
| U-52 | P0 | Transcripción sucia: "la beredita la cabaña por jamundi" | Fuzzy match resuelve o devuelve candidatos; nunca error |
| U-53 | P1 | Alias y apócopes del gazetteer ("San José" → San José del Palmar en contexto Chocó) | El alias resuelve al pcode canónico |
| U-54 | P1 | Lugar inexistente / basura ("asdfgh") | `candidatos[]` vacío + confianza 0, respuesta estructurada (el agente repregunta) |
| U-55 | P2 | Texto con municipio como desambiguador ("La Cabaña, Jamundí") | El municipio acota la búsqueda y sube la confianza |

### Otros

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-60 | P1 | Hash de `reporter_ref` | Determinístico, con salt de servicio, no reversible; el ref en claro no se persiste |
| U-61 | P1 | Contenido del QR del acta | `wa.me/<num>?text=<folio>` correcto y escaneable |
| U-62 | P2 | Etiquetado HXL del CSV | Fila de hashtags HXL válida bajo los encabezados |

---

## 2. Pruebas de integración (I)

*Con Postgres+PostGIS real (testcontainers o instancia efímera), shapefiles DANE de muestra y gazetteer de fixtures.*

### Base de datos

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-01 | P0 | UPDATE/DELETE directo sobre `events` | Bloqueado a nivel de DB (trigger/permiso de rol), no solo por convención de código |
| I-02 | P0 | Evento de corrección | Nuevo registro con referencia al folio original; el original queda intacto |
| I-03 | P1 | Carga de shapefiles DANE con geometría inválida | `ST_MakeValid` al ingestar; ningún polígono inválido llega a query time |
| I-05 | P0 | Dos inserts concurrentes con la misma `idempotency_key` | Exactamente un evento (constraint único en DB, no solo check en aplicación) |

### Resolución geográfica

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-10 | P0 | Pin dentro de un municipio conocido | pcode correcto contra el polígono DANE |
| I-11 | P1 | Pin en frontera entre polígonos / dentro de centro poblado | Resuelve al nivel más específico (`centro_poblado` sobre `municipio`) |
| I-12 | P1 | Pin fuera de Colombia o en el mar | Respuesta estructurada "fuera de cobertura", nunca 500 |
| I-15 | P0 | Refresh de `mv_desatencion` con territorio priorizado sin eventos | El pcode aparece con `alerta_maxima` |

### Reconciliación (batch)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-16 | P0 | `receipt` que cita folio de `dispatch` existente | Match determinístico; par marcado como reconciliado |
| I-17 | P1 | `receipt` sin folio, coincidente en pcode+categoría+ventana temporal con un `dispatch` | Match **probabilístico y marcado como tal** — distinguible del determinístico |
| I-18 | P1 | `dispatch` sin `receipt` tras el umbral de desfase | Genera candidato de `alerta_desfase` para el notificador |
| I-19 | P2 | `receipt` que cita folio inexistente | No rompe el batch; queda en cola de no-matcheados |

### Export estático

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-20 | P0 | Contenido del export (CSV/GeoJSON/HTML) | Solo agregados por pcode: cero coordenadas de pin, cero reporter_hash, cero payload crudo |
| I-21 | P1 | GeoJSON generado | Válido (parseable, geometrías correctas), un feature por pcode con la métrica |
| I-22 | P1 | Job de export con DB caída | El export anterior sigue sirviéndose; el job falla con alerta, no publica archivo vacío/corrupto |
| I-23 | P2 | Estabilidad de columnas del CSV | Nombres de columna idénticos entre corridas (contrato con consumidores externos) |

### Notificador y actas

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-30 | P0 | Comprobante listo → notificación | Se llama `POST {plataforma}/notify` con `reporter_ref` opaco + plantilla + `adjunto_url`; ningún envío directo |
| I-31 | P1 | Plataforma de notify caída / 5xx | Reintento con backoff; la notificación no se pierde ni se duplica |
| I-32 | P1 | Generación de acta para `dispatch` | PDF con folio, QR y número oficial; `acta_url` accesible para que la plataforma la adjunte |

---

## 3. Pruebas de servicio / contrato (S)

*Contra el servicio desplegado (o entorno idéntico), simulando exactamente lo que envía la plataforma Vozy. Estas son las pruebas que un agente "vive" en conversación.*

### Autenticación y contrato general

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-01 | P0 | Request sin token / token inválido de workspace | 401 estructurado; ningún efecto secundario |
| S-02 | P1 | Content-type incorrecto o JSON malformado | 400 estructurado, no 500 |
| S-03 | P1 | Errores estructurados consumibles por el agente | Todo rechazo incluye `{codigo, campo, motivo}` suficiente para formular una repregunta sin lógica adicional |

### `crear_evento` — el flujo del agente

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-10 | P0 | **Reintento de la plataforma** (timeout percibido, misma `idempotency_key`) | Misma respuesta, mismo folio, un solo evento — es el escenario de producción más frecuente |
| S-11 | P0 | Happy path `receipt` completo (flujo `radar_recepcion` de punta a punta) | `folio` retornado; evento consultable vía `consultar_folio` |
| S-12 | P1 | `dispatch` válido | Respuesta incluye `acta_url` descargable (solo dispatch la tiene) |
| S-13 | P0 | Payload con categoría inventada por el LLM | Rechazo estructurado; el evento NO se crea |
| S-14 | P1 | Posible duplicado (mismo reporter_hash, pcode y categoría en ventana corta) | Se crea con `warnings[]` de duplicación — advertir, no bloquear |
| S-15 | P1 | `need` — verificación de que el Core no exige datos prohibidos | El esquema no contiene ni acepta cédula, teléfono ni datos bancarios |
| S-16 | P2 | Rate limiting por reporter_hash | Ráfaga anómala del mismo hash se limita con error estructurado; hashes distintos no se afectan |

### `resolver_ubicacion` — ambos modos

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-20 | P0 | Modo pin (WhatsApp): coordenadas de un municipio priorizado | pcode + nombre_oficial + confianza alta |
| S-21 | P0 | Modo texto (voz): nombre único | pcode correcto, sin desambiguación |
| S-22 | P0 | Modo texto: nombre ambiguo | `candidatos[]` ≥ 2 y confianza bajo umbral → el agente puede preguntar "¿La Cabaña de Jamundí o la de Riofrío?" |
| S-23 | P1 | Ni pin ni texto, o ambos a la vez | 400 estructurado indicando el modo esperado |

### `consultar_folio`

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-25 | P0 | Folio existente | `{existe: true, type, estado, resumen}` — suficiente para precargar destino en `radar_recepcion` |
| S-26 | P0 | Folio inexistente / con typo de dictado | `{existe: false}` con 200 — es un resultado, no un error; el flujo continúa sin folio |

### Salida pública — otras aplicaciones consumidoras

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-30 | P0 | Auditoría de PII sobre los tres artefactos públicos | Grep exhaustivo: sin teléfonos, refs, hashes, coordenadas exactas ni texto libre de reportes |
| S-31 | P1 | `datos.csv` consumido por herramienta externa | Parseable, HXL válido, cada pcode priorizado presente (incluidos los de `alerta_maxima`) |
| S-32 | P1 | `geojson` en un visor de mapas estándar | Renderiza; propiedades documentadas presentes en cada feature |
| S-33 | P1 | Frescura del export | Header/campo de "generado el" ≤ 5 min tras cambios; cacheable en Cloudflare |
| S-34 | P2 | QR de un acta escaneado por un tercero | Abre `wa.me` con el folio precargado; el folio existe vía `consultar_folio` |

### Punta a punta (escenarios de negocio)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-40 | P0 | Ciclo completo: `dispatch` (con acta) → `receipt` citando el folio → reconciliación → export | El pcode sale del estado de desatención en la siguiente corrida del export |
| S-41 | P1 | Ciclo voz: `receipt` con ubicación hablada ambigua → desambiguación → evento → export | El evento queda en el pcode confirmado por el usuario |
| S-42 | P1 | Corrección: evento nuevo referenciando folio equivocado | El export refleja la corrección; el log conserva ambos eventos |

---

## 4. Pruebas de performance (P)

*Presupuestos derivados del canal: un tool call síncrono **bloquea una conversación de voz** — el silencio al teléfono es el peor UX posible y provoca reintentos de la plataforma (que a su vez ejercitan la idempotencia).*

| ID | Pri | Caso | Objetivo |
|---|---|---|---|
| P-01 | P0 | Latencia `resolver_ubicacion` modo pin (p95) | ≤ 500 ms — es un point-in-polygon indexado |
| P-02 | P0 | Latencia `resolver_ubicacion` modo texto con fuzzy match (p95) | ≤ 1.5 s con el gazetteer completo cargado (voz tolera ~2 s de pausa) |
| P-03 | P0 | Latencia `crear_evento` incluida generación de folio (p95) | ≤ 1 s; la generación del acta PDF es **asíncrona** — no puede estar en el request path |
| P-04 | P1 | Latencia `consultar_folio` (p95) | ≤ 300 ms |
| P-05 | P0 | **Carrera de idempotencia**: N requests concurrentes, misma key | 1 evento, N respuestas idénticas, sin deadlocks — a 50 concurrentes |
| P-06 | P1 | Throughput de `crear_evento` en pico (patrón post-desastre: ráfagas) | Sostener 20 req/s por 5 min sin degradar p95; el rate limit por hash no penaliza a reporters distintos |
| P-07 | P1 | Job de export con volumen de 30 días de emergencia (~50k eventos, ~400 pcodes) | Corre completo en < 2 min (la ventana es de 5) sin bloquear escrituras en `events` |
| P-08 | P1 | Refresh de vistas materializadas bajo escritura concurrente | `REFRESH ... CONCURRENTLY` o equivalente; las lecturas del job de export no bloquean tool calls |
| P-09 | P2 | Degradación con gazetteer creciendo (85 municipios curados) | La latencia de U-52/S-22 se mantiene dentro de P-02 |

---

## 5. Transversales: seguridad y privacidad (X)

*Estas pruebas existen porque el contexto lo exige: conflicto armado, suplantación activa y falsos censos documentados en la investigación.*

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| X-01 | P0 | Auditoría de esquema de DB y migraciones | Ninguna columna capaz de almacenar teléfono/PII; `reporter_ref` en claro no se persiste en ninguna tabla |
| X-02 | P0 | Auditoría de logs de aplicación bajo tráfico real de prueba | Ningún `reporter_ref`, payload crudo con nombres, ni coordenada exacta en logs/traces/métricas |
| X-03 | P0 | Irreversibilidad del `reporter_hash` | Sin tabla de mapeo inverso; el salt no está en el repo ni en el export |
| X-04 | P1 | Respuestas de error | Los errores estructurados no filtran payloads de otros eventos ni detalles internos (stack traces, SQL) |
| X-05 | P0 | Zona privada/pública en todos los caminos de salida | `pin geography` solo aparece en consultas internas de resolución; auditar acta PDF, notify y export |
| X-06 | P1 | Token de workspace comprometido (rotación) | Tokens revocables sin downtime; el token no habilita lectura masiva del log |
| X-07 | P1 | Inyección vía texto libre (payload del LLM hacia SQL/HTML del export) | Parametrización total; el texto de reportes jamás se interpola en `tabla.html` sin escape (y de base, no se publica texto libre) |
| X-08 | P2 | Detección de patrón coordinado (falsos censos) | Ráfaga de eventos de hashes distintos pero patrón idéntico genera alerta interna, no bloqueo automático |

---

## 6. Qué NO se prueba aquí (frontera con la plataforma Vozy)

Fuera de alcance del Radar Core — se asume cubierto por Vozy, pero **debe verificarse manualmente antes del día 2** (son las capacidades listadas como "a confirmar" en la arquitectura):

- Transcripción de voz y extracción LLM ("agua y remedios pa la presión" → `["agua","medicamentos"]`)
- Sesiones, timeouts, reintentos de mensaje y ventana de 24 h de Meta
- Envío de documentos PDF por WhatsApp
- Que WhatsApp y voz compartan el mismo procedure sin bifurcar la definición
- Que la API de salida proactiva sea invocable por un servicio externo con `reporter_ref`

La suite S simula el **comportamiento** de la plataforma (reintentos, datos sucios, refs opacas), no la plataforma misma.

---

## 7. Orden de implementación sugerido

Alineado con el orden de construcción (architecture.md §6):

1. **Día 1** junto con el primer código: U-10, U-20, U-30..U-33, I-01, I-05, S-10 — los invariantes se prueban desde el commit uno.
2. **Día 2** (agentes + actas): S-11..S-14, I-32, U-61.
3. **Día 3** (reconciliación + export): I-16..I-22, S-30..S-33, X-01..X-05.
4. **Día 4** (voz + gazetteer): U-50..U-55, S-20..S-23, P-02.
5. **Día 5** (punta a punta): S-40..S-42, P-01..P-08 como gate antes de la prueba con despachador real.
