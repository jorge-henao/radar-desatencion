# Suite de casos de prueba — Radar de Desatención

> **Perspectiva:** el sistema se prueba desde el punto de vista de los sistemas que se
> integran con él, para soportar los casos de uso de las épicas:
>
> - los **tres agentes Vozy** — tool calls síncronos, con reintentos y datos sucios de LLM/voz (épica 01)
> - las **aplicaciones externas** que consumen la salida pública — despachadores, instituciones, CSV/HXL/GeoJSON (épica 01)
> - el **visitante web** de las vistas ciudadana y operativa, detrás de Cloudflare (épicas 02–03)
> - **Lili Analyze** — consumida solo por su API de lectura (épica 02)
> - **Ayudas Pereira** — feed `acopios.json` entrante y `desatencion.json` saliente (épica 02)
> - las **fuentes de medios** del Vigía — contenido de terceros no confiable (épica 03)
>
> Convención de IDs: `U-` unitaria · `I-` integración · `S-` servicio/contrato · `E-` punta a punta
> del sistema · `P-` performance · `X-` transversal (seguridad/privacidad). Los IDs de las
> épicas 02 y 03 llevan el número de épica: `U2-`, `I2-`, `S2-`, `U3-`, `I3-`, `S3-`.
> Prioridad: **P0** = bloqueante (protege un invariante), **P1** = core, **P2** = robustez.

---

## 0. Estructura de `tests/` y ejecución

La carpeta espeja esta suite: **unitarias e integración por épica**, y clasificaciones
del sistema completo (e2e, performance, transversal) al nivel raíz.

```
tests/
  conftest.py                      # fixtures compartidos (DB de pruebas :54329/radar_test)
  epica01_radar_atencion/
    unit/                          # U-xx
    integration/                   # I-xx
    contrato/                      # S-xx — el agente Vozy como consumidor
  epica02_radar_ciudadano/         # U2/I2/S2 — se implementan con los componentes 9–11
  epica03_radar_operativo/         # U3/I3/S3 — se implementan con los componentes 12–14
  e2e/                             # S-3x/S-4x/E-xx — sistema completo, salida pública
  performance/                     # P-xx
  transversal/                     # X-xx — seguridad y privacidad
```

Los markers de tipo (`unit`, `integration`, `service`, `performance`, `transversal`) viven en
cada módulo; los de épica y e2e (`epica01`, `epica02`, `epica03`, `e2e`) se derivan de la
carpeta automáticamente (conftest raíz):

```bash
poetry run pytest                    # suite completa (previa ./scripts/dev_db.sh)
poetry run pytest -m epica01         # todo lo de la épica 01
poetry run pytest -m "unit or e2e"   # por tipo
```

P-06 corre acortada por defecto (15 s); `RADAR_PERF_FULL=1` la ejecuta a los 5 minutos
completos de la especificación. Los IDs de esta suite van en los nombres de cada test.

---

## 1. Matriz de riesgo → cobertura

| Invariante / riesgo | Casos que lo protegen |
|---|---|
| PII nunca entra al Core | X-01..X-04 |
| `events` append-only | U-10, I-01, I-02 |
| Publicación agregada a pcode (nunca pin) | X-05, I-20, S-30, U2-22, S2-11 |
| Idempotencia real ante reintentos de la plataforma | U-20, I-05, S-10..S-12, P-05 |
| Validación de dominio en el Core, no en el LLM | U-30..U-34, S-13..S-15, U3-02..U3-03 |
| Sin eventos = alerta_maxima, no NULL | U-40, I-15 |
| Voz: transcripción sucia → pcode correcto o desambiguación | U-50..U-55, S-20..S-24 |
| Nunca auto-resolver sin certeza; toda ubicación con procedencia | U-56..U-58, I-13, I-14 |
| Latencia compatible con conversación de voz | P-01..P-04 |
| Export estático correcto y sin dependencia de DB en lectura | I-20..I-23, S-30..S-33, I2-05, E-14 |
| Notificador nunca envía directo / usa ref opaca | I-30, X-03 |
| Señales de medios NUNCA en el log de eventos | U3-01..U3-05, I3-03, E-13 |
| Audio sin consentimiento jamás público | U2-01, S2-01, E-12, X-10 |
| El front no inventa — renderiza | U2-20, U2-21, U2-25, S3-05 |
| El Vigía no degrada la alerta por ausencia | U3-09, S3-02, E-13 |
| Lili Analyze solo por API de lectura (nunca ES, nunca invocar análisis) | I2-02, X-13 |
| Degradación automática ante dependencias externas caídas | U2-10, I3-05, E-11 |
| Nunca publicar localidad sin pcode conciliado | I3-01, U3-04 |

