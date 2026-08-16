"""Per-domain scenario coverage scanner (issue #281).

Scans ``src/autoinfo/mcp/scenarios/*.yaml`` (including the ``regression/``
subdirectory) and reports, per demo domain:

- which scenarios cover it — gathered from BOTH each scenario's
  ``requires_domain`` AND each step's ``arguments.domain``;
- **missing domains** — demo domains with zero scenario coverage;
- **undeclared step domains** — a machine-checkable mis-key: a non-throwaway
  step domain that appears in some step's ``arguments.domain`` while the
  scenario DECLARES a non-empty ``requires_domain`` that omits it
  (e.g. ``sources-a6-keyed.yaml`` declared ``["medical-research"]`` but its
  steps target ``financial-intelligence``).  Scenarios without a
  ``requires_domain`` are domain-agnostic by design and are never flagged.

Throwaway fixture domains (``THROWAWAY_DOMAINS``) are whitelisted from both
checks — they are intentional negative/throwaway fixtures (error-boundary's
``nonexistent-domain-xyz``, promotion-triggers' ``t9-sweep``, the regression
noop domains) and must never count as missing or undeclared.

Exit code 0 when both checks pass, 1 otherwise.

Run from the project root: ``python3 scripts/scenario_domain_coverage.py``
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

SCENARIOS_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "autoinfo" / "mcp" / "scenarios"
)

DEMO_DOMAINS: list[str] = [
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

# Intentional negative/throwaway fixtures used by error-boundary.yaml
# (nonexistent-domain-xyz), promotion-triggers.yaml (t9-sweep) and the
# regression scenarios (regression-121/126-noop-domain).  Never accounted
# as missing or undeclared.
THROWAWAY_DOMAINS: frozenset[str] = frozenset(
    {
        "t9-sweep",
        "nonexistent-domain-xyz",
        "regression-121-noop-domain",
        "regression-126-noop-domain",
    }
)


def demo_domains() -> list[str]:
    """The exact 13 demo domains shipped with AutoInfo."""
    return list(DEMO_DOMAINS)


def _step_domains(step: dict[str, Any]) -> set[str]:
    """Step domains declared via ``arguments.domain`` (strings only)."""
    args = step.get("arguments")
    if not isinstance(args, dict):
        return set()
    dom = args.get("domain")
    return {dom} if isinstance(dom, str) else set()


def scan_scenario_domains(scenarios_dir: Path) -> dict[str, list[str]]:
    """Map domain -> sorted scenario names covering it.

    A scenario covers a domain when the domain appears in its
    ``requires_domain`` OR in any step's ``arguments.domain``.  Scans
    ``*.yaml`` recursively (the ``regression/`` subdirectory included).
    """
    coverage: dict[str, set[str]] = {}
    for yf in sorted(scenarios_dir.rglob("*.yaml")):
        data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        name = data.get("name") or yf.stem
        domains: set[str] = set(data.get("requires_domain") or [])
        for step in data.get("steps") or []:
            if isinstance(step, dict):
                domains |= _step_domains(step)
        for dom in domains:
            coverage.setdefault(dom, set()).add(name)
    return {d: sorted(names) for d, names in sorted(coverage.items())}


def missing_domains(scenarios_dir: Path | None = None) -> list[str]:
    """Demo domains with zero scenario coverage (sorted; empty when 13/13)."""
    scenarios_dir = scenarios_dir or SCENARIOS_DIR
    coverage = scan_scenario_domains(scenarios_dir)
    return [d for d in demo_domains() if d not in coverage]


def undeclared_step_domains(
    scenarios_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Scenario -> step domains it targets without declaring in requires_domain.

    Only scenarios with a NON-empty ``requires_domain`` can be mis-keyed: a
    step domain not in the declared list is a mis-key.  Scenarios with no
    ``requires_domain`` are domain-agnostic by design (kb-access,
    cron-schedules, ...) and are never flagged.  Throwaway domains are
    whitelisted and never flagged.
    """
    scenarios_dir = scenarios_dir or SCENARIOS_DIR
    undeclared: dict[str, list[str]] = {}
    for yf in sorted(scenarios_dir.rglob("*.yaml")):
        data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        declared = set(data.get("requires_domain") or [])
        if not declared:
            continue
        name = data.get("name") or yf.stem
        step_domains: set[str] = set()
        for step in data.get("steps") or []:
            if isinstance(step, dict):
                step_domains |= _step_domains(step)
        flagged = sorted(
            (step_domains - declared) - THROWAWAY_DOMAINS
        )
        if flagged:
            undeclared[name] = flagged
    return undeclared


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv[1:]) if argv else []
    scenarios_dir = Path(args[0]) if args else SCENARIOS_DIR

    coverage = scan_scenario_domains(scenarios_dir)
    missing = missing_domains(scenarios_dir)
    undeclared = undeclared_step_domains(scenarios_dir)
    covered = len(demo_domains()) - len(missing)

    print("Scenario domain coverage (per-domain table)")
    print("=" * 60)
    print(f"{'domain':<24}{'scenarios':>10}")
    for d in demo_domains():
        print(f"{d:<24}{len(coverage.get(d, [])):>10}")
    print(f"Demo domains covered: {covered}/{len(demo_domains())}")

    ok = True
    if missing:
        ok = False
        print(f"\nMISSING demo domains ({len(missing)}):")
        for d in missing:
            print(f"  - {d}")

    if undeclared:
        ok = False
        print(f"\nUNDECLARED step domains ({len(undeclared)} scenarios):")
        for name in sorted(undeclared):
            print(f"  - {name}: {undeclared[name]}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
