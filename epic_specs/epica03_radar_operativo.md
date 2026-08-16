# Épica: Radar Operativo — vista de despacho con curaduría automatizada ("Vigía de Medios")

> **Estado:** especificación consolidada para implementación. Corte: 15 de agosto de 2026.
> **Hermana de:** `epica-radar-ciudadano.md` (v1.4) — comparte identidad visual, principio data-driven y componentes del Radar Core. Este documento copia lo necesario para ser autosuficiente para un agente implementador.
> **Depende de:** `radar-desatencion-arquitectura-v2-vozy.md` (v2.1): gazetteer, log de eventos, export estático, scheduler.
> **Convención:** puntos sin definir marcados `[FALTA]`.

---

## 1. El problema: el arranque en frío mata la credibilidad

La vista operativa (la tabla de priorización para quien despacha — U2 acopios/ONGs, U3 CMGRD) hoy tiene un defecto letal: **en el estado inicial, sin reportes ciudadanos, se ve vacía o ruidosa — descuidada, no creíble**. Y la credibilidad de esa vista es la palanca de adopción de TODO el sistema:

```
despachadores usan la vista → declaran despachos con folio → el folio viaja con el camión
  → la comunidad confirma recepción → nace el gracias → la vista ciudadana tiene qué contar
```

Sin despachadores no hay folios; sin folios no hay confirmaciones; sin confirmaciones ni el radar de desatención ni el radar ciudadano funcionan. **Esta pieza es el primer dominó.** Por eso no puede esperar a que la ciudadanía adopte: debe ser útil desde el día cero, con o sin reportes.

## 2. La solución: curaduría automatizada de medios + transición gradual a reportes

Un agente automatizado — nombre de trabajo **"Vigía de Medios"** (alternativas a decidir: *Oído Público*, *Barrido*) — escanea periódicamente fuentes confiables (medios, ONGs, boletines oficiales, sitios de coordinación humanitaria) y extrae **señales estructuradas** de dónde se reporta necesidad de ayuda. Esas señales alimentan la vista operativa desde el día cero con información curada y con procedencia visible, y a medida que la adopción crece, los reportes ciudadanos de primera mano se suman **sin reemplazar la curaduría** — ambas capas conviven, siempre distinguibles.

### Decisiones tomadas (no re-debatir)

1. **Tres modos de la vista, por configuración** (`vista_operativa.modo`): `curado` (solo señales del Vigía — el modo de lanzamiento), `mixto` (señales + reportes ciudadanos, capas separadas — el estado objetivo), `reportes` (solo primera mano — futuro lejano, si algún día los medios sobran). Cambiar de modo = configuración, no deploy.
2. **Las señales de medios NUNCA entran al log de eventos.** El log es exclusivamente hechos de primera mano (NEED/DISPATCH/RECEIPT reportados por actores identificables con folio). Las señales viven en su propia tabla (`senales_medios`) y se unen con el log solo en la capa de presentación, con procedencia explícita. *(Refina el "sembrado con eventos externos de baja confianza" de arquitectura v2.1 §changelog: el sembrado se implementa como señales, no como eventos — protege la pureza epistemológica del log append-only.)*
3. **Toda señal lleva cita textual corta + URL + fuente + fecha.** El agente resume y estructura, pero la evidencia original siempre es verificable con un tap. Señal sin URL verificable = señal descartada.
4. **Toda localidad mencionada debe conciliarse con el gazetteer** (pcode) antes de aparecer en la vista. Sin match → cola de incorporación (sección 5), nunca un pin inventado.
5. **El agente es un grafo LangGraph escrito directamente en el Radar Core (Python)** — sin ninguna dependencia de Nexus v3, Factory ni de la plataforma Vozy: código LangGraph puro dentro del mismo servicio FastAPI/Railway del Radar, corriendo como job del scheduler con cadencia configurable. Sus fuentes se gobiernan desde **un archivo de configuración simple** (`vigia.yaml`) — no variables de entorno, no base de datos de administración.
6. **La vista operativa adopta la identidad del Radar Ciudadano** con el modo oscuro (E · Tinta profunda) como default — es una vista de sala de operaciones — y claro (A · Registro civil) disponible por `prefers-color-scheme`. Tokens copiados en la sección 7.
7. **El Vigía no reemplaza la tesis anti-sesgo (R1).** Los medios cubren lo visible; el corazón del Radar es medir lo invisible. Territorio sin eventos NI señales sigue siendo **alerta máxima** — y la UI lo declara. El Vigía agrega información, jamás degrada la alerta por ausencia.

