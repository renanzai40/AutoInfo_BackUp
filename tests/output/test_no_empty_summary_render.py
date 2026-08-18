"""Tests for issue #294: empty-summary entries must never leak into products.

The product pipeline renders entries with empty/blank summaries.
This test file covers:
- ``_is_test_entry`` drops entries with empty/placeholder summary
- ``_filter_product_entries`` excludes empty-summary entries
- ``generate_digest``/``generate_report`` never render empty summary cells
  in markdown, JSON, or agent output formats
- No ``"No content provided"`` string leaks into any rendered output

TDD: these tests should fail (RED) before the fix, pass (GREEN) after.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    DeliveryOutput,
    _filter_product_entries,
    _is_test_entry,
    generate_digest,
    generate_report,
)


def _extract_body(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)

# ---------------------------------------------------------------------------
# Sample entries
# ---------------------------------------------------------------------------

_REAL_ENTRY: dict[str, Any] = {
    "entry_id": "real-001",
    "title": "Improved IVF outcomes with time-lapse embryo imaging",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Time-lapse imaging improves live birth rates (48.2% vs 39.5%).",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 92.0,
}

_REAL_ENTRY_2: dict[str, Any] = {
    "entry_id": "real-002",
    "title": "AI-driven embryo selection: a systematic review",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=2)).isoformat(),
    "summary": "AI models show promise but lack prospective validation.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 85.0,
}

_EMPTY_SUMMARY_ENTRY: dict[str, Any] = {
    "entry_id": "empty-sum-001",
    "title": "A paper with no summary text",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/11111111/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 50.0,
}

_EMPTY_SUMMARY_WS_ENTRY: dict[str, Any] = {
    "entry_id": "empty-sum-ws-001",
    "title": "Whitespace-only summary",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/22222222/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "   \t  ",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 40.0,
}

_NO_CONTENT_PLACEHOLDER_ENTRY: dict[str, Any] = {
    "entry_id": "no-content-001",
    "title": "Empty content paper",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/33333333/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "No content provided to summarize.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 30.0,
}

_EMPTY_TITLE_AND_SUMMARY: dict[str, Any] = {
    "entry_id": "empty-both-001",
    "title": "",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/44444444/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "",
    "tags": "[]",
}

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": "IVF outcomes improve with time-lapse imaging and AI.",
    "key_findings": [
        {
            "text": "Time-lapse imaging improves live birth rates.",
            "source_url": "",
        },
    ],
    "recommendations": ["Expand access to time-lapse monitoring."],
    "trends": ["Growing adoption of AI in IVF clinics."],
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return mixed entries including empty-summary ones."""
    if domain == "empty-domain":
        return []
    return [
        _REAL_ENTRY,
        _REAL_ENTRY_2,
        _EMPTY_SUMMARY_ENTRY,
        _EMPTY_SUMMARY_WS_ENTRY,
        _NO_CONTENT_PLACEHOLDER_ENTRY,
        _EMPTY_TITLE_AND_SUMMARY,
    ]


# ---------------------------------------------------------------------------
# Test: _is_test_entry identifies empty/placeholder summaries
# ---------------------------------------------------------------------------


class TestIsTestEntryEmptySummary:
    """_is_test_entry should flag entries with empty or placeholder summaries."""

    def test_empty_summary_is_test(self) -> None:
        assert _is_test_entry(_EMPTY_SUMMARY_ENTRY) is True

    def test_whitespace_summary_is_test(self) -> None:
        assert _is_test_entry(_EMPTY_SUMMARY_WS_ENTRY) is True

    def test_no_content_placeholder_is_test(self) -> None:
        assert _is_test_entry(_NO_CONTENT_PLACEHOLDER_ENTRY) is True

    def test_empty_title_and_summary_is_test(self) -> None:
        assert _is_test_entry(_EMPTY_TITLE_AND_SUMMARY) is True

    def test_real_entry_is_not_test(self) -> None:
        assert _is_test_entry(_REAL_ENTRY) is False

    def test_real_entry_2_is_not_test(self) -> None:
        assert _is_test_entry(_REAL_ENTRY_2) is False


# ---------------------------------------------------------------------------
# Test: _filter_product_entries excludes empty-summary entries
# ---------------------------------------------------------------------------


class TestFilterProductEntriesExcludesEmptySummary:
    """_filter_product_entries should not let empty-summary entries through."""

    def test_drops_empty_summary(self) -> None:
        result = _filter_product_entries(
            [_EMPTY_SUMMARY_ENTRY, _REAL_ENTRY]
        )
        ids = [e["entry_id"] for e in result]
        assert "empty-sum-001" not in ids
        assert "real-001" in ids

    def test_drops_whitespace_summary(self) -> None:
        result = _filter_product_entries(
            [_EMPTY_SUMMARY_WS_ENTRY, _REAL_ENTRY]
        )
        ids = [e["entry_id"] for e in result]
        assert "empty-sum-ws-001" not in ids

    def test_drops_no_content_placeholder(self) -> None:
        result = _filter_product_entries(
            [_NO_CONTENT_PLACEHOLDER_ENTRY, _REAL_ENTRY]
        )
        ids = [e["entry_id"] for e in result]
        assert "no-content-001" not in ids

    def test_mixed_list_yields_only_real(self) -> None:
        mixed = [
            _REAL_ENTRY,
            _EMPTY_SUMMARY_ENTRY,
            _EMPTY_SUMMARY_WS_ENTRY,
            _NO_CONTENT_PLACEHOLDER_ENTRY,
            _EMPTY_TITLE_AND_SUMMARY,
            _REAL_ENTRY_2,
        ]
        result = _filter_product_entries(mixed)
        ids = [e["entry_id"] for e in result]
        assert ids == ["real-001", "real-002"]


