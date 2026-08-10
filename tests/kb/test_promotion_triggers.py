"""T6 promotion-trigger unit tests (plan kb-curation-gap-closure).

Three automatic promotion-trigger paths, all reusing the existing
admission gate + ``promote_kb_draft``, none blocking content generation:

(a) product-driven — ``generate_digest`` / ``generate_report`` promote
    eligible 02-Draft entries before entry selection (per-entry
    try/except; a failing promotion never blocks generation).
(b) process-driven — ``run_processing(..., auto_promote=True)``
    admission-checks and promotes each entry that passes extraction +
    quality gates (per-entry try/except, default ``False``).
(c) sweep — ``KBStore.promote_pending_drafts`` (CLI ``kb promote-pending``
    + MCP ``promote_pending``): batch promotion with a summary and
    per-entry failure reasons; entries carrying a ``_failed/`` marker are
    skipped and never retried.

G4 is an LLM call; tests monkeypatch
``autoinfo.promotion.G4FactualConsistency`` with a fake checker (no real
LLM is ever invoked).  Project config is absent in tests (no
``.autoinfo/config.yaml``), so the admission gate uses its defaults
(30/30, G4 enabled).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.config import Config, QualityGateConfig
from autoinfo.kb import KBStore, PromotionRejected
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.output import _promote_eligible_drafts, generate_digest, generate_report
from autoinfo.process import ProcessResult
from autoinfo.promotion import RejectionReason
from autoinfo.quality import QualityResult

# ===================================================================
# Fixtures / builders
# ===================================================================


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    """A KBStore rooted in a fresh temp directory."""
    return KBStore(base_path=tmp_path / "knowledge")


def make_scored_raw(
    store: KBStore,
    *,
    item_id: str = "raw-001",
    title: str = "Raw source paper",
    source_url: str = "https://example.com/paper1",
    source_platform: str = "pubmed",
    g1_score: float = 72.0,
    g3_score: float = 85.0,
    with_quality_results: bool = True,
) -> KBEntry:
    """Store a 01-Raw entry with full provenance and (optionally) real
    G1/G3 gate scores, mirroring test_promotion.py."""
    item = Item(
        id=item_id,
        source_name="pubmed",
        source_type="api",
        source_url=source_url,
        source_platform=source_platform,
        title=title,
        content=(
            "Time-lapse embryo imaging has been proposed as a non-invasive "
            "method to improve embryo selection in IVF cycles."
        ),
        content_type="text",
        collected_at="2026-07-15T10:30:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=2,
    )
    if not with_quality_results:
        return store.store_entry(item)
    g3 = QualityResult(gate_name="G3-RelevanceScoring", passed=True, score=g3_score)
    g1 = QualityResult(
        gate_name="G1-SourceAuthority",
        passed=True,
        score=0.0,
        details={"source_score": g1_score},
    )
    return store.store_entry(
        item,
        quality_results={"G3-RelevanceScoring": g3, "G1-SourceAuthority": g1},
    )


def make_draft(store: KBStore, raw: KBEntry, title: str, summary: str = "") -> KBEntry:
    """Create a 02-Draft from a single Raw entry."""
    return store.create_kb_draft(
        raw_ids=[raw.entry_id],
        title=title,
        summary=summary or "Time-lapse embryo imaging improves IVF selection.",
    )


def _g4_result(passed: bool) -> QualityResult:
    if passed:
        return QualityResult(
            gate_name="G4-SummaryFactual",
            passed=True,
            score=1.0,
            details={"contradiction": False},
        )
    return QualityResult(
        gate_name="G4-SummaryFactual",
        passed=False,
        flagged=True,
        score=0.0,
        details={"contradiction": True, "action": "block"},
    )


@pytest.fixture
def patch_g4(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Monkeypatch the module-level G4 class; returns a pass/fail setter.

    The fake accepts any constructor kwargs and returns a canned
    :class:`QualityResult` from every ``check`` call.
    """
    current = {"passed": True}

    class _FakeG4:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def check(
            self,
            item: object,
            extraction: object,
            gate_config: QualityGateConfig | None = None,  # noqa: ARG002
        ) -> QualityResult:
            return _g4_result(current["passed"])

    monkeypatch.setattr("autoinfo.promotion.G4FactualConsistency", _FakeG4)

    def set_passed(passed: bool) -> None:
        current["passed"] = passed

    return set_passed


def _marker_path(store: KBStore, entry_id: str) -> Path:
    """The ``_failed/<domain>/<entry_id>.md`` marker path for a draft."""
    return store.base_path / "_failed" / "medical-research" / f"{entry_id}.md"


def _tier(store: KBStore, entry_id: str) -> str:
    """Read the index tier for *entry_id* (asserts the row exists)."""
    meta = store.index.get_entry(entry_id)
    assert meta is not None
    return str(meta["tier"])


