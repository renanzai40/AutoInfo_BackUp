"""Tests for the baseline-aware coverage gate (scripts/coverage_gate.py).

Covers the pure logic (TOTAL-row parsing, per-module floor computation,
new-vs-existing module detection) and the gate orchestration with a mocked
``coverage report`` subprocess — no real coverage data, no network.

The gate replaces the fixed ``fail-under=60`` check: an existing module's
floor is its merge-base coverage minus a tolerance; a NEW module's floor is
the threshold (60).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# scripts/ is not a package — load it via sys.path like the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import coverage_gate as cg  # noqa: E402  (sys.path insert above)

# ---------------------------------------------------------------------------
# parse_total_pct
# ---------------------------------------------------------------------------


def test_parse_total_pct_extracts_percent() -> None:
    report = (
        "Name                         Stmts   Miss  Cover\n"
        "-----------------------------------------------\n"
        "src/autoinfo/mcp/server.py    2794   1325    53%\n"
        "-----------------------------------------------\n"
        "TOTAL                         2794   1325    53%\n"
    )
    assert cg.parse_total_pct(report) == 53.0


def test_parse_total_pct_no_data_returns_none() -> None:
    assert cg.parse_total_pct("No data to report.") is None
    assert cg.parse_total_pct("") is None


def test_parse_total_pct_handles_fractional_cover() -> None:
    report = "TOTAL   10   3    70%\n"
    assert cg.parse_total_pct(report) == 70.0


# ---------------------------------------------------------------------------
# compute_floor
# ---------------------------------------------------------------------------


def test_floor_new_module_is_threshold() -> None:
    # New modules have no base coverage — the threshold is the floor.
    assert cg.compute_floor(is_new=True, base_pct=None, threshold=60.0, tolerance=2.0) == 60.0
    assert cg.compute_floor(is_new=True, base_pct=53.0, threshold=60.0, tolerance=2.0) == 60.0


def test_floor_existing_module_is_base_minus_tolerance() -> None:
    # server.py at 53% base -> floor 51%: a 1-line change passes as long as
    # it doesn't regress coverage (the fixed-60 gate's failure mode).
    assert cg.compute_floor(is_new=False, base_pct=53.0, threshold=60.0, tolerance=2.0) == 51.0


def test_floor_existing_module_no_base_data_is_zero() -> None:
    # Module never executed at base (no data) -> floor 0, cannot fail.
    assert cg.compute_floor(is_new=False, base_pct=None, threshold=60.0, tolerance=2.0) == 0.0


def test_floor_existing_module_clamped_at_zero() -> None:
    # Tolerance must not push the floor below 0.
    assert cg.compute_floor(is_new=False, base_pct=1.0, threshold=60.0, tolerance=2.0) == 0.0


# ---------------------------------------------------------------------------
# module_exists_at
# ---------------------------------------------------------------------------


@patch("coverage_gate.subprocess.run")
def test_module_exists_at_true(mock_run: Mock) -> None:
    mock_run.return_value.returncode = 0
    assert cg.module_exists_at("src/autoinfo/mcp/server.py", "abc123") is True
    mock_run.assert_called_once()


@patch("coverage_gate.subprocess.run")
def test_module_exists_at_false(mock_run: Mock) -> None:
    mock_run.return_value.returncode = 128  # git cat-file -e missing path
    assert cg.module_exists_at("src/autoinfo/new.py", "abc123") is False


def test_module_exists_at_none_sha_is_conservative() -> None:
    # No base SHA provided -> treat as existing (new-module gate stays off).
    assert cg.module_exists_at("anything.py", None) is True


# ---------------------------------------------------------------------------
# measure_module_coverage (mocked subprocess)
# ---------------------------------------------------------------------------


def _fake_coverage_report(returncode: int, output: str) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=output, stderr="")


@patch("coverage_gate.subprocess.run")
def test_measure_module_coverage_relative_pattern(mock_run: Mock) -> None:
    mock_run.return_value = _fake_coverage_report(
        0,
        "TOTAL   2794  1325   53%\n",
    )
    pct = cg.measure_module_coverage(Path(".coverage.pr"), "src/autoinfo/mcp/server.py")
    assert pct == 53.0
    # First attempt uses the git-relative pattern.
    assert mock_run.call_args.args[0][-3:-1] == ["--include", "src/autoinfo/mcp/server.py"]


@patch("coverage_gate.subprocess.run")
def test_measure_module_coverage_absolute_pattern_fallback(mock_run: Mock) -> None:
    # Relative pattern reports no data -> retry with */ prefix.
    mock_run.side_effect = [
        _fake_coverage_report(1, "No data to report."),
        _fake_coverage_report(0, "TOTAL   10  3  70%\n"),
    ]
    pct = cg.measure_module_coverage(Path(".coverage.pr"), "src/autoinfo/mcp/server.py")
    assert pct == 70.0
    assert len(mock_run.call_args_list) == 2
    assert mock_run.call_args_list[1].args[0][-3:-1] == [
        "--include",
        "*/src/autoinfo/mcp/server.py",
    ]


@patch("coverage_gate.subprocess.run")
def test_measure_module_coverage_never_executed(mock_run: Mock) -> None:
    mock_run.side_effect = [
        _fake_coverage_report(1, "No data to report."),
        _fake_coverage_report(1, "No data to report."),
    ]
    assert cg.measure_module_coverage(Path(".coverage.pr"), "src/autoinfo/x.py") is None


# ---------------------------------------------------------------------------
# gate orchestration
# ---------------------------------------------------------------------------


def _run_gate(
    modules: list[str],
    *,
    base_exists: bool = True,
    pr_pct: float = 60.0,
    base_pct: float | None = 60.0,
    threshold: float = 60.0,
    tolerance: float = 2.0,
) -> int:
    """Drive the gate with a fully-mocked coverage subprocess."""
    with (
        patch("coverage_gate.measure_module_coverage") as mock_measure,
        patch("coverage_gate.module_exists_at") as mock_exists,
        patch("coverage_gate.subprocess.run") as mock_run,
    ):
        mock_run.return_value = _fake_coverage_report(0, "")
        mock_exists.return_value = base_exists

        def _measure(data_file: Path, module: str) -> float | None:  # noqa: ARG001
            if data_file.name == ".coverage.pr":
                return pr_pct
            return base_pct  # .coverage.base

        mock_measure.side_effect = _measure
        return cg.gate(
            modules,
            Path(".coverage.pr"),
            Path(".coverage.base"),
            base_sha="abc123",
            threshold=threshold,
            tolerance=tolerance,
        )


def test_gate_existing_module_at_base_passes() -> None:
    # server.py: 53% at base, 54% on the PR -> passes (floor 51%).
    assert _run_gate(["src/autoinfo/mcp/server.py"], pr_pct=54.0, base_pct=53.0) == 0


def test_gate_existing_module_regression_fails() -> None:
    # server.py: 53% at base, 30% on the PR -> regression -> fail.
    assert _run_gate(["src/autoinfo/mcp/server.py"], pr_pct=30.0, base_pct=53.0) == 1


def test_gate_new_module_below_threshold_fails() -> None:
    # New module with no tests at all -> 0% vs threshold 60 -> fail.
    assert _run_gate(
        ["src/autoinfo/new_module.py"], base_exists=False, pr_pct=0.0
    ) == 1


def test_gate_new_module_at_threshold_passes() -> None:
    assert _run_gate(
        ["src/autoinfo/new_module.py"], base_exists=False, pr_pct=60.0
    ) == 0


def test_gate_mixed_modules_reports_all() -> None:
    # One pass + one fail -> exit 1, both lines printed.
    with (
        patch("coverage_gate.measure_module_coverage") as mock_measure,
        patch("coverage_gate.module_exists_at") as mock_exists,
        patch("coverage_gate.subprocess.run"),
    ):
        mock_exists.side_effect = (
            lambda m, s: "new_module" not in m
        )  # only new_module is "new"
        mock_measure.return_value = 55.0
        rc = cg.gate(
            ["src/autoinfo/mcp/server.py", "src/autoinfo/new_module.py"],
            Path(".coverage.pr"),
            Path(".coverage.base"),
            base_sha="abc123",
            threshold=60.0,
            tolerance=2.0,
        )
    assert rc == 1  # new_module at 55% < threshold 60 fails; server.py at 55% >= 51 passes


def test_gate_new_module_detection_uses_exists() -> None:
    # module_exists_at=False routes to the new-module branch (threshold floor).
    with (
        patch("coverage_gate.measure_module_coverage") as mock_measure,
        patch("coverage_gate.module_exists_at", return_value=False) as mock_exists,
        patch("coverage_gate.subprocess.run"),
    ):
        mock_measure.return_value = 50.0  # below threshold 60
        rc = cg.gate(
            ["src/autoinfo/new_module.py"],
            Path(".coverage.pr"),
            Path(".coverage.base"),
            base_sha="abc123",
            threshold=60.0,
            tolerance=2.0,
        )
        assert rc == 1
        mock_exists.assert_called_once()


# ---------------------------------------------------------------------------
# main() / file handling
# ---------------------------------------------------------------------------


def test_read_changed_src_modules_filters(tmp_path: Path) -> None:
    f = tmp_path / "changed-files.txt"
    f.write_text(
        "src/autoinfo/mcp/server.py\n"
        "tests/test_foo.py\n"
        "src/autoinfo/config.py\n"
        "docs/readme.md\n",
        encoding="utf-8",
    )
    assert cg._read_changed_src_modules(f) == [
        "src/autoinfo/mcp/server.py",
        "src/autoinfo/config.py",
    ]


def test_main_skips_when_no_src_modules(tmp_path: Path) -> None:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("tests/test_foo.py\n", encoding="utf-8")
    rc = cg.main(
        [
            "--changed",
            str(changed),
            "--pr-data",
            str(tmp_path / ".coverage.pr"),
            "--base-data",
            str(tmp_path / ".coverage.base"),
        ]
    )
    assert rc == 0


def test_main_errors_when_data_missing(tmp_path: Path) -> None:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("src/autoinfo/mcp/server.py\n", encoding="utf-8")
    rc = cg.main(
        [
            "--changed",
            str(changed),
            "--pr-data",
            str(tmp_path / ".coverage.pr"),
            "--base-data",
            str(tmp_path / ".coverage.base"),
        ]
    )
    assert rc == 2  # both data files missing