---

## 2. Épica 01 — Radar de Atención (implementada)

### 2.1 Unitarias (U) — `tests/epica01_radar_atencion/unit/`

#### Folios e idempotencia

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-01 | P1 | Generación de folio | Formato `DS-NNNN`, único, monotónico o no-colisionante bajo concurrencia |
| U-02 | P2 | Folio citable por voz | Sin caracteres ambiguos al dictado; parseo tolera `ds 0392`, `DS-0392`, `ds0392` |
| U-10 | P0 | Capa de persistencia de `events` | No expone operación de UPDATE/DELETE; una corrección produce un evento nuevo con referencia al folio corregido |
| U-20 | P0 | Resolución de `idempotency_key` | Misma key → retorna el evento/folio original sin insertar; key nueva → inserta |
| U-21 | P1 | Key igual con payload distinto | Se retorna el evento original y se marca discrepancia en `warnings[]` (nunca dos eventos) |

#### Validación de esquema por tipo de evento

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-30 | P0 | Payload `need` válido / inválido | Válido pasa; inválido rechaza con error estructurado `{codigo, campo, motivo}` |
| U-31 | P0 | Payload `dispatch` válido / inválido | Ídem; incluye destino (pcode) y categorías |
| U-32 | P0 | Payload `receipt` válido / inválido | Ídem; `folio_citado` opcional |
| U-33 | P0 | Categoría fuera del enum (`agua\|alimentos\|medicamentos\|aseo\|techo\|otro`) | Rechazo server-side aunque el agente la haya "normalizado" — no se confía en el LLM |
| U-34 | P1 | Campos extra / tipos incorrectos inyectados por el LLM (`hogares: "como veinte"`) | Rechazo estructurado por campo, no error 500 ni coerción silenciosa |
| U-35 | P1 | `reporter_ref` ausente o vacío | Rechazo — es obligatorio en todo `crear_evento` |

#### Métrica de desatención

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-40 | P0 | pcode sin ningún evento | Métrica = `alerta_maxima`, jamás NULL ni excluido del resultado |
| U-41 | P1 | Cálculo días-desde-última-entrega | Usa el último `receipt` reconciliado del pcode, no el último `dispatch` |
| U-42 | P2 | Decaimiento/dedup de eventos `need` repetidos | Reportes repetidos del mismo reporter_hash+pcode no inflan la métrica |

#### Geo y gazetteer (el caso difícil: voz)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-50 | P0 | Match exacto: "Jamundí" | pcode del municipio, `confianza` alta, nivel `municipio` |
| U-51 | P0 | Match ambiguo: "La Cabaña" (existe en Jamundí y Riofrío) | `candidatos[]` con ambos, `confianza` bajo umbral — nunca elegir uno silenciosamente |
| U-52 | P0 | Transcripción sucia: "la beredita la cabaña por jamundi" | Fuzzy match resuelve o devuelve candidatos; nunca error |
| U-53 | P1 | Alias y apócopes del gazetteer ("San José" → San José del Palmar en contexto Chocó) | El alias resuelve al pcode canónico |
| U-54 | P1 | Lugar inexistente / basura ("asdfgh") | `candidatos[]` vacío + confianza 0, respuesta estructurada (el agente repregunta) |
| U-55 | P2 | Texto con municipio como desambiguador ("La Cabaña, Jamundí") | El municipio acota la búsqueda y sube la confianza |
| U-56 | P0 | Corpus de relleno sin lugar ("por ahí cerquita del río", "en la vereda esa") contra catálogo denso de nombres reales | Ninguna auto-resuelve a un pcode; el control positivo de transcripciones sucias reales sigue resolviendo |
| U-57 | P0 | Candidato único por debajo del piso ("kibdo" → Quibdó) | `pcode` null + `motivo: "confianza_baja"` + `candidatos[]` no vacío — se ofrece, no se elige |
| U-58 | P0 | Palabras de nombres reales del DANE contra la lista de stopwords | Ninguna es stopword; ningún nombre del catálogo normaliza a vacío |
| U-59 | P1 | Title case de topónimos ("VALLE DEL CAUCA") | "Valle del Cauca", no "Valle Del Cauca" — el departamento se lee en voz |

#### Otros

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U-60 | P1 | Hash de `reporter_ref` | Determinístico, con salt de servicio, no reversible; el ref en claro no se persiste |
| U-61 | P1 | Contenido del QR del acta | `wa.me/<num>?text=<folio>` correcto y escaneable |
| U-62 | P2 | Etiquetado HXL del CSV | Fila de hashtags HXL válida bajo los encabezados |

