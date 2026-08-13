"""Tests for ``_STORAGE_LOCK`` scope (llm-concurrency todo 4).

The CEFR classification call is an LLM call (network I/O, can take seconds)
and must run OUTSIDE ``_STORAGE_LOCK`` — a worker stuck on the LLM would
otherwise stall every other worker's KB storage write.  The lock must still
serialize ALL storage writes (``store_entry`` etc.), and a CEFR failure must
not break the storage path.

Covers:

(a) lock NOT held during the CEFR classification call — probed both at the
    call site in ``_process_item`` and at the actual LLM call
    (``autoinfo.cefr.classify_text``) inside ``_classify_entry_cefr``
(b) storage writes remain serialized under concurrency — two workers on two
    items never overlap in the ``store_entry`` write section
    (barrier-synchronized start, max in-flight counter == 1)
(c) CEFR failure -> storage write still happens and the error is recorded
    per the existing error-handling contract (both at the call site and for
    a failure inside the helper, which swallows per its own contract)

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import CEFRConfig, Config
from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import _STORAGE_LOCK, run_processing

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


def _extraction(item: Item) -> ExtractionResult:
    return ExtractionResult(
        item_id=item.id,
        title=item.title,
        tl_dr="A summary.",
        key_points=["A key point"],
        entities=[{"name": "IVF", "type": "procedure"}],
        relevance_score=80.0,
    )


def _quality_all_pass():
    from autoinfo.quality import QualityResult

    return {
        "G1-SourceAuthority": QualityResult(gate_name="G1", passed=True, details={}),
        "G2-Dedup": QualityResult(
            gate_name="G2", passed=True, details={"is_duplicate": False}
        ),
        "G3-RelevanceScoring": QualityResult(
            gate_name="G3", passed=True, score=80.0, details={}
        ),
    }


def _entry(entry_id: str = "e1") -> KBEntry:
    return KBEntry(entry_id=entry_id, title="t", domain="medical-research")


def _mock_store(entry: KBEntry) -> MagicMock:
    store = MagicMock(spec=KBStore)
    store.store_entry.return_value = entry
    store.list_entries.return_value = []
    store.store_entities.return_value = {"entities_indexed": 1, "relations_discovered": 0}
    store.count_entries.return_value = 5
    return store


def _cefr_config() -> Config:
    """Config with CEFR classification enabled for English items."""
    return Config(cefr=CEFRConfig(enabled=True, languages=["en"]))


def _run_with_patches(
    items: list[Item],
    store: MagicMock,
    config: Config,
    *extra_patches,
):
    """Run ``run_processing`` with the standard mock seam for KB + LLM."""
    patches = [
        patch("autoinfo.process.load_cached_items", return_value=items),
        patch("autoinfo.process.load_config", return_value=config),
        patch("autoinfo.process.KBStore", return_value=store),
        patch.object(
            LLMExtractor,
            "extract",
            side_effect=lambda item, schema=None: _extraction(item),  # noqa: ARG005
        ),
        *extra_patches,
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return run_processing("medical-research")


# ---------------------------------------------------------------------------
# (a) Lock NOT held during the CEFR classification call
# ---------------------------------------------------------------------------


class TestCefrCallOutsideLock:
    def test_call_site_probe_lock_not_held(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CEFR call site must not hold ``_STORAGE_LOCK``.

        A mock CEFR function records ``_STORAGE_LOCK.locked()`` at entry.
        Red before the refactor (call is inside ``with _STORAGE_LOCK:`` ->
        probe sees ``True``), green after (``False``).
        """
        lock_states: list[bool] = []

        def fake_cefr(entry, item, config):  # noqa: ARG001
            lock_states.append(_STORAGE_LOCK.locked())
            return None

        item = _item("cefr-a1-item", "First test article about IVF")
        store = _mock_store(_entry("cefr-a1-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.process._classify_entry_cefr", side_effect=fake_cefr),
        )

        assert lock_states == [False], (
            f"CEFR call ran with _STORAGE_LOCK held (states={lock_states}) — "
            "the LLM call must not block other workers' storage writes"
        )
        assert result.kb_entries_created == 1

    def test_deep_probe_llm_call_outside_lock_writes_inside(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real helper: LLM call outside the lock, its writes inside.

        Probes the actual ``autoinfo.cefr.classify_text`` call (the LLM call)
        and the frontmatter write that follows it.  Before the refactor both
        see ``locked() == True`` (whole helper under the lock) — the first
        assertion is red; after the refactor the LLM call sees ``False`` and
        the storage writes still see ``True``.
        """
        llm_lock_states: list[bool] = []
        write_lock_states: list[bool] = []

        def fake_classify(text, lang, model_config):  # noqa: ARG001
            llm_lock_states.append(_STORAGE_LOCK.locked())
            return {"cefr_level": "B1", "confidence": 0.9}

        def fake_frontmatter(file_path, key, value):  # noqa: ARG001
            write_lock_states.append(_STORAGE_LOCK.locked())

        item = _item("cefr-a2-item", "First test article about IVF")
        store = _mock_store(_entry("cefr-a2-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.cefr.classify_text", side_effect=fake_classify),
            patch("autoinfo.process._update_index_cefr"),
            patch(
                "autoinfo.kb.update_frontmatter_field",
                side_effect=fake_frontmatter,
            ),
        )

        assert llm_lock_states == [False], (
            f"CEFR LLM call ran with _STORAGE_LOCK held (states={llm_lock_states})"
        )
        assert write_lock_states == [True], (
            f"CEFR storage writes lost the lock (states={write_lock_states}) — "
            "SQLite/frontmatter writes must stay serialized"
        )
        assert result.kb_entries_created == 1


# ---------------------------------------------------------------------------
# (b) Storage writes stay serialized (max in-flight == 1)
# ---------------------------------------------------------------------------


class TestStorageWritesSerialized:
    def test_max_one_write_in_flight_under_concurrency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two concurrent ``_process_item`` runs never overlap in the write.

        Both workers are barrier-synchronized at the quality gates so they
        race into ``store_entry`` simultaneously; the mocked write widens its
        window with a short sleep so a lock-less implementation would
        observably overlap (max in-flight == 2).  The lock must keep the
        maximum at exactly 1.
        """
        gate_barrier = threading.Barrier(2, timeout=15)
        counter_lock = threading.Lock()
        inflight = 0
        max_inflight = 0

        def _gates(*args, **kwargs):  # noqa: ARG001
            gate_barrier.wait(timeout=15)
            return _quality_all_pass()

        def _store_entry(item, extraction, quality_results):  # noqa: ARG001
            nonlocal inflight, max_inflight
            with counter_lock:
                inflight += 1
                max_inflight = max(max_inflight, inflight)
            time.sleep(0.05)  # widen the window; no timing assertion depends on it
            with counter_lock:
                inflight -= 1
            return _entry("cefr-b1-stored")

        item_a = _item("cefr-b1-item-a", "First test article about IVF")
        item_b = _item("cefr-b1-item-b", "Second test article about IVF")
        store = _mock_store(_entry("cefr-b1-entry"))
        store.store_entry.side_effect = _store_entry
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "2")

        result = _run_with_patches(
            [item_a, item_b],
            store,
            Config(),  # CEFR disabled — pure storage-write serialization test
            patch("autoinfo.process.run_quality_gates", side_effect=_gates),
        )

        assert max_inflight == 1, (
            f"storage writes overlapped: max in-flight writes = {max_inflight}"
        )
        assert store.store_entry.call_count == 2
        assert result.kb_entries_created == 2


