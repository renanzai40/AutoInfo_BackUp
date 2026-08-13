"""Tests for digest generation — output.py, MCP, and CLI wiring.

Covers:
- ``generate_digest`` with markdown, HTML, JSON output
- Empty domain (no entries)
- Invalid period / format validation
- ``_compute_date_range`` helper
- MCP ``_handle_generate_digest`` handler
- CLI ``digest`` command
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.output import (
    _compute_date_range,
    _parse_json_response,
    generate_digest,
)


# ---------------------------------------------------------------------------
# Sample entry data
# ---------------------------------------------------------------------------

_SAMPLE_ENTRIES = [
    {
        "entry_id": "med-ivf-001",
        "title": "Improved IVF outcomes with time-lapse embryo imaging",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://example.com/ivf-001",
        "source_type": "api",
        "source_platform": "pubmed",
        "collected_at": (date.today() - timedelta(days=2)).isoformat(),
        "summary": "Time-lapse imaging improves live birth rates (48.2% vs 39.5%).",
        "tags": '["IVF", "embryo imaging", "RCT"]',
        "quality_tier": 1,
        "relevance_score": 92.0,
        "dedup_status": "unique",
        "file_path": "",
    },
    {
        "entry_id": "med-ivf-002",
        "title": "AI-driven embryo selection: a systematic review",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://example.com/ivf-002",
        "source_type": "api",
        "source_platform": "pubmed",
        "collected_at": (date.today() - timedelta(days=1)).isoformat(),
        "summary": "AI models show promise but lack prospective validation.",
        "tags": '["AI", "IVF", "embryo selection"]',
        "quality_tier": 1,
        "relevance_score": 85.0,
        "dedup_status": "unique",
        "file_path": "",
    },
]

_SAMPLE_LLM_SYNTHESIS = {
    "executive_summary": (
        "This week's key developments focus on IVF technology "
        "advancements including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": "Significant improvement in live birth rates (48.2% vs 39.5%) in a large RCT.",
        },
        {
            "topic": "AI embryo selection",
            "detail": "Promising but lacks prospective clinical validation.",
        },
    ],
    "trends": [
        "Increasing integration of AI/ML in reproductive medicine",
        "Growing evidence for time-lapse imaging benefits",
    ],
    "recommendations": [
        "Consider time-lapse imaging as standard of care",
        "Support prospective AI validation trials",
    ],
}


# ---------------------------------------------------------------------------
# Tests: _compute_date_range
# ---------------------------------------------------------------------------


class TestComputeDateRange:
    def test_daily(self) -> None:
        date_from, date_to = _compute_date_range("daily")
        expected_from = (date.today() - timedelta(days=1)).isoformat()
        assert date_from == expected_from
        assert date_to == date.today().isoformat()

    def test_weekly(self) -> None:
        date_from, date_to = _compute_date_range("weekly")
        expected_from = (date.today() - timedelta(days=7)).isoformat()
        assert date_from == expected_from
        assert date_to == date.today().isoformat()

    def test_monthly(self) -> None:
        date_from, date_to = _compute_date_range("monthly")
        expected_from = (date.today() - timedelta(days=30)).isoformat()
        assert date_from == expected_from
        assert date_to == date.today().isoformat()


# ---------------------------------------------------------------------------
# Tests: _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_direct_json(self) -> None:
        result = _parse_json_response('{"a": 1, "b": "two"}')
        assert result == {"a": 1, "b": "two"}

    def test_fenced_code_block(self) -> None:
        result = _parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_fenced_code_block_no_lang(self) -> None:
        result = _parse_json_response('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_bare_object_in_text(self) -> None:
        result = _parse_json_response(
            'Some text before {"nested": {"inner": 42}} and after'
        )
        assert result == {"nested": {"inner": 42}}

    def test_invalid_json_returns_empty(self) -> None:
        result = _parse_json_response("not json at all")
        assert result == {}

    def test_none_content_returns_empty(self) -> None:
        """None content (LLM json_object mismatch) must not crash (issues #96/#99)."""
        result = _parse_json_response(None)  # type: ignore[arg-type]
        assert result == {}


# ---------------------------------------------------------------------------
# Helpers for test mocks
# ---------------------------------------------------------------------------


def _mock_list_entries(
    domain=None, date_from=None, limit=20, offset=0
) -> list[dict]:
    """Return sample entries, or empty for 'empty-domain'."""
    if domain == "empty-domain":
        return []
    return _SAMPLE_ENTRIES


# ---------------------------------------------------------------------------
# Tests: generate_digest
# ---------------------------------------------------------------------------


class TestGenerateDigest:
    @patch("autoinfo.output.KBStore")  # TRIAGE #32-34: patch target must be the name used inside generate_digest (hoisted at src/autoinfo/output/__init__.py:49)
    @patch("autoinfo.output._call_llm_for_digest")
    def test_markdown_output_includes_entries_and_synthesis(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Markdown digest includes entries list and LLM synthesis sections."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(domain="medical-research", period="weekly")

        assert isinstance(result, str)
        assert "Weekly Digest" in result
        assert "medical-research" in result
        assert "Executive Summary" in result
        assert "IVF outcomes with time-lapse" in result
        assert "AI-driven embryo selection" in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_json_output_valid_structure(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """JSON output is parsable with structured metadata and entries."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="json"
        )
        parsed = json.loads(result)

        assert parsed["digest_type"] == "digest"
        assert parsed["domain"] == "medical-research"
        assert parsed["period"] == "weekly"
        assert parsed["entry_count"] == 2
        assert len(parsed["entries"]) == 2
        assert parsed["llm_synthesis"]["executive_summary"] != ""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_html_output_no_css(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """HTML output uses markdown-to-HTML conversion without styling."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="html"
        )

        assert isinstance(result, str)
        # Has HTML structure (headings, paragraphs)
        assert "<h" in result or "<p>" in result
        assert "Weekly Digest" in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_empty_domain_shows_no_entries_message(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Digest for empty domain shows 'No entries found'."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(domain="empty-domain", period="weekly")
        assert "No entries found" in result
        assert "empty-domain" in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_json_empty_domain_zero_entries(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """JSON output for empty domain has entry_count == 0."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="empty-domain", period="weekly", format="json"
        )
        parsed = json.loads(result)
        assert parsed["entry_count"] == 0
        assert parsed["entries"] == []

    @patch("autoinfo.output.KBStore")
    def test_llm_failure_still_renders_entries(
        self, mock_kb: MagicMock
    ) -> None:
        """When LLM fails, digest still renders entries without synthesis."""
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        with patch("autoinfo.output._call_llm_for_digest", return_value={}):
            result = generate_digest(
                domain="medical-research", period="weekly"
            )
            assert "Entries" in result
            assert "IVF outcomes with time-lapse" in result
            assert "Executive Summary" not in result

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period raises ValueError."""
        with pytest.raises(ValueError, match="Invalid period"):
            generate_digest(domain="test", period="yearly")

    def test_invalid_format_raises_value_error(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid format"):
            generate_digest(domain="test", period="weekly", format="pdf")

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_daily_and_monthly_periods(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Daily and monthly periods produce correct labels."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        mock_kb.return_value = mock_store

        daily = generate_digest(domain="medical-research", period="daily")
        assert "Daily Digest" in daily

        monthly = generate_digest(domain="medical-research", period="monthly")
        assert "Monthly Digest" in monthly


# ---------------------------------------------------------------------------
# Tests: MCP handler
# ---------------------------------------------------------------------------


class TestMcpHandler:
    """Tests the _handle_generate_digest MCP handler directly."""

    @pytest.fixture
    def kb_store_with_entries(self):
        """Stub KBStore entries so the handler reaches generate_digest.

        TRIAGE #38-41 — ``_handle_generate_digest`` has an intentional no-entry
        pre-check (src/autoinfo/mcp/server.py:2380-2386, added e497e11) that
        short-circuits with ``{status: "noop"}`` before the mocked
        ``generate_digest`` runs. The handler resolves KBStore via a
        function-local ``from autoinfo.kb import KBStore`` (server.py:2374),
        so this fixture patches that seam to return a non-empty preview.
        These tests exercise the handler's rendering/envelope paths, not the
        noop behavior — stubbing entries (preferred over asserting the noop
        envelope) keeps them testing what they claim to test.
        """
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        with patch("autoinfo.kb.KBStore", return_value=mock_store):
            yield

    @patch("autoinfo.mcp.server.logger")
    def test_handler_returns_success_with_content(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Handler returns success dict with rendered content."""
        from autoinfo.mcp.server import _handle_generate_digest

        with patch(
            "autoinfo.output.generate_digest",
            return_value="# Weekly Digest -- test\n\ncontent",
        ):
            result = _handle_generate_digest(
                domain="medical-research", period="weekly", format="markdown"
            )

        assert result["success"] is True
        assert result["format"] == "markdown"
        assert "# Weekly Digest" in result["content"]

    @patch("autoinfo.mcp.server.logger")
    def test_handler_json_format_parses_content(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Handler parses JSON string into dict for JSON format response."""
        from autoinfo.mcp.server import _handle_generate_digest

        json_content = json.dumps(
            {"digest_type": "digest", "domain": "test", "entry_count": 0}
        )
        with patch(
            "autoinfo.output.generate_digest",
            return_value=json_content,
        ):
            result = _handle_generate_digest(
                domain="test", period="weekly", format="json"
            )

        assert result["success"] is True
        assert result["format"] == "json"
        assert result["content"]["digest_type"] == "digest"
        assert result["content"]["entry_count"] == 0

    @patch("autoinfo.mcp.server.logger")
    def test_handler_propagates_validation_error(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Handler returns error dict for ValueError from generate_digest."""
        from autoinfo.mcp.server import _handle_generate_digest

        with patch(
            "autoinfo.output.generate_digest",
            side_effect=ValueError("Invalid period 'yearly'"),
        ):
            result = _handle_generate_digest(domain="test", period="yearly")

        assert "error_code" in result
        assert result["error_code"] == "ValidationError"

    @patch("autoinfo.mcp.server.logger")
    def test_handler_returns_error_for_exception(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Handler returns error dict for generic exceptions."""
        from autoinfo.mcp.server import _handle_generate_digest

        with patch(
            "autoinfo.output.generate_digest",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = _handle_generate_digest(domain="test", period="weekly")

        assert "error_code" in result

    @patch("autoinfo.mcp.server.logger")
    def test_handler_digest_with_product_passes_registry_template(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Handler forwards the PRODUCT_TEMPLATES row for product to generate_digest."""
        from autoinfo.output import PRODUCT_TEMPLATES
        from autoinfo.mcp.server import _handle_generate_digest

        _row = next(
            r for r in PRODUCT_TEMPLATES if r["name"] == "magazine-digest"
        )
        with patch(
            "autoinfo.output.generate_digest",
            return_value="# Magazine Digest -- test\n\ncurated content",
        ) as mock_generate:
            result = _handle_generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                product="magazine-digest",
            )

        assert result["success"] is True
        assert "# Magazine Digest" in result["content"]
        assert mock_generate.call_args.kwargs["product_template"] is _row["template"]

    @patch("autoinfo.mcp.server.logger")
    def test_handler_digest_unknown_product_returns_error_envelope(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """Unknown product returns the canonical error envelope with valid names."""
        from autoinfo.output import PRODUCT_TEMPLATES
        from autoinfo.mcp.server import _handle_generate_digest

        result = _handle_generate_digest(
            domain="medical-research", product="no-such-product"
        )

        assert result["success"] is False
        assert result["error"]["code"] == "ValidationError"
        assert result["error"]["actionable"] is True
        assert "no-such-product" in result["error"]["message"]
        _valid = {r["name"] for r in PRODUCT_TEMPLATES}
        for name in _valid:
            assert name in result["error"]["message"]

    @patch("autoinfo.mcp.server.logger")
    def test_handler_digest_without_product_unchanged(
        self, mock_logger: MagicMock, kb_store_with_entries
    ) -> None:
        """No product param -> generate_digest receives product_template=None."""
        from autoinfo.mcp.server import _handle_generate_digest

        with patch(
            "autoinfo.output.generate_digest",
            return_value="# Weekly Digest -- test\n\ncontent",
        ) as mock_generate:
            result = _handle_generate_digest(
                domain="medical-research", period="weekly", format="markdown"
            )

        assert result["success"] is True
        assert "# Weekly Digest" in result["content"]
        assert mock_generate.call_args.kwargs["product_template"] is None


# ---------------------------------------------------------------------------
# Tests: CLI wiring
# ---------------------------------------------------------------------------


# CLI tests skipped due to typer + Python 3.14 incompatibility
# (inspect.signature(eval_str=True) fails on Python 3.14 + typer 0.12)
# Issue affects ALL CLI tests across the project, not just digest.
# Re-enable when upstream typer fixes eval_str compatibility with Python 3.14.

class TestCliDigest:
    @patch("autoinfo.output.generate_digest")
    def test_digest_command_calls_generate(
        self, mock_generate: MagicMock
    ) -> None:
        """CLI digest command calls generate_digest and echoes result."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_digest")
    def test_digest_command_json_format(
        self, mock_generate: MagicMock
    ) -> None:
        """JSON format flag forwarded to generate_digest."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_digest")
    def test_digest_command_error_handling(
        self, mock_generate: MagicMock
    ) -> None:
        """When generate_digest raises, CLI exits with error code 1."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_digest")
    def test_digest_command_defaults(
        self, mock_generate: MagicMock
    ) -> None:
        """CLI uses default period (weekly) and format (markdown)."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")
