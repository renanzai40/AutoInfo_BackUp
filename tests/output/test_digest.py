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
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import (
    DeliveryOutput,
    _annotate_rmb_usd,
    _build_digest_llm_prompt,
    _call_llm_for_digest,
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
        "language": "en",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
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
        "language": "en",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
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
            "detail": (
                "Significant improvement in live birth rates (48.2% vs 39.5%)"
                " in a large RCT."
            ),
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
        result = _parse_json_response(None)
        assert result == {}


# ---------------------------------------------------------------------------
# Helpers for test mocks
# ---------------------------------------------------------------------------


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return sample entries, or empty for 'empty-domain'."""
    if domain == "empty-domain":
        return []
    return _SAMPLE_ENTRIES


# ---------------------------------------------------------------------------
# Tests: generate_digest
# ---------------------------------------------------------------------------


class TestCallLlmForDigestRetry:
    """Issue #217: empty synthesis retries before giving up."""

    def _make_response(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    def test_retries_once_on_empty_content(self) -> None:
        """A first empty response triggers one retry that returns synthesis."""
        empty = self._make_response("not json")
        good = self._make_response(json.dumps({"executive_summary": "ok"}))
        with (
            patch(
                "autoinfo.output.call_with_fallback",
                side_effect=[empty, good],
            ),
            patch("autoinfo.output.load_config", return_value=None),
        ):
            result = _call_llm_for_digest("prompt")
        assert result.get("executive_summary") == "ok"

    def test_two_empty_responses_return_empty(self) -> None:
        """Two consecutive empty responses give up and return {} — the
        caller then fills the sections deterministically (fallback)."""
        empty = self._make_response("not json")
        with (
            patch(
                "autoinfo.output.call_with_fallback",
                side_effect=[empty, empty],
            ),
            patch("autoinfo.output.load_config", return_value=None),
        ):
            result = _call_llm_for_digest("prompt")
        assert result == {}


class TestGenerateDigest:
    @patch(
        # TRIAGE #32-34: patch target must be the name used inside
        # generate_digest (hoisted at src/autoinfo/output/__init__.py:49)
        "autoinfo.output.KBStore",
    )
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
        # Issue #144/#153: the rendered product uses the display domain name
        # (Medical Research), never the internal slug (R1).
        assert "Medical Research" in result
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
        parsed = json.loads(cast(str, result))

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
        """Digest for empty domain shows a neutral empty-state message (#342)."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(domain="empty-domain", period="weekly")
        assert "This edition has no curated items yet" in cast(str, result)
        # Issue #144/#153: display domain name (Empty Domain), not the slug.
        assert "Empty Domain" in cast(str, result)
        assert "No entries found" not in cast(str, result)
        assert "_No " not in cast(str, result)

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
        parsed = json.loads(cast(str, result))
        assert parsed["entry_count"] == 0
        assert parsed["entries"] == []

    @patch("autoinfo.output.KBStore")
    def test_llm_failure_still_renders_entries(
        self, mock_kb: MagicMock
    ) -> None:
        """When LLM fails, digest still renders entries — and, per issue
        #217, a deterministic entry-derived synthesis fills the D1-required
        sections instead of leaving them empty."""
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        with patch("autoinfo.output._call_llm_for_digest", return_value={}):
            result = generate_digest(
                domain="medical-research", period="weekly"
            )
            assert "Entries" in cast(str, result)
            assert "IVF outcomes with time-lapse" in cast(str, result)
            # Issue #217: synthesis is now entry-derived, never empty —
            # D1 (product completeness) must not block the product.
            assert "Executive Summary" in cast(str, result)
            assert "IVF" in cast(str, result)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_empty_llm_synthesis_falls_back_to_entry_sections(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Issue #217: when the LLM returns empty synthesis, the digest still
        carries non-empty D1-required sections derived from real entries —
        D1 must not block the product for empty key_findings/summary/
        recommendations."""
        mock_llm.return_value = {}  # DeepSeek intermittent empty output
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="json"
        )
        parsed = json.loads(cast(str, result))
        synth = parsed["llm_synthesis"]
        assert synth["executive_summary"].strip()
        assert synth["key_findings"]
        assert synth["recommendations"]
        # Fallback is derived from the real entries, never fabricated.
        assert "IVF" in synth["executive_summary"] or "AI" in synth["executive_summary"]

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_empty_synthesis_passes_d1_gate(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Issue #217: D1 (product completeness) must pass when the LLM
        synthesis was empty and the deterministic entry-derived fallback
        filled the required sections."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="json",
            delivery_gate_configs={
                "D1-ProductCompleteness": {"action": "block"},
            },
        )
        assert isinstance(result, DeliveryOutput)
        assert not result.delivery_blocked
        d1 = result.gate_results.get("D1-ProductCompleteness")
        assert d1 is not None
        assert d1.passed is True

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
        assert "Daily Digest" in cast(str, daily)

        monthly = generate_digest(domain="medical-research", period="monthly")
        assert "Monthly Digest" in cast(str, monthly)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_renders_real_tags(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Issue #16: a digest entry with real tags renders them (never ``—``),
        and its relevance_score renders as a real value (never ``—``)."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        entries = [
            {
                "entry_id": "tagged-001",
                "title": "AI startup raises Series A",
                "language": "en",
                "domain": "medical-research",
                "tier": "01-Raw",
                "source_url": "https://example.com/tagged-001",
                "source_type": "api",
                "source_platform": "pubmed",
                "collected_at": (date.today() - timedelta(days=1)).isoformat(),
                "summary": "A startup closed a funding round.",
                "tags": '["ai", "funding"]',
                "quality_tier": 1,
                "relevance_score": 70.0,
                "dedup_status": "unique",
                "file_path": "",
            },
        ]
        mock_store = MagicMock()
        mock_store.list_entries.return_value = entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        )
        body = cast(str, result)
        # Issue #91 (R2): the entry renders its title, summary, source — but
        # the internal Field|Value metadata table (Tags/Relevance/Type/
        # Collected) is stripped from the user-facing product.
        assert "**Tags**" not in body
        assert "| 70.0/100" not in body
        assert "ai" in body
        assert "funding" in body
        assert "AI startup raises Series A" in body
        assert "**Source**: pubmed" in body


