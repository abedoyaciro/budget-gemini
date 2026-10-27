#!/usr/bin/env python3
"""
Ajuste de initialBalance como partida de apertura
=================================================

Corrige el residual de conciliación que se originó ANTES de la ventana de
extracción y que, por tanto, no se puede explicar con registros.

Regla elegida y documentada:
  Se usa la PARTIDA DE APERTURA (initialBalance) y NO un asiento de
  "Ajuste de conciliación" en una categoría de sistema, porque ese asiento
  ensuciaría los reportes de ingresos y gastos del período.

Condiciones obligatorias (las tres):
  (a) delta cuantificado y explicado  -> flags --delta y --explicacion
  (b) aprobación humana explícita      -> pregunta en consola, sin --auto
  (c) registro en enriquecimiento_log.json

No es para registrar intereses: los intereses son transacciones normales
(income) y se crean con `conciliar_cuenta.py`.

Uso:
    python -m src.ajustar_saldo_cuenta \\
        --cuenta "Pibank" \\
        --initial-balance 2580398.47 \\
        --delta 2580400.24 \\
        --explicacion "Residual de apertura anterior a la ventana de conciliación"

    python -m src.ajustar_saldo_cuenta --plan plan.json   # usa ajuste_apertura del plan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from plan_conciliacion import PlanValidationError, load_plan, parse_es_co_number
from wallet_client import WalletAPIError, WalletClient

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

OUTPUT_DIR = "output"
LOG_PATH = os.path.join(OUTPUT_DIR, "enriquecimiento_log.json")
MIN_EXPLICACION = 10


# ─────────────────────────────────────────────────────────────────────────────
# Formato
# ─────────────────────────────────────────────────────────────────────────────

def fmt(valor: Optional[float], moneda: str = "COP") -> str:
    """
    Formato es-CO: separador de miles '.' y decimal ','.

    2580398.47      -> '2.580.398,47 COP'
    -1.77           -> '-1,77 COP'
    2608906.12      -> '2.608.906,12 COP'
    """
    if valor is None:
        return "—"
    signo = "-" if valor < 0 else ""
    cuerpo = f"{abs(valor):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{cuerpo} {moneda}"


# ─────────────────────────────────────────────────────────────────────────────
# Auditoría
# ─────────────────────────────────────────────────────────────────────────────

def registrar(accion: str, detalle: Dict[str, Any], resultado: Any = None, error: str = "") -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log: Dict[str, Any] = {"sesiones": []}
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                log = {"sesiones": data}
            elif isinstance(data, dict):
                data.setdefault("sesiones", [])
                log = data
        except Exception:
            log = {"sesiones": []}

    log["sesiones"].append(
        {
            "timestamp": datetime.now().astimezone().isoformat(),
            "accion": accion,
            "detalle": detalle,
            "resultado_api": resultado or {},
            "exito": not error,
            "error": error,
        }
    )
    log["ultima_sesion"] = log["sesiones"][-1]["timestamp"]

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print(f"   [LOG] Registrado en {LOG_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def _leer_confirmacion(pregunta: str) -> bool:
    """Aprobación humana explícita. Sin TTY se asume NO."""
    try:
        return input(pregunta).strip().upper() == "S"
    except EOFError:
        print("\n   [INFO] Sin terminal interactivo: aprobación no otorgada")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ajuste de initialBalance como partida de apertura (requiere aprobación humana)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
El delta se valida contra (initialBalance objetivo - initialBalance actual).
Debe declararse explícitamente para forzar que el cambio esté cuantificado.

Ejemplos:
  python -m src.ajustar_saldo_cuenta --cuenta Pibank \\
      --initial-balance 2580398.47 --delta 2580400.24 \\
      --explicacion "Residual de apertura anterior a la ventana"

  python -m src.ajustar_saldo_cuenta --plan plan.json
""",
    )
    parser.add_argument("--cuenta", help="Nombre de la cuenta en Wallet")
    parser.add_argument(
        "--initial-balance",
        help="Nuevo initialBalance (admite formato es-CO: 2.580.398,47)",
    )
    parser.add_argument(
        "--delta",
        help="Delta esperado (objetivo - actual). Se valida; no se adivina.",
    )
    parser.add_argument(
        "--explicacion",
        help=f"Motivo del ajuste (mínimo {MIN_EXPLICACION} caracteres)",
    )
    parser.add_argument(
        "--plan",
        help="Plan de conciliación v1 con bloque ajuste_apertura (alternativa a los flags)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra la propuesta; no escribe en Wallet",
    )
    args = parser.parse_args()

    # ── Origen de los datos ──────────────────────────────────────────────────
    if args.plan:
        try:
            plan = load_plan(args.plan)
        except PlanValidationError as exc:
            print(f"[PLAN INVÁLIDO] {exc}")
            sys.exit(2)
        ajuste = plan.get("ajuste_apertura")
        if not ajuste:
            print("[ERROR] El plan no incluye el bloque 'ajuste_apertura'")
            sys.exit(2)
        cuenta_nombre = plan["cuenta"]
        objetivo = float(ajuste["initial_balance_objetivo"])
        explicacion = ajuste["explicacion"]
        delta_declarado: Optional[float] = None
        moneda_plan = plan["moneda"]
    else:
        if not args.cuenta or args.initial_balance is None:
            parser.error("debes indicar --cuenta y --initial-balance (o usar --plan)")
        if not args.explicacion:
            parser.error("--explicacion es obligatoria: el delta debe estar justificado")
        cuenta_nombre = args.cuenta
        try:
            objetivo = parse_es_co_number(args.initial_balance)
            delta_declarado = (
                parse_es_co_number(args.delta) if args.delta is not None else None
            )
        except PlanValidationError as exc:
            print(f"[ERROR] {exc}")
            sys.exit(2)
        explicacion = args.explicacion.strip()
        moneda_plan = "COP"

    # ── Validar explicación ──────────────────────────────────────────────────
    if len(explicacion) < MIN_EXPLICACION:
        print(
            f"[ERROR] La explicación debe tener al menos {MIN_EXPLICACION} caracteres "
            f"(actual: {len(explicacion)})"
        )
        sys.exit(2)

    try:
        client = WalletClient()
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    try:
        cuenta = client.find_account(cuenta_nombre)
        if not cuenta:
            print(f"[ERROR] Cuenta '{cuenta_nombre}' no encontrada en Wallet")
            disponibles = [c.get("name") for c in client.get_accounts()]
            print(f"        Disponibles: {', '.join(disponibles)}")
            sys.exit(1)

        if cuenta.get("archived"):
            print(f"[ERROR] La cuenta '{cuenta['name']}' está archivada")
            sys.exit(1)

        moneda = (cuenta.get("currencyCode") or moneda_plan).upper()
        initial_actual = float((cuenta.get("balance") or {}).get("initial") or 0.0)
        delta_real = round(objetivo - initial_actual, 2)

        print("\n" + "=" * 64)
        print("  AJUSTE DE initialBalance — PARTIDA DE APERTURA")
        print("=" * 64)
        print(f"  Cuenta                  : {cuenta['name']} ({cuenta['id'][:8]}...)")
        print(f"  initialBalance actual   : {fmt(initial_actual, moneda)}")
        print(f"  initialBalance objetivo : {fmt(objetivo, moneda)}")
        print(f"  Delta real calculado    : {fmt(delta_real, moneda)}")
        if delta_declarado is not None:
            print(f"  Delta declarado         : {fmt(delta_declarado, moneda)}")
        print(f"  Explicación             : {explicacion}")
        print("=" * 64)

        # ── Validar delta declarado ──────────────────────────────────────────
        if delta_declarado is not None and abs(delta_real - delta_declarado) > 0.01:
            print(
                f"\n[ERROR] El delta declarado ({fmt(delta_declarado, moneda)}) no coincide "
                f"con el calculado ({fmt(delta_real, moneda)})."
            )
            print("        El delta debe ser objetivo - actual.")
            sys.exit(2)

        if delta_real == 0:
            print("\n[INFO] Delta cero: no hay nada que ajustar")
            return

        if args.dry_run:
            print("\n[DRY-RUN] No se escribió nada en Wallet")
            registrar(
                "ajuste_apertura_dry_run",
                {
                    "cuenta": cuenta["name"],
                    "initial_actual": initial_actual,
                    "initial_objetivo": objetivo,
                    "delta": delta_real,
                    "explicacion": explicacion,
                },
            )
            return

        # ── Aprobación humana explícita (obligatoria) ─────────────────────────
        if not _leer_confirmacion(
            "\n¿Aplicar este ajuste de apertura? [S]í / [N]o: "
        ):
            print("[INFO] Cancelado: sin aprobación humana no se modifica initialBalance")
            registrar(
                "ajuste_apertura_cancelado",
                {"cuenta": cuenta["name"], "delta": delta_real, "explicacion": explicacion},
            )
            return

        # ── Aplicar ──────────────────────────────────────────────────────────
        resultado = client.patch_accounts(
            [{"id": cuenta["id"], "initialBalance": objetivo}]
        )
        print("\n[OK] initialBalance actualizado")

        registrar(
            "ajuste_apertura_initialbalance",
            {
                "cuenta": cuenta["name"],
                "initial_actual": initial_actual,
                "initial_objetivo": objetivo,
                "delta": delta_real,
                "explicacion": explicacion,
            },
            resultado,
        )

        print("\n[INFO] Verificación:")
        cuentas = client.get_accounts()
        actualizada = next((c for c in cuentas if c["id"] == cuenta["id"]), None)
        if actualizada:
            bal = actualizada.get("balance") or {}
            print(f"       initialBalance : {fmt(bal.get('initial'), moneda)}")
            print(f"       currentBalance : {fmt(bal.get('currentBalance'), moneda)}")

    except WalletAPIError as exc:
        print(f"\n[ERROR API] {exc}")
        registrar("ajuste_apertura_error", {"cuenta": cuenta_nombre}, None, str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
