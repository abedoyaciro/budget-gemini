"""La copia de la skill para Hermes debe coincidir con la canónica de OpenCode.

Una sola fuente de verdad: .opencode/skills/wallet/SKILL.md.
Si editas la skill, corre scripts/sync_skills.py (o budget.ps1 sync-skills).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICA = ROOT / ".opencode" / "skills" / "wallet" / "SKILL.md"
HERMES = ROOT / ".hermes" / "skills" / "wallet" / "SKILL.md"


def test_skill_canonica_existe():
    assert CANONICA.is_file(), f"Falta la skill canónica: {CANONICA}"


def test_copia_hermes_existe():
    assert HERMES.is_file(), (
        "Falta .hermes/skills/wallet/SKILL.md. "
        "Corre: python tools/sync_skills.py"
    )


def test_copias_sincronizadas():
    canonica = CANONICA.read_text(encoding="utf-8")
    hermes = HERMES.read_text(encoding="utf-8")
    assert hermes == canonica, (
        "La copia de Hermes está desincronizada con .opencode. "
        "Corre: python tools/sync_skills.py"
    )
