
# Épica: Radar Ciudadano — cierre del lazo con el donante

> **Estado:** consolidada y cerrada para implementación. Corte: 15 de agosto de 2026.
> **Depende de:** `radar-desatencion-arquitectura-v2-vozy.md` (v2.1). Extiende el Radar Core con los componentes 9–11 y la vista pública narrativa.
> **Convención:** los puntos sin definir van marcados `[FALTA]`.

## Mapa de artefactos de esta épica

| Artefacto | Qué es | Relación |
|---|---|---|
| `epica-radar-ciudadano.md` | **Este documento** — producto, integraciones, decisiones | Documento madre; referencia a todos los demás |
| `especificacion-front-radar-ciudadano.md` | Spec de implementación del front: principio data-driven, contrato JSON, tokens, plantillas P1–P8, microcopy M0–M7, mapa, protocolo de verificación, apéndice de basemap | **Contrato para el agente implementador.** Ante ambigüedad con el prototipo, gana la spec |
| `radar-ciudadano-historia.html` | Prototipo funcional de la vista narrativa: scrollytelling data-driven, autocontenido (0 dependencias, 44KB, funciona offline) | Referencia visual y de interacción; semilla del template Jinja2 del componente 11 |
| `radar-exploracion-diseno.html` | Exploración de 5 direcciones de diseño conmutables (A registro / B noche / C río / D bitácora / E tinta) | Documenta la decisión de identidad: **A claro + E oscuro**; B/C/D quedan como banco de lenguaje |
| `radar-ciudadano-prototipo.html` | Prototipo con MapLibre + tiles vectoriales | Superseded para la vista narrativa; queda como referencia si se agrega vista de exploración con detalle vial (PMTiles) |
| `addendum-ayudas-pereira.md` | Análisis de Ayudas Pereira y parches a los docs base | Insumo de la sección 4 |
| `epica-radar-operativo.md` | **Épica hermana**: vista de despacho (U2/U3) + Vigía de Medios (curaduría automatizada LangGraph para el arranque en frío) + conciliación de localidades | Comparte identidad (A/E), principio data-driven y stack; agrega componentes 12–14 al core |

---

## 1. Contexto y objetivo

El Radar conecta necesidad → despacho → recepción, pero el **donante ciudadano** —quien alimenta toda la cadena— solo recibía auditoría fría (U4). Esta épica cierra ese lazo: una vista pública que le muestra al ciudadano **que su ayuda llega**, dónde, y —cuando existe— **la voz del territorio agradeciendo**.

Principios heredados que esta épica NO rompe:

- **No es trazabilidad ítem→persona** (trampa donante-céntrica, insight 8). La granularidad máxima de identidad del donante es *el acopio* — que es lo físicamente real (insight 20: la identidad del ítem se destruye en el acopio).
- **No compite con Ayudas Pereira**: ellos resuelven "dónde donar" (primera milla); nosotros "qué pasó con lo donado" (última milla). La integración es simbiótica, no sustitutiva.
- **Agregación obligatoria** (R6): todo se publica a nivel vereda/pcode. Nunca nombres, nunca pins, nunca teléfonos.
- **La vista ciudadana no oculta la desatención**: muestra también dónde no ha llegado. El contraste es lo que le dice al donante dónde importa su próxima donación.

---

## 2. Decisiones tomadas (no re-debatir)

1. **Se soportan las TRES fases de integración con Ayudas Pereira simultáneamente**, como capacidades activables por configuración — no como etapas de roadmap. El sistema funciona de lo macro a lo micro con lo que haya disponible:
   - **Fase 0 — referidos verificados**: sin acuerdo, sin datos de ellos. Panel "Cómo ayudar" con enlaces salientes verificados + UTM.
   - **Fase 1 — contexto cruzado**: ellos exponen su feed de acopios+necesidades; el CTA se vuelve contextual por categoría y ciudad. Recíprocamente, ellos embeben nuestro JSON de desatención.
   - **Fase 2 — acopio como identidad del donante**: sus acopios entran al catálogo `orgs`, declaran despachos con folio, y cada acopio tiene página pública con sus despachos, confirmaciones y gracias.
