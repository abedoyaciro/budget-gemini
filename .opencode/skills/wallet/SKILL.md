---
name: wallet
description: Operar Wallet (BudgetBakers) vía MCP en lenguaje natural — registrar gastos e ingresos, consultar saldos, generar informes, conciliar contra capturas del banco y corregir movimientos, usando la Knowledge Base local en rules/ y pidiendo aprobación antes de escribir
---

# Skill: wallet

Opera Wallet con el MCP oficial. La Knowledge Base (`rules/`) dice **cómo piensa
el usuario**; este skill dice **qué pasos seguir**.

## Arranque de sesión (solo la primera vez por conversación)

1. `get_client_profile` → guarda `grantedScopes`, moneda base y `syncState`.
   - Si `syncState` es `"syncing"`: avisa y espera 1-2 min.
   - Si faltan scopes de escritura: dilo antes de intentar escribir.
2. Lee **solo** los archivos de `rules/` que necesites para la petición.
   No los cargues todos por defecto.

## Permisos

**Estado verificado (2026-10-27):** todos los scopes concedidos, incluidos
`accounts.delete`, `budgets.delete`, `categories.delete`, `labels.delete` y
`records.delete`. La cuenta se autorizó con el máximo permiso posible.

| Acción | Permiso |
|---|---|
| `get_*` (lectura) | libre |
| `create_records` | confirmación del usuario |
| `patch_records` | confirmación + mostrar antes/después |
| `delete_documents` de **records** | confirmación explícita + `get_references` antes |
| `delete_documents` de **cuentas, categorías, etiquetas, presupuestos** | **PROHIBIDO sin doble confirmación escrita y `get_references` con referencias mostradas** |
| `create_account` / `create_budget` / `create_category` / `create_label` | solo si lo piden; nunca por iniciativa |
| `patch_accounts` (`initialBalance`) | doble confirmación, vía procedimiento P5 |

### Regla de mínimo privilegio

Aunque la cuenta tenga todos los scopes, el agente **no los usa todos**:

- `delete_documents` se limita a `records` (corregir duplicados/errores).
- Nunca borra una cuenta, categoría, etiqueta o presupuesto sin que el usuario
  escriba explícitamente "borra <nombre>". Si hay referencias, se detiene y las
  muestra; no reasigna por su cuenta.
- Antes de cualquier borrado: `get_references` y mostrar qué lo usa.
- Si el usuario quiere reducir riesgo: en `web.budgetbakers.com/settings/mcp-server`
  → Manage Permissions → apagar **Delete** en Accounts, Budgets, Categories y
  Labels. Basta con Records: Read/Create/Update.

---

## P1 — Registrar un gasto o ingreso

Entrada típica: *"Gasté 45.300 en servicentro con la de Nequi"*,
*"Me llegaron 20.381 de intereses a Pibank"*.

1. **Cuenta**: busca en `rules/cuentas.md` por nombre.
   - 1 coincidencia → sigue. 0 o >1 → **pregunta**.
2. **Categoría**: busca el término en `rules/categorias.md`.
   - Usa la tabla "Términos de nota → categoría dominante".
   - Consistencia ≥ 90 % → proponla. < 90 % o sin término → **pregunta**.
   - Obtén el `id` real con `get_categories` usando el `systemId`.
     **Nunca copies un `categoryId` de un archivo.**
3. **Etiquetas**: revisa `rules/etiquetas.md` ("cuándo la uso").
   Añade solo las que encajen con su convención escrita.
4. **Signo**: gasto negativo, ingreso positivo.
5. **Fecha**: hoy en `America/Bogota`, enviada como `T12:00:00-05:00`.
   Si él dice otra fecha, usa esa.
6. **Idempotencia** (obligatorio): `get_records` de esa cuenta, ventana ±5 días,
   mismo monto. Si ya existe algo equivalente (fecha ±3 días, monto exacto),
   **no crees**: muestra el existente y pregunta si quiere otro igual.
7. **Resumen + confirmación**, con este formato:

   ```
   Registraré:
   Cuenta : Nequi (COP)
   Monto  : -45.300,00 COP
   Fecha  : 2026-10-26
   Categoría: Fuel (vehicle__fuel)
   Etiquetas: Moto
   Nota   : Servicentro
   ¿Confirmas? (sí / no / cambia X)
   ```

