"""Tests for FTS5 + LLM Q&A on collected content.

Covers:
    - ``query_collected`` returns answer with source citations
    - Empty results when no matching content exists
    - Explicit ``content_ids`` limits the context to specific entries
    - Independent queries do not share state (no conversation persistence)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.qa import query_collected
from autoinfo.kb import KBStore
from autoinfo.models import Item


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def kb_store(tmp_path: Path) -> KBStore:
    """Create a KBStore backed by a temporary directory.

    The store's base path is ``tmp_path / "knowledge"``, and its SQLite
    database lives at ``tmp_path / "autoinfo.db"``.
    """
    base = tmp_path / "knowledge"
    base.mkdir(parents=True, exist_ok=True)
    return KBStore(base_path=base)


@pytest.fixture
def seed_entries(kb_store: KBStore) -> dict[str, str]:
    """Populate the KBStore with a few realistic-looking entries.

    Returns a mapping of ``entry_id -> title`` for later assertions.
    """
    items = [
        Item(
            id="seed-001",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/1",
            title="Improved IVF outcomes with time-lapse embryo imaging",
            content=(
                "Time-lapse embryo imaging has been proposed as a non-invasive "
                "method to improve embryo selection in IVF cycles. We conducted "
                "a multicenter randomized controlled trial involving 1,200 "
                "patients. The live birth rate was significantly higher in the "
                "time-lapse group (48.2% vs. 39.5%, p=0.006). Time-lapse embryo "
                "imaging significantly improves live birth rates compared to "
                "standard morphological assessment."
            ),
            collected_at="2026-07-15T10:30:00Z",
            domain="medical-research",
            topic_tags=["IVF", "embryo imaging"],
        ),
        Item(
            id="seed-002",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/2",
            title="AI-powered embryo selection using deep learning",
            content=(
                "Deep learning models can predict embryo viability with 89% "
                "accuracy. We trained a convolutional neural network on 10,000 "
                "time-lapse images of embryos. The model outperformed traditional "
                "morphological assessment in predicting blastocyst formation. "
                "This approach could significantly improve IVF success rates "
                "by selecting the most viable embryos for transfer."
            ),
            collected_at="2026-07-14T10:30:00Z",
            domain="medical-research",
            topic_tags=["AI", "embryo", "deep learning"],
        ),
        Item(
            id="seed-003",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/3",
            title="LLM market trends and investment in 2026",
            content=(
                "Large language models continue to dominate AI investment "
                "in 2026. Venture capital funding for LLM startups reached "
                "$15 billion in Q1 alone. Major technology companies are "
                "investing heavily in foundation model development and "
                "deployment infrastructure."
            ),
            collected_at="2026-07-13T10:30:00Z",
            domain="ai-commercial",
            topic_tags=["LLM", "market", "AI"],
        ),
    ]

    entry_ids: dict[str, str] = {}
    for item in items:
        entry = kb_store.store_entry(item)
        entry_ids[entry.entry_id] = entry.title

    return entry_ids


# ===================================================================
# Mock helpers
# ===================================================================


_LLM_ANSWER_IVF = (
    "Based on the provided articles, here are the key findings about IVF "
    "and embryo research:\n\n"
    "[1] Time-lapse embryo imaging significantly improves live birth rates "
    "(48.2% vs 39.5%) in a large randomized controlled trial with 1,200 "
    "patients.\n\n"
    "[2] AI-powered deep learning models can predict embryo viability with "
    "89% accuracy, outperforming traditional morphological assessment."
)


@pytest.fixture
def mock_litellm() -> MagicMock:
    """Return a mock ``litellm`` whose completion returns a canned answer."""
    m = MagicMock()
    m.completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=_LLM_ANSWER_IVF))]
    )
    return m


# ===================================================================
# Tests
# ===================================================================


class TestQueryCollected:
    """``query_collected()`` — happy path and edge cases."""

    # ------------------------------------------------------------------
    # Answer with citations
    # ------------------------------------------------------------------

    @patch("autoinfo.qa.call_with_fallback")
    def test_answer_with_citations(
        self,
        mock_get_litellm: MagicMock,
        mock_litellm: MagicMock,
        kb_store: KBStore,
        seed_entries: dict[str, str],
    ) -> None:
        """FTS5 search yields entries; LLM returns a cited answer."""
        mock_get_litellm.return_value = mock_litellm.completion.return_value

        result = query_collected(
            query="embryo IVF time-lapse",
            domain="medical-research",
            store=kb_store,
        )

        # Answer is the canned LLM output
        assert "IVF" in result["answer"]
        assert "[1]" in result["answer"]
        assert "[2]" in result["answer"]

        # Sources are populated
        assert len(result["sources"]) >= 1
        for src in result["sources"]:
            assert "entry_id" in src
            assert "title" in src

        # Verify the LLM was called with the expected prompt shape
        call_args = mock_get_litellm.call_args
        assert call_args is not None
        messages = call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "embryo" in messages[1]["content"]

    # ------------------------------------------------------------------
    # Empty results
    # ------------------------------------------------------------------

    @patch("autoinfo.qa.call_with_fallback")
    def test_empty_results(
        self,
        mock_get_litellm: MagicMock,
        mock_litellm: MagicMock,
        kb_store: KBStore,
        seed_entries: dict[str, str],
    ) -> None:
        """No matching entries → graceful empty response, no LLM call."""
        mock_get_litellm.return_value = mock_litellm.completion.return_value

        result = query_collected(
            query="xyznonexistent12345",
            domain="medical-research",
            store=kb_store,
        )

        assert result["answer"]
        assert "No relevant articles found" in result["answer"]
        assert result["sources"] == []

        # LLM should NOT be called when there are no sources
        mock_get_litellm.assert_not_called()

    # ------------------------------------------------------------------
    # Explicit content_ids
    # ------------------------------------------------------------------

    @patch("autoinfo.qa.call_with_fallback")
    def test_explicit_content_ids(
        self,
        mock_get_litellm: MagicMock,
        mock_litellm: MagicMock,
        kb_store: KBStore,
        seed_entries: dict[str, str],
    ) -> None:
        """When content_ids is provided, only those entries are used."""
        mock_get_litellm.return_value = mock_litellm.completion.return_value

        # Pick two specific entry IDs
        entry_ids = list(seed_entries.keys())
        selected = entry_ids[:2]

        result = query_collected(
            query="Tell me about embryo research",
            domain="medical-research",
            content_ids=selected,
            store=kb_store,
        )

        # Only the selected entries appear in sources
        assert len(result["sources"]) == 2
        source_ids = {s["entry_id"] for s in result["sources"]}
        assert source_ids == set(selected)

        # The third entry should NOT be in sources
        assert entry_ids[2] not in source_ids

    # ------------------------------------------------------------------
    # Independent queries
    # ------------------------------------------------------------------

    @patch("autoinfo.qa.call_with_fallback")
    def test_independent_queries(
        self,
        mock_get_litellm: MagicMock,
        mock_litellm: MagicMock,
        kb_store: KBStore,
        seed_entries: dict[str, str],
    ) -> None:
        """Each call is stateless — second query ignores first."""
        mock_get_litellm.return_value = mock_litellm.completion.return_value

        # First query
        result1 = query_collected(
            query="embryo IVF",
            domain="medical-research",
            store=kb_store,
        )
        assert result1["answer"]

        # Second query — same question, new call
        result2 = query_collected(
            query="embryo IVF",
            domain="medical-research",
            store=kb_store,
        )
        assert result2["answer"]

        # Verify LLM was called twice with full conversation each time
        assert mock_get_litellm.call_count == 2

        # Each call should contain the full article context (not just
        # a continuation).  Check that both messages include the
        # article content.
        for call_args in mock_get_litellm.call_args_list:
            messages = call_args[1]["messages"]
            user_msg = messages[1]["content"]
            assert "Question: embryo IVF" in user_msg
            assert "time-lapse" in user_msg

    # ------------------------------------------------------------------
    # content_ids with non-existent IDs
    # ------------------------------------------------------------------

    @patch("autoinfo.qa.call_with_fallback")
    def test_content_ids_unknown(
        self,
        mock_get_litellm: MagicMock,
        mock_litellm: MagicMock,
        kb_store: KBStore,
    ) -> None:
        """content_ids that don't exist → empty sources."""
        mock_get_litellm.return_value = mock_litellm.completion.return_value

        result = query_collected(
            query="anything",
            domain="medical-research",
            content_ids=["nonexistent-001", "nonexistent-002"],
            store=kb_store,
        )

        assert "No relevant articles found" in result["answer"]
        assert result["sources"] == []
        mock_get_litellm.assert_not_called()
