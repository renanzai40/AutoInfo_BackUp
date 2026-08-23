"""Scenario outcome-audit: D-工-5 evidence for the best-practice review.

Static audit of the validation scenario library in
``src/autoinfo/mcp/scenarios/`` (65 functional + 51 regression) against the
Anthropic-derived "grade the outcome, not the path" discipline (D-工-5 in
``docs/dev/best-practice-review.md``):

- **Outcome grading** — every step must assert the *outcome envelope*
  (``success`` or ``error_code``/``error_actionable``), not just that a call
  happened. A step with no ``success`` key grades the path only.
- **Error-path depth** — error steps (``success: false``) should pin the
  ``error_code`` and, where remediation guidance matters, assert
  ``error_actionable`` (issue #141).
- **Isolation / anti-cheat gating** — steps that need an external
  prerequisite must declare it in the scenario header so the engine reports
  ``unconfigured`` instead of silently passing: ``kind: http`` steps need
  ``requires_http``; ``llm_assert`` steps need ``requires_env`` carrying an
  LLM key; ``collect_artifacts`` scenarios need nothing extra.

Run from the project root: ``python3 scripts/scenario_outcome_audit.py``

Writes a timestamped report to
``validation-runs/coverage/scenario-outcome-<date>.json`` and prints a
summary to stdout. Pure static YAML analysis — no server imports, no LLM.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "src" / "autoinfo" / "mcp" / "scenarios"
OUT_DIR = ROOT / "validation-runs" / "coverage"

# Env prerequisites that gate LLM-dependent steps (unconfigured reporting).
LLM_ENV_KEYS = ("AUTOINFO_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

STEP_KINDS = ("mcp", "cli", "http")


def _scenario_files() -> list[Path]:
    """All scenario YAML files (recursive — picks up regression/)."""
    return sorted(SCENARIOS_DIR.rglob("*.yaml"))


def audit_scenario(file_path: Path) -> dict[str, Any] | None:
    """Audit one scenario file; returns None if unparseable."""
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or "steps" not in data:
        return None

    steps = data.get("steps", []) or []
    requires_env = list(data.get("requires_env", []) or [])
    requires_http = list(data.get("requires_http", []) or [])
    requires_domain = list(data.get("requires_domain", []) or [])
    is_regression = bool(data.get("regression", False))

    step_rows: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        expect = step.get("expect") or {}
        kind = step.get("kind", "mcp")
        is_error = expect.get("success") is False
        has_success_key = "success" in expect
        has_code = expect.get("error_code") is not None
        has_actionable = expect.get("error_actionable") is not None
        has_data_assert = any(
            k in expect
            for k in ("data_has", "exit_code", "stdout_has", "stderr_has",
                      "status_code", "json_has", "llm_assert")
        )
        has_llm_assert = expect.get("llm_assert") is not None
        is_http = kind == "http"

        step_rows.append({
            "index": i,
            "name": step.get("name", ""),
            "kind": kind,
            "tool": step.get("tool", ""),
            "has_success_key": has_success_key,
            "success": expect.get("success"),
            "is_error": is_error,
            "has_error_code": has_code,
            "has_error_actionable": has_actionable,
            "has_data_assert": has_data_assert,
            "has_llm_assert": has_llm_assert,
            "is_http": is_http,
        })

    # Step-level violations -------------------------------------------------
    grade_path_only = [r for r in step_rows if not r["has_success_key"]]
    error_without_code = [
        r for r in step_rows if r["is_error"] and not r["has_error_code"]
    ]
    error_without_actionable = [
        r for r in step_rows if r["is_error"] and not r["has_error_actionable"]
    ]
    success_without_assert = [
        r for r in step_rows
        if r["success"] is True and not r["has_data_assert"]
    ]
    llm_assert_ungated = [
        r for r in step_rows
        if r["has_llm_assert"] and not any(k in requires_env for k in LLM_ENV_KEYS)
    ]
    http_ungated = [
        r for r in step_rows if r["is_http"] and not requires_http
    ]

    return {
        "file": file_path.name,
        "name": data.get("name", file_path.stem),
        "category": data.get("category", ""),
        "is_regression": is_regression,
        "step_count": len(step_rows),
        "requires_env": requires_env,
        "requires_http": requires_http,
        "requires_domain": requires_domain,
        "violations": {
            "grade_path_only": [r["index"] for r in grade_path_only],
            "error_without_code": [r["index"] for r in error_without_code],
            "error_without_actionable": [
                r["index"] for r in error_without_actionable
            ],
            "success_without_assert": [r["index"] for r in success_without_assert],
            "llm_assert_ungated": [r["index"] for r in llm_assert_ungated],
            "http_ungated": [r["index"] for r in http_ungated],
        },
        "steps": step_rows,
    }


def audit_all() -> dict[str, Any]:
    """Audit every scenario file and aggregate the D-工-5 metrics."""
    scenarios: list[dict[str, Any]] = []
    for f in _scenario_files():
        audited = audit_scenario(f)
        if audited is not None:
            scenarios.append(audited)

    all_steps: list[dict[str, Any]] = []
    for sc in scenarios:
        all_steps.extend(sc["steps"])
    agg: dict[str, Any] = {
        "total_scenarios": len(scenarios),
        "total_steps": len(all_steps),
        "regression_scenarios": sum(1 for s in scenarios if s["is_regression"]),
        "steps_grading_outcome": sum(1 for s in all_steps if s["has_success_key"]),
        "steps_grade_path_only": sum(1 for s in all_steps if not s["has_success_key"]),
        "error_steps": sum(1 for s in all_steps if s["is_error"]),
        "error_steps_with_code": sum(
            1 for s in all_steps if s["is_error"] and s["has_error_code"]
        ),
        "error_steps_with_actionable": sum(
            1 for s in all_steps if s["is_error"] and s["has_error_actionable"]
        ),
        "success_steps_without_assert": sum(
            1 for s in all_steps if s["success"] is True and not s["has_data_assert"]
        ),
        "llm_assert_steps": sum(1 for s in all_steps if s["has_llm_assert"]),
        "llm_assert_ungated": sum(
            len(sc["violations"]["llm_assert_ungated"]) for sc in scenarios
        ),
        "http_steps": sum(1 for s in all_steps if s["is_http"]),
        "http_ungated": sum(
            len(sc["violations"]["http_ungated"]) for sc in scenarios
        ),
        "scenarios_with_env_gate": sum(1 for s in scenarios if s["requires_env"]),
        "scenarios_with_http_gate": sum(1 for s in scenarios if s["requires_http"]),
        "scenarios_with_llm_gate": sum(
            1 for s in scenarios if any(k in s["requires_env"] for k in LLM_ENV_KEYS)
        ),
    }
    return {"summary": agg, "scenarios": scenarios}


def main() -> int:
    result = audit_all()
    s = result["summary"]

    print(f"Scenario outcome-audit (D-工-5) — {datetime.date.today().isoformat()}")
    print(f"Scenarios: {s['total_scenarios']} "
          f"(regression: {s['regression_scenarios']}), "
          f"steps: {s['total_steps']}")
    print(f"Steps grading outcome (explicit success): "
          f"{s['steps_grading_outcome']} "
          f"({s['steps_grading_outcome'] / max(s['total_steps'], 1):.1%})")
    print(f"Steps grade-path-only (no success key): {s['steps_grade_path_only']}")
    print(f"Error steps: {s['error_steps']} — with code: "
          f"{s['error_steps_with_code']}, with actionable: "
          f"{s['error_steps_with_actionable']}")
    print(f"Success steps without data assert: {s['success_steps_without_assert']}")
    print(f"llm_assert steps: {s['llm_assert_steps']} (ungated: {s['llm_assert_ungated']})")
    print(f"http steps: {s['http_steps']} (ungated: {s['http_ungated']})")
    print(f"Env-gated scenarios: {s['scenarios_with_env_gate']} "
          f"(LLM-gated: {s['scenarios_with_llm_gate']})")

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"scenario-outcome-{datetime.date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
