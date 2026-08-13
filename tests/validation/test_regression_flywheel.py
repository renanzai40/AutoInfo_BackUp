"""Tests for the regression flywheel: report, template, and audit integration (issue #140).

Covers:
- ``scripts/validation_report.py`` renders a ``## Regression failures`` section
  and verdict-table `` (regression)`` suffix for regression scenarios.
- ``scripts/coverage_audit.py`` prints ``Regression scenarios: N (issues: ...)``.
- ``.github/ISSUE_TEMPLATE/bug_report.md`` contains the mandatory regression
  scenario field (``id: regression-scenario``, ``required: true``, 回归场景).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = ROOT / "scripts" / "coverage_audit.py"
BUG_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md"

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
def regression_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "validation-runs" / "2026-08-06_reg_001"
    run_dir.mkdir(parents=True)
    tid = "aaaa-bbbb-cccc-dddd"
    scenarios: list[dict[str, Any]] = [
        {
            "scenario": "regression-source-301",
            "description": "Regression #135",
            "category": "regression",
            "status": "failed",
            "regression": True,
            "regression_issue": "#135",
            "summary": {"passed": 1, "failed": 2, "unconfigured": 0, "recovered": 0, "total": 3},
            "trace_id": tid,
            "steps": [
                _step("ss probe", "test_source", "failed", "reachable false", 1, tid, 0.1),
                _step("arxiv probe", "test_source", "passed",
                      {"success": True, "data": {}}, 2, tid, 0.2),
                _step("uspto probe", "test_source", "failed", "timeout", 3, tid, 0.3),
            ],
        },
        {
            "scenario": "functional-pass",
            "description": "Functional pass",
            "category": "general",
            "status": "passed",
            "summary": {"passed": 1, "failed": 0, "unconfigured": 0, "recovered": 0, "total": 1},
            "trace_id": tid,
            "steps": [_step("step1", "health_check", "passed", {"success": True}, 1, tid, 0.05)],
        },
    ]
    (run_dir / "scenarios.json").write_text(
        json.dumps({"run_id": run_dir.name, "scenarios": scenarios}, indent=2),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def report(regression_run_dir: Path, monkeypatch) -> Path:
    monkeypatch.setattr(vr, "RUNS", regression_run_dir / "validation-runs")
    monkeypatch.setattr(vr, "REPORTS", regression_run_dir / "reports")
    return vr.generate(version="test", run_id="2026-08-06_reg_001")


class TestRegressionReportSection:

    def test_regression_failures_section_exists(self, report: Path) -> None:
        text = report.read_text(encoding="utf-8")
        assert "## Regression failures" in text

    def test_regression_failure_marked_with_reg_rgression(self, report: Path) -> None:
        text = report.read_text(encoding="utf-8")
        assert "REG RGRESSION regression-source-301 (#135)" in text

    def test_verdict_table_suffixes_regression_status(self, report: Path) -> None:
        text = report.read_text(encoding="utf-8")
        verdicts = text.split("## Verdicts", 1)[1].split("## Executive summary", 1)[0]
        assert "failed (regression)" in verdicts
        assert "passed |" in verdicts

    def test_regression_count_in_executive_summary(self, report: Path) -> None:
        text = report.read_text(encoding="utf-8")
        exec_sum = text.split("## Executive summary", 1)[1].split("## Regression failures", 1)[0]
        assert "1 regression failure(s)" in exec_sum

    def test_no_regression_failures_placeholder(self, tmp_path: Path, monkeypatch) -> None:
        run_dir = tmp_path / "runs" / "r2"
        run_dir.mkdir(parents=True)
        (run_dir / "scenarios.json").write_text(
            json.dumps({"run_id": "r2", "scenarios": [{
                "scenario": "ok", "description": "d", "category": "general",
                "status": "passed", "summary": {"passed": 1, "failed": 0,
                "unconfigured": 0, "recovered": 0, "total": 1},
                "trace_id": "t",
                "steps": [{"name": "s", "tool": "t1", "status": "passed",
                           "detail": "d", "step_index": 1, "duration": 0.1,
                           "arguments": {}, "trace_id": "t"}],
            }]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(vr, "RUNS", tmp_path / "runs")
        monkeypatch.setattr(vr, "REPORTS", tmp_path / "reports")
        out = vr.generate(version="test", run_id="r2")
        text = out.read_text(encoding="utf-8")
        regr_section = text.split("## Regression failures", 1)[1].split("## Blockers", 1)[0]
        assert "(no regression failures in this run)" in regr_section


class TestBugReportTemplate:

    def test_template_exists(self) -> None:
        assert BUG_TEMPLATE.is_file(), f"{BUG_TEMPLATE} does not exist"

    def test_has_required_field_id(self) -> None:
        content = BUG_TEMPLATE.read_text(encoding="utf-8")
        assert "id: regression-scenario" in content

    def test_has_required_true(self) -> None:
        content = BUG_TEMPLATE.read_text(encoding="utf-8")
        assert "required: true" in content

    def test_has_label_with_chinese(self) -> None:
        content = BUG_TEMPLATE.read_text(encoding="utf-8")
        assert "回归场景" in content


class TestCoverageAuditRegressionMetric:

    def test_audit_output_contains_regression_line(self) -> None:
        result = subprocess.run(
            [sys.executable, str(AUDIT_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("Regression scenarios:")]
        assert len(lines) == 1
        assert "#104" in lines[0]
        assert "#135" in lines[0]
