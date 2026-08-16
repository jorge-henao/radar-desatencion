# Pruebas — Épica 02 · Radar Ciudadano

Los componentes 9–11 (banco de voces, importador de feeds de aliados, generador
de vista ciudadana) y la tool `buscar_gracias` están **especificados pero no
implementados**. Los casos de prueba ya están definidos en
[docs/test-suite.md](../../docs/test-suite.md) §3 con IDs `U2-` / `I2-` / `S2-`.

Regla de la casa: los tests de invariantes (consentimiento, agregación,
solo-lectura del API de Analyze, auditoría de strings del front) se escriben
**junto con la primera versión de cada componente**, no después.

Estructura esperada al implementar (espejo de la épica 01):

```
epica02_radar_ciudadano/
  unit/          U2-xx — gate de moderación, selección de historia, degradación de feeds…
  integration/   I2-xx — pipeline del adaptador Analyze (API simulada), export de la vista…
  contrato/      S2-xx — buscar_gracias desde el agente Vozy; la vista desde el visitante web
```
