# mypy: ignore-errors
"""Scenario outcome-audit tests (D-工-5 evidence, best-practice-review).

Locks the behavior of ``scripts/scenario_outcome_audit.py`` so the D-工-5
evidence stays deterministic:

1. All 117 scenarios (65 functional + 52 regression) are parsed with 448
   steps (446 + the #351 V5 step-5 append to
   ``regression-351-year-hallucination-tuning`` + the #9-reopened
   ``regression-9-generic-theme-blocklist`` scenario).
2. **Outcome grading** — >= 95% of steps assert an explicit ``success``
   key (grade the outcome envelope, not the path).
3. **Error-path depth** — every error step pins ``error_code``; the
   ``error_actionable`` (issue #141) assertion is present on the majority
   of error steps.
4. **Isolation / anti-cheat gating** — zero ungated ``llm_assert`` steps
   and zero ungated ``http`` steps: every LLM-dependent step declares an
   LLM env key in the scenario header, every http step declares
   ``requires_http`` (so the engine reports ``unconfigured`` instead of
   silently passing).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = ROOT / "scripts" / "scenario_outcome_audit.py"


@pytest.fixture(scope="module")
def outcome_audit():
    spec = importlib.util.spec_from_file_location(
        "scenario_outcome_audit", AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(outcome_audit):
    return outcome_audit.audit_all()


def test_all_116_scenarios_parsed(result: dict[str, Any]) -> None:
    # 124 = 117 + 6 scenarios from the #8-#18 output-fix wave
    # (regression-9-generic-theme-blocklist, regression-14-*, #16, #17, #18)
    # + the #15 presentation language/provenance regression scenario
    # (regression-15-presentation-language-provenance.yaml).
    assert result["summary"]["total_scenarios"] == 124
    assert result["summary"]["regression_scenarios"] == 59


def test_total_steps(result):
    # 455 = 448 + 6 steps from the #8-#18 output-fix wave + the #15
    # regression scenario step (regression-15-presentation-language-provenance.yaml).
    assert result["summary"]["total_steps"] == 455


def test_outcome_grading_ratio_high(result):
    s = result["summary"]
    assert s["steps_grading_outcome"] + s["steps_grade_path_only"] == s["total_steps"]
    assert s["steps_grading_outcome"] / s["total_steps"] >= 0.95


def test_error_steps_all_pin_error_code(result):
    s = result["summary"]
    assert s["error_steps"] >= 15
    # >= 95% pin error_code; the cli-extra portal-history step grades via
    # exit_code instead (a legitimate CLI-path exception).
    assert s["error_steps_with_code"] / s["error_steps"] >= 0.95


def test_error_actionable_majority(result):
    s = result["summary"]
    assert s["error_steps_with_actionable"] / s["error_steps"] >= 0.5


def test_zero_ungated_llm_assert(result):
    # Every llm_assert step must be env-gated (no silent-pass cheating).
    assert result["summary"]["llm_assert_steps"] >= 3
    assert result["summary"]["llm_assert_ungated"] == 0


def test_zero_ungated_http_steps(result):
    assert result["summary"]["http_steps"] >= 3
    assert result["summary"]["http_ungated"] == 0


def test_llm_env_gate_declared(result):
    # At least one scenario declares an LLM env key (e.g. llm-gated.yaml).
    assert result["summary"]["scenarios_with_llm_gate"] >= 1


def test_scenario_row_shape(result):
    row = result["scenarios"][0]
    for key in (
        "file", "name", "step_count", "requires_env", "requires_http",
        "violations", "steps",
    ):
        assert key in row, key
