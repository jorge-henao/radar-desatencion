# Radar de Desatención — Arquitectura

> **Premisa de esta versión:** toda la capa conversacional —canales (WhatsApp y voz), manejo de la conversación, máquina de estados/flujos, extracción y normalización con LLM, reintentos, sesiones— **ya está cubierta por la plataforma de agentes de Vozy** 
Este documento asume eso como resuelto y se concentra en **qué componentes nuevos hay que construir y cómo se conectan**.
> 

---

## 0. Qué cambia respecto a la v1

| Aspecto | v1 (standalone) | v2 (sobre Vozy) |
| --- | --- | --- |
| Canal WhatsApp | Meta Cloud API directo, webhook propio, **verificación de Meta como ruta crítica** | Provisto por la plataforma; aprovisionamiento del número por los canales que Vozy ya opera |
| Máquina de estados | Plataforma Vozy | **Agentes definidos en plataforma Vozy** |
| Normalización LLM | Función propia contra la API de Anthropic | Capacidad nativa de la plataforma |
| Canal de voz | Fase 2 | **Día uno.** Los mismos agentes/flujos conversacionales  sobre el canal telefónico — el constraint más duro (vereda sin datos, solo señal de voz) queda cubierto de entrada |
| PII (teléfonos) | Zona privada propia con TTL | **Nunca entra al Radar.** Se queda en la plataforma; el core solo ve referencias opacas |
| Qué hay que construir | Todo | **Solo el Radar Core: un servicio de registro** (log de eventos + geo + reconciliación + export) y tres agentes en Vozy |

**El resultado neto:** el Radar deja de ser "un bot con base de datos" y se convierte en lo que
siempre fue conceptualmente — **un registro de eventos con salida pública**, al que la plataforma
conversacional le habla por tools.

---

## 1. Vista general

```
┌──────────────────────────────────────────────┐
│         PLATAFORMA VOZY (existente)          │
│                                              │
│  Canales:  WhatsApp ─┐                       │
│            Voz/SIP ──┤                       │
│                      ▼                       │
│  Maquina de estados / Flowise: sesiones, estado,         │
│  extracción LLM, reintentos                  │
│                      │                       │
│  3 agentes (Plataforma Vozy):                │
│   · radar-recepcion   (flujo RECEIPT)        │
│   · radar-despacho    (flujo DISPATCH)       │
│   · radar-necesidad   (flujo NEED)           │
│                      │                       │
└──────────┬───────────┼───────────────────────┘
           │           │ @tool_call (HTTP, síncrono)
   API de  │           ▼
   salida  │  ┌────────────────────────────────────────┐
 proactiva │  │      RADAR CORE (a construir)          │
 (notify)  │  │      un servicio en Railway            │
           │  │                                        │
           └──┤  Tools API      Jobs (scheduler)       │
              │  · resolver_    · reconciliación       │
              │    ubicacion    · decaimiento/dedup    │
              │  · crear_evento · export estático      │
              │  · consultar_                          │
              │    folio        Generador de actas     │
              │                 (PDF + QR)             │
              │            │                           │
              │  ┌─────────▼─────────────────┐         │
              │  │ PostgreSQL + PostGIS      │         │
              │  │ events (append-only)      │         │
              │  │ geo_divipola · gazetteer  │         │
              │  │ vistas materializadas     │         │
              │  └───────────────────────────┘         │
              └───────────────┬────────────────────────┘
                              │ escribe cada 5 min
                              ▼
              ┌────────────────────────────────────────┐
              │  SALIDA PÚBLICA ESTÁTICA (Cloudflare o Railway appl.up.railway.appp)  │
              │  tabla.html · datos.csv (HXL) · geojson│
              └────────────────────────────────────────┘
```

**Componentes a construir: dos.** El Radar Core (un servicio) y los tres agentes en plataforma Vozy.

---

## 2. División de responsabilidades

### Lo que cubre la plataforma Vozy (asumido, no se construye)

- Canal WhatsApp y canal de voz telefónica, con el mismo agente sobre ambos
- Ciclo de vida de la conversación: sesión, estado, timeouts, reintentos de mensaje
- Comprensión y extracción: "agua y remedios pa la presión" → `["agua","medicamentos"]` contra el enum del flujo, transcripción de voz incluida
- Envío de documentos por WhatsApp (el acta PDF) y mensajes salientes proactivos (comprobantes,
alertas) vía la API de salida de la plataforma
- Custodia del PII: el teléfono del usuario vive en la plataforma y solo ahí

### Lo que hay que construir (el Radar Core)