2. **Llegamos con la propuesta de contrato de datos hecha** (sección 4). Si ellos ya tienen API, adaptamos con un adapter; si no, les proponemos el JSON estático más simple posible de publicar. La conversación es "esto te sirve tal cual o decinos qué cambiar", no "diseñemos juntos".
3. **La interfaz es UNA sola, preparada para las tres fases.** Las fases no son tres UIs: son slots de la misma vista que se encienden cuando el dato existe. Pasar de fase = cambiar configuración, no desplegar código.
4. **Los audios de agradecimiento se soportan condicionalmente igual**: la vista funciona sin ellos, y se enciende cuando existen. Fuente principal: **Lili Analyze**, consumida **exclusivamente a través de su API** (llm-insights) — la persistencia interna del servicio (Elasticsearch, S3) es detalle de implementación de Analyze que el Radar nunca toca. Adaptador **configurable por metadatos** (sección 5.2). Fuente secundaria: nota de voz de WhatsApp en el flujo de recepción.

---

## 3. La vista ciudadana — estructura narrativa final

**Decisión de forma:** la portada pública ES una historia que se cuenta con el scroll — de lo esencial (arriba, para quien solo quiere la respuesta) a lo personal (abajo, las voces). Dos pestañas: **Radar ciudadano** (esta vista) y **Datos y auditoría** (tabla/CSV/HXL/GeoJSON existente). Detalle completo en `especificacion-front-radar-ciudadano.md` §3; prototipo funcional en `radar-ciudadano-historia.html`.

### Los cinco actos

| Acto | Contenido | Nota |
|---|---|---|
| **1 · La respuesta** (100svh) | Verificación del número oficial (ancla anti-suplantación) → "¿Está llegando la ayuda?" → respuesta en serif (plantilla P1 por umbral de proporción) → contadores confirmadas/esperando → hint de scroll | Debe bastar solo: quien no scrollea se va informado |
| **2 · El país** | Mapa fijo (sticky); pasos "cada punto es una comunidad" y "los que esperan" con conteos reales | Ámbar = espera, nunca rojo |
| **3 · Una historia** | La historia destacada de la semana: un paso por evento del log (need→dispatch→receipt), con "Día N" calculado, folios visibles, y escena de mapa derivada de las coordenadas de cada evento — incluida la ruta origen→destino etiquetada "trayecto ilustrativo" | Selección determinística por el export (spec §1) |
| **4 · Voces de agradecimiento** | Reproductores (si hay audios autorizados) o "esencia" data-driven con el contador real (si no) | La sección nunca desaparece ni se disculpa |
| **5 · Cierre** | "La próxima historia puede empezar con vos" + territorios esperando + CTA "Quiero ayudar" (panel de la sección 4) | El pedido llega después de la evidencia, no antes |

### Principio rector del front (innegociable)

**El front no inventa — renderiza.** Todo string visible proviene de (a) el JSON del export, (b) las plantillas P1–P8, o (c) el microcopy fijo M0–M7 — listas taxativas en la spec §4. Prohibido: personas/roles inferidos, causas no capturadas, citas atribuidas, cifras fuera del JSON. Historia de esta regla: mató frases buenas pero inventadas ("una promotora de salud caminó...", "la vía bloqueada por derrumbes", la cita «gracias por no olvidarnos») — y cazó un error real (un "Día 8" manual que el cálculo corrigió a Día 9). Si algún día se quiere color narrativo, el camino es capturar más datos (p. ej. campo `contexto` curado y aprobado por un humano), nunca que el front lo alucine.

### Identidad visual (decisión tomada tras explorar 5 direcciones)

