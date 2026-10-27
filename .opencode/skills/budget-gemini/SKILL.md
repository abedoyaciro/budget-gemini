---
name: budget-gemini
description: Operar el pipeline budget-gemini (extraer, analizar, aprender, enriquecer, dashboard) y conciliar cuentas contra capturas de banco con aprobación humana
license: MIT
compatibility: opencode
metadata:
  project: budget-gemini
  workspace: C:\Users\Anderson2\Documents\busqueda-laboral\data\proyectos\budget-gemini
---

# budget-gemini

Pipeline financiero personal: extrae de Wallet, analiza con Gemini,
aprende reglas contables y **concilia cuentas contra capturas del banco**.

Los intereses son **transacciones normales** (`income`), no ajustes de saldo.

## Runner

En Windows `make` no existe por defecto. Usa el runner nativo:

```powershell
.\scripts\budget.ps1 help
.\scripts\budget.ps1 snapshot -Days 0      # historico completo
.\scripts\budget.ps1 reconcile -Plan plans/plan_x.json -DryRun
.\scripts\budget.ps1 ajustar -Cuenta X -InitialBalance 2580398.47 -Delta 2580400.24 -Explicacion "..."
.\scripts\budget.ps1 test
```

Con `make` (detecta Docker y cae a modo nativo si el daemon no responde):

```bash
make doctor
make snapshot               # DAYS=90 por defecto; DAYS=0 = historico completo
make reconcile PLAN=plan.json [DRY=1] [YES=1]
make ajustar CUENTA=X INITIAL=N DELTA=N EXPLICACION="..." [DRY=1]
make test
```

El runner fuerza `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` y `PYTHONPATH=src`.
Sin eso, `print()` con emoji revienta con `UnicodeEncodeError` en cp1252 y una
extracción exitosa termina con exit code 1.

## Comandos

| Comando | Qué hace | Permiso |
|---------|----------|---------|
| `snapshot` / `budget:extract` | Extrae cuentas, categorías, etiquetas y registros | allow |
| `analyze` / `budget:analyze` | Diagnóstico con Gemini + memoria histórica | allow |
| `learn` / `budget:learn` | Detecta patrones y propone reglas contables | allow |
| `confirm` / `budget:confirm` | Confirma/rechaza/modifica reglas (interactivo) | ask |
| `enrich` / `budget:enrich` | Mejora notas/etiquetas/categorías en Wallet | ask |
| `dashboard` / `budget:dashboard` | Genera HTML con Chart.js + Tailwind | allow |
| `reconcile` / `budget:reconcile` | Concilia contra capturas: crea registros faltantes | ask |
| `ajustar` / `budget:ajustar` | Ajusta `initialBalance` (partida de apertura) | ask |
| `historial`, `reglas`, `logs` | Consultas de solo lectura | allow |

---

# Flujo: conciliar una cuenta con capturas

El humano adjunta capturas (app del banco, opcionalmente Wallet) y dice algo
como "concilia mi cuenta Pibank con estas capturas".

## Paso 1 — Leer las capturas con visión

Extrae **todos** los movimientos visibles y el saldo que muestra el banco.

Reglas de extracción obligatorias:

- **Números en formato es-CO**: `2.580.398,47` son dos millones quinientos
  ochenta mil, NO 2.58. El punto separa miles y la coma decimales.
  Registra los montos tal cual aparecen y deja que el parser los normalice.
- **Saldo corrido**: para cada fila anota el saldo que muestra la columna
  derecha. Sirve para validar movimiento por movimiento.
- **El saldo de referencia es el DEL BANCO**, no el de Wallet. Si solo tienes
  captura de Wallet, no puedes conciliar: pide la del banco.
- Anota la fecha de cada movimiento tal como la muestra el banco.

## Paso 2 — Leer Wallet

```powershell
.\scripts\budget.ps1 snapshot -Days 0 -Limit 0
```

`-Days 0` = histórico completo. **No uses ventanas cortas para conciliar**:
con `DAYS_BACK=90` una cuenta con 28 movimientos aparece vacía y se concluye
falsamente que "faltan 9 movimientos".

Lee `output/snapshot_wallet.json`: `cuentas[].balance.currentBalance` y
`cuentas[].registros`.

## Paso 3 — Construir el plan `plan.conciliacion.v1`

