"""RED tests for #348 — ``validate --matrix`` smart-skip of stable (domain, product) pairs.

Issue #348: when a product has passed N consecutive batches, no code touched its
template/rendering path, and no new raw data arrived, ``validate --matrix`` should
NOT regenerate it — instead it reuses the last persisted artifact, runs the cheap
assertion pass on it (防漏 — a now-failing artifact is reported as failing, not
skipped), and marks the row ``frozen``/``stale`` in the report card.  ``--no-skip``
forces full regeneration; premium products (premium-briefing, column,
enterprise-briefing) need stricter skip conditions.

These tests define the target API surface the implementation will provide.  The
implementation does NOT exist yet — every test fails RED on the current tree
(AttributeError on the not-yet-existing symbols, AssertionError on the
``schema_version`` 1→2 contract, or AssertionError on the missing CLI flags), and
the implementer turns them GREEN by shipping the design below.

Target API (referenced only inside test bodies so collection always succeeds):

* ``vm.SkipPolicy`` — dataclass: ``allow_skip: bool = False``,
  ``threshold: int = 3``, ``skip_premium: bool = False``,
  ``data_dir: Path | None = None`` (default ``allow_skip=False`` keeps existing
  callers unchanged).
* ``vm.run_matrix(..., skip: vm.SkipPolicy | None = None)`` — new keyword-only
  argument, default ``None`` (backward compatible).
* ``vm._load_batch_history(snapshot_dir)`` — glob ``report-card-*.json`` under
  the snapshot dir's batch subdirs, sorted oldest→newest.
* ``vm._last_pass_commit(history, domain, product)`` — commit of the newest
  trailing batch where the (domain, product) row exists, status ``"ok"`` and all
  assertions passed; ``None`` when the newest batch fails.
* ``vm._consecutive_passes(history, domain, product)`` — trailing count of
  consecutive passing batches; a failing/missing row in the middle resets.
* ``vm._code_changed(since_commit, product, domain, template_paths)``.
* ``vm._raw_entry_count(domain, data_dir)`` — count of ``.md`` files under
  ``<data_dir>/<domain>/01-Raw/``.
* ``vm._should_skip(history, domain, product, *, policy, template_paths,
  raw_counts)`` — pure decision.
* ``vm._premium_products()`` — the products held to the stricter skip bar
  (the non-free PRODUCT_TEMPLATES rows that appear in the matrix grid).

Deterministic only: every test patches ``vm._generate_product``,
``vm._current_commit``, ``vm._code_changed``, ``vm._raw_entry_count`` and/or
``vm._persisted_product_paths``; there is no LLM call, no network access and no
real git subprocess.  All filesystem state lives under ``tmp_path``.
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

# Products held to the stricter #348 skip bar: PRODUCT_TEMPLATES rows with
# access_level != "free" that appear in the matrix grid (pinned by
# test_premium_set_contract against the live PRODUCT_TEMPLATES registry).
PREMIUM = {"premium-briefing", "column", "enterprise-briefing"}

# A fully-passing rendered report (passes all 12 formalized assertions for the
# ai-commercial/report pair) — used as the reused-artifact body and as the
# regeneration result so the cheap assertion pass is deterministic.
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


# ---------------------------------------------------------------------------
# Fixture helpers — build report-card dicts, batch trees and artifacts.
# Batch layout modelled on #335: <snapshot_dir>/<batch_id>/report-card-<commit>
# -<stamp>.json + <snapshot_dir>/<batch_id>/products/<domain>/<product>-markdown
# -<batch_id>.md
# ---------------------------------------------------------------------------


def _card_dict(
    commit: str,
    batch_id: str,
    products: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    schema_version: int = 1,
    generated_at: str = "2026-08-21T00:00:00Z",
) -> dict[str, Any]:
    """A report-card dict in the ``MatrixReport.to_dict()`` shape."""
    return {
        "schema_version": schema_version,
        "tool": "autoinfo validate --matrix",
        "generated_at": generated_at,
        "commit": commit,
        "batch_id": batch_id,
        "products": products,
        "summary": summary or {},
    }


def _pass_row(domain: str, product: str) -> dict[str, Any]:
    """A fully-passing product row (status ok + passing assertions)."""
    return {
        "domain": domain,
        "product": product,
        "status": "ok",
        "assertions": [
            {"assertion": "_not_empty", "passed": True},
            {"assertion": "_title_first", "passed": True},
        ],
    }


def _fail_row(domain: str, product: str) -> dict[str, Any]:
    """A failing product row (status ok but a failing assertion)."""
    return {
        "domain": domain,
        "product": product,
        "status": "ok",
        "assertions": [{"assertion": "_not_empty", "passed": False}],
    }


def _write_batch(
    snap: Path,
    batch_id: str,
    commit: str,
    stamp: str,
    products: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    schema_version: int = 1,
    generated_at: str = "2026-08-21T00:00:00Z",
) -> dict[str, Any]:
    """Persist a report card at ``<snap>/<batch_id>/report-card-<commit>-<stamp>
    .json`` and return the card dict."""
    batch_dir = snap / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    card = _card_dict(
        commit, batch_id, products,
        summary=summary, schema_version=schema_version, generated_at=generated_at,
    )
    (batch_dir / f"report-card-{commit}-{stamp}.json").write_text(
        json.dumps(card, ensure_ascii=False), encoding="utf-8",
    )
    return card


def _write_artifact(
    snap: Path, batch_id: str, domain: str, product: str, text: str,
) -> Path:
    """Persist a product artifact at ``<snap>/<batch_id>/products/<domain>/
    <product>-markdown-<batch_id>.md``; returns its path."""
    path = (
        snap / batch_id / "products" / domain / f"{product}-markdown-{batch_id}.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _passing_history(domain: str, product: str, n: int) -> list[dict[str, Any]]:
    """``n`` oldest→newest fully-passing report cards for (domain, product),
    each recording ``summary.raw_counts = {domain: 5}`` at generation time."""
    return [
        _card_dict(
            f"c{i}", f"b{i}", [_pass_row(domain, product)],
            summary={"raw_counts": {domain: 5}},
            generated_at=f"2026-08-{i:02d}T00:00:00Z",
        )
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Skip decision — pure _should_skip + run_matrix integration
# ---------------------------------------------------------------------------


class TestSkipDecision:
    def test_skip_on_n_consecutive_pass(self, tmp_path: Path) -> None:
        """#348 — N (=3) consecutive fully-passing batches, no code change, no
        new raw data ⇒ _should_skip True, and run_matrix skips regeneration,
        reuses the last artifact and marks the row frozen/stale."""
        kb = tmp_path / "kb"
        history = _passing_history("ai-commercial", "report", 3)

        # Pure decision.
        with patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False):
            assert vm._should_skip(
                history, "ai-commercial", "report",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, data_dir=kb,
                ),
                template_paths=[], raw_counts={"ai-commercial": 5},
            ) is True

        # Integration: 3 real batches b1/b2/b3 + b3's artifact on disk, then a
        # 4th run that must skip.
        snap = tmp_path / "snap"
        b3_artifact = _write_artifact(snap, "b3", "ai-commercial", "report", CLEAN)
        b1_card = _write_batch(
            snap, "b1", "c1", "1", [_pass_row("ai-commercial", "report")],
            summary={"raw_counts": {"ai-commercial": 5}},
            generated_at="2026-08-01T00:00:00Z",
        )
        b2_card = _write_batch(
            snap, "b2", "c2", "2", [_pass_row("ai-commercial", "report")],
            summary={"raw_counts": {"ai-commercial": 5}},
            generated_at="2026-08-02T00:00:00Z",
        )
        b3_card = _write_batch(
            snap, "b3", "c3", "3", [_pass_row("ai-commercial", "report")],
            summary={"raw_counts": {"ai-commercial": 5}},
            generated_at="2026-08-03T00:00:00Z",
        )
        assert b1_card and b2_card  # silence unused-helper warnings
        reused_row = next(
            p for p in b3_card["products"] if p["product"] == "report"
        )
        with patch("autoinfo.validation_matrix._generate_product") as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"), \
             patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False), \
             patch("autoinfo.validation_matrix._raw_entry_count",
                   create=True, return_value=5), \
             patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[b3_artifact]):
            report = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False,
                batch_id="b4", artifacts_dir=snap,
                skip=vm.SkipPolicy(allow_skip=True, threshold=3, data_dir=kb),
            )
        gen.assert_not_called()
        row = next(p for p in report.products if p["product"] == "report")
        assert row["status"] == "ok"
        assert row.get("frozen") is True
        assert row.get("reused_batch") == "b3"
        assert row.get("freshness") == "stale"
        assert row.get("consecutive_passes") == 3
        # The skipped row carries the reused card's stored passing assertions.
        assert row["assertions"] == reused_row["assertions"]
        assert report.summary.get("skipped_products") == ["report"]
        assert report.summary.get("raw_counts") == {"ai-commercial": 5}
        assert report.to_dict()["schema_version"] == 2
        assert report.summary["failures"] == 0

    def test_policy_default_and_none_regenerate(self) -> None:
        """#348 — backward compatible: ``skip=None`` (the default) and
        ``SkipPolicy(allow_skip=False)`` both regenerate; no frozen key."""
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value=CLEAN) as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"):
            report_none = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False, skip=None,
            )
        assert gen.called
        assert "frozen" not in report_none.products[0]

        gen.reset_mock()
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value=CLEAN) as gen_off, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"):
            report_off = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False,
                skip=vm.SkipPolicy(allow_skip=False),
            )
        assert gen_off.called
        assert "frozen" not in report_off.products[0]

    def test_code_change_invalidates_skip(self, tmp_path: Path) -> None:
        """#348 — same N-pass history but the product's template/render path
        changed ⇒ _should_skip False ⇒ regenerate (no frozen row)."""
        kb = tmp_path / "kb"
        history = _passing_history("ai-commercial", "report", 3)

        with patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=True):
            assert vm._should_skip(
                history, "ai-commercial", "report",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, data_dir=kb,
                ),
                template_paths=[], raw_counts={"ai-commercial": 5},
            ) is False

        snap = tmp_path / "snap"
        for bid, commit, stamp in [("b1", "c1", "1"), ("b2", "c2", "2"), ("b3", "c3", "3")]:
            _write_batch(
                snap, bid, commit, stamp, [_pass_row("ai-commercial", "report")],
                summary={"raw_counts": {"ai-commercial": 5}},
            )
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value=CLEAN) as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"), \
             patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=True), \
             patch("autoinfo.validation_matrix._raw_entry_count",
                   create=True, return_value=5):
            report = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False,
                batch_id="b4", artifacts_dir=snap,
                skip=vm.SkipPolicy(allow_skip=True, threshold=3, data_dir=kb),
            )
        assert gen.called
        row = next(p for p in report.products if p["product"] == "report")
        assert row.get("frozen") is not True

    def test_data_change_invalidates_skip(self, tmp_path: Path) -> None:
        """#348 — the per-domain raw count changed since the last card (new
        data arrived in 01-Raw) ⇒ _should_skip False ⇒ regenerate."""
        kb = tmp_path / "kb"
        history = _passing_history("ai-commercial", "report", 3)

        # Pure decision: card recorded 5 raw entries, the run sees 99.
        with patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False):
            assert vm._should_skip(
                history, "ai-commercial", "report",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, data_dir=kb,
                ),
                template_paths=[], raw_counts={"ai-commercial": 99},
            ) is False

        snap = tmp_path / "snap"
        for bid, commit, stamp in [("b1", "c1", "1"), ("b2", "c2", "2"), ("b3", "c3", "3")]:
            _write_batch(
                snap, bid, commit, stamp, [_pass_row("ai-commercial", "report")],
                summary={"raw_counts": {"ai-commercial": 5}},
            )
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value=CLEAN) as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"), \
             patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False), \
             patch("autoinfo.validation_matrix._raw_entry_count",
                   create=True, return_value=99), \
             patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[]):
            report = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False,
                batch_id="b4", artifacts_dir=snap,
                skip=vm.SkipPolicy(allow_skip=True, threshold=3, data_dir=kb),
            )
        assert gen.called
        row = next(p for p in report.products if p["product"] == "report")
        assert row.get("frozen") is not True

    def test_premium_products_need_stricter_conditions(self, tmp_path: Path) -> None:
        """#348 — premium/enterprise products need threshold+2 consecutive
        passes (3→5) unless ``skip_premium`` opts in; free products keep the
        plain threshold."""
        kb = tmp_path / "kb"
        raw = {"ai-commercial": 5}

        def history(product: str, n: int) -> list[dict[str, Any]]:
            return _passing_history("ai-commercial", product, n)

        with patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False):
            # premium-briefing with 3 passes, skip_premium=False → NOT skipped.
            assert vm._should_skip(
                history("premium-briefing", 3), "ai-commercial", "premium-briefing",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, skip_premium=False, data_dir=kb,
                ),
                template_paths=[], raw_counts=raw,
            ) is False
            # premium-briefing with 5 passes, skip_premium=True → skipped.
            assert vm._should_skip(
                history("premium-briefing", 5), "ai-commercial", "premium-briefing",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, skip_premium=True, data_dir=kb,
                ),
                template_paths=[], raw_counts=raw,
            ) is True
            # premium-briefing with 5 passes, skip_premium=False → skipped
            # (5 >= threshold + 2).
            assert vm._should_skip(
                history("premium-briefing", 5), "ai-commercial", "premium-briefing",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, skip_premium=False, data_dir=kb,
                ),
                template_paths=[], raw_counts=raw,
            ) is True
            # Free product with 3 passes is NOT held to the premium bar.
            assert vm._should_skip(
                history("report", 3), "ai-commercial", "report",
                policy=vm.SkipPolicy(
                    allow_skip=True, threshold=3, skip_premium=False, data_dir=kb,
                ),
                template_paths=[], raw_counts=raw,
            ) is True

    def test_premium_set_contract(self) -> None:
        """#348 — the stricter-skip product set is exactly the non-free
        PRODUCT_TEMPLATES rows that appear in the matrix grid; the
        implementation must expose the same set via _premium_products()."""
        from autoinfo.output import PRODUCT_TEMPLATES

        expected = {
            row["name"] for row in PRODUCT_TEMPLATES
            if row.get("access_level") != "free"
            and row["name"] in vm.MATRIX_PRODUCTS
        }
        assert expected == PREMIUM
        assert PREMIUM == {"premium-briefing", "column", "enterprise-briefing"}
        # RED: the skip logic must read its premium set from one source of truth.
        assert set(vm._premium_products()) == PREMIUM

    def test_missing_artifact_forces_regeneration(self, tmp_path: Path) -> None:
        """#348 — history says the last batch passed but the persisted artifact
        is gone: skip cannot reuse a missing artifact ⇒ regenerate (防漏)."""
        kb = tmp_path / "kb"
        snap = tmp_path / "snap"
        for bid, commit, stamp in [("b1", "c1", "1"), ("b2", "c2", "2"), ("b3", "c3", "3")]:
            _write_batch(
                snap, bid, commit, stamp, [_pass_row("ai-commercial", "report")],
                summary={"raw_counts": {"ai-commercial": 5}},
            )
        with patch("autoinfo.validation_matrix._generate_product",
                   return_value=CLEAN) as gen, \
             patch("autoinfo.validation_matrix._current_commit", return_value="c4"), \
             patch("autoinfo.validation_matrix._code_changed",
                   create=True, return_value=False), \
             patch("autoinfo.validation_matrix._raw_entry_count",
                   create=True, return_value=5), \
             patch("autoinfo.validation_matrix._persisted_product_paths",
                   return_value=[]):
            report = vm.run_matrix(
                ["ai-commercial"], ["report"], only_assert=False,
                batch_id="b4", artifacts_dir=snap,
                skip=vm.SkipPolicy(allow_skip=True, threshold=3, data_dir=kb),
            )
        assert gen.called
        row = next(p for p in report.products if p["product"] == "report")
        assert row.get("frozen") is not True


# ---------------------------------------------------------------------------
# Report-card schema v2 + frozen rows in the #340 diff reconciliation
# ---------------------------------------------------------------------------


class TestReportCardV2:
    def test_frozen_rows_keep_diff_reconciliation(self) -> None:
        """#348 — a frozen row (status ok + stored passing assertions) never
        lands in a failure bucket, card_issue_counts never counts it, and the
        #340 reconciliation (cur issues == new + regressed + existing_failing)
        still holds.  RED hook: schema_version bumps 1 → 2."""
        # RED: the v2 schema contract ships with #348.
        assert vm.MatrixReport().to_dict()["schema_version"] == 2, (
            "#348 must bump the report-card schema_version to 2"
        )

        v1 = _card_dict("c3", "b3", [_pass_row("ai-commercial", "report")])
        frozen_row = {
            "domain": "ai-commercial", "product": "report", "status": "ok",
            "frozen": True, "reused_batch": "b3", "freshness": "stale",
            "consecutive_passes": 3,
            "assertions": [{"assertion": "_not_empty", "passed": True}],
        }
        v2 = _card_dict(
            "c4", "b4", [frozen_row],
            summary={"skipped_products": ["report"], "raw_counts": {"ai-commercial": 5}},
            schema_version=2,
        )
        d = vm.diff_report_cards(v1, v2)
        counts = d["counts"]
        cur_issues = sum(vm.card_issue_counts(v2).values())
        assert counts["new"] + counts["regressed"] + counts["existing_failing"] == cur_issues
        assert counts == {"new": 0, "regressed": 0, "fixed": 0, "existing_failing": 0}
        # The frozen row is in NO failure bucket.
        failure_buckets = d["new"] + d["regressed"] + d["existing_failing"]
        assert ("ai-commercial", "report", "_not_empty") not in failure_buckets
        assert ("ai-commercial", "report", vm.PRODUCT_STATUS) not in (
            d["regressed"] + d["new"]
        )
        # And card_issue_counts does not count the frozen row.
        assert vm.card_issue_counts(v2)["failing_assertions"] == 0

    def test_v1_v2_schema_compat_diff(self) -> None:
        """#348 — a v1 card (schema_version 1, no new fields) diffs cleanly
        against a v2 card (schema_version 2, frozen fields present); the diff
        works and reconciles.  RED hook: schema_version bumps 1 → 2."""
        # RED: the v2 schema contract ships with #348.
        assert vm.MatrixReport().to_dict()["schema_version"] == 2, (
            "#348 must bump the report-card schema_version to 2"
        )

        v1 = _card_dict("c3", "b3", [_pass_row("ai-commercial", "report")])
        v2 = _card_dict(
            "c4", "b4",
            [{
                "domain": "ai-commercial", "product": "report", "status": "ok",
                "frozen": True, "reused_batch": "b3", "freshness": "stale",
                "consecutive_passes": 3,
                "assertions": [{"assertion": "_not_empty", "passed": True}],
            }],
            summary={"skipped_products": ["report"], "raw_counts": {"ai-commercial": 5}},
            schema_version=2,
        )
        d = vm.diff_report_cards(v1, v2)
        assert d["counts"] == {
            "new": 0, "regressed": 0, "fixed": 0, "existing_failing": 0,
        }
        assert not (d["new"] + d["regressed"] + d["existing_failing"])


# ---------------------------------------------------------------------------
# Batch-history semantics
# ---------------------------------------------------------------------------


class TestBatchHistory:
    def test_load_batch_history_sorted_oldest_newest(self, tmp_path: Path) -> None:
        """#348 — _load_batch_history globs report-card-*.json under the batch
        subdirs and returns them sorted oldest→newest."""
        snap = tmp_path / "snap"
        _write_batch(
            snap, "b1", "c1", "1", [_pass_row("ai-commercial", "report")],
            summary={"raw_counts": {"ai-commercial": 5}},
            generated_at="2026-08-20T10:00:00Z",
        )
        _write_batch(
            snap, "b2", "c2", "2", [_pass_row("ai-commercial", "report")],
            summary={"raw_counts": {"ai-commercial": 5}},
            generated_at="2026-08-21T10:00:00Z",
        )
        history = vm._load_batch_history(snap)
        assert len(history) == 2
        assert history[0]["batch_id"] == "b1"
        assert history[-1]["batch_id"] == "b2"
        # The newest (trailing) batch is the last entry.
        assert history[-1]["commit"] == "c2"

    def test_consecutive_passes_trailing_only(self) -> None:
        """#348 — _consecutive_passes counts only the TRAILING run of passing
        batches: a failing/missing row in the middle resets; a failing newest
        batch → 0."""
        # pass, pass, fail, pass, pass → 2
        history = [
            _card_dict("c1", "b1", [_pass_row("d", "report")]),
            _card_dict("c2", "b2", [_pass_row("d", "report")]),
            _card_dict("c3", "b3", [_fail_row("d", "report")]),
            _card_dict("c4", "b4", [_pass_row("d", "report")]),
            _card_dict("c5", "b5", [_pass_row("d", "report")]),
        ]
        assert vm._consecutive_passes(history, "d", "report") == 2

        # trailing fail (newest batch fails) → 0
        trailing_fail = [
            _card_dict("c1", "b1", [_pass_row("d", "report")]),
            _card_dict("c2", "b2", [_pass_row("d", "report")]),
            _card_dict("c3", "b3", [_fail_row("d", "report")]),
        ]
        assert vm._consecutive_passes(trailing_fail, "d", "report") == 0

        # a missing row in the middle resets the trailing run → 2
        missing_middle = [
            _card_dict("c1", "b1", [_pass_row("d", "report")]),
            _card_dict("c2", "b2", []),  # (d, report) row absent this batch
            _card_dict("c3", "b3", [_pass_row("d", "report")]),
            _card_dict("c4", "b4", [_pass_row("d", "report")]),
        ]
        assert vm._consecutive_passes(missing_middle, "d", "report") == 2

    def test_last_pass_commit_returns_newest_pass(self) -> None:
        """#348 — _last_pass_commit returns the commit of the newest trailing
        fully-passing batch; None when the newest batch fails."""
        all_pass = [
            _card_dict("c1", "b1", [_pass_row("d", "report")]),
            _card_dict("c2", "b2", [_pass_row("d", "report")]),
            _card_dict("c3", "b3", [_pass_row("d", "report")]),
        ]
        assert vm._last_pass_commit(all_pass, "d", "report") == "c3"

        newest_fails = [
            _card_dict("c1", "b1", [_pass_row("d", "report")]),
            _card_dict("c2", "b2", [_fail_row("d", "report")]),
        ]
        assert vm._last_pass_commit(newest_fails, "d", "report") is None


# ---------------------------------------------------------------------------
# CLI surface — --no-skip / --skip-threshold / --skip-premium
# ---------------------------------------------------------------------------


class TestValidateCliSkipFlags:
    def test_matrix_help_lists_skip_flags(self) -> None:
        """#348 — ``validate matrix --help`` advertises the smart-skip flags:
        ``--no-skip`` (force full regeneration), ``--skip-threshold`` and
        ``--skip-premium``.  RED today: the flags do not exist."""
        result = runner.invoke(app, ["matrix", "--help"])
        assert result.exit_code == 0, result.output
        for flag in ("--no-skip", "--skip-threshold", "--skip-premium"):
            assert flag in result.output, (
                f"#348: `validate matrix --help` must advertise {flag}"
            )
