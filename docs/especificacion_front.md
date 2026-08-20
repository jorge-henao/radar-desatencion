# Especificación Front — Radar Ciudadano, vista narrativa

> **Estado:** especificación de implementación. Corte: 15 de agosto de 2026.
> **Complementa:** `epica-radar-ciudadano.md` (producto) y `radar-desatencion-arquitectura-v2-vozy.md` (sistema). El prototipo de referencia que implementa esta spec es `radar-ciudadano-historia.html`.

---

## 0. Principio rector: el front no inventa — renderiza

Todo texto, número, coordenada, escena de mapa y paso de la historia proviene de **una** de estas tres fuentes, y de ninguna otra:

| Fuente | Qué es | Ejemplos |
|---|---|---|
| **(a) Datos** | Campos del JSON generado por el export desde el log de eventos | fechas, folios, categorías, hogares, pcodes, coordenadas agregadas, días calculados |
| **(b) Plantillas** | Frases con slots, listadas taxativamente en la sección 4. Determinísticas: mismo dato → misma frase | "La comunidad confirmó: llegó, y alcanzó para {hogares} hogares." |
| **(c) Microcopy fijo** | Texto del sistema aprobado en esta spec: labels, leyendas, explicaciones del mecanismo | "confirmado por su comunidad", "El acta viajó con la carga", la leyenda del mapa |

**Prohibido en el front:** inferir personas, roles, motivos o circunstancias no capturadas ("una promotora", "la vía bloqueada", "caminó hasta la señal"); citas atribuidas a nadie; adjetivos de estado emocional del territorio; cualquier cifra no presente en el JSON. Si un dato no existe, la frase que lo necesita **no se renderiza** — nunca se rellena.

**Criterio de verificación:** todo string visible en la página debe poder señalarse en (a), (b) o (c). Un string que no se pueda señalar es un bug.

---

## 1. Contrato de datos — `vista-ciudadana.json`

Generado por el export estático (componente 11) cada 5 minutos. El front lo consume tal cual; en el build estático se inyecta inline.

```json
{
  "generado": "2026-08-15T06:00:00-05:00",
  "contadores": { "confirmadas_semana": 34, "esperando": 12, "total_territorios": 46 },
  "territorios": [
    { "id": "27660001", "nombre": "cgto. San Pedro", "mun": "San José del Palmar, Chocó",
      "lat": 4.986, "lng": -76.234,
      "estado": "llego",            
      "dias": 0,                    
      "reciente": true,             
      "gracias": true,
      "faltante": ["medicamentos"] }
  ],
  "historia": {
    "territorio_id": "27660001",
    "eventos": [
      { "tipo": "need",     "fecha": "2026-08-06", "folio": "NE-0847", "canal": "whatsapp",
        "categorias": ["agua","alimentos"], "hogares": 30 },
      { "tipo": "dispatch", "fecha": "2026-08-14", "folio": "DS-0392",
        "detalle": "80 kits de alimentos y 120 bidones de agua",
        "origen": { "mun": "Pereira", "lat": 4.81, "lng": -75.69, "org_publica": null } },
      { "tipo": "receipt",  "fecha": "2026-08-15", "folio": "RC-1204",
        "hogares": 28, "cruza_con": "DS-0392" }
    ]
  },
  "faltantes_top": [ { "territorio_id": "76364012", "dias": 11 } ],
  "voces": [
    { "territorio_id": "27660001", "fecha_rel": "hoy", "dur": "0:38",
      "mp3": "/voces/rc1204.mp3", "ogg": "/voces/rc1204.ogg", "autorizado": true }
  ]
}
```

Reglas del contrato: coordenadas SIEMPRE agregadas (centroide de vereda/centro poblado — nunca el pin del evento); `voces` solo contiene `autorizado=true` y `estado=aprobado|auto_aprobado` (el filtrado ocurre en el export, el front no filtra privacidad); fechas ISO, el front formatea; `org_publica` solo trae nombre si la org catalogada autorizó aparecer — si es `null`, la plantilla usa "un acopio de {origen.mun}".

**Selección de la historia destacada** (regla del export, determinística): el `RECEIPT` reconciliado más reciente cuyo territorio tuvo la mayor espera resuelta (días entre primer NEED/último RECEIPT anterior y este RECEIPT); empate → más hogares alcanzados. Requiere cadena mínima `dispatch→receipt`; `need` es opcional. **Sin historia elegible** → `historia: null` y el scrolly renderiza solo los pasos S0–S1 (país y esperando), que son data-driven puros.

---

## 2. Tokens de diseño

