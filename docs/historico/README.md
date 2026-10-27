# Histórico — documentos del sistema anterior

Estos documentos describen el proyecto **antes** del giro a *Wallet MCP +
Knowledge Base*. Se archivan, no se borran, porque contienen ideas que siguen
siendo válidas y que conviene no re-descubrir.

Nada de aquí es normativo. La referencia vigente está en
[`../../AGENTS.md`](../../AGENTS.md), [`../../rules/`](../../rules) y
[`../commands.md`](../commands.md).

## Qué hay

| Archivo | Qué era | Por qué se conserva |
|---|---|---|
| `arquitectura-modular-ia-plan.md` | Plan de refactor por capas + proveedores IA intercambiables (Gemini / Nvidia+RAG) | Contratos estables, separación de capas y estrategia de ramas. Varias ideas se resolvieron de otra forma con MCP, pero el razonamiento sirve |
| `tareas.md` | Backlog del sistema con dashboard e IA | Ideas de análisis que siguen pendientes y hoy son más baratas de hacer por lenguaje natural |
| `estado-del-sistema-flujo-completo.html` | Diagrama del pipeline anterior | Contexto histórico del flujo |
| `commands.md` | Stub de comandos antiguo | Reemplazado por `../commands.md` |
| `docker-guide.md`, `docker-compose-guide.md` | Guías genéricas de Docker | Conocimiento de despliegue; Docker sigue siendo opcional |
| `interactions.openapi.json` | Spec de la API Interactions de Gemini | Solo referencia; el SDK ya no está en el proyecto |

## Ideas rescatadas

Del backlog anterior, lo que sigue teniendo valor y **cómo se cubre ahora**:

| Idea | Estado actual |
|---|---|
| Chat sobre los propios registros | Cubierto: es exactamente lo que hace el agente con el MCP |
| Análisis de avance por meses, cuentas y categorías | Cubierto: `get_records_aggregation` agrupa por mes/cuenta/categoría |
| Homogeneidad de etiquetas | Cubierto: `rules/etiquetas.md` + `patch_labels` |
| Nombres de categorías en español | Cubierto en `rules/categorias.md` (término humano → `systemId`) |
| Histórico de análisis con línea de discurso | Cubierto: `rules/informes.md` define plantillas estables |
| Patrimonio por cuenta y moneda en el tiempo | **Pendiente** — agregación por cuenta + serie temporal |
| Top contrapartes / comercios | **Pendiente** — agregación por `counterParty` |
| Fallback de proveedor de tasas históricas | Cubierto por el MCP (conversión con tasas históricas) |
| Sankey / dashboard | **Descartado** como app propia: los informes se piden en el chat |
| Auto-revisión multiagente de análisis | **Descartado**: el agente ya razona sobre datos agregados, no sobre volcados |

## Lo que se descartó y por qué

- **Pipeline de IA propio** (`analizador_finanzas`, `aprendizaje_reglas`,
  `confirmador_reglas`, `asistente_enriquecimiento`, `generar_dashboard`):
  duplicaba el trabajo del agente y quemaba tokens enviando el histórico
  completo en cada llamada.
- **Snapshots automáticos**: el MCP lee en vivo; el respaldo JSON queda como
  herramienta puntual (`tools/backup_wallet.py`).
- **Abstracción multi-proveedor de IA**: el proveedor lo elige el harness
  (OpenCode/Hermes), no el repo.
