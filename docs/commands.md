# Comandos

El uso diario (registrar, consultar, informes, correcciones) va por el **MCP de
Wallet dentro del agente**. Este documento cubre las herramientas deterministas.

## Runner nativo (Windows, sin Docker, sin make)

```powershell
.\scripts\budget.ps1 help
```

| Comando | Qué hace |
|---|---|
| `budget.ps1 doctor` | Comprueba Python, `.env`, `opencode.json` y `rules/` |
| `budget.ps1 backup [-Out ruta.json]` | Respaldo completo (cuentas, categorías, etiquetas, registros) |
| `budget.ps1 bootstrap [-Days 0] [-DryRun]` | (Re)genera `rules/*.md` |
| `budget.ps1 reconcile -Plan p.json [-DryRun] [-Yes]` | Concilia una cuenta |
| `budget.ps1 ajustar -Cuenta X -InitialBalance N -Delta N -Explicacion "..." [-DryRun]` | Ajuste de partida de apertura |
| `budget.ps1 test` | Suite de tests |

Aplica siempre `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` y `PYTHONPATH=tools`.
Sin eso, un `print()` con acentos revienta en cp1252 y un proceso exitoso
termina con exit code 1.

## Make (opcional)

```bash
make doctor
make backup
make bootstrap DAYS=0
make reconcile PLAN=plans/x.json DRY=1
make ajustar CUENTA=Pibank INITIAL=2.580.398,47 DELTA=2.580.400,24 \
             EXPLICACION="Residual de apertura" DRY=1
make test
```

## Python directo

```powershell
$env:PYTHONPATH="tools"; $env:PYTHONUTF8="1"
python tools/bootstrap_rules.py --days 0
python tools/backup_wallet.py
python tools/conciliar_cuenta.py --plan plans\plan_pibank.json --dry-run
python tools/ajustar_saldo_cuenta.py --cuenta Pibank --initial-balance 2.580.398,47 `
    --delta 2.580.400,24 --explicacion "Residual de apertura" --dry-run
```

## Docker (opcional)

```bash
docker compose run --rm wallet-tools python tools/backup_wallet.py
docker compose run --rm wallet-tools python tools/bootstrap_rules.py --days 0
docker compose run --rm wallet-tools python tools/conciliar_cuenta.py --plan plans/x.json --dry-run
```

## MCP de Wallet

```powershell
opencode mcp add wallet --url https://mcp.wallet.budgetbakers.com
opencode mcp list
```

Si aparece `needs authentication`: en la interfaz, `/mcps` → `wallet` → sign in.
Los permisos (scopes) se activan en `web.budgetbakers.com/settings/mcp-server`.

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `WALLET_API_TOKEN no configurado` | Falta `.env` | Copia `.env.example` a `.env` |
| `401 Unauthorized` | Token REST caducado | Genera otro en la web de Wallet |
| MCP `needs authentication` | Falta OAuth | `/mcps` → sign in |
| `permission not granted` | Scope desactivado | Actívalo en la web y verifica con `get_client_profile` |
| `429 Too Many Requests` | Límite compartido MCP+REST | Parar y esperar; no reintentar en bucle |
| Cambio no visible tras escribir | Sync de hasta 15 min | Una relectura; si no aparece, esperar |
| Cuenta con 0 movimientos | Ventana de fechas mal puesta | Usar `--days 0` (histórico) |
| `UnicodeEncodeError` | Consola cp1252 | Usa el runner o exporta `PYTHONUTF8=1` |
| `Errno 11001` | DNS inestable | El cliente reintenta; en Docker usa `dns: 8.8.8.8` |
