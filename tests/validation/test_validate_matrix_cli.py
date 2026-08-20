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
from typing import Any
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
    def test_clean_report_all_12_pass(self) -> None:
        results = vm.run_assertions(CLEAN, domain="ai-commercial", product="report")
        assert len(results) == 12
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
        """#325 — the whole body is scanned, not just the References section:
        RSS residue in the masthead/byline position (no References heading)
        must fail loudly."""
        bad = "# T\n\n*RSS* · relevance 90.0/100\n\n## Entries\n\n| **Source** | RSS |\n"
        assert not vm._source_labels_specific(bad, "d", "magazine-digest").passed
        # RSS residue BEFORE a References section also fails (whole-body scan).
        bad_with_refs = (
            "# T\n\n*RSS* · relevance 90.0/100\n\n## References\n\n"
            "1. **A** — https://x.com (techcrunch)\n"
        )
        assert not vm._source_labels_specific(
            bad_with_refs, "d", "magazine-digest"
        ).passed
        assert vm._source_labels_specific(CLEAN, "d", "report").passed

    def test_no_placeholder(self) -> None:
        bad = "# T\n\n_No implication captured for this takeaway._\n"
        assert not vm._no_placeholder(bad, "d", "premium-briefing").passed
        assert vm._no_placeholder(CLEAN, "d", "report").passed

    def test_no_placeholder_detects_analysis_layer_tokens(self) -> None:
        """#334 — the premium/enterprise analysis layer (implications / risks /
        action_required / key_metrics / recommendations) can carry placeholder
        values that are NOT the template ``_No ..._`` markers: standalone
        ``N/A``/``None``/``TBD`` cells or list items, ``Not available``,
        ``To be determined``, and the deterministic fallback
        ``No knowledge base entries were available.``.  Each must fail the
        assertion (the 9 missed spots on the mimo enterprise layer)."""
        analysis_samples = [
            # 1. key_metrics table with N/A + Not available cells
            "| Metric | Value | Source |\n|--------|-------|--------|\n"
            "| Schwab | N/A | Not available |\n",
            # 1b. bare no-data / no-content cell
            "| Metric | Value | Source |\n|--------|-------|--------|\n"
            "| Growth | None | No data |\n",
            # 2. action list item that is a bare placeholder token
            "- [ ] None\n- [ ] Track ACME for validation in the next period.\n",
            # 3. risk matrix with TBD likelihood / None mitigation
            "| Risk | Likelihood | Impact | Mitigation |\n"
            "|------|-----------|--------|------------|\n"
            "| Market shock | TBD | Medium | None |\n",
            # 4. recommendations list of to-be-determined
            "- To be determined\n- Monitor market shifts.\n",
            # 5. deterministic fallback exec summary (no underscore markers)
            "# E\n\nNo knowledge base entries were available.\n",
            # 6. bare line placeholder
            "# E\n\nNot available\n",
        ]
        for i, sample in enumerate(analysis_samples):
            r = vm._no_placeholder(sample, "ai-commercial", "enterprise-briefing")
            assert not r.passed, (
                f"analysis-layer placeholder sample #{i} escaped detection: "
                f"{r.details!r}"
            )

    def test_no_placeholder_all_template_empty_states(self) -> None:
        """#334 — every premium/enterprise/magazine/column template empty-state
        marker must be caught (full coverage of the paid analysis layer)."""
        markers = [
            "_No executive summary available for this period._",
            "_No quantified metrics in this period._",
            "_No actions required in this period._",
            "_No material risks identified in this period._",
            "_No source references available for this briefing._",
            "_No implication captured for this takeaway._",
            "_No material risks or opportunities identified for this takeaway._",
            "_No follow-up actions suggested._",
            "_No key takeaways were extracted for this period._",
            "_No articles found for general-news in the Weekly period._",
            "_No deep-dive sections available for this column._",
            "_No outlook sections available._",
            "_No developments this week._",
            "_No references included in this report._",
            "_No entries found for medical-research in the Weekly period._",
            "_No objectives defined._",
            "_No exercises provided._",
            "_No references provided._",
        ]
        for m in markers:
            r = vm._no_placeholder(f"# T\n\n{m}\n", "medical-research", "digest")
            assert not r.passed, f"template empty-state marker escaped: {m!r}"

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

    def test_no_internal_leak(self) -> None:
        """#338 — products must not carry internal keyword-search/counting
        logs (``N entries related to <kw>``, ``N entry(ies) not matched to a
        topic keyword``, per-theme count bullets, ``N entries included in
        this report``)."""
        leaky = [
            "# T\n\n6 entries related to 'new'.\n",
            "# T\n\n66 entry(ies) not matched to a topic keyword.\n",
            "## Additional Topics\n\n5 entry(ies) not covered by other themes.\n",
            "# T\n\nThis report covers 67 knowledge base entries grouped into\n"
            "44 themes:\n\n- **API**: 12 entry(ies)\n",
            "# T\n\nAll 3 entries included in this report.\n",
            "# T\n\n12 entries from rss sources.\n",
        ]
        for i, sample in enumerate(leaky):
            r = vm._no_internal_leak(sample, "ai-commercial", "report")
            assert not r.passed, f"leak sample #{i} escaped: {r.details!r}"
        assert vm._no_internal_leak(CLEAN, "ai-commercial", "report").passed


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
        assert ("d", "p", "_title_first") in d["regressed"]
        assert ("d", "p", "_not_empty") in d["fixed"]
        assert ("d", "q", "_not_empty") in d["new"]
        assert ("d", "p", "_no_leak") in d["existing_failing"]

    def test_diff_counts_reconcile_with_cur_failures(self) -> None:
        """#336 — diff counts must reconcile with the failure count a reader
        would compute by hand from the cards: every cur issue (failing
        assertion OR missing/error product) lands in exactly one of
        new / regressed / existing_failing."""
        def card(products: list[dict[str, Any]]) -> dict[str, Any]:
            m = vm.MatrixReport(generated_at="t", commit="c")
            m.products = products
            return m.to_dict()

        def cur_issues(card_data: dict[str, Any]) -> int:
            return sum(
                1
                for p in card_data["products"]
                for a in p.get("assertions", [])
                if not a.get("passed")
            ) + sum(
                1
                for p in card_data["products"]
                if p.get("status", "ok") not in ("ok",)
            )

        prev = card([
            {"product": "a", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": True}]},
            {"product": "b", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": True}]},
            {"product": "c", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": True}]},
        ])
        cur = card([
            {"product": "a", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": False}]},
            {"product": "b", "status": "missing", "assertions": []},
            {"product": "c", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": True}]},
            {"product": "d", "status": "error", "assertions": [], "error": "boom"},
        ])
        d = vm.diff_report_cards(prev, cur)
        c = d["counts"]
        reconciled = c["new"] + c["regressed"] + c["existing_failing"]
        assert cur_issues(cur) == 3
        assert reconciled == cur_issues(cur), (
            f"diff counts {c} fail to reconcile with hand-counted cur issues "
            f"{cur_issues(cur)}"
        )
        assert c == {"new": 1, "regressed": 2, "fixed": 0, "existing_failing": 0}
        assert ("", "b", vm.PRODUCT_STATUS) in d["regressed"]
        assert ("", "d", vm.PRODUCT_STATUS) in d["new"]

    def test_diff_reconciles_across_domains(self) -> None:
        """#340 — the diff key must include the DOMAIN: a real matrix card
        spans 3 domains x the same product, so a ``(product, assertion)`` key
        collides across domains and drops failures.  With the domain in the
        key, every cur failure (incl. missing/error products) lands in
        exactly one bucket and ``cur issues == new + regressed + existing``."""
        def card(
            domain_products: list[tuple[str, str, str, list[dict[str, Any]]]],
        ) -> dict[str, Any]:
            m = vm.MatrixReport(generated_at="t", commit="c")
            m.products = [
                {"domain": dom, "product": prod, "status": st, "assertions": asc}
                for dom, prod, st, asc in domain_products
            ]
            return m.to_dict()

        def fail(a: str) -> dict[str, Any]:
            return {"assertion": a, "passed": False}

        def ok(a: str) -> dict[str, Any]:
            return {"assertion": a, "passed": True}

        def cur_issues(card_data: dict[str, Any]) -> int:
            return sum(
                1
                for p in card_data["products"]
                for a in p.get("assertions", [])
                if not a.get("passed")
            ) + sum(
                1
                for p in card_data["products"]
                if p.get("status", "ok") not in ("ok",)
            )

        prev = card([
            ("ai-commercial", "report", "ok", [ok("_no_cross_domain_noise"), ok("_not_empty")]),
            ("medical-research", "report", "ok", [ok("_not_empty")]),
            ("financial-intelligence", "report", "ok", [ok("_no_financial_dilution")]),
            ("ai-commercial", "digest", "ok", []),
        ])
        cur = card([
            ("ai-commercial", "report", "ok",
             [fail("_no_cross_domain_noise"), ok("_not_empty")]),
            ("medical-research", "report", "ok",
             [fail("_references_numbered"), fail("_not_empty")]),
            ("financial-intelligence", "report", "ok",
             [fail("_no_financial_dilution"), fail("_not_empty")]),
            ("ai-commercial", "digest", "missing", []),
        ])
        d = vm.diff_report_cards(prev, cur)
        c = d["counts"]
        reconciled = c["new"] + c["regressed"] + c["existing_failing"]
        hand = cur_issues(cur)
        assert hand == 6
        assert reconciled == hand, (
            f"#340: diff buckets {c} fail to reconcile across domains "
            f"(hand-counted {hand})"
        )
        # Domain is part of every bucket item's identity.
        assert c == {"new": 2, "regressed": 4, "fixed": 0, "existing_failing": 0}
        assert ("medical-research", "report", "_references_numbered") in d["new"]
        assert ("financial-intelligence", "report", "_not_empty") in d["new"]
        assert ("medical-research", "report", "_not_empty") in d["regressed"]
        assert ("ai-commercial", "digest", vm.PRODUCT_STATUS) in d["regressed"]
        assert ("financial-intelligence", "report", "_no_financial_dilution") in d["regressed"]

    def test_run_matrix_summary_breakdown_reconciles(self, tmp_path: Path) -> None:
        """#336 — the matrix report summary must break down failures into
        failing_assertions + missing_products + error_products so
        ``failures`` reconciles without hand-reading the JSON."""
        with patch("autoinfo.validation_matrix._generate_product",
                   side_effect=[CLEAN, RuntimeError("boom")]), \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(
                ["ai-commercial"], ["digest", "report"], only_assert=False,
                batch_id="b1", artifacts_dir=tmp_path,
            )
        s = report.summary
        assert s["error_products"] == 1
        assert s["missing_products"] == 0
        assert s["failing_assertions"] == 0
        assert s["failures"] == (
            s["failing_assertions"] + s["missing_products"] + s["error_products"]
        )

    def test_as_str_helper(self) -> None:
        class _DO:
            output = "delivery"

        assert vm._as_str(_DO()) == "delivery"
        assert vm._as_str("plain") == "plain"

    def test_assertion_names_consistent(self) -> None:
        for name, fn in vm.ASSERTION_FUNCS:
            r = fn("x", "d", "p")
            assert r.name == name, (name, r.name)


class TestBatchIsolation:
    """#335 — validate artifacts/snapshots must be isolated per batch: full
    mode persists generated products under ``artifacts_dir/<batch_id>`` and
    ``--only-assert`` scans that batch tree, never the shared ``outputs/``."""

    def test_full_mode_persists_products_per_batch(self, tmp_path: Path) -> None:
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value="rendered body"), \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(
                ["ai-commercial"], ["digest"], only_assert=False,
                batch_id="b1", artifacts_dir=tmp_path,
            )
        prod = tmp_path / "b1" / "products" / "ai-commercial" / "digest-markdown-b1.md"
        assert prod.is_file()
        assert prod.read_text(encoding="utf-8") == "rendered body"
        assert report.batch_id == "b1"

    def test_batches_are_isolated_no_overwrite(self, tmp_path: Path) -> None:
        with patch("autoinfo.validation_matrix._generate_product",
                   side_effect=["batch-1-body", "batch-2-body"]), \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            vm.run_matrix(["d"], ["digest"], only_assert=False,
                          batch_id="b1", artifacts_dir=tmp_path)
            vm.run_matrix(["d"], ["digest"], only_assert=False,
                          batch_id="b2", artifacts_dir=tmp_path)
        b1 = tmp_path / "b1" / "products" / "d" / "digest-markdown-b1.md"
        b2 = tmp_path / "b2" / "products" / "d" / "digest-markdown-b2.md"
        assert b1.is_file() and b1.read_text(encoding="utf-8") == "batch-1-body"
        assert b2.is_file() and b2.read_text(encoding="utf-8") == "batch-2-body"

    def test_only_assert_scans_batch_tree_not_outputs(self, tmp_path: Path) -> None:
        batch_prod = tmp_path / "b1" / "products" / "ai-commercial" / "digest-markdown-b1.md"
        batch_prod.parent.mkdir(parents=True)
        batch_prod.write_text(CLEAN, encoding="utf-8")
        polluted = tmp_path / "outputs" / "ai-commercial" / "digest-markdown-zzz.md"
        polluted.parent.mkdir(parents=True)
        polluted.write_text(
            "_No key takeaways were extracted for this period._", encoding="utf-8",
        )
        with patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(
                ["ai-commercial"], ["digest"], only_assert=True,
                batch_id="b1", artifacts_dir=tmp_path,
            )
        assert report.summary["failures"] == 0
        assert not any(p.get("status") == "missing" for p in report.products)

    def test_artifacts_dir_none_keeps_legacy_outputs_scan(self, tmp_path: Path) -> None:
        fixture = tmp_path / "digest-report-a.md"
        fixture.write_text(CLEAN, encoding="utf-8")
        with patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[fixture]) as lookup, \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"):
            report = vm.run_matrix(["ai-commercial"], ["digest"], only_assert=True)
        assert report.summary["failures"] == 0
        assert report.batch_id
        assert lookup.call_args.kwargs.get("base_dir") is None


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

    def test_diff_command_reconciliation_failure_is_hard_exit(self, tmp_path: Path) -> None:
        """#340 — when the diff buckets do NOT reconcile with the card failure
        count, the CLI must exit non-zero (hard gate), not print a soft
        WARNING and continue."""
        prev = tmp_path / "prev.json"
        cur = tmp_path / "cur.json"
        prev.write_text(json.dumps({"products": [{
            "product": "p", "assertions": [{"assertion": "_title_first", "passed": True}],
        }]}), encoding="utf-8")
        cur.write_text(json.dumps({"products": [{
            "product": "p", "assertions": [{"assertion": "_title_first", "passed": True}],
        }]}), encoding="utf-8")
        with patch("autoinfo.cli.validate.card_issue_counts",
                   side_effect=[{"failing_assertions": 0, "missing_products": 0,
                                 "error_products": 0},
                                {"failing_assertions": 99, "missing_products": 0,
                                 "error_products": 0}]):
            result = runner.invoke(app, ["diff", str(prev), str(cur)])
        assert "do not reconcile" in result.output
        assert result.exit_code == 1

    def test_default_domains_fallback(self) -> None:
        from autoinfo.cli import validate as _v

        with patch("autoinfo.config.get_config_path", return_value=None):
            domains = _v._default_domains()
        assert domains

    def test_only_assert_without_batch_keeps_legacy_scan(self, tmp_path: Path) -> None:
        """#335 — ``--only-assert`` without ``--batch`` must NOT scan the batch
        tree (it would report every product missing); it keeps the legacy
        shared outputs/ scan (backward compatible)."""
        report = vm.MatrixReport(generated_at="t", commit="abc", batch_id="abc-1")
        report.summary = {"failures": 0, "domains": ["d"], "products": ["digest"]}
        with patch("autoinfo.cli.validate.run_matrix", return_value=report) as rm, \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"), \
             patch("autoinfo.cli.validate.save_report_card"):
            result = runner.invoke(app, [
                "matrix", "--only-assert", "--domains", "ai-commercial",
                "--products", "digest", "--snapshot-dir", str(tmp_path / "snap"),
            ])
        assert result.exit_code == 0, result.output
        assert rm.call_args.kwargs["artifacts_dir"] is None
        assert rm.call_args.kwargs["batch_id"]

    def test_only_assert_with_batch_targets_batch_tree(self, tmp_path: Path) -> None:
        """#335 — ``--only-assert --batch <id>`` scans the isolated batch tree
        (``<snapshot-dir>/<batch_id>/products``)."""
        report = vm.MatrixReport(generated_at="t", commit="abc", batch_id="b1")
        report.summary = {"failures": 0, "domains": ["d"], "products": ["digest"]}
        snap = tmp_path / "snap"
        with patch("autoinfo.cli.validate.run_matrix", return_value=report) as rm, \
             patch("autoinfo.validation_matrix._current_commit", return_value="abc"), \
             patch("autoinfo.cli.validate.save_report_card"):
            result = runner.invoke(app, [
                "matrix", "--only-assert", "--batch", "b1",
                "--domains", "ai-commercial", "--products", "digest",
                "--snapshot-dir", str(snap),
            ])
        assert result.exit_code == 0, result.output
        assert rm.call_args.kwargs["artifacts_dir"] == snap
        assert rm.call_args.kwargs["batch_id"] == "b1"

    def test_write_html_report(self, tmp_path: Path) -> None:
        from autoinfo.cli import validate as _v

        report = vm.MatrixReport(generated_at="t", commit="c")
        report.products = [{"domain": "d", "product": "p", "status": "ok"}]
        out = tmp_path / "card.html"
        _v._write_html(report, out)
        assert out.is_file()
        assert "report card" in out.read_text(encoding="utf-8")