### 2.2 Integración (I) — `tests/epica01_radar_atencion/integration/`

*Con Postgres+PostGIS real, shapefiles DANE de muestra y gazetteer de fixtures.*

#### Base de datos

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-01 | P0 | UPDATE/DELETE directo sobre `events` | Bloqueado a nivel de DB (trigger/permiso de rol), no solo por convención de código |
| I-02 | P0 | Evento de corrección | Nuevo registro con referencia al folio original; el original queda intacto |
| I-03 | P1 | Carga de shapefiles DANE con geometría inválida | `ST_MakeValid` al ingestar; ningún polígono inválido llega a query time |
| I-05 | P0 | Dos inserts concurrentes con la misma `idempotency_key` | Exactamente un evento (constraint único en DB, no solo check en aplicación) |

#### Resolución geográfica

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-10 | P0 | Pin dentro de un municipio conocido | pcode correcto contra el polígono DANE |
| I-11 | P1 | Pin en frontera entre polígonos / dentro de centro poblado | Resuelve al nivel más específico (`centro_poblado` sobre `municipio`) |
| I-12 | P1 | Pin fuera de Colombia o en el mar | Respuesta estructurada "fuera de cobertura", nunca 500 |
| I-13 | P0 | Procedencia de toda ubicación resuelta, en ambos modos | Si hay `pcode` hay `municipio_pcode` + `municipio_nombre`, en la respuesta y en cada candidato; un municipio es su propio municipio; sin ubicación, la procedencia va entera en null |
| I-13b | P0 | Pin sobre territorio sin municipio (filas heredadas del pre-guard) | Degrada al nivel más específico con procedencia; el insituable no aparece ni como candidato; si ninguno la tiene, `motivo: "procedencia_incompleta"` con `candidatos: []` |
| I-13c | P0 | Texto que resuelve a un municipio ausente del índice (seed parcial) | El candidato se filtra antes de decidir — no se auto-resuelve ni se ofrece; `motivo: "procedencia_incompleta"` |
| I-14 | P1 | Mismo territorio por pin y por texto | Idénticos `municipio_*` y `departamento_*` — las dos fuentes (PostGIS y el índice en memoria) no pueden divergir |
| I-15 | P0 | Refresh de `mv_desatencion` con territorio priorizado sin eventos | El pcode aparece con `alerta_maxima` |

#### Reconciliación (batch)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-16 | P0 | `receipt` que cita folio de `dispatch` existente | Match determinístico; par marcado como reconciliado |
| I-17 | P1 | `receipt` sin folio, coincidente en pcode+categoría+ventana temporal con un `dispatch` | Match **probabilístico y marcado como tal** — distinguible del determinístico |
| I-18 | P1 | `dispatch` sin `receipt` tras el umbral de desfase | Genera candidato de `alerta_desfase` para el notificador |
| I-19 | P2 | `receipt` que cita folio inexistente | No rompe el batch; queda en cola de no-matcheados |

#### Export estático

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-20 | P0 | Contenido del export (CSV/GeoJSON/HTML) | Solo agregados por pcode: cero coordenadas de pin, cero reporter_hash, cero payload crudo |
| I-21 | P1 | GeoJSON generado | Válido (parseable, geometrías correctas), un feature por pcode con la métrica |
| I-22 | P1 | Job de export con DB caída | El export anterior sigue sirviéndose; el job falla con alerta, no publica archivo vacío/corrupto |
| I-23 | P2 | Estabilidad de columnas del CSV | Nombres de columna idénticos entre corridas (contrato con consumidores externos) |

#### Notificador y actas

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I-30 | P0 | Comprobante listo → notificación | Se llama `POST {plataforma}/notify` con `reporter_ref` opaco + plantilla + `adjunto_url`; ningún envío directo |
| I-31 | P1 | Plataforma de notify caída / 5xx | Reintento con backoff; la notificación no se pierde ni se duplica |
| I-32 | P1 | Generación de acta para `dispatch` | PDF con folio, QR y número oficial; `acta_url` accesible para que la plataforma la adjunte |

### 2.3 Contrato (S) — `tests/epica01_radar_atencion/contrato/`

*Simulando exactamente lo que envía la plataforma Vozy. Estas son las pruebas que un agente "vive" en conversación.*

#### Autenticación y contrato general

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-01 | P0 | Request sin token / token inválido de workspace | 401 estructurado; ningún efecto secundario |
| S-02 | P1 | Content-type incorrecto o JSON malformado | 400 estructurado, no 500 |
| S-03 | P1 | Errores estructurados consumibles por el agente | Todo rechazo incluye `{codigo, campo, motivo}` suficiente para formular una repregunta sin lógica adicional |

