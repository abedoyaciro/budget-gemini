# Análisis Financiero Inteligente — Gemini AI + BudgetBakers Wallet

> **WIP** — Proyecto personal en evolución activa.
> Plan: evolucionar hacia un Cloud Support Lab (Docker + CI/CD + tests automatizados).

Sistema de análisis financiero personal que integra **Google Gemini AI** con la
**API REST de BudgetBakers Wallet**. Extrae transacciones, mantiene un histórico
de snapshots con detección de cambios, aprende reglas contables automáticamente,
genera diagnósticos con memoria y **concilia cuentas contra capturas del banco**.

---

## Inicio rápido

### Windows (sin Docker, sin make)

```powershell
.\scripts\budget.ps1 help
.\scripts\budget.ps1 snapshot -Days 0
.\scripts\budget.ps1 analyze
```

### Con Docker / make

```bash
make doctor          # detecta Docker; si no responde, usa modo nativo
make snapshot DAYS=0
make analyze
make test
```

---

## Arquitectura

```
budget-gemini/
├── src/
│   ├── wallet_client.py            # Cliente API: única fuente de contratos
│   ├── plan_conciliacion.py        # Esquema v1, parsing es-CO, matching
│   ├── conciliar_cuenta.py         # Conciliación contra capturas del banco
│   ├── ajustar_saldo_cuenta.py     # Partida de apertura (initialBalance)
│   ├── extractor_wallet.py         # Extracción paginada con retry
│   ├── gestor_snapshots.py         # Histórico + detección de cambios
│   ├── analizador_finanzas.py      # Diagnóstico con memoria
│   ├── aprendizaje_reglas.py       # Detección de patrones
│   ├── confirmador_reglas.py       # Confirmación interactiva
│   ├── asistente_enriquecimiento.py# Notas/etiquetas/categorías
│   ├── generar_dashboard.py        # HTML con Chart.js + Tailwind
│   └── logging_config.py
├── schemas/
│   └── plan.conciliacion.v1.json   # Contrato del plan de conciliación
├── plans/                          # Planes de conciliación por cuenta
├── scripts/
│   └── budget.ps1                  # Runner nativo Windows
├── tests/                          # 54 tests (pytest)
├── docs/
│   ├── commands.md
│   ├── budgetbakers.openapi.json
│   ├── interactions.openapi.json
│   ├── docker-guide.md
│   └── docker-compose-guide.md
├── output/                         # Snapshots, diagnósticos, logs, dashboard
├── Makefile                        # Docker con fallback nativo
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Conciliación de cuentas

Flujo genérico, válido para cualquier cuenta:

1. El humano adjunta capturas del banco (y opcionalmente de Wallet).
2. El agente las lee con visión y extrae movimientos + saldo corrido.
3. Se construye un `plan.conciliacion.v1` (ver `schemas/`).
4. `reconcile --dry-run` muestra el reporte: saldo, saldo corrido, faltantes,
   ya existentes y transferencias.
5. Tras aprobación humana se aplica con `--yes`.
6. El propio script verifica que `currentBalance` cuadre con la captura.

```powershell
.\scripts\budget.ps1 snapshot -Days 0 -Limit 0
.\scripts\budget.ps1 reconcile -Plan plans/plan_conciliacion_pibank.json -DryRun
.\scripts\budget.ps1 reconcile -Plan plans/plan_conciliacion_pibank.json -Yes
```

**Los intereses son transacciones normales** (`income`, categoría
`income__interest_dividends`). No se suman a `initialBalance`.

### Contratos de la API (verificados)

| Operación | Contrato real |
|-----------|---------------|
| `GET /records` | Siempre con `recordDate=gte.<ISO>`; solo con `accountId` devuelve 0 registros |
| Paginación | `limit` ≤ 200; avanzar con `nextOffset` |
| `POST` / `PATCH /records` | Body = array raíz (`{"records": [...]}` → 400) |
| Campos escribibles | `accountId`, `amount{value,currencyCode}`, `recordDate`, `note`, `categoryId`, `counterParty`, `labelIds` |
| Campos rechazados (400) | `recordType`, `recordState`, `source`, `paymentType` |
| `PATCH /accounts` | Batch sobre la colección; `PATCH /accounts/{id}` → 404 |
| Transferencias | Salida: `transfer: {type: "paired", transferId, mirrorRecord}`; no existe `pairingMode` |
| Categorías | Se resuelven por `systemId` en runtime; aborta si no hay match exacto |

### Regla de `initialBalance`

El residual anterior a la ventana de conciliación se corrige como **partida de
apertura**, no como asiento de "Ajuste de conciliación" (ese ensuciaría los
reportes de ingresos y gastos). Requiere delta cuantificado, explicación,
aprobación humana explícita y registro en `output/enriquecimiento_log.json`.

```powershell
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 `
    -Delta 2580400.24 -Explicacion "Residual de apertura pre-ventana"
```

---

## Variables de entorno

Crea `.env` en la raíz (copia desde `.env.example`):

```env
GEMINI_API_KEY=tu_api_key
WALLET_API_TOKEN=tu_token

# Extracción
DAYS_BACK=90          # 0 = histórico completo (usa piso de fecha)
RECORDS_LIMIT=0       # 0 = sin tope; pagina completo y luego trunca

# Modelos Gemini
GEMINI_MODEL_ANALIZADOR=gemini-3.1-flash-lite
GEMINI_MODEL_APRENDIZAJE=gemini-3.1-flash-lite
GEMINI_MODEL_CONFIRMADOR=gemini-3.1-flash-lite
GEMINI_TEMPERATURA=0.3
```

`.env` está en `.gitignore`.

---

## Módulos

### `wallet_client.py`

Única fuente de verdad para HTTP. Encapsula contratos, resuelve categorías por
`systemId`, pagina con `nextOffset`, reintenta con backoff y **falla fuerte**
(nunca devuelve datos parciales como si fueran completos).

### `conciliar_cuenta.py`

Valida el plan, compara contra Wallet (fecha ±3 días + monto exacto), crea solo
los faltantes, analiza transferencias sin duplicar pares, valida el saldo corrido
movimiento por movimiento y verifica el resultado contra el saldo de la captura.

### `ajustar_saldo_cuenta.py`

Ajuste de partida de apertura. Sin `--auto`: la aprobación humana es obligatoria.

### `extractor_wallet.py`

Extracción paginada. `DAYS_BACK=0` usa un piso de fecha explícito (`2000-01-01`),
porque sin `recordDate` la API devuelve un subset. `RECORDS_LIMIT` es tope total:
se pagina completo y luego se trunca.

### `gestor_snapshots.py`

Histórico en `output/snapshots/`. La metadata del envelope y del snapshot
coinciden (`tipo_extraccion`, `ventana_dias`).

---

## Tests

```powershell
.\scripts\budget.ps1 test
# o
make test
# o
PYTHONUTF8=1 PYTHONPATH=src python -m pytest tests -q
```

54 tests cubriendo: parsing es-CO, tolerancia de fechas, validación del plan,
contratos de escritura, shape de transferencias, paginación y resolución de
categorías en runtime.

---

## Documentación

- [`docs/commands.md`](docs/commands.md) — comandos y solución de problemas
- [`docs/budgetbakers.openapi.json`](docs/budgetbakers.openapi.json) — API Wallet
- [`docs/interactions.openapi.json`](docs/interactions.openapi.json) — Gemini Interactions
- [`docs/docker-guide.md`](docs/docker-guide.md)
- [`docs/docker-compose-guide.md`](docs/docker-compose-guide.md)

---

## Licencia

Proyecto privado

## Autor

Anderson Bedoya Ciro
