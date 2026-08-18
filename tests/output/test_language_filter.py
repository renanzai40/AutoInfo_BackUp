"""Tests for the entry-language filter (issue #309).

A ``language`` parameter on ``generate_digest`` / ``generate_report`` (and the
matching MCP tools) keeps a product internally consistent by dropping entries
whose detected ``language`` doesn't match — no zh/en interleave.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    DeliveryOutput,
    _filter_entries_by_language,
    _normalize_lang,
    generate_digest,
    generate_report,
)


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)

# ---------------------------------------------------------------------------
# _normalize_lang / _filter_entries_by_language
# ---------------------------------------------------------------------------


class TestNormalizeLang:
    def test_iso_codes(self) -> None:
        assert _normalize_lang("zh") == "zh"
        assert _normalize_lang("en") == "en"
        assert _normalize_lang("ja") == "ja"

    def test_region_suffixed(self) -> None:
        assert _normalize_lang("zh_CN") == "zh"
        assert _normalize_lang("zh-CN") == "zh"
        assert _normalize_lang("en-US") == "en"
        assert _normalize_lang("en-GB") == "en"

    def test_aliases(self) -> None:
        assert _normalize_lang("中文") == "zh"
        assert _normalize_lang("chinese") == "zh"
        assert _normalize_lang("english") == "en"
        assert _normalize_lang("cn") == "zh"

    def test_empty(self) -> None:
        assert _normalize_lang("") == ""
        assert _normalize_lang(" ") == ""


class TestFilterEntriesByLanguage:
    def _entry(self, lang: str) -> dict[str, Any]:
        return {"language": lang, "title": f"item-{lang}"}

    def test_empty_filter_returns_all(self) -> None:
        entries = [self._entry("zh"), self._entry("en")]
        assert _filter_entries_by_language(entries, "") == entries

    def test_filters_to_matching_language(self) -> None:
        entries = [self._entry("zh"), self._entry("en"), self._entry("zh-hans")]
        kept = _filter_entries_by_language(entries, "zh")
        assert [e["title"] for e in kept] == ["item-zh", "item-zh-hans"]

    def test_drops_unknown_language_when_filter_active(self) -> None:
        entries = [self._entry("", ), {"language": None, "title": "none"}, self._entry("en")]
        kept = _filter_entries_by_language(entries, "en")
        assert [e["title"] for e in kept] == ["item-en"]

    def test_alias_matching(self) -> None:
        entries = [self._entry("zh_CN"), self._entry("en-US")]
        kept = _filter_entries_by_language(entries, "zh")
        assert [e["title"] for e in kept] == ["item-zh_CN"]


# ---------------------------------------------------------------------------
# End-to-end: generate_digest with language filter
# ---------------------------------------------------------------------------


def _digest_mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


_ZHRISH_ENTRIES = [
    {
        "entry_id": "zh-001",
        "title": "中文 IVF 突破",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://36kr.com/zh/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "zh",
        "collected_at": "2026-08-17",
        "summary": "中文摘要内容",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    },
    {
        "entry_id": "en-001",
        "title": "English IVF breakthrough",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://techcrunch.com/en/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "en",
        "collected_at": "2026-08-17",
        "summary": "English summary content",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 85.0,
    },
]


class TestDigestLanguageFilter:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_zh_filter_keeps_only_zh_entries(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb_store.return_value = _digest_mock_store(_ZHRISH_ENTRIES)
        body = _as_text(generate_digest(
            domain="medical-research", period="weekly", format="markdown",
            language="zh",
        ))
        # The zh entry is retained; the en summary/content is not rendered.
        assert "中文 IVF 突破" in body
        assert "English IVF breakthrough" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_no_language_includes_both(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb_store.return_value = _digest_mock_store(_ZHRISH_ENTRIES)
        body = _as_text(generate_digest(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert "中文 IVF 突破" in body
        assert "English IVF breakthrough" in body


class TestReportLanguageFilter:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_zh_filter(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_kb.return_value = _digest_mock_store(_ZHRISH_ENTRIES)
        mock_group.return_value = []
        mock_synthesis.return_value = "Overview."
        body = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown",
            language="zh",
        ))
        assert "中文 IVF 突破" in body
        assert "English IVF breakthrough" not in body
