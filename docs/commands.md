# Comandos — budget-gemini

## Runner nativo (Windows, sin Docker)

`make` no viene instalado por defecto en Windows y el Makefile dependía de
Docker. Usa el runner en PowerShell:

```powershell
.\scripts\budget.ps1 help
```

| Comando | Descripción |
|---------|-------------|
| `budget.ps1 snapshot [-Days 90] [-Limit 0]` | Extrae datos de Wallet |
| `budget.ps1 analyze` | Diagnóstico con Gemini |
| `budget.ps1 learn` | Aprende reglas contables |
| `budget.ps1 enrich` | Enriquece notas y etiquetas |
| `budget.ps1 confirm` | Confirma reglas (interactivo) |
| `budget.ps1 dashboard` | Genera `output/dashboard.html` |
| `budget.ps1 historial` | Historial de snapshots |
| `budget.ps1 reglas` | Reglas aprendidas |
| `budget.ps1 pipeline` | snapshot + analyze |
| `budget.ps1 full` | snapshot + analyze + learn + enrich |
| `budget.ps1 reconcile -Plan plan.json [-DryRun] [-Yes]` | Concilia una cuenta |
| `budget.ps1 ajustar -Cuenta X -InitialBalance N -Delta N -Explicacion "..." [-DryRun]` | Ajuste de partida de apertura |
| `budget.ps1 test` | Suite de tests |

El runner aplica automáticamente:

```
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
PYTHONPATH=src
```

Sin eso, `print()` con emoji revienta con `UnicodeEncodeError` en cp1252 y una
extracción exitosa termina con exit code 1.

## Make (Docker o nativo)

`make` detecta el daemon de Docker. Si responde, ejecuta en contenedor; si no,
cae a modo nativo con `PYTHONPATH=src`.

```bash
make doctor        # comprueba entorno y modo activo
make snapshot      # DAYS=90
make snapshot DAYS=0 LIMIT=0    # histórico completo, sin tope
make analyze
make learn
make enrich
make confirm
make dashboard
make pipeline
make full
make reconcile PLAN=plan.json DRY=1
make reconcile PLAN=plan.json YES=1
make ajustar CUENTA=Pibank INITIAL=2580398.47 DELTA=2580400.24 \
             EXPLICACION="Residual de apertura pre-ventana" DRY=1
make historial
make reglas
make logs
make test
make clean
```

## Variables

| Variable | Significado |
|----------|-------------|
| `DAYS` / `DAYS_BACK` | Días hacia atrás. `0` = histórico completo (usa piso de fecha, **no** omite `recordDate`) |
| `LIMIT` / `RECORDS_LIMIT` | Tope **total** de registros. `0` = sin tope |
| `MAX_REG` | Registros enviados al aprendizaje de reglas |
| `TEMPERATURA` | Temperatura de Gemini |
| `PLAN` | Ruta del plan de conciliación |
| `DRY` / `DRY=1` | Solo reporta, no escribe |
| `YES` / `YES=1` | No volver a pedir confirmación |

## Conciliación

```powershell
# 1. Histórico completo (necesario para conciliar)
.\scripts\budget.ps1 snapshot -Days 0 -Limit 0

# 2. Construir el plan (esquema: schemas/plan.conciliacion.v1.json)
#    Ejemplo real: plans/plan_conciliacion_pibank.json

# 3. Ver el reporte sin escribir nada
.\scripts\budget.ps1 reconcile -Plan plans/plan_conciliacion_pibank.json -DryRun

# 4. Aplicar tras aprobación humana
.\scripts\budget.ps1 reconcile -Plan plans/plan_conciliacion_pibank.json -Yes
```

## Ajuste de partida de apertura

Solo para residuales originados **antes** de la ventana de conciliación.

```powershell
# Propuesta
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 `
    -Delta 2580400.24 -Explicacion "Residual de apertura pre-ventana" -DryRun

# Aplicar (pide confirmación; no existe --auto)
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 `
    -Delta 2580400.24 -Explicacion "Residual de apertura pre-ventana"
```

## Docker

```bash
docker compose run --rm budget-pipeline
docker compose run --rm budget-pipeline --full
docker compose up budget-confirmar-reglas    # interactivo (requiere TTY)
```

## Solución de problemas

| Error | Causa | Solución |
|-------|-------|----------|
| `WALLET_API_TOKEN no configurado` | Falta `.env` | Copia `.env.example` a `.env` |
| `401 Unauthorized` | Token expirado | Genera uno nuevo en BudgetBakers |
| `Errno 11001` / `10054` | DNS inestable | El cliente reintenta con backoff; si persiste, usa `--dns 8.8.8.8` en Docker |
| `UnicodeEncodeError` | Consola cp1252 | Usa el runner (`budget.ps1`) o exporta `PYTHONUTF8=1` |
| Cuenta con 0 registros | Ventana corta (`DAYS_BACK=90`) | Usa `DAYS=0` |
| `JSON inválido` en plan | Falta `version` o campo desconocido | Revisa `schemas/plan.conciliacion.v1.json` |
