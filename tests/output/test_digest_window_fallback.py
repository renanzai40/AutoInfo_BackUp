"""Digest window-fallback tests (backup issue #83).

The digest's date-window query may return rows that are ALL archived /
deprecated / test / empty — the archive exclusion then drains the list to
zero and the digest renders an empty shell, even though valid active
content exists outside the window.  The fallback must fire when the
FILTERED result is empty, not only when the window query returns zero
rows — and must only recover non-archived active content.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autoinfo.output import generate_digest

_ACTIVE_TITLES = [f"Active content {i}" for i in range(10)]


def _active_entry(i: int) -> dict[str, object]:
    return {
        "entry_id": f"active-{i}",
        "title": f"Active content {i}",
        "domain": "online-education",
        "tier": "01-Raw",
        "source_url": f"https://example.com/active/{i}",
        "source_type": "rss",
        "source_platform": "coursera",
        "collected_at": "2026-08-15T00:00:00+00:00",
        "summary": f"Relevant summary {i}.",
        "quality_tier": 2,
        "relevance_score": 80.0,
        "dedup_status": "unique",
        "file_path": "",
        "tags": "[]",
        "custom_fields": '{"status": "active"}',
        "language": "en",
    }


def _archived_entry(i: int) -> dict[str, object]:
    e = _active_entry(i)
    e.update({
        "entry_id": f"archived-{i}",
        "title": f"Archived content {i}",
        "custom_fields": '{"status": "archived"}',
    })
    return e


def _mock_llm_synthesis() -> dict[str, object]:
    return {
        "executive_summary": "Weekly summary.",
        "key_findings": [{"topic": "Topic", "detail": "Detail"}],
        "trends": [],
        "recommendations": ["Read."],
    }


class TestWindowFallback:
    def _render(self, mock_kb: MagicMock) -> str:
        result = generate_digest(
            domain="online-education", period="weekly", format="markdown"
        )
        assert isinstance(result, str)
        return result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_window_all_archived_falls_back_to_full_domain(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Window returns only-archived entries; the full-domain fallback
        recovers the active content (issue #83)."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        # First call (window query): 25 archived. Second call (fallback): 10 active.
        store.list_entries.side_effect = [
            [_archived_entry(i) for i in range(25)],
            [_active_entry(i) for i in range(10)],
        ]
        mock_kb.return_value = store

        out = self._render(mock_kb)

        assert store.list_entries.call_count == 2, "fallback must re-query"
        assert "Active content 0" in out
        assert "Archived content 0" not in out

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_window_archived_and_fallback_empty_no_loop(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Both the window and the full-domain set are archived-only → no
        infinite fallback loop, neutral empty message rendered."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        store.list_entries.side_effect = [
            [_archived_entry(i) for i in range(5)],
            [_archived_entry(i) for i in range(5)],
        ]
        mock_kb.return_value = store

        out = self._render(mock_kb)

        # Fallback fired once, then stopped (no third query).
        assert store.list_entries.call_count == 2
        assert "no curated items" in out.lower() or "empty" in out.lower() \
            or "no" in out.lower()

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_window_has_good_content_no_fallback(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Window has some active content → NO fallback (good content wins)."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        window = [_archived_entry(i) for i in range(5)] + [_active_entry(i) for i in range(3)]
        store.list_entries.side_effect = [window, [_active_entry(i) for i in range(10)]]
        mock_kb.return_value = store

        out = self._render(mock_kb)

        assert store.list_entries.call_count == 1, "no fallback when content survives"
        assert "Active content 0" in out
        assert "Archived content 0" not in out

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_empty_window_fallback_still_works(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Regression lock: the pre-existing zero-row window fallback."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        store.list_entries.side_effect = [[], [_active_entry(i) for i in range(10)]]
        mock_kb.return_value = store

        out = self._render(mock_kb)

        assert store.list_entries.call_count == 2
        assert "Active content 0" in out

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_mixed_drain_triggers_fallback(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Window = archived + test/empty entries → drains to zero → fallback."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        test_entry = dict(_active_entry(99))
        test_entry.update({
            "entry_id": "test-99",
            "title": "Test Entry for pytest",
            "custom_fields": '{"status": "test"}',
        })
        window = [_archived_entry(i) for i in range(4)] + [test_entry]
        store.list_entries.side_effect = [window, [_active_entry(i) for i in range(10)]]
        mock_kb.return_value = store

        out = self._render(mock_kb)

        assert store.list_entries.call_count == 2
        assert "Active content 0" in out

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_fallback_set_all_stale_raises_stalesourceerror(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """#52 interaction: the fallback recovered content that is ALL stale
        → the staleness guard still raises StaleSourceError (the #83 fallback
        does not bypass the freshness guard)."""
        mock_llm.return_value = _mock_llm_synthesis()
        store = MagicMock()
        stale_entry = dict(_active_entry(0))
        stale_entry.update({
            "collected_at": "2026-01-10T00:00:00+00:00",  # 230+ days old → stale
        })
        store.list_entries.side_effect = [
            [_archived_entry(i) for i in range(5)],
            [stale_entry for _ in range(10)],
        ]
        mock_kb.return_value = store

        from autoinfo.output import StaleSourceError

        try:
            self._render(mock_kb)
        except StaleSourceError:
            return  # expected — stale fallback content is blocked
        raise AssertionError(
            "expected StaleSourceError when fallback content is all stale"
        )
