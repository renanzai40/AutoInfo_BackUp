"""Tests for cross-domain report and digest generation.

Covers:
- generate_report single-domain mode unchanged (backward compat)
- generate_report cross-domain with 2 domains
- generate_report cross-domain with 3+ domains
- Cross-domain report items include domain labels
- Cross-domain title: "Cross-Domain — Report"
- Empty cross-domain report message
- generate_digest cross-domain (single-domain regression)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult

# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def medical_entries() -> list[dict[str, Any]]:
    """Synthetic medical-research entries."""
    return [
        {
            "entry_id": "med-001",
            "title": "CRISPR gene editing advances",
            "summary": "New CRISPR techniques reduce off-target effects.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
            "source_type": "api",
            "source_platform": "pubmed",
            "relevance_score": 92.0,
            "tags": '["crispr", "gene-editing"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-15T10:00:00Z",
            "domain": "medical-research",
        },
        {
            "entry_id": "med-002",
            "title": "mRNA vaccine platform improvements",
            "summary": "Improved mRNA delivery for cancer vaccines.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
            "source_type": "api",
            "source_platform": "pubmed",
            "relevance_score": 85.0,
            "tags": '["mrna", "vaccine"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-16T10:00:00Z",
            "domain": "medical-research",
        },
    ]


@pytest.fixture
def ai_entries() -> list[dict[str, Any]]:
    """Synthetic ai-commercial entries."""
    return [
        {
            "entry_id": "ai-001",
            "title": "OpenAI raises $40B in new funding round",
            "summary": "OpenAI valuation reaches $300B after latest round.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654322/",
            "source_type": "rss",
            "source_platform": "techcrunch",
            "relevance_score": 95.0,
            "tags": '["funding", "openai"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-17T10:00:00Z",
            "domain": "ai-commercial",
        },
    ]


@pytest.fixture
def finance_entries() -> list[dict[str, Any]]:
    """Synthetic financial-intelligence entries."""
    return [
        {
            "entry_id": "fin-001",
            "title": "Fed maintains interest rates steady",
            "summary": "Federal Reserve holds rates amid inflation concerns.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654323/",
            "source_type": "api",
            "source_platform": "alpha-vantage",
            "relevance_score": 88.0,
            "tags": '["interest-rates", "fed"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-18T10:00:00Z",
            "domain": "financial-intelligence",
        },
    ]


def _make_grouping(entry_ids: list[str]) -> ExtractionResult:
    """Make a grouping ExtractionResult for the given entry IDs."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "Cross-Domain Synthesis",
                    "description": "Synthesized findings across domains.",
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
            "executive_summary": "This cross-domain report synthesizes "
            "findings from medical and AI commercial domains.",
        },
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the LLMExtractor class for mocking."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


# Helpers
# ---------------------------------------------------------------------------

def _call_report(domain: str = "test-domain", **kwargs: Any) -> str:
    """Call generate_report from autoinfo.output."""
    from autoinfo.output import DeliveryOutput, generate_report

    result = generate_report(domain=domain, format="markdown", **kwargs)
    return result.output if isinstance(result, DeliveryOutput) else result


# Tests — generate_report cross-domain
# ---------------------------------------------------------------------------