## 3. El Vigía de Medios — agente y pipeline

### 3.1 Arquitectura

```
scheduler (cadencia configurable, ej. cada 24h o cada 6h en pico)
  └─ job vigia_run
       └─ agente LangGraph (grafo puro en el core — sin Nexus v3)
            ├─ tool: leer_fuentes        (fetch de cada fuente activa de vigia.yaml)
            ├─ tool: buscar_web          (búsquedas dirigidas: "{depto} ayuda humanitaria", 
            │                             términos configurables)
            ├─ tool: extraer_senales     (LLM: extracción estructurada por fuente)
            ├─ tool: resolver_ubicacion  (el MISMO gazetteer del core — reuso, no duplicación)
            └─ tool: registrar_senales   (upsert con dedupe + conciliación)
```

Nodos del grafo: `planificar` (qué fuentes tocan hoy según cadencia por fuente) → `recolectar` (fetch paralelo) → `extraer` (estructuración con LLM, por documento) → `conciliar` (gazetteer + dedupe) → `persistir` → `reportar` (resumen del run al log de auditoría del Vigía).

### 3.2 Extracción estructurada (contrato de la señal)

Por cada mención de necesidad territorial, el LLM extrae:

```json
{
  "localidad_texto": "corregimiento Santa Cecilia, Pueblo Rico",
  "categorias": ["agua", "medicamentos"],
  "urgencia_texto": "llevan dos semanas sin agua potable",
  "cita": "«…las 300 familias de Santa Cecilia completan 14 días sin agua potable…»",
  "url": "https://…",
  "fuente_id": "eltiempo",
  "fecha_publicacion": "2026-08-14",
  "hogares_estimados": 300
}
```

Reglas de extracción: `categorias` mapea al **enum compartido del sistema** (`agua|alimentos|medicamentos|aseo|techo|otro` — el mismo de eventos y acopios); `cita` máx. ~40 palabras, textual; si el texto no menciona localidad resoluble, no hay señal; el LLM **nunca** infiere cifras no presentes en el texto.

### 3.3 Persistencia y ciclo de vida

```sql
senales_medios
  id            uuid PK
  pcode         text NULL         -- resuelto por gazetteer; NULL = en cola de incorporación
  localidad_texto text
  categorias    text[]
  cita          text
  url           text NOT NULL
  fuente_id     text              -- FK lógica a vigia.yaml
  confianza     float             -- peso de la fuente (de vigia.yaml)
  fecha_pub     date
  detectada_at  timestamptz
  refuerzos     int default 1     -- señales duplicadas de otras fuentes suman acá
  estado        activa | caducada | descartada | convertida
  descartada_por text NULL        -- auditoría: quién y cuándo descartó
```

- **Dedupe:** misma (pcode, categorías∩, ventana 7 días) → no se duplica: `refuerzos+1` y se anexa la fuente. "Según 3 fuentes" vale más que "según 1".
- **Decaimiento:** señal sin refuerzo en `vigia.caducidad_dias` (default 10) pasa a `caducada` y sale de la vista. Los medios se mueven; la vista no puede quedar anclada a una noticia vieja.
- **Conversión:** si llega un NEED de primera mano del mismo pcode, la señal se marca `convertida` y la vista muestra el reporte ciudadano como capa principal (la señal queda como contexto histórico).
- **Descarte humano:** desde la vista, un operador puede descartar una señal (falso positivo del LLM) — queda auditado.

### 3.4 `vigia.yaml` — el artefacto de configuración

```yaml
vigia:
  activo: true
  cadencia_horas: 24              # el job corre cada N horas
  caducidad_dias: 10
  modelo: "[FALTA: modelo LLM y proveedor — decisión de costo]"
  terminos_busqueda:              # para la tool buscar_web, además de las fuentes fijas
    - "ayuda humanitaria {departamento}"
    - "damnificados sin ayuda"
  fuentes:
    - id: eltiempo
      url: https://www.eltiempo.com/colombia
      tipo: medio
      confianza: 0.8
      activa: true
    - id: ungrd_boletines
      url: "[FALTA: URL de boletines UNGRD]"
      tipo: oficial
      confianza: 0.95
      activa: true
    - id: cuidar_colombia
      url: https://cuidarcolombia.vercel.app
      tipo: agregador_verificado
      confianza: 0.85
      activa: true
    # curaduría creciente: agregar fuente = agregar bloque, sin código
vista_operativa:
  modo: curado                    # curado | mixto | reportes
```

