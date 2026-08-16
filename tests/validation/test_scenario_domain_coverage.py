"""Per-domain scenario coverage scanner tests (issue #281).

Locks the behavior of ``scripts/scenario_domain_coverage.py``:

1. **Pure-function tests** against a fixture tmp dir: ``missing_domains``
   (demo domain with zero scenario coverage) and ``undeclared_step_domains``
   (a scenario's step domain missing from its own ``requires_domain``) are
   computed from BOTH ``requires_domain`` and each step's
   ``arguments.domain``.  Throwaway fixtures (``THROWAWAY_DOMAINS``) are
   whitelisted from every accounting — they are intentional negative/throwaway
   domains (t9-sweep, nonexistent-domain-xyz, regression-121-noop-domain,
   regression-126-noop-domain), never coverage.
2. **Live assertions** against the REAL ``src/autoinfo/mcp/scenarios``: all
   13 demo domains are covered by at least one scenario and no scenario pins
   a ``requires_domain`` that omits a domain its steps target (machine-
   checkable mis-key; sources-a6-keyed.yaml was the offender, re-keyed).
3. **CLI contract**: the script prints the per-domain table and exits 0 only
   when both checks pass; ``coverage_audit.py`` surfaces the metric line.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCAN_SCRIPT = ROOT / "scripts" / "scenario_domain_coverage.py"
AUDIT_SCRIPT = ROOT / "scripts" / "coverage_audit.py"
SCENARIOS_DIR = ROOT / "src" / "autoinfo" / "mcp" / "scenarios"

DEMO_DOMAINS = [
    "medical-research",
    "ai-commercial",
    "financial-intelligence",
    "tech-ai-developer",
    "language-learning",
    "online-video",
    "financial-news",
    "online-education",
    "legal-compliance",
    "general-news",
    "gaming",
    "b2b",
    "retail",
]


@pytest.fixture(scope="module")
def scanner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scenario_domain_coverage", SCAN_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_scenario(
    dirpath: Path, name: str, requires_domain: list[str], step_domains: list[str]
) -> Path:
    steps = [
        {
            "name": f"get_domain_schema for {d}",
            "tool": "get_domain_schema",
            "kind": "mcp",
            "arguments": {"domain": d},
            "expect": {"success": True},
        }
        for d in step_domains
    ]
    p = dirpath / f"{name}.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "description": f"{name} fixture scenario",
                "requires_domain": requires_domain,
                "steps": steps,
            }
        ),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Pure-function tests (fixture tmp dir)
# ---------------------------------------------------------------------------


def test_demo_domains_is_exact_13(scanner: Any) -> None:
    assert scanner.demo_domains() == DEMO_DOMAINS
    assert len(scanner.demo_domains()) == 13


def test_scan_reports_missing_and_undeclared(scanner: Any, tmp_path: Path) -> None:
    """2 scenarios covering 2 demo domains, plus a throwaway step domain and
    an undeclared (non-throwaway) step domain -> both checks report exactly
    what the scanner is designed to flag."""
    _write_scenario(
        tmp_path,
        "alpha",
        ["medical-research"],
        ["medical-research"],
    )
    _write_scenario(
        tmp_path,
        "beta",
        ["ai-commercial"],
        ["ai-commercial", "t9-sweep", "financial-intelligence"],
    )

    coverage = scanner.scan_scenario_domains(tmp_path)
    assert coverage["medical-research"] == ["alpha"]
    assert coverage["ai-commercial"] == ["beta"]
    # Throwaway domains still appear in the raw coverage map (they are real
    # step domains) but must never surface in either check.
    assert coverage["t9-sweep"] == ["beta"]

    missing = scanner.missing_domains(tmp_path)
    # financial-intelligence is covered by beta's (undeclared) step domain —
    # the raw map includes step arguments.domain by spec; the undeclared
    # flag is a declaration-hygiene check, not a coverage-absence check.
    assert missing == [
        d
        for d in DEMO_DOMAINS
        if d
        not in (
            "medical-research",
            "ai-commercial",
            "financial-intelligence",
        )
    ]
    assert len(missing) == 10

    undeclared = scanner.undeclared_step_domains(tmp_path)
    # financial-intelligence: beta's step targets it but requires_domain only
    # declares ai-commercial -> flagged.  t9-sweep: throwaway -> whitelisted.
    assert undeclared == {"beta": ["financial-intelligence"]}


def test_throwaway_and_agnostic_scenarios_never_flagged(
    scanner: Any, tmp_path: Path
) -> None:
    """A scenario whose steps only use throwaway domains, and a scenario with
    NO requires_domain at all (domain-agnostic by design, e.g. kb-access /
    cron-schedules style) must never be reported as undeclared."""
    _write_scenario(
        tmp_path,
        "sweep",
        [],
        [
            "t9-sweep",
            "nonexistent-domain-xyz",
            "regression-121-noop-domain",
            "regression-126-noop-domain",
        ],
    )
    _write_scenario(tmp_path, "agnostic", [], ["medical-research"])

    assert scanner.undeclared_step_domains(tmp_path) == {}
    # Throwaway domains are not demo domains, so they cannot appear in
    # missing_domains either.
    assert all(d not in scanner.missing_domains(tmp_path) for d in scanner.THROWAWAY_DOMAINS)
    assert scanner.THROWAWAY_DOMAINS == frozenset(
        {
            "t9-sweep",
            "nonexistent-domain-xyz",
            "regression-121-noop-domain",
            "regression-126-noop-domain",
        }
    )


def test_undeclared_requires_negative_requires_domain(scanner: Any, tmp_path: Path) -> None:
    """The undeclared-step-domain check is a *mis-key* check: it fires only
    when a scenario DECLARES a non-empty requires_domain that omits a domain
    its steps target.  A scenario with no requires_domain is domain-agnostic
    by design and is never flagged."""
    _write_scenario(tmp_path, "mis-keyed", ["medical-research"], ["financial-intelligence"])
    assert scanner.undeclared_step_domains(tmp_path) == {"mis-keyed": ["financial-intelligence"]}

    _write_scenario(tmp_path, "no-decl", [], ["financial-intelligence"])
    assert scanner.undeclared_step_domains(tmp_path) == {"mis-keyed": ["financial-intelligence"]}


# ---------------------------------------------------------------------------
# Live assertions against the REAL scenario library (RED -> GREEN for #281)
# ---------------------------------------------------------------------------


def test_live_all_13_demo_domains_covered(scanner: Any) -> None:
    missing = scanner.missing_domains(SCENARIOS_DIR)
    assert missing == [], f"demo domains with zero scenario coverage: {missing}"


def test_live_no_undeclared_step_domains(scanner: Any) -> None:
    undeclared = scanner.undeclared_step_domains(SCENARIOS_DIR)
    assert undeclared == {}, f"scenarios with undeclared step domains: {undeclared}"


def test_live_cli_exits_zero_and_prints_13_13() -> None:
    result = subprocess.run(
        [sys.executable, str(SCAN_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "13/13" in result.stdout


def test_live_coverage_audit_prints_domain_metric() -> None:
    """coverage_audit.py must surface the scanner metric after the
    'Regression scenarios:' line."""
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Scenario domain coverage: 13/13 demo domains" in result.stdout
    lines = result.stdout.splitlines()
    regr_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("Regression scenarios:")
    )
    metric_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("Scenario domain coverage:")
    )
    assert metric_idx > regr_idx