- **Modo claro = A · Registro civil** (papel frío, teal/ámbar, mono registral) · **Modo oscuro = E · Tinta profunda** (carbón azulado #10161A) — automático por `prefers-color-scheme`, sin toggle. Tokens completos en spec §2.
- Semántica dura de color: **teal** = confirmado/canal del sistema; **ámbar** = espera; `--alerta` reservado a alerta máxima.
- Tres registros tipográficos = tres voces: sans del sistema (narración/UI), **mono** (folios, fechas, contadores — el mono ES el registro), serif (solo voz humana).
- Las direcciones B (Señales en la noche), C (Río abajo) y D (Bitácora) quedan en `radar-exploracion-diseno.html` como banco de lenguaje/estética para piezas de difusión.

### Interacción del mapa: historia y exploración sin costura

Mapa SVG embebido con dos modos: **historia** (el scroll dirige las escenas; el mapa no es interactivo) y **explorar** (botón `✥` → pan/pinch/rueda, tap en punto → chip con nombre/estado/días; el scroll NO retoma el mapa; botón `↩` vuelve volando a la escena del paso activo). Reglas técnicas anti-bug (pointer-events de paso-a-través; tap detectado en pointerup) documentadas en spec §5 — obligatorias.

### Stack (decisión cerrada — sin razones contundentes en contra, no se reabre)

- **Cero servicios nuevos, cero Node, cero build, cero framework.** Python/Jinja2 genera el HTML en el export (componente 11); interacción en vanilla JS (~250 líneas); **mapa SVG autocontenido** (34 departamentos Natural Earth proyectados inline, ~18KB — script en spec Apéndice A). Presupuesto: archivo único ≤45KB, funciona con la red 100% bloqueada.
- El camino MapLibre + PMTiles propio (colombia.pmtiles en bucket, cero tile server) queda documentado en `radar-ciudadano-prototipo.html` para una eventual vista de exploración con detalle vial — mejora progresiva, no requisito.
- Umbral para reabrir la decisión de framework: escritura/estado compartido en la vista (comentarios, sesión). Hoy no existe en el roadmap.
- **Cloudflare delante de todo**: la vista ciudadana es el escenario de pico de prensa y es 100% estática.

### Qué NO tiene esta vista

Compartir por historia en redes (señalización de bienes — pendiente de evaluación), transcripciones visibles de audios (existen en pipeline, no se publican), geolocalización del visitante (la ciudad se pregunta con botones), recaudo propio, registro de usuarios.

## 4. Integración Ayudas Pereira — contrato propuesto y capacidades

### 4.1 Modelo de capacidades (cómo conviven las tres fases)

Un solo archivo de configuración gobierna qué está encendido:

```yaml
aliados:
  ayudas_pereira:
    referidos: true                      # fase 0 — siempre on
    feed_acopios_url: null               # fase 1 — al setear la URL, se enciende
    feed_poll_min: 15
    orgs_vinculadas: false               # fase 2 — se enciende al vincular acopios en orgs
```

Reglas de degradación: si `feed_acopios_url` falla o devuelve datos viejos (> 24 h), la UI degrada automáticamente a fase 0 **sin intervención** — el panel genérico es el fallback permanente. Fase 2 requiere fase 1 activa solo para el contexto, no como dependencia dura: un acopio puede declarar despachos (fase 2) aunque el feed (fase 1) no exista.

### 4.2 Propuesta de contrato — `acopios.json` (lo que les llevamos)

Diseñado para ser **lo más barato posible de publicar para ellos**: un archivo estático versionado, servido con CORS abierto desde su mismo hosting. Sin API, sin auth, sin backend nuevo.

```json
{
  "version": "1.0",
  "updated_at": "2026-08-15T06:00:00-05:00",
  "acopios": [
    {
      "id": "ap-unicentro",
      "nombre": "Acopio Unicentro Pereira",
      "municipio_dane": "66001",
      "lat": 4.8065, "lon": -75.7223,
      "direccion": "Av. 30 de Agosto #75-51",
      "telefono": "+57 6 XXX XXXX",
      "horario": "8:00–18:00 lun–sáb",
      "estado": "activo",
      "necesidades": [
        { "categoria": "agua", "prioridad": "alta", "actualizado": "2026-08-15" },
        { "categoria": "aseo", "prioridad": "media", "actualizado": "2026-08-14" }
      ]
    }
  ]
}
```

Puntos del contrato: `categoria` usa **nuestro enum compartido** (`agua|alimentos|medicamentos|aseo|techo|otro`) — es la clave del join; `municipio_dane` es DIVIPOLA (les damos la tabla); `id` estable (es la futura FK a `orgs` en fase 2). Si su SPA ya consume un JSON interno equivalente, el adapter mapea el de ellos al nuestro y no les pedimos nada.

**Reciprocidad (lo que ellos ganan):** (a) nuestro `desatencion.json` público con CORS para mostrar junto a cada acopio "a dónde está haciendo falta que llegue lo que acá se recibe"; (b) tráfico medible: todo enlace saliente lleva `?utm_source=radar-desatencion`; (c) en fase 2, la respuesta a "¿dónde terminó lo que doné?" a nivel acopio — diferenciador que hoy nadie les da.

### 4.3 Panel "Cómo ayudar" (el CTA en sus tres modos)

Mismo componente, tres estados según configuración:

- **Modo referidos (fase 0):** máximo 5 enlaces organizados por *tipo de ayuda*, no por organización: llevar donaciones (Ayudas Pereira si Risaralda; puntos Colombia Un Solo Corazón otras ciudades) · donar al transporte (ABACO — el cuello de botella real) · todos los canales verificados (Cuidar a Colombia). Selección de ciudad con botones, sin geolocalizar. Es un panel de referidos, NO otro directorio (regla de frontera).
- **Modo contextual (fase 1):** el panel hereda el contexto de navegación — si la persona miraba "La Cabaña espera *agua* hace 11 días", el panel muestra "el acopio Unicentro está recibiendo agua esta semana" (join por categoría + ciudad elegida). Fallback por ítem: si no hay acopio que reciba esa categoría, cae al modo referidos.
- **Modo identidad (fase 2):** página pública por acopio `/acopio/{id}`: despachos declarados, confirmaciones desde territorio, gracias asociados. Enlace de vuelta desde la confirmación de donación de ellos. Generada por el **mismo export estático** — sin superficie dinámica nueva.

---

## 5. Voces del territorio — banco de audios de agradecimiento

### 5.1 Fuentes (ambas condicionales; la vista funciona con cero audios)

| Fuente | Cómo llega | Consentimiento |
|---|---|---|
| **A. WhatsApp** (flujo recepción) | Al cerrar F1.2 el agente ofrece *una vez*: "Si querés, dejá un mensaje de gracias — nota de voz o texto". Media ID → bytes vía plataforma → S3 propio | El agente pregunta explícito: "¿Autorizás que se escuche en la página pública? Aparece con tu vereda, sin tu nombre ni número" |
| **B. Lili Analyze** | Insight `Agradecimiento` detectado en la llamada, con span exacto en el audio. Insights, metadatos y referencia al audio (mp3/ogg) **retornados por el API de llm-insights** | `[FALTA]` definir cómo viaja el flag de consentimiento en la llamada (pregunta del agente al final del flujo, persistida como insight/metadato). **Regla dura: sin flag de consentimiento explícito → el audio nunca es público** (queda disponible solo como evidencia privada para el despachador reconciliado) |

### 5.2 Adaptador Lili Analyze (integración configurable — decisión clave)

La integración tiene **dos planos**, y el API real de llm-insights (verificado contra su OpenAPI, prod) resuelve el primero de forma tipada:

**Plano 1 — Configuración (API llm-insights, conocida y tipada).** El servicio expone la gestión completa de use cases, segments e insights por customer, autenticada por header `x-api-key`:

- `GET /db/insights?customer_id={id}&name_search=Agradecimiento` → devuelve las **definiciones** de insights del customer (paginado: `items[]` con `id`, `name`, `description`, `tags`, `use_cases`, `weight`). El adaptador lo usa al arrancar para resolver el `insight_id` real de cada insight que le interesa — nada de nombres hardcodeados contra los resultados.
- Los insights viven dentro de **segments** (unidades de prompt con `system_prompt`, `task_prompt`, `response_format`, `scope`), agrupados en use cases **versionados** (draft → activate, con diff estructural).
- **Consecuencia de diseño clave:** los tres `[FALTA]` de esta épica dejan de ser incógnitas y se convierten en entregables nuestros — el Radar define sus propios insights en su use case vía `POST /db/create/insight`: `Agradecimiento` (span + texto), `ConsentimientoPublicacion` (booleano — la pregunta de autorización del agente, detectada en la misma llamada) y `ContenidoInapropiado` (score — el gate de moderación). El consentimiento y el gate no son integraciones aparte: **son insights más del mismo pipeline de Analyze.**

**Plano 2 — Resultados (el mismo API, solo lectura — decisión: NO se accede a Elasticsearch directo).** La ejecución del análisis es **responsabilidad de la operación Vozy** y queda fuera del alcance del Radar: el Radar **nunca invoca el análisis** (`/analyses:run` no se usa), solo **consulta los insights ya procesados** asumiendo que Vozy corre el pipeline. Una sola api-key, superficie HTTP de solo lectura, cero acoplamiento al almacenamiento interno. El endpoint/forma exacta de consulta de resultados procesados queda `[FALTA]` por confirmar, pero el spec ya tipa la pieza central: los **segments de conversación** traen `speaker`, `start`, `end`, `duration` y `transcription` — el span y el texto extraído vienen dados por contrato, no hay que inferirlos.

```yaml
insight_sources:
  lili_analyze:
    # Plano 1: configuración
    api:
      base_url: https://llm-insights.prod.eksia.us-east-1.c1.vozy.co
      api_key: ${LLM_INSIGHTS_API_KEY}          # header x-api-key
      customer_id: "[FALTA: customer/use case del Radar]"
      insights:                                  # nombres a resolver → insight_id al arrancar
        agradecimiento: "Agradecimiento"
        consentimiento: "ConsentimientoPublicacion"
        gate_contenido: "ContenidoInapropiado"
    # Plano 2: resultados
    resultados:
      tipo: api                                  # mismo servicio, misma api-key — nunca ES directo
      endpoint_resultados: "[FALTA: ruta de consulta de resultados procesados por conversación]"
      cursor_param: "[FALTA: offset/since para lectura incremental]"
      mapeo:                                     # JSONPath sobre la respuesta del API
        insight_id:      "[FALTA]"               # se filtra por los ids resueltos en el plano 1
        insight_valor:   "[FALTA]"
        span_inicio_s:   "$.segments[*].start"   # tipado en el spec (Segment)
        span_fin_s:      "$.segments[*].end"
        texto_extraido:  "$.segments[*].transcription"
        audio_ref:       "[FALTA: ruta S3 en el documento]"
        conversacion_id: "[FALTA]"
        territorio_hint: "[FALTA: pcode o folio si la llamada lo trae]"
```

**Pipeline del adaptador** (job del scheduler, mismo patrón que el resto del core):

```
al arrancar: resolver insight_ids vía GET /db/insights (plano 1, cache local)
poll al API de resultados (lectura incremental) → filtrar por insight_id de Agradecimiento
  → resolver audio en S3 (lectura cross-cuenta o URL prefirmada [FALTA definir acceso])
  → COPIAR a bucket propio (nunca hot-link al bucket de Lili: desacople + retención propia)
  → recortar span (ffmpeg -ss inicio -to fin) → transcodificar a MP3/AAC
    (OGG/Opus no reproduce confiable en Safari/iOS — transcodificar SIEMPRE, guardar original)
  → asociar territorio: por folio citado en la llamada > por pcode del evento vinculado > [FALTA]
  → verificar consentimiento
  → GATE AUTOMÁTICO: insight de contenido inapropiado de Lili Analyze (configurable)
      pasa el gate  → según modo: publica directo (auto) o cola manual (manual/híbrido)
      no pasa       → rechazado automático, queda en log para auditoría
  → publicado → encender marcador en mapa + notificar al despachador reconciliado
```

**Moderación configurable (decisión):** la moderación primaria es **automática**, apoyada en la capacidad de filtrado de contenido que Lili Analyze ya tiene — un insight configurable determina qué pasa y qué no. La cola manual existe como modo opcional, no como cuello de botella obligatorio:

```yaml
moderacion:
  modo: auto | manual | hibrido
  gate:
    insight_nombre: "[FALTA: nombre real del insight de contenido inapropiado]"
    tipo: booleano | score
    umbral: 0.8              # solo si tipo=score
  hibrido:                   # solo si modo=hibrido
    auto_publica_si_score_menor_a: 0.2
    cola_manual_entre: [0.2, 0.8]
```

En modo `auto`, todo lo que tiene consentimiento y pasa el gate se publica sin intervención humana; en `hibrido`, los casos ambiguos del rango medio van a revisión manual y el resto fluye solo. Cambiar de modo = cambiar configuración.

### 5.3 Modelo de datos

```sql
audio_gracias
  id              uuid PK
  source          whatsapp | lili_analyze
  external_ref    text          -- media_id (WhatsApp) o conversacion_id (Analyze)
  territorio_pcode text         -- SIEMPRE agregado; nunca pin
  event_folio     text opcional -- reconciliación con RECEIPT/DISPATCH
  span_inicio_s   float opcional
  span_fin_s      float opcional
  duracion_s      float
  url_original    text          -- bucket propio, privado
  url_publica     text          -- MP3 transcodificado, solo si aprobado
  consentimiento  bool NOT NULL
  estado          pendiente | auto_aprobado | aprobado | rechazado
  gate_score      float opcional -- valor del insight de contenido inapropiado
  texto_extraido  text opcional  -- valor texto del insight Agradecimiento (Analyze)
  sentimiento     text opcional  -- insight SentimientoAgradecimiento
  categorias      text[] opcional-- insight CategoriaAyudaMencionada
  reproducciones  int default 0  -- rotación del aleatorio ponderado
  transcript      text opcional  -- pipeline STT; NO se publica (decisión sección 3)
  created_at      timestamptz
```

### 5.5 Voces en los canales: escuchar y dar gracias a demanda

Las voces dejan de ser solo una capa de la web: se vuelven **dos opciones del menú principal en ambos canales** (WhatsApp y telefónico), disponibles a demanda.

**Menú principal actualizado (ambos canales):**

```
[1] Reportar una necesidad
[2] Confirmar que llegó ayuda
[3] Declarar un despacho
[4] Escuchar un agradecimiento      ← nuevo
[5] Dar las gracias                 ← nuevo (antes solo al cierre de recepción)
```

**Flujo `radar_dar_gracias` (a demanda):** ya no requiere venir de una confirmación de recepción. El agente pide la ubicación (pin en WhatsApp / nombre en voz, reutilizando `resolver_ubicacion`), ofrece citar folio si lo tiene, recibe la nota de voz (WhatsApp) o toma el gracias del propio flujo de llamada (Analyze extrae el span), pregunta el **consentimiento de publicación**, y el audio entra al mismo pipeline (gate → banco). Un solo pipeline para las tres puertas de entrada: cierre de recepción, a demanda por WhatsApp, a demanda por llamada.

**Flujo `radar_escuchar_gracias`:**

```
@procedure radar_escuchar_gracias
  @ask   filtro   "¿Querés escuchar un gracias de algún lugar en particular,
                   o te pongo uno cualquiera?"  → [cualquiera | lugar | tema/sentimiento]
  @if    lugar → @tool_call resolver_ubicacion (mismo gazetteer, misma desambiguación)
  @tool_call buscar_gracias {pcode?, sentimiento?, categoria?, texto?, aleatorio}
  @if    sin resultados → ofrecer aleatorio como fallback
  → WhatsApp: enviar clip OGG/Opus (se renderiza como nota de voz)
  → Telefonía: reproducir el clip en la llamada (capacidad asumida; ver configuración)
  @say   "Este gracias llegó desde {territorio}, {fecha_rel}. ¿Otro?"
```

**Nueva tool en el core:**

```
POST /tools/buscar_gracias
  in:  { pcode?, sentimiento?, categorias?[], texto_libre?, aleatorio: bool }
  out: { clip_url_ogg, clip_url_mp3, territorio_nombre, pcode, duracion_s, fecha }
```

Reglas de selección: solo `estado=aprobado|auto_aprobado` con consentimiento (el mismo universo que la web pública — esta función no expone nada nuevo); aleatorio ponderado que rota el catálogo (penaliza lo recién reproducido, favorece voces poco escuchadas); cada reproducción se registra (rotación + métrica de uso).

**Búsqueda: los insights de Analyze SON la capa semántica.** No se arranca con embeddings: la extracción semántica ya la hizo Analyze al procesar el transcript — la consulta conversacional del usuario ("algo de Chocó que hable del agua", "ponme uno alegre") la normaliza el **agente** (que para eso está) a filtros estructurados contra el banco. Tres niveles, en orden de pertinencia:

1. **Filtros por insights estructurados** (primario): pcode, sentimiento, categoría mencionada — exacto, barato, explicable.
2. **Léxica** (secundario): full-text search en español + trigram sobre `transcript`/`texto_extraido`, en el mismo Postgres — para "que mencione a los niños de la escuela".
3. **Semántica por embeddings** (opcional, configurable, fase posterior): pgvector sobre transcripts solo si el catálogo crece lo suficiente para que 1+2 se queden cortos. No es MVP.

**Insights clave a definir en el use case del Radar (vía `POST /db/create/insight`):**

| Insight | Tipo | Para qué |
|---|---|---|
| `Agradecimiento` | span + texto | Detectar y recortar el gracias (existente) |
| `ConsentimientoPublicacion` | booleano | Autorización explícita de publicación (existente) |
| `ContenidoInapropiado` | score | Gate de moderación (existente) |
| `SentimientoAgradecimiento` | enum (alivio, esperanza, alegría, gratitud serena) | Filtro "ponme uno alegre" |
| `CategoriaAyudaMencionada` | enum[] (agua, alimentos, medicamentos, aseo, techo) | Filtro por tipo de ayuda — cruza con el enum del sistema |
| `LugarMencionado` | texto | Hint de territorio para el gazetteer cuando no hay pin ni folio |
| `MencionaNombresPropios` | booleano | Señal de privacidad para el gate (nombre propio → cola manual aunque pase el score) |

**Configuración por canal (la telefonía puede no soportar reproducción):**

```yaml
voces:
  dar_gracias_a_demanda: true
  escuchar:
    whatsapp: true
    telefonia: true        # capacidad ASUMIDA: la plataforma reproduce un audio
                           # que le devolvemos por URL. Si no la soporta: false,
                           # y la opción [4] simplemente no aparece en el menú de voz.
  busqueda:
    lexica: true
    embeddings: false      # pgvector, fase posterior
```

La degradación es la misma filosofía de toda la épica: la opción existe donde la capacidad existe; apagarla es configuración, no deploy.

### 5.6 El gracias como parte del gancho de U2

Cuando un gracias aprobado reconcilia con un despacho, **el despachador lo recibe** junto al comprobante: evidencia emocional para su informe al donante, que ningún acta en Excel les da. En fase 2, aparece también en la página de su acopio.

---

## 6. Componentes nuevos en el Radar Core (extiende v2.1)

| # | Componente | Responsabilidad |
|---|---|---|
| 9 | **Banco de voces** | Adaptador del API de Analyze (mapeo configurable) + copia/recorte/transcodificación + gate/moderación + tabla `audio_gracias` + publicación + **tool `buscar_gracias`** (filtros por insights, FTS léxica, aleatorio ponderado) |
| 10 | **Importador de feeds de aliados** | Poller de `acopios.json` (o adapter a su API), normalización a tabla `acopios`, detección de datos viejos → degradación a fase 0 |
| 11 | **Generador de vista ciudadana** | Template Jinja2 `vista_ciudadana.html.j2` según `especificacion-front-radar-ciudadano.md`: construye `vista-ciudadana.json` desde el log (selección de historia + voces autorizadas), aplica plantillas P/M **server-side**, inyecta el JSON inline para mapa/interacciones, y escribe al directorio estático. Incluye panel Cómo ayudar en sus tres modos y páginas `/acopio/{id}` en fase 2. Verificación previa a publicar: protocolo de spec §9 (offline total + hit-testing real) |

Nada dinámico nuevo de cara al público. El único componente con estado nuevo es la cola de moderación (una tabla + una vista interna mínima o incluso revisión por WhatsApp al moderador `[FALTA decidir]`).

---

## 7. Criterios de aceptación

- [ ] La vista narrativa cumple TODOS los criterios de `especificacion-front-radar-ciudadano.md` §10, empezando por la auditoría de strings (nada visible fuera de datos + P1–P8 + M0–M7).
- [ ] Con **cero** configuración de aliados y **cero** audios: la vista ciudadana renderiza completa (contadores, mapa, historias, "donde falta", panel modo referidos). Ninguna sección rota o vacía sin mensaje.
- [ ] Setear `feed_acopios_url` → el panel pasa a contextual sin deploy. Tumbar el feed → degrada a referidos solo, sin intervención.
- [ ] Vincular un acopio en `orgs` → su página `/acopio/{id}` aparece en el siguiente export.
- [ ] Insight `Agradecimiento` retornado por el API con consentimiento → audio recortado, transcodificado → en modo `auto`, si pasa el gate de contenido se publica **sin intervención humana**, reproducible en Safari/iOS y con marcador encendido; si no pasa, rechazado automático con registro.
- [ ] En modo `hibrido`: los casos del rango medio del score van a cola manual; los extremos fluyen solos.
- [ ] Insight sin consentimiento → jamás aparece en superficie pública; disponible solo en el comprobante privado del despachador.
- [ ] El gracias por voz funciona en ambos canales sin código distinto: nota de voz de WhatsApp y llamada telefónica (la llamada ES audio — Analyze extrae el span del agradecimiento del propio flujo de voz).
- [ ] Cambiar el mapeo de campos de la respuesta del API → cero cambios de código. El Radar no tiene cliente de Elasticsearch ni credenciales de ES en ninguna parte, y **nunca invoca el análisis**: es consumidor de solo lectura de insights ya procesados por la operación Vozy.
- [ ] Todo enlace saliente a aliados lleva UTM.
- [ ] Opciones [4] Escuchar un agradecimiento y [5] Dar las gracias disponibles a demanda en el menú principal de ambos canales; con `voces.escuchar.telefonia=false`, la [4] desaparece del menú de voz sin tocar código.
- [ ] `buscar_gracias` resuelve "uno cualquiera", "de {lugar}" (vía gazetteer) y "que hable de {categoría}/{sentimiento}"; solo sirve audios aprobados con consentimiento; el aleatorio rota el catálogo.
- [ ] En WhatsApp el clip llega como nota de voz (OGG/Opus); en telefonía se reproduce en la llamada.

## 8. Riesgos específicos de esta épica

| Riesgo | Mitigación |
|---|---|
| Voz = dato biométrico identificable de líderes en zona de conflicto (R6 amplificado) | Consentimiento explícito como regla dura + agregación a vereda + sin nombres + moderación previa + transcript no público |
| Audio con nombres propios, quejas o denuncias publicado | Cola de moderación obligatoria antes de publicar (manual en MVP) |
| Dependencia del feed de Ayudas Pereira | Cache local + umbral de frescura + degradación automática a fase 0 |
| Códec OGG/Opus en Safari/iOS | Transcodificación a MP3/AAC en el pipeline, siempre |
| La vista ciudadana como imán de tráfico | Ya resuelto por diseño: 100% estático tras Cloudflare |
| "Historias" percibidas como propaganda | Plantillas solo sobre eventos reconciliados reales; la desatención visible en la misma página |

## 9. Preguntas abiertas

- [ ] `[FALTA]` Endpoint y forma exacta de **consulta de resultados procesados** en el API (por conversación/customer, lectura incremental): dónde viven `insight_id`/valor, los segments (`start/end/transcription` ya tipados), la referencia al audio y el id de conversación
- [ ] `[FALTA]` Cómo entrega el servicio la referencia al audio: ¿URL prefirmada (ideal — cero credenciales cruzadas) o ruta S3 que requiera rol de lectura?
- [ ] **Propuesta al equipo Analyze:** crear en el use case del Radar los insights `Agradecimiento`, `ConsentimientoPublicacion` y `ContenidoInapropiado` vía `POST /db/create/insight` — el consentimiento y el gate dejan de ser `[FALTA]` y pasan a ser configuración nuestra. Confirmar customer_id/use case y obtener `x-api-key`
- [ ] `[FALTA]` Asociación llamada→territorio cuando no hay folio citado (el insight `LugarMencionado` + gazetteer es el camino propuesto)
- [ ] Confirmar en la plataforma Vozy: reproducción de un audio por URL dentro de la llamada (para [4] en voz) y envío de audio como adjunto en salida proactiva (para el gracias al despachador). Si la primera no existe: `voces.escuchar.telefonia=false`
- [ ] `[FALTA]` Nombre real del insight de contenido inapropiado en Analyze, su tipo (booleano/score) y calibración del umbral
- [ ] Si se activa modo `hibrido`: quién revisa la cola manual y por qué canal (propuesta: aprobación por WhatsApp vía notificador, sin UI nueva)
- [ ] Ayudas Pereira: ¿tienen ya JSON/API interno? (determina adapter vs. contrato propuesto)
- [ ] ¿Compartir historias en redes? (pendiente por riesgo de señalización)
- [ ] Decisión editorial: historia destacada 100% automática (regla de spec §1) vs. curada por humano las primeras semanas
- [ ] ¿Campo `contexto` opcional en eventos, escrito y aprobado por curador humano, para color narrativo legítimo?
- [ ] Publicación con URL real (Cloudflare Pages o Railway) para pruebas sin fricción de archivos — paso previo a jinja-ficar
- [ ] Ritmo del scrolly (56svh entre pasos) y altura del mapa fijo (52svh): validar en dispositivos reales antes de congelar

---

**Changelog**
- v1 (15 ago): consolidación inicial — fases Ayudas Pereira, banco de voces, contrato acopios.json.
- v1.1: moderación automática configurable (gate por insight de Analyze, modos auto/manual/híbrido); insights tipados; gracias por voz nativo en ambos canales.
- v1.2: integración Lili Analyze adaptada al API real (dos planos sobre llm-insights); **solo lectura de insights ya procesados — nunca ES directo, nunca invocar el análisis**; los 3 insights del Radar se crean vía POST /db/create/insight.
- v1.3: opciones [4] Escuchar un agradecimiento y [5] Dar las gracias en el menú de ambos canales; tool `buscar_gracias`; búsqueda por insights (capa semántica) + FTS léxica + pgvector opcional; 7 insights identificados; envío de clips a WhatsApp (OGG=nota de voz) y reproducción en telefonía con desactivación por config.
- v1.4 (esta versión): sección 3 reescrita con la estructura narrativa final (5 actos, scrollytelling); principio "el front no inventa — renderiza"; identidad A/E; stack cerrado (Jinja2 + SVG autocontenido, 0 deps); mapa de artefactos; componente 11 y criterios actualizados; spec de front y prototipo como artefactos hermanos.

*Decisiones de la sección 2 y del stack: tomadas — no re-debatir sin razón contundente nueva.*