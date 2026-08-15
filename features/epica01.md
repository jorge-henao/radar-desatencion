# Radar de Desatención

**Un 3W de última milla, en tiempo real.** Mide lo único que nadie está midiendo: **dónde no ha llegado nada.**

> Un registro público de **eventos de entrega** de ayuda humanitaria, alimentado por WhatsApp desde los dos extremos de la cadena —quien despacha y quien recibe—, cuya salida es un ranking de territorios por **días sin recepción registrada**.

**SÍ es:** un registro de entregas.
**NO es:** mapa de daños · directorio de donaciones · inventario de stock · registro de beneficiarios · canal de recaudo.

*Contexto: terremoto M7.4, San José del Palmar (Chocó), 10 ago 2026 · 437 municipios afectados, 13 departamentos · corte del documento: 14 ago 2026 · propuesta sin validación de campo.*

---

## 1. Por qué existe — la ayuda sigue a la visibilidad, no a la necesidad

La cadena de razonamiento en cinco pasos, cada uno anclado a evidencia:

1. **La ayuda se concentra donde hay visibilidad, no donde hay necesidad.** Los donantes escogen zonas de entrega según lo que ven en redes y medios — y las redes se enfocan en los casos grandes, no en los remotos. *(Kermanshah 2017 · JHLSCM 13(4), 2023)*
2. **La visibilidad depende de señal, vía y cobertura mediática** — tres cosas que correlacionan negativamente con la vulnerabilidad. En Riofrío rural, 3 días después nadie había hecho censo; la gobernadora del Chocó tardó 2 días en llegar al epicentro. *(La Silla Vacía · Defensoría del Pueblo, ago 2026)*
3. **Todo el ecosistema mide daño** (dónde ocurrió): imágenes satelitales, drones, mapeo HOT/OSM. **Nadie mide desatención** (dónde no ha llegado nada desde entonces). *(UNGRD/NASA: 166 imágenes satelitales · HOT Tasking Manager)*
4. **En suministros consumibles no falta oferta** — el PMA tiene 565.000 canastas ya en país. Faltan señal de demanda granular y coordinación entre cinco cadenas paralelas (Cruz Roja, ABACO, fundaciones, alcaldías, gremios) que no se ven entre sí. *(PMA Colombia · mapeo de acopios, ago 2026)*
5. **La ausencia de eventos de entrega en un territorio ES la señal de desatención.** No hay que preguntarla: se deduce del registro. Basta con registrar entregas y leer los huecos. ← *el insight central*

**El bucle que el sistema rompe:**

```
sin señal/vía ──▶ no hay reporte ──▶ no hay censo ──▶ no hay asignación ──▶ no llega ayuda
      ▲                                                                        │
      └────────────── y sin ayuda, tampoco se restablece la señal ◀────────────┘
```

---

## 2. Por qué importa — los precedentes ya demostraron qué falla

**México 2017.** Verificado19S resolvió la verificación y **no** resolvió la distribución: Puebla, Morelos, Oaxaca y Chiapas recibieron menos ayuda con la plataforma funcionando desde el día 1. → La salida debe ser un ranking accionable, no un mapa de puntos. **Mapear ≠ asignar.** *(Ford Foundation · Ruta Cívica)*

**Colombia 2026 · el RUD.** El registro estatal exige evaluación técnica presencial: el hogar rural disperso con la vía bloqueada es el último en ser censado — el mecanismo de acceso a la ayuda deja de último a quien más la necesita. → El sistema no puede depender del RUD para identificar necesidad. *(UNGRD · ColombiaTramita)*

**La oferta lo está pidiendo.** SCARE pidió que las donaciones respondan "exclusivamente a necesidades comunicadas oficialmente" — una organización diciendo en voz alta que le falta el dato de qué se necesita dónde. Hay un cliente esperando. *(Asoc. Col. de Sociedades Científicas, ago 2026)*

**Nepal 2015.** Más proveedores concentrados **empeoran** la asignación: el exceso de organizaciones en los distritos de mayor impacto intensificó la confusión. La deduplicación tiene valor incluso donde sobra oferta — fue el valor real de Building Blocks (US$288M en duplicación evitada). *(Ejército de Nepal / RSIS 2016 · WFP Innovation)*