| # | Componente | Responsabilidad | Por qué no puede vivir en la plataforma |
| --- | --- | --- | --- |
| 1 | **Tools API** | Contrato HTTP que los agentes invocan con `@tool_call` | Es el dominio del Radar: folios, validación de esquema, idempotencia |
| 2 | **Log de eventos** | `events` append-only en Postgres; la fuente de verdad | El registro debe ser neutral, auditable y exportable — independiente de la sesión conversacional |
| 3 | **Servicio geo** | Pin → DIVIPOLA (PostGIS + shapefiles DANE); nombre → territorio (gazetteer, para voz) | Conocimiento de dominio geográfico, no conversacional |
| 4 | **Reconciliación** | Match DISPATCH↔RECEIPT en dos niveles (determinístico por folio / probabilístico marcado) | Corre en batch sobre el log, fuera de cualquier conversación |
| 5 | **Generador de actas** | PDF con folio, QR (`wa.me/<num>?text=DS-0392`), número oficial | Artefacto de dominio; la plataforma solo lo transporta |
| 6 | **Export estático** | tabla.html + CSV/HXL + GeoJSON cada 5 min, detrás de Cloudflare | La salida pública no puede depender de nada conversacional ni tocar la DB en lectura |
| 7 | **Notificador** | Decide *cuándo* avisar (comprobante listo, duplicación, desfase) y llama a la API de salida proactiva de la plataforma con la referencia opaca del destinatario | La lógica de negocio de las alertas es del Radar; el envío es de la plataforma |

---

## 3. El contrato entre las dos partes (la frontera que importa)

### 3.1 Agente → Core: Tools API

Tres endpoints, síncronos, autenticados por token de workspace:

```
POST /tools/resolver_ubicacion
  in:  { lat, lon }                           ← pin de WhatsApp
   o:  { texto: "vereda La Cabaña, Jamundí" } ← canal de voz (sin GPS)
  out: { pcode, nivel: municipio|centro_poblado,
         nombre_oficial, confianza, candidatos[] }

POST /tools/crear_evento
  in:  { type: need|dispatch|receipt,
         payload: {...},                      ← ya normalizado por el agente
         reporter_ref,                        ← ID opaco de la plataforma. NUNCA el teléfono.
         idempotency_key }                    ← ID de conversación+paso, para reintentos
  out: { folio, warnings[],                   ← ej. duplicación detectada
         acta_url? }                          ← solo para dispatch; el agente la envía como documento

GET  /tools/consultar_folio?folio=DS-0392
  out: { existe, type, estado, resumen }      ← para validar el folio citado en una recepción
```

Reglas del contrato:

- **Idempotencia en el core, no en el agente:** la plataforma puede reintentar un `@tool_call`;
`idempotency_key` (conversación + paso) garantiza un solo evento.
- **El core valida contra esquema y rechaza con error estructurado**; el agente traduce el rechazo
a una repregunta. La validación de dominio no se delega al LLM.
- **`reporter_ref` es la única identidad que cruza la frontera.** El core la hashea y la usa para
rate limiting y detección de patrones coordinados; no puede resolverla de vuelta a un teléfono.

### 3.2 Core → Plataforma: salida proactiva

```
POST {plataforma}/notify
  { reporter_ref | org_ref,
    plantilla: comprobante_listo | alerta_duplicacion | alerta_desfase,
    variables: {...},
    adjunto_url? }                            ← comprobante PDF
```

El core nunca envía mensajes directamente: decide el *cuándo* y el *qué*; la plataforma resuelve
el *a quién* (ref → teléfono) y el *cómo* (canal, plantilla aprobada, ventana de 24 h vs.
template de Meta).

### 3.3 Los tres agentes  Vozy

Cada flujo es un procedure corto de scope `workspace`. A modo de ilustración del primero:

```
@procedure radar_recepcion
  @ask   folio_citado?     "¿Tenés el número del acta?"        → opcional
  @tool_call consultar_folio                                   → si existe, precarga destino
  @ask   categorias        enum[agua|alimentos|medicamentos|aseo|techo|otro]
  @ask   hogares           entero aproximado
  @ask   ubicacion         pin (WhatsApp) | nombre de lugar (voz)
  @tool_call resolver_ubicacion
  @if    confianza < umbral → @ask confirmar entre candidatos
  @tool_call crear_evento  type=receipt
  @say   "Registrado. Folio {folio}. Gracias — esto es lo que
          permite saber qué zonas siguen sin recibir."
```

Reglas duras que van en el agente (por diseño del flujo, no por prompt): jamás pedir cédula ni
datos bancarios; el flujo de necesidad abre con el disclaimer de expectativa hardcodeado
("esto NO garantiza que llegue una entrega").

---