#### `crear_evento` — el flujo del agente

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-10 | P0 | **Reintento de la plataforma** (timeout percibido, misma `idempotency_key`) | Misma respuesta, mismo folio, un solo evento — es el escenario de producción más frecuente |
| S-11 | P0 | Happy path `receipt` completo (flujo `radar_recepcion` de punta a punta) | `folio` retornado; evento consultable vía `consultar_folio` |
| S-12 | P1 | `dispatch` válido | Respuesta incluye `acta_url` descargable (solo dispatch la tiene) |
| S-13 | P0 | Payload con categoría inventada por el LLM | Rechazo estructurado; el evento NO se crea |
| S-14 | P1 | Posible duplicado (mismo reporter_hash, pcode y categoría en ventana corta) | Se crea con `warnings[]` de duplicación — advertir, no bloquear |
| S-15 | P1 | `need` — verificación de que el Core no exige datos prohibidos | El esquema no contiene ni acepta cédula, teléfono ni datos bancarios |
| S-16 | P2 | Rate limiting por reporter_hash | Ráfaga anómala del mismo hash se limita con error estructurado; hashes distintos no se afectan |

#### `resolver_ubicacion` — ambos modos

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-20 | P0 | Modo pin (WhatsApp): coordenadas de un municipio priorizado | pcode + nombre_oficial + confianza alta |
| S-21 | P0 | Modo texto (voz): nombre único | pcode correcto, sin desambiguación |
| S-22 | P0 | Modo texto: nombre ambiguo | `candidatos[]` ≥ 2 y confianza bajo umbral → el agente puede preguntar "¿La Cabaña de Jamundí o la de Riofrío?" |
| S-23 | P1 | Ni pin ni texto, o ambos a la vez | 400 estructurado indicando el modo esperado |
| S-24 | P0 | Desde el agente: procedencia suficiente para repreguntar | Cada candidato trae municipio, departamento y `etiqueta` legible tal cual; `pcode` y `confianza` nunca se contradicen |

#### `consultar_folio`

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-25 | P0 | Folio existente | `{existe: true, type, estado, resumen}` — suficiente para precargar destino en `radar_recepcion` |
| S-26 | P0 | Folio inexistente / con typo de dictado | `{existe: false}` con 200 — es un resultado, no un error; el flujo continúa sin folio |

---

## 3. Épica 02 — Radar Ciudadano (especificada; se implementa con los componentes 9–11)

*Consumidores simulados: el API de llm-insights (mock tipado contra su OpenAPI), el feed
`acopios.json` de Ayudas Pereira (fixtures), el agente Vozy invocando `buscar_gracias`,
y el visitante web de la vista narrativa.*

### 3.1 Unitarias (U2) — `tests/epica02_radar_ciudadano/unit/`

#### Banco de voces (componente 9)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U2-01 | P0 | Audio sin `consentimiento=true` | Jamás alcanza estado publicable ni URL pública; disponible solo como evidencia privada del despachador reconciliado |
| U2-02 | P0 | Gate de moderación por modo (`auto`/`manual`/`hibrido`) | auto: pasa el gate → publica, no pasa → rechazado con registro; hibrido: score bajo → auto-publica, rango medio → cola manual, alto → rechazado; cambiar de modo = configuración |
| U2-03 | P1 | Recorte de span + transcodificación | Clip exacto `[span_inicio_s, span_fin_s]`; SIEMPRE se produce MP3/AAC (OGG/Opus no reproduce confiable en Safari/iOS); el original se conserva |
| U2-04 | P1 | Resolución de insights por nombre al arrancar | `insight_id` resuelto vía `GET /db/insights` con el nombre configurado — nada hardcodeado; nombre inexistente → error de arranque explícito, no fallo silencioso en runtime |
| U2-05 | P1 | `MencionaNombresPropios=true` | Va a cola manual aunque el score pase el gate (señal de privacidad) |
| U2-06 | P1 | Selección de `buscar_gracias` | Universo = `estado ∈ {aprobado, auto_aprobado}` ∧ consentimiento — idéntico al de la web pública; el aleatorio ponderado penaliza lo recién reproducido y favorece voces poco escuchadas |
| U2-07 | P2 | Asociación audio→territorio | Prioridad: folio citado > pcode del evento vinculado; sin ninguno → retenido, no publicable |