# ---------------------------------------------------------------------------
# Tests: MCP handler
# ---------------------------------------------------------------------------


class TestMcpHandler:
    """Tests the _handle_generate_digest MCP handler directly."""

    @pytest.fixture
    def kb_store_with_entries(self) -> Iterator[None]:
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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
    ) -> None:
        """Handler forwards the PRODUCT_TEMPLATES row for product to generate_digest."""
        from autoinfo.mcp.server import _handle_generate_digest
        from autoinfo.output import PRODUCT_TEMPLATES

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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
    ) -> None:
        """Unknown product returns the canonical error envelope with valid names."""
        from autoinfo.mcp.server import _handle_generate_digest
        from autoinfo.output import PRODUCT_TEMPLATES

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
        self, mock_logger: MagicMock, kb_store_with_entries: Iterator[None]
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


# ======================================================================
# #165: literal "(Source: X URL)" fake-source placeholder stripping
# #166: per-domain product relevance floor
# ======================================================================


class TestFakeSourcePlaceholderStrip:
    """``_strip_fake_source_placeholders`` removes literal non-URL source
    citations (issue #165)."""

    def test_strips_literal_x_url_placeholder(self) -> None:
        from autoinfo.output import _strip_fake_source_placeholders

        out = _strip_fake_source_placeholders(
            "**Actions:** Due diligence: ... (Source: TechCrunch URL)"
        )
        assert "TechCrunch URL" not in out
        assert "Due diligence" in out

    def test_preserves_real_url_and_markdown_link(self) -> None:
        from autoinfo.output import _strip_fake_source_placeholders

        url = "(Source: https://techcrunch.com/2026/08/31/ryan-breslow-/)"
        assert _strip_fake_source_placeholders(f"Keep {url}") == f"Keep {url}"
        md = "(Source: [TechCrunch](https://techcrunch.com/x))"
        assert _strip_fake_source_placeholders(md) == md


