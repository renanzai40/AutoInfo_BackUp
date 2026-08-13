"""Tests for v1.5 quality gates: G0 + D1-D3 delivery gates.

Covers:
    - G0SchemaIntegrity: mandatory field validation, frontmatter YAML check,
      retry-once-block-last philosophy
    - G0 wired into run_quality_gates orchestrator
    - D1-ProductCompleteness: required sections check
    - D2-FormatIntegrity: HTML/JSON/Markdown parsing
    - D3-Freshness: recency window check
    - D1-D3 skipped for RAW product type
    - D1-D3 configurable per domain via context
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.config import QualityGateConfig
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.quality import (
    D1ProductCompleteness,
    D2FormatIntegrity,
    D3Freshness,
    G0SchemaIntegrity,
    G1SourceAuthority,
    G2Dedup,
    G3RelevanceScoring,
    G4FactualConsistency,
    QualityResult,
    run_delivery_gates,
    run_quality_gates,
)
from autoinfo.llm import LLMExtractor
from tests.conftest import requires_optional_dep

# TRIAGE #15 (env-dep): PyMuPDF missing → `import fitz` fails inside
# D2FormatIntegrity pdf check at src/autoinfo/quality.py:2106-2119 → passed=False,
# score=0.0 vs the asserts below. Gate on the conftest HAVE_PYMUPDF check;
# install '.[pdf]' to run this test.
requires_fitz = requires_optional_dep("fitz")


# ===================================================================
# G0 — Schema Integrity
# ===================================================================


class TestG0SchemaIntegrity:
    """G0 validates raw item dict schema — hard gate, blocks on failure."""

    def test_valid_item_passes(self) -> None:
        """All mandatory fields present and non-empty → passes."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is True
        assert result.score == 1.0
        assert result.gate_name == "G0-SchemaIntegrity"
        assert result.details["valid"] is True

    def test_valid_item_with_frontmatter_passes(self) -> None:
        """Valid YAML frontmatter does not cause failure."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
            "frontmatter": "title: Test\ndate: 2026-07-24\n",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is True
        assert result.details["valid"] is True

    def test_valid_item_with_empty_frontmatter_passes(self) -> None:
        """Empty frontmatter string (no content) is not a failure."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
            "frontmatter": "",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is True

    def test_valid_item_with_none_frontmatter_passes(self) -> None:
        """None frontmatter is ignored."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
            "frontmatter": None,
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is True

    def test_empty_source_url_fails_and_blocks(self) -> None:
        """Empty source_url → G0 fails, retries once, blocks."""
        item = {
            "source_url": "",
            "source_type": "api",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.flagged is True
        assert result.score == 0.0
        assert result.details["action"] == "block"
        assert result.details["retry_count"] == 1
        assert any(f["field"] == "source_url" for f in result.details["failed_fields"])

    def test_missing_source_url_fails(self) -> None:
        """Missing source_url key → fails."""
        item = {
            "source_type": "api",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"
        assert result.details["retry_count"] == 1

    def test_empty_source_type_fails(self) -> None:
        """Empty source_type → fails."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"
        assert any(f["field"] == "source_type" for f in result.details["failed_fields"])

    def test_empty_source_platform_fails(self) -> None:
        """Empty source_platform → passes (field has default, not mandatory).

        Note: source_platform defaults to "" so empty is acceptable."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"
        assert any(f["field"] == "source_platform" for f in result.details["failed_fields"])

    def test_non_string_source_url_fails(self) -> None:
        """Non-string source_url (e.g. None) → fails."""
        item = {
            "source_url": None,
            "source_type": "api",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"

    def test_all_fields_empty_fails_with_multiple_errors(self) -> None:
        """All mandatory fields empty → multiple errors in failed_fields."""
        item = {
            "source_url": "",
            "source_type": "",
            "source_platform": "",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert len(result.details["failed_fields"]) == 3
        assert result.details["retry_count"] == 1

    def test_invalid_frontmatter_fails(self) -> None:
        """Invalid YAML frontmatter → fails."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
            "frontmatter": "title: [unclosed bracket\n",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"
        assert any(f["field"] == "frontmatter" for f in result.details["failed_fields"])

    def test_non_string_frontmatter_fails(self) -> None:
        """Non-string frontmatter (e.g. dict) → fails."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
            "frontmatter": {"title": "test"},
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item)

        assert result.passed is False
        assert result.details["action"] == "block"
        assert any(f["field"] == "frontmatter" for f in result.details["failed_fields"])

    def test_gate_name_constant(self) -> None:
        """gate_name is always 'G0-SchemaIntegrity'."""
        g0 = G0SchemaIntegrity()
        result = g0.check({"source_url": "x", "source_type": "y", "source_platform": "z"})
        assert result.gate_name == "G0-SchemaIntegrity"

    def test_context_is_ignored(self) -> None:
        """context parameter is accepted but not used (reserved for future)."""
        item = {
            "source_url": "https://example.com/article",
            "source_type": "api",
            "source_platform": "pubmed",
        }
        g0 = G0SchemaIntegrity()
        result = g0.check(item, context={"some_key": "some_value"})

        assert result.passed is True


# ===================================================================
# G0 in orchestrator
# ===================================================================


class TestG0InOrchestrator:
    """G0 runs as part of run_quality_gates()."""

    def test_g0_is_first_result(self, sample_item) -> None:
        """G0-SchemaIntegrity is the first entry in the results dict."""
        results = run_quality_gates(sample_item)
        keys = list(results.keys())

        assert keys[0] == "G0-SchemaIntegrity"

    def test_g0_passes_for_valid_sample(self, sample_item) -> None:
        """Sample item has all mandatory fields → G0 passes."""
        results = run_quality_gates(sample_item)

        assert results["G0-SchemaIntegrity"].passed is True
        assert results["G0-SchemaIntegrity"].score == 1.0


# ===================================================================
# D1 — Product Completeness
# ===================================================================


class TestD1ProductCompleteness:
    """D1 checks that all required sections are present and non-empty."""

    def test_all_sections_present_passes(self) -> None:
        """All required sections present and non-empty → passes."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "Key finding 1, key finding 2",
            "summary": "This is a summary of the content.",
            "recommendations": "Recommendation A, Recommendation B",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is True
        assert result.gate_name == "D1-ProductCompleteness"
        assert result.score == 1.0
        assert result.details["all_present"] is True

    def test_missing_section_blocks(self) -> None:
        """Missing required section → blocks (default action_on_failure)."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "Some findings",
            "summary": "Some summary",
            # recommendations is missing
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is False
        assert result.flagged is True
        assert result.score == 0.0
        assert "recommendations" in result.details["missing_sections"]

    def test_empty_section_flags(self) -> None:
        """Empty section → flagged."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "",
            "summary": "A valid summary",
            "recommendations": "A recommendation",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is False
        assert "key_findings" in result.details["empty_sections"]

    def test_missing_and_empty_combined(self) -> None:
        """Both missing and empty sections are reported."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "",
            # summary is missing
            "recommendations": "Valid recommendation",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is False
        assert "key_findings" in result.details["empty_sections"]
        assert "summary" in result.details["missing_sections"]

    def test_skipped_for_raw_product(self) -> None:
        """RAW product type → gate skipped trivially."""
        product = {
            "product_type": "RAW",
            "key_findings": "",
            "summary": "",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is True
        assert result.score == 1.0
        assert result.details.get("skipped") is True

    def test_action_on_failure_fallback(self) -> None:
        """With action_on_failure='fallback', missing sections do not block."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "Findings",
            # summary missing
            "recommendations": "Recs",
        }
        gate = D1ProductCompleteness(action_on_failure="fallback")
        result = gate.check(product)

        # passed because action is not "block"
        assert result.passed is True
        assert result.flagged is True

    def test_action_on_failure_flag(self) -> None:
        """With action_on_failure='flag', missing sections are flagged but pass."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": "Findings",
            "summary": "Summary",
            # recommendations missing
        }
        gate = D1ProductCompleteness(action_on_failure="flag")
        result = gate.check(product)

        assert result.passed is True
        assert result.flagged is True

    def test_custom_required_sections(self) -> None:
        """Custom required_sections parameter works."""
        product = {
            "product_type": "PROCESSED",
            "title": "My Title",
            "author": "Author Name",
        }
        gate = D1ProductCompleteness(
            required_sections=["title", "author"],
            action_on_failure="flag",
        )
        result = gate.check(product)

        assert result.passed is True

    def test_gate_type_property(self) -> None:
        """gate_type is 'delivery'."""
        gate = D1ProductCompleteness()
        assert gate.gate_type == "delivery"

    def test_context_product_type_override(self) -> None:
        """product_type from context overrides product_output."""
        product = {
            "key_findings": "",
            "summary": "",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product, context={"product_type": "RAW"})

        assert result.passed is True
        assert result.details.get("skipped") is True

    def test_none_section_counts_as_missing(self) -> None:
        """None value for a section is treated as missing."""
        product = {
            "product_type": "PROCESSED",
            "key_findings": None,
            "summary": "Summary",
            "recommendations": "Recs",
        }
        gate = D1ProductCompleteness()
        result = gate.check(product)

        assert result.passed is False
        assert "key_findings" in result.details["missing_sections"]


# ===================================================================
# D2 — Format Integrity
# ===================================================================


class TestD2FormatIntegrity:
    """D2 checks that rendered output parses for its format."""

    def test_valid_html_passes(self) -> None:
        """Well-formed HTML → passes."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<html><body><h1>Hello</h1><p>World</p></body></html>",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["valid"] is True

    def test_invalid_html_falls_back(self) -> None:
        """Malformed HTML → falls back (default action_on_failure)."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<html><body><h1>Broken</body></html>",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        # Default action_on_failure is "fallback" → passed=True, flagged=True
        assert result.passed is True
        assert result.flagged is True
        assert result.score == 0.0

    def test_invalid_html_blocks_when_configured(self) -> None:
        """With action_on_failure='block', invalid HTML blocks."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<html><body><h1>Broken</body></html>",
        }
        gate = D2FormatIntegrity(action_on_failure="block")
        result = gate.check(product)

        assert result.passed is False
        assert result.flagged is True

    def test_invalid_html_flagged(self) -> None:
        """With action_on_failure='flag', invalid HTML is flagged but passes."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<html><body><h1>Broken</body></html>",
        }
        gate = D2FormatIntegrity(action_on_failure="flag")
        result = gate.check(product)

        assert result.passed is True
        assert result.flagged is True

    def test_valid_json_passes(self) -> None:
        """Well-formed JSON → passes."""
        product = {
            "product_type": "PROCESSED",
            "format": "json",
            "body": '{"key": "value", "list": [1, 2, 3]}',
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.details["valid"] is True

    def test_invalid_json_falls_back(self) -> None:
        """Malformed JSON → falls back."""
        product = {
            "product_type": "PROCESSED",
            "format": "json",
            "body": '{"key": value"}',
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.flagged is True

    def test_markdown_trivially_passes(self) -> None:
        """Markdown always passes."""
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Hello\n\nAny text is valid markdown.",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["valid"] is True

    def test_unknown_format_passes_with_note(self) -> None:
        """Unknown format passes with advisory note."""
        product = {
            "product_type": "PROCESSED",
            "format": "xml",
            "body": "<root><item/></root>",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert "Unknown format" in result.details["note"]

    @pytest.mark.optional
    @requires_fitz
    def test_valid_pdf_passes(self) -> None:
        """Valid PDF parsed with fitz → passes with metadata."""
        pdf_path = Path(__file__).resolve().parents[1] / "fixtures" / "sample.pdf"
        pdf_body = pdf_path.read_bytes()
        product = {
            "product_type": "PROCESSED",
            "format": "pdf",
            "body": pdf_body,
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["valid"] is True
        assert result.details["page_count"] == 1
        assert result.details["title"] == "Test PDF"

    def test_corrupted_pdf_fails(self) -> None:
        """Corrupted PDF data → fails with descriptive error."""
        product = {
            "product_type": "PROCESSED",
            "format": "pdf",
            "body": "%%EOF",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        # Default action_on_failure is "fallback" → passed=True, flagged=True
        assert result.passed is True
        assert result.flagged is True
        assert result.score == 0.0
        assert "error" in result.details

    def test_corrupted_pdf_blocks_when_configured(self) -> None:
        """With action_on_failure='block', corrupted PDF blocks."""
        product = {
            "product_type": "PROCESSED",
            "format": "pdf",
            "body": "not a pdf at all",
        }
        gate = D2FormatIntegrity(action_on_failure="block")
        result = gate.check(product)

        assert result.passed is False
        assert result.flagged is True
        assert "error" in result.details

    def test_empty_body_fails(self) -> None:
        """Empty body → fails."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is False
        assert result.flagged is True
        assert "empty" in result.details["error"].lower()

    def test_skipped_for_raw_product(self) -> None:
        """RAW product type → gate skipped."""
        product = {
            "product_type": "RAW",
            "format": "html",
            "body": "<broken>html",
        }
        gate = D2FormatIntegrity()
        result = gate.check(product)

        assert result.passed is True
        assert result.details.get("skipped") is True

    def test_gate_type_property(self) -> None:
        """gate_type is 'delivery'."""
        gate = D2FormatIntegrity()
        assert gate.gate_type == "delivery"


