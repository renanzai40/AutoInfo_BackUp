"""Tests for cross-day stability of ``validate --matrix`` (#352.1).

A single-day matrix snapshot is a point-in-time artifact; a re-run on the
same persisted product set must be diffable to expose drift/regression.  This
module covers ``autoinfo.validation_matrix.assert_persisted_batch`` /
``diff_batches`` (deterministic re-assertion of persisted products — NEVER
regeneration, so LLM nondeterminism cannot cause false diffs) and the
``autoinfo validate stability`` CLI command.

The comparison is on ASSERTION PASS/FAIL STATE, not bytes: two batches with
identical product bodies diff clean, and a body drift that flips an assertion
shows up as a regression/fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from autoinfo import validation_matrix as vm
from autoinfo.cli.validate import app

runner = CliRunner()

# CLEAN body that passes all 12 assertions of this branch (main's set, #352 —
# the #351 assertions are NOT merged here): a report with **Sections**: 2,
# Summary, numbered Key Takeaways, numbered References with http entries.
CLEAN = """# AI Commercial Report

**Domain**: ai-commercial
**Sections**: 2

## Summary

AI funding accelerated this week.

## Key Takeaways

### 1. Startup A raised $50M (Source: https://techcrunch.com/1)
Monitor developments.

### 2. Startup B raised $30M (Source: https://techcrunch.com/2)
Watch consolidation.

## References

1. **Startup A** — https://techcrunch.com/1 (techcrunch)
2. **Startup B** — https://techcrunch.com/2 (techcrunch)
"""

# Body that fails ``_no_placeholder`` (P0): the template empty-state marker.
PLACEHOLDER = "# T\n\n_No articles found for general-news in the Weekly period._\n"


def _write_batch(batch_root: Path, batch_id: str, bodies: dict[tuple[str, str], str]) -> None:
    """Persist a batch tree:
    ``<root>/<batch_id>/products/<domain>/<product>-markdown-<batch_id>.md``.

    The filename mirrors run_matrix's #335 persistence scheme, so
    ``assert_persisted_batch`` scans a real on-disk batch without mocking the
    file lookup.
    """
    for (domain, product), body in bodies.items():
        out = batch_root / batch_id / "products" / domain / f"{product}-markdown-{batch_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")


class TestAssertPersistedBatch:
    def test_builds_report_card_shape(self, tmp_path: Path) -> None:
        _write_batch(tmp_path, "a", {("ai-commercial", "report"): CLEAN})
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            card = vm.assert_persisted_batch(
                tmp_path / "a" / "products", ["ai-commercial"], ["report"]
            )
        assert card["schema_version"] == 2
        assert card["tool"] == "autoinfo validate --matrix"
        assert card["commit"] == "abc"
        # batch_id = the products-root dir name; the CLI knows the real ids.
        assert card["batch_id"] == "products"
        assert len(card["products"]) == 1
        row = card["products"][0]
        assert (row["domain"], row["product"], row["status"]) == (
            "ai-commercial", "report", "ok"
        )
        assert len(row["assertions"]) == len(vm.ASSERTION_FUNCS)
        assert all(a["passed"] for a in row["assertions"])
        assert card["summary"]["failures"] == 0

    def test_missing_product_reported(self, tmp_path: Path) -> None:
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            card = vm.assert_persisted_batch(
                tmp_path / "a" / "products", ["ai-commercial"], ["digest"]
            )
        row = card["products"][0]
        assert (row["domain"], row["product"], row["status"]) == (
            "ai-commercial", "digest", "missing"
        )
        assert card["summary"]["missing_products"] == 1
        assert card["summary"]["failures"] >= 1


class TestDiffBatches:
    def test_stability_diff_same_batch_is_stable(self, tmp_path: Path) -> None:
        """Two identical batch product trees -> 0 regressions/new/fixed."""
        for batch_id in ("a", "b"):
            _write_batch(tmp_path, batch_id, {("ai-commercial", "report"): CLEAN})
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            d = vm.diff_batches(
                tmp_path / "a" / "products", tmp_path / "b" / "products",
                ["ai-commercial"], ["report"],
            )
        assert d["stable"] is True
        assert d["diff"]["counts"] == {
            "new": 0, "regressed": 0, "fixed": 0, "existing_failing": 0,
        }
        assert d["diff"]["regressed"] == []
        assert d["diff"]["new"] == []
        assert d["diff"]["fixed"] == []

    def test_stability_diff_detects_regression(self, tmp_path: Path) -> None:
        """Batch A passes ``_no_placeholder``, batch B carries a placeholder
        marker -> the assertion regresses (domain, product, assertion)."""
        _write_batch(tmp_path, "a", {("ai-commercial", "report"): CLEAN})
        _write_batch(tmp_path, "b", {("ai-commercial", "report"): PLACEHOLDER})
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            d = vm.diff_batches(
                tmp_path / "a" / "products", tmp_path / "b" / "products",
                ["ai-commercial"], ["report"],
            )
        assert d["stable"] is False
        assert d["diff"]["counts"]["regressed"] >= 1
        assert ("ai-commercial", "report", "_no_placeholder") in d["diff"]["regressed"]
        assert d["diff"]["counts"]["new"] == 0
        assert d["diff"]["counts"]["fixed"] == 0

    def test_stability_diff_detects_fix(self, tmp_path: Path) -> None:
        """A fails, B passes -> fixed."""
        _write_batch(tmp_path, "a", {("ai-commercial", "report"): PLACEHOLDER})
        _write_batch(tmp_path, "b", {("ai-commercial", "report"): CLEAN})
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            d = vm.diff_batches(
                tmp_path / "a" / "products", tmp_path / "b" / "products",
                ["ai-commercial"], ["report"],
            )
        assert d["stable"] is True  # nothing regressed or new
        assert d["diff"]["counts"]["fixed"] >= 1
        assert ("ai-commercial", "report", "_no_placeholder") in d["diff"]["fixed"]
        assert d["diff"]["counts"]["regressed"] == 0
        assert d["diff"]["counts"]["new"] == 0

    def test_stability_diff_uses_assertions_not_regeneration(self, tmp_path: Path) -> None:
        """The stability path must NEVER call ``_generate_product`` (LLM
        nondeterminism would cause false diffs); it re-asserts persisted files."""
        _write_batch(tmp_path, "a", {("ai-commercial", "report"): CLEAN})
        _write_batch(tmp_path, "b", {("ai-commercial", "report"): CLEAN})

        def _boom(*_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("stability must not regenerate products")

        with patch("autoinfo.validation_matrix._generate_product",
                   side_effect=_boom) as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            d = vm.diff_batches(
                tmp_path / "a" / "products", tmp_path / "b" / "products",
                ["ai-commercial"], ["report"],
            )
        assert gen.call_count == 0
        assert d["stable"] is True


class TestStabilityCli:
    def _run(self, tmp_path: Path, a_body: str, b_body: str) -> Any:
        _write_batch(tmp_path, "a", {("ai-commercial", "report"): a_body})
        _write_batch(tmp_path, "b", {("ai-commercial", "report"): b_body})
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            return runner.invoke(app, [
                "stability", "a", "b",
                "--snapshot-dir", str(tmp_path),
                "--domains", "ai-commercial", "--products", "report",
            ])

    def test_stability_cli_reports_and_exits_stable(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, CLEAN, CLEAN)
        assert result.exit_code == 0, result.output
        assert "stable" in result.output.lower()
        assert "regressed" in result.output

    def test_stability_cli_exits_one_on_regression(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, CLEAN, PLACEHOLDER)
        assert result.exit_code == 1, result.output
        assert "regressed" in result.output
        assert "_no_placeholder" in result.output
        assert "ai-commercial" in result.output
        assert "report" in result.output

    def test_stability_cli_exits_one_on_fix_reported(self, tmp_path: Path) -> None:
        """A fix (prev fails, cur passes) is reported but is NOT an exit-1
        regression — only regressed/new force a non-zero exit."""
        result = self._run(tmp_path, PLACEHOLDER, CLEAN)
        assert result.exit_code == 0, result.output
        assert "fixed" in result.output
