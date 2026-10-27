#!/usr/bin/env python3
"""
Conciliación genérica de cuenta contra capturas del banco
=========================================================

Toma un plan `plan.conciliacion.v1` (validado), compara contra Wallet y
crea los registros que faltan. Funciona para cualquier cuenta.

Qué hace:
  1. Valida el plan contra el esquema versionado (aborta si no cumple).
  2. Lee los registros de Wallet con ventana explícita (recordDate=gte.<ISO>).
  3. Matchea cada movimiento con tolerancia ±3 días + monto exacto.
  4. Crea solo los faltantes, resolviendo la categoría por systemId en runtime.
  5. Verifica transferencias antes de crear espejos (nunca por defecto).
  6. Valida el saldo corrido de la captura movimiento por movimiento.
  7. Verifica el resultado: currentBalance vs saldo de la captura, con la
     tolerancia declarada en el plan.
  8. Registra todo en output/enriquecimiento_log.json.

Lo que NO hace:
  * No toca initialBalance salvo que el plan incluya `ajuste_apertura`
    con `confirmar: true` y explicación (regla documentada abajo).

Regla de initialBalance (elegida y documentada):
  El residual de conciliación originado ANTES de la ventana no se resuelve
  sin inventar registros. Se trata como PARTIDA DE APERTURA (ajuste de
  initialBalance), no como asiento de "Ajuste de conciliación" en una
  categoría de sistema, porque ese asiento ensuciaría los reportes de
  ingresos/gastos del período. El ajuste exige:
    (a) delta cuantificado y explicado,
    (b) aprobación humana explícita (confirmar: true + pregunta en consola),
    (c) registro en enriquecimiento_log.json.

Uso:
    python -m src.conciliar_cuenta --plan plan.json
    python -m src.conciliar_cuenta --plan plan.json --yes     # plan ya aprobado
    python -m src.conciliar_cuenta --plan plan.json --dry-run # solo reporta
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from plan_conciliacion import (
    DEFAULT_DATE_TOLERANCE_DAYS,
    PLAN_VERSION,
    PlanValidationError,
    fechas_coinciden,
    iso_utc,
    load_plan,
    load_plan_from_string,
    parse_fecha,
)
from wallet_client import (
    SYSTEM_ID_INTEREST_DIVIDENDS,
    SYSTEM_ID_TRANSFER,
    CategoryNotFoundError,
    WalletAPIError,
    WalletClient,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv es opcional en entornos ya configurados
    pass

OUTPUT_DIR = "output"
LOG_PATH = os.path.join(OUTPUT_DIR, "enriquecimiento_log.json")


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades de moneda y log
# ─────────────────────────────────────────────────────────────────────────────

def fmt(valor: Optional[float], moneda: str = "COP") -> str:
    """
    Formatea con separador de miles '.' y decimal ',' (es-CO).

    2580398.47 -> '2.580.398,47 COP'
    """
    if valor is None:
        return "—"
    signo = "-" if valor < 0 else ""
    cuerpo = f"{abs(valor):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{cuerpo} {moneda}"


def _read_log() -> Dict[str, Any]:
    if not os.path.exists(LOG_PATH):
        return {"sesiones": []}
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"sesiones": []}

    if isinstance(data, list):
        return {"sesiones": data}
    if isinstance(data, dict):
        data.setdefault("sesiones", [])
        return data
    return {"sesiones": []}


def registrar(accion: str, detalle: Dict[str, Any], resultado: Any = None, error: str = "") -> None:
    """Añade una entrada de auditoría a enriquecimiento_log.json."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log = _read_log()
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


# ─────────────────────────────────────────────────────────────────────────────
# Matching
# ─────────────────────────────────────────────────────────────────────────────

def _amount_of(record: Dict[str, Any]) -> float:
    return float((record.get("amount") or {}).get("value") or 0.0)


def _category_id_of(record: Dict[str, Any]) -> Optional[str]:
    cat = record.get("category") or {}
    return cat.get("id") or record.get("categoryId")


def _category_name_of(record: Dict[str, Any]) -> str:
    cat = record.get("category") or {}
    return (cat.get("name") or "").strip().lower()