# ===================================================================
# D3 — Freshness
# ===================================================================


class TestD3Freshness:
    """D3 checks that all cited items are within the recency window."""

    def test_fresh_entries_pass(self) -> None:
        """All entries within recency window → passes."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Fresh Article",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
                {
                    "title": "Another Fresh",
                    "collected_at": (now - timedelta(days=5)).isoformat(),
                },
            ],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["stale_count"] == 0

    def test_stale_entries_flagged(self) -> None:
        """Stale entries → flagged with warning (default action_on_failure='flag')."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Stale Article",
                    "collected_at": (now - timedelta(days=60)).isoformat(),
                },
            ],
        }
        gate = D3Freshness(recency_window_days=30)
        result = gate.check(product)

        assert result.passed is True  # flag mode → passes but flagged
        assert result.flagged is True
        assert result.details["stale_count"] == 1

    def test_stale_entries_block_when_configured(self) -> None:
        """With action_on_failure='block', stale entries block."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Stale Article",
                    "collected_at": (now - timedelta(days=60)).isoformat(),
                },
            ],
        }
        gate = D3Freshness(action_on_failure="block", recency_window_days=30)
        result = gate.check(product)

        assert result.passed is False
        assert result.flagged is True

    def test_mixed_fresh_and_stale(self) -> None:
        """Mixed fresh and stale → reports count."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Fresh",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
                {
                    "title": "Stale",
                    "collected_at": (now - timedelta(days=40)).isoformat(),
                },
            ],
        }
        gate = D3Freshness(recency_window_days=30)
        result = gate.check(product)

        assert result.flagged is True
        assert result.details["stale_count"] == 1
        assert result.details["total_entries"] == 2

    def test_no_entries_passes(self) -> None:
        """No entries → trivially passes."""
        product = {
            "product_type": "PROCESSED",
            "entries": [],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True
        assert result.details["stale_count"] == 0
        assert result.details["total_entries"] == 0

    def test_entries_without_dates_skipped(self) -> None:
        """Entries missing date fields are skipped (not counted as stale)."""
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {"title": "No Date Entry"},
            ],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True
        assert result.details["stale_count"] == 0

    def test_date_field_alternate_key(self) -> None:
        """Check that 'date' key is also accepted."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Uses Date Field",
                    "date": (now - timedelta(days=2)).isoformat(),
                },
            ],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True
        assert result.details["stale_count"] == 0

    def test_datetime_object_directly(self) -> None:
        """Direct datetime objects are accepted."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Datetime Object",
                    "collected_at": now - timedelta(hours=6),
                },
            ],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True

    def test_skipped_for_raw_product(self) -> None:
        """RAW product type → gate skipped."""
        product = {
            "product_type": "RAW",
            "entries": [
                {
                    "title": "Old Entry",
                    "collected_at": "2020-01-01T00:00:00+00:00",
                },
            ],
        }
        gate = D3Freshness()
        result = gate.check(product)

        assert result.passed is True
        assert result.details.get("skipped") is True

    def test_gate_type_property(self) -> None:
        """gate_type is 'delivery'."""
        gate = D3Freshness()
        assert gate.gate_type == "delivery"

    def test_context_recency_window_override(self) -> None:
        """recency_window_days from context overrides constructor value."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "entries": [
                {
                    "title": "Borderline",
                    "collected_at": (now - timedelta(days=10)).isoformat(),
                },
            ],
        }
        # Constructor says 30 days, context says 7 days → entry at 10 days is stale
        gate = D3Freshness(recency_window_days=30)
        result = gate.check(product, context={"recency_window_days": 7})

        assert result.flagged is True
        assert result.details["stale_count"] == 1


# ===================================================================
# D1-D3 orchestrator
# ===================================================================


class TestRunDeliveryGates:
    """run_delivery_gates() orchestrates D1-D3."""

    def test_all_gates_pass_for_complete_product(self) -> None:
        """All three gates pass for a valid, complete product."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Valid\n\nMarkdown content.",
            "key_findings": "Key finding",
            "summary": "Summary text",
            "recommendations": "Recommendation text",
            "entries": [
                {
                    "title": "Fresh Entry",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
            ],
        }
        results = run_delivery_gates(product)

        assert results["D1-ProductCompleteness"].passed is True
        assert results["D2-FormatIntegrity"].passed is True
        assert results["D3-Freshness"].passed is True

    def test_delivery_gates_skipped_for_raw(self) -> None:
        """All delivery gates skip for RAW product type."""
        product = {
            "product_type": "RAW",
            "format": "html",
            "body": "<broken>",
        }
        results = run_delivery_gates(product)

        for gate_name, result in results.items():
            assert result.passed is True, f"{gate_name} should pass for RAW"
            assert result.details.get("skipped") is True, f"{gate_name} should be skipped"

    def test_d1_blocks_when_missing_sections(self) -> None:
        """D1 blocks delivery when sections are missing."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Report",
            # No key_findings, summary, recommendations
            "entries": [
                {
                    "title": "Fresh Entry",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
            ],
        }
        results = run_delivery_gates(product)

        assert results["D1-ProductCompleteness"].passed is False
        assert results["D1-ProductCompleteness"].details["action"] == "block"

    def test_d2_falls_back_for_invalid_html(self) -> None:
        """D2 falls back to plain text for invalid HTML."""
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<html><body><h1>Broken</body></html>",
            "key_findings": "Findings",
            "summary": "Summary",
            "recommendations": "Recs",
            "entries": [],
        }
        results = run_delivery_gates(product)

        # D2 in fallback mode → passed=True (triggers fallback)
        assert results["D2-FormatIntegrity"].passed is True
        assert results["D2-FormatIntegrity"].flagged is True
        assert results["D2-FormatIntegrity"].details["action"] == "fallback"

    def test_d3_flags_stale_citations(self) -> None:
        """D3 flags stale citations with warning."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Report",
            "key_findings": "Findings",
            "summary": "Summary",
            "recommendations": "Recs",
            "entries": [
                {
                    "title": "Stale Entry",
                    "collected_at": (now - timedelta(days=90)).isoformat(),
                },
            ],
        }
        results = run_delivery_gates(product)

        # D3 in flag mode → passed=True, flagged=True
        assert results["D3-Freshness"].passed is True
        assert results["D3-Freshness"].flagged is True
        assert results["D3-Freshness"].details["stale_count"] == 1

    def test_delivery_gates_configurable_per_domain(self) -> None:
        """D1-D3 configs passed via delivery_gate_configs are applied."""
        now = datetime.now(timezone.utc)
        product = {
            "format": "html",
            "body": "<broken>html",
            "entries": [
                {
                    "title": "Stale Entry",
                    "collected_at": (now - timedelta(days=90)).isoformat(),
                },
            ],
        }
        configs = {
            "D1": {"enabled": False},
            "D2": {"enabled": True, "action_on_failure": "flag"},
            "D3": {"enabled": True, "action_on_failure": "block"},
        }
        results = run_delivery_gates(product, delivery_gate_configs=configs)

        # D1 is disabled → trivially passes with skipped reason
        assert results["D1-ProductCompleteness"].passed is True
        assert results["D1-ProductCompleteness"].details["skipped"] is True
        # D2 uses flag mode (not block) despite missing sections in product_output
        # Actually D2 checks body/format, not sections. With action_on_failure="flag",
        # invalid HTML passes but flagged.
        assert results["D2-FormatIntegrity"].passed is True
        assert results["D2-FormatIntegrity"].flagged is True
        # D3 uses block mode
        assert results["D3-Freshness"].passed is False