---

## 3. La salida — una tabla que se usa a las 6 a.m.

No es un mapa: es la herramienta con la que el despachador decide a dónde sale el camión mañana.

| Territorio | Días sin recepción | Hogares ~ | Faltante reportado | Vía |
|---|---|---|---|---|
| **cgto. sin reporte NI recepción** (DIVIPOLA 27660···) | **⚠ ALERTA MÁXIMA** | ? | *sin datos ≠ sin necesidad* | ? |
| vda. La Cabaña — Jamundí (Valle) | **11** | ~40 | agua, alimentos | ⚠ restringida |
| cgto. San Pedro — San José del Palmar (Chocó) | **9** | ~25 | agua, medicamentos | ✕ bloqueada |
| comuna 4 — Dosquebradas (Risaralda) | 6 | ~120 | alimentos | ✓ transitable |
| barrio Niquía Alta — Quibdó (Chocó) | 1 | ~80 | aseo/higiene | ✓ transitable |

**Regla explícita contra el sesgo de acceso:** territorio sin ningún evento = **alerta máxima, no dato faltante.** Quien no puede reportar es exactamente la población objetivo.

```
desatención(territorio) = días desde el último RECEIPT confirmado
                          × población_estimada_afectada
                          ÷ factor_accesibilidad_vial   ← Invias #767
```

---

## 4. Usuarios — cuatro, no dos

El despachador decide *entre municipios*; el coordinador receptor decide *dentro del municipio*. Son las dos escalas del problema y necesitan vistas distintas.

| | Quién es | Necesidad real | Interfaz |
|---|---|---|---|
| **U1 · Reportante en territorio** | Habitante, docente, promotora de salud, personero, presidente de JAC, líder de consejo comunitario | "Que alguien sepa que acá no ha llegado nada" | WhatsApp conversacional · sin app · sin registro previo |
| **U2 · Despachador** | Coordinador de bodega/acopio: Cruz Roja, ABACO, Fundación Éxito, alcaldía emisora, SCARE, gremio, municipio padrino | "Decidir a dónde sale el camión mañana — y tener evidencia de entrega para el donante y la legalización" | Web (leer la tabla) + WhatsApp (declarar despacho) |
| **U3 · Coordinador receptor** | CMGRD, alcaldía o gobernación del municipio afectado | "Saber qué veredas de mi municipio faltan — y si lo que declararon que me mandaron llegó" | Web filtrada a su territorio + WhatsApp (validar) |
| **U4 · Público** | Prensa, Defensoría del Pueblo, donantes, academia, ciudadanía | "Ver si la ayuda está llegando donde debe" | Web pública sin registro + descarga abierta CSV/HXL |

**U4 no es decorativo:** la rendición de cuentas pública fue la variable causal que eliminó la captura de élite en la evidencia de China rural *(World Development 115, 2019)*. Es una función del sistema, no marketing.

---

## 5. Interfaces — tres superficies, cada una para algo concreto

Cada capa funciona sin la de arriba: WhatsApp → SMS → llamada de voz que transcribe. En las veredas del epicentro la falta de señal es el hecho dominante.

**WhatsApp / voz — registrar eventos** *(U1 · U2 · U3)*
- Confirmar recepción: qué llegó, a cuántos hogares, pin GPS, foto opcional (< 60 s)
- Declarar despacho: categoría, unidades, destino, ETA → devuelve folio (< 30 s)
- Reportar necesidad: categorías cerradas, hogares en rangos, pin (< 60 s)
- Pin de WhatsApp como ubicación: usa GPS del teléfono, funciona sin datos. Nunca direcciones — en vereda dispersa no existen
- Degradación a voz telefónica: funciona con señal 2G, baja alfabetización digital, español regional

**Web — decidir y auditar** *(U2 · U3 · U4, lectura, sin login)*
- Tabla de priorización ordenable: días sin recepción × hogares × vía transitable
- Vista de municipio para el CMGRD: sus veredas, a nivel DIVIPOLA
- Alerta de desfase: despachos declarados sin recepción confirmada tras N días
- Alerta de duplicación: "otra organización declaró despacho a este mismo destino hace 2 días"
- Mapa público con una sola métrica visible, agregada a vereda — sin pins individuales

