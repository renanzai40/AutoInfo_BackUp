"""Tests for ``autoinfo validation list`` (P1-1, plan todo 10).

Exercises the new ``validation`` CLI group — distinct from ``validate``
(the matrix/diff/stability executor).  All expected counts are derived at
runtime from :func:`autoinfo.mcp.validation.list_scenarios` — never
hardcoded, because the regression flywheel keeps growing the library.

Run inside a temp project dir (``monkeypatch.chdir``) so the CLI never
touches the repo's runtime state (hermetic, no network / no LLM).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from autoinfo.cli import app
from autoinfo.mcp.validation import list_scenarios


@pytest.fixture
def cli_runner() -> Any:
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture(autouse=True)
def temp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run every test inside an isolated temp project directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _expected_counts() -> tuple[int, int, set[str]]:
    """Derive (functional, regression, names) from the live scenario library."""
    result = list_scenarios()
    scenarios = result["scenarios"]
    functional = sum(1 for sc in scenarios if not sc.get("regression"))
    regression = sum(1 for sc in scenarios if sc.get("regression"))
    names = {sc["name"] for sc in scenarios}
    return functional, regression, names


def _extract_labeled_count(output: str, label: str) -> int:
    m = re.search(rf"{label}:\s*(\d+)", output)
    assert m, f"'{label}: N' not found in output:\n{output}"
    return int(m.group(1))


class TestValidationListCommand:
    """``autoinfo validation list`` — full scenario listing."""

    def test_list_exits_zero_and_lists_scenarios(self, cli_runner: Any) -> None:
        _, _, names = _expected_counts()
        result = cli_runner.invoke(app, ["validation", "list"])
        assert result.exit_code == 0, result.output
        listed = [n for n in names if n in result.output]
        # Every discovered scenario name appears in the listing.
        assert set(listed) == names, (
            f"missing scenario rows: {sorted(names - set(listed))}"
        )

    def test_list_shows_category_and_regression_columns(
        self, cli_runner: Any
    ) -> None:
        result = cli_runner.invoke(app, ["validation", "list"])
        assert result.exit_code == 0
        for field in ("category=", "regression=", "env="):
            assert field in result.output, field

    def test_list_reports_total_matching_runtime(self, cli_runner: Any) -> None:
        result = list_scenarios()
        expected = result["count"]
        got = cli_runner.invoke(app, ["validation", "list"])
        assert got.exit_code == 0
        m = re.search(r"Validation scenarios \((\d+)\)", got.output)
        assert m, got.output
        assert int(m.group(1)) == expected


class TestValidationListSummary:
    """``autoinfo validation list --summary`` — per-category split."""

    def test_summary_counts_match_runtime(self, cli_runner: Any) -> None:
        functional, regression, _ = _expected_counts()
        result = cli_runner.invoke(app, ["validation", "list", "--summary"])
        assert result.exit_code == 0, result.output
        got_functional = _extract_labeled_count(result.output, "functional")
        got_regression = _extract_labeled_count(result.output, "regression")
        assert got_functional == functional
        assert got_regression == regression
        assert got_functional + got_regression == functional + regression

    def test_summary_functional_plus_regression_equals_total(
        self, cli_runner: Any
    ) -> None:
        total = list_scenarios()["count"]
        result = cli_runner.invoke(app, ["validation", "list", "--summary"])
        assert result.exit_code == 0
        functional = _extract_labeled_count(result.output, "functional")
        regression = _extract_labeled_count(result.output, "regression")
        assert functional + regression == total

    def test_summary_lists_known_categories(self, cli_runner: Any) -> None:
        result = list_scenarios()
        categories = {sc.get("category", "general") for sc in result["scenarios"]}
        got = cli_runner.invoke(app, ["validation", "list", "--summary"])
        assert got.exit_code == 0
        for cat in categories:
            assert cat in got.output, cat


class TestValidationGroupIdentity:
    """The validation group stays separate from the validate executor."""

    def test_validation_in_top_level_help(self, cli_runner: Any) -> None:
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "validation" in result.output
        assert "validate" in result.output

    def test_no_scenario_dir_fails_cleanly(
        self, tmp_path: Path, cli_runner: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``list_scenarios`` reads the built-in scenarios dir next to the
        # module; patch its resolver so it points at an empty temp dir and
        # verify the CLI exits non-zero with a clear message, no traceback.
        import autoinfo.cli.validation as vmod

        empty = tmp_path / "empty-scenarios"
        empty.mkdir()
        monkeypatch.setattr(
            vmod, "list_scenarios", lambda scenarios_dir=None: {
                "scenarios": [], "count": 0
            }
        )
        assert empty.is_dir()
        result = cli_runner.invoke(app, ["validation", "list"])
        assert result.exit_code == 1
        assert "No validation scenarios found" in result.output
        assert "Traceback" not in result.output
