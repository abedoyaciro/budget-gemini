# Hermes — configuración equivalente a OpenCode

Objetivo: que **Hermes** opere Wallet con el mismo MCP, la misma Knowledge Base
(`rules/`) y la misma skill (`wallet`) que OpenCode, sin duplicar lógica ni
credenciales.

Hermes es el agente CLI/desktop de Nous Research. A diferencia de OpenCode, su
configuración es global (`%LOCALAPPDATA%\hermes\config.yaml`) y sus skills
repo-local se cargan desde `./.hermes/skills` o `./.agents/skills` cuando el repo
está *trusted*.

## 1. Requisitos

- Hermes instalado y funcionando (`hermes --version`).
- Plan Premium de Wallet con MCP habilitado.
- Python 3.11+ y PowerShell 7 (para los scripts deterministas).

## 2. Registrar el MCP de Wallet en Hermes

### Opción A — CLI (recomendada)

```powershell
hermes mcp add wallet --url https://mcp.wallet.budgetbakers.com --auth oauth
```

En modo no interactivo el comando guarda el servidor como **disabled** porque no
puede completar OAuth. Es lo esperado. Después:

```powershell
hermes mcp login wallet
```

Completa el flujo en el navegador (email + código de 6 dígitos). Luego:

```powershell
hermes mcp test wallet
hermes mcp list
```

### Opción B — Config manual

Pega el bloque de [`.hermes/config.example.yaml`](../.hermes/config.example.yaml)
bajo `mcp_servers:` en la configuración activa:

```
%LOCALAPPDATA%\hermes\config.yaml
```

El bloque mínimo es:

```yaml
mcp_servers:
  wallet:
    url: https://mcp.wallet.budgetbakers.com
    auth: oauth
    connect_timeout: 10.0
    keepalive_interval: 120
    enabled: true
```

`auth: oauth` activa OAuth 2.1 + PKCE. Sin token, la primera conexión falla con
un mensaje claro; corre `hermes mcp login wallet` y reintenta.

### Permisos

Los scopes finos se activan en `web.budgetbakers.com/settings/mcp-server`
(matriz entidad × acción). Verifica con `get_client_profile` → `grantedScopes`.
Detalle en [`rules/mcp_tools.md`](../rules/mcp_tools.md).

## 3. Cargar la skill en Hermes

La skill canónica vive en `.opencode/skills/wallet/SKILL.md`. Para Hermes se
genera una copia en `.hermes/skills/wallet/SKILL.md`:

```powershell
.\scripts\budget.ps1 sync-skills
```

Luego confía en el repo para que Hermes cargue skills repo-local:

```powershell
hermes skills trust .
hermes skills list
```

`AGENTS.md` se inyecta automáticamente desde el CWD; no requiere copia. `rules/`
se lee como markdown normal.

## 4. Verificación rápida

| Comando | Esperado |
|---|---|
| `hermes mcp list` | `wallet` con `enabled` |
| `hermes mcp test wallet` | conexión OK y lista de tools |
| `hermes skills list` | `wallet` como skill local |
| `hermes -s wallet -z "¿Cuánto tengo en Nequi?"` | respuesta con datos reales |

Si `hermes mcp test wallet` falla por OAuth, repite `hermes mcp login wallet`.
Si falla por red, revisa DNS/proxy; el servidor es `mcp.wallet.budgetbakers.com`.

## 5. Mantener la skill sincronizada

Después de editar `.opencode/skills/wallet/SKILL.md`:

```powershell
.\scripts\budget.ps1 sync-skills
.\scripts\budget.ps1 test
```

El test `tests/test_skill_sync.py` falla si las copias divergen. Es intencional:
una sola fuente de verdad.

## 6. Qué NO se comparte con OpenCode

- **Token OAuth:** Hermes guarda su propio token; no reutiliza el de OpenCode.
- **Sesiones/historial:** cada agente mantiene su estado.
- **`opencode.json`:** es de OpenCode. Hermes usa `mcp_servers` en su config.
- **Nombres de tools con prefijo:** OpenCode usa `wallet_get_accounts`; Hermes usa
  `mcp__wallet__get_accounts` (o similar). El nombre lógico no cambia: la skill y
  `rules/mcp_tools.md` usan `get_accounts`, `create_records`, etc.

## 7. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `wallet` aparece disabled | OAuth no completado | `hermes mcp login wallet` |
| `non-interactive environment` | Login en shell no interactivo | Abre una terminal normal y repite |
| Skill no aparece | Repo no trusted | `hermes skills trust <ruta>` |
| Skill desactualizada | Editaste solo OpenCode | `.\scripts\budget.ps1 sync-skills` |
| `permission not granted` | Scope apagado en la web | Actívalo y verifica con `get_client_profile` |
| `429` | Límite compartido MCP+REST | Para y espera; no reintentes en bucle |
| Cambio no visible | Sync de hasta 15 min | Una relectura; espera |

## 8. Referencias

- [`AGENTS.md`](../AGENTS.md) — reglas duras del agente
- [`rules/mcp_tools.md`](../rules/mcp_tools.md) — tools reales y contratos
- [`rules/informes.md`](../rules/informes.md) — plantillas de informes
- [`.hermes/README.md`](../.hermes/README.md) — notas de la carpeta Hermes
- [`docs/commands.md`](commands.md) — comandos deterministas
