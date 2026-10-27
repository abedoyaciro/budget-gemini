#!/usr/bin/env python3
"""
Agregación determinista de movimientos de Wallet
================================================

Lee por REST (no gasta el presupuesto del MCP) y suma montos por grupo.
Es el fallback de P6 cuando `get_records_aggregation` no devuelve la suma.

Uso:
    python tools/agregar_periodo.py --desde 2026-10-01 --hasta 2026-11-01
    python tools/agregar_periodo.py --desde 2026-01-01 --cuenta Nequi --por categoria
    python tools/agregar_periodo.py --desde 2026-10-01 --por mes --formato json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from wallet_client import WalletAPIError, WalletClient  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass


def _group_key(record: Dict[str, Any], por: str) -> str:
    if por == "mes":
        return (record.get("recordDate") or "")[:7] or "?"
    if por == "cuenta":
        return record.get("accountName") or record.get("accountId") or "?"
    if por == "etiqueta":
        labels = record.get("labels") or []
        if labels:
            return ", ".join(l.get("name") or "?" for l in labels)
        return "(sin etiqueta)"
    categoria = record.get("category") or {}
    return categoria.get("name") or "Unknown"


def _amount(record: Dict[str, Any]) -> Tuple[float, str]:
    amount = record.get("amount") or {}
    currency = amount.get("currencyCode") or "?"
    try:
        return float(amount.get("value") or 0), currency
    except (TypeError, ValueError):
        return 0.0, currency


def _filas(records: List[Dict[str, Any]], por: str, moneda: str | None) -> List[Dict[str, Any]]:
    grupos: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in records:
        valor, currency = _amount(record)
        if moneda and currency != moneda:
            continue
        clave = (_group_key(record, por), currency)
        fila = grupos.setdefault(
            clave,
            {
                "grupo": clave[0],
                "moneda": currency,
                "ingresos": 0.0,
                "gastos": 0.0,
                "neto": 0.0,
                "registros": 0,
            },
        )
        if valor >= 0:
            fila["ingresos"] += valor
        else:
            fila["gastos"] += valor
        fila["neto"] += valor
        fila["registros"] += 1
    return sorted(grupos.values(), key=lambda f: (f["moneda"], f["grupo"]))


def _print_md(filas: List[Dict[str, Any]], args: argparse.Namespace, total: int) -> None:
    print(f"# Suma por {args.por}")
    print(f"Rango: {args.desde} -> {args.hasta or 'hoy'}")
    print(f"Registros leídos: {total}")
    print(f"Registros sumados: {sum(f['registros'] for f in filas)}")
    if args.cuenta:
        print(f"Cuenta: {args.cuenta}")
    if args.moneda:
        print(f"Moneda: {args.moneda}")
    print()
    print("| Grupo | Moneda | Ingresos | Gastos | Neto | N |")
    print("|---|---:|---:|---:|---:|---:|")
    for fila in filas:
        print(
            "| {grupo} | {moneda} | {ingresos:.2f} | {gastos:.2f} | {neto:.2f} | {registros} |".format(
                **fila
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Suma determinista de movimientos de Wallet (fallback de P6)"
    )
    parser.add_argument("--desde", required=True, help="Fecha inicial (YYYY-MM-DD o ISO 8601)")
    parser.add_argument("--hasta", help="Fecha final (YYYY-MM-DD o ISO 8601)")
    parser.add_argument("--cuenta", help="Nombre de cuenta (opcional)")
    parser.add_argument(
        "--por",
        choices=["categoria", "mes", "cuenta", "etiqueta"],
        default="categoria",
        help="Campo de agrupación",
    )
    parser.add_argument("--moneda", help="Filtrar por moneda (ej. COP)")
    parser.add_argument("--formato", choices=["md", "json"], default="md")
    parser.add_argument("--limite", type=int, help="Máximo de registros a leer (opcional)")
    args = parser.parse_args()

    try:
        client = WalletClient(verbose=False)
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        return 1

    try:
        if args.cuenta:
            cuenta = client.find_account(args.cuenta)
            if not cuenta:
                print(f"[ERROR] Cuenta no encontrada: {args.cuenta}")
                return 1
            records = client.get_records(
                cuenta["id"], args.desde, args.hasta, max_records=args.limite
            )
        else:
            records = client.get_all_records(
                args.desde, args.hasta, max_records=args.limite
            )
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        return 1

    filas = _filas(records, args.por, args.moneda)

    if args.formato == "json":
        print(
            json.dumps(
                {
                    "desde": args.desde,
                    "hasta": args.hasta,
                    "por": args.por,
                    "cuenta": args.cuenta,
                    "moneda": args.moneda,
                    "registros_leidos": len(records),
                    "filas": filas,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _print_md(filas, args, len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
