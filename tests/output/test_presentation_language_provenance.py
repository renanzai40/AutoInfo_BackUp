"""Tests for presentation language filtering + source provenance (issue #15).

The presentation generator (``generate_presentation``) leaked #8 Chinese
financial noise (沪指 / 创业板 / A股 / 浙江数据集团) with ZERO source URLs in
the real ai-commercial deck (batch ai-verify-20260825, audit noSrc=21) because:

1. It never applied the effective-language filter that digest/report apply
   (issue #309/#317) — zh entries flowed into ``topic_entries`` and the
   KB-derived fallback slides.
2. ``_fallback_slides_from_entries`` built slide dicts with no ``source_url``,
   so even the deterministic path shipped 0 provenance.

These tests lock:
  1. effective-language filtering on the presentation path (zh entries dropped
     before synthesis/fallback),
  2. ``source_url`` provenance on every KB-derived fallback slide,
  3. the exclude_keywords guard (issue #319) still applies on the fallback path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from autoinfo.output import DeliveryOutput, generate_presentation


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


def _write_config(tmp_path: Path, default_language: str = "en") -> None:
    """Write a minimal project config with an ai-commercial domain.

    Declares ``default_language`` explicitly so ``_resolve_effective_language``
    resolves deterministically regardless of the host environment (no reliance
    on the seed fallback).
    """
    cfg_dir = tmp_path / ".autoinfo"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "project": {"name": "test"},
        "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
        "domains": [
            {
                "name": "ai-commercial",
                "active": True,
                "default_language": default_language,
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


# Mixed zh-finance / en-AI entries for ai-commercial.  The zh entries carry the
# exact #8 noise (沪指/创业板/A股/浙江数据集团) AND mention "AI" in their
# summary so they match the topic filter and leak into ``topic_entries``
# pre-fix — the real leak surface.
_MIXED_ENTRIES = [
    {
        "entry_id": "zh-001",
        "title": "沪指早盘走低 创业板翻红",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://finance.example.com/zh/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "zh",
        "collected_at": "2026-08-25",
        "summary": "AI概念股带动A股市场早盘波动 沪指小幅下跌 创业板翻红 锂矿稀土黄金股走强",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    },
    {
        "entry_id": "zh-002",
        "title": "浙江数据集团：中国数据基础设施布局",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://finance.example.com/zh/2",
        "source_type": "web",
        "source_platform": "web",
        "language": "zh",
        "collected_at": "2026-08-25",
        "summary": "AI数据基础设施 注册资本20亿元 数据要素市场布局",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 75.0,
    },
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


def _mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


class TestPresentationLanguageFilter:
    """Issue #15: zh finance noise must be filtered before synthesis/fallback."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_presentation_applies_effective_language(
        self,
        mock_llm: MagicMock,
        mock_kb_store: MagicMock,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        # Force the KB-derived fallback: LLM returns no slides, so
        # _fallback_slides_from_entries builds slides from topic_entries.
        # Pre-fix those entries are UNFILTERED by language — the zh finance
        # noise leaks into the rendered deck.
        mock_llm.return_value = {"title": "AI", "description": "", "slides": []}
        mock_kb_store.return_value = _mock_store(_MIXED_ENTRIES)
        _write_config(tmp_path, default_language="en")
        monkeypatch.chdir(tmp_path)

        body = _as_text(generate_presentation(
            domain="ai-commercial", topic="AI", format="markdown",
            allow_empty=True,
        ))

        # zh finance noise must never reach the rendered deck.
        assert "沪指" not in body
        assert "创业板" not in body
        assert "A股" not in body
        assert "浙江数据集团" not in body
        # en entries survive the filter.
        assert "AI startup funding roundup" in body
        assert "Generative AI product launch" in body


class TestPresentationSourceProvenance:
    """Issue #15: KB-derived fallback slides must carry their entry source_url."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_presentation_slides_carry_source_url(
        self,
        mock_llm: MagicMock,
        mock_kb_store: MagicMock,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        mock_llm.return_value = {"title": "AI", "description": "", "slides": []}
        mock_kb_store.return_value = _mock_store(_MIXED_ENTRIES)
        _write_config(tmp_path, default_language="en")
        monkeypatch.chdir(tmp_path)

        body = _as_text(generate_presentation(
            domain="ai-commercial", topic="AI", format="markdown",
            allow_empty=True,
        ))

        # Every KB-derived slide must render its entry's source_url.
        assert "(Source: https://techcrunch.com/en/1)" in body
        assert "(Source: https://techcrunch.com/en/2)" in body


class TestPresentationExcludeKeywordsFallback:
    """Issue #319 guard: exclude_keywords still applies on the fallback path."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_presentation_exclude_keywords_still_applied_on_fallback(
        self,
        mock_llm: MagicMock,
        mock_kb_store: MagicMock,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        # The noise entry matches the topic ("AI" in summary) so WITHOUT the
        # exclude_keywords guard it would leak into the KB-derived fallback.
        entries = [
            {
                "entry_id": "noise-001",
                "title": "贝达药业 肺癌新药获批",
                "domain": "ai-commercial",
                "tier": "01-Raw",
                "source_url": "https://example.com/noise",
                "source_type": "web",
                "source_platform": "web",
                "language": "zh",
                "collected_at": "2026-08-25",
                "summary": "贝达药业 AI医药概念 新药上市 医药板块",
                "tags": "[]",
                "quality_tier": 1,
                "relevance_score": 70.0,
            },
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
                "summary": "AI startups raised record funding this week.",
                "tags": "[]",
                "quality_tier": 1,
                "relevance_score": 90.0,
            },
        ]
        mock_llm.return_value = {"title": "AI", "description": "", "slides": []}
        mock_kb_store.return_value = _mock_store(entries)
        _write_config(tmp_path, default_language="en")
        monkeypatch.chdir(tmp_path)

        body = _as_text(generate_presentation(
            domain="ai-commercial", topic="AI", format="markdown",
            allow_empty=True,
        ))

        assert "贝达药业" not in body
        assert "AI startup funding roundup" in body