## 4. Conciliación de localidades (requisito duro)

Toda `localidad_texto` pasa por `resolver_ubicacion` (gazetteer del core: DIVIPOLA + fuzzy + alias acumulados):

- **Match con confianza alta** → señal con pcode, visible en la vista.
- **Match ambiguo** → candidatos guardados; la señal aparece en la vista marcada "ubicación por confirmar" solo en la sección de revisión, no en la tabla principal.
- **Sin match** → entra a la cola **`localidades_por_incorporar`**: el pipeline intenta enriquecer automáticamente (lookup contra DIVIPOLA/COD-AB por municipio inferido del texto — el Excel de COD-AB Colombia en HDX trae nombres alternativos); si el enriquecimiento produce candidato, se propone; la incorporación final al gazetteer la aprueba un humano (nuevo pcode o alias de uno existente). La señal queda retenida hasta resolverse. **Nunca se publica una ubicación no conciliada.**

Efecto colateral valioso: **el Vigía engorda el gazetteer** — cada localidad de medios incorporada mejora también la resolución conversacional de WhatsApp/voz.

## 5. La vista operativa (front)

**Audiencia:** U2 (acopios, ONGs) y U3 (CMGRD). **Objetivo de diseño:** decidir a dónde despachar en menos de un minuto, con evidencia verificable a un tap. Eficiencia primero — el estilo sirve a la velocidad, no compite con ella.

### 5.1 Estructura

| Bloque | Contenido |
|---|---|
| **Barra de estado del Vigía** | `Vigía de Medios · última pasada hace {n}h · {m} fuentes · {k} señales activas` (mono). Transparencia del mecanismo = credibilidad. Si `modo=mixto`: ` · {r} reportes de primera mano` |
| **Tabla de priorización** | Una fila por territorio, orden: alerta máxima primero, luego score descendente. Columnas: territorio (nombre + mun), días sin recepción, ~hogares, necesidades (chips de categoría), **procedencia** (chips: `⚑ medios ×3` / `✉ reporte directo` / ambos), acción (`Declarar despacho` → deep link `wa.me` con texto prellenado del folio flow) |
| **Fila expandida** (tap) | Señales con cita textual + fuente + fecha + link; eventos del log si existen; historial del territorio |
| **Filtros** (client-side) | departamento · categoría · procedencia · solo alerta máxima |
| **Sección de revisión** (colapsada) | señales con ubicación por confirmar + cola de incorporación de localidades + descarte de señales |

### 5.2 Estados de arranque (el corazón de esta épica)

- **Día cero, `modo=curado`:** la tabla abre poblada con señales del Vigía. Nada de vacío: el primer render ya dice "según El Tiempo y 2 fuentes más, Santa Cecilia lleva 14 días sin agua". La barra de estado declara el mecanismo.
- **Cero señales y cero reportes** (peor caso): la tabla muestra los territorios del área afectada con su estado de alerta por ausencia — "sin información: eso ES la alerta" (tesis R1) — más un bloque explicando cómo reportar. Nunca una tabla vacía sin sentido.
- **`modo=mixto`:** los reportes de primera mano se ordenan por encima de señales equivalentes; procedencia siempre visible; territorio con ambos muestra el reporte como principal y las señales como corroboración ("y 3 medios lo confirman").

### 5.3 Procedencia — regla de credibilidad

Nunca se mezclan sin etiqueta. Chips de procedencia con iconografía sobria (sección 7): señal de medios ≠ reporte ciudadano ≠ evento con folio. Un despachador debe poder distinguir en un vistazo qué es rumor estructurado y qué es un hecho reportado por alguien en el territorio.

### 5.4 Principio data-driven (heredado — innegociable)

Aplica íntegro el §0 de `especificacion-front-radar-ciudadano.md`: **el front no inventa — renderiza.** En esta vista además: la "urgencia" se muestra con la **cita textual** de la fuente, nunca con paráfrasis del front; los resúmenes los produce el agente (y quedan en datos), no el template.

## 6. Contrato de datos — `vista-operativa.json`

Generado por el mismo export estático (extensión del componente 11), cada 5 min:

```json
{
  "generado": "2026-08-15T06:00:00-05:00",
  "vigia": { "ultima_pasada": "2026-08-15T04:00:00-05:00", "fuentes_activas": 14, "senales_activas": 23, "modo": "curado" },
  "territorios": [
    {
      "pcode": "66572001", "nombre": "cgto. Santa Cecilia", "mun": "Pueblo Rico, Risaralda",
      "alerta_maxima": false, "dias_sin_recepcion": 14, "hogares_est": 300,
      "necesidades": ["agua","medicamentos"], "score": 87.3,
      "procedencia": { "senales": 3, "reportes": 0 },
      "senales": [
        { "cita": "«…las 300 familias de Santa Cecilia completan 14 días sin agua potable…»",
          "fuente": "El Tiempo", "url": "https://…", "fecha": "2026-08-14", "refuerzos": 3 }
      ],
      "eventos": []
    }
  ],
  "revision": { "ubicacion_por_confirmar": 2, "localidades_por_incorporar": 1 }
}
```

El score usa la métrica existente (días sin recepción × población ÷ accesibilidad); para territorios sin datos de primera mano, las señales elevan la visibilidad pero **no reemplazan** el estado de alerta por ausencia — un territorio con señal de medios y cero eventos se muestra como "señalado por medios, sin confirmación en terreno", que es en sí un llamado a despachar con folio.

## 7. Diseño (referencia: Radar Ciudadano, con lo copiado acá para autosuficiencia)

**Identidad:** modo oscuro default = **E · Tinta profunda** (vista de sala de operaciones, uso intensivo y nocturno); claro = **A · Registro civil**, por `prefers-color-scheme`. Decisión y exploración: `radar-exploracion-diseno.html`. Tokens (copiados de `especificacion-front-radar-ciudadano.md` §2 — si divergen, gana la spec del ciudadano):

```css
:root{ /* A · Registro civil */
  --bg:#F4F6F5; --card:#FFFFFF; --ink:#14231F; --muted:#5C6B66; --line:#D9E0DD;
  --ok:#0F7B54; --ok-mid:#1D9E75; --ok-soft:#E3F3EC;
  --wait:#B4690E; --wait-soft:#FBF1DF; --alerta:#CE3A12;
  --r:8px;
  --f-sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --f-mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){ :root{ /* E · Tinta profunda */
  --bg:#10161A; --card:#161E23; --ink:#E8EDEF; --muted:#93A2A9; --line:#28343B;
  --ok:#2FBF8F; --ok-mid:#2FBF8F; --ok-soft:#122A23;
  --wait:#E8A33D; --wait-soft:#2B2214;
}}
```

**Semántica dura (idéntica al ciudadano):** teal = confirmado/primera mano; ámbar = espera/señal; `--alerta` SOLO para alerta máxima — **esta vista es el único lugar del sistema donde `--alerta` aparece con frecuencia**, y por eso el resto debe ser sobrio: el rojo debe doler, no decorar.

**Tipografía:** mono para todo lo registral (días, scores, folios, barra del Vigía, chips de procedencia); sans para nombres y acciones. Sin serif en esta vista (la serif es la voz humana — acá no hay voz, hay operación).

**Iconografía (sobria, inline SVG, trazo 1.5px, 16px, monocroma heredando color):** set mínimo de 6 — `⚑` señal de medios (banderín/antena) · `✉` reporte directo (mensaje) · `▲` alerta máxima (triángulo, único uso de --alerta) · `⬡` categoría de necesidad (los 6 del enum con glifo simple: gota, pan, cruz, jabón, techo, caja) · `→` despachar (flecha/camión) · `✓` confirmado. Nada de librerías de iconos: 6 SVGs inline definidos una vez como `<symbol>`. Prohibido: emojis, iconos rellenos, más de un ícono por celda.

**Layout:** tabla densa pero respirada — filas 52px, `max-width` sin límite (esta vista es desktop-first para el CMGRD y responsive hacia móvil para el acopio en bodega); en móvil la tabla colapsa a tarjetas apiladas manteniendo el orden de prioridad.

**Stack:** idéntico al ciudadano — export estático Jinja2 + vanilla JS (filtros/orden/expansión client-side sobre el JSON inline), cero dependencias externas, tras Cloudflare. El protocolo de verificación de spec §9 aplica íntegro (offline total + hit-testing real).

## 8. Componentes nuevos en el Radar Core

| # | Componente | Responsabilidad |
|---|---|---|
| 12 | **Vigía de Medios** | Agente LangGraph + job del scheduler + `vigia.yaml` + tabla `senales_medios` + dedupe/decaimiento/conversión + log de auditoría de pasadas |
| 13 | **Cola de incorporación de localidades** | `localidades_por_incorporar` + enriquecimiento DIVIPOLA/COD-AB + aprobación humana → alta en gazetteer |
| 14 | **Vista operativa** | Template Jinja2 `vista_operativa.html.j2` + `vista-operativa.json` en el export + filtros client-side + sección de revisión |

## 9. Criterios de aceptación

- [ ] Con el sistema recién instalado y cero reportes ciudadanos, la vista operativa renderiza poblada y creíble en `modo=curado` tras la primera pasada del Vigía; con cero señales Y cero reportes, muestra el estado de alerta por ausencia con explicación — nunca vacío sin sentido.
- [ ] Toda señal visible tiene cita textual + fuente + URL funcional + fecha; señal sin URL no existe.
- [ ] Ninguna localidad aparece en la tabla principal sin pcode conciliado; las no conciliadas viven solo en la sección de revisión.
- [ ] Agregar/desactivar una fuente o cambiar la cadencia = editar `vigia.yaml`, sin deploy.
- [ ] Cambiar `vista_operativa.modo` reordena las capas sin deploy; la procedencia es visible en los tres modos.
- [ ] NEED de primera mano en un pcode con señal activa → señal `convertida`, reporte como capa principal, señales como corroboración.
- [ ] Señales sin refuerzo caducan a los `caducidad_dias` y salen de la vista.
- [ ] Un operador puede descartar una señal desde la sección de revisión, con auditoría.
- [ ] Territorio sin eventos ni señales conserva alerta máxima (R1) — el Vigía nunca la degrada.
- [ ] La vista pasa el protocolo de verificación (offline total, hit-testing real, auditoría de strings, ambos temas A/E).
- [ ] Las señales de medios no aparecen en el log de eventos ni en los exports de auditoría de primera mano (CSV/HXL) — o aparecen en dataset separado claramente rotulado `[FALTA decidir]`.

## 10. Riesgos específicos

| Riesgo | Mitigación |
|---|---|
| Alucinación del LLM (señal inventada) | Cita textual + URL obligatorias y verificables; lista blanca de fuentes; descarte humano auditado; confianza por fuente |
| Sesgo de medios (cubren lo visible) → el Vigía refuerza el sesgo que el Radar combate | Decisión 7: alerta por ausencia intocable; la UI distingue "señalado por medios" de "confirmado en terreno"; métrica de desatención no consume señales |
| Copyright de medios | Solo citas cortas (~40 palabras) con atribución y link a la fuente — la vista manda tráfico al medio, no lo sustituye |
| Costo LLM del barrido | Cadencia configurable; extracción solo sobre contenido nuevo (hash por URL); modelo económico `[FALTA decidir]` |
| Señal vieja anclada en la vista | Decaimiento automático + refuerzos |
| Localidad mal conciliada → despacho mal dirigido | Umbral de confianza del gazetteer + revisión humana para ambiguos + nunca publicar sin pcode |

## 11. Preguntas abiertas

- [ ] `[FALTA]` Nombre definitivo del agente (propuesto: Vigía de Medios) — decisión de marca junto con gobernanza del Radar
- [ ] `[FALTA]` Modelo LLM y presupuesto del barrido (¿API frontier vs. modelo económico? volumen estimado: decenas de documentos/día)
- [ ] `[FALTA]` Lista inicial de fuentes (semilla propuesta: UNGRD boletines, El Tiempo/El Espectador regionales, Cuidar a Colombia, HOT/ChatMap, boletines OCHA Colombia, Ayudas Pereira) — curar con criterio de confiabilidad antes del primer run
- [ ] ¿Dataset público separado de señales de medios en la pestaña de auditoría? (transparencia vs. confusión con primera mano)
- [ ] Deep link `wa.me` de "Declarar despacho": texto prellenado exacto `[FALTA definir con el procedure de despacho]`

---

**Referencias cruzadas:** `epica-radar-ciudadano.md` v1.4 (identidad, principio data-driven, componentes 9–11, mapa de artefactos) · `especificacion-front-radar-ciudadano.md` (tokens §2, plantillas §4, protocolo de verificación §9, basemap Apéndice A si esta vista suma mapa) · `radar-desatencion-arquitectura-v2-vozy.md` v2.1 (gazetteer, log, scheduler, export, métrica de desatención).

*Decisiones de la sección 2: tomadas — no re-debatir sin razón contundente nueva.*