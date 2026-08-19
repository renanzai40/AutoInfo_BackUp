"""Tests for the full-matrix validation executor (#331) and its CLI (#332-A).

Covers ``autoinfo.validation_matrix`` (the 11-assertion set, matrix runner,
report-card snapshot + regression diff) and ``autoinfo.cli.validate`` (the
``validate matrix`` / ``validate diff`` CLI commands).  These are the new
modules introduced by #331/#332, so the coverage gate requires >=60%
fast-subset coverage on them.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from autoinfo import validation_matrix as vm
from autoinfo.cli.validate import app

runner = CliRunner()

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


class TestAssertionSet:
    def test_clean_report_all_11_pass(self) -> None:
        results = vm.run_assertions(CLEAN, domain="ai-commercial", product="report")
        assert len(results) == 11
        failed = [r.name for r in results if not r.passed]
        assert not failed, failed

    def test_title_first_fails_on_polluted_header(self) -> None:
        polluted = "\x1b[1;31mGive Feedback / Get Help: x\x1b[0m\n# Title\n"
        r = vm._title_first(polluted, "d", "report")
        assert not r.passed
        assert r.issue == "#318"

    def test_no_error_leak_detects_litellm_and_ansi(self) -> None:
        leaky = (
            "\x1b[1;31mGive Feedback / Get Help: "
            "https://github.com/BerriAI/litellm/issues/new\x1b[0m\n# Title\n"
        )
        assert not vm._no_error_leak(leaky, "d", "report").passed
        assert vm._no_error_leak(CLEAN, "d", "report").passed

    def test_references_numbered(self) -> None:
        assert vm._references_numbered(CLEAN, "d", "report").passed
        broken = "# T\n\n## References\n\n1. **A**\n1. **B**\n"
        assert not vm._references_numbered(broken, "d", "report").passed

    def test_source_labels_specific_rejects_rss(self) -> None:
        bad = "# T\n\n## References\n\n1. **A** — https://x.com (RSS)\n"
        assert not vm._source_labels_specific(bad, "d", "report").passed
        assert vm._source_labels_specific(CLEAN, "d", "report").passed

    def test_no_placeholder(self) -> None:
        bad = "# T\n\n_No implication captured for this takeaway._\n"
        assert not vm._no_placeholder(bad, "d", "premium-briefing").passed
        assert vm._no_placeholder(CLEAN, "d", "report").passed

    def test_column_deep_dive(self) -> None:
        col = "# C\n\n## Deep Dive\n\n### S1\nbody\n\n### S2\nbody\n"
        assert vm._column_deep_dive(col, "d", "column").passed
        assert vm._column_deep_dive(col, "d", "report").passed
        assert not vm._column_deep_dive("# C\n", "d", "column").passed

    def test_report_sections_and_metadata_consistency(self) -> None:
        assert vm._report_sections(CLEAN, "d", "report").passed
        assert vm._metadata_consistency(CLEAN, "d", "report").passed
        mismatched = CLEAN.replace("**Sections**: 2", "**Sections**: 7")
        assert not vm._metadata_consistency(mismatched, "d", "report").passed

    def test_cross_domain_noise(self) -> None:
        noisy = "# T\n\n贝达药业 财报 华能 SEC 8-K\n"
        assert not vm._no_cross_domain_noise(noisy, "ai-commercial", "digest").passed
        assert vm._no_cross_domain_noise(noisy, "medical-research", "digest").passed

    def test_financial_dilution(self) -> None:
        fin = "# T\n\nForm 8-K and 10-Q metadata only\n"
        assert not vm._no_financial_dilution(fin, "financial-intelligence", "digest").passed
        assert vm._no_financial_dilution(fin, "medical-research", "digest").passed

    def test_not_empty(self) -> None:
        assert not vm._not_empty("", "d", "report").passed
        assert vm._not_empty(CLEAN, "d", "report").passed


class TestMatrix:
    def test_generate_product_routes_and_coerces(self) -> None:
        class _DO:
            output = "rendered body"

        with patch("autoinfo.output.generate_report", return_value=_DO()):
            assert vm._generate_product("d", "report", None) == "rendered body"
        with patch("autoinfo.output.generate_digest", return_value="dg"):
            assert vm._generate_product("d", "digest", None) == "dg"

    def test_run_matrix_only_assert(self, tmp_path: Path) -> None:
        fixture = tmp_path / "digest-report-a.md"
        fixture.write_text(CLEAN, encoding="utf-8")
        with patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[fixture]), \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(["ai-commercial"], ["report"], only_assert=True)
        assert report.summary["total_products"] == 1
        assert report.summary["failures"] == 0
        assert report.to_dict()["schema_version"] == 1
        assert report.to_dict()["tool"] == "autoinfo validate --matrix"

    def test_run_matrix_missing_file_reports_failure(self) -> None:
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(["nope-domain"], ["digest"], only_assert=True)
        assert report.summary["failures"] >= 1

    def test_run_matrix_generation_error_path(self) -> None:
        with patch("autoinfo.validation_matrix._generate_product",
                   side_effect=RuntimeError("boom")), \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(["d"], ["digest"], only_assert=False)
        assert report.summary["failures"] >= 1
        assert any(p.get("status") == "error" for p in report.products)

    def test_save_report_card_creates_dir(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "snap" / "nested"
        report = vm.MatrixReport(generated_at="t", commit="c")
        path = vm.save_report_card(report, out_dir)
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1

    def test_diff_report_cards_all_classes(self) -> None:
        def card(
            pairs: list[tuple[str, str, bool]],
        ) -> vm.MatrixReport:
            m = vm.MatrixReport(generated_at="t", commit="c")
            m.products = [{
                "domain": "d", "product": p, "status": "ok",
                "assertions": [{"assertion": a, "passed": ps}],
            } for p, a, ps in pairs]
            return m

        prev = card([
            ("p", "_title_first", True),
            ("p", "_not_empty", False),
            ("p", "_no_leak", False),
        ])
        cur = card([
            ("p", "_title_first", False),   # regressed
            ("p", "_not_empty", True),      # fixed
            ("q", "_not_empty", False),     # new
            ("p", "_no_leak", False),       # existing-failing
        ])
        d = vm.diff_report_cards(prev.to_dict(), cur.to_dict())
        assert d["counts"] == {"new": 1, "regressed": 1, "fixed": 1, "existing_failing": 1}
        assert ("p", "_title_first") in d["regressed"]
        assert ("p", "_not_empty") in d["fixed"]
        assert ("q", "_not_empty") in d["new"]
        assert ("p", "_no_leak") in d["existing_failing"]

    def test_as_str_helper(self) -> None:
        class _DO:
            output = "delivery"

        assert vm._as_str(_DO()) == "delivery"
        assert vm._as_str("plain") == "plain"

    def test_assertion_names_consistent(self) -> None:
        for name, fn in vm.ASSERTION_FUNCS:
            r = fn("x", "d", "p")
            assert r.name == name, (name, r.name)


class TestValidateCli:
    def test_matrix_only_assert_end_to_end(self, tmp_path: Path) -> None:
        fixture = tmp_path / "outputs" / "ai-commercial" / "digest-report-a.md"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(CLEAN, encoding="utf-8")
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"), \
             patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[fixture]):
            result = runner.invoke(
                app,
                ["matrix", "--only-assert", "--domains", "ai-commercial",
                 "--products", "report", "--json-out", str(tmp_path / "card.json"),
                 "--snapshot-dir", str(tmp_path / "snap")],
            )
        assert result.exit_code == 0, result.output
        data = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
        assert data["summary"]["failures"] == 0
        assert bool((tmp_path / "snap").iterdir())

    def test_matrix_nonzero_exit_on_failure(self, tmp_path: Path) -> None:
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"), \
             patch("autoinfo.validation_matrix._persisted_product_paths", return_value=[]):
            result = runner.invoke(
                app,
                ["matrix", "--only-assert", "--domains", "d", "--products", "digest",
                 "--snapshot-dir", str(tmp_path / "snap")],
            )
        assert result.exit_code == 1

    def test_diff_command_highlights_regression(self, tmp_path: Path) -> None:
        prev = tmp_path / "prev.json"
        cur = tmp_path / "cur.json"
        prev.write_text(json.dumps({"products": [{
            "product": "p", "assertions": [{"assertion": "_title_first", "passed": True}],
        }]}), encoding="utf-8")
        cur.write_text(json.dumps({"products": [{
            "product": "p", "assertions": [{"assertion": "_title_first", "passed": False}],
        }]}), encoding="utf-8")
        result = runner.invoke(app, ["diff", str(prev), str(cur)])
        assert "regressed" in result.output
        assert result.exit_code == 1

    def test_default_domains_fallback(self) -> None:
        from autoinfo.cli import validate as _v

        with patch("autoinfo.config.get_config_path", return_value=None):
            domains = _v._default_domains()
        assert domains

    def test_write_html_report(self, tmp_path: Path) -> None:
        from autoinfo.cli import validate as _v

        report = vm.MatrixReport(generated_at="t", commit="c")
        report.products = [{"domain": "d", "product": "p", "status": "ok"}]
        out = tmp_path / "card.html"
        _v._write_html(report, out)
        assert out.is_file()
        assert "report card" in out.read_text(encoding="utf-8")
