#!/usr/bin/env python3
"""Generate a versioned validation run report (fixes #129 P0-2).

Reads the persisted scenario results from ``validation-runs/<run>/scenarios.json``
(the newest run by default) and emits an executive report to
``docs/dev/validation-reports/launch-validation-<version>-<runid>.md``.

The report uses the framework ``§6`` executive-summary skeleton: verdict counts,
scenario status table, and an appendix pointer back to the framework template
and evidence catalog.  Since issue #139 it also renders a root-cause
``## Blockers`` section — every failing step of every failed scenario, with its
``llm_reason`` / ``llm_meta`` when present — and a ``## Per-step trace``
appendix with the full per-step trace table (scenario | step_index | name |
tool | status | duration | trace_id).

Usage:
    python3 scripts/validation_report.py [--version VERSION] [--run RUN_ID]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "validation-runs"
REPORTS = ROOT / "docs" / "dev" / "validation-reports"
FRAMEWORK = "docs/dev/acceptance-framework.md"
TEMPLATE = "docs/archive/launch-validation-framework.md"


def _latest_run() -> str:
    pointer = RUNS / "latest.txt"
    if pointer.exists():
        return pointer.read_text().strip()
    raise SystemExit(f"No validation runs found under {RUNS}; run scenarios with save_results first.")


def _status_counts(scenarios: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sc in scenarios:
        status = sc.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _truncate_detail(detail: Any, limit: int = 200) -> str:
    """Render a step detail for the blockers list, truncated to ~*limit* chars.

    Non-string details (e.g. the envelope dict on passed steps) are
    serialised to JSON first so the truncation applies to the text.
    """
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    if len(detail) > limit:
        return detail[:limit] + "…"
    return detail


def _escape_cell(value: str) -> str:
    """Escape pipe/newline characters so a value fits a markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")


