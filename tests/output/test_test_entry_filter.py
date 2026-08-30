"""Tests for issue #293: hardened _is_test_entry marker set.

Table-driven tests for each marker class: build an entry dict, assert
``_is_test_entry`` returns True for test/placeholder entries and False
for legitimate content.

End-to-end: mixed entry list rendered through generate_digest / generate_report
must never contain test/placeholder content.

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_entry(**overrides: Any) -> dict[str, Any]:
    """Build a minimal KB entry dict with sensible defaults."""
    base: dict[str, Any] = {
        "entry_id": "entry-001",
        "title": "Normal title",
        "summary": "A normal summary with real content.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "source_type": "api",
        "source_platform": "pubmed",
        "collected_at": (date.today() - timedelta(days=1)).isoformat(),
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Table-driven: entries that MUST be flagged (True)
# ---------------------------------------------------------------------------

class TestIsTestEntryTrue:
    """Each row: (description, entry) -> _is_test_entry must return True."""

    # --- URL markers ---

    def test_url_example_org(self) -> None:
        e = _mk_entry(source_url="https://example.org/placeholder")
        assert _is_test_entry(e) is True

    def test_url_localhost(self) -> None:
        e = _mk_entry(source_url="http://localhost:8080/api/data")
        assert _is_test_entry(e) is True

    def test_url_local(self) -> None:
        e = _mk_entry(source_url="http://myapp.local/api/v1")
        assert _is_test_entry(e) is True

    def test_url_127(self) -> None:
        e = _mk_entry(source_url="http://127.0.0.1:3000/test")
        assert _is_test_entry(e) is True

    # --- Title markers: exact match ---

    def test_title_get_test(self) -> None:
        e = _mk_entry(title="Get Test")
        assert _is_test_entry(e) is True

    def test_title_entry_a(self) -> None:
        e = _mk_entry(title="Entry A")
        assert _is_test_entry(e) is True

    def test_title_entry_b(self) -> None:
        e = _mk_entry(title="Entry B")
        assert _is_test_entry(e) is True

    def test_title_entry_c(self) -> None:
        e = _mk_entry(title="Entry C")
        assert _is_test_entry(e) is True

    def test_title_qa_article(self) -> None:
        e = _mk_entry(title="QA Article")
        assert _is_test_entry(e) is True

    def test_title_test_entry(self) -> None:
        e = _mk_entry(title="Test Entry")
        assert _is_test_entry(e) is True

    def test_title_standalone_test(self) -> None:
        """Just 'Test' as a title is never real content."""
        e = _mk_entry(title="Test")
        assert _is_test_entry(e) is True

    def test_title_standalone_test_lowercase(self) -> None:
        e = _mk_entry(title="test")
        assert _is_test_entry(e) is True

    # --- Title markers: regex ---

    def test_title_parity_t(self) -> None:
        e = _mk_entry(title="parity-t49-spotcheck")
        assert _is_test_entry(e) is True

    def test_title_test_date_epoch(self) -> None:
        """Date-epoch titles like 'Test 2026-08-11' are test fixtures."""
        e = _mk_entry(title="Test 2026-08-11")
        assert _is_test_entry(e) is True

    # --- Title markers: substring ---

    def test_title_validation_import(self) -> None:
        e = _mk_entry(title="Validation Import Fixture")
        assert _is_test_entry(e) is True

    def test_title_spotcheck(self) -> None:
        e = _mk_entry(title="Spotcheck Entry")
        assert _is_test_entry(e) is True

    def test_title_lorem_ipsum(self) -> None:
        e = _mk_entry(title="Lorem ipsum dolor sit amet")
        assert _is_test_entry(e) is True

    def test_title_placeholder(self) -> None:
        e = _mk_entry(title="Placeholder entry for testing")
        assert _is_test_entry(e) is True

    def test_title_test_content(self) -> None:
        e = _mk_entry(title="Test Content Here")
        assert _is_test_entry(e) is True

    # --- Summary markers: lorem ipsum ---

    def test_summary_lorem_ipsum(self) -> None:
        e = _mk_entry(summary="Lorem ipsum dolor sit amet, consectetur.")
        assert _is_test_entry(e) is True

    def test_summary_lorem_ipsum_lowercase(self) -> None:
        e = _mk_entry(summary="lorem ipsum")
        assert _is_test_entry(e) is True

    # --- Empty / placeholder summary (T2) ---

    def test_summary_empty(self) -> None:
        e = _mk_entry(summary="")
        assert _is_test_entry(e) is True

    def test_summary_whitespace(self) -> None:
        e = _mk_entry(summary="   \t  ")
        assert _is_test_entry(e) is True

    def test_summary_no_content_provided(self) -> None:
        e = _mk_entry(summary="No content provided to summarize.")
        assert _is_test_entry(e) is True

    # --- Empty title + summary ---

    def test_empty_title_and_summary(self) -> None:
        e = _mk_entry(title="", summary="")
        assert _is_test_entry(e) is True

    # --- custom_fields ---

    def test_custom_fields_test_flag(self) -> None:
        e = _mk_entry(custom_fields={"test": True})
        assert _is_test_entry(e) is True

    def test_custom_fields_status_test(self) -> None:
        e = _mk_entry(custom_fields={"status": "test"})
        assert _is_test_entry(e) is True

    def test_custom_fields_status_placeholder(self) -> None:
        e = _mk_entry(custom_fields={"status": "placeholder"})
        assert _is_test_entry(e) is True

    def test_custom_fields_status_mock(self) -> None:
        e = _mk_entry(custom_fields={"status": "mock"})
        assert _is_test_entry(e) is True

    def test_custom_fields_status_sample(self) -> None:
        e = _mk_entry(custom_fields={"status": "sample"})
        assert _is_test_entry(e) is True

    def test_custom_fields_status_demo(self) -> None:
        e = _mk_entry(custom_fields={"status": "demo"})
        assert _is_test_entry(e) is True

    # --- Source platform markers ---

    def test_platform_fixture(self) -> None:
        e = _mk_entry(source_platform="fixture")
        assert _is_test_entry(e) is True

    def test_platform_mock(self) -> None:
        e = _mk_entry(source_platform="mock")
        assert _is_test_entry(e) is True

    def test_platform_stub(self) -> None:
        e = _mk_entry(source_platform="stub")
        assert _is_test_entry(e) is True

    def test_platform_sample(self) -> None:
        e = _mk_entry(source_platform="sample")
        assert _is_test_entry(e) is True


# ---------------------------------------------------------------------------
# Table-driven: entries that must NOT be flagged (False)
# ---------------------------------------------------------------------------

class TestIsTestEntryFalse:
    """Each row: (description, entry) -> _is_test_entry must return False."""

    def test_real_medical_article(self) -> None:
        e = _mk_entry(
            title="IVF time-lapse imaging improves live birth rates",
            summary="A multicenter RCT found that time-lapse imaging "
                    "improved live birth rates from 39.5% to 48.2%.",
            source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
            source_platform="pubmed",
        )
        assert _is_test_entry(e) is False

    def test_real_ai_research(self) -> None:
        e = _mk_entry(
            title="Deep learning for embryo grading in IVF",
            summary="CNN-based model achieves 92% accuracy on embryo "
                    "quality assessment from time-lapse images.",
            source_url="https://arxiv.org/abs/2301.12345",
            source_platform="arxiv",
        )
        assert _is_test_entry(e) is False

    def test_real_news_article(self) -> None:
        e = _mk_entry(
            title="FDA approves new CRISPR-based therapy",
            summary="The FDA granted approval for the first CRISPR-based "
                    "gene therapy targeting sickle cell disease.",
            source_url="https://www.reuters.com/health/fda-crispr-2026",
            source_platform="reuters",
        )
        assert _is_test_entry(e) is False

    def test_title_containing_test_results(self) -> None:
        """'Test results show...' is legitimate content, not a test entry."""
        e = _mk_entry(
            title="Test results show promising outcomes for new drug",
            summary="Phase III trial results demonstrate significant "
                    "improvement in patient outcomes.",
        )
        assert _is_test_entry(e) is False

    def test_url_example_com(self) -> None:
        """example.com is an RFC 2606 reserved domain used by real fixtures
        (relaxed in 9b0bf13) — must NOT be flagged as a test entry."""
        e = _mk_entry(source_url="https://example.com/test-article")
        assert _is_test_entry(e) is False

    def test_platform_test(self) -> None:
        """source_platform 'test' is used by many real fixtures (relaxed in
        9b0bf13) — must NOT be flagged as a test entry."""
        e = _mk_entry(source_platform="test")
        assert _is_test_entry(e) is False

    def test_platform_demo(self) -> None:
        """source_platform 'demo' is a demo-domain value (relaxed in 9b0bf13)
        — must NOT be flagged as a test entry."""
        e = _mk_entry(source_platform="demo")
        assert _is_test_entry(e) is False

    def test_title_containing_sample_size(self) -> None:
        """'Sample size' is legitimate methodology language."""
        e = _mk_entry(
            title="Large sample size study of IVF outcomes",
            summary="This study analyzed 50,000 IVF cycles across "
                    "120 clinics in the US.",
        )
        assert _is_test_entry(e) is False

    def test_title_containing_validation(self) -> None:
        """'Validation of a new test' is legitimate research."""
        e = _mk_entry(
            title="Validation of a novel PGT-A assay",
            summary="New assay shows 99.1% concordance with traditional "
                    "NGS-based PGT-A.",
        )
        assert _is_test_entry(e) is False

    def test_title_containing_demo_of_feature(self) -> None:
        """'Demo of new feature' could be a real product review."""
        e = _mk_entry(
            title="Demo of new AI embryo selection feature",
            summary="The new AI feature in EmbryoScope+ shows promising "
                    "results in preliminary testing.",
        )
        assert _is_test_entry(e) is False

    def test_real_pubmed_source(self) -> None:
        e = _mk_entry(
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=42522050",
            source_platform="pubmed",
        )
        assert _is_test_entry(e) is False

    def test_real_ncbi_source(self) -> None:
        e = _mk_entry(
            source_url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/",
            source_platform="pubmed",
        )
        assert _is_test_entry(e) is False

    def test_real_reuters_source(self) -> None:
        e = _mk_entry(
            source_url="https://www.reuters.com/business/healthcare-pharmaceuticals",
            source_platform="reuters",
        )
        assert _is_test_entry(e) is False


# ---------------------------------------------------------------------------
# _filter_product_entries: mixed list yields only real entries
# ---------------------------------------------------------------------------


class TestFilterProductEntriesHardened:
    """_filter_product_entries drops all marker classes from a mixed list."""

    def test_mixed_list_yields_only_real(self) -> None:
        real1 = _mk_entry(
            entry_id="real-001",
            title="IVF breakthrough with AI",
            summary="AI improves IVF outcomes by 15%.",
            source_url="https://pubmed.ncbi.nlm.nih.gov/11111/",
        )
        real2 = _mk_entry(
            entry_id="real-002",
            title="CRISPR gene editing advances",
            summary="New CRISPR technique corrects 89% of mutations.",
            source_url="https://pubmed.ncbi.nlm.nih.gov/22222/",
        )
        test_entries = [
            _mk_entry(entry_id="t1", source_url="https://example.org/test"),
            _mk_entry(entry_id="t2", title="Lorem ipsum dolor"),
            _mk_entry(entry_id="t3", title="Get Test"),
            _mk_entry(entry_id="t4", title="Test"),
            _mk_entry(entry_id="t5", title="parity-t49-spotcheck"),
            _mk_entry(entry_id="t6", title="Test 2026-08-11"),
            _mk_entry(entry_id="t7", source_url="http://localhost:8080"),
            _mk_entry(entry_id="t8", source_url="http://127.0.0.1:3000"),
            _mk_entry(entry_id="t9", source_url="http://myapp.local/api"),
            _mk_entry(entry_id="t10", source_platform="sample"),
            _mk_entry(entry_id="t11", source_platform="fixture"),
            _mk_entry(entry_id="t12", custom_fields={"status": "placeholder"}),
            _mk_entry(entry_id="t13", summary="Lorem ipsum content here"),
        ]
        mixed = [real1] + test_entries + [real2]
        result = _filter_product_entries(mixed)
        ids = [e["entry_id"] for e in result]
        assert ids == ["real-001", "real-002"]


# ---------------------------------------------------------------------------
# End-to-end: generate_digest / generate_report never render test content
# ---------------------------------------------------------------------------


_REAL_ENTRY: dict[str, Any] = {
    "entry_id": "real-001",
    "title": "IVF time-lapse imaging improves live birth rates",
    "language": "en",
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
    "language": "en",
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

_EXAMPLE_COM_ENTRY: dict[str, Any] = {
    "entry_id": "test-url-001",
    "title": "Test Entry from Example Domain",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://example.com/test-article",
    "source_type": "web",
    "source_platform": "web",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "This is a test entry from the example domain.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 50.0,
}

_LOREM_IPSUM_ENTRY: dict[str, Any] = {
    "entry_id": "lorem-001",
    "title": "Lorem ipsum placeholder article",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/99999999/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 40.0,
}

_SAMPLE_PLATFORM_ENTRY: dict[str, Any] = {
    "entry_id": "sample-001",
    "title": "Sample test entry from mock platform",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/88888888/",
    "source_type": "api",
    "source_platform": "sample",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "This is a sample entry for testing purposes.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 30.0,
}

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": "IVF outcomes improve with time-lapse imaging and AI.",
    "key_findings": [
        {"text": "Time-lapse imaging improves live birth rates.", "source_url": ""},
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
    """Return mixed entries including test/placeholder ones."""
    if domain == "empty-domain":
        return []
    return [
        _REAL_ENTRY,
        _REAL_ENTRY_2,
        _EXAMPLE_COM_ENTRY,
        _LOREM_IPSUM_ENTRY,
        _SAMPLE_PLATFORM_ENTRY,
    ]


def _extract_body(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


class TestEndToEndNoTestContent:
    """generate_digest / generate_report must never render test content."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_md_no_example_com(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        body = _extract_body(generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "example.com" not in body
        assert "Test Entry from Example Domain" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_md_no_lorem_ipsum(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        body = _extract_body(generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "Lorem ipsum" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_md_no_sample_platform(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        body = _extract_body(generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "Sample test entry from mock platform" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_json_no_test_entries(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        body = _extract_body(generate_digest(
            domain="medical-research", period="weekly", format="json"
        ))
        data = json.loads(body)
        entry_titles = [e.get("title", "") for e in data.get("entries", [])]
        assert "Test Entry from Example Domain" not in entry_titles
        assert "Lorem ipsum placeholder article" not in entry_titles
        assert "Sample test entry from mock platform" not in entry_titles

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_real_entries_present(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        body = _extract_body(generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "IVF time-lapse imaging improves live birth rates" in body
        assert "AI-driven embryo selection" in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_report_md_no_test_entries(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda ext, prompt, field: (
                [{"theme": "General", "description": "All", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [
            _REAL_ENTRY,
            _EXAMPLE_COM_ENTRY,
            _LOREM_IPSUM_ENTRY,
            _SAMPLE_PLATFORM_ENTRY,
        ]
        mock_kb.return_value = mock_store

        body = _extract_body(generate_report(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "example.com" not in body
        assert "Lorem ipsum" not in body
        assert "Sample test entry" not in body
        assert "IVF time-lapse" in body
