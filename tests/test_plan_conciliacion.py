"""Pruebas del esquema de plan, parsing es-CO y matching."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from plan_conciliacion import (  # noqa: E402
    PLAN_VERSION,
    PlanValidationError,
    fechas_coinciden,
    parse_es_co_number,
    validate_plan,
)


# ── Parsing es-CO ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("2.580.398,47", 2580398.47),
        ("$ 2.580.398,47", 2580398.47),
        ("+22.038,81", 22038.81),
        ("-1,77", -1.77),
        ("9.526,52", 9526.52),
        ("4.250,12", 4250.12),
        ("1.400.000,00", 1400000.0),
        ("426.872,26", 426872.26),
        ("0,00", 0.0),
        ("2580398.47", 2580398.47),
        (2580398.47, 2580398.47),
        (0, 0.0),
    ],
)
def test_parse_es_co_number(entrada, esperado):
    assert parse_es_co_number(entrada) == pytest.approx(esperado)


@pytest.mark.parametrize("entrada", ["", "   ", "abc", None, "1,2,3"])
def test_parse_es_co_number_invalido(entrada):
    with pytest.raises(PlanValidationError):
        parse_es_co_number(entrada)


def test_parse_es_co_no_confunde_miles_con_decimales():
    # El bug clásico: "2.580" NO son 2.58
    assert parse_es_co_number("2.580") == pytest.approx(2580.0)


# ── Fechas ────────────────────────────────────────────────────────────────────

def test_fechas_coinciden_tolerancia_3_dias():
    coincide, diff = fechas_coinciden("2026-05-01", "2026-05-02")
    assert coincide and diff == 1

    coincide, diff = fechas_coinciden("2026-05-01", "2026-05-04")
    assert coincide and diff == 3

    coincide, diff = fechas_coinciden("2026-05-01", "2026-05-05")
    assert not coincide and diff == 4


def test_fechas_coinciden_iso_con_hora():
    coincide, diff = fechas_coinciden("2026-05-01T00:00:00Z", "2026-05-02T13:45:00Z")
    assert coincide and diff == 1


# ── Validación del plan ───────────────────────────────────────────────────────

def _plan_minimo(**overrides):
    plan = {"version": PLAN_VERSION, "cuenta": "Pibank"}
    plan.update(overrides)
    return plan


def test_plan_minimo_valido():
    resultado = validate_plan(_plan_minimo())
    assert resultado["cuenta"] == "Pibank"
    assert resultado["moneda"] == "COP"
    assert resultado["since_date"]  # se deduce


def test_plan_sin_version_falla():
    with pytest.raises(PlanValidationError, match="version"):
        validate_plan({"cuenta": "Pibank"})


def test_plan_version_incorrecta_falla():
    with pytest.raises(PlanValidationError, match="version"):
        validate_plan({"version": "plan.conciliacion.v2", "cuenta": "Pibank"})


def test_plan_sin_cuenta_falla():
    with pytest.raises(PlanValidationError, match="cuenta"):
        validate_plan({"version": PLAN_VERSION})


def test_plan_campo_desconocido_falla():
    with pytest.raises(PlanValidationError, match="no permitidos"):
        validate_plan(_plan_minimo(campo_inventado=1))


def test_movimiento_sin_monto_falla():
    plan = _plan_minimo(
        crear_registros=[{"fecha": "2026-05-01", "concepto": "Intereses"}]
    )
    with pytest.raises(PlanValidationError, match="monto"):
        validate_plan(plan)


def test_movimiento_monto_cero_falla():
    plan = _plan_minimo(
        crear_registros=[{"fecha": "2026-05-01", "monto": 0, "concepto": "x"}]
    )
    with pytest.raises(PlanValidationError, match="cero"):
        validate_plan(plan)


def test_movimiento_normaliza_monto_es_co():
    plan = _plan_minimo(
        crear_registros=[
            {"fecha": "2026-05-01", "monto": "4.250,12", "concepto": "Intereses"}
        ]
    )
    resultado = validate_plan(plan)
    assert resultado["crear_registros"][0]["monto"] == pytest.approx(4250.12)


def test_movimiento_con_dos_categorias_falla():
    plan = _plan_minimo(
        crear_registros=[
            {
                "fecha": "2026-05-01",
                "monto": 1,
                "concepto": "x",
                "category_system_id": "income__interest_dividends",
                "category_nombre": "Intereses",
            }
        ]
    )
    with pytest.raises(PlanValidationError, match="no ambos"):
        validate_plan(plan)


def test_transferencia_crear_espejo_por_defecto_false():
    plan = _plan_minimo(
        transferencias=[
            {"fecha": "2026-07-06", "monto": 1400000, "cuenta_contraparte": "Lulo"}
        ]
    )
    resultado = validate_plan(plan)
    assert resultado["transferencias"][0]["crear_espejo"] is False


def test_ajuste_apertura_exige_explicacion_larga():
    plan = _plan_minimo(
        ajuste_apertura={"initial_balance_objetivo": 100, "explicacion": "corto"}
    )
    with pytest.raises(PlanValidationError, match="explicacion"):
        validate_plan(plan)


def test_ajuste_apertura_confirmar_por_defecto_false():
    plan = _plan_minimo(
        ajuste_apertura={
            "initial_balance_objetivo": 100,
            "explicacion": "Residual de apertura previo a la ventana",
        }
    )
    resultado = validate_plan(plan)
    assert resultado["ajuste_apertura"]["confirmar"] is False


def test_captura_sin_saldo_final_falla():
    plan = _plan_minimo(captura={"fecha": "2026-10-26"})
    with pytest.raises(PlanValidationError, match="saldo_final"):
        validate_plan(plan)


def test_since_date_se_deduce_del_primer_movimiento():
    plan = _plan_minimo(
        crear_registros=[{"fecha": "2026-05-01", "monto": 1, "concepto": "x"}]
    )
    resultado = validate_plan(plan)
    # 31 días antes del 2026-05-01
    assert resultado["since_date"].startswith("2026-03-31")
