"""Tests for item-internal second-level parallelism (llm-concurrency todo 6).

After LLM extraction, G3 (LLM relevance), G4 (factual consistency, when
enabled), G5 (translation accuracy, when enabled) and the CEFR LLM
classification run CONCURRENTLY with a per-item sub-task cap (default 4,
``AUTOINFO_SUBTASK_CAP``).  Gate semantics are untouched — the gates
themselves are unchanged, only their invocation is parallelized — and gate
results are reported in canonical G0→G5 order regardless of completion
order.

Covers:

(a) mocked gates block on a barrier → in-flight reaches the sub-task cap
    (concurrency is real) and stays at the cap when it is lowered
    (concurrency is bounded)
(b) quality results are emitted in canonical G0→G5 order even when the
    concurrent gates complete out of order
(c) flaky G4 (LLM fails twice then succeeds) → 3 attempts observed, then
    success (G4's internal 3× retry loop still drives the retries)
(d) G4 always-fail → hard-gate block path preserved (3× retry then block:
    storage skipped, item blocked, G4 writes its own ``_failed/``
    diagnostics)

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import CEFRConfig, Config, QualityGateConfig
from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import (
    _DEFAULT_SUBTASK_CAP,
    _resolve_subtask_cap,
    run_processing,
)
from autoinfo.quality import G4FactualConsistency, QualityResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(item_id: str, title: str) -> Item:
    return Item(
        id=item_id,
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url=f"https://example.com/{item_id}",
        title=title,
        content=f"This is the content of {title} about IVF treatment outcomes.",
        content_type="text",
        collected_at="2026-07-15T10:00:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=1,
        raw_data={},
    )


def _extraction(item: Item, translation: str = "") -> ExtractionResult:
    custom_fields = {}
    if translation:
        custom_fields = {"translation": translation}
    return ExtractionResult(
        item_id=item.id,
        title=item.title,
        tl_dr="A summary.",
        key_points=["A key point"],
        entities=[{"name": "IVF", "type": "procedure"}],
        relevance_score=80.0,
        custom_fields=custom_fields,
    )


def _g3_pass() -> QualityResult:
    return QualityResult(
        gate_name="G3-RelevanceScoring", passed=True, score=80.0, details={}
    )


def _g4_pass() -> QualityResult:
    return QualityResult(
        gate_name="G4-SummaryFactual", passed=True, flagged=False, details={}
    )


def _quality_all_pass():
    """Canonical deterministic-gate dict (G0..G3) — mirrors run_quality_gates."""
    return {
        "G0-SchemaIntegrity": QualityResult(
            gate_name="G0-SchemaIntegrity", passed=True, details={}
        ),
        "G1-SourceAuthority": QualityResult(
            gate_name="G1-SourceAuthority", passed=True, details={}
        ),
        "G1-TosCompliance": QualityResult(
            gate_name="G1-TosCompliance", passed=True, details={}
        ),
        "G2-Dedup": QualityResult(
            gate_name="G2-Dedup", passed=True, details={"is_duplicate": False}
        ),
        "G3-RelevanceScoring": _g3_pass(),
    }


def _entry(entry_id: str = "par-e1") -> KBEntry:
    return KBEntry(entry_id=entry_id, title="t", domain="medical-research")


def _mock_store(entry: KBEntry) -> MagicMock:
    store = MagicMock(spec=KBStore)
    store.store_entry.return_value = entry
    store.list_entries.return_value = []
    store.store_entities.return_value = {
        "entities_indexed": 1,
        "relations_discovered": 0,
    }
    store.count_entries.return_value = 5
    return store


def _cefr_config() -> Config:
    """Config with CEFR classification enabled for English items."""
    return Config(cefr=CEFRConfig(enabled=True, languages=["en"]))


def _g4_config(retries: int = 3) -> Config:
    """Config with a hard G4 gate configured for *retries* attempts."""
    return Config(
        quality_gates={
            "G4-SummaryFactual": QualityGateConfig(
                name="G4-SummaryFactual", category="hard", retries=retries
            )
        }
    )


def _run_with_patches(
    items: list[Item],
    store: MagicMock,
    config: Config,
    *extra_patches,
    translation: str = "",
    **proc_kwargs,
):
    """Run ``run_processing`` with the standard mock seam for KB + LLM."""
    patches = [
        patch("autoinfo.process.load_cached_items", return_value=items),
        # Force the config seam regardless of a local .autoinfo/config.yaml —
        # run_processing only calls load_config when get_config_path() finds a
        # file, so on CI (no gitignored config) the patch below is a no-op.
        patch("autoinfo.process.get_config_path", return_value=Path("/nonexistent/config.yaml")),
        patch("autoinfo.process.load_config", return_value=config),
        patch("autoinfo.process.KBStore", return_value=store),
        patch.object(
            LLMExtractor,
            "extract",
            side_effect=lambda item, schema=None: _extraction(  # noqa: ARG001, ARG005
                item, translation=translation
            ),
        ),
        *extra_patches,
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return run_processing("medical-research", **proc_kwargs)


class _Inflight:
    """Thread-safe in-flight counter with observed max."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.inflight = 0
        self.max_inflight = 0

    def enter(self) -> None:
        with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)

    def exit(self) -> None:
        with self._lock:
            self.inflight -= 1