## 4. Datos (sin cambios de fondo respecto a v1, con una simplificación)

```sql
events          -- append-only. folio único, type, payload jsonb validado,
                -- pin geography (zona privada), pcode, reporter_hash, created_at
geo_divipola    -- polígonos DANE (municipios + centros poblados)
gazetteer       -- NUEVO: nombres de lugar → pcode, con alias y fuzzy match.
                -- Alimentado por: centros poblados DANE + catálogo curado de
                -- veredas por municipio priorizado. Es lo que hace posible voz.
mv_desatencion  -- métrica por pcode (regla: sin eventos = alerta_maxima, no NULL)
mv_reconciliacion
```

**Simplificación ganada:** desaparecen `conversations` y `wa_messages` de la v1 — la sesión y la
deduplicación de mensajes entrantes son problema de la plataforma. El core solo deduplica por
`idempotency_key`. El teléfono en claro **no existe en ningún lado del Radar**.

La zona pública sigue igual que en v1: captura con pin exacto, publicación agregada a pcode, sin
excepciones. Las correcciones siguen siendo eventos nuevos que referencian el folio corregido;
el log nunca se toca.

---

## 5. El canal de voz: la ganancia y su costo

**La ganancia:** el mismo procedure atiende una llamada a un número fijo. La promotora de salud
que solo tiene señal 2G llama, habla, y el evento entra igual. El constraint que en la v1 era
"fase 2" y en los documentos de investigación era el hecho dominante del territorio, queda
cubierto el día uno con cero infraestructura adicional.

**El costo que hay que pagar en el core:** en voz **no hay pin GPS**. La ubicación llega como
nombre hablado ("la vereda La Cabaña, por Jamundí"), transcrito. Por eso `resolver_ubicacion`
tiene el modo texto contra el `gazetteer`, con score de confianza y desambiguación conversacional
cuando hay candidatos múltiples ("¿La Cabaña de Jamundí o la de Riofrío?"). El gazetteer es
trabajo de datos, no de código: centros poblados DANE de base + catálogo de veredas curado a mano
**solo para los municipios priorizados** (los ~85 de la UNGRD son el techo; los 10–15 más
desatendidos son el arranque realista).

---

## 6. Orden de construcción actualizado

| Día | Entregable |
| --- | --- |
| 0 | Aprovisionar número (WhatsApp + voz) por los canales existentes de Vozy · cargar shapefiles DANE en PostGIS · workspace y tokens |
| 1 | Radar Core: `crear_evento` + `resolver_ubicacion` (modo pin) + log de eventos + folios |
| 2 | Agentes `radar_recepcion` y `radar_despacho` en plataforma Vozy · generador de actas PDF+QR |
| 3 | Reconciliación + notificador (comprobante por salida proactiva) + export estático detrás de Cloudflare |
| 4 | Gazetteer v1 (centros poblados + 10 municipios curados) · `resolver_ubicacion` modo texto · habilitar canal de voz |
| 5 | Agente `radar_necesidad` · prueba de punta a punta con un despachador real (ABACO / Fundación Éxito) |

La ruta crítica de la v1 (verificación de Meta Business) desaparece o se acorta drásticamente:
el aprovisionamiento pasa por relaciones que Vozy ya tiene.

---

## 7. Decisiones y preguntas abiertas específicas de esta versión

- [ ]  **Gobernanza y marca:** ¿el Radar opera como iniciativa Vozy, como proyecto neutral que
*usa* infraestructura Vozy, o bajo un tercero (universidad, Federación de Municipios)? Afecta la
adopción institucional (R7) y la percepción de neutralidad del registro — el deslinde fue una de las razones documentadas del éxito del FOREC.
- [ ]  **Aislamiento:** ¿Quién paga las conversaciones y la telefonía?
- [ ]  **Capacidades a confirmar en la plataforma** (asumidas arriba): envío de documentos PDF por
WhatsApp; API de salida proactiva invocable por un servicio externo con `reporter_ref`; canal de
voz y WhatsApp compartiendo el mismo procedure sin bifurcar la definición.
- [ ]  **Continuidad:** si el Radar debe transferirse a un hogar institucional (SNIGRD), ¿qué se
transfiere? Respuesta de diseño: el log de eventos y el export son autónomos y portables; los
agentes son la única pieza acoplada a Vozy
- [ ]  Heredadas de v1: formato de ingesta del SNIGRD · factor de accesibilidad manual vs. Invias ·
¿el comprobante necesita hash verificable o basta folio + página pública?

---

*Documento generado el 14 de agosto de 2026. v2 — capa conversacional delegada a la plataforma Vozy; por construir: el Radar Core (un servicio) + tres agentes en plataforma Vozy.*