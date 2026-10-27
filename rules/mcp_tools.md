# Tools del MCP de Wallet — inventario real

> Fuente: documentación oficial `mcp.wallet.budgetbakers.com/docs` (consultada 2026-10-26).
> **Este archivo es la única lista autorizada de nombres de tools.**
> Si el servidor cambia, se actualiza aquí; el agente nunca improvisa nombres.

- **URL:** `https://mcp.wallet.budgetbakers.com`
- **Transporte:** MCP sobre Streamable HTTP
- **Auth:** OAuth 2.0 + PKCE (o token manual en `web.budgetbakers.com/settings/mcp-server`)
- **Total:** 20 tools

## Lectura (9)

| Tool | Para qué |
|---|---|
| `get_client_profile` | Permisos (`grantedScopes`), estado de sync, moneda base. **Primera llamada de cada sesión** |
| `get_accounts` | Cuentas con `balance.currentBalance`, `isBankSync`, `recordStats`. Nº de cuenta enmascarado salvo `revealBankAccountNumber: true` |
| `get_categories` | ~90 categorías base + personalizadas, con `systemId` y jerarquía |
| `get_labels` | Etiquetas (hashtags) |
| `get_records` | Movimientos con filtros (fecha, cuenta, categoría, etiqueta, texto, monto, estado) y paginación |
| `get_records_aggregation` | **Preferida para informes**: agrupa (categoría, mes, cuenta…), calcula `sum/avg/min/max/median/absSum` y convierte moneda con tasas históricas |
| `get_budgets` | Presupuestos con gastado/restante del período |
| `get_entity` | Órdenes permanentes, metas, reglas de registro |
| `get_references` | Qué referencia a una entidad. **Obligatoria antes de borrar** |

## Creación (5)

| Tool | Límite | Notas |
|---|---|---|
| `create_records` | **50 por petición** | Soporta transferencias pareadas (2 registros enlazados), no pareadas y multimoneda. `pairingMode: "existing"` enlaza a un registro existente |
| `create_account` | 1 | Tipos: General, Cash, CurrentAccount, SavingAccount, Insurance |
| `create_budget` | 1 | Semanal, mensual, anual o rango |
| `create_category` | 1 | Derivada de una categoría base |
| `create_label` | 1 | Etiqueta nueva |

## Actualización (5)

| Tool | Límite | Notas |
|---|---|---|
| `patch_records` | **20 por petición** | Categoría, etiquetas (reemplazo o add/remove incremental), nota, contraparte, estado, fecha, monto, lugar, cuenta. `$clear` para vaciar campos o **cancelar el estado de transferencia** |
| `patch_accounts` | **20** | Nombre, color, `initialBalance`, archivar, número de cuenta. **La moneda es inmutable** |
| `patch_budgets` | 20 | Límites, nombre, filtros, cerrar/reabrir |
| `patch_categories` | 20 | Renombrar, color, cardinalidad |
| `patch_labels` | 20 | Nombre, color, archivar |

## Borrado (1)

| Tool | Límite | Notas |
|---|---|---|
| `delete_documents` | **20 por petición** | Registros, cuentas, presupuestos, categorías, etiquetas, órdenes, reglas. Aplica integridad referencial: si hay referencias, falla. Usar `get_references` antes |

---

## Contratos que hay que respetar

1. **Categoría por `systemId`, nunca por ID copiado.** Se obtiene con `get_categories` y se usa el `id` que devuelve.
2. **Batches no son atómicos.** La respuesta trae `summary` y `results[]` por ítem.
   Reintentar **solo** los ítems con `success: false`.
3. **Transferencias pareadas:** `summary.total` cuenta filas de salida, no entradas.
   Los espejos vienen con `isMirror: true` y comparten `inputIndex` con su raíz.
4. **Cuentas con sync bancario** (`isBankSync: true`): solo se pueden parchear
   categoría, etiquetas, nota y contraparte; monto, fecha y estado los fija el banco.
   En las cuentas de este usuario `isBankSync` es `false` en todas (ver `cuentas.md`).
5. **Categoría de una transferencia bloqueada:** para cambiarla, primero
   `patch_records` con `$clear: ["transfer"]`.
6. **`amount` es número**, no string. `recordDate` ISO 8601. `accountId` UUID.
7. **`bankAccountNumber` no se reenvía enmascarado** (`****1234`) al crear o parchear.

## Rate limit y uso razonable

- Doble cubeta (ráfaga + sostenido). Estado en `_meta.rateLimit` de cada respuesta.
- La REST API y el MCP **comparten presupuesto**.
- `429` significa **bajar el ritmo**, no reintentar. Un cliente que insiste puede
  perder el token.
- Nunca sondear en bucle. Una verificación por escritura como máximo.

## Sync

Los cambios de la app/REST pueden tardar **hasta 15 minutos** en verse por MCP.
Tras escribir, una sola relectura; si no aparece, informar y esperar, no insistir.

---

## Errores y qué hacer

| Mensaje | Causa | Acción |
|---|---|---|
| `<permiso> permission not granted for <entidad>` | Scope desactivado en la web | `web.budgetbakers.com/settings/mcp-server` → activar → verificar con `get_client_profile` |
| `invalid params` | Payload no cumple el esquema | Revisar el campo concreto del mensaje (monto número, fecha ISO, UUID) |
| `category cannot be changed on transfer records` | El registro es una transferencia | `$clear: ["transfer"]` primero |
| `... bank-synced accounts can only have category, labelIds, note, counterParty patched` | Cuenta con sync bancario | Solo esos campos |
| `cannot move record to account with different currency` | Cambio de cuenta con otra moneda | Borrar y recrear en la cuenta destino |
| `<entidad> has active references: N record(s)` | Integridad referencial | `get_references` → reasignar → borrar |
| `429 Too Many Requests` | Límite | Parar, esperar, reducir llamadas |

---

## Permisos (capa Wallet, siempre presente)

Se configuran en `web.budgetbakers.com/settings/mcp-server`. Por defecto solo lectura.

| Scope | Necesario para este proyecto |
|---|---|
| read (records, accounts, categories, labels, budgets) | **Sí** |
| create `records` | **Sí** |
| update `records` | **Sí** |
| delete `records` | Sí (para corregir errores) |
| create/update accounts, budgets, categories, labels | Solo si se piden explícitamente |

Verificación: `get_client_profile` → `grantedScopes` debe incluir los scopes marcados.
