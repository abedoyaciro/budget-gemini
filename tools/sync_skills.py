#!/usr/bin/env python3
"""
Sincroniza la skill canónica de OpenCode hacia Hermes
=====================================================

Fuente única: .opencode/skills/wallet/SKILL.md
Destino:      .hermes/skills/wallet/SKILL.md

Hermes carga skills repo-local desde ./.hermes/skills (y ./.agents/skills)
cuando el repo está "trusted" con `hermes skills trust .`.

Uso:
    python tools/sync_skills.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".opencode" / "skills" / "wallet" / "SKILL.md"
DESTS = [ROOT / ".hermes" / "skills" / "wallet" / "SKILL.md"]


def main() -> int:
    if not SRC.exists():
        print(f"[ERROR] Falta la skill canónica: {SRC}", file=sys.stderr)
        return 1
    for dst in DESTS:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC, dst)
        print(f"Sincronizada: {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