#### Importador de feeds de aliados (componente 10)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U2-10 | P0 | Feed caído o con datos viejos (> umbral de frescura) | Degradación automática a fase 0 (panel referidos) **sin intervención**; al volver el feed fresco, re-asciende solo |
| U2-11 | P1 | Ítem del feed con categoría fuera del enum compartido o `municipio_dane` no-DIVIPOLA | Se descarta el ítem con registro — no el feed completo |
| U2-12 | P2 | Fase 2 sin fase 1 | Un acopio vinculado en `orgs` puede declarar despachos aunque `feed_acopios_url` sea null (no es dependencia dura) |

#### Generador de vista ciudadana (componente 11)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U2-20 | P0 | **Auditoría de strings** del HTML generado | Todo string visible ∈ datos ∪ plantillas P1–P8 ∪ microcopy M0–M7 (spec §4, listas taxativas); un string no señalable = fallo del test |
| U2-21 | P0 | Selección determinística de la historia destacada | Regla de spec §1: `RECEIPT` reconciliado más reciente con mayor espera resuelta; empate → más hogares; sin cadena `dispatch→receipt` elegible → `historia: null` y el scrolly renderiza solo S0–S1 |
| U2-22 | P0 | Coordenadas en `vista-ciudadana.json` | Siempre centroides agregados de vereda/centro poblado — nunca el pin del evento; `voces[]` solo con `autorizado=true` (el front no filtra privacidad: ya viene filtrado) |
| U2-23 | P1 | Plantilla P1 por umbral de proporción | `confirmadas/(confirmadas+esperando)` en ≥0.66 / 0.33–0.66 / <0.33 produce la frase correcta; los bordes exactos (0.33, 0.66) definidos y testeados |
| U2-24 | P1 | Cero audios / cero aliados / cero eventos | La vista renderiza completa: sección de voces muestra la "esencia" con el contador real (nunca desaparece ni se disculpa); panel Cómo ayudar en modo referidos; ninguna sección rota |
| U2-25 | P1 | Dato ausente para una plantilla | La frase NO se renderiza — jamás se rellena (`org_publica: null` → "un acopio de {origen.mun}") |
| U2-26 | P2 | Cálculo de "Día N" de la historia | Derivado de las fechas del log, nunca manual (el caso real que motivó la regla: un "Día 8" corregido a 9 por el cálculo) |

### 3.2 Integración (I2) — `tests/epica02_radar_ciudadano/integration/`

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I2-01 | P0 | Pipeline completo del adaptador Analyze contra API simulada | insight con consentimiento → copia a bucket propio (nunca hot-link al de Lili) → recorte → MP3 → gate → estado correcto en `audio_gracias` |
| I2-02 | P0 | Superficie de llamadas del adaptador | Solo lecturas del API llm-insights; **nunca** `/analyses:run`, cero clientes ES/S3 de Analyze en el código (auditoría del mock: toda llamada fuera de la lista blanca falla el test) |
| I2-03 | P1 | Cambio de mapeo JSONPath en configuración | Campo re-mapeado sin tocar código; mapeo roto → error de configuración explícito, nunca datos corruptos silenciosos |
| I2-04 | P1 | Poll incremental de resultados | El cursor persiste; reprocesar el mismo lote no duplica filas en `audio_gracias` (idempotencia del job — paridad con la trampa de reintentos de la Tools API) |
| I2-05 | P1 | Export integrado | `vista-ciudadana.json` + HTML autocontenido salen del mismo job de 5 min; job caído → la versión anterior sigue sirviéndose (paridad I-22) |
| I2-06 | P2 | Fase 2: vincular un acopio en `orgs` | La página `/acopio/{id}` aparece en el siguiente export, generada estáticamente — sin superficie dinámica nueva |

### 3.3 Contrato (S2) — `tests/epica02_radar_ciudadano/contrato/`

#### `buscar_gracias` — el agente Vozy como consumidor

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S2-01 | P0 | `{aleatorio: true}` | Clip aprobado+consentido con ambas URLs (`clip_url_ogg` para nota de voz WhatsApp, `clip_url_mp3` para telefonía); la reproducción queda registrada (rotación + métrica) |
| S2-02 | P0 | `{pcode}` de territorio sin audios / filtros sin resultados | Respuesta estructurada "sin resultados" que permite al agente ofrecer el aleatorio como fallback — nunca 404 ni 500 |
| S2-03 | P1 | Filtros combinados (`sentimiento` + `categorias`) | Filtra por insights estructurados; `categorias` usa el enum compartido; `pcode` resuelto vía el mismo gazetteer |
| S2-04 | P1 | Universo de selección | El endpoint jamás sirve un audio no aprobado o sin consentimiento — mismo universo que la web pública, verificado con fixtures adversariales |