def _assert_tier(store: KBStore, entry_id: str, expected: str) -> None:
    """Assert *entry_id* currently lives in the *expected* tier."""
    assert _tier(store, entry_id) == expected


def _file_path(store: KBStore, entry_id: str) -> str:
    """Read the index file_path for *entry_id* (asserts the row exists)."""
    meta = store.index.get_entry(entry_id)
    assert meta is not None
    return str(meta["file_path"])


# ===================================================================
# (a) Product-driven — shared _promote_eligible_drafts helper
# ===================================================================


class TestPromoteEligibleHelper:
    def test_promotes_eligible_drafts(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Helper eligible draft")

        summary = _promote_eligible_drafts(store, ["medical-research"], caller="digest")

        assert draft.entry_id in summary["promoted"]
        assert summary["rejected"] == []
        assert summary["failed"] == []
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "03-Wiki"

    def test_rejection_is_non_fatal(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store, with_quality_results=False)
        draft = make_draft(store, raw, title="Helper rejected draft")

        summary = _promote_eligible_drafts(store, ["medical-research"], caller="digest")

        assert summary["promoted"] == []
        assert len(summary["rejected"]) == 1
        assert summary["rejected"][0]["entry_id"] == draft.entry_id
        reasons = summary["rejected"][0]["reasons"]
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in reasons
        assert RejectionReason.RELEVANCE_BELOW_THRESHOLD in reasons
        # Draft untouched — still 02-Draft
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "02-Draft"

    def test_no_domains_is_noop(self, store: KBStore) -> None:
        summary = _promote_eligible_drafts(store, [], caller="digest")
        assert summary == {"promoted": [], "rejected": [], "failed": []}

    def test_unexpected_store_error_does_not_raise(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store)
        make_draft(store, raw, title="Helper error draft")

        with patch.object(store, "promote_kb_draft", side_effect=RuntimeError("boom")):
            summary = _promote_eligible_drafts(store, ["medical-research"])

        assert summary["promoted"] == []
        assert len(summary["failed"]) == 1
        assert summary["failed"][0]["error"] == "boom"


# ===================================================================
# (a) Product-driven — generate_digest integration
# ===================================================================


class TestDigestPromotionTrigger:
    def test_digest_promotes_eligible_drafts(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        """generate_digest promotes eligible 02-Draft entries before
        entry selection and still produces a digest."""
        patch_g4(True)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Digest eligible draft")

        with (
            patch("autoinfo.output.KBStore", return_value=store),
            patch("autoinfo.output._call_llm_for_digest", return_value={}),
        ):
            result = generate_digest(domain="medical-research", period="weekly")

        assert isinstance(result, str)
        # The draft was promoted to 03-Wiki and is consumed by the digest itself
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "03-Wiki"
        assert "Digest eligible draft" in result

    def test_digest_survives_when_all_drafts_rejected(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        """A failing promotion must NOT block digest generation."""
        patch_g4(False)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Digest rejected draft")

        with (
            patch("autoinfo.output.KBStore", return_value=store),
            patch("autoinfo.output._call_llm_for_digest", return_value={}),
        ):
            result = generate_digest(domain="medical-research", period="weekly")

        assert isinstance(result, str)
        # Draft rejected by the G4 gate — stays in 02-Draft, no raise
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "02-Draft"


# ===================================================================
# (a) Product-driven — generate_report integration
# ===================================================================


class TestReportPromotionTrigger:
    def test_report_promotes_eligible_drafts(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Report eligible draft")

        mock_extract = MagicMock(
            side_effect=[
                _make_grouping([draft.entry_id]),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore", return_value=store),
            patch.object(_get_llm_extractor_class(), "extract", mock_extract),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            result = generate_report(domain="medical-research", format="markdown")

        assert isinstance(result, str)
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "03-Wiki"


def _make_grouping(entry_ids: list[str]) -> ExtractionResult:
    """Make a grouping ExtractionResult for the given entry IDs."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "Synthesis",
                    "description": "Synthesized findings.",
                    "entry_ids": entry_ids,
                },
            ],
        },
    )


def _make_summary() -> ExtractionResult:
    """Make a summary ExtractionResult."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Executive Summary",
        custom_fields={
            "executive_summary": "This report synthesizes findings.",
        },
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the LLMExtractor class used inside generate_report."""
    return LLMExtractor


# ===================================================================
# (b) Process-driven — run_processing(auto_promote=...)
# ===================================================================


def _make_quality_results_all_pass() -> dict[str, QualityResult]:
    """Quality gate results where all three gates pass."""
    return {
        "G1-SourceAuthority": QualityResult(
            gate_name="G1-SourceAuthority",
            passed=True,
            score=1.0,
            details={"quality_tier": 1, "source_name": "pubmed"},
        ),
        "G2-Dedup": QualityResult(
            gate_name="G2-Dedup",
            passed=True,
            score=1.0,
            details={"is_duplicate": False, "matched_by": None},
        ),
        "G3-RelevanceScoring": QualityResult(
            gate_name="G3-RelevanceScoring",
            passed=True,
            score=85.0,
            details={"hidden": False},
        ),
    }


@pytest.fixture
def sample_items() -> list[Item]:
    """Two synthetic items for processing tests."""
    return [
        Item(
            id="item-001",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/1",
            title="First test article about IVF",
            content="This is the content of the first test article about IVF treatment outcomes.",
            content_type="text",
            collected_at="2026-07-15T10:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["IVF"],
            quality_tier=1,
            raw_data={},
        ),
        Item(
            id="item-002",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/2",
            title="Second test article about neuroplasticity",
            content="This is the content of the second test article about synaptic plasticity.",
            content_type="text",
            collected_at="2026-07-15T11:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["neuroplasticity"],
            quality_tier=1,
            raw_data={},
        ),
    ]


@pytest.fixture
def mock_extraction() -> ExtractionResult:
    """A predictable :class:`ExtractionResult` for mock LLM calls."""
    return ExtractionResult(
        item_id="item-001",
        title="First test article about IVF",
        tl_dr="A test article about IVF treatment outcomes.",
        key_points=["IVF is a key treatment", "Outcomes depend on many factors"],
        entities=[{"name": "IVF", "type": "procedure", "relevance": 0.9}],
        relevance_score=85.0,
    )


class TestProcessAutoPromote:
    """``run_processing(auto_promote=...)`` — per-entry auto promotion."""

    def _run(
        self,
        mock_store: MagicMock,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
        auto_promote: bool = False,
    ) -> ProcessResult:
        from autoinfo.process import run_processing

        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(
                _get_llm_extractor_class(),
                "extract",
                MagicMock(side_effect=lambda item, schema=None: mock_extraction),
            ),
            patch(
                "autoinfo.process.run_quality_gates",
                MagicMock(return_value=_make_quality_results_all_pass()),
            ),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            return run_processing("medical-research", auto_promote=auto_promote)

    def _mock_store(self, entry: KBEntry, draft: KBEntry | None = None) -> MagicMock:
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = entry
        mock_store.list_entries.return_value = []
        if draft is not None:
            mock_store.create_kb_draft.return_value = draft
        return mock_store

    def test_auto_promote_default_false_does_not_promote(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
    ) -> None:
        """Default behavior unchanged: no draft creation, no promotion."""
        entry = KBEntry(entry_id="test", title="test", domain="test")
        mock_store = self._mock_store(entry)

        result = self._run(mock_store, sample_items, mock_extraction)

        assert result.kb_entries_created == 2
        mock_store.create_kb_draft.assert_not_called()
        mock_store.promote_kb_draft.assert_not_called()

    def test_auto_promote_true_promotes_eligible_entries(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
    ) -> None:
        """Each gated-passing entry is drafted and promoted (per-entry)."""
        entry = KBEntry(entry_id="test", title="test", domain="test")
        draft = KBEntry(entry_id="medical-research-draft-test", title="test", domain="test")
        mock_store = self._mock_store(entry, draft)
        mock_store.promote_kb_draft.return_value = {"status": "promoted"}

        result = self._run(
            mock_store, sample_items, mock_extraction, auto_promote=True
        )

        assert result.errors == []
        assert mock_store.create_kb_draft.call_count == 2
        assert mock_store.promote_kb_draft.call_count == 2
        assert all(log["auto_promoted"] is True for log in result.per_item_logs)

    def test_auto_promote_rejection_is_non_fatal(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
    ) -> None:
        """PromotionRejected per entry is caught — item still 'ok', no errors."""
        entry = KBEntry(entry_id="test", title="test", domain="test")
        draft = KBEntry(entry_id="medical-research-draft-test", title="test", domain="test")
        mock_store = self._mock_store(entry, draft)
        mock_store.promote_kb_draft.side_effect = PromotionRejected(
            [RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD]
        )

        result = self._run(
            mock_store, sample_items, mock_extraction, auto_promote=True
        )

        assert result.errors == []
        assert all(log["status"] == "ok" for log in result.per_item_logs)
        assert all(log["auto_promoted"] is False for log in result.per_item_logs)
        assert all(
            log["promotion_rejected"] == ["source-score-below-threshold"]
            for log in result.per_item_logs
        )


# ===================================================================
# (c) Sweep — KBStore.promote_pending_drafts
# ===================================================================


class TestPromotePendingSweep:
    def test_sweep_promotes_eligible_and_reports_rejected(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw_ok = make_scored_raw(store, item_id="raw-ok", title="Raw ok paper")
        draft_ok = make_draft(store, raw_ok, title="Sweep eligible draft")
        raw_low = make_scored_raw(
            store, item_id="raw-low", title="Raw low paper",
            g1_score=5.0, g3_score=5.0,
        )
        draft_low = make_draft(store, raw_low, title="Sweep low-score draft")

        summary = store.promote_pending_drafts(domain="medical-research")

        assert summary["total"] == 2
        assert [p["entry_id"] for p in summary["promoted"]] == [draft_ok.entry_id]
        assert [r["entry_id"] for r in summary["rejected"]] == [draft_low.entry_id]
        reasons = summary["rejected"][0]["reasons"]
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in reasons
        assert RejectionReason.RELEVANCE_BELOW_THRESHOLD in reasons
        # Tier transitions
        _assert_tier(store, draft_ok.entry_id, "03-Wiki")
        _assert_tier(store, draft_low.entry_id, "02-Draft")

    def test_sweep_skips_entries_with_failed_marker(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        """Entries previously rejected (carrying a _failed/ marker) are
        never retried by the sweep."""
        patch_g4(True)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Sweep skipped draft")
        # Pre-existing marker (e.g. from an earlier rejected admission attempt)
        marker = _marker_path(store, draft.entry_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("---\ngate: PromotionAdmission\n---\n", encoding="utf-8")

        summary = store.promote_pending_drafts(domain="medical-research")

        assert summary["promoted"] == []
        assert summary["skipped_failed_markers"] == [draft.entry_id]
        # Draft untouched — still 02-Draft
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "02-Draft"

    def test_sweep_is_idempotent(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store)
        make_draft(store, raw, title="Sweep idempotent draft")

        first = store.promote_pending_drafts(domain="medical-research")
        assert len(first["promoted"]) == 1

        second = store.promote_pending_drafts(domain="medical-research")
        assert second["promoted"] == []
        assert second["total"] == 0  # nothing left in 02-Draft

    def test_sweep_records_caller(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        patch_g4(True)
        raw = make_scored_raw(store)
        draft = make_draft(store, raw, title="Sweep caller draft")

        store.promote_pending_drafts(domain="medical-research", caller="sweep")

        wiki_path = _file_path(store, draft.entry_id)
        raw_text = Path(wiki_path).read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        fm = yaml.safe_load(raw_text[3:end])
        assert fm["promoted_by"] == "sweep"
        assert fm["promotion_source"] == "agent"

    def test_sweep_continues_after_unexpected_failure(
        self, store: KBStore, patch_g4: Callable[[bool], None]
    ) -> None:
        """An unexpected per-entry error is collected, not raised."""
        patch_g4(True)
        raw_ok = make_scored_raw(store, item_id="raw-ok", title="Raw ok paper")
        draft_ok = make_draft(store, raw_ok, title="Sweep ok draft")
        raw_bad = make_scored_raw(store, item_id="raw-bad", title="Raw bad paper")
        draft_bad = make_draft(store, raw_bad, title="Sweep boom draft")

        real_promote = store.promote_kb_draft

        def flaky_promote(
            draft_id: str,
            *,
            config: Config | None = None,
            caller: str = "agent",
        ) -> dict[str, Any]:
            if draft_id == draft_bad.entry_id:
                raise RuntimeError("disk on fire")
            return real_promote(draft_id=draft_id, config=config, caller=caller)

        with patch.object(store, "promote_kb_draft", side_effect=flaky_promote):
            summary = store.promote_pending_drafts(domain="medical-research")

        assert [p["entry_id"] for p in summary["promoted"]] == [draft_ok.entry_id]
        assert summary["failed"] == [
            {"entry_id": draft_bad.entry_id, "error": "disk on fire"}
        ]
        _assert_tier(store, draft_ok.entry_id, "03-Wiki")
        _assert_tier(store, draft_bad.entry_id, "02-Draft")


# ===================================================================
# (c) Sweep — CLI `autoinfo kb promote-pending`
# ===================================================================


class TestCliPromotePending:
    def test_cli_promote_pending_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        patch_g4: Callable[[bool], None],
    ) -> None:
        patch_g4(True)
        from typer.testing import CliRunner

        from autoinfo.cli.kb import app as kb_app

        monkeypatch.chdir(tmp_path)
        store = KBStore()
        raw = make_scored_raw(store, item_id="raw-cli", title="Raw cli paper")
        make_draft(store, raw, title="CLI sweep draft")

        result = CliRunner().invoke(
            kb_app, ["promote-pending", "--domain", "medical-research", "--json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["domain"] == "medical-research"
        assert len(data["promoted"]) == 1
