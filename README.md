# Wallet + Knowledge Base

Finanzas personales en lenguaje natural sobre **BudgetBakers Wallet (Premium)**
con el MCP oficial, una base de conocimiento local y cero código de IA.

> **WIP** — proyecto personal en evolución.

## Idea

```
Wallet (MCP oficial)  ←→  Agente (OpenCode / Hermes)  ←→  rules/ (Knowledge Base)
                                     ↕
                            tools/ (escape hatch determinista)
```

- **El agente razona.** No hay pipeline, ni prompts empaquetados, ni SDK de IA
  en el repo. OpenCode o Hermes leen el MCP y deciden.
- **`rules/` guarda cómo piensas tú.** Hechos observados en tu histórico +
  convenciones que escribes a mano. Es markdown versionado, editable y barato
  de leer.
- **`tools/` es el escape hatch.** Lo que el MCP no cubre bien: respaldo,
  conciliación determinista contra capturas, ajuste de apertura, bootstrap de
  la KB.

## Uso diario

Dentro del agente, en lenguaje natural:

| Dices | Pasa |
|---|---|
| "Gasté 45.300 en servicentro con Nequi" | Resuelve cuenta, categoría (Fuel) y etiquetas desde `rules/`, muestran resumen, confirman y registran |
| "¿Cuánto tengo?" | Tabla por cuenta + total por moneda |
| "Informe de octubre" | Agregación por categoría |
| "Concilia Pibank con esta captura" | Plan v1 → `tools/conciliar_cuenta.py` |
| "Corrige la categoría de ese movimiento" | `patch_records` con antes/después |

Reglas duras (aprobación antes de escribir, idempotencia, IDs por `systemId`,
fechas en `America/Bogota`, sin conversiones implícitas): ver `AGENTS.md`.

## Conectar el MCP

```powershell
opencode mcp add wallet --url https://mcp.wallet.budgetbakers.com
```

Luego, en la interfaz: `/mcps` → `wallet` → **sign in** (OAuth con email y
código de 6 dígitos).

### Hermes

```powershell
hermes mcp add wallet --url https://mcp.wallet.budgetbakers.com --auth oauth
hermes mcp login wallet          # interactivo: email + código
hermes skills trust .            # carga .hermes/skills/wallet
```

Guía completa: [`docs/hermes-setup.md`](docs/hermes-setup.md).

Permisos se gobiernan en `web.budgetbakers.com/settings/mcp-server`
(por defecto solo lectura). Habilita `records.create`, `records.update` y
`records.delete`. Se verifican con `get_client_profile` → `grantedScopes`.

> **Ojo con el modelo de permisos.** El OAuth del MCP solo maneja dos scopes
> gruesos: `read` y `write`. Los permisos finos (`records.create`,
> `records.update`, `records.delete`…) **no son scopes de OAuth**: son
> interruptores por tipo de dato en la web de Wallet. Ahí no verás una casilla
> llamada `records.create`; verás una matriz de *entidades × acciones*
> (Records / Accounts / Budgets / Categories / Labels con Read, Create,
> Update, Delete). Detalle en [`rules/mcp_tools.md`](rules/mcp_tools.md).

Inventario completo de tools, límites de lote y tabla de errores:
[`rules/mcp_tools.md`](rules/mcp_tools.md).

## Herramientas

```powershell
.\scripts\budget.ps1 doctor        # entorno, MCP y KB
.\scripts\budget.ps1 backup        # respaldo completo a output/
.\scripts\budget.ps1 bootstrap     # (re)genera rules/*.md
.\scripts\budget.ps1 agregar -Desde 2026-10-01 -Por categoria
.\scripts\budget.ps1 sync-skills   # copia la skill a .hermes/
.\scripts\budget.ps1 reconcile -Plan plans\plan_pibank.json -DryRun
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2.580.398,47 -Delta 2.580.400,24 -Explicacion "Residual de apertura"
.\scripts\budget.ps1 test
```

Sin PowerShell: `make <target>` o `python tools/<script>.py` (con `PYTHONPATH=tools`).

## Estructura

```
AGENTS.md              Identidad y reglas del agente
opencode.json          MCP de Wallet (OpenCode)
.opencode/
  skills/wallet/SKILL.md  Skill canónica (fuente única)
.hermes/
  config.example.yaml   Fragmento MCP para Hermes
  skills/wallet/SKILL.md  Copia generada de la skill (no editar a mano)
rules/
  cuentas.md           Cuentas, moneda, sync, saldo (hechos) + tu rol (convenciones)
  categorias.md        systemId + consistencia de términos de nota
  etiquetas.md         Uso real de cada etiqueta
  informes.md          Plantillas y reglas de coste
  mcp_tools.md         Inventario real de tools del MCP
tools/
  wallet_client.py     Cliente REST con contratos verificados
  backup_wallet.py     Respaldo JSON
  bootstrap_rules.py   Genera rules/*.md (determinista, sin LLM)
  plan_conciliacion.py Esquema v1 + parsing es-CO + matching
  conciliar_cuenta.py  Conciliación contra capturas
  ajustar_saldo_cuenta.py  Partida de apertura (initialBalance)
  agregar_periodo.py   Suma determinista por grupo (fallback de P6)
  sync_skills.py       Sincroniza la skill canónica a .hermes/
plans/                 Planes de conciliación
schemas/               plan.conciliacion.v1.json
tests/                 Suite del cliente, plan y sincronización de skills
scripts/budget.ps1     Runner nativo (Windows)
docs/commands.md       Comandos y problemas frecuentes
docs/hermes-setup.md   Guía de Hermes equivalente a OpenCode
docs/historico/        Documentos del sistema anterior (ideas rescatadas)
```

## Knowledge Base

`rules/*.md` tiene dos zonas:

```markdown
<!-- HECHOS:START -->   ... se regenera con tools/bootstrap_rules.py
<!-- HECHOS:END -->

<!-- CONVENCIONES:START -->   ... tuya, nunca se sobrescribe
<!-- CONVENCIONES:END -->
```

Correr `bootstrap` de nuevo refresca los hechos y **conserva** lo que escribiste.
El aprendizaje es editar el markdown: explícito, auditable y sin coste de tokens.

## Tests

```powershell
.\scripts\budget.ps1 test
```

Cubren parsing es-CO, tolerancia de fechas, validación del plan, contratos de
escritura, shape de transferencias, paginación y resolución de categorías por
`systemId` en runtime.

## Documentación

- [`AGENTS.md`](AGENTS.md) — reglas que sigue el agente
- [`rules/mcp_tools.md`](rules/mcp_tools.md) — tools reales del MCP
- [`docs/commands.md`](docs/commands.md) — comandos y problemas frecuentes
- [`docs/budgetbakers.openapi.json`](docs/budgetbakers.openapi.json) — API REST

## Autor

Anderson Bedoya Ciro