# ---------------------------------------------------------------------------
# (c) CEFR failure -> storage path intact
# ---------------------------------------------------------------------------


class TestCefrFailurePath:
    def test_call_site_failure_records_error_after_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raising CEFR call must not undo the KB write, and the error is
        recorded per the ``_process_item`` contract (item status ``error`` +
        entry in ``ProcessResult.errors``).  Completes fast — no deadlock:
        the CEFR failure releases the lock so storage proceeds."""
        def _boom_cefr(entry, item, config):  # noqa: ARG001
            raise RuntimeError("cefr boom")

        item = _item("cefr-c1-item", "First test article about IVF")
        store = _mock_store(_entry("cefr-c1-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.process._classify_entry_cefr", side_effect=_boom_cefr),
        )

        assert store.store_entry.call_count == 1  # storage write still happened
        assert result.kb_entries_created == 1  # entry was created before CEFR ran
        assert result.per_item_logs[0]["status"] == "error"
        assert any("cefr boom" in str(e.get("error", "")) for e in result.errors)

    def test_llm_failure_inside_helper_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure of the actual LLM call inside ``_classify_entry_cefr`` is
        swallowed by the helper (classification must never block entry
        creation): the KB write still happened and no error propagates."""
        def _boom_classify(text, lang, model_config):  # noqa: ARG001
            raise RuntimeError("cefr llm boom")

        item = _item("cefr-c2-item", "First test article about IVF")
        store = _mock_store(_entry("cefr-c2-entry"))
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")

        result = _run_with_patches(
            [item],
            store,
            _cefr_config(),
            patch("autoinfo.cefr.classify_text", side_effect=_boom_classify),
        )

        assert store.store_entry.call_count == 1  # storage write still happened
        assert result.errors == []  # helper swallowed the LLM failure
        assert result.per_item_logs[0]["status"] == "ok"
        assert result.kb_entries_created == 1