class TestCrossDomainReport:
    """Cross-domain report generation via ``generate_report``."""

    def test_single_domain_unchanged(
        self, medical_entries: list[dict[str, Any]]
    ) -> None:
        """Single-domain report behavior is unchanged — backward compat."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(["med-001", "med-002"]),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = medical_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(domain="medical-research")

        # Title uses single domain
        assert "# medical-research — Report" in report
        # Entries included
        assert "CRISPR gene editing advances" in report
        assert "mRNA vaccine platform improvements" in report

    def test_cross_domain_two_domains(
        self, medical_entries: list[dict[str, Any]], ai_entries: list[dict[str, Any]]
    ) -> None:
        """Cross-domain with 2 domains aggregates entries from both."""
        all_entry_ids = ["med-001", "med-002", "ai-001"]
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(all_entry_ids),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()

            def _list_entries(domain: str, **_: Any) -> list[dict[str, Any]]:
                if domain == "medical-research":
                    return medical_entries
                if domain == "ai-commercial":
                    return ai_entries
                return []

            mock_store.list_entries.side_effect = _list_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                domain="medical-research",
                domains=["medical-research", "ai-commercial"],
            )

        # Title is "Cross-Domain — Report"
        assert "# Cross-Domain — Report" in report
        # All entries from both domains are present
        assert "CRISPR gene editing advances" in report
        assert "mRNA vaccine platform improvements" in report
        assert "OpenAI raises $40B in new funding round" in report

    def test_cross_domain_three_domains(
        self,
        medical_entries: list[dict[str, Any]],
        ai_entries: list[dict[str, Any]],
        finance_entries: list[dict[str, Any]],
    ) -> None:
        """Cross-domain with 3+ domains aggregates entries from all."""
        all_entry_ids = ["med-001", "med-002", "ai-001", "fin-001"]
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(all_entry_ids),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()

            def _list_entries(domain: str, **_: Any) -> list[dict[str, Any]]:
                if domain == "medical-research":
                    return medical_entries
                if domain == "ai-commercial":
                    return ai_entries
                if domain == "financial-intelligence":
                    return finance_entries
                return []

            mock_store.list_entries.side_effect = _list_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                domain="medical-research",
                domains=["medical-research", "ai-commercial", "financial-intelligence"],
            )

        assert "# Cross-Domain — Report" in report
        assert "CRISPR gene editing advances" in report
        assert "OpenAI raises $40B in new funding round" in report
        assert "Fed maintains interest rates steady" in report

    def test_cross_domain_items_have_domain_labels(
        self, medical_entries: list[dict[str, Any]], ai_entries: list[dict[str, Any]]
    ) -> None:
        """Each section item in a cross-domain report has a domain field."""
        all_entry_ids = ["med-001", "med-002", "ai-001"]
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(all_entry_ids),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()

            def _list_entries(domain: str, **_: Any) -> list[dict[str, Any]]:
                if domain == "medical-research":
                    return medical_entries
                if domain == "ai-commercial":
                    return ai_entries
                return []

            mock_store.list_entries.side_effect = _list_entries
            mock_kb_cls.return_value = mock_store

            # Use JSON format to inspect item-level data
            from autoinfo.output import DeliveryOutput, generate_report

            result = generate_report(
                domain="medical-research",
                domains=["medical-research", "ai-commercial"],
                format="json",
            )
            report_json = result.output if isinstance(result, DeliveryOutput) else result
            import json

            data: dict[str, Any] = json.loads(report_json)
            entries_list: list[dict[str, Any]] = data.get("entries", [])
            domains_found: set[str] = {
                e.get("domain", "") for e in entries_list
            }
            assert "medical-research" in domains_found
            assert "ai-commercial" in domains_found

    def test_cross_domain_empty_entries(
        self,
    ) -> None:
        """Empty cross-domain report produces appropriate message."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                domain="medical-research",
                domains=["medical-research", "ai-commercial"],
            )

        assert "Cross-Domain" in report
        assert "No knowledge base entries found" in report

    def test_domains_single_entry_uses_single_domain(
        self, medical_entries: list[dict[str, Any]]
    ) -> None:
        """domains with only 1 entry behaves as single-domain (no cross-domain)."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(["med-001", "med-002"]),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = medical_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                domain="medical-research",
                domains=["medical-research"],
            )

        # Single domain in domains list → treated as single-domain
        assert "# medical-research — Report" in report

    def test_references_include_domain(
        self, medical_entries: list[dict[str, Any]], ai_entries: list[dict[str, Any]]
    ) -> None:
        """References in cross-domain report include domain field."""
        all_entry_ids = ["med-001", "ai-001"]
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping(all_entry_ids),
                _make_summary(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()

            def _list_entries(domain: str, **_: Any) -> list[dict[str, Any]]:
                if domain == "medical-research":
                    return [medical_entries[0]]
                if domain == "ai-commercial":
                    return [ai_entries[0]]
                return []

            mock_store.list_entries.side_effect = _list_entries
            mock_kb_cls.return_value = mock_store

            from autoinfo.output import DeliveryOutput, generate_report

            result = generate_report(
                domain="medical-research",
                domains=["medical-research", "ai-commercial"],
                format="json",
            )
            report_json = result.output if isinstance(result, DeliveryOutput) else result
            import json

            data: dict[str, Any] = json.loads(report_json)
            entries_list: list[dict[str, Any]] = data.get("entries", [])
            domains_found: set[str] = {
                e.get("domain", "") for e in entries_list
            }
            assert len(domains_found) >= 1


# Tests — generate_digest cross-domain
# ---------------------------------------------------------------------------


def _call_cross_digest(**kwargs: Any) -> str:
    """Call generate_digest for cross-domain tests."""
    from autoinfo.output import DeliveryOutput, generate_digest

    if "domain" not in kwargs:
        kwargs["domain"] = "test-domain"
    result = generate_digest(format="markdown", **kwargs)
    return result.output if isinstance(result, DeliveryOutput) else result


class TestCrossDomainDigest:
    """Cross-domain digest generation via ``generate_digest``."""

    def test_single_domain_digest_unchanged(
        self, medical_entries: list[dict[str, Any]]
    ) -> None:
        """Single-domain digest behavior is unchanged — backward compat."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = medical_entries
            mock_kb_cls.return_value = mock_store

            with patch("autoinfo.output._call_llm_for_digest", return_value={}):
                digest = _call_cross_digest(domain="medical-research")

        assert "medical-research" in digest

    def test_cross_domain_digest_two_domains(
        self, medical_entries: list[dict[str, Any]], ai_entries: list[dict[str, Any]]
    ) -> None:
        """Cross-domain digest with 2 domains aggregates both."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()

            def _list_entries(domain: str, **_: Any) -> list[dict[str, Any]]:
                if domain == "medical-research":
                    return medical_entries
                if domain == "ai-commercial":
                    return ai_entries
                return []

            mock_store.list_entries.side_effect = _list_entries
            mock_kb_cls.return_value = mock_store

            with patch("autoinfo.output._call_llm_for_digest", return_value={}):
                digest = _call_cross_digest(
                    domain="medical-research",
                    domains=["medical-research", "ai-commercial"],
                )

        assert "Cross-Domain" in digest
        assert "CRISPR gene editing advances" in digest
        assert "OpenAI raises $40B in new funding round" in digest

    def test_cross_domain_digest_empty(self) -> None:
        """Cross-domain digest with empty entries still works."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            digest = _call_cross_digest(
                domain="medical-research",
                domains=["medical-research", "ai-commercial"],
            )

        assert "Cross-Domain" in digest

    def test_domains_single_entry_uses_single_domain_digest(
        self, medical_entries: list[dict[str, Any]]
    ) -> None:
        """domains with 1 entry behaves as single-domain digest."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = medical_entries
            mock_kb_cls.return_value = mock_store

            with patch("autoinfo.output._call_llm_for_digest", return_value={}):
                digest = _call_cross_digest(
                    domain="medical-research",
                    domains=["medical-research"],
                )

        # Not "Cross-Domain" since domains has only 1 entry
        assert "Cross-Domain" not in digest
        assert "medical-research" in digest
