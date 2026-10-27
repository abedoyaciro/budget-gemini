#!/usr/bin/env python3
"""
Esquema, validación y utilidades del plan de conciliación
=========================================================

Centraliza:
  * Carga y validación del plan versionado `plan.conciliacion.v1`.
  * Parsing explícito de números en formato es-CO (`2.580.398,47`).
  * Normalización de fechas y comparación con tolerancia.
  * Matching de movimientos con tolerancia ±N días.

El plan es el contrato entre el agente (que lee capturas con visión) y
`conciliar_cuenta.py` (que escribe en Wallet). Sin validación, un plan mal
formado escribe basura en la contabilidad.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

PLAN_VERSION = "plan.conciliacion.v1"
SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schemas",
    "plan.conciliacion.v1.json",
)

# Tolerancia por defecto al matchear fechas entre banco y Wallet.
# Verificado: el banco puede fechar el 01/05 lo que Wallet registra el 02/05.
DEFAULT_DATE_TOLERANCE_DAYS = 3


class PlanValidationError(ValueError):
    """El plan no cumple el contrato: se aborta antes de escribir nada."""


# ─────────────────────────────────────────────────────────────────────────────
# Parsing es-CO
# ─────────────────────────────────────────────────────────────────────────────

# Formato es-CO: signo opcional, grupos de miles con '.', decimales con ','.
_ES_CO_NUMBER = re.compile(r"^[+-]?\d{1,3}(\.\d{3})*(,\d+)?$|^[+-]?\d+(,\d+)?$")


def parse_es_co_number(valor: Any) -> float:
    """
    Convierte un número en formato es-CO a float.

    Reglas:
      "2.580.398,47" -> 2580398.47   (punto = miles, coma = decimal)
      "$ 2.580.398,47" -> 2580398.47
      "-1,77" -> -1.77
      "+22.038,81" -> 22038.81
      2580398.47 -> 2580398.47      (numérico se devuelve tal cual)

    Si el texto no encaja en el patrón es-CO, se intenta interpretarlo como
    número con punto decimal (formato en-US) y, si tampoco, se lanza error.
    """
    if isinstance(valor, (int, float)):
        return float(valor)

    if not isinstance(valor, str):
        raise PlanValidationError(f"Valor numérico inválido: {valor!r}")

    texto = valor.strip()
    texto = texto.replace("$", "").replace("COP", "").replace("\u00a0", " ").strip()
    texto = texto.replace(" ", "")

    if not texto:
        raise PlanValidationError("Valor numérico vacío")

    # Quitar el signo para analizar y reaplicarlo después
    signo = -1.0 if texto.startswith("-") else 1.0
    cuerpo = texto.lstrip("+-")

    if _ES_CO_NUMBER.match(texto):
        normalizado = cuerpo.replace(".", "").replace(",", ".")
        return signo * float(normalizado)

    # Fallback: formato con punto decimal (en-US)
    try:
        return float(texto)
    except ValueError:
        raise PlanValidationError(
            f"No se pudo parsear '{valor}' como número es-CO ni como decimal"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fechas
# ─────────────────────────────────────────────────────────────────────────────

def parse_fecha(valor: Any) -> datetime:
    """Parsea fecha ISO (con o sin hora) a datetime UTC offset-aware."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if not isinstance(valor, str) or not valor.strip():
        raise PlanValidationError(f"Fecha inválida: {valor!r}")

    texto = valor.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        raise PlanValidationError(f"Fecha no ISO 8601: {valor!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fechas_coinciden(
    fecha_a: Any,
    fecha_b: Any,
    tolerancia_dias: int = DEFAULT_DATE_TOLERANCE_DAYS,
) -> Tuple[bool, int]:
    """
    Compara dos fechas con tolerancia en días de calendario.

    Devuelve (coinciden, diferencia_en_dias).

    Se comparan fechas (no instantes): el banco y Wallet difieren ±1 día y
    además la hora es irrelevante para conciliar. Restar datetimes completos
    daría un día de menos por el truncamiento de timedelta.days.
    """
    try:
        a = parse_fecha(fecha_a).date()
        b = parse_fecha(fecha_b).date()
    except PlanValidationError:
        return False, 10**6
    diff = abs((a - b).days)
    return diff <= tolerancia_dias, diff


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────
# Validación del plan
# ─────────────────────────────────────────────────────────────────────────────

