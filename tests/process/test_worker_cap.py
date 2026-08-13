"""Tests for the processing worker-cap resolution (llm-concurrency todo 3).

Covers:

- ``_resolve_process_workers`` clamps ``AUTOINFO_PROCESS_WORKERS`` into
  1..``_PROCESS_WORKER_CAP`` (0 -> 1, 999 -> cap, explicit value honored,
  unset -> ``_DEFAULT_PROCESS_WORKERS``)
- ``run_processing`` dispatches items through a ``ThreadPoolExecutor`` sized
  with the resolved worker count (process.py:1236)

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import (
    _DEFAULT_PROCESS_WORKERS,
    _PROCESS_WORKER_CAP,
    _resolve_process_workers,
)


def _dummy_extraction(item: Item) -> ExtractionResult:
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
        "G2-Dedup": QualityResult(gate_name="G2", passed=True, details={"is_duplicate": False}),
        "G3-RelevanceScoring": QualityResult(gate_name="G3", passed=True, score=80.0, details={}),
    }


@pytest.fixture
def sample_items() -> list[Item]:
    """Two synthetic items for the dispatch test."""
    return [
        Item(
            id="cap-item-001",
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
            id="cap-item-002",
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


class TestResolveProcessWorkers:
    """``AUTOINFO_PROCESS_WORKERS`` env is clamped into 1.._PROCESS_WORKER_CAP."""

    def test_cap_is_16(self) -> None:
        """The cap was raised to 16 by the probe gate."""
        assert _PROCESS_WORKER_CAP == 16

    def test_clamp_zero_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """clamp(0) -> 1."""
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "0")
        assert _resolve_process_workers() == 1

    def test_clamp_over_cap_to_16(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """clamp(999) -> 16 (the raised cap, not the raw value)."""
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "999")
        assert _resolve_process_workers() == 16

    def test_env_override_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An in-range env value is honored verbatim."""
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "3")
        assert _resolve_process_workers() == 3
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "16")
        assert _resolve_process_workers() == 16

    def test_invalid_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-numeric env values fall back to the default worker count."""
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "not-a-number")
        assert _resolve_process_workers() == _DEFAULT_PROCESS_WORKERS

    def test_unset_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default worker count stays 5 when the env var is unset."""
        assert _DEFAULT_PROCESS_WORKERS == 5
        monkeypatch.delenv("AUTOINFO_PROCESS_WORKERS", raising=False)
        assert _resolve_process_workers() == 5


class TestDispatchUsesResolvedCap:
    """The ThreadPoolExecutor at process.py:1236 is sized by the resolved cap."""

    def test_thread_pool_uses_resolved_worker_count(
        self, sample_items: list[Item], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``run_processing`` dispatches through a pool with the resolved cap."""
        from autoinfo.process import run_processing

        captured: dict = {}

        class FakePool:
            def __init__(self, max_workers, thread_name_prefix=""):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, *args, **kwargs):
                fut = Future()
                fut.set_result(fn(*args, **kwargs))
                return fut

        mock_ext = MagicMock(return_value=_dummy_extraction(sample_items[0]))
        mock_quality = MagicMock(return_value=_quality_all_pass())
        mock_entry = KBEntry(entry_id="e", title="t", domain="d")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "16")
        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
            patch("autoinfo.process.ThreadPoolExecutor", FakePool),
        ):
            result = run_processing("medical-research")

        assert captured["max_workers"] == 16
        assert result.kb_entries_created == 2
        assert result.passed_gates == 2