def _iter_steps(
    scenarios: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Flatten every step of every scenario for the per-step trace table.

    Yields ``(scenario_name, step)`` pairs covering the main steps, their
    nested recovery steps (issue #138), and the cleanup steps — in that
    order — so the appendix renders the full execution trace of the run.
    """
    rows: list[tuple[str, dict[str, Any]]] = []
    for sc in scenarios:
        sc_name = sc.get("scenario", "?")
        for step in sc.get("steps", []):
            rows.append((sc_name, step))
            for rec in step.get("recovery", []):
                rows.append((sc_name, rec))
        for step in sc.get("cleanup", {}).get("steps", []):
            rows.append((sc_name, step))
    return rows


def generate(version: str, run_id: str) -> Path:
    run_dir = RUNS / run_id
    payload_path = run_dir / "scenarios.json"
    if not payload_path.exists():
        raise SystemExit(f"scenarios.json not found in {run_dir}")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    scenarios: list[dict[str, Any]] = payload.get("scenarios", [])
    counts = _status_counts(scenarios)
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    unconfigured = counts.get("unconfigured", 0)

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"launch-validation-{version}-{run_id}.md"

    lines: list[str] = []
    lines.append(f"# Launch Validation Run Report {version} ({run_id})")
    lines.append("")
    lines.append(f"> Run: {run_id} | Scenarios: {len(scenarios)} "
                 f"(passed={passed}, failed={failed}, unconfigured={unconfigured})")
    lines.append(">")
    lines.append(f"> Template: `{FRAMEWORK}` | Skeleton: `§6` | Evidence catalog: appendix of the template")
    lines.append("")
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| Scenario | Status | Passed/Total |")
    lines.append("|----------|--------|---|")
    for sc in sorted(scenarios, key=lambda x: x.get("scenario", "")):
        summary = sc.get("summary", {})
        status_str = sc.get("status", "?")
        if sc.get("regression"):
            status_str = f"{status_str} (regression)"
        lines.append(f"| {sc.get('scenario', '?')} | {status_str} "
                     f"| {summary.get('passed', 0)}/{summary.get('total', 0)} |")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    regression_failed = sum(
        1 for sc in scenarios
        if sc.get("regression") and sc.get("status") == "failed"
    )
    if failed or unconfigured:
        lines.append(f"{failed} scenario(s) failed and {unconfigured} were unconfigured; "
                     f"{passed} passed. See the per-scenario status table and the evidence "
                     f"files under `{run_dir}` for details.")
        if regression_failed:
            lines.append(f"Includes {regression_failed} regression failure(s) "
                         f"(see Regression failures section).")
    else:
        lines.append(f"All {passed} scenario(s) passed. Evidence available under `{run_dir}`.")
    lines.append("")

    # --- Regression failures section (issue #140 P1-3) -----------------------
    regression_failures = [
        sc for sc in scenarios
        if sc.get("regression") and sc.get("status") == "failed"
    ]
    lines.append("## Regression failures")
    lines.append("")
    if not regression_failures:
        lines.append("(no regression failures in this run)")
    else:
        for sc in regression_failures:
            sc_name = sc.get("scenario", "?")
            issue_ref = sc.get("regression_issue", "?")
            issue_paren = f"({issue_ref})" if issue_ref.startswith("#") else f"(#{issue_ref})"
            summary = sc.get("summary", {})
            lines.append(
                f"- `REG RGRESSION {sc_name} {issue_paren}` — "
                f"failed {summary.get('passed', 0)}/{summary.get('total', 0)} passed "
                f"({summary.get('failed', 0)} failed, "
                f"{summary.get('unconfigured', 0)} unconfigured)"
            )
    lines.append("")
    # --- Scenario leak warnings (B-03) ---
    # A leak is a hygiene failure even on a passing scenario: fixtures that
    # should have been cleaned up still live in the user's KB.  Surface them
    # regardless of scenario status.
    leak_warnings = [
        w
        for sc in scenarios
        for w in sc.get("warnings", [])
        if w.startswith("SCENARIO_LEAK")
    ]
    if leak_warnings:
        lines.append("### Scenario leak warnings (B-03)")
        lines.append("")
        for w in leak_warnings:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("## Blockers")
    lines.append("")
    failed_scenarios = [sc for sc in scenarios if sc.get("status") == "failed"]
    if not failed_scenarios:
        lines.append("(no failing scenarios in this run)")
    else:
        for sc in failed_scenarios:
            sc_name = sc.get("scenario", "?")
            for step in sc.get("steps", []):
                if step.get("status") != "failed":
                    continue
                lines.append(
                    f"- `{sc_name}` step {step.get('step_index', '?')} "
                    f"{step.get('name', '?')} ({step.get('tool', '?')}) — "
                    f"{_truncate_detail(step.get('detail'))}"
                )
                reason = step.get("llm_reason")
                if reason:
                    lines.append(f"  - llm_reason: {reason}")
                llm_meta = step.get("llm_meta")
                if llm_meta:
                    lines.append(
                        f"  - llm_meta: {json.dumps(llm_meta, ensure_ascii=False)}"
                    )
    lines.append("")
    lines.append("## Per-step trace")
    lines.append("")
    lines.append("Full per-step execution trace for every scenario — "
                 "step_index (1-based), duration (wall-clock seconds, incl. "
                 "recovery), and the run trace_id (issue #139).")
    lines.append("")
    lines.append("| Scenario | Step | Name | Tool | Status | Duration (s) | Trace ID |")
    lines.append("|----------|------|------|------|--------|--------------|----------|")
    for sc_name, step in _iter_steps(scenarios):
        dur = step.get("duration")
        dur_cell = f"{dur:.3f}" if isinstance(dur, (int, float)) else "-"
        lines.append(
            f"| {_escape_cell(sc_name)} | {step.get('step_index', '-')} "
            f"| {_escape_cell(str(step.get('name', '?')))} "
            f"| {_escape_cell(str(step.get('tool', '?')))} "
            f"| {step.get('status', '?')} | {dur_cell} "
            f"| {step.get('trace_id', '-')} |"
        )
    lines.append("")
    lines.append("## Appendix pointer")
    lines.append("")
    ev = run_dir / "evidence"
    if ev.is_dir():
        for f in sorted(ev.rglob("*")):
            if f.is_file():
                lines.append(f"- `{f.relative_to(ROOT)}`")
    else:
        lines.append(f"(no evidence subdir yet — artifacts appear under `{run_dir}` on collect)")
    lines.append("")
    lines.append("Generated by `python3 scripts/validation_report.py`.")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a versioned validation run report")
    parser.add_argument("--version", default="unreleased", help="Release/feature version label")
    parser.add_argument("--run", default="", help="Run ID (default: newest from latest.txt)")
    args = parser.parse_args()

    run_id = args.run or _latest_run()
    import os
    version = args.version or os.environ.get("AUTOINFO_VERSION", "unreleased")
    out = generate(version, run_id)
    print(f"REPORT: {out}")


if __name__ == "__main__":
    sys.exit(main())
