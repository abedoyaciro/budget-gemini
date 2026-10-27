#!/usr/bin/env python3
"""
Respaldo completo de Wallet a JSON
==================================

Copia de seguridad antes de cualquier operación destructiva o de migración.
Lee por REST (no por MCP): no gasta el presupuesto del MCP y no depende del
estado de OAuth.

Uso:
    python tools/backup_wallet.py
    python tools/backup_wallet.py --out output/backup_2026-10-26.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

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

PISO_HISTORICO = "2000-01-01T00:00:00Z"


def main() -> None:
    parser = argparse.ArgumentParser(description="Respaldo completo de Wallet a JSON")
    parser.add_argument("--out", help="Ruta de salida (por defecto output/backup_<ts>.json)")
    args = parser.parse_args()

    try:
        client = WalletClient(verbose=False)
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)

    try:
        print("Leyendo cuentas, categorías, etiquetas y registros...")
        datos = {
            "metadata": {
                "timestamp": datetime.now().astimezone().isoformat(),
                "fuente": client.base_url,
                "desde": PISO_HISTORICO,
            },
            "cuentas": client.get_accounts(),
            "categorias": client.get_categories(),
            "etiquetas": client.get_labels(),
            "registros": client.get_all_records(since_date=PISO_HISTORICO),
        }
    except WalletAPIError as exc:
        print(f"[ERROR API] {exc}")
        raise SystemExit(1)

    destino = args.out or os.path.join(
        ROOT, "output", f"backup_{datetime.now():%Y-%m-%d_%H%M%S}.json"
    )
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)

    print(
        f"\nOK · {len(datos['cuentas'])} cuentas · {len(datos['categorias'])} categorías "
        f"· {len(datos['etiquetas'])} etiquetas · {len(datos['registros'])} registros"
    )
    print(f"Guardado en: {destino}")


if __name__ == "__main__":
    main()