class TestProductRelevanceFloor:
    """``_filter_entries_by_domain_exclusions`` drops below-floor entries
    (issue #166)."""

    def test_below_floor_dropped_at_floor_and_absent_kept(self) -> None:
        from autoinfo.output import _filter_entries_by_domain_exclusions

        entries = [
            {"entry_id": "a", "title": "Horse hydration RCT", "relevance_score": 10,
             "domain": "medical-research"},
            {"entry_id": "b", "title": "IVF breakthrough", "relevance_score": 85,
             "domain": "medical-research"},
            {"entry_id": "c", "title": "Unscored curated", "domain": "medical-research"},
            {"entry_id": "d", "title": "Boundary", "relevance_score": 30,
             "domain": "medical-research"},
        ]
        kept = [e["entry_id"] for e in _filter_entries_by_domain_exclusions(
            entries, "medical-research"
        )]
        # medical-research seed floor is 30 -> below-floor 'a' dropped;
        # at-floor 'd', scored 'b', and absent-score 'c' (fail-open) kept.
        assert kept == ["b", "c", "d"], kept


# ======================================================================
# #178: synthesized multi-source digest entries excluded from products
# ======================================================================


class TestSynthesizedDigestExclusion:
    """A Draft/Wiki entry compiled from MULTIPLE raw sources is a production
    artifact — it must not surface in the product stream as a fake single
    news item (issue #178)."""

    def test_multi_source_draft_excluded_from_product_input(self) -> None:
        from autoinfo.output import _filter_product_entries

        synthesized = {
            "entry_id": "fin-draft-1", "title": "金融市场情报 4",
            "summary": "本期要点: ...", "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a", "raw-b"],
                              "source_raw_ids": "raw-a,raw-b"},
        }
        real = {
            "entry_id": "fin-news-1", "title": "Fed holds rates",
            "summary": "The Fed held rates steady.", "tier": "01-Raw",
        }
        kept = [e["entry_id"] for e in _filter_product_entries([synthesized, real])]
        assert kept == ["fin-news-1"], kept

    def test_single_source_draft_kept(self) -> None:
        from autoinfo.output import _filter_product_entries

        single = {
            "entry_id": "draft-1", "title": "A single compiled note",
            "summary": "From one source.", "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a"], "source_raw_ids": "raw-a"},
        }
        kept = [e["entry_id"] for e in _filter_product_entries([single])]
        assert kept == ["draft-1"], kept


# ======================================================================
# #184: single-source placeholder drafts excluded from products
# ======================================================================


class TestSingleSourcePlaceholderDraftExclusion:
    """A single-source Draft carrying digest-flag placeholder markers is still
    a synthesized digest artifact, not a news item — it must be excluded from
    the product stream even though it escapes the multi-source check (issue
    #184)."""

    @pytest.mark.parametrize("entry", [
        # truncated "本期...要点" summary placeholder
        {
            "entry_id": "ph-1", "title": "AI-commercial weekly: digest",
            "summary": "本期核心要点: 数字人民币联盟链交易量环比翻倍, 大模型",
            "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a"]},
        },
        # digest-flag title token ("weekly:", "weekly")
        {
            "entry_id": "ph-2", "title": "AI-commercial weekly: 本期周报",
            "summary": "Some normal summary text here.",
            "tier": "03-Wiki",
            "custom_fields": {"source_raw_ids": "raw-a"},
        },
        # template-name + digit title ("情报 4")
        {
            "entry_id": "ph-3", "title": "金融市场情报 4",
            "summary": "正常摘要文本。", "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a"]},
        },
        # template-name + digit title ("周报9" no space)
        {
            "entry_id": "ph-4", "title": "医疗前沿周报9",
            "summary": "Normal English summary.", "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a"]},
        },
    ])
    def test_single_source_placeholder_draft_excluded(self, entry) -> None:
        from autoinfo.output import _filter_product_entries, _is_synthesized_digest_entry

        assert _is_synthesized_digest_entry(entry) is True
        kept = [e["entry_id"] for e in _filter_product_entries([entry])]
        assert kept == [], kept

    @pytest.mark.parametrize("entry", [
        # real single-source news item
        {
            "entry_id": "news-1", "title": "Fed holds rates steady",
            "summary": "The Fed held rates steady at 5.25%.", "tier": "02-Draft",
            "custom_fields": {"source_ids": ["raw-a"]},
        },
        # real article whose title contains a number but NO template flag
        {
            "entry_id": "news-2", "title": "3 trends in AI for 2025",
            "summary": "Analysis of the top three AI trends.", "tier": "02-Draft",
            "custom_fields": {"source_id": "raw-a"},
        },
    ])
    def test_real_entries_not_misclassified(self, entry) -> None:
        from autoinfo.output import _filter_product_entries, _is_synthesized_digest_entry

        assert _is_synthesized_digest_entry(entry) is False
        kept = [e["entry_id"] for e in _filter_product_entries([entry])]
        assert kept == [entry["entry_id"]], kept


