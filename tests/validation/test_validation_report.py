"""Tests for scripts/validation_report.py report generation (issue #139).

Covers:
- ``generate`` renders the root-cause ``## Blockers`` section — every failing
  step of every failed scenario listed as ``<scenario> step <index> <name>
  (<tool>) — <detail>`` with ``llm_reason`` / ``llm_meta`` appended when
  present — and the ``## Per-step trace`` appendix with the full trace table
  (scenario | step_index | name | tool | status | duration | trace_id).
- The verdict table, executive summary, and appendix pointer sections stay
  intact.

The script's ``RUNS`` / ``REPORTS`` module globals are monkeypatched to
``tmp_path`` so the tests never touch the real ``validation-runs/`` tree.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Load the real scripts/validation_report.py (same pattern as the sibling
# test_validation_delivery.py) so the tests exercise the script's own code.
_SPEC = importlib.util.spec_from_file_location(
    "validation_report", ROOT / "scripts" / "validation_report.py"
)
assert _SPEC is not None and _SPEC.loader is not None
vr = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(vr)


def _step(
    name: str,
    tool: str,
    status: str,
    detail: Any,
    step_index: int,
    trace_id: str,
    duration: float,
    **extra: Any,
) -> dict[str, Any]:
    """Build a scenario step result dict shaped like run_scenario's output."""
    step: dict[str, Any] = {
        "name": name,
        "tool": tool,
        "status": status,
        "detail": detail,
        "step_index": step_index,
        "duration": duration,
        "arguments": {},
        "trace_id": trace_id,
    }
    step.update(extra)
    return step


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """A tmp validation-runs tree with one scenarios.json fixture run."""
    run_dir = tmp_path / "validation-runs" / "2026-08-06_120000_000001"
    run_dir.mkdir(parents=True)
    trace_id = "11111111-2222-4333-8444-555555555555"
    scenarios: list[dict[str, Any]] = [
        {
            "scenario": "alpha-pass",
            "description": "Passing scenario",
            "category": "general",
            "status": "passed",
            "summary": {"passed": 1, "failed": 0, "unconfigured": 0,
                        "recovered": 0, "total": 1},
            "trace_id": trace_id,
            "steps": [
                _step("collect data", "test_source", "passed",
                      {"success": True, "data": {"ok": True}}, 1, trace_id, 0.123),
            ],
        },
        {
            "scenario": "beta-fail",
            "description": "Failing scenario",
            "category": "general",
            "status": "failed",
            "summary": {"passed": 0, "failed": 2, "unconfigured": 0,
                        "recovered": 0, "total": 2},
            "trace_id": trace_id,
            "steps": [
                _step("llm verify", "classify_cefr", "failed",
                      "llm_assert FAILED: level mismatch. Tool output: ...", 1,
                      trace_id, 1.234,
                      llm_reason="level mismatch",
                      llm_meta={"model": "deepseek/deepseek-chat",
                                "tokens": {"prompt_tokens": 10, "total_tokens": 25},
                                "duration": 0.5}),
                _step("long detail step", "collect_sources", "failed",
                      "x" * 500, 2, trace_id, 0.456),
            ],
        },
        {
            "scenario": "gamma-gated",
            "description": "Env-gated scenario",
            "category": "general",
            "status": "unconfigured",
            "summary": {"passed": 0, "failed": 0, "unconfigured": 1,
                        "recovered": 0, "total": 1},
            "trace_id": trace_id,
            "steps": [
                _step("gated step", "health_check", "unconfigured",
                      "missing required env var(s): X", 1, trace_id, 0.0),
            ],
        },
    ]
    payload = {
        "run_id": run_dir.name,
        "timestamp": "2026-08-06T12:00:00",
        "scenarios": scenarios,
    }
    (run_dir / "scenarios.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def report(runs_dir: Path, monkeypatch) -> Path:
    """Generate the report against the tmp fixture and return its path."""
    monkeypatch.setattr(vr, "RUNS", runs_dir / "validation-runs")
    monkeypatch.setattr(vr, "REPORTS", runs_dir / "reports")
    return vr.generate(version="1.0", run_id="2026-08-06_120000_000001")


class TestValidationReport:
    """Report generation against a tmp scenarios.json fixture."""

    def test_report_written_to_tmp_reports(self, report: Path) -> None:
        """The report lands under the monkeypatched REPORTS dir."""
        assert report.exists()
        assert report.parent.name == "reports"
        assert report.name.startswith("launch-validation-1.0-")

    def test_verdict_table_and_executive_summary_kept(self, report: Path) -> None:
        """The verdict table, executive summary, and appendix pointer remain."""
        text = report.read_text(encoding="utf-8")
        assert "## Verdicts" in text
        assert "| Scenario | Status | Passed/Total |" in text
        assert "| alpha-pass | passed | 1/1 |" in text
        assert "| beta-fail | failed | 0/2 |" in text
        assert "## Executive summary" in text
        assert "1 scenario(s) failed and 1 were unconfigured; 1 passed." in text
        assert "## Appendix pointer" in text
        assert "Generated by" in text

    def test_blockers_lists_failing_steps_by_name_and_tool(self, report: Path) -> None:
        """Failed steps appear as `<scenario> step <i> <name> (<tool>) — detail`."""
        text = report.read_text(encoding="utf-8")
        assert "## Blockers" in text
        # Only the failed scenario contributes blocker lines.
        assert "`beta-fail` step 1 llm verify (classify_cefr)" in text
        assert "`beta-fail` step 2 long detail step (collect_sources)" in text
        # Passing / unconfigured scenarios are not listed.
        assert "alpha-pass` step" not in text
        assert "gamma-gated` step" not in text

    def test_blockers_appends_llm_reason_and_llm_meta(self, report: Path) -> None:
        """llm_reason / llm_meta are appended when present on the step."""
        text = report.read_text(encoding="utf-8")
        assert "llm_reason: level mismatch" in text
        assert 'llm_meta: {"model": "deepseek/deepseek-chat"' in text
        assert '"prompt_tokens": 10' in text

    def test_blockers_truncates_long_details(self, report: Path) -> None:
        """Details longer than ~200 chars are truncated."""
        text = report.read_text(encoding="utf-8")
        blockers = text.split("## Blockers", 1)[1].split("## Per-step trace", 1)[0]
        line = [ln for ln in blockers.splitlines() if "long detail step" in ln][0]
        assert "…" in line
        # ~200-char detail + the ~80-char prefix/suffix renders < 320 total.
        assert len(line) < 320

    def test_per_step_trace_appendix(self, report: Path) -> None:
        """The per-step trace table exposes the new trace fields per scenario."""
        text = report.read_text(encoding="utf-8")
        assert "## Per-step trace" in text
        assert "| Scenario | Step | Name | Tool | Status | Duration (s) | Trace ID |" in text
        # Every scenario's steps appear with step_index, duration, trace_id.
        assert "| alpha-pass | 1 | collect data | test_source | passed | 0.123 |" in text
        assert "| beta-fail | 1 | llm verify | classify_cefr | failed | 1.234 |" in text
        assert "| beta-fail | 2 | long detail step | collect_sources | failed | 0.456 |" in text
        assert "| gamma-gated | 1 | gated step | health_check | unconfigured | 0.000 |" in text
        assert "11111111-2222-4333-8444-555555555555" in text

    def test_report_contains_scenario_and_run_ids(self, report: Path) -> None:
        """Header lines carry the version, run id, and status counts."""
        text = report.read_text(encoding="utf-8")
        assert "# Launch Validation Run Report 1.0 (2026-08-06_120000_000001)" in text
        assert "(passed=1, failed=1, unconfigured=1)" in text

    def test_no_failed_scenarios_renders_placeholder(self, tmp_path: Path, monkeypatch) -> None:
        """An all-pass run renders a placeholder line instead of an empty list."""
        run_dir = tmp_path / "runs" / "r1"
        run_dir.mkdir(parents=True)
        (run_dir / "scenarios.json").write_text(
            json.dumps({
                "run_id": "r1",
                "scenarios": [{
                    "scenario": "ok", "description": "d", "category": "general",
                    "status": "passed", "summary": {"passed": 1, "failed": 0,
                    "unconfigured": 0, "recovered": 0, "total": 1},
                    "trace_id": "t",
                    "steps": [{"name": "s", "tool": "t1", "status": "passed",
                               "detail": "d", "step_index": 1, "duration": 0.1,
                               "arguments": {}, "trace_id": "t"}],
                }],
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(vr, "RUNS", tmp_path / "runs")
        monkeypatch.setattr(vr, "REPORTS", tmp_path / "reports")
        out = vr.generate(version="1.0", run_id="r1")
        text = out.read_text(encoding="utf-8")
        blockers = text.split("## Blockers", 1)[1].split("## Per-step trace", 1)[0]
        assert "(no failing scenarios in this run)" in blockers