#### La vista pública — visitante web

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S2-10 | P0 | HTML autocontenido | ≤45KB, cero requests a hosts externos, renderiza con la red bloqueada (protocolo de spec §9); ambos temas A/E completos, ningún color fuera de `:root` |
| S2-11 | P0 | Auditoría PII de los artefactos nuevos | `vista-ciudadana.json`, HTML narrativo y páginas `/acopio/{id}`: sin pins, teléfonos, nombres de reporters, refs ni transcripts |

#### Aliados — Ayudas Pereira como consumidor

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S2-20 | P1 | `desatencion.json` consumible por su SPA | CORS abierto, esquema estable entre corridas; todo enlace saliente hacia ellos lleva `?utm_source=radar-desatencion` |

---

## 4. Épica 03 — Radar Operativo (especificada; se implementa con los componentes 12–14)

*Consumidores/fuentes simulados: fuentes de medios como fixtures HTML/RSS (incluidas
adversariales), el gazetteer real del core, y el despachador (U2/U3) leyendo
`vista-operativa.json`.*

### 4.1 Unitarias (U3) — `tests/epica03_radar_operativo/unit/`

#### Reglas de extracción del Vigía

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U3-01 | P0 | Señal sin URL verificable | Descartada — no se persiste, no suma refuerzos ("señal sin URL = señal descartada") |
| U3-02 | P0 | Documento sin cifras de hogares | `hogares_estimados` ausente — el extractor **jamás** inventa cifras no presentes en el texto; `cita` textual ≤ ~40 palabras |
| U3-03 | P0 | Categoría fuera del enum compartido | Rechazo/normalización server-side al mismo enum de eventos y acopios (`agua\|alimentos\|medicamentos\|aseo\|techo\|otro`) |
| U3-04 | P0 | Texto sin localidad resoluble | No se produce señal (regla dura: sin localidad no hay señal; nunca un pin inventado) |

#### Ciclo de vida de la señal

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| U3-05 | P0 | Dedupe | Misma (pcode, categorías∩, ventana 7 días) → `refuerzos+1` y fuente anexada — nunca fila nueva; "según 3 fuentes" > "según 1" |
| U3-06 | P1 | Decaimiento | Señal sin refuerzo en `caducidad_dias` → `caducada` y sale de la vista |
| U3-07 | P0 | Conversión | NEED de primera mano en un pcode con señal activa → señal `convertida`; el reporte pasa a capa principal y la señal queda como contexto |
| U3-08 | P1 | Descarte humano | Estado `descartada` con `descartada_por` poblado — auditable |
| U3-09 | P0 | **La métrica no consume señales** | `mv_desatencion` idéntica con y sin señales; territorio sin eventos NI señales = `alerta_maxima` — el Vigía nunca la degrada |
| U3-10 | P1 | `vigia.yaml` gobierna el agente | Agregar/desactivar fuente o cambiar cadencia = editar YAML, sin código; la `confianza` de la fuente viaja a la señal |
| U3-11 | P2 | Contenido ya procesado (hash por URL) | No se re-extrae — control del costo LLM del barrido |

### 4.2 Integración (I3) — `tests/epica03_radar_operativo/integration/`

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| I3-01 | P0 | Conciliación de localidades contra el gazetteer real | Confianza alta → señal con pcode, visible; ambigua → candidatos guardados, visible solo en sección de revisión; sin match → `localidades_por_incorporar` con la señal retenida — **jamás publicada sin pcode** |
| I3-02 | P1 | Enriquecimiento + aprobación humana | Candidato propuesto vía DIVIPOLA/COD-AB; la aprobación da de alta pcode/alias en el gazetteer y desde entonces `resolver_ubicacion` también lo resuelve (el Vigía engorda el gazetteer) |
| I3-03 | P0 | Frontera con el log de eventos | Cero filas originadas por el Vigía en `events`; el CSV/HXL de auditoría de primera mano no contiene señales |
| I3-04 | P1 | Run completo del grafo con fuentes fixture | planificar → recolectar → extraer → conciliar → persistir → reportar; el log de auditoría de la pasada registra conteos por fuente |
| I3-05 | P2 | Una fuente caída durante el run | El run continúa con las demás fuentes; la falla queda en el log de la pasada — nunca aborta el barrido completo |

### 4.3 Contrato (S3) — `tests/epica03_radar_operativo/contrato/`