# ---------------------------------------------------------------------------
# Test: generate_digest renders no empty summary in any format
# ---------------------------------------------------------------------------


class TestDigestNoEmptySummaryRender:
    """generate_digest with mixed entries must never render empty summaries."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_markdown_no_empty_summary(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Markdown digest: no blank summary cells, no empty entry shells."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        )
        body = _extract_body(result)
        # No empty-summary entry should appear
        assert "A paper with no summary text" not in body
        assert "Whitespace-only summary" not in body
        assert "Empty content paper" not in body
        # The real entries should appear
        assert "Improved IVF outcomes" in body
        assert "AI-driven embryo selection" in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_json_no_empty_summary(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """JSON digest: empty-summary entries must be excluded from entries list."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="json"
        )
        body = _extract_body(result)
        data = json.loads(body)
        entry_titles = [e.get("title") for e in data.get("entries", [])]
        assert "A paper with no summary text" not in entry_titles
        assert "Whitespace-only summary" not in entry_titles
        assert "Empty content paper" not in entry_titles
        assert "No content provided to summarize." not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_agent_no_empty_summary(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Agent (JSON-LD) digest: empty-summary entries excluded."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="agent"
        )
        body = _extract_body(result)
        data = json.loads(body)
        entry_titles = [e.get("title") for e in data.get("entries", [])]
        assert "A paper with no summary text" not in entry_titles
        assert "No content provided to summarize." not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_never_renders_no_content_provided(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """The literal string 'No content provided' must never appear."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for fmt in ("markdown", "json", "agent"):
            result = generate_digest(
                domain="medical-research", period="weekly", format=fmt
            )
            body = _extract_body(result)
            assert "No content provided" not in body, (
                f"'No content provided' leaked in format={fmt}"
            )


# ---------------------------------------------------------------------------
# Test: generate_report renders no empty summary in any format
# ---------------------------------------------------------------------------


class TestReportNoEmptySummaryRender:
    """generate_report with mixed entries must never render empty summaries."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_report_markdown_no_empty_summary(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        """Report markdown: no blank summary cells."""
        mock_synthesis.return_value = "Executive summary for the report."
        mock_extract.side_effect = (
            lambda extractor, prompt, field: (
                [
                    {
                        "theme": "General",
                        "description": "All entries",
                        "entry_ids": ["real-001"],
                    }
                ]
                if field == "groups"
                else "Executive summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [
            _REAL_ENTRY,
            _EMPTY_SUMMARY_ENTRY,
            _NO_CONTENT_PLACEHOLDER_ENTRY,
        ]
        mock_kb.return_value = mock_store

        result = generate_report(
            domain="medical-research", period="weekly", format="markdown"
        )
        body = _extract_body(result)
        assert "No content provided" not in body
        assert "A paper with no summary text" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_report_json_no_empty_summary(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        """Report JSON: empty-summary entries excluded."""
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda extractor, prompt, field: (
                [
                    {
                        "theme": "General",
                        "description": "All",
                        "entry_ids": ["real-001"],
                    }
                ]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [
            _REAL_ENTRY,
            _EMPTY_SUMMARY_ENTRY,
            _NO_CONTENT_PLACEHOLDER_ENTRY,
        ]
        mock_kb.return_value = mock_store

        result = generate_report(
            domain="medical-research", period="weekly", format="json"
        )
        body = _extract_body(result)
        data = json.loads(body)
        entry_titles = [e.get("title") for e in data.get("entries", [])]
        assert "A paper with no summary text" not in entry_titles
        assert "No content provided to summarize." not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_report_never_renders_no_content_provided(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        """Report: 'No content provided' must never appear in any format."""
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda extractor, prompt, field: (
                [
                    {
                        "theme": "General",
                        "description": "All",
                        "entry_ids": ["real-001"],
                    }
                ]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [
            _REAL_ENTRY,
            _EMPTY_SUMMARY_ENTRY,
            _NO_CONTENT_PLACEHOLDER_ENTRY,
        ]
        mock_kb.return_value = mock_store

        for fmt in ("markdown", "json"):
            result = generate_report(
                domain="medical-research", period="weekly", format=fmt
            )
            body = _extract_body(result)
            assert "No content provided" not in body, (
                f"'No content provided' leaked in format={fmt}"
            )
