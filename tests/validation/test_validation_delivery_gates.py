"""Tests for scripts/validation_delivery.py #70 delivery gates.

Covers the two new packaging gates:
- ``_template_leak_scan`` — detects UNRENDERED Python template expressions
  (``{datetime.datetime.now().isoformat()[:19]}``) anchored on Python
  signatures so legit Markdown ``{keyword}`` / JSON ``{{"a": 1}}`` never fire.
- ``_honesty_gate`` — cross-checks a README's "clean" claim against the
  delivered product files for ``Relevance —/100`` placeholders and residual
  HTML tags.
- ``--check-readme`` CLI flag — standalone gate run that exits before any
  scenario execution (no LLM needed).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Load the real scripts/validation_delivery.py (same pattern as the sibling
# test_validation_delivery.py) so the tests exercise the script's own code.
_SPEC = importlib.util.spec_from_file_location(
    "validation_delivery", ROOT / "scripts" / "validation_delivery.py"
)
assert _SPEC is not None and _SPEC.loader is not None
vd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vd)


# ---------------------------------------------------------------------------
# _template_leak_scan
# ---------------------------------------------------------------------------

def test_template_leak_gate_rejects_leaked_readme():
    text = "生成时间:{datetime.datetime.now().isoformat()[:19]}"
    findings = vd._template_leak_scan(text, source="README.md")
    assert findings, "expected the unrendered datetime expression to be flagged"
    assert "README.md" in findings[0]
    assert "datetime" in findings[0] or "isoformat" in findings[0]


def test_clean_readme_passes_gate():
    text = (
        "# Report\n\n"
        "The {keyword} was rendered.\n"
        'JSON: {{"a": 1}}.\n\n'
        "```json\n"
        '{"key": "value", "nested": {"x": [1, 2]}}\n'
        "```\n"
    )
    assert vd._template_leak_scan(text, source="README.md") == []


# ---------------------------------------------------------------------------
# _honesty_gate
# ---------------------------------------------------------------------------

def test_honesty_gate_fails_clean_claim_with_placeholders():
    readme = "# Delivery Report\n\n152/152 clean — all gates passed."
    artifacts = {
        "digest.md": "| **Relevance** | —/100 |\n| **Tags** | — |",
    }
    failures = vd._honesty_gate(readme, artifacts)
    assert failures, "expected honesty gate to flag the placeholder artifacts"
    assert "honesty" in failures[0]
    assert "digest.md" in failures[0]


def test_honesty_gate_passes_without_claim():
    readme = "# Delivery Report\n\nAll scenarios executed and artifacts packaged."
    artifacts = {
        "digest.md": "| **Relevance** | —/100 |\n| **Tags** | — |",
    }
    assert vd._honesty_gate(readme, artifacts) == []


def test_honesty_gate_passes_clean_claim_with_clean_artifacts():
    readme = "# Delivery Report\n\n152/152 clean — all gates passed."
    artifacts = {
        "digest.md": "# Medical Digest\n\nAll relevance scores rendered as 87/100.",
    }
    assert vd._honesty_gate(readme, artifacts) == []


# ---------------------------------------------------------------------------
# --check-readme CLI flag
# ---------------------------------------------------------------------------

@pytest.fixture
def _check_readme_runner():
    def _run(readme_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "scripts/validation_delivery.py", "--check-readme",
             str(readme_dir / "README.md")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    return _run


def test_check_readme_flag_validates_existing_readme(tmp_path, _check_readme_runner):
    # Leaked template in the README + placeholder products -> exit 1.
    leaked_dir = tmp_path / "leaked"
    leaked_dir.mkdir()
    (leaked_dir / "README.md").write_text(
        "# Delivery Report\n\n"
        "生成时间:{datetime.datetime.now().isoformat()[:19]}\n\n"
        "152/152 clean\n",
        encoding="utf-8",
    )
    (leaked_dir / "product.md").write_text(
        "| **Relevance** | —/100 |\n", encoding="utf-8",
    )
    leaked = _check_readme_runner(leaked_dir)
    assert leaked.returncode == 1, f"expected exit 1, got {leaked.returncode}:\n{leaked.stderr}"
    combined = leaked.stdout + leaked.stderr
    assert "isoformat" in combined or "datetime" in combined

    # Clean README + clean products -> exit 0.
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "README.md").write_text(
        "# Delivery Report\n\n152/152 scenarios clean\n",
        encoding="utf-8",
    )
    (clean_dir / "product.md").write_text(
        "# Product\n\nAll values rendered.\n", encoding="utf-8",
    )
    clean = _check_readme_runner(clean_dir)
    assert clean.returncode == 0, f"expected exit 0, got {clean.returncode}:\n{clean.stderr}"
