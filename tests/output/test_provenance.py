"""Issue #279 (first half — provenance/trust): per-finding source citations.

Digest/report synthesis prompts used to pass only Title/Summary/Tags per
entry to the LLM (no ``source_url``), and rendered output cited nothing
per-finding — only a global References bibliography — so claims like
"EA $55B" were untraceable.  This locks the fix:

- ``_build_digest_llm_prompt`` threads each entry's ``source_url`` into
  the prompt and instructs the LLM to cite sources inline.
- ``_build_report_entries_detail`` / ``_build_report_synthesis_prompt``
  do the same for the report path.
- ``_deterministic_synthesis_fallback`` produces ``{"text", "source_url"}``
  finding objects when the entry carries a URL.
- Rendered Markdown cites each finding as ``(Source: URL)`` when the
  finding carries a ``source_url`` — and never emits ``(Source: —)`` junk
  for entries without one.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    _build_digest_llm_prompt,
    _build_report_entries_detail,
    _build_report_synthesis_prompt,
    _deterministic_synthesis_fallback,
    generate_digest,
)

_ENTRY: dict[str, Any] = {
    "entry_id": "entry-001",
    "title": "Acme raises $55B for EA expansion",
    "summary": "Acme announced a $55B capital raise for EA expansion.",
    "source_url": "https://x.com/a",
    "source_type": "api",
    "source_platform": "pubmed",
    "domain": "medical-research",
    "relevance_score": 92.0,
    "tags": '["EA", "funding"]',
    "tier": "01-Raw",
    "collected_at": "2026-08-01T10:00:00Z",
}


# ---------------------------------------------------------------------------
# (a) digest prompt threads the entry source_url
# ---------------------------------------------------------------------------


class TestDigestPromptSourceUrl:
    def test_prompt_contains_source_url_line(self) -> None:
        """Each entry block carries a ``Source URL:`` line."""
        prompt = _build_digest_llm_prompt(
            [
                {
                    "title": "T",
                    "summary": "S",
                    "tags": "[]",
                    "source_url": "https://x.com/a",
                }
            ]
        )
        assert "Source URL: https://x.com/a" in prompt

    def test_prompt_omits_url_line_value_when_entry_has_none(self) -> None:
        """Entries without a source_url render the em-dash placeholder."""
        prompt = _build_digest_llm_prompt(
            [{"title": "T", "summary": "S", "tags": "[]"}]
        )
        assert "Source URL: \u2014" in prompt

    def test_prompt_instructs_inline_citation(self) -> None:
        """The closing instructions ask the LLM to cite sources inline."""
        prompt = _build_digest_llm_prompt([_ENTRY])
        assert "cite its source inline as (Source: URL)" in prompt


# ---------------------------------------------------------------------------
# (b) report synthesis prompt threads the entry source_url
# ---------------------------------------------------------------------------


class TestReportPromptSourceUrl:
    def _detail(self) -> str:
        return _build_report_entries_detail(
            [_ENTRY],
            [{"theme": "Finance", "description": "d", "entries": [_ENTRY]}],
        )

    def test_entries_detail_contains_source_url(self) -> None:
        detail = self._detail()
        assert "https://x.com/a" in detail
        assert "Source: https://x.com/a" in detail

    def test_prompt_contains_url_and_cite_instruction(self) -> None:
        prompt = _build_report_synthesis_prompt(self._detail())
        assert "https://x.com/a" in prompt
        assert "cite its source inline as (Source: URL)" in prompt


# ---------------------------------------------------------------------------
# (c) deterministic fallback findings carry {text, source_url}
# ---------------------------------------------------------------------------


class TestDeterministicFallbackProvenance:
    def test_findings_are_text_source_url_objects(self) -> None:
        """Entries with a source_url yield ``{text, source_url}`` findings."""
        result = _deterministic_synthesis_fallback([_ENTRY])
        assert result["key_findings"] == [
            {"text": "Acme raises $55B for EA expansion: Acme announced a "
                     "$55B capital raise for EA expansion.",
             "source_url": "https://x.com/a"}
        ]

    def test_entry_without_url_keeps_legacy_string_finding(self) -> None:
        """No source_url -> plain ``title: summary`` string (unchanged)."""
        no_url = {k: v for k, v in _ENTRY.items() if k != "source_url"}
        result = _deterministic_synthesis_fallback([no_url])
        assert result["key_findings"] == [
            "Acme raises $55B for EA expansion: Acme announced a "
            "$55B capital raise for EA expansion."
        ]


# ---------------------------------------------------------------------------
# (d) rendered digest cites the finding's source inline
# ---------------------------------------------------------------------------


class TestRenderedDigestCitation:
    def test_markdown_digest_renders_source_citation(self) -> None:
        """LLM findings with a source_url render ``(Source: URL)`` in the
        Key Findings section; text stays ``**topic**: detail``."""
        llm_synthesis: dict[str, Any] = {
            "executive_summary": "Executive summary.",
            "key_findings": [
                {
                    "topic": "t",
                    "detail": "d",
                    "source_url": "https://x.com/a",
                }
            ],
            "recommendations": ["r"],
        }
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
        ):
            mock_llm.return_value = llm_synthesis
            mock_store = MagicMock()
            mock_store.list_entries.return_value = [_ENTRY]
            mock_kb_cls.return_value = mock_store

            result = generate_digest(domain="medical-research", period="weekly")

        rendered = cast(str, result)
        assert "### Key Findings" in rendered
        assert "- **t**: d (Source: https://x.com/a)" in rendered

    def test_markdown_digest_omits_citation_without_url(self) -> None:
        """Findings without a source_url render exactly as before — no
        ``(Source: —)`` junk."""
        llm_synthesis: dict[str, Any] = {
            "executive_summary": "Executive summary.",
            "key_findings": [{"topic": "t", "detail": "d"}],
            "recommendations": ["r"],
        }
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
        ):
            mock_llm.return_value = llm_synthesis
            mock_store = MagicMock()
            mock_store.list_entries.return_value = [_ENTRY]
            mock_kb_cls.return_value = mock_store

            result = generate_digest(domain="medical-research", period="weekly")

        rendered = cast(str, result)
        assert "- **t**: d" in rendered
        assert "(Source:" not in rendered