**Salida de datos — interoperar** *(U4 · sector humanitario · SNIGRD)*
- CSV con etiquetas HXL: consumible por HDX y el sector, no otro silo
- Códigos DIVIPOLA (p-codes): cruza con todo lo que ya existe en Colombia
- Comprobante de entrega reconciliado: despacho + confirmación independiente desde territorio, listo para el informe al donante y la legalización UNGRD
- API pública del registro agregado, sin PII: captura a nivel hogar, publica a nivel vereda

---

## 6. Storyboard — el flujo completo, de la necesidad al cierre

Un solo caso de punta a punta: el corregimiento San Pedro, San José del Palmar (Chocó) — la vía bloqueada por derrumbes, sin censo tres días después. Siete pasos, tres actores; en cada paso, quién es el usuario y el problema que atiende.

### Paso 1 · U1 — Una promotora de salud reporta lo que falta

No es la afectada directa: es un tercero que reporta por su comunidad. Camina hasta donde hay señal y en menos de 60 segundos registra qué falta, para cuántos hogares y dónde. Sin app, sin registro, solo el pin GPS de WhatsApp.

```
BOT: Hola. Esto sirve para que quienes coordinan ayuda sepan dónde no ha
     llegado. NO garantiza que llegue una entrega.
     ¿Qué hace más falta ahí?
     [1] Agua [2] Alimentos [3] Medicamentos [4] Aseo [5] Techo [6] Otro
USR: 1 2
BOT: ¿Cuántos hogares, más o menos? [1-5] [6-20] [21-50] [+50] [no sé]
USR: 21-50
BOT: Mandame tu ubicación (📎 → Ubicación). Funciona sin datos.
USR: 📍 4.9861, -76.2340
BOT: ¿Cómo se llama el lugar?
USR: corregimiento San Pedro
BOT: Listo. Folio NE-0847. Esto queda visible para quienes coordinan
     envíos. Si llega algo, avisame por acá.
```

> **Problema que atiende:** el corregimiento no existe para el sistema de asignación — nadie ha censado, el RUD exige una visita presencial que no llega. Este mensaje es la primera vez que San Pedro aparece en el radar de alguien.

### Paso 2 · Sistema — La señal se vuelve dato estructurado

El pin se resuelve a DIVIPOLA, las categorías cerradas evitan el texto libre, y la deduplicación colapsa reportes de la misma categoría a <500 m / 24 h: dos vecinos más reportaron lo mismo, eso suma *intensidad*, no triple necesidad. San Pedro sube en la tabla.

> **Problema que atiende:** los datos "desestructurados y sueltos" son los primeros que las agencias descartan en emergencia — le pasó al mapa de Haití. El esquema cerrado y los p-codes hacen que este dato sí encaje en el flujo de quien decide.

### Paso 3 · U2 — La coordinadora de bodega decide con la tabla, no con las noticias

6:00 a.m. en el acopio de Pereira. Abre la tabla —sin login—, ordena por días sin recepción, filtra por vía transitable y por lo que tiene en bodega. San Pedro está arriba: 9 días, ~30 hogares, agua y alimentos. El camión de mañana cambia de destino.

> **Problema que atiende:** hoy el destino se escoge por visibilidad mediática, llamadas y experiencia propia — el sesgo documentado en Kermanshah. La tabla reemplaza la intuición por la métrica de desatención.

### Paso 4 · U2 — Declara el despacho en 30 segundos y recibe un folio

```
USR: Despacho: alimentos 80 kits, agua 120 bidones → San José del Palmar,
     cgto. San Pedro. Llega mañana en la tarde.
BOT: Registrado ✓  Folio DS-0392 · ETA 15 ago p.m.
     Imprimí el acta adjunta y mandala con el camión: con ella la
     comunidad confirma la recepción.
SYS: alerta enviada a 1 organización con despacho declarado al mismo destino
```

