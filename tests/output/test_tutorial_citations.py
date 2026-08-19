"""Tests for issue #312: tutorial body inline citations.

Tutorial bodies must carry inline citations to the real ``source_url`` of
the KB entries they synthesize — aligned with the digest/report citation
mechanism.  Three layers are locked:

1. The entry-summary lines fed to the LLM carry ``(Source: <source_url>)``.
2. The generation prompts instruct the model to cite sources inline.
3. A rendered tutorial preserves citations emitted by the model.

TDD: these tests fail (RED) on main, pass (GREEN) after the #312 fix.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import _build_tutorial_markdown_prompt, generate_tutorial

_ENTRY: dict[str, Any] = {
    "entry_id": "pmid-12345678",
    "title": "Time-lapse imaging improves IVF outcomes",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "source_type": "api",
    "source_platform": "pubmed",
    "summary": "Time-lapse imaging improves live birth rates (48.2% vs 39.5%).",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 92.0,
}

_COMPLETE_TUTORIAL: dict[str, Any] = {
    "title": "IVF Imaging — Tutorial",
    "duration": "30 minutes",
    "prerequisites": "None",
    "objectives": ["Understand time-lapse imaging."],
    "content": [
        {
            "heading": "Time-lapse Imaging",
            "body": (
                "Time-lapse imaging improves live birth rates. "
                "(Source: https://pubmed.ncbi.nlm.nih.gov/12345678/)"
            ),
            "code_example": None,
            "code_language": None,
            "key_takeaway": "Better outcomes with time-lapse.",
        }
    ],
    "exercises": [
        {"title": "Key finding", "description": "Summarize the main finding."}
    ],
    "summary": "Time-lapse imaging improves IVF outcomes.",
    "further_reading": ["https://pubmed.ncbi.nlm.nih.gov/12345678/"],
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return [_ENTRY]


class TestTutorialPromptContainsSourceUrls:
    """generate_tutorial must feed (Source: <url>) into the LLM prompt."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_tutorial_prompt_contains_source_urls(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = dict(_COMPLETE_TUTORIAL)
        captured: dict[str, str] = {}

        def _capture(prompt: str) -> dict[str, Any]:
            captured["prompt"] = prompt
            return dict(_COMPLETE_TUTORIAL)

        mock_llm.side_effect = _capture
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        generate_tutorial(domain="medical-research", format="markdown")

        assert captured, "LLM prompt was never captured"
        assert "https://pubmed.ncbi.nlm.nih.gov/12345678/" in captured["prompt"]


class TestTutorialMarkdownPromptInstructsCitations:
    """The markdown generation prompt must instruct inline citations."""

    def test_tutorial_markdown_prompt_instructs_citations(self) -> None:
        prompt = _build_tutorial_markdown_prompt(
            "student",
            "a general audience",
            "[e1] T: S (Source: https://x)",
            "",
        )
        assert "(Source:" in prompt
        assert "cite" in prompt.lower()


class TestTutorialRendersInlineCitations:
    """A model-emitted citation must survive rendering."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_tutorial_renders_inline_citations(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = dict(_COMPLETE_TUTORIAL)
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_tutorial(domain="medical-research", format="markdown")

        assert isinstance(result, str)
        assert "https://pubmed.ncbi.nlm.nih.gov/12345678/" in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_tutorial_fallback_content_carries_citations(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Entry-derived fallback bodies must carry (Source: <url>).

        When the LLM result is unusable, ``_ensure_tutorial_complete`` fills
        content bodies from KB entries — those bodies must cite their
        source URL.
        """
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_tutorial(domain="medical-research", format="markdown")

        assert isinstance(result, str)
        assert "(Source: https://pubmed.ncbi.nlm.nih.gov/12345678/)" in result