*El despachador (U2 acopios/ONGs, U3 CMGRD) como consumidor de `vista-operativa.json` y la vista.*

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S3-01 | P0 | Día cero, `modo=curado`, tras la primera pasada | `vista-operativa.json` poblado; barra de estado con última pasada, fuentes activas y señales — el mecanismo se declara |
| S3-02 | P0 | Cero señales Y cero reportes (peor caso) | La tabla muestra los territorios del área afectada con alerta por ausencia + explicación de cómo reportar — nunca una tabla vacía sin sentido |
| S3-03 | P1 | `modo=mixto` | Reportes de primera mano por encima de señales equivalentes; territorio con ambos: reporte como principal + "y N medios lo confirman" |
| S3-04 | P1 | Procedencia siempre etiquetada | Chips `⚑ medios` / `✉ reporte directo` distinguibles en los tres modos; ninguna fila mezcla capas sin etiqueta |
| S3-05 | P1 | Fila expandida | Cada señal con cita textual + fuente + fecha + URL funcional — la urgencia se muestra con la cita, nunca con paráfrasis del front |
| S3-06 | P2 | Cambiar `vista_operativa.modo` | Reordena capas en el siguiente export, sin deploy |

---

## 5. Punta a punta del sistema (E) — `tests/e2e/`

*El sistema completo desde afuera: agentes, salida pública, y — al implementar las
épicas 02/03 — el lazo completo entre las tres.*

### 5.1 Salida pública — otras aplicaciones consumidoras (implementadas)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-30 | P0 | Auditoría de PII sobre los tres artefactos públicos | Grep exhaustivo: sin teléfonos, refs, hashes, coordenadas exactas ni texto libre de reportes |
| S-31 | P1 | `datos.csv` consumido por herramienta externa | Parseable, HXL válido, cada pcode priorizado presente (incluidos los de `alerta_maxima`) |
| S-32 | P1 | `geojson` en un visor de mapas estándar | Renderiza; propiedades documentadas presentes en cada feature |
| S-33 | P1 | Frescura del export | Header/campo de "generado el" ≤ 5 min tras cambios; cacheable en Cloudflare |
| S-34 | P2 | QR de un acta escaneado por un tercero | Abre `wa.me` con el folio precargado; el folio existe vía `consultar_folio` |

### 5.2 Escenarios de negocio (implementados)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| S-40 | P0 | Ciclo completo: `dispatch` (con acta) → `receipt` citando el folio → reconciliación → export | El pcode sale del estado de desatención en la siguiente corrida del export |
| S-41 | P1 | Ciclo voz: `receipt` con ubicación hablada ambigua → desambiguación → evento → export | El evento queda en el pcode confirmado por el usuario |
| S-42 | P1 | Corrección: evento nuevo referenciando folio equivocado | El export refleja la corrección; el log conserva ambos eventos |

### 5.3 Escenarios inter-épicas (se implementan con las épicas 02/03)

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| E-10 | P0 | **El dominó completo** (é03→é01→é02): señal del Vigía sobre un pcode → `dispatch` con folio hacia ese pcode → `receipt` que cita el folio → reconciliación → gracias con consentimiento pasa el gate | La señal queda `convertida`; la historia aparece en `vista-ciudadana.json`; el audio se publica y se notifica al despachador reconciliado — cada eslabón verificable en los artefactos del export |
| E-11 | P1 | Degradación en cascada: API de Analyze caída + feed de aliados viejo + una fuente del Vigía caída | Ambas vistas renderizan completas (esencia data-driven, panel referidos, señales con decaimiento normal); ningún bloque roto ni error visible al público |
| E-12 | P0 | Consentimiento de punta a punta: gracias procesado **sin** flag de consentimiento | Nunca en `vista-ciudadana.json`, ni en el HTML, ni vía `buscar_gracias`; sí disponible en el comprobante privado del despachador reconciliado |
| E-13 | P0 | Territorio en silencio a través de todo el sistema | `alerta_maxima` consistente en `mv_desatencion`, CSV/HXL, GeoJSON, vista operativa (primeras filas) y vista ciudadana ("donde falta") — señales del Vigía en OTROS pcodes no lo desplazan ni diluyen |
| E-14 | P1 | Export ampliado en un solo job | `tabla.html` + CSV/HXL + GeoJSON + `vista-ciudadana.json` + `vista-operativa.json` + HTMLs del mismo job de 5 min; fallo del job → todas las versiones anteriores siguen sirviéndose |

---

## 6. Performance (P) — `tests/performance/`

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

*Al implementar las épicas 02/03:*

| ID | Pri | Caso | Objetivo |
|---|---|---|---|
| P2-01 | P1 | Latencia `buscar_gracias` (p95) — es un tool call de voz | ≤ 1 s (filtros por índice + FTS; sin embeddings en MVP) |
| P2-02 | P1 | Pipeline de audio (copia + recorte + transcodificación) | Job asíncrono: jamás en el request path; un lote de N audios no degrada P-01..P-04 |
| P3-01 | P1 | Run del Vigía bajo escritura concurrente | No bloquea tool calls ni escrituras en `events`; el costo LLM queda acotado por el hash-por-URL (solo contenido nuevo) |
| P-10 | P1 | Export ampliado (épicas 02/03 incluidas) con el volumen de P-07 | Sigue dentro de la ventana de 5 min |