**Dos temas, un solo sistema:** modo claro = **A · Registro civil** (papel frío institucional); modo oscuro = **E · Tinta profunda** (carbón azulado `#10161A`, decisión tomada tras explorar 5 direcciones — ver `radar-exploracion-diseno.html`). Conmutación automática por `prefers-color-scheme`, sin toggle manual. Ambos temas cubren TODO, incluido el mapa (variables `--map-*`). Un solo set de variables; **ningún color se hardcodea fuera de `:root`** — si un color aparece fuera de estas variables, es un bug.

```css
:root{
  --bg:#F4F6F5;  --card:#FFFFFF;  --ink:#14231F;  --muted:#5C6B66;  --line:#D9E0DD;
  --ok:#0F7B54;  --ok-mid:#1D9E75;  --ok-soft:#E3F3EC;
  --wait:#B4690E;  --wait-soft:#FBF1DF;
  --alerta:#CE3A12;                        /* SOLO alerta máxima; jamás para "esperando" */
  --map-bg:#E9EEEC; --map-fill:#F1F4F2; --map-line:#C6D0CB; --map-city:#7d8a84; --dot-stroke:#fff;
  --r:8px;
  --f-sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --f-mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --f-serif:Georgia,'Times New Roman',serif;
}
@media (prefers-color-scheme: dark){ :root{
  --bg:#10161A; --card:#161E23; --ink:#E8EDEF; --muted:#93A2A9; --line:#28343B;
  --ok:#2FBF8F; --ok-mid:#2FBF8F; --ok-soft:#122A23; --wait:#E8A33D; --wait-soft:#2B2214;
  --map-bg:#0C1216; --map-fill:#131B20; --map-line:#25313A; --map-city:#5c6d76; --dot-stroke:#10161A;
}}
```

**Semántica de color (regla dura):** teal = evento confirmado / canal del sistema; ámbar = espera (nunca rojo — es espera, no catástrofe); `--alerta` reservado exclusivamente a territorios `alerta_maxima` (sin ningún evento). Los tres nunca se intercambian.

**Tipografía (system stack, decisión de peso cero):** sans del sistema para UI y narración de pasos; **mono** para todo lo registral (folios, fechas, contadores, leyenda, verificación del número — el mono ES la identidad del registro); **serif** exclusivamente para la voz humana (respuesta del hero, esencia de voces). Tres registros tipográficos = tres voces: sistema, registro, humano. Escala: h1 `clamp(32px,8.5vw,46px)/800`; h2 `clamp(22px,5.5vw,28px)/800`; cuerpo 16px/1.55; contador 34px mono 600; meta 11px mono; mínimo absoluto 10.5px.

**Espaciado y forma:** contenedor `max-width:640px`, padding lateral 20px; radios `--r:8px` (10–12px tarjetas grandes); bordes 1px `--line`; acento lateral de 3px (`--ok-mid` en historias/esencia) siempre con `border-radius:0` en ese lado. Separación entre pasos del scrolly: `56svh` (ritmo contemplativo — es EL parámetro de tempo de la narración).

---

## 3. Estructura narrativa (el scroll es la historia)

Cinco actos, de lo esencial a lo personal. El orden es diseño, no accidente:

| Acto | Contenido | Fuente |
|---|---|---|
| **1 · La respuesta** (100svh, sin scroll) | verificación del número (mono) → pregunta h1 → respuesta en serif (plantilla P1 por umbral) → 2 contadores → hint de scroll | datos + P1 |
| **2 · El país** (scrolly S0–S1) | mapa fijo; paso "cada punto es una comunidad" con conteos reales; paso "los que esperan" con conteo real | datos + microcopy M1–M2 |
| **3 · Una historia** (scrolly S2..Sn) | presentación del territorio + un paso por evento del log, en orden cronológico, con escena de mapa derivada de sus coordenadas | datos + P2–P5 |
| **4 · Voces de agradecimiento** | reproductores (si `voces.length>0`) o esencia data-driven (si no) | datos + M3/P6 |
| **5 · Cierre** | "la próxima historia puede empezar con vos" + `faltantes_top` + CTA + footer de auditoría | datos + M4 |

**El hero debe bastar solo:** quien no scrollea se va con pregunta, respuesta, dos números y el número oficial verificable.

---

## 4. Plantillas y microcopy (lista taxativa — nada fuera de esto)

### Plantillas (slots = datos)