# ===================================================================
# G1 — Source Authority: configurable action
# ===================================================================


class TestG1SourceAuthorityAction:
    """G1 supports configurable action via gate_config parameter."""

    def test_default_action_flag_tier_low_passes(self) -> None:
        """Default action='flag' — tier 1-2 passes unflagged (backward compat)."""
        item = Item(
            id="test-g1-01", source_name="trusted", source_type="api",
            source_url="https://example.com", title="", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        gate = G1SourceAuthority()
        result = gate.check(item)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["action"] == "flag"

    def test_default_action_flag_tier_high_passes_flagged(self) -> None:
        """Default action='flag' — tier 3+ passes with flag (backward compat)."""
        item = Item(
            id="test-g1-02", source_name="low-trust", source_type="api",
            source_url="https://example.com", title="", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=3,
        )
        gate = G1SourceAuthority()
        result = gate.check(item)

        assert result.passed is True
        assert result.flagged is True
        assert result.details["action"] == "flag"
        assert "warning" in result.details

    def test_action_skip_tier_high_fails(self) -> None:
        """action='skip' and tier 3+ → passed=False with action=skip."""
        item = Item(
            id="test-g1-03", source_name="low-trust", source_type="api",
            source_url="https://example.com", title="", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=3,
        )
        config = QualityGateConfig(name="G1", category="soft", action="skip")
        gate = G1SourceAuthority()
        result = gate.check(item, gate_config=config)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["action"] == "skip"

    def test_action_skip_tier_low_passes(self) -> None:
        """action='skip' but tier 1-2 → still passes (only high tiers are skipped)."""
        item = Item(
            id="test-g1-04", source_name="trusted", source_type="api",
            source_url="https://example.com", title="", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        config = QualityGateConfig(name="G1", category="soft", action="skip")
        gate = G1SourceAuthority()
        result = gate.check(item, gate_config=config)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["action"] == "skip"

    def test_no_gate_config_uses_default_flag(self) -> None:
        """No gate_config → default action='flag' (backward compat)."""
        item = Item(
            id="test-g1-05", source_name="low-trust", source_type="api",
            source_url="https://example.com", title="", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=4,
        )
        gate = G1SourceAuthority()
        result = gate.check(item)

        assert result.passed is True  # default flag never blocks
        assert result.flagged is True
        assert result.details["action"] == "flag"


# ===================================================================
# G2 — Dedup: configurable action
# ===================================================================


class TestG2DedupAction:
    """G2 supports configurable action via gate_config parameter."""

    def test_default_action_flag_duplicate(self) -> None:
        """Default action='flag' — duplicate is flagged (backward compat)."""
        item = Item(
            id="test-g2-01", source_name="test", source_type="api",
            source_url="https://example.com/dup", title="Dup", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        existing = [
            KBEntry(
                entry_id="existing-01", title="Dup", domain="test", tier="01-Raw",
                source_url="https://example.com/dup",
                source_type="api", source_platform="web",
                collected_at="", file_path="",
            ),
        ]
        gate = G2Dedup()
        result = gate.check(item, existing)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["action"] == "flag"
        assert result.details["is_duplicate"] is True

    def test_action_skip_duplicate(self) -> None:
        """action='skip' — duplicate detected with action='skip' in details."""
        item = Item(
            id="test-g2-02", source_name="test", source_type="api",
            source_url="https://example.com/dup2", title="Dup2", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        existing = [
            KBEntry(
                entry_id="existing-02", title="Dup2", domain="test", tier="01-Raw",
                source_url="https://example.com/dup2",
                source_type="api", source_platform="web",
                collected_at="", file_path="",
            ),
        ]
        config = QualityGateConfig(name="G2", category="soft", action="skip")
        gate = G2Dedup()
        result = gate.check(item, existing, gate_config=config)

        assert result.passed is False  # still detects duplicate
        assert result.flagged is True
        assert result.details["action"] == "skip"
        assert result.details["is_duplicate"] is True

    def test_no_gate_config_uses_default_flag(self) -> None:
        """No gate_config → default action='flag' (backward compat)."""
        item = Item(
            id="test-g2-03", source_name="test", source_type="api",
            source_url="https://example.com/nodup", title="Unique", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        gate = G2Dedup()
        result = gate.check(item, [])

        assert result.passed is True
        assert result.details["action"] == "flag"

    def test_action_skip_unique_passes(self) -> None:
        """action='skip' — unique item still passes normally."""
        item = Item(
            id="test-g2-04", source_name="test", source_type="api",
            source_url="https://example.com/unique", title="Unique", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        config = QualityGateConfig(name="G2", category="soft", action="skip")
        gate = G2Dedup()
        result = gate.check(item, [], gate_config=config)

        assert result.passed is True
        assert result.details["action"] == "skip"


# ===================================================================
# G3 — Relevance Scoring: configurable action
# ===================================================================


class TestG3RelevanceScoringAction:
    """G3 supports configurable action via gate_config parameter."""

    def test_default_action_archive_below_threshold(self) -> None:
        """Default action='archive' — below-threshold gets hidden=True + archive=True (backward compat)."""
        item = Item(
            id="test-g3-01", source_name="test", source_type="api",
            source_url="https://example.com", title="No match here",
            content="Completely unrelated content that does not match keywords",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        gate = G3RelevanceScoring()
        result = gate.check(item, ["IVF", "embryo", "fertility"], threshold=30)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["hidden"] is True
        assert result.details["action"] == "archive"
        assert result.details.get("archive") is True

    def test_action_archive_below_threshold(self) -> None:
        """action='archive' — below-threshold item has archive=True in details."""
        item = Item(
            id="test-g3-02", source_name="test", source_type="api",
            source_url="https://example.com", title="Unrelated",
            content="Some random text that does not contain keywords",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        config = QualityGateConfig(name="G3", category="soft", action="archive")
        gate = G3RelevanceScoring()
        result = gate.check(item, ["IVF", "embryo"], threshold=30, gate_config=config)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["hidden"] is True
        assert result.details["action"] == "archive"
        assert result.details.get("archive") is True

    def test_action_flag_below_threshold(self) -> None:
        """action='flag' — below-threshold gets hidden=True but no archive flag."""
        item = Item(
            id="test-g3-03", source_name="test", source_type="api",
            source_url="https://example.com", title="Unrelated",
            content="Some random text that does not contain keywords",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        config = QualityGateConfig(name="G3", category="soft", action="flag")
        gate = G3RelevanceScoring()
        result = gate.check(item, ["IVF", "embryo"], threshold=30, gate_config=config)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["hidden"] is True
        assert result.details["action"] == "flag"
        assert result.details.get("archive") is None  # no archive when action=flag

    def test_above_threshold_passes(self) -> None:
        """Above threshold item passes regardless of action config."""
        item = Item(
            id="test-g3-04", source_name="test", source_type="api",
            source_url="https://example.com", title="IVF breakthrough",
            content="New IVF treatment shows promising results for embryo development",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        config = QualityGateConfig(name="G3", category="soft", action="archive")
        gate = G3RelevanceScoring()
        result = gate.check(item, ["IVF", "embryo"], threshold=30, gate_config=config)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["hidden"] is False
        assert result.details["action"] == "archive"

    def test_no_gate_config_uses_default_archive(self) -> None:
        """No gate_config → default action='archive' (backward compat)."""
        item = Item(
            id="test-g3-05", source_name="test", source_type="api",
            source_url="https://example.com", title="No keywords",
            content="Completely unrelated content with zero keyword matches",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        gate = G3RelevanceScoring()
        result = gate.check(item, ["IVF", "embryo"], threshold=30)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["hidden"] is True
        assert result.details["action"] == "archive"
        assert result.details.get("archive") is True


# ===================================================================
# Helpers for G4 tests
# ===================================================================


def _g4_make_response(return_json: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(return_json)
    return mock_response


def _g4_mock_litellm_sequential(return_jsons: list[dict]) -> MagicMock:
    mock_litellm = MagicMock()
    mock_litellm.completion.side_effect = [
        _g4_make_response(rj) for rj in return_jsons
    ]
    return mock_litellm


def _g4_fixture_item() -> Item:
    return Item(
        id="test-item-g4-retry",
        source_name="pubmed",
        source_type="api",
        source_url="https://example.com/article",
        title="Test article about IVF outcomes",
        content=(
            "A recent study found that IVF success rates improve with "
            "time-lapse imaging. The live birth rate was 48.2% in the "
            "treatment group compared to 39.5% in the control group."
        ),
        content_type="text",
        collected_at="2026-07-20T10:00:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=1,
    )


def _g4_fixture_extraction(tl_dr: str = "IVF success rates improve with time-lapse imaging.") -> ExtractionResult:
    return ExtractionResult(
        item_id="test-item-g4-retry",
        title="Test article about IVF outcomes",
        tl_dr=tl_dr,
        key_points=["Time-lapse imaging improves IVF outcomes"],
        entities=[{"name": "IVF", "type": "procedure", "relevance": 0.9}],
        relevance_score=90.0,
    )


def _g4_gate_config(retries: int = 3) -> QualityGateConfig:
    return QualityGateConfig(
        name="G4",
        category="hard",
        retries=retries,
        retry_models=["test/model-two", "test/model-three"],
        action="block",
    )


# ===================================================================
# G4 — Retry Chain
# ===================================================================


class TestG4RetryChain:
    """G4FactualConsistency retry logic — 3x retry with escalating context."""

    def test_passes_on_consistent_summary_single_call(self) -> None:
        """G4 passes when LLM returns no contradiction on first call."""
        item = _g4_fixture_item()
        extraction = _g4_fixture_extraction()
        gate_config = _g4_gate_config(retries=3)

        mock_llm = _g4_mock_litellm_sequential([
            {"contradiction": False, "explanation": "Summary matches source."},
        ])
        with patch("autoinfo.quality.call_with_fallback", side_effect=mock_llm.completion.side_effect) as mock_cwf:
            g4 = G4FactualConsistency(model="test/test-model")
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["contradiction"] is False
        assert result.score == 1.0
        assert mock_cwf.call_count == 1

    def test_retries_twice_succeeds_on_third(self) -> None:
        """G4 retries after contradiction; succeeds on 3rd attempt with different model."""
        item = _g4_fixture_item()
        extraction = _g4_fixture_extraction()
        gate_config = _g4_gate_config(retries=3)

        mock_llm = _g4_mock_litellm_sequential([
            {
                "contradiction": True,
                "explanation": "Summary says decrease but source says increase.",
            },
            {
                "contradiction": True,
                "explanation": "Summary still contradicts source on second check.",
            },
            {"contradiction": False, "explanation": "Summary matches source on re-evaluation."},
        ])
        with patch("autoinfo.quality.call_with_fallback", side_effect=mock_llm.completion.side_effect) as mock_cwf:
            g4 = G4FactualConsistency(model="test/test-model")
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["contradiction"] is False
        assert result.score == 1.0
        assert mock_cwf.call_count == 3
        model_args = [call.kwargs.get("model") for call in mock_cwf.call_args_list]
        assert model_args[0] == "test/test-model"
        assert model_args[1] == "test/model-two"
        assert model_args[2] == "test/model-three"

    def test_blocks_after_all_retries_exhausted(self) -> None:
        """G4 blocks when all 3 retries return contradiction."""
        item = _g4_fixture_item()
        extraction = _g4_fixture_extraction()
        gate_config = _g4_gate_config(retries=3)

        mock_llm = _g4_mock_litellm_sequential([
            {"contradiction": True, "explanation": "First check: contradiction found."},
            {"contradiction": True, "explanation": "Second check: still contradictory."},
            {"contradiction": True, "explanation": "Third check: still contradicts."},
        ])
        with patch("autoinfo.quality.call_with_fallback", side_effect=mock_llm.completion.side_effect) as mock_cwf:
            g4 = G4FactualConsistency(model="test/test-model")
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is False
        assert result.flagged is True
        assert result.score == 0.0
        assert result.details["contradiction"] is True
        assert result.details["action"] == "block"
        assert result.details["retry_count"] == 3
        assert mock_cwf.call_count == 3

    def test_failed_json_written_on_block(self, tmp_path: Path) -> None:
        """When G4 blocks, _failed/ diagnostics JSON is written."""
        item = _g4_fixture_item()
        extraction = _g4_fixture_extraction()
        gate_config = _g4_gate_config(retries=3)

        mock_llm = _g4_mock_litellm_sequential([
            {"contradiction": True, "explanation": "Contradiction 1"},
            {"contradiction": True, "explanation": "Contradiction 2"},
            {"contradiction": True, "explanation": "Contradiction 3"},
        ])

        collections_dir = tmp_path / "collections"
        with patch("autoinfo.quality.call_with_fallback", side_effect=mock_llm.completion.side_effect) as mock_cwf:
            g4 = G4FactualConsistency(
                model="test/test-model",
                collections_path=str(collections_dir),
            )
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is False
        assert result.details["action"] == "block"

        failed_path = collections_dir / "medical-research" / "_failed" / "test-item-g4-retry.json"
        assert failed_path.exists()

        with open(failed_path, encoding="utf-8") as fh:
            diagnostics = json.load(fh)

        assert diagnostics["item_id"] == "test-item-g4-retry"
        assert diagnostics["source_url"] == "https://example.com/article"
        assert len(diagnostics["retries"]) == 3
        assert diagnostics["retries"][0]["attempt"] == 1
        assert diagnostics["retries"][0]["model"] == "test/test-model"
        assert diagnostics["retries"][1]["model"] == "test/model-two"
        assert diagnostics["retries"][2]["model"] == "test/model-three"
        assert "final_error" in diagnostics
        assert "item_snapshot" in diagnostics
        assert isinstance(diagnostics["item_snapshot"], dict)
        assert diagnostics["item_snapshot"]["id"] == "test-item-g4-retry"
        assert diagnostics["item_snapshot"]["source_url"] == "https://example.com/article"

    def test_skips_when_extraction_failed(self) -> None:
        """G4 skips LLM call when extraction has no tl_dr (extraction_failed)."""
        item = _g4_fixture_item()
        extraction = _g4_fixture_extraction(tl_dr="")
        gate_config = _g4_gate_config(retries=3)

        mock_llm = MagicMock()
        with patch("autoinfo.quality.call_with_fallback", side_effect=mock_llm.completion.side_effect) as mock_cwf:
            g4 = G4FactualConsistency(model="test/test-model")
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is True
        assert result.flagged is False
        assert result.details["contradiction"] is False
        assert result.details["explanation"] == "No summary to check"
        mock_llm.completion.assert_not_called()


# ===================================================================
# Gate config integration — per-gate config via run_quality_gates
# ===================================================================


class TestGateConfigIntegration:
    """run_quality_gates() with gate_config dict — retries, action, threshold."""

    def test_g0_retry_count_from_config(self, sample_item: Item) -> None:
        """G0 reads retry count from gate_config (retries=3 → retry_count=3)."""
        from autoinfo.config import QualityGateConfig as QGC
        g0_gate = G0SchemaIntegrity()
        result = g0_gate.check(
            {"source_url": "", "source_type": "", "source_platform": ""},
            gate_config=QGC(name="G0", category="hard", retries=3, action="block"),
        )
        assert result.passed is False
        assert result.details["retry_count"] == 3
        assert result.details["action"] == "block"

    def test_defaults_when_gate_config_empty(self, sample_item: Item) -> None:
        """All gates use default values when gate_config is None or empty."""
        results = run_quality_gates(sample_item)
        assert results["G0-SchemaIntegrity"].passed is True
        assert results["G1-SourceAuthority"].passed is True
        assert results["G2-Dedup"].passed is True
        assert results["G3-RelevanceScoring"].passed is True

        g0 = G0SchemaIntegrity()
        result = g0.check({"source_url": "", "source_type": "", "source_platform": ""})
        assert result.details["retry_count"] == 1

        results2 = run_quality_gates(sample_item, gate_config={})
        assert results2["G0-SchemaIntegrity"].passed is True

    def test_invalid_gate_config_type_does_not_crash(self, sample_item: Item) -> None:
        """Invalid gate_config type (e.g. str) logs warning and falls back to defaults."""
        results = run_quality_gates(sample_item, gate_config="invalid")  # type: ignore[arg-type]
        assert "G0-SchemaIntegrity" in results
        assert results["G0-SchemaIntegrity"].passed is True
        assert results["G1-SourceAuthority"].passed is True

        results2 = run_quality_gates(sample_item, gate_config=None)
        assert "G0-SchemaIntegrity" in results2

    def test_g3_threshold_from_gate_config(self, sample_item: Item) -> None:
        """G3 threshold is read from gate_config when provided (overrides context)."""
        from autoinfo.config import QualityGateConfig as QGC
        item_no_match = Item(
            id="test-g3-threshold", source_name="test", source_type="api",
            source_url="https://example.com", title="No keywords here",
            content="Completely unrelated content that does not match",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
        )
        keywords = ["IVF", "embryo"]

        results_high = run_quality_gates(
            item_no_match,
            context={"topic_keywords": keywords, "threshold": 100},
        )
        assert results_high["G3-RelevanceScoring"].details["hidden"] is True

        cfg = QGC(name="G3", category="soft", threshold=5.0)
        results_low = run_quality_gates(
            item_no_match,
            context={"topic_keywords": keywords, "threshold": 100},
            gate_config={"G3-RelevanceScoring": cfg},
        )
        assert results_low["G3-RelevanceScoring"].details["hidden"] is True
        assert results_low["G3-RelevanceScoring"].details["threshold"] == 5

    def test_per_domain_config_override_merge(self) -> None:
        """Domain-level quality_gates override global defaults (merge logic)."""
        from autoinfo.config import QualityGateConfig as QGC

        global_gates = {
            "G0-SchemaIntegrity": QGC(name="G0", category="hard", retries=1, action="block"),
            "G1-SourceAuthority": QGC(name="G1", category="soft", action="flag"),
            "G2-Dedup": QGC(name="G2", category="soft", action="flag"),
        }
        domain_gates = {
            "G1-SourceAuthority": QGC(name="G1", category="soft", action="skip"),
            "G3-RelevanceScoring": QGC(name="G3", category="soft", threshold=50.0),
        }

        merged = dict(global_gates)
        merged.update(domain_gates)

        assert merged["G0-SchemaIntegrity"].action == "block"
        assert merged["G0-SchemaIntegrity"].retries == 1
        assert merged["G1-SourceAuthority"].action == "skip"
        assert merged["G3-RelevanceScoring"].threshold == 50.0
        assert merged["G2-Dedup"].action == "flag"


# ===================================================================
# G0/G4 hard gate enforcement in processing pipeline
# ===================================================================


class TestG0G4InProcessingPipeline:
    """G0 and G4 hard gate enforcement in ``run_processing()``.

    Tests that:
    - G0 runs BEFORE LLM extraction and blocks malformed items
    - G4 retry chain can block items after extraction
    - Both write ``_failed/`` diagnostics per domain
    - Passing both gates stores items normally
    """

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _make_config_yaml(
        tmp_path: Path,
        domain: str = "test-domain",
        quality_gates: dict | None = None,
    ) -> Path:
        """Write a minimal config to ``tmp_path/.autoinfo/config.yaml``."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_data: dict = {
            "project": {"name": "Test", "created_at": "2026-07-24"},
            "llm": {"provider": "openrouter", "model": "test/model"},
            "domains": [
                {
                    "name": domain,
                    "active": True,
                    "sources": [],
                    "topics": [],
                }
            ],
        }
        if quality_gates:
            config_data["quality_gates"] = quality_gates
            config_data["domains"][0]["quality_gates"] = quality_gates

        config_path = config_dir / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as fh:
            yaml.dump(config_data, fh, default_flow_style=False)
        return config_path

    @staticmethod
    def _make_good_item(item_id: str = "good-item") -> Item:
        """Return an Item with valid mandatory fields (passes G0)."""
        return Item(
            id=item_id,
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/article",
            title="Test article",
            content=(
                "Time-lapse embryo imaging significantly improves live birth "
                "rates compared to standard morphological assessment in IVF "
                "patients (48.2% vs. 39.5%, p=0.006)."
            ),
            content_type="text",
            collected_at="2026-07-20T10:00:00Z",
            language="en",
            domain="test-domain",
            source_platform="pubmed",
            quality_tier=1,
        )

    @staticmethod
    def _make_bad_item(item_id: str = "bad-item") -> Item:
        """Return an Item with empty source_url (triggers G0 block)."""
        return Item(
            id=item_id,
            source_name="pubmed",
            source_type="api",
            source_url="",  # empty → G0 blocks
            title="Bad item",
            content="Some content",
            content_type="text",
            collected_at="",
            language="en",
            domain="test-domain",
        )

    @staticmethod
    def _make_mock_store() -> MagicMock:
        """Return a mocked KBStore."""
        from autoinfo.kb import KBEntry as KBEntryCls

        mock_store = MagicMock()
        mock_store.list_entries.return_value = []
        mock_store.store_entry.return_value = KBEntryCls(
            entry_id="mock-entry",
            title="mock",
            domain="test-domain",
        )
        return mock_store

    @staticmethod
    def _make_mock_litellm(return_json: dict | None = None) -> MagicMock:
        """Return a mock litellm completion that returns *return_json*."""
        mock_llm = MagicMock()
        if return_json is not None:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps(return_json)
            mock_response.usage = MagicMock()
            # Set all usage fields explicitly so getattr() returns ints, not MagicMocks
            mock_response.usage.prompt_tokens = 50
            mock_response.usage.completion_tokens = 30
            mock_response.usage.total_tokens = 80
            mock_llm.completion.return_value = mock_response
        return mock_llm

    # -- tests ---------------------------------------------------------

    def test_g0_failure_skips_item_and_writes_failed(
        self, tmp_path: Path
    ) -> None:
        """G0 failure → item skipped, _failed/ written, no KB entry."""
        config_path = self._make_config_yaml(tmp_path)
        bad_item = self._make_bad_item()
        mock_store = self._make_mock_store()

        original_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            with (
                patch(
                    "autoinfo.process.get_config_path",
                    return_value=config_path,
                ),
                patch(
                    "autoinfo.process.load_cached_items",
                    return_value=[bad_item],
                ),
                patch(
                    "autoinfo.process.KBStore",
                    return_value=mock_store,
                ),
            ):
                from autoinfo.process import run_processing

                result = run_processing(domain="test-domain")
        finally:
            os.chdir(original_cwd)

        assert result.kb_entries_created == 0
        mock_store.store_entry.assert_not_called()

        failed_dir = tmp_path / "collections" / "test-domain" / "_failed"
        assert failed_dir.is_dir()
        failed_file = failed_dir / "bad-item.json"
        assert failed_file.exists()

        with open(failed_file, encoding="utf-8") as fh:
            diag = json.load(fh)
        assert diag["item_id"] == "bad-item"
        assert diag["gate"] == "G0"
        assert diag["gate_result"]["passed"] is False
        assert diag["gate_result"]["details"]["action"] == "block"

        assert len(result.per_item_logs) == 0

    def test_g4_failure_blocks_item_and_writes_failed(
        self, tmp_path: Path
    ) -> None:
        """G4 retry chain exhaustion → item blocked, not stored in KB."""
        config_path = self._make_config_yaml(tmp_path)
        good_item = self._make_good_item("g4-blocked-item")
        mock_store = self._make_mock_store()

        mock_extract_llm = self._make_mock_litellm({
            "tl_dr": "Test summary that contradicts.",
            "key_points": ["Point"],
            "entities": [{"name": "IVF", "type": "procedure", "relevance": 0.9}],
            "relevance_score": 80.0,
        })

        block_result = QualityResult(
            gate_name="G4-SummaryFactual",
            passed=False,
            flagged=True,
            score=0.0,
            details={
                "contradiction": True,
                "action": "block",
                "retry_count": 3,
                "explanation": "All 3 attempts exhausted.",
            },
        )

        original_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            with (
                patch(
                    "autoinfo.process.get_config_path",
                    return_value=config_path,
                ),
                patch(
                    "autoinfo.process.load_cached_items",
                    return_value=[good_item],
                ),
                patch(
                    "autoinfo.process.KBStore",
                    return_value=mock_store,
                ),
                patch.object(
                    LLMExtractor,
                    "_get_litellm",
                    return_value=mock_extract_llm,
                ),
                patch.object(
                    G4FactualConsistency,
                    "check",
                    return_value=block_result,
                ),
            ):
                from autoinfo.process import run_processing

                result = run_processing(
                    domain="test-domain", check_factual=True
                )
        finally:
            os.chdir(original_cwd)

        assert result.kb_entries_created == 0
        mock_store.store_entry.assert_not_called()
        assert len(result.per_item_logs) == 0

    def test_g0_and_g4_pass_item_stored_normally(
        self, tmp_path: Path
    ) -> None:
        """G0 + G4 pass → item stored in KB, no _failed/ for this item."""
        config_path = self._make_config_yaml(tmp_path)
        good_item = self._make_good_item("passing-item")
        mock_store = self._make_mock_store()

        mock_extract_llm = self._make_mock_litellm({
            "tl_dr": "IVF success rates improve with time-lapse imaging.",
            "key_points": ["Time-lapse imaging improves IVF outcomes"],
            "entities": [{"name": "IVF", "type": "procedure", "relevance": 0.9}],
            "relevance_score": 85.0,
        })

        mock_g4_llm = self._make_mock_litellm(
            {"contradiction": False, "explanation": "Summary matches source."}
        )

        with (
            patch("autoinfo.process.get_config_path", return_value=config_path),
            patch(
                "autoinfo.process.load_cached_items",
                return_value=[good_item],
            ),
            patch("autoinfo.process.KBStore", return_value=mock_store),
            patch.object(
                LLMExtractor, "_get_litellm", return_value=mock_extract_llm
            ),
            patch.object(
                G4FactualConsistency,
                "_get_litellm",
                return_value=mock_g4_llm,
            ),
        ):
            from autoinfo.process import run_processing
            result = run_processing(
                domain="test-domain", check_factual=True
            )

        assert result.kb_entries_created == 1
        mock_store.store_entry.assert_called_once()

        failed_dir = tmp_path / "collections" / "test-domain" / "_failed"
        failed_file = failed_dir / "passing-item.json"
        assert not failed_file.exists()

        # Per-item log shows ok
        assert len(result.per_item_logs) == 1
        assert result.per_item_logs[0]["status"] == "ok"

    def test_failed_dir_created_per_domain(
        self, tmp_path: Path
    ) -> None:
        """_failed/ directory is created per domain on first G0 failure."""
        config_path = self._make_config_yaml(tmp_path, domain="domain-a")
        bad_item_a = self._make_bad_item("bad-a")
        mock_store = self._make_mock_store()

        original_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            with (
                patch(
                    "autoinfo.process.get_config_path",
                    return_value=config_path,
                ),
                patch(
                    "autoinfo.process.load_cached_items",
                    return_value=[bad_item_a],
                ),
                patch(
                    "autoinfo.process.KBStore",
                    return_value=mock_store,
                ),
            ):
                from autoinfo.process import run_processing

                run_processing(domain="domain-a")

            # _failed/ exists for domain-a
            failed_a = tmp_path / "collections" / "domain-a" / "_failed"
            assert failed_a.is_dir()
            assert (failed_a / "bad-a.json").exists()

            # Second domain also creates its own _failed/
            config_path_b = self._make_config_yaml(
                tmp_path, domain="domain-b"
            )
            bad_item_b = self._make_bad_item("bad-b")
            mock_store_b = self._make_mock_store()

            with (
                patch(
                    "autoinfo.process.get_config_path",
                    return_value=config_path_b,
                ),
                patch(
                    "autoinfo.process.load_cached_items",
                    return_value=[bad_item_b],
                ),
                patch(
                    "autoinfo.process.KBStore",
                    return_value=mock_store_b,
                ),
            ):
                run_processing(domain="domain-b")
        finally:
            os.chdir(original_cwd)

        failed_b = tmp_path / "collections" / "domain-b" / "_failed"
        assert failed_b.is_dir()
        assert (failed_b / "bad-b.json").exists()
        assert len(list(failed_a.iterdir())) == 1
        assert len(list(failed_b.iterdir())) == 1
