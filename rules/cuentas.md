# Cuentas

Qué cuentas existen, en qué moneda y cuánto tienen. Generado desde Wallet.


> La zona **HECHOS** se regenera al correr `tools/bootstrap_rules.py`.
> La zona **CONVENCIONES** es tuya: nunca se sobrescribe.

<!-- HECHOS:START -->
| Cuenta | id | Moneda | Tipo | Archivada | Sync banco | Registros | Primer mov. | Último mov. | Saldo actual |
|---|---|---|---|---|---|---|---|---|---|
| Binance | `0b301918…` | USD | Investment | no | no | 9 | 2024-11-08 | 2026-10-27 | 7,80 |
| Efectivo | `e0b128f4…` | COP | Cash | no | no | 264 | 2024-01-02 | 2026-07-06 | 30.000,00 |
| Lulo | `1a51ce53…` | COP | SavingAccount | no | no | 117 | 2024-09-02 | 2026-10-03 | 186.532,83 |
| Lulo X | `43f59023…` | USD | SavingAccount | no | no | 1 | 2026-06-10 | 2026-06-10 | 0,00 |
| Nequi | `7723a27d…` | COP | SavingAccount | no | no | 122 | 2024-08-06 | 2026-10-23 | 33.042,18 |
| Nu | `04ae14e9…` | COP | SavingAccount | no | no | 6 | 2024-09-02 | 2025-02-05 | 17,50 |
| Pibank | `67549ec7…` | COP | SavingAccount | no | no | 28 | 2024-07-01 | 2026-10-01 | 2.580.398,47 |
| Trii - Fondo Acciones Dinámico | `d1d2f324…` | COP | Investment | no | no | 14 | 2024-12-03 | 2026-10-27 | 474.692,34 |
| Tyba | `540a9aba…` | COP | Investment | no | no | 15 | 2024-11-08 | 2026-10-27 | 953.149,00 |
| Ualá | `11942301…` | COP | SavingAccount | no | no | 43 | 2024-09-01 | 2026-10-27 | 70,94 |

**Total por moneda (no se suman entre sí):** 4.257.903,26 COP · 7,80 USD


**Sync banco = sí**: la entidad bancaria fija monto, fecha y estado. Solo se pueden editar categoría, etiquetas, nota y contraparte; no se pueden crear ni borrar movimientos en esas cuentas.
<!-- HECHOS:END -->

<!-- CONVENCIONES:START -->
## Mis convenciones

**Yo nombro la cuenta explícitamente.** El agente no debe adivinar por el
contexto ni por el historial. Si en el mensaje no aparece una cuenta que exista
en la tabla de hechos, el agente pregunta y no registra nada.

| Cuenta | Rol (para qué la uso) | ¿Por defecto para gastos? |
|---|---|---|
| | | |

### Reglas
- Cuenta nombrada = cuenta usada. Aunque el historial sugiera otra, manda lo que
  yo escribo.
- Nombre parcial que coincide con más de una cuenta (`Lulo` / `Lulo X`) →
  pregunta, no elijas por parecido.
- Si digo "la de siempre" o "la del sueldo" sin nombrarla, el agente debe tener
  esa equivalencia escrita aquí; si no está, pregunta.
- Cuenta en USD (`Binance`, `Lulo X`) → nunca convertir a COP sin que yo lo pida.
<!-- CONVENCIONES:END -->
