"""Presentation provenance tests (backup issue #93).

The LLM-generated presentation may cite fabricated internal sources
("KB: <title>", "KB-N", "knowledgebase.local", bare media/person names)
instead of real entry URLs.  The prompt now forbids fabrication and the
render-time sanitizer strips any non-URL citation from the markdown/html/
mkslides deck (agent JSON-LD untouched — its sources are real URLs).
"""

from __future__ import annotations

import re

from autoinfo.output import _sanitize_presentation_sources

_ACCEPTANCE_RE = re.compile(r"knowledgebase|KB-|Source: [A-Z][a-z]+$")


class TestSanitizePresentationSources:
    def test_strips_fabricated_sources(self) -> None:
        for fake in (
            "(Source: KB: Some Title)",
            "(Source: KB-N)",
            "(Source: knowledgebase.local/article)",
            "(Source: knowledgebase.example.com/x)",
            "(Source: Inside Higher Ed)",
            "(Source: Channels)",
            "(Source: EU Council)",
            "(Source: NASA)",
        ):
            assert _sanitize_presentation_sources(fake) == "", f"{fake} not stripped"

    def test_preserves_real_urls(self) -> None:
        out = _sanitize_presentation_sources(
            "(Source: https://www.wsj.com/articles/foo)"
        )
        assert "https://www.wsj.com" in out

    def test_preserves_markdown_links(self) -> None:
        out = _sanitize_presentation_sources(
            "(Source: [link](https://example.com))"
        )
        assert "example.com" in out

    def test_plain_text_unchanged(self) -> None:
        assert _sanitize_presentation_sources("A plain bullet") == "A plain bullet"

    def test_acceptance_scan_clean(self) -> None:
        body = (
            "Slide 1 (Source: KB: Title)\n"
            "Slide 2 (Source: knowledgebase.local/x)\n"
            "Slide 3 (Source: https://real.example.com/article)\n"
        )
        cleaned = _sanitize_presentation_sources(body)
        assert _ACCEPTANCE_RE.search(cleaned) is None
        assert "https://real.example.com/article" in cleaned