def _barrier_gate(barrier: threading.Barrier, counter: _Inflight, result):
    """Gate mock body: count in-flight, wait on the barrier, return result."""

    def _gate(*args, **kwargs):  # noqa: ARG001
        counter.enter()
        try:
            barrier.wait(timeout=15)
        finally:
            counter.exit()
        return result

    return _gate


def _sleepy_gate(counter: _Inflight, result, delay: float = 0.05):
    """Gate mock body: count in-flight, sleep, return result."""

    def _gate(*args, **kwargs):  # noqa: ARG001
        counter.enter()
        try:
            time.sleep(delay)
        finally:
            counter.exit()
        return result

    return _gate


# ---------------------------------------------------------------------------
# Sub-task cap resolution
# ---------------------------------------------------------------------------


class TestResolveSubtaskCap:
    """``AUTOINFO_SUBTASK_CAP`` is parsed with a default of 4 and a floor of 1."""

    def test_default_is_4(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOINFO_SUBTASK_CAP", raising=False)
        assert _DEFAULT_SUBTASK_CAP == 4
        assert _resolve_subtask_cap() == 4

    def test_env_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOINFO_SUBTASK_CAP", "2")
        assert _resolve_subtask_cap() == 2

    def test_invalid_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_SUBTASK_CAP", "not-a-number")
        assert _resolve_subtask_cap() == _DEFAULT_SUBTASK_CAP

    def test_floor_at_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOINFO_SUBTASK_CAP", "0")
        assert _resolve_subtask_cap() == 1


# ---------------------------------------------------------------------------
# (a) Concurrent + bounded: in-flight reaches (and respects) the sub-task cap
# ---------------------------------------------------------------------------


class TestConcurrentGates:
    def test_in_flight_reaches_subtask_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four post-extraction sub-tasks (G3/G4/G5/CEFR) run concurrently.

        Each mocked gate blocks on a shared barrier of 4 — if any gate ran
        serially the barrier would time out and the run would error.  The
        observed max in-flight must reach 4 (the default sub-task cap).
        """
        barrier = threading.Barrier(4, timeout=15)
        counter = _Inflight()
        g5_scores = {
            "faithfulness": 0.9,
            "terminology": 0.9,
            "style": 0.9,
            "readability": 0.9,
            "issues": [],
        }

        mock_g3 = MagicMock()
        mock_g3.return_value.check.side_effect = _barrier_gate(
            barrier, counter, _g3_pass()
        )
        mock_g4 = MagicMock()
        mock_g4.return_value.check.side_effect = _barrier_gate(
            barrier, counter, _g4_pass()
        )
        mock_llm_judge = MagicMock(
            side_effect=_barrier_gate(barrier, counter, g5_scores)
        )
        mock_cefr = MagicMock(side_effect=_barrier_gate(barrier, counter, None))

        item = _item("par-a1-item", "First test article about IVF")
        store = _mock_store(_entry("par-a1-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.process.G3RelevanceScoring", mock_g3),
            patch("autoinfo.process.G4FactualConsistency", mock_g4),
            patch("autoinfo.process.llm_judge", mock_llm_judge),
            patch("autoinfo.process._classify_entry_cefr", mock_cefr),
            check_factual=True,
            check_translation=True,
            translation=(
                "This is the translated version of the article about IVF"
                " treatment outcomes."
            ),
        )

        assert counter.max_inflight == 4, (
            f"post-extraction gates did not run concurrently "
            f"(max in-flight = {counter.max_inflight})"
        )
        assert result.kb_entries_created == 1
        assert result.per_item_logs[0]["status"] == "ok"

    def test_subtask_cap_bounds_in_flight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lowering ``AUTOINFO_SUBTASK_CAP`` bounds concurrency to that value."""
        monkeypatch.setenv("AUTOINFO_SUBTASK_CAP", "2")
        counter = _Inflight()

        mock_g3 = MagicMock()
        mock_g3.return_value.check.side_effect = _sleepy_gate(counter, _g3_pass())
        mock_g4 = MagicMock()
        mock_g4.return_value.check.side_effect = _sleepy_gate(counter, _g4_pass())
        mock_llm_judge = MagicMock(
            side_effect=_sleepy_gate(
                counter,
                {
                    "faithfulness": 0.9,
                    "terminology": 0.9,
                    "style": 0.9,
                    "readability": 0.9,
                    "issues": [],
                },
            )
        )
        mock_cefr = MagicMock(side_effect=_sleepy_gate(counter, None))

        item = _item("par-a2-item", "First test article about IVF")
        store = _mock_store(_entry("par-a2-entry"))

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.process.G3RelevanceScoring", mock_g3),
            patch("autoinfo.process.G4FactualConsistency", mock_g4),
            patch("autoinfo.process.llm_judge", mock_llm_judge),
            patch("autoinfo.process._classify_entry_cefr", mock_cefr),
            check_factual=True,
            check_translation=True,
            translation=(
                "This is the translated version of the article about IVF"
                " treatment outcomes."
            ),
        )

        assert counter.max_inflight == 2, (
            f"sub-task cap=2 was not respected (max in-flight = "
            f"{counter.max_inflight})"
        )
        assert result.kb_entries_created == 1