El esquema está en `schemas/plan.conciliacion.v1.json`. Ejemplo real en
`plans/plan_conciliacion_pibank.json`.

```json
{
  "version": "plan.conciliacion.v1",
  "cuenta": "Pibank",
  "moneda": "COP",
  "tolerancia": 0.01,
  "captura": {
    "fecha": "2026-10-26",
    "saldo_final": 2580398.47,
    "saldo_corrido": [
      { "fecha": "2026-10-01", "saldo": 2580398.47 }
    ],
    "movimientos": [
      { "fecha": "2026-10-01", "monto": 22038.81, "concepto": "Intereses",
        "category_system_id": "income__interest_dividends",
        "saldo_corrido": 2580398.47 }
    ]
  },
  "crear_registros": [
    { "fecha": "2026-10-01", "monto": 22038.81, "concepto": "Intereses",
      "category_system_id": "income__interest_dividends" }
  ],
  "transferencias": [
    { "fecha": "2026-07-06", "monto": 1400000.00, "concepto": "Pago Interbancario",
      "cuenta_contraparte": "Lulo", "crear_espejo": false }
  ]
}
```

Detalles:

- `captura.saldo_final` es **obligatorio**: es la referencia de verificación.
- `captura.movimientos` incluye también los que ya existen en Wallet.
- `crear_registros` solo los que faltan.
- `category_system_id` se resuelve a `categoryId` en runtime consultando
  `/categories`. Si no hay coincidencia exacta, el script **aborta**.
- Para intereses el systemId correcto es `income__interest_dividends`
  (NO `financial_expenses__interest_dividends`).
- `transferencias[].crear_espejo` es `false` por defecto: la captura suele
  mostrar un solo lado del par.

## Paso 4 — Dry-run y presentación

```powershell
.\scripts\budget.ps1 reconcile -Plan plans/plan_x.json -DryRun
```

El reporte muestra:

- **SALDO**: `currentBalance` de Wallet vs `captura.saldo_final`, con el delta
  y la tolerancia declarada.
- **SALDO CORRIDO**: replay movimiento por movimiento contra la captura.
  Detecta registros mal fechados y traslapes.
- **REGISTROS A CREAR** con su categoría.
- **YA EXISTEN EN WALLET** con la diferencia en días del match (±1 día es
  normal: el banco fecha 01/05 lo que Wallet registra 02/05).
- **TRANSFERENCIAS**: `YA PAREADA`, `ESPEJO YA EXISTE`,
  `REQUIERE CONFIRMACIÓN` o `CREARÁ ESPEJO`.

Presenta esto al humano y **espera aprobación**.

## Paso 5 — Aplicar

```powershell
.\scripts\budget.ps1 reconcile -Plan plans/plan_x.json -Yes
```

Solo con aprobación explícita del humano. Sin `-Yes` el script vuelve a
preguntar.

## Paso 6 — Verificar

El propio script re-verifica al final comparando `balance.currentBalance`
contra `captura.saldo_final`. No depende de la ventana de extracción.

Si el delta queda fuera de tolerancia, revisa: movimientos no visibles en las
capturas, registros duplicados o un residual anterior a la ventana
(ver `ajustar`).

---

# Regla de `initialBalance` (partida de apertura)

El residual de conciliación que se originó **antes** de la primera fecha
disponible no se puede explicar con registros. Inventar un registro ensucia
la contabilidad, así que se trata como **partida de apertura**.

Decisión documentada: se ajusta `initialBalance` y **no** se crea un asiento
"Ajuste de conciliación" en una categoría de sistema, porque ese asiento
contaminaría los reportes de ingresos y gastos del período.

Condiciones obligatorias (las tres):

1. **Delta cuantificado y explicado** — `-Delta` y `-Explicacion` (≥10 chars).
2. **Aprobación humana explícita** — pregunta en consola. No existe `--auto`.
3. **Registro en `output/enriquecimiento_log.json`**.

```powershell
# Propuesta
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 `
    -Delta 2580400.24 -Explicacion "Residual de apertura previo a la ventana" -DryRun

# Aplicar (pedirá confirmación)
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 `
    -Delta 2580400.24 -Explicacion "Residual de apertura previo a la ventana"
```

El script valida que `delta == initialBalance_objetivo - initialBalance_actual`.
Si no coincide, aborta.

Alternativa por plan: incluir el bloque `ajuste_apertura` con
`confirmar: true` dentro del plan de conciliación.