8. Con el "sí": `create_records` con **array** de registros (máx. 50).
9. Relee `get_accounts` (una vez) y reporta el nuevo `currentBalance`.
   Si no cambió, es sync (hasta 15 min): dilo, no repitas la escritura.
10. Si la escritura falló: lee `rules/mcp_tools.md` → tabla de errores.
    Tras un timeout, **relee antes de reintentar**.

## P2 — Consultar saldo o últimos movimientos

1. `get_accounts` → filtra por nombre.
2. Saldo: `balance.currentBalance`, formato es-CO + moneda de la cuenta.
3. Movimientos: `get_records` con `accountId`, ventana (30 días por defecto) y
   `limit` ≤ 50 → tabla `fecha | monto | categoría | nota`.
4. Si tiene varias cuentas y pide "cuánto tengo": tabla por cuenta + total
   **por moneda** (nunca una suma mezclada).

## P3 — Informe

Lee la plantilla correspondiente en `rules/informes.md`.

- **Mensual por categoría** → `get_records_aggregation` agrupando por categoría
  en el mes. Columnas: Categoría | Ingresos | Gastos | Neto | % del gasto.
- **Por etiqueta** → filtrar por etiqueta en la ventana y agregar.
- **Presupuestos** → `get_budgets`; marca los que pasen del 100 %.
- **Rendimiento** → TEA mensual =
  `(1 + interés_mes / saldo_promedio_mes)^12 − 1`, solo con saldo promedio
  > 10.000 COP. Meses con saldo ≈ 0: **no concluyente**.
- Sin tool de agregación adecuada: trae el período con `limit` acotado y agrega
  tú, indicando cuántos registros usaste.

Nunca vuelques JSON crudo. Tabla + 2-3 frases de lectura.

## P4 — Conciliar contra captura del banco

Requiere captura del **banco** (no de Wallet) con el saldo visible.

1. Extrae de la captura: movimientos (fecha, monto, concepto) y **saldo final**.
   - Números es-CO: `2.580.398,47` es dos millones quinientos ochenta mil.
2. Construye el plan `plan.conciliacion.v1`
   (esquema: `schemas/plan.conciliacion.v1.json`, ejemplo: `plans/`).
3. Ejecuta el modo simulación:

   ```powershell
   .\scripts\budget.ps1 reconcile -Plan plans\plan_<cuenta>.json -DryRun
   ```

4. Presenta el reporte al usuario: saldo Wallet vs captura, saldo corrido,
   faltantes, ya existentes y transferencias.
5. **Espera aprobación** y solo entonces:

   ```powershell
   .\scripts\budget.ps1 reconcile -Plan plans\plan_<cuenta>.json -Yes
   ```

No reimplementes el matching en lenguaje natural: el script hace fecha ±3 días +
monto exacto y valida el saldo corrido. No crees espejos de transferencia salvo
`crear_espejo: true` **y** confirmación.

## P5 — Ajustar partida de apertura (`initialBalance`)

Solo para un residual anterior a la primera fecha con datos.

```powershell
# 1) Propuesta (no escribe)
.\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2.580.398,47 `
    -Delta 2.580.400,24 -Explicacion "Residual de apertura previo a la ventana" -DryRun
```

Muestra el delta al usuario y pide **doble confirmación** antes de ejecutarlo sin
`-DryRun`. El script exige explicación ≥10 caracteres y valida el delta; sin
aprobación humana no aplica nada.

## P6 — Corregir un movimiento

1. Localízalo con `get_records` (cuenta + ventana + texto).
2. Muestra `antes → después` campo por campo.
3. Con aprobación: `patch_records` (máx. 20).
   - Etiquetas: reemplazo total o add/remove incremental, según lo pedido.
   - Si es una transferencia y hay que cambiar la categoría:
     `$clear: ["transfer"]` primero, y avisa de que se rompe el pareo.
4. Relee y confirma el resultado.

## Errores

Tabla completa en `rules/mcp_tools.md`. Lo esencial:

- `permission not granted` → falta scope en la web; no reintentes.
- `429` → paras y esperas; insistir puede costar el token.
- `invalid params` → revisa el campo que indica el mensaje.
- Cuenta con `isBankSync: true` → solo categoría, etiquetas, nota y contraparte.

## Coste

- Arranque: 1 llamada (`get_client_profile`).
- Lectura de KB: solo el archivo necesario.
- Por registro: 3-4 llamadas. Por informe: 1-3. Por conciliación: el script.
- Nada de bucles de sondeo ni volcados largos.