# ---------------------------------------------------------------------------
# (b) Canonical G0→G5 report order regardless of completion order
# ---------------------------------------------------------------------------


class TestReportOrder:
    def test_gates_reported_in_canonical_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """quality_results keys stay G0→G5 even when gates complete out of order.

        G3's mock sleeps 0.3 s while G4/G5 return immediately — G3 finishes
        last, yet the dict passed to ``store_entry`` must list gates in
        canonical G0→G5 order.
        """
        captured: dict = {}

        def _capture_store(item, extraction, quality_results):  # noqa: ARG001
            captured["quality_results"] = quality_results
            return _entry("par-b1-entry")

        mock_quality = MagicMock(return_value=_quality_all_pass())
        mock_g3 = MagicMock()
        mock_g3.return_value.check.side_effect = _sleepy_gate(
            _Inflight(), _g3_pass(), delay=0.3
        )
        mock_g4 = MagicMock()
        mock_g4.return_value.check.side_effect = lambda *a, **k: _g4_pass()
        mock_llm_judge = MagicMock(
            return_value={
                "faithfulness": 0.9,
                "terminology": 0.9,
                "style": 0.9,
                "readability": 0.9,
                "issues": [],
            }
        )

        item = _item("par-b1-item", "First test article about IVF")
        store = _mock_store(_entry("par-b1-entry"))
        store.store_entry.side_effect = _capture_store

        result = _run_with_patches(
            [item],
            store,
            Config(),  # CEFR disabled — pure gate-order test
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.G3RelevanceScoring", mock_g3),
            patch("autoinfo.process.G4FactualConsistency", mock_g4),
            patch("autoinfo.process.llm_judge", mock_llm_judge),
            check_factual=True,
            check_translation=True,
            translation=(
                "This is the translated version of the article about IVF"
                " treatment outcomes."
            ),
        )

        assert result.kb_entries_created == 1
        assert list(captured["quality_results"].keys()) == [
            "G0-SchemaIntegrity",
            "G1-SourceAuthority",
            "G1-TosCompliance",
            "G2-Dedup",
            "G3-RelevanceScoring",
            "G4-SummaryFactual",
            "G5-TranslationAccuracy",
        ], "gate report order is not canonical G0→G5"