> **Problema que atiende:** la legalización de entregas que la UNGRD ya exige hoy se hace en Excel, a mano, después y de memoria. Declarar acá es el primer paso del comprobante que necesita para el donante y para el Estado. Entra por interés propio; el dato de coordinación es el subproducto.

### Paso 5 · Sistema — El folio viaja físicamente con el camión

El acta impresa lleva el folio, el número oficial de WhatsApp y un QR (`wa.me/<num>?text=DS-0392`). Es el mismo papel de entrega que el Manual de Logística de la UNGRD ya exige — solo que ahora **ese papel es también el canal**.

> **Problema que atiende:** dos a la vez. El arranque en frío (¿cómo se entera una vereda sin internet de que el canal existe? — cada entrega siembra un reportante) y la reconciliación (citando el folio, el cruce despacho↔recepción es determinístico, no una adivinanza por categoría y fecha).

### Paso 6 · U1 — Alguien de la comunidad confirma que llegó

No tiene que ser la misma persona del paso 1: el presidente de la JAC, con el acta en la mano, confirma en menos de 60 segundos.

```
USR: Llegó la ayuda del folio DS-0392
BOT: ¿Qué llegó? [Agua][Alimentos][Medicamentos][Aseo][Techo][Otro]
USR: Agua y alimentos
BOT: ¿A cuántos hogares alcanzó, más o menos?
USR: Como 28
BOT: Ubicación 📎 · ¿Foto? (opcional)
USR: 📍 4.9858, -76.2338 · 📷
BOT: Registrado. Folio RC-1204, cruzado con el despacho DS-0392.
     Gracias — esto es lo que permite saber qué zonas siguen sin recibir.
```

> **Problema que atiende:** sin cierre, la demanda se degrada en ruido. La confirmación es la señal más limpia del sistema — **nadie exagera lo que ya recibió** — y es lo que hace que "días sin recepción" sea un dato y no una suposición.

### Paso 7 · Sistema → U2 · U3 · U4 — El ciclo se cierra y todos ven lo mismo

La reconciliación DS-0392 ↔ RC-1204 dispara tres cosas: la fundación recibe su **comprobante de entrega** con confirmación independiente (informe al donante + legalización); el CMGRD ve el cierre — y vería la **alerta de desfase** si nunca hubiera llegado; y el contador de San Pedro vuelve a cero, empujando **el siguiente territorio desatendido** al tope de la tabla pública que la Defensoría y la prensa pueden descargar.

```
COMPROBANTE DE ENTREGA · ✓ reconciliado
despacho   DS-0392 · agua + alimentos
recepción  RC-1204 · 15 ago 17:40 · ~28 hogares
nivel      confirmación independiente + folio citado

TABLA PÚBLICA · después del cierre
cgto. San Pedro ............ 0 días ✓
vda. La Cabaña — Jamundí ... 9 días  ← el siguiente hueco sube al tope
```

> **Problema que atiende:** rendición de cuentas sin canal de quejas — la exclusión se vuelve visible en el dato agregado, la pérdida o desvío se detecta por desfase sin acusar a nadie, y el hueco que sigue queda arriba, donde el próximo despachador lo verá a las 6 a.m.

---

## 7. MVP — el recorte mínimo demostrable

**Dentro:** U1 confirma recepción por WhatsApp · U2 declara despacho y recibe comprobante · tabla de días-sin-recepción.
**Fuera:** reporte de necesidad · coordinador receptor · mapa público · alertas de duplicación · validación por líder.

Con esto solo ya se puede ir a la Federación de Municipios o al SNIGRD con algo que funciona, en vez de un diagrama — y ya produce la métrica que nadie tiene. El reporte de necesidad parece el corazón del producto y no lo es: la recepción confirmada produce la misma métrica con una señal más limpia y sin el riesgo de expectativa incumplida.

**Riesgos críticos vigilados:** R1 sesgo de acceso (territorio sin eventos = alerta máxima) · R7 no adopción institucional (entrar por el papeleo, no por el mapa).

---

*Radar de Desatención · propuesta de diseño · corte 14 ago 2026 · estándares: DIVIPOLA · HXL · vocabulario 3W/4W · integración objetivo: SNIGRD*