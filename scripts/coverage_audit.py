"""Coverage audit: which of the 146 MCP tools are exercised by scenarios.

Run from the project root: ``python3 scripts/coverage_audit.py``

Writes a timestamped report to ``validation-runs/coverage/coverage-<date>.json``
and prints the same summary to stdout (fixes #129 P1-5, #134 counting bug).

Counting semantics (fixes the phantom-inflated ``covered`` set):

- ``declared``  = tool names from ``Tool(name="...")`` in server.py
- ``scenario_used`` = tool names of every ``kind: mcp`` (default) step across
  all scenario YAMLs.  This set MAY contain phantoms — tool names that no
  server tool declares (e.g. ``definitely_not_a_real_tool`` used by
  error-boundary.yaml to exercise the UnknownTool error path).
- ``covered = declared & scenario_used`` — intersection only, so a phantom
  tool can never count as coverage for a real declared tool.
- ``missing = declared - covered`` — the genuinely-uncovered tools.
- ``phantom = scenario_used - declared`` — informational only; phantoms are
  expected (error-boundary scenarios deliberately reference them) and are
  NOT reported as missing.
"""
import datetime
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src/autoinfo/mcp/server.py"
SCN = ROOT / "src/autoinfo/mcp/scenarios"


def compute_coverage(server_src: str, scenarios_dir: Path) -> dict[str, Any]:
    """Count scenario coverage from server source and scenario YAMLs.

    Parameters
    ----------
    server_src:
        Contents of ``src/autoinfo/mcp/server.py``; declared tools are the
        ``Tool(name="...")`` call sites.
    scenarios_dir:
        Directory holding the ``*.yaml`` scenario files.

    Returns
    -------
    dict
        With keys ``declared``, ``scenario_used``, ``covered`` (= declared ∩
        scenario_used), ``missing`` (= declared - covered), ``phantom``
        (= scenario_used - declared), and ``scenario_names``.  All tool lists
        are sorted.
    """
    declared = sorted(set(re.findall(r'Tool\(\s*name="(\w+)"', server_src)))

    scenario_used: set[str] = set()
    scenario_names: list[str] = []
    for yf in sorted(scenarios_dir.rglob("*.yaml")):
        data = yaml.safe_load(yf.read_text())
        scenario_names.append(data.get("name"))
        for step in data.get("steps", []):
            if step.get("kind", "mcp") == "mcp":
                tool = step.get("tool")
                if tool:
                    scenario_used.add(tool)

    declared_set = set(declared)
    return {
        "declared": declared,
        "scenario_used": sorted(scenario_used),
        "covered": sorted(declared_set & scenario_used),
        "missing": sorted(declared_set - scenario_used),
        "phantom": sorted(scenario_used - declared_set),
        "scenario_names": scenario_names,
    }


def main() -> None:
    cov = compute_coverage(SRC.read_text(), SCN)
    print(f"Total MCP tools declared: {len(cov['declared'])}")
    print(f"Covered by scenarios: {len(cov['covered'])}/{len(cov['declared'])}")
    print(f"Scenarios: {len(cov['scenario_names'])}")
    print(f"MISSING tools ({len(cov['missing'])}):")
    for t in cov["missing"]:
        print(f"  - {t}")
    print(f"Phantom scenario tools (not declared; informational): {len(cov['phantom'])}")
    for t in cov["phantom"]:
        print(f"  - {t}")

    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "src"))
        from autoinfo.mcp.validation import load_scenarios as _load_scenarios
        _all_scenarios = _load_scenarios()
        _regr = [s for s in _all_scenarios if s.get("regression")]
        _regr_issues = [s.get("regression_issue", "?") for s in _regr]
        print(f"Regression scenarios: {len(_regr)} (issues: {', '.join(_regr_issues)})")
    except Exception:
        print("Regression scenarios: (unable to load)")

    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import scenario_domain_coverage as _sdc
        _covered = len(_sdc.demo_domains()) - len(_sdc.missing_domains())
        print(
            f"Scenario domain coverage: {_covered}/{len(_sdc.demo_domains())} demo domains"
        )
    except Exception:
        print("Scenario domain coverage: (unable to load)")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = ROOT / "validation-runs" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"coverage-{stamp}.json"
    payload = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_tools": len(cov["declared"]),
        "covered_tools": len(cov["covered"]),
        "missing_tools": cov["missing"],
        "phantom_tools": cov["phantom"],
        "scenario_count": len(cov["scenario_names"]),
        "scenario_names": cov["scenario_names"],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Coverage report: {out_path}")


if __name__ == "__main__":
    main()