# ---------------------------------------------------------------------------
# (c) G4 hard-gate 3× retry: flaky LLM succeeds on the third attempt
# ---------------------------------------------------------------------------


class TestG4RetrySemantics:
    def test_flaky_g4_retries_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """G4's internal retry loop drives 3 attempts; success on attempt 3.

        The LLM call fails twice (RuntimeError) then returns a non-
        contradictory verdict.  Exactly 3 attempts must be observed and the
        item stored (no block) — proving G4's hard-gate 3× retry semantics
        survive the parallel invocation.
        """
        calls = {"n": 0}

        def flaky_llm(*args, **kwargs):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("provider boom")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"contradiction": false, '
                                '"explanation": "all good"}'
                            )
                        )
                    )
                ]
            )

        item = _item("par-c1-item", "First test article about IVF")
        store = _mock_store(_entry("par-c1-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _g4_config(retries=3),
            patch("autoinfo.quality.call_with_fallback", side_effect=flaky_llm),
            check_factual=True,
        )

        assert calls["n"] == 3, (
            f"G4 retry loop did not run 3 attempts (observed {calls['n']})"
        )
        assert result.kb_entries_created == 1  # passed → stored
        assert store.store_entry.call_count == 1
        g4 = store.store_entry.call_args.args[2]["G4-SummaryFactual"]
        assert g4.passed is True
        assert g4.details.get("retry_count") == 2

    def test_g4_always_fail_blocks_item(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """3 failed attempts → hard-gate block path preserved.

        All three attempts fail: G4 returns the ``action: block`` result,
        the item is blocked (no storage), and G4 writes its own ``_failed/``
        diagnostics (3 attempts recorded).
        """
        def always_fail(*args, **kwargs):  # noqa: ARG001
            raise RuntimeError("provider boom")

        item = _item("par-d1-item", "First test article about IVF")
        store = _mock_store(_entry("par-d1-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        with patch.object(
            G4FactualConsistency, "_write_failed_diagnostics"
        ) as mock_wfd:
            result = _run_with_patches(
                [item],
                store,
                _g4_config(retries=3),
                patch(
                    "autoinfo.quality.call_with_fallback", side_effect=always_fail
                ),
                check_factual=True,
            )

        # G4 wrote its _failed/ diagnostics after exhausting 3 attempts
        assert mock_wfd.call_count == 1
        retry_log = mock_wfd.call_args.args[2]
        assert len(retry_log) == 3, (
            f"G4 block path did not exhaust 3 attempts (retry_log={len(retry_log)})"
        )
        # Hard-gate block: storage skipped, item marked blocked and
        # unlogged (the existing g4_blocked contract: stats["logged"]=False)
        assert store.store_entry.call_count == 0
        assert result.kb_entries_created == 0
        assert result.per_item_logs == []
        assert result.errors == []
        assert "G4 blocked item par-d1-item" in caplog.text