---

# Contratos de la API (verificados)

Centralizados en `src/wallet_client.py`. No hables HTTP directamente.

| Operación | Contrato real |
|-----------|---------------|
| `GET /records` | **Siempre** con `recordDate=gte.<ISO>`. Solo con `accountId` devuelve 200 con 0 registros. |
| Paginación | `limit` máx. 200 (más devuelve 400). Avanzar con `nextOffset`, no con `offset` suelto. |
| `POST /records` | Body = **array raíz**. `{"records": [...]}` devuelve 400 `cannot unmarshal object into Go value`. |
| `PATCH /records` | Body = **array raíz**, igual que POST. |
| Campos escribibles | `accountId`, `amount{value,currencyCode}`, `recordDate`, `note`, `categoryId`, `counterParty`, `labelIds`. |
| Campos rechazados (400) | `recordType`, `recordState`, `source`, `paymentType`. No se ignoran: la petición falla. |
| `PATCH /accounts` | Batch sobre la **colección**: `[{"id": ..., "initialBalance": ...}]`. `PATCH /accounts/{id}` da 404. |
| Transferencias | Shape de salida: `transfer: {type: "paired", transferId, mirrorRecord}`. No existe `pairingMode`. |
| `X-RateLimit-Remaining` | No siempre viene. Nunca condicionar el flujo a esa cabecera. |
| Límites de batch | OpenAPI declara 50 (create) y 10 (patch). **No verificados empíricamente**: se usan como cota conservadora. |

Reglas derivadas:

- **Nunca IDs de categoría literales.** Se resuelve por `systemId` en runtime.
- **Idempotencia**: match por fecha ±3 días + monto exacto + cuenta
  (+ categoría compatible si se especifica). Evita duplicados cuando el banco
  y Wallet fechan con ±1 día de diferencia.
- **Transferencias ya pareadas** se detectan por `transfer.type == "paired"`
  y no se vuelven a parear.
- **No crear el espejo** sin `crear_espejo: true` y sin verificar antes que
  no exista ya en la cuenta contraparte.
- **Visión**: parsing es-CO explícito (`2.580.398,47` → `2580398.47`).

---

# Diagnóstico del pipeline

- `DAYS_BACK=90` recorta la historia. Para conciliar usa histórico completo.
- `DAYS_BACK=0` **no** omite el filtro: usa un piso de fecha (`2000-01-01`).
  Sin `recordDate` la API devuelve un subset (no todo).
- `RECORDS_LIMIT`/`-Limit` es un tope total; `0` = sin tope. La paginación se
  completa y luego se trunca: nunca se corta a mitad.
- `_get_paginated` reintenta con backoff y **falla fuerte**. Antes hacía
  `break` silencioso y devolvía datos parciales como si fueran completos.
- Tasas históricas: `api.frankfurter.dev/v1` con fallback a
  `api.frankfurter.app`. Las fechas sin tasa se omiten en silencio.

---

# Archivos

| Ruta | Contenido |
|------|-----------|
| `schemas/plan.conciliacion.v1.json` | Esquema del plan |
| `plans/` | Planes de conciliación |
| `output/snapshot_wallet.json` | Último snapshot (cuentas, registros, stats) |
| `output/enriquecimiento_log.json` | Auditoría de toda escritura en Wallet |
| `src/wallet_client.py` | Cliente API con todos los contratos |
| `src/plan_conciliacion.py` | Validación del plan y parsing es-CO |
| `src/conciliar_cuenta.py` | Conciliación |
| `src/ajustar_saldo_cuenta.py` | Ajuste de partida de apertura |
| `scripts/budget.ps1` | Runner nativo Windows |

Nunca leas `.env` directamente.

---

# Prompts que activan cada flujo

| Prompt | Comando |
|--------|---------|
| "Concilia mi cuenta Pibank con estas capturas" | `reconcile` |
| "¿Cuadra Nequi con este screenshot?" | `reconcile` |
| "Ajusta el saldo de apertura de Lulo: residual de X" | `ajustar` |
| "Extrae datos de Wallet y dime los saldos" | `snapshot` |
| "Genera el diagnóstico financiero" | `analyze` |
| "Aprende reglas de los últimos gastos" | `learn` |
| "Mejora notas y categorías" | `enrich` |
| "Genera el dashboard" | `dashboard` |
