# Pruebas — Épica 03 · Radar Operativo

Los componentes 12–14 (Vigía de Medios, cola de incorporación de localidades,
vista operativa) están **especificados pero no implementados**. Los casos de
prueba ya están definidos en [docs/test-suite.md](../../docs/test-suite.md) §4
con IDs `U3-` / `I3-` / `S3-`.

Regla de la casa: los tests de invariantes (señales fuera del log de eventos,
señal sin URL descartada, nunca publicar localidad sin pcode, la alerta por
ausencia no se degrada) se escriben **junto con la primera versión de cada
componente**, no después.

Estructura esperada al implementar (espejo de la épica 01):

```
epica03_radar_operativo/
  unit/          U3-xx — reglas de extracción, dedupe/refuerzos, decaimiento, conversión…
  integration/   I3-xx — run del Vigía con fuentes fixture, conciliación, cola de localidades…
  contrato/      S3-xx — la vista operativa desde el despachador; estados de arranque
```