- **P1 · Respuesta del hero** (por proporción `confirmadas/(confirmadas+esperando)`):
  - ≥0.66: `**Sí — a la mayoría de los territorios.** Y sabemos exactamente dónde no, porque cada entrega la confirma la propia comunidad.`
  - 0.33–0.66: `**A muchos territorios sí — a otros todavía no.** Y sabemos exactamente cuáles, porque cada entrega la confirma la propia comunidad.`
  - <0.33: `**Todavía a muy pocos.** Pero sabemos exactamente dónde falta, porque cada entrega la confirma la propia comunidad.`
- **P2 · Presentación de historia:** `Esta es la historia de **{territorio.nombre}**, en {territorio.mun}.` (+ si hay NEED: ` El primer reporte llegó el {fecha_need}.`)
- **P3 · Paso NEED:** k=`Día 1` · `Alguien de la comunidad reportó por {canal}: **falta {categorias} para unos {hogares} hogares.**` · fecha=`{fecha} · folio {folio}`
- **P4 · Paso DISPATCH:** k=`Día {n}` · `{org_publica ?? "Un acopio de {origen.mun}"} despachó **{detalle}**. El acta viajó con la carga.` · fecha=`{fecha} · folio {folio}`
- **P5 · Paso RECEIPT:** k=`Día {n}` · `La comunidad confirmó con el acta en la mano: **llegó, y alcanzó para {hogares} hogares.**{dias_espera>0 ? " {dias_espera} días después del primer reporte." : ""}` · fecha=`{fecha} · folio {folio}{cruza_con ? " · cruzado con {cruza_con}" : ""}` · badge=`✓ confirmado por su comunidad`
- **P6 · Esencia (sin audios):** `Mientras llega la primera voz, lo dice el registro: **{confirmadas_semana} confirmaciones esta semana** — cada una, alguien que ya no está esperando.`
- **P7 · Fila faltante:** `{territorio.nombre} — {territorio.mun}` / `{dias} días`
- **P8 · Chip del punto (modo explorar):** `{nombre}` / `{mun} · {estado==="llego" ? "llegó {fecha_rel}" : "{dias} días sin recepción"}{gracias ? " · gracias grabado" : ""}`

`Día {n}` = diferencia en días respecto al primer evento de la historia + 1, calculada — nunca escrita a mano.

### Microcopy fijo (c)

- M0 verificación: `RADAR DE DESATENCIÓN · WhatsApp oficial {numero} — si no es este, es falso`
- M1 país: `Cada punto es una comunidad. **Verde:** la ayuda llegó y su propia gente lo confirmó. **Ámbar:** todavía esperan.` + nota `Ubicaciones agregadas por vereda — nunca puntos exactos ni nombres.`
- M2 esperan: `{esperando} territorios siguen sin recibir la primera entrega. **No están olvidados: están registrados** — y este registro es público, para que nadie pueda decir que no sabía.`
- M3 voces: título `Voces de agradecimiento`; sub con audios: `Agradecimientos enviados por nota de voz o llamada al confirmar. Con autorización, sin nombres.`; sub sin audios: `Cuando una comunidad graba su gracias y autoriza publicarlo, suena acá.`
- M4 cierre: título `La próxima historia puede empezar con vos`; sub `Estos territorios siguen esperando — acá importa más la próxima donación.`; CTA `Quiero ayudar — ver dónde donar`; footer `datos abiertos: CSV · HXL · GeoJSON en la pestaña de auditoría / sin nombres · sin puntos exactos · confirmado desde el territorio`
- M5 hint: `bajá — esto también es una historia`
- M6 ruta (junto a la línea de despacho, obligatorio): `trayecto ilustrativo` — la línea origen→destino es esquemática, NO la vía real; declararlo es parte de la honestidad del sistema.
- M7 modos del mapa: `✥ explorar el mapa` / `↩ seguir la historia`

Cambiar cualquier plantilla o microcopy = cambio de esta spec, no edición ad-hoc en código.

---

## 5. El mapa

**Implementación:** SVG inline autocontenido. Departamentos de Colombia (Natural Earth 10m, simplificados, ~18KB de paths) proyectados con `x=(lon+79.2)·60, y=(13.6−lat)·60`; el zoom/vuelo es animación del `viewBox` (easeInOut 1300ms). `vector-effect:non-scaling-stroke` en los límites. Tamaños de puntos/textos/ruta escalan con `k = viewBox.w/340` para mantener tamaño visual constante.

**Capas (orden z):** departamentos → ruta (punteada `--ok-mid`, opacidad 0 salvo escena dispatch) → pulsos (`reciente=true`, r 9→22·k, opacidad 0.3→0, ciclo 2s) → anillos de gracias (stroke `--ok-mid`) → puntos (r 6.5·k; fill teal/ámbar; stroke `--dot-stroke` 1.4·k) → etiquetas de ciudades (mono, `--map-city`).

**Escenas — derivadas de los datos, nunca coordenadas a mano:**

| Escena | Regla de cálculo |
|---|---|
| S0 país | `bbox(todos los territorios)` + 18% padding |
| S1 esperan | `bbox(territorios estado=espera)` + 22% |
| S2 presentación | centro = territorio de la historia; `w = 110` |
| S(need) | mismo centro; `w = 75` |
| S(dispatch) | centro = punto medio(origen, destino); `w = distancia·1.7` (mín 90); ruta visible = polyline origen→destino |
| S(receipt) | centro = territorio; `w = 55` |

`bbox→w`: `w = max(Δlon, Δlat/aspecto)·60·(1+pad)`, con el aspecto del contenedor calculado en runtime. Clamps: `22 ≤ w ≤ 420`.

**Dos modos, transición sin costura:**
- *Historia* (default): mapa no interactivo; `IntersectionObserver` (rootMargin −42%/−42%) activa el paso y dispara su escena; tarjeta activa opacidad 1, resto 0.45.
- *Explorar* (botón M7): pan (drag), pinch (2 punteros), rueda; tap en punto → chip P8 (5s); todos los puntos a opacidad plena; **el scroll de pasos no toma el mapa**. Salir → flyTo a la escena del paso activo.
- **Regla anti-bug obligatoria:** `.steps{pointer-events:none}` + `.step .card{pointer-events:auto}` — sin esto, el contenedor de pasos intercepta todo toque sobre el mapa fijo (bug encontrado en pruebas con hit-testing real). Tap vs. drag se distingue en `pointerup` (umbral 7px), porque `setPointerCapture` retargetea el click.
- `touch-action:none` en el SVG solo en modo explorar.

---

## 6. Voces de agradecimiento

Con audios: tarjeta por voz — botón circular 46px (▶/❚❚, invertido al reproducir), forma de onda (barras 3px, **decorativa con alturas fijas** salvo que el export provea el campo opcional `peaks:[..]` con amplitudes reales), meta mono `{territorio} · {fecha_rel} · {dur} · publicado con autorización`. `<audio>` nativo con MP3 (Safari/iOS) y OGG; un solo audio a la vez. Sin audios: la sección **no desaparece ni se disculpa** — tarjeta esencia (borde teal, serif) con P6. El título M3 funciona en ambos estados.

## 7. Piso de calidad (no negociable)

- **Cero dependencias externas**: sin CDN, sin fuentes web, sin tiles. Presupuesto total ≤ 45KB. Si un entorno ejecuta HTML+JS, esto corre.
- **Sin JavaScript**: todo el contenido textual legible. **En producción esto exige que Jinja2 renderice los strings server-side** (plantillas P/M aplicadas en el export, no en el cliente); el objeto `DATA` se inyecta además como JSON inline solo para mapa e interacciones. *(El prototipo renderiza todo client-side por simplicidad — NO replicar eso en producción.)* El mapa muestra su primera escena estática (SVG renderiza sin JS); solo mueren vuelo, modos y player.
- `prefers-reduced-motion`: vuelos → cortes; pulso → apagado; hint sin animación.
- `prefers-color-scheme`: automático, tokens incluidos el mapa.
- Accesibilidad: SVG `role="img"` + `aria-label`; botones con `aria-label`; contraste AA en ambos modos; targets ≥ 44px.
- Rendimiento: sin frameworks; un solo rAF loop compartido (animación de viewBox + pulso).

## 8. Integración con el export (componente 11) y notas de implementación

- **Un solo template Jinja2** (`vista_ciudadana.html.j2`) en el job de export del Radar Core. El export: (1) construye `vista-ciudadana.json` desde el log de eventos (aplicando la regla de selección de historia y el filtrado de voces autorizadas), (2) aplica las plantillas P/M server-side para el contenido textual, (3) inyecta el JSON inline en un `<script>` para mapa e interacciones, (4) escribe el HTML final al directorio estático servido tras Cloudflare. Sin build de frontend, sin Node, sin framework.
- **Módulos del JS del cliente** (vanilla, un archivo inline, ~250 líneas): construcción de capas SVG desde `DATA.territorios` → motor de viewBox (escenas calculadas + animación easeInOut 1300ms en un único rAF compartido con el pulso 2s) → observer de pasos (rootMargin −42%/−42%) → modo explorar (pan/pinch/rueda, tap en `pointerup` con umbral 7px, chip P8) → voces (audio nativo, uno a la vez) → sin estado global más allá de `VB/focus/freeMode/curScene`.
- **El toggle "demo: con/sin audios" es SOLO del prototipo** — no existe en producción; el estado lo decide `voces.length`.
- **Basemap**: los paths SVG de departamentos se generan una vez con el script del Apéndice A y se incluyen en el template como fragmento estático. No se regeneran en cada export.
- **Prototipo de referencia**: `radar-ciudadano-historia.html` implementa esta spec al 100% client-side y es la referencia visual y de interacción; ante ambigüedad entre spec y prototipo, gana la spec.