def _require(obj: Dict[str, Any], campo: str, tipo: type, contexto: str = "plan") -> Any:
    if campo not in obj:
        raise PlanValidationError(f"{contexto}: falta el campo obligatorio '{campo}'")
    valor = obj[campo]
    if not isinstance(valor, tipo):
        raise PlanValidationError(
            f"{contexto}: '{campo}' debe ser {tipo.__name__}, es {type(valor).__name__}"
        )
    return valor


def _validate_movimiento(mov: Dict[str, Any], contexto: str) -> Dict[str, Any]:
    if not isinstance(mov, dict):
        raise PlanValidationError(f"{contexto}: cada movimiento debe ser un objeto")

    permitidos = {
        "fecha",
        "monto",
        "concepto",
        "category_system_id",
        "category_nombre",
        "contraparte",
        "label_ids",
        "saldo_corrido",
    }
    desconocidos = set(mov) - permitidos
    if desconocidos:
        raise PlanValidationError(
            f"{contexto}: campos no permitidos {sorted(desconocidos)}. "
            f"Permitidos: {sorted(permitidos)}"
        )

    _require(mov, "fecha", str, contexto)
    _require(mov, "concepto", str, contexto)
    if "monto" not in mov:
        raise PlanValidationError(f"{contexto}: falta 'monto'")

    monto = parse_es_co_number(mov["monto"])
    if monto == 0:
        raise PlanValidationError(f"{contexto}: monto no puede ser cero")

    parse_fecha(mov["fecha"])

    if "category_system_id" in mov and "category_nombre" in mov:
        raise PlanValidationError(
            f"{contexto}: usa category_system_id O category_nombre, no ambos"
        )

    salida = dict(mov)
    salida["monto"] = monto
    if "saldo_corrido" in mov and mov["saldo_corrido"] is not None:
        salida["saldo_corrido"] = parse_es_co_number(mov["saldo_corrido"])
    return salida


def validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Valida el plan contra `plan.conciliacion.v1` y devuelve una copia normalizada.

    Lanza PlanValidationError con el motivo concreto. No escribe nada.
    """
    if not isinstance(plan, dict):
        raise PlanValidationError("El plan debe ser un objeto JSON")

    version = plan.get("version")
    if version != PLAN_VERSION:
        raise PlanValidationError(
            f"version debe ser '{PLAN_VERSION}', se recibió {version!r}. "
            f"Esquema: {SCHEMA_PATH}"
        )

    _require(plan, "cuenta", str)

    permitidos = {
        "version",
        "cuenta",
        "banco",
        "moneda",
        "tolerancia",
        "since_date",
        "captura",
        "crear_registros",
        "transferencias",
        "ajuste_apertura",
    }
    desconocidos = set(plan) - permitidos
    if desconocidos:
        raise PlanValidationError(
            f"Campos no permitidos en el plan: {sorted(desconocidos)}"
        )

    normalizado: Dict[str, Any] = {
        "version": version,
        "cuenta": plan["cuenta"].strip(),
        "banco": plan.get("banco"),
        "moneda": (plan.get("moneda") or "COP").upper(),
        "tolerancia": parse_es_co_number(plan.get("tolerancia", 0.01)),
        "crear_registros": [],
        "transferencias": [],
    }

    if "since_date" in plan and plan["since_date"] is not None:
        normalizado["since_date"] = iso_utc(parse_fecha(plan["since_date"]))

    # ── captura ──────────────────────────────────────────────────────────────
    if "captura" in plan:
        captura = plan["captura"]
        if not isinstance(captura, dict):
            raise PlanValidationError("captura debe ser un objeto")
        cap_permitidos = {"fecha", "saldo_final", "saldo_corrido", "movimientos"}
        desconocidos = set(captura) - cap_permitidos
        if desconocidos:
            raise PlanValidationError(
                f"captura: campos no permitidos {sorted(desconocidos)}"
            )
        if "saldo_final" not in captura:
            raise PlanValidationError("captura: falta 'saldo_final'")

        cap_norm: Dict[str, Any] = {
            "fecha": captura.get("fecha"),
            "saldo_final": parse_es_co_number(captura["saldo_final"]),
            "saldo_corrido": [],
            "movimientos": [],
        }
        for i, punto in enumerate(captura.get("saldo_corrido") or []):
            if not isinstance(punto, dict) or "fecha" not in punto or "saldo" not in punto:
                raise PlanValidationError(
                    f"captura.saldo_corrido[{i}]: requiere 'fecha' y 'saldo'"
                )
            cap_norm["saldo_corrido"].append(
                {
                    "fecha": iso_utc(parse_fecha(punto["fecha"])),
                    "saldo": parse_es_co_number(punto["saldo"]),
                }
            )
        for i, mov in enumerate(captura.get("movimientos") or []):
            cap_norm["movimientos"].append(
                _validate_movimiento(mov, f"captura.movimientos[{i}]")
            )
        normalizado["captura"] = cap_norm

    # ── crear_registros ──────────────────────────────────────────────────────
    for i, mov in enumerate(plan.get("crear_registros") or []):
        normalizado["crear_registros"].append(
            _validate_movimiento(mov, f"crear_registros[{i}]")
        )

    # ── transferencias ───────────────────────────────────────────────────────
    for i, tr in enumerate(plan.get("transferencias") or []):
        contexto = f"transferencias[{i}]"
        if not isinstance(tr, dict):
            raise PlanValidationError(f"{contexto}: debe ser un objeto")
        tr_permitidos = {
            "fecha",
            "monto",
            "concepto",
            "cuenta_contraparte",
            "crear_espejo",
        }
        desconocidos = set(tr) - tr_permitidos
        if desconocidos:
            raise PlanValidationError(
                f"{contexto}: campos no permitidos {sorted(desconocidos)}"
            )
        _require(tr, "cuenta_contraparte", str, contexto)
        if "fecha" not in tr or "monto" not in tr:
            raise PlanValidationError(f"{contexto}: requiere 'fecha' y 'monto'")
        normalizado["transferencias"].append(
            {
                "fecha": iso_utc(parse_fecha(tr["fecha"])),
                "monto": parse_es_co_number(tr["monto"]),
                "concepto": tr.get("concepto") or "",
                "cuenta_contraparte": tr["cuenta_contraparte"].strip(),
                "crear_espejo": bool(tr.get("crear_espejo", False)),
            }
        )

    # ── ajuste_apertura ──────────────────────────────────────────────────────
    if "ajuste_apertura" in plan:
        ajuste = plan["ajuste_apertura"]
        if not isinstance(ajuste, dict):
            raise PlanValidationError("ajuste_apertura debe ser un objeto")
        if "initial_balance_objetivo" not in ajuste:
            raise PlanValidationError(
                "ajuste_apertura: falta 'initial_balance_objetivo'"
            )
        explicacion = ajuste.get("explicacion") or ""
        if len(explicacion.strip()) < 10:
            raise PlanValidationError(
                "ajuste_apertura.explicacion debe explicar el delta (mínimo 10 caracteres)"
            )
        normalizado["ajuste_apertura"] = {
            "initial_balance_objetivo": parse_es_co_number(
                ajuste["initial_balance_objetivo"]
            ),
            "explicacion": explicacion.strip(),
            "confirmar": bool(ajuste.get("confirmar", False)),
        }

    # ── deducir since_date si no viene ───────────────────────────────────────
    if not normalizado.get("since_date"):
        fechas: List[datetime] = []
        for mov in normalizado["crear_registros"]:
            fechas.append(parse_fecha(mov["fecha"]))
        for tr in normalizado["transferencias"]:
            fechas.append(parse_fecha(tr["fecha"]))
        for mov in normalizado.get("captura", {}).get("movimientos", []):
            fechas.append(parse_fecha(mov["fecha"]))
        if fechas:
            normalizado["since_date"] = iso_utc(
                min(fechas) - timedelta(days=31)
            )
        else:
            # Sin movimientos no hay nada que reconciliar; ventana amplia segura.
            normalizado["since_date"] = iso_utc(
                datetime.now(timezone.utc) - timedelta(days=365 * 5)
            )

    return normalizado


def load_plan(path: str) -> Dict[str, Any]:
    """Carga y valida un plan desde archivo."""
    if not os.path.exists(path):
        raise PlanValidationError(f"No existe el plan: {path}")
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise PlanValidationError(f"JSON inválido en {path}: {exc}")
    return validate_plan(data)


def load_plan_from_string(texto: str) -> Dict[str, Any]:
    """Carga y valida un plan desde string JSON."""
    try:
        data = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise PlanValidationError(f"JSON inválido: {exc}")
    return validate_plan(data)
