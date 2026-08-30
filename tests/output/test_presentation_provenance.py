"""Presentation provenance tests (backup issues #93 and #101).

The LLM-generated presentation may cite fabricated internal sources
("KB: <title>", "KB-N", "knowledgebase.local", bare media/person names)
instead of real entry URLs.  The prompt now forbids fabrication and the
render-time sanitizer strips any non-URL citation from the markdown/html/
mkslides deck (agent JSON-LD untouched — its sources are real URLs).

Issue #101 backstop: a well-formed but fabricated URL (e.g.
"https://www.news.com/<slug>", "https://example.com/kb/N") passes the #93
shape check, so the prompt now feeds each entry's real ``source_url`` and
the sanitizer additionally cross-checks every rendered ``(Source: URL)``
against that real-URL whitelist.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from autoinfo.output import _sanitize_presentation_sources, generate_presentation

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


class TestSanitizePresentationSourcesWhitelist:
    """Issue #101 backstop: URL-shaped but fabricated placeholder sources.

    Without a whitelist the #93 shape pass lets any well-formed http(s) URL
    through.  With ``allowed_urls`` (the real KB source_url set), a citation
    whose URL is not verifiable against a real source is stripped — only the
    citation marker, never the bullet or the source mechanism itself.
    """

    _REAL_URLS = {
        "https://www.reuters.com/article/tech-1",
        "https://en.wikipedia.org/wiki/Hindi",
    }

    def test_strips_fabricated_placeholder_urls(self) -> None:
        for fake in (
            "(Source: https://www.news.com/hot-topic)",
            "(Source: https://example.com/kb/404)",
            "(Source: [details](https://www.news.com/hot-topic))",
        ):
            out = _sanitize_presentation_sources(fake, allowed_urls=self._REAL_URLS)
            assert fake not in out, f"placeholder source survived: {fake!r}"
            assert "news.com" not in out
            assert "example.com/kb" not in out

    def test_preserves_verifiable_real_urls(self) -> None:
        out = _sanitize_presentation_sources(
            "(Source: https://www.reuters.com/article/tech-1)",
            allowed_urls=self._REAL_URLS,
        )
        assert "(Source: https://www.reuters.com/article/tech-1)" in out

    def test_preserves_boundary_variants(self) -> None:
        # Trailing slash / query-suffix on the exact real URL: verifiable.
        out = _sanitize_presentation_sources(
            "(Source: https://www.reuters.com/article/tech-1/)"
            + " (Source: https://en.wikipedia.org/wiki/Hindi?section=1)",
            allowed_urls=self._REAL_URLS,
        )
        assert "reuters.com/article/tech-1" in out
        assert "wikipedia.org/wiki/Hindi" in out

    def test_preserves_host_root_of_real_domain(self) -> None:
        # A host-root prefix IS a verifiable substring of the real source_url
        # (acceptance criterion #1) — a real media domain, not a placeholder.
        out = _sanitize_presentation_sources(
            "(Source: https://www.reuters.com)",
            allowed_urls=self._REAL_URLS,
        )
        assert "https://www.reuters.com" in out

    def test_rejects_domain_lookalike(self) -> None:
        # A similar-looking but different host must NOT match: no path-separated
        # boundary joins it to a real source_url.
        for fake in (
            "(Source: https://www.reuters.com.evil/slug)",
            "(Source: https://reuters.community/x)",
            "(Source: https://www.news.com/hot-topic)",
        ):
            out = _sanitize_presentation_sources(fake, allowed_urls=self._REAL_URLS)
            assert "(Source:" not in out, f"lookalike source survived: {fake!r}"

    def test_no_whitelist_keeps_shape_valid_urls(self) -> None:
        # Backward-compatible default: without allowed_urls the #93 shape
        # pass is unchanged (digest/report/tutorial never pass a whitelist).
        out = _sanitize_presentation_sources("(Source: https://www.news.com/x)")
        assert "https://www.news.com/x" in out

    def test_bullet_survives_whitelist_strip(self) -> None:
        body = (
            "- Funding rounds accelerated. (Source: https://www.news.com/%s)"
            % "hot-topic"
        )
        cleaned = _sanitize_presentation_sources(body, allowed_urls=self._REAL_URLS)
        # The bullet text stays; only the fabricated citation marker is dropped.
        assert "Funding rounds accelerated." in cleaned
        assert "news.com" not in cleaned


def _write_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".autoinfo"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "project": {"name": "test"},
        "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
        "domains": [
            {
                "name": "ai-commercial",
                "active": True,
                "sources": [
                    {
                        "name": "techcrunch",
                        "type": "rss",
                        "url": "https://techcrunch.com/feed/",
                    }
                ],
                "topics": [],
            }
        ],
    }
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


_ENTRIES = [
    {
        "entry_id": "en-001",
        "title": "AI startup funding roundup",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://techcrunch.com/en/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "en",
        "collected_at": "2026-08-25",
        "summary": "AI startups raised record funding this week across seed and Series A rounds.",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 90.0,
    },
    {
        "entry_id": "en-002",
        "title": "Generative AI product launch",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://techcrunch.com/en/2",
        "source_type": "web",
        "source_platform": "web",
        "language": "en",
        "collected_at": "2026-08-25",
        "summary": "A new generative AI product launched with enterprise adoption momentum.",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 88.0,
    },
]


class TestPresentationPromptCarriesRealSources:
    """Issue #101 fix 1: the LLM prompt embeds each entry's real source_url.

    Prior to the fix, ``entry_summaries`` carried only title + summary — the
    LLM had no real URL to copy and fabricated placeholders.  Mirroring the
    tutorial/report pattern, every entry now ends with ``(Source: <url>)``.
    """

    def test_prompt_includes_real_source_url(self) -> None:
        captured: dict[str, Any] = {}

        def fake_llm(prompt: str, slide_count: int) -> dict[str, Any]:
            captured["prompt"] = prompt
            return _llm_result_with_fabricated_sources()

        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_kb_cls.return_value = _mock_store(_ENTRIES)
            with patch("autoinfo.output._call_llm_for_presentation", side_effect=fake_llm):
                generate_presentation(
                    domain="ai-commercial",
                    topic="AI",
                    format="markdown",
                    allow_empty=True,
                )

        prompt = captured["prompt"]
        assert "(Source: https://techcrunch.com/en/1)" in prompt
        assert "(Source: https://techcrunch.com/en/2)" in prompt

    def test_rendered_deck_strips_fabricated_placeholders(self) -> None:
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_kb_cls.return_value = _mock_store(_ENTRIES)
            mock_llm = MagicMock(
                return_value=_llm_result_with_fabricated_sources()
            )
            with patch("autoinfo.output._call_llm_for_presentation", mock_llm):
                body = str(
                    generate_presentation(
                        domain="ai-commercial",
                        topic="AI",
                        format="markdown",
                        allow_empty=True,
                    )
                )

        # Real, verifiable sources survive the render-time whitelist.
        assert "(Source: https://techcrunch.com/en/1)" in body
        assert "(Source: https://techcrunch.com/en/2)" in body
        # Fabricated placeholder URLs are gone — the acceptance scan is clean.
        for placeholder in ("news.com", "example.com/kb", "knowledgebase"):
            assert placeholder not in body, f"fabricated source leaked: {placeholder}"
        assert _ACCEPTANCE_RE.search(body) is None
        # Source mechanism is intact, not bulk-deleted.
        assert body.count("(Source: ") >= 2


def _mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


def _llm_result_with_fabricated_sources() -> dict[str, Any]:
    """LLM result mixing one real citation and two fabricated placeholders."""
    slides = [
        {
            "title": "Funding",
            "content": "Record funding rounds shaped the week.",
            "bullets": [
                "AI startups raised record funding. (Source: https://techcrunch.com/en/1)",
                "A hot rumor. (Source: https://www.news.com/hot-topic)",
                "An invented claim. (Source: https://example.com/kb/404)",
            ],
            "notes": None,
        },
        {
            "title": "Products",
            "content": "Generative AI adoption accelerated.",
            "bullets": [
                "A new product launched. (Source: https://techcrunch.com/en/2)",
                "Another false lead. (Source: [stats](https://www.news.com/stats))",
            ],
            "notes": None,
        },
    ]
    return {"title": "AI 2026", "description": "A deck.", "slides": slides}