## 9. Protocolo de verificación (obligatorio antes de publicar)

Probado con Playwright/Chromium headless, viewport 390×844:

1. **Red 100% bloqueada** (`route abort` de todo excepto `file://`): la página completa debe renderizar y funcionar. Cero requests externos.
2. **Hit-testing real, nunca clicks sintéticos** (`element.click()` por JS salta las capas y esconde bugs de superposición): entrar a modo explorar con click real en el botón → pan con drag real → zoom con rueda → tap real sobre un punto → chip visible → salir → el mapa vuela a la escena del paso activo.
3. **Escenas**: scrollear cada paso al centro y verificar que el `viewBox` cambia al valor calculado; la ruta con etiqueta "trayecto ilustrativo" visible SOLO en la escena dispatch.
4. **Datos alternativos**: `historia:null` → solo pasos S0–S1, sin errores; `voces:[]` → esencia P6 con contador real; cambiar fechas de eventos → los "Día N" se recalculan.
5. **Auditoría de strings** (criterio 8.1): grep del HTML final contra las listas P/M — ningún string huérfano.
6. `pageerror` en consola = bloqueo de publicación.

## 10. Criterios de aceptación

- [ ] **Auditoría de strings:** todo texto visible es rastreable a un campo del JSON, a una plantilla P1–P8 o a un microcopy M0–M7. Ninguna persona, rol, causa o cita inventada.
- [ ] Cambiar el JSON (otra historia, otros territorios) re-narra la página completa sin tocar una línea de código: pasos, días, escenas y ruta se recalculan.
- [ ] `historia:null` → la página funciona con S0–S1 y sin sección de historia rota.
- [ ] `voces:[]` → esencia P6 con el contador real.
- [ ] Escenas del mapa correctas para cualquier geometría de datos (bbox dinámico, sin coordenadas mágicas).
- [ ] Ciclo scroll → explorar → pinch → tap punto → volver, verificado con hit-testing real (no clicks sintéticos).
- [ ] Archivo único ≤ 45KB, funcional con la red 100% bloqueada.


---

## Apéndice A — Generación del basemap embebido

Fuente: Natural Earth 10m admin-1 (`ne_10m_admin_1_states_provinces.geojson`). Ejecutar una vez; el fragmento resultante (~18KB) se pega en el template dentro de `<g class="dpto">`.

```python
import json
from shapely.geometry import shape, mapping

data = json.load(open('ne_10m_admin_1_states_provinces.geojson'))
cols = [f for f in data['features'] if f['properties'].get('adm0_a3') == 'COL']  # 34 departamentos

LON0, LAT0, K = -79.2, 13.6, 60.0          # proyección: x=(lon-LON0)*K ; y=(LAT0-lat)*K
xy = lambda lon, lat: (round((lon-LON0)*K, 1), round((LAT0-lat)*K, 1))

paths = []
for f in cols:
    g = shape(f['geometry']).simplify(0.035, preserve_topology=True)
    gm = mapping(g)
    polys = gm['coordinates'] if gm['type'] == 'MultiPolygon' else [gm['coordinates']]
    d = ''.join('M' + ' '.join(f'{x} {y}' for x, y in (xy(lon, lat) for lon, lat in ring)) + 'Z'
                for poly in polys for ring in poly)
    paths.append(f'<path d="{d}"/>')

open('dptos_paths.svg.frag', 'w').write(''.join(paths))
```

La MISMA proyección (`x=(lon+79.2)·60`, `y=(13.6−lat)·60`) se usa en el JS del cliente para puntos, ruta y ciudades — si cambia una, cambian ambas. El `viewBox` inicial de referencia es `120 480 340 380` y el factor de escala visual es `k = viewBox.w / 340`.

## Apéndice B — Datos de ciudades del basemap

Etiquetas fijas (microcopy geográfico, parte del basemap, no del JSON): Cali (−76.53, 3.45) · Pereira (−75.69, 4.81) · Quibdó (−76.66, 5.69) · Medellín (−75.57, 6.25). Ampliar solo si la cobertura de territorios se extiende a otras regiones.