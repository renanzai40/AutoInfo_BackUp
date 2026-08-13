"""Integration test: doc_inventory.py --check stays green (docs-as-code gate).

Runs ``scripts/doc_inventory.py --check`` and asserts exit 0. This is the
self-enforcement gate that keeps the drift-prone facts in README.md, AGENTS.md
and the doc-manager skill (SKILL.md) mutually consistent, so a doc-sync wave
can never silently leave the skill's own numbers stale again.

Reference: .opencode/skills/doc-manager-skill/SKILL.md §3 Step 4 (verify step).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "doc_inventory.py"


def test_doc_inventory_check_passes() -> None:
    """--check must exit 0: README↔AGENTS↔SKILL facts agree, no stray files."""
    assert SCRIPT.exists(), f"Missing: {SCRIPT}"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"doc_inventory.py --check failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