# ======================================================================
# #181: CJK leak warning (non-learning domains) / #182: currency split
# ======================================================================


class TestCjkLeakAndCurrencySplit:
    def test_cjk_leak_warns_for_non_learning_domain(self) -> None:
        from autoinfo.output import _warn_cjk_leak

        count = _warn_cjk_leak("financial-intelligence", "digest",
                               "本期要点中文内容1234567")
        assert count > 5

    def test_cjk_leak_exempts_english_learning(self) -> None:
        from autoinfo.output import _warn_cjk_leak

        assert _warn_cjk_leak("english-learning", "digest", "中文中文中文中文") == 0

    def test_currency_figure_not_split(self) -> None:
        from autoinfo.output import _split_summary_sentences

        bullets = _split_summary_sentences("VAST raised $8.5 billion. Second $1.1 billion fund.")
        assert bullets[0] == "VAST raised $8.5 billion"
        assert bullets[1] == "Second $1.1 billion fund"


# ======================================================================
# #200/#203: synthesis traceability (report+digest) and canonical RMB->USD
# annotation injected into the digest synthesis context
# ======================================================================


class TestSynthesisTraceabilityAndRmbUsd:
    def test_digest_prompt_carries_signal_traceability_constraint(self) -> None:
        from autoinfo.quality_constraints import (
            SYNTHESIS_SIGNAL_TRACEABILITY_CONSTRAINT,
        )

        prompt = _build_digest_llm_prompt(_SAMPLE_ENTRIES)
        assert SYNTHESIS_SIGNAL_TRACEABILITY_CONSTRAINT in prompt
        assert "low market breadth" in prompt

    def test_report_prompt_carries_signal_traceability_constraint(self) -> None:
        from autoinfo.output import _build_report_synthesis_prompt
        from autoinfo.quality_constraints import (
            SYNTHESIS_SIGNAL_TRACEABILITY_CONSTRAINT,
        )

        prompt = _build_report_synthesis_prompt("themes and entries here")
        assert SYNTHESIS_SIGNAL_TRACEABILITY_CONSTRAINT in prompt
        assert "low market breadth" in prompt

    def test_rmb_yi_to_usd_whole_millions(self) -> None:
        assert _annotate_rmb_usd("筹集30亿元", 7.0) == "筹集30亿元（≈$429M @7.0）"
        assert _annotate_rmb_usd("获得50亿元", 7.0) == "获得50亿元（≈$714M @7.0）"

    def test_digest_context_injects_canonical_usd_for_30yi(self) -> None:
        entry = {
            "entry_id": "va-1",
            "title": "VAST 完成30亿元融资",
            "language": "zh",
            "domain": "ai-commercial",
            "tier": "01-Raw",
            "source_url": "https://example.com/vast",
            "source_type": "api",
            "source_platform": "web",
            "collected_at": "2026-09-01",
            "summary": "该公司获得30亿元新一轮投资，用于扩大算力规模。",
            "tags": '["融资", "AI"]',
            "relevance_score": 90.0,
        }
        prompt = _build_digest_llm_prompt([entry], rmb_usd_rate=7.0)
        assert "≈$429M @7.0" in prompt

    def test_rmb_annotation_disabled_when_rate_zero(self) -> None:
        assert _annotate_rmb_usd("筹集30亿元", 0) == "筹集30亿元"
        assert _annotate_rmb_usd("筹集30亿元", None) == "筹集30亿元"
