# Hermes — integración local

Esta carpeta hace que **Hermes** funcione igual que OpenCode sobre este repo.

## Qué hay aquí

| Archivo | Para qué |
|---|---|
| `config.example.yaml` | Fragmento para pegar en la config global de Hermes (`%LOCALAPPDATA%\hermes\config.yaml`) con el servidor MCP de Wallet |
| `skills/wallet/SKILL.md` | Copia **generada** de `.opencode/skills/wallet/SKILL.md`. No la edites a mano |

## Configurar Hermes (una vez)

1. **Servidor MCP.** Agrega Wallet a Hermes. Dos formas:
   - CLI: `hermes mcp add wallet --url https://mcp.wallet.budgetbakers.com --auth oauth`
   - Manual: pega el bloque de `config.example.yaml` bajo `mcp_servers:` en
     `%LOCALAPPDATA%\hermes\config.yaml`.
2. **OAuth (interactivo).** En una terminal normal:
   ```powershell
   hermes mcp login wallet
   ```
   Completa el flujo en el navegador. Hermes guarda el token y lo reutiliza.
3. **Confiar en el repo.** Para que Hermes cargue skills repo-local:
   ```powershell
   hermes skills trust .
   ```
4. **Sincronizar la skill.** Después de editar `.opencode/skills/wallet/SKILL.md`:
   ```powershell
   .\scripts\budget.ps1 sync-skills
   ```
   o `python tools/sync_skills.py`.
5. **Verificar.**
   ```powershell
   hermes mcp list          # wallet debe aparecer enabled
   hermes mcp test wallet   # conexión + tools
   hermes skills list       # wallet debe aparecer como local
   ```

## Qué se comparte automáticamente

- **`AGENTS.md`**: Hermes lo inyecta desde el directorio de trabajo. No hay que
  copiarlo ni configurarlo.
- **`rules/`**: es markdown plano; el agente lo lee con sus herramientas de
  archivos.
- **`tools/`**: los scripts deterministas se ejecutan igual (Python/PowerShell).

## Qué NO se comparte

- El estado de OAuth de OpenCode. Hermes necesita su propio `hermes mcp login wallet`.
- La sesión y el historial de OpenCode. Hermes usa sus propias sesiones.
- El archivo `opencode.json`: es exclusivo de OpenCode. Hermes usa `mcp_servers`
  en su config global.

## Diferencias de nombres de tools

OpenCode expone las tools como `wallet_get_accounts` (prefijo del servidor). Hermes
las expone como `mcp__wallet__get_accounts` o similar. El **nombre lógico** del
tool no cambia: `get_accounts`, `create_records`, etc. La skill usa los nombres
lógicos y las reglas de `rules/mcp_tools.md`.

## Mantenimiento

El test `tests/test_skill_sync.py` falla si `.hermes/skills/wallet/SKILL.md` no
coincide con la copia canónica. Corre `sync-skills` y vuelve a probar.