def find_match(
    mov: Dict[str, Any],
    registros: List[Dict[str, Any]],
    categoria_esperada_id: Optional[str] = None,
    categoria_esperada_nombre: Optional[str] = None,
    usados: Optional[set] = None,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """
    Busca un registro existente equivalente al movimiento.

    Criterios (todos deben cumplirse):
      * fecha con tolerancia ±3 días (el banco y Wallet difieren ±1 día)
      * monto exacto (diferencia < 0.01)
      * categoría compatible, si el plan especifica una

    `usados` evita que dos movimientos de la captura consuman el mismo
    registro de Wallet (traslapes).
    """
    monto = float(mov["monto"])
    usados = usados if usados is not None else set()

    mejor: Optional[Dict[str, Any]] = None
    mejor_diff = 10**6

    for record in registros:
        rid = record.get("id")
        if rid in usados:
            continue
        if abs(_amount_of(record) - monto) >= 0.01:
            continue

        coincide, diff = fechas_coinciden(mov["fecha"], record.get("recordDate"))
        if not coincide:
            continue

        if categoria_esperada_id:
            actual = _category_id_of(record)
            if actual and actual != categoria_esperada_id:
                continue
        elif categoria_esperada_nombre:
            actual_nombre = _category_name_of(record)
            if actual_nombre and categoria_esperada_nombre.lower() not in actual_nombre:
                continue

        if diff < mejor_diff:
            mejor, mejor_diff = record, diff

    return mejor, mejor_diff


# ─────────────────────────────────────────────────────────────────────────────
# Resolución de categoría
# ─────────────────────────────────────────────────────────────────────────────

def resolver_categoria(
    client: WalletClient, mov: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Devuelve (categoryId, descripcion). Aborta si el plan pide una categoría
    que no existe con coincidencia exacta (nunca IDs literales ni aproximados).
    """
    system_id = mov.get("category_system_id")
    nombre = mov.get("category_nombre")

    if system_id:
        try:
            return client.resolve_category_id(system_id), f"systemId={system_id}"
        except CategoryNotFoundError as exc:
            raise SystemExit(f"[ABORTA] {exc}")

    if nombre:
        cat_id = client.find_category_id_by_name(nombre)
        if not cat_id:
            raise SystemExit(
                f"[ABORTA] No existe categoría con nombre exacto '{nombre}' en Wallet"
            )
        return cat_id, f"nombre={nombre}"

    return None, None


def inferir_system_id(mov: Dict[str, Any]) -> Optional[str]:
    """Heurística explícita para intereses; nunca inventa categoría."""
    concepto = (mov.get("concepto") or "").lower()
    if "interes" in concepto or "interest" in concepto or "dividend" in concepto:
        return SYSTEM_ID_INTEREST_DIVIDENDS
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Validación de saldo corrido
# ─────────────────────────────────────────────────────────────────────────────

def validar_saldo_corrido(
    plan: Dict[str, Any], registros: List[Dict[str, Any]], moneda: str
) -> Dict[str, Any]:
    """
    Reproduce el saldo corrido de la captura contra los movimientos del banco.

    Detecta:
      * movimientos que faltan en la ventana
      * registros mal fechados (aparecen fuera de orden)
      * traslapes (un mismo monto dos veces)

    Nota: la captura solo muestra movimientos recientes, así que el saldo
    inicial del tramo se deduce y se contrasta con lo que Wallet tiene.
    """
    captura = plan.get("captura") or {}
    puntos = captura.get("saldo_corrido") or []
    movimientos = captura.get("movimientos") or []

    if not puntos or not movimientos:
        return {"disponible": False, "motivo": "sin saldo_corrido en el plan"}

    puntos_ord = sorted(puntos, key=lambda p: parse_fecha(p["fecha"]))
    movs_ord = sorted(movimientos, key=lambda m: parse_fecha(m["fecha"]))

    # Cada punto de saldo_corrido es el saldo DESPUÉS del movimiento de esa
    # fecha. El saldo base es, por tanto, el del primer punto menos la suma de
    # movimientos hasta esa fecha inclusive.
    primera_fecha = parse_fecha(puntos_ord[0]["fecha"])
    saldo_base = puntos_ord[0]["saldo"] - sum(
        float(m["monto"]) for m in movs_ord if parse_fecha(m["fecha"]) <= primera_fecha
    )

    saldo_por_fecha = {parse_fecha(p["fecha"]): p["saldo"] for p in puntos_ord}

    desviaciones: List[Dict[str, Any]] = []
    saldo = round(saldo_base, 2)
    for mov in movs_ord:
        saldo = round(saldo + float(mov["monto"]), 2)
        esperado = saldo_por_fecha.get(parse_fecha(mov["fecha"]))
        if esperado is not None and abs(saldo - esperado) > 0.01:
            desviaciones.append(
                {
                    "fecha": mov["fecha"],
                    "saldo_calculado": saldo,
                    "saldo_captura": esperado,
                    "delta": round(saldo - esperado, 2),
                }
            )
    inicial = saldo_base

    ultimo_esperado = puntos_ord[-1]["saldo"]
    return {
        "disponible": True,
        "saldo_inicial_deducido": round(inicial, 2),
        "saldo_final_calculado": round(saldo, 2),
        "saldo_final_captura": ultimo_esperado,
        "coincide": abs(saldo - ultimo_esperado) <= 0.01,
        "desviaciones": desviaciones,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ejecución
# ─────────────────────────────────────────────────────────────────────────────

def construir_payload(
    client: WalletClient,
    cuenta: Dict[str, Any],
    mov: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Construye el body de creación. Solo campos escribibles."""
    account_id = cuenta["id"]
    moneda = cuenta.get("currencyCode") or "COP"

    # Categoría: del plan o inferida explícitamente (intereses)
    system_id = mov.get("category_system_id") or inferir_system_id(mov)
    categoria_id: Optional[str] = None
    nota_cat: Optional[str] = None

    if system_id:
        try:
            categoria_id = client.resolve_category_id(system_id)
            nota_cat = f"systemId={system_id}"
        except CategoryNotFoundError as exc:
            raise SystemExit(f"[ABORTA] {exc}")
    elif mov.get("category_nombre"):
        categoria_id = client.find_category_id_by_name(mov["category_nombre"])
        if not categoria_id:
            raise SystemExit(
                f"[ABORTA] Categoría '{mov['category_nombre']}' sin coincidencia exacta"
            )
        nota_cat = f"nombre={mov['category_nombre']}"

    payload: Dict[str, Any] = {
        "accountId": account_id,
        "amount": {"value": float(mov["monto"]), "currencyCode": moneda},
        "recordDate": iso_utc(parse_fecha(mov["fecha"])),
        "note": (mov.get("concepto") or "")[:255],
    }
    if categoria_id:
        payload["categoryId"] = categoria_id
    if mov.get("contraparte"):
        payload["counterParty"] = str(mov["contraparte"])[:255]
    if mov.get("label_ids"):
        payload["labelIds"] = list(mov["label_ids"])

    return payload, nota_cat


def plan_de_creacion(
    client: WalletClient,
    cuenta: Dict[str, Any],
    plan: Dict[str, Any],
    registros: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Compare los movimientos del plan contra Wallet.

    Devuelve (a_crear, ya_existen).
    """
    usados: set = set()
    a_crear: List[Dict[str, Any]] = []
    ya_existen: List[Dict[str, Any]] = []

    for mov in plan.get("crear_registros", []):
        system_id = mov.get("category_system_id") or inferir_system_id(mov)
        cat_id = None
        cat_nombre = mov.get("category_nombre")
        if system_id:
            try:
                cat_id = client.resolve_category_id(system_id)
            except CategoryNotFoundError as exc:
                raise SystemExit(f"[ABORTA] {exc}")

        match, diff = find_match(
            mov,
            registros,
            categoria_esperada_id=cat_id,
            categoria_esperada_nombre=cat_nombre,
            usados=usados,
        )

        if match:
            usados.add(match.get("id"))
            ya_existen.append(
                {
                    "movimiento": mov,
                    "registro_id": match.get("id"),
                    "registro_fecha": (match.get("recordDate") or "")[:10],
                    "diferencia_dias": diff,
                }
            )
            continue

        payload, nota_cat = construir_payload(client, cuenta, mov)
        a_crear.append({"movimiento": mov, "payload": payload, "categoria": nota_cat})

    return a_crear, ya_existen


def procesar_transferencias(
    client: WalletClient,
    cuenta: Dict[str, Any],
    plan: Dict[str, Any],
    registros: List[Dict[str, Any]],
    cuentas: List[Dict[str, Any]],
    moneda: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Analiza las transferencias del plan.

    Regla: la captura normalmente muestra UN SOLO LADO del par. No se crea
    el espejo a menos que el plan traiga `crear_espejo: true` Y se verifique
    que el espejo no existe ya en la cuenta contraparte.
    """
    acciones: List[Dict[str, Any]] = []
    espejos_a_crear: List[Dict[str, Any]] = []

    for tr in plan.get("transferencias", []):
        origen, diff = find_match(tr, registros)
        contraparte = client.find_account(tr["cuenta_contraparte"])

        if not contraparte:
            acciones.append(
                {
                    "tipo": "transferencia",
                    "estado": "contraparte_no_encontrada",
                    "detalle": tr,
                    "mensaje": f"Cuenta '{tr['cuenta_contraparte']}' no existe en Wallet",
                }
            )
            continue

        if origen and client.is_paired_transfer(origen):
            info = client.get_transfer_info(origen) or {}
            acciones.append(
                {
                    "tipo": "transferencia",
                    "estado": "ya_pareada",
                    "detalle": tr,
                    "transfer_id": info.get("transferId"),
                    "mensaje": "El registro ya tiene transfer pareada; no se duplica",
                }
            )
            continue

        # ¿Existe ya el espejo en la contraparte?
        registros_contraparte = client.get_records(
            contraparte["id"], since_date=plan["since_date"], max_records=500
        )
        espejo_mov = {
            "fecha": tr["fecha"],
            "monto": -float(tr["monto"]),
            "concepto": tr.get("concepto") or "",
        }
        espejo, diff_espejo = find_match(espejo_mov, registros_contraparte)

        if espejo:
            acciones.append(
                {
                    "tipo": "transferencia",
                    "estado": "espejo_existe",
                    "detalle": tr,
                    "registro_id": espejo.get("id"),
                    "mensaje": "El lado espejo ya existe; no se crea",
                }
            )
            continue

        if not tr.get("crear_espejo"):
            acciones.append(
                {
                    "tipo": "transferencia",
                    "estado": "requiere_confirmacion",
                    "detalle": tr,
                    "mensaje": (
                        "La captura muestra un solo lado del par. Para crear el espejo "
                        "añade 'crear_espejo: true' en el plan."
                    ),
                }
            )
            continue

        try:
            cat_transfer = client.resolve_category_id(SYSTEM_ID_TRANSFER)
        except CategoryNotFoundError:
            cat_transfer = None

        payload: Dict[str, Any] = {
            "accountId": contraparte["id"],
            "amount": {
                "value": -float(tr["monto"]),
                "currencyCode": contraparte.get("currencyCode") or moneda,
            },
            "recordDate": iso_utc(parse_fecha(tr["fecha"])),
            "note": (tr.get("concepto") or "Transferencia")[:255],
        }
        if cat_transfer:
            payload["categoryId"] = cat_transfer

        espejos_a_crear.append({"detalle": tr, "payload": payload})
        acciones.append(
            {
                "tipo": "transferencia",
                "estado": "crear_espejo",
                "detalle": tr,
                "cuenta_contraparte": contraparte["name"],
            }
        )

    return acciones, espejos_a_crear


def verificar_saldo(
    client: WalletClient, cuenta_id: str, plan: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Verificación post-aplicación.

    Compara balance.currentBalance de Wallet contra el saldo final de la
    captura con la tolerancia declarada. No depende de la ventana de
    extracción: /accounts siempre devuelve el saldo calculado vigente.
    """
    captura = plan.get("captura") or {}
    if "saldo_final" not in captura:
        return {"verificado": False, "motivo": "el plan no declara captura.saldo_final"}

    cuentas = client.get_accounts()
    cuenta = next((c for c in cuentas if c["id"] == cuenta_id), None)
    if not cuenta:
        return {"verificado": False, "motivo": "cuenta no encontrada"}

    actual = float((cuenta.get("balance") or {}).get("currentBalance") or 0.0)
    esperado = float(captura["saldo_final"])
    tolerancia = float(plan.get("tolerancia", 0.01))
    delta = round(actual - esperado, 2)

    return {
        "verificado": True,
        "saldo_wallet": actual,
        "saldo_captura": esperado,
        "delta": delta,
        "tolerancia": tolerancia,
        "coincide": abs(delta) <= tolerancia,
    }


def aplicar_ajuste_apertura(
    client: WalletClient,
    cuenta: Dict[str, Any],
    ajuste: Dict[str, Any],
    moneda: str,
    yes: bool,
) -> Dict[str, Any]:
    """
    Ajusta initialBalance como partida de apertura.

    Requisitos: `confirmar: true` en el plan + aprobación humana explícita.
    """
    initial_actual = float((cuenta.get("balance") or {}).get("initial") or 0.0)
    objetivo = float(ajuste["initial_balance_objetivo"])
    delta = round(objetivo - initial_actual, 2)

    if not ajuste.get("confirmar"):
        return {
            "aplicado": False,
            "motivo": "ajuste_apertura.confirmar no es true",
            "initial_actual": initial_actual,
            "initial_objetivo": objetivo,
            "delta": delta,
            "explicacion": ajuste["explicacion"],
        }

    if delta == 0:
        return {
            "aplicado": False,
            "motivo": "delta cero: no hay nada que ajustar",
            "initial_actual": initial_actual,
        }

    print("\n" + "-" * 64)
    print("  AJUSTE DE PARTIDA DE APERTURA (initialBalance)")
    print("-" * 64)
    print(f"  initialBalance actual   : {fmt(initial_actual, moneda)}")
    print(f"  initialBalance objetivo : {fmt(objetivo, moneda)}")
    print(f"  Delta                   : {fmt(delta, moneda)}")
    print(f"  Explicación             : {ajuste['explicacion']}")
    print("-" * 64)

    if not yes:
        try:
            respuesta = input("  ¿Aplicar el ajuste de apertura? [S]í / [N]o: ").strip().upper()
        except EOFError:
            respuesta = "N"
        if respuesta != "S":
            return {
                "aplicado": False,
                "motivo": "cancelado por el usuario",
                "delta": delta,
            }

    resultado = client.patch_accounts(
        [{"id": cuenta["id"], "initialBalance": objetivo}]
    )
    registrar(
        "ajuste_apertura_initialbalance",
        {
            "cuenta": cuenta.get("name"),
            "initial_actual": initial_actual,
            "initial_objetivo": objetivo,
            "delta": delta,
            "explicacion": ajuste["explicacion"],
        },
        resultado,
    )
    return {
        "aplicado": True,
        "initial_actual": initial_actual,
        "initial_objetivo": objetivo,
        "delta": delta,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Presentación del plan antes de aplicar
# ─────────────────────────────────────────────────────────────────────────────

def imprimir_plan(
    plan: Dict[str, Any],
    cuenta: Dict[str, Any],
    a_crear: List[Dict[str, Any]],
    ya_existen: List[Dict[str, Any]],
    acciones_tr: List[Dict[str, Any]],
    espejos: List[Dict[str, Any]],
    corrido: Dict[str, Any],
    verif: Dict[str, Any],
) -> None:
    moneda = plan["moneda"]
    print("\n" + "=" * 64)
    print(f"  PLAN DE CONCILIACIÓN — {cuenta.get('name')} ({moneda})")
    print("=" * 64)
    print(f"  Ventana leída : recordDate >= {plan['since_date']}")
    print(f"  Tolerancia    : {plan['tolerancia']} {moneda}")

    if verif.get("verificado"):
        estado = "COINCIDE" if verif["coincide"] else "DIFIERE"
        print("\n  SALDO (estado previo a aplicar):")
        print(f"    Wallet  : {fmt(verif['saldo_wallet'], moneda)}")
        print(f"    Captura : {fmt(verif['saldo_captura'], moneda)}")
        print(f"    Delta   : {fmt(verif['delta'], moneda)}  -> {estado}")

    if corrido.get("disponible"):
        print("\n  SALDO CORRIDO (validación movimiento por movimiento):")
        print(
            f"    Calculado {fmt(corrido['saldo_final_calculado'], moneda)} | "
            f"Captura {fmt(corrido['saldo_final_captura'], moneda)} | "
            f"{'OK' if corrido['coincide'] else 'REVISAR'}"
        )
        for desv in corrido.get("desviaciones", [])[:5]:
            print(
                f"    ! {desv['fecha'][:10]} calculado {fmt(desv['saldo_calculado'], moneda)} "
                f"vs captura {fmt(desv['saldo_captura'], moneda)}"
            )

    print(f"\n  REGISTROS A CREAR ({len(a_crear)}):")
    if not a_crear:
        print("    (ninguno)")
    for item in a_crear:
        mov = item["movimiento"]
        cat = item["categoria"] or "sin categoría"
        print(
            f"    + {mov['fecha'][:10]} | {fmt(float(mov['monto']), moneda):>18} | "
            f"{(mov.get('concepto') or '')[:32]:32} | {cat}"
        )

    if ya_existen:
        print(f"\n  YA EXISTEN EN WALLET ({len(ya_existen)}):")
        for item in ya_existen:
            mov = item["movimiento"]
            print(
                f"    = {mov['fecha'][:10]} | {fmt(float(mov['monto']), moneda):>18} | "
                f"(match {item['registro_fecha']}, ±{item['diferencia_dias']}d)"
            )

    if acciones_tr:
        print(f"\n  TRANSFERENCIAS ({len(acciones_tr)}):")
        for acc in acciones_tr:
            tr = acc["detalle"]
            etiqueta = {
                "ya_pareada": "YA PAREADA (no se duplica)",
                "espejo_existe": "ESPEJO YA EXISTE (no se crea)",
                "requiere_confirmacion": "REQUIERE CONFIRMACIÓN (crear_espejo: true)",
                "crear_espejo": "CREARÁ ESPEJO",
                "contraparte_no_encontrada": "CONTRAPARTE NO ENCONTRADA",
            }.get(acc["estado"], acc["estado"])
            print(
                f"    * {tr['fecha'][:10]} | {fmt(float(tr['monto']), moneda):>18} | "
                f"{tr['cuenta_contraparte']} -> {etiqueta}"
            )

    if espejos:
        print(f"\n  ESPEJOS A CREAR ({len(espejos)}):")
        for esp in espejos:
            tr = esp["detalle"]
            print(
                f"    + {tr['fecha'][:10]} | {fmt(-float(tr['monto']), moneda):>18} | "
                f"en {tr['cuenta_contraparte']}"
            )

    print("=" * 64)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Conciliación genérica de cuenta (esquema {PLAN_VERSION})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python -m src.conciliar_cuenta --plan plan.json
  python -m src.conciliar_cuenta --plan plan.json --dry-run
  python -m src.conciliar_cuenta --plan plan.json --yes
""",
    )
    parser.add_argument("--plan", help="Ruta del plan JSON validado por esquema")
    parser.add_argument("--plan-json", help="Plan JSON inline")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="No volver a pedir confirmación (el plan ya fue aprobado por el humano)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra el plan y la verificación; no escribe en Wallet",
    )
    args = parser.parse_args()

    if not args.plan and not args.plan_json:
        parser.error("debes indicar --plan o --plan-json")

    # ── 1. Validar plan ──────────────────────────────────────────────────────
    try:
        plan = load_plan(args.plan) if args.plan else load_plan_from_string(args.plan_json)
    except PlanValidationError as exc:
        print(f"[PLAN INVÁLIDO] {exc}")
        sys.exit(2)

    try:
        client = WalletClient()
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    moneda = plan["moneda"]

    try:
        # ── 2. Cuenta ────────────────────────────────────────────────────────
        cuenta = client.find_account(plan["cuenta"])
        if not cuenta:
            print(f"[ERROR] Cuenta '{plan['cuenta']}' no encontrada en Wallet")
            disponibles = [c.get("name") for c in client.get_accounts()]
            print(f"        Disponibles: {', '.join(disponibles)}")
            sys.exit(1)

        moneda_cuenta = (cuenta.get("currencyCode") or moneda).upper()
        if moneda_cuenta != moneda:
            print(
                f"[ERROR] La cuenta '{cuenta['name']}' es {moneda_cuenta} "
                f"pero el plan declara {moneda}"
            )
            sys.exit(1)

        print(f"\n[1/5] Cuenta: {cuenta['name']} ({cuenta['id'][:8]}...)")

        # ── 3. Registros con ventana explícita ───────────────────────────────
        registros = client.get_records(
            cuenta["id"], since_date=plan["since_date"], max_records=None
        )
        print(
            f"[2/5] Registros leídos: {len(registros)} "
            f"(desde {plan['since_date']})"
        )

        # ── 4. Comparación ───────────────────────────────────────────────────
        a_crear, ya_existen = plan_de_creacion(client, cuenta, plan, registros)
        cuentas = client.get_accounts()
        acciones_tr, espejos = procesar_transferencias(
            client, cuenta, plan, registros, cuentas, moneda
        )
        corrido = validar_saldo_corrido(plan, registros, moneda)
        verif = verificar_saldo(client, cuenta["id"], plan)
        print("[3/5] Comparación completada")

        imprimir_plan(
            plan, cuenta, a_crear, ya_existen, acciones_tr, espejos, corrido, verif
        )

        if args.dry_run:
            print("\n[DRY-RUN] No se escribió nada en Wallet")
            registrar(
                "conciliar_dry_run",
                {"cuenta": cuenta["name"], "plan": plan},
                {"a_crear": len(a_crear), "espejos": len(espejos)},
            )
            return

        if not a_crear and not espejos and "ajuste_apertura" not in plan:
            print("\n[INFO] Nada que aplicar: la cuenta ya está conciliada")
            registrar(
                "conciliar_sin_cambios",
                {"cuenta": cuenta["name"]},
                {"a_crear": 0, "espejos": 0},
            )
            return

        # ── 5. Confirmación ──────────────────────────────────────────────────
        if not args.yes:
            try:
                respuesta = input(
                    f"\n¿Aplicar {len(a_crear)} registro(s) y "
                    f"{len(espejos)} espejo(s)? [S]í / [N]o: "
                ).strip().upper()
            except EOFError:
                respuesta = "N"
            if respuesta != "S":
                print("[INFO] Cancelado por el usuario")
                return

        # ── 6. Crear registros ───────────────────────────────────────────────
        print("\n[4/5] Aplicando cambios...")
        creados_detalle: List[Dict[str, Any]] = []

        if a_crear:
            payloads = [item["payload"] for item in a_crear]
            resultado = client.create_records(payloads)
            creados_detalle.extend(
                {
                    "movimiento": item["movimiento"],
                    "categoria": item["categoria"],
                }
                for item in a_crear
            )
            registrar(
                "conciliar_crear_registros",
                {"cuenta": cuenta["name"], "items": creados_detalle},
                resultado,
            )
            ok = (resultado.get("summary") or {}).get("succeeded", 0)
            print(f"      Registros creados: {ok}/{len(payloads)}")

        if espejos:
            payloads_esp = [esp["payload"] for esp in espejos]
            resultado_esp = client.create_records(payloads_esp)
            registrar(
                "conciliar_crear_espejos_transferencia",
                {"cuenta": cuenta["name"], "items": [esp["detalle"] for esp in espejos]},
                resultado_esp,
            )
            ok_esp = (resultado_esp.get("summary") or {}).get("succeeded", 0)
            print(f"      Espejos creados: {ok_esp}/{len(payloads_esp)}")

        # ── 6b. Ajuste de apertura (opcional, explícito) ─────────────────────
        if "ajuste_apertura" in plan:
            resultado_ajuste = aplicar_ajuste_apertura(
                client, cuenta, plan["ajuste_apertura"], moneda, args.yes
            )
            if resultado_ajuste.get("aplicado"):
                print(f"      Ajuste de apertura aplicado: {fmt(resultado_ajuste['delta'], moneda)}")
            else:
                print(f"      Ajuste de apertura NO aplicado: {resultado_ajuste.get('motivo')}")

        # ── 7. Verificación final ────────────────────────────────────────────
        print("\n[5/5] Verificación post-aplicación...")
        verif_final = verificar_saldo(client, cuenta["id"], plan)
        if verif_final.get("verificado"):
            print(f"      Wallet  : {fmt(verif_final['saldo_wallet'], moneda)}")
            print(f"      Captura : {fmt(verif_final['saldo_captura'], moneda)}")
            print(f"      Delta   : {fmt(verif_final['delta'], moneda)}")
            if verif_final["coincide"]:
                print("      [OK] La cuenta cuadra con el banco")
            else:
                print(
                    f"      [PENDIENTE] Diferencia de {fmt(verif_final['delta'], moneda)} "
                    f"fuera de tolerancia {verif_final['tolerancia']}"
                )
        else:
            print(f"      No verificable: {verif_final.get('motivo')}")

        registrar(
            "conciliar_verificacion",
            {"cuenta": cuenta["name"], "tolerancia": plan["tolerancia"]},
            verif_final,
        )

    except WalletAPIError as exc:
        print(f"\n[ERROR API] {exc}")
        registrar("conciliar_error", {"cuenta": plan.get("cuenta")}, None, str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
