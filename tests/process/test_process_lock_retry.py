"""Tests for the bounded DB-lock retry around ``store_entry`` (issue #295).

Parallel ``autoinfo process`` workers write to the same SQLite DB.  Under
external-writer contention (WAL checkpoint, another process) a write can
raise ``sqlite3.OperationalError: database is locked``.  Before the fix the
item was permanently dropped for that run (only logged as a failure).

The fix adds a BOUNDED retry with a small jittered backoff around the
``store_entry`` region.  Non-lock operational errors are NOT retried — they
surface immediately through the existing error path (item logged + counted,
CLI exit code 1).  The ``except Exception`` handler semantics are unchanged.

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import sqlite3
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import Config
from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import ProcessResult, run_processing
from autoinfo.quality import QualityResult

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


def _entry(entry_id: str = "e1") -> KBEntry:
    return KBEntry(entry_id=entry_id, title="t", domain="medical-research")


def _mock_store(entry: KBEntry) -> MagicMock:
    store = MagicMock(spec=KBStore)
    store.store_entry.return_value = entry
    store.list_entries.return_value = []
    store.store_entities.return_value = {"entities_indexed": 1, "relations_discovered": 0}
    store.count_entries.return_value = 5
    return store


def _run_with_patches(
    items: list[Item],
    store: MagicMock,
    config: Config,
    *extra_patches: Any,
) -> ProcessResult:
    """Run ``run_processing`` with the standard mock seam for KB + LLM."""
    patches = [
        patch("autoinfo.process.load_cached_items", return_value=items),
        patch("autoinfo.process.get_config_path", return_value=Path("/nonexistent/config.yaml")),
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


def _no_sleep(_seconds: float) -> None:
    """Test seam: never actually sleep during pytest runs."""


# ---------------------------------------------------------------------------
# Bounded retry on "database is locked"
# ---------------------------------------------------------------------------


class TestDbLockRetry:
    def test_lock_error_retried_and_item_stored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient ``database is locked`` on the first 2 store attempts is
        retried; the third attempt succeeds and the item IS stored.

        Red before the fix: no retry exists, so the item fails and
        ``kb_entries_created`` stays 0.  Green after: the retry succeeds.
        """
        item = _item("lock-retry-item", "First test article about IVF")
        store = _mock_store(_entry("lock-retry-entry"))
        attempts = {"n": 0}

        def _flaky_store(
            item: Item,
            extraction: ExtractionResult | None,
            quality_results: dict[str, QualityResult] | None,
        ) -> KBEntry | None:  # noqa: ARG001
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise sqlite3.OperationalError("database is locked")
            return _entry("lock-retry-entry")

        store.store_entry.side_effect = _flaky_store
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")
        monkeypatch.setattr("autoinfo.process.time.sleep", _no_sleep)

        result = _run_with_patches([item], store, Config())

        assert attempts["n"] == 3, (
            f"store_entry attempted {attempts['n']} times — expected 3 "
            "(2 lock failures + 1 success)"
        )
        assert store.store_entry.call_count == 3
        assert result.kb_entries_created == 1, (
            "item was dropped despite a transient 'database is locked' — "
            "the bounded retry must store it"
        )
        assert result.errors == []
        assert result.per_item_logs[0]["status"] == "ok"

    def test_lock_error_exhausted_still_goes_through_error_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When every retry attempt hits ``database is locked``, the ORIGINAL
        error propagates to the existing ``except Exception`` handler: the
        item is logged + counted exactly as today (no semantic change)."""
        item = _item("lock-exhaust-item", "First test article about IVF")
        store = _mock_store(_entry("lock-exhaust-entry"))
        store.store_entry.side_effect = sqlite3.OperationalError("database is locked")
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")
        monkeypatch.setattr("autoinfo.process.time.sleep", _no_sleep)

        result = _run_with_patches([item], store, Config())

        assert store.store_entry.call_count == 3  # bounded: 3 attempts, no more
        assert result.kb_entries_created == 0
        assert len(result.errors) == 1
        assert "database is locked" in result.errors[0]["error"]
        assert result.per_item_logs[0]["status"] == "error"


# ---------------------------------------------------------------------------
# Non-lock errors are NOT retried (existing error path preserved)
# ---------------------------------------------------------------------------


class TestNonLockErrorNotRetried:
    def test_non_lock_error_not_retried_goes_through_error_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-lock ``OperationalError`` (e.g. ``no such table``) is NOT
        retried — it surfaces immediately through the existing error path:
        item logged as error and ``stats["errors"]`` incremented."""
        item = _item("non-lock-item", "First test article about IVF")
        store = _mock_store(_entry("non-lock-entry"))
        store.store_entry.side_effect = sqlite3.OperationalError(
            "no such table: entries"
        )
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")
        monkeypatch.setattr("autoinfo.process.time.sleep", _no_sleep)

        result = _run_with_patches([item], store, Config())

        assert store.store_entry.call_count == 1, (
            "a non-lock OperationalError must NOT be retried"
        )
        assert result.kb_entries_created == 0
        assert len(result.errors) == 1
        assert "no such table" in result.errors[0]["error"]
        assert result.per_item_logs[0]["status"] == "error"

    def test_cli_exit_code_1_when_item_errors(
        self, cli_runner: Any
    ) -> None:
        """The CLI exits 1 when any item failed processing (existing contract
        preserved — the retry must not change error reporting)."""
        from autoinfo.cli.process import app

        errored = ProcessResult(
            domain="medical-research",
            total_items=1,
            processed_count=1,
            remaining_count=0,
            is_complete=True,
            errors=[{"item_id": "non-lock-item", "error": "no such table: entries"}],
        )
        with patch("autoinfo.cli.process.run_processing", return_value=errored):
            res = cli_runner.invoke(app, ["--domain", "medical-research"])

        assert res.exit_code == 1, (
            f"CLI must exit 1 when items failed (got exit_code={res.exit_code})"
        )