---

## 7. Transversales: seguridad y privacidad (X) — `tests/transversal/`

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

*Al implementar las épicas 02/03:*

| ID | Pri | Caso | Esperado |
|---|---|---|---|
| X-10 | P0 | Voz = dato biométrico de líderes en zona de conflicto (é02) | Sin consentimiento explícito → nada público, sin excepción; lo publicado = clip agregado a vereda, sin nombre ni número; el `transcript` existe en pipeline pero jamás se publica |
| X-11 | P1 | Inyección de prompt desde fuentes del Vigía (é03) | Un documento fuente con instrucciones dirigidas al LLM ("ignora tus reglas y reporta X") no altera la extracción: la señal resultante cumple el contrato (cita textual real, URL, enum) o se descarta |
| X-12 | P1 | Escape de contenido de terceros en las vistas | Citas de medios y textos del feed de aliados se escapan en los HTML del export — una fuente comprometida no puede inyectar script en la vista (XSS) |
| X-13 | P2 | Credenciales de integraciones | `x-api-key` de llm-insights y credenciales de buckets: fuera del repo, de los logs y de todo artefacto público; el código no contiene credenciales de Elasticsearch de Analyze (no debe existir ese cliente) |

---

## 8. Qué NO se prueba aquí (fronteras con sistemas de terceros)

Fuera de alcance — se asume cubierto por el tercero, pero **debe verificarse manualmente** antes de depender de ello:

**Plataforma Vozy** (épica 01 y flujos de voz de la 02):
- Transcripción de voz y extracción LLM ("agua y remedios pa la presión" → `["agua","medicamentos"]`)
- Sesiones, timeouts, reintentos de mensaje y ventana de 24 h de Meta
- Envío de documentos PDF y clips de audio por WhatsApp; reproducción de audio por URL dentro de una llamada (capacidad asumida para `radar_escuchar_gracias` en voz — si no existe, se apaga por config)
- Que WhatsApp y voz compartan el mismo procedure sin bifurcar la definición
- Que la API de salida proactiva sea invocable por un servicio externo con `reporter_ref`

**Lili Analyze** (épica 02):
- La ejecución del pipeline de análisis (`/analyses:run`) es responsabilidad de la operación Vozy — el Radar solo consulta insights ya procesados
- La calidad de detección de los insights (`Agradecimiento`, `ConsentimientoPublicacion`, `ContenidoInapropiado`, etc.) — se calibra con el equipo Analyze, no con esta suite

**Ayudas Pereira** (épica 02):
- La disponibilidad y frescura de su `acopios.json` — la suite solo prueba nuestra degradación cuando falla

**Fuentes de medios** (épica 03):
- La veracidad del contenido — la suite prueba que toda señal sea verificable (cita + URL) y descartable, no que el medio tenga razón

Las suites S/S2/S3 simulan el **comportamiento** de estos sistemas (reintentos, datos sucios, feeds caídos, contenido adversarial), no los sistemas mismos.

---

## 9. Orden de implementación

Regla transversal: **los tests de invariantes (P0) se escriben junto con la primera versión
de cada componente, no después.**

1. **Épica 01** — implementada: las secciones 2, 5.1, 5.2, 6 (P-01..P-09) y 7 (X-01..X-08) están en verde en `tests/`.
2. **Épica 03, componente 12–13 (Vigía + cola de localidades):** U3-01..U3-05, U3-09, I3-01, I3-03 desde el primer commit; luego U3-06..U3-11, I3-02, I3-04..I3-05, X-11.
3. **Épica 03, componente 14 (vista operativa):** S3-01..S3-06, X-12, P-10.
4. **Épica 02, componente 9 (banco de voces):** U2-01..U2-07, I2-01..I2-04, S2-01..S2-04, X-10, X-13, P2-01..P2-02.
5. **Épica 02, componentes 10–11 (feeds + vista ciudadana):** U2-10..U2-12, U2-20..U2-26, I2-05..I2-06, S2-10..S2-20.
6. **Cierre inter-épicas:** E-10..E-14 como gate antes de publicar las vistas con URL real.

El orden 03-antes-que-02 sigue la lógica de adopción de las épicas: la vista operativa es el
primer dominó (sin despachadores no hay folios; sin folios, la vista ciudadana no tiene qué contar).
