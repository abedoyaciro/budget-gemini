# Informes

Plantillas de informe y reglas de coste. Intención, no nombres de tool.


> La zona **HECHOS** se regenera al correr `tools/bootstrap_rules.py`.
> La zona **CONVENCIONES** es tuya: nunca se sobrescribe.

<!-- HECHOS:START -->
**Inventario disponible ahora mismo**

| Dato | Valor |
|---|---|
| Registros leídos | 619 |
| Rango de fechas | 2024-01-02 → 2026-10-27 |
| Cuentas activas | 10 |
| Monedas presentes | COP, USD |
| Leído desde | `2000-01-01T00:00:00Z` |

---

## Plantillas (intención, no nombres de tool)

Los nombres reales de los tools están en `mcp_tools.md`. Aquí solo la intención.

### 1. Mensual por categoría
- Agrupar los registros del mes por categoría.
- Columnas: Categoría | Ingresos | Gastos | Neto | % del gasto total.
- Preferir una tool de **agregación** (una llamada). Si no hay, traer el mes con
  `limit` acotado y agregar localmente.
- Nunca traer el histórico completo para esto.

### 2. Saldo y últimos movimientos por cuenta
- Saldo: de la lista de cuentas (`currentBalance`).
- Últimos 10 movimientos: por cuenta y por fecha descendente.

### 3. Por etiqueta
- Total y desglose por categoría de los registros con esa etiqueta en la ventana.

### 4. Conciliación contra captura del banco
- Delegar en `tools/conciliar_cuenta.py` con un plan v1.
- Nunca reimplementar el matching en lenguaje natural.

### 5. Rendimiento de una cuenta (TEA mensual)
- `TEA = (1 + interes_mes / saldo_promedio_mes) ^ 12 − 1`
- Solo calcular en meses con saldo promedio > 10.000 COP.
- Meses con saldo ≈ 0 se marcan **no concluyente** (la tasa es ruido).
- Reportar la tabla mes | interés | saldo promedio | TEA, sin redondear a mano.

### 6. Presupuestos (si existen)
- Listar presupuestos con gastado, restante y % de avance del período actual.
- Marcar los que estén por encima del 100 %.

---

## Reglas de coste

- Agregar antes de traer: una agregación vale más que 200 registros.
- Tope por consulta: 50 registros salvo que el humano pida más.
- No volcar JSON crudo al chat: tablas.
- No sumar monedas distintas: reportar por moneda.
- Un total sin suma verificada no se publica: si la agregación no devuelve la
  suma, cae a `get_records` y suma localmente (P6 de la skill).
<!-- HECHOS:END -->

<!-- CONVENCIONES:START -->
## Mis preferencias de informe

- Formato de números: es-CO (2.580.398,47).
- Moneda de reporte: la de cada cuenta, sin conversiones implícitas.
- Período por defecto: mes calendario en curso.
- (añadir preferencias propias)
<!-- CONVENCIONES:END -->
