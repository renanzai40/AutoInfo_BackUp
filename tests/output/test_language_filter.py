"""Tests for the entry-language filter (issue #309).

A ``language`` parameter on ``generate_digest`` / ``generate_report`` (and the
matching MCP tools) keeps a product internally consistent by dropping entries
whose detected ``language`` doesn't match — no zh/en interleave.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    DeliveryOutput,
    _filter_entries_by_language,
    _normalize_lang,
    _resolve_effective_language,
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


# ai-commercial today: 6 zh-cn + 1 vi entries, ZERO en (issue #8) — the "en"
# seed filter drops every one of them.
_ZH_ONLY_ENTRIES = [
    {
        "entry_id": "zh-002",
        "title": "中文 AI 融资报道",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://36kr.com/zh/2",
        "source_type": "web",
        "source_platform": "web",
        "language": "zh",
        "collected_at": "2026-08-17",
        "summary": "中文摘要内容",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 82.0,
    },
    {
        "entry_id": "vi-001",
        "title": "Báo cáo AI thương mại",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://example.com/vi/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "vi",
        "collected_at": "2026-08-17",
        "summary": "Tóm tắt tiếng Việt",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 78.0,
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
            domain="language-learning", period="weekly", format="markdown"
        ))
        assert "中文 IVF 突破" in body
        assert "English IVF breakthrough" in body


class TestDigestLanguageWindowFallback:
    """A domain whose default-language corpus is fully out-of-window while
    the period window holds entries in other languages must relax the DATE
    window (keeping the language filter) instead of rendering an empty shell
    (backup-repo #28 evidence run: general-news zh corpus dated 2025-06,
    fresh en in-window)."""

    def _entry(self, eid: str, lang: str, title: str, collected_at: str) -> dict[str, Any]:
        return {
            "entry_id": eid,
            "title": title,
            "domain": "general-news",
            "tier": "01-Raw",
            "source_url": f"https://example.com/{eid}",
            "source_type": "rss",
            "source_platform": "rss",
            "language": lang,
            "collected_at": collected_at,
            "summary": f"summary-{eid}",
            "tags": "[]",
            "quality_tier": 1,
            "relevance_score": 80.0,
        }

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_zh_filter_emptied_by_window_relaxes_date_keeps_language(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock
    ) -> None:
        """In-window en entries + out-of-window zh corpus on a zh domain.

        The period query returns the en entries (blocking the existing
        no-window fallback), the zh filter empties them — the digest must
        relax the date window and render the zh corpus, never an empty shell.
        """
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        en_in_window = self._entry("en-1", "en", "English world news", "2026-08-25T00:00:00+00:00")
        zh_out_of_window = self._entry("zh-1", "zh", "中文综合新闻", "2025-06-05T00:00:00+00:00")

        store = MagicMock()

        def _list_entries(**kwargs: Any) -> list[dict[str, Any]]:
            if "date_from" in kwargs:
                return [en_in_window]
            return [zh_out_of_window]

        store.list_entries.side_effect = _list_entries
        mock_kb_store.return_value = store

        body = _as_text(generate_digest(
            domain="general-news", period="weekly", format="markdown",
            language="zh", include_stale=True,
        ))
        assert "中文综合新闻" in body, "out-of-window zh entry must render via the relaxed window"
        assert "English world news" not in body, "language filter must stay active"

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_period_empty_fallback_still_respects_language(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock
    ) -> None:
        """The pre-existing no-window fallback keeps filtering by language too."""
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        en_entry = self._entry("en-2", "en", "English other", "2026-08-25T00:00:00+00:00")
        zh_entry = self._entry("zh-2", "zh", "中文另一条", "2025-06-05T00:00:00+00:00")

        store = MagicMock()

        def _list_entries(**kwargs: Any) -> list[dict[str, Any]]:
            if "date_from" in kwargs:
                return []
            return [en_entry, zh_entry]

        store.list_entries.side_effect = _list_entries
        mock_kb_store.return_value = store

        body = _as_text(generate_digest(
            domain="general-news", period="weekly", format="markdown",
            language="zh", include_stale=True,
        ))
        assert "中文另一条" in body
        assert "English other" not in body


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


# ---------------------------------------------------------------------------
# Seed fallback for _resolve_effective_language (issue #8)
# ---------------------------------------------------------------------------
# A project config that EXISTS and declares the ai-commercial domain WITHOUT
# a ``default_language`` key must seed "en" (from the demo-domain sources.yaml
# at line 8).  The seed fallback mirrors the #319 exclude_keywords pattern and
# engages ONLY when a config file exists but the domain block lacks the key;
# a project with NO config file stays ``""`` (no filtering, backward
# compatible).


def _write_tmp_config(tmp_path: Path, domain_block: str) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"domains:\n{domain_block}", encoding="utf-8")
    return cfg_path


class TestResolveEffectiveLanguageSeed:
    # --- (a) DISCRIMINATING case: config-present, key-absent -> seed ---------
    def test_config_present_key_absent_uses_seed(self, tmp_path: Path) -> None:
        cfg_path = _write_tmp_config(
            tmp_path, "  - name: ai-commercial\n    active: true\n"
        )
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            assert _resolve_effective_language("", "ai-commercial") == "en"

    # --- (b) explicit-empty wins over the seed -------------------------------
    def test_explicit_empty_language_wins_over_seed(self, tmp_path: Path) -> None:
        cfg_path = _write_tmp_config(
            tmp_path,
            "  - name: ai-commercial\n    default_language: \"\"\n    active: true\n",
        )
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            assert _resolve_effective_language("", "ai-commercial") == ""

    # --- (c) explicit zh wins ------------------------------------------------
    def test_explicit_zh_wins(self, tmp_path: Path) -> None:
        cfg_path = _write_tmp_config(
            tmp_path,
            "  - name: ai-commercial\n    default_language: zh\n    active: true\n",
        )
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            assert _resolve_effective_language("", "ai-commercial") == "zh"

    # --- (d) cross-domain returns "" before any config/seed read -------------
    def test_cross_domain_never_seeds(self, tmp_path: Path) -> None:
        cfg_path = _write_tmp_config(
            tmp_path, "  - name: ai-commercial\n    active: true\n"
        )
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            assert (
                _resolve_effective_language("", "ai-commercial", cross_domain=True)
                == ""
            )

    # --- (e) no config file at all -> "" (no seeding on a missing config) ----
    def test_no_config_file_returns_empty(self) -> None:
        with patch("autoinfo.output.get_config_path", return_value=None):
            assert _resolve_effective_language("", "ai-commercial") == ""

    # --- (f) unknown domain, config present, key absent -> no seed -----------
    def test_unknown_domain_no_seed(self, tmp_path: Path) -> None:
        cfg_path = _write_tmp_config(
            tmp_path, "  - name: ai-commercial\n    active: true\n"
        )
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            assert _resolve_effective_language("", "unknown-domain") == ""


# ---------------------------------------------------------------------------
# ai-commercial empty-after-filter enforcement (issue #8)
# ---------------------------------------------------------------------------
# INTENDED enforcement decision: the ai-commercial domain on the current KB
# (6 zh-cn + 1 vi entries, zero en) will come out EMPTY once the "en" seed
# filter engages — this is single-language enforcement per the issue's own
# acceptance, NOT a regression.  Two pinned behaviors:
#   1. Unit: _filter_entries_by_language(zh_entries, "en") == [].
#   2. Full-path generate_report with zero kept entries:
#      - WITHOUT delivery_gate_configs (the CLI/MCP default): the
#        ``if not entries`` branch returns the empty-shell STRING — the
#        _apply_min_content_guard call sits inside the
#        ``delivery_gate_configs is not None`` conditional, so it is skipped
#        and the rendered empty shell is returned.
#      - WITH delivery_gate_configs={"D1": {"action": "block"}}: the
#        DeliveryOutput path runs _apply_min_content_guard, which sets
#        delivery_blocked=True (0 usable entries for a PROCESSED product).
# Both _group_by_theme and _generate_executive_summary are stubbed so no live
# LLM call ever happens (the D1 gate is a deterministic completeness check and
# the product judge is skipped once the min-content guard blocks, and fails
# open without an LLM key anyway).


class TestAiCommercialEmptyAfterFilter:
    def test_zh_entries_filtered_by_en_seed_are_dropped(self) -> None:
        zh_only_entries = [
            {"language": "zh", "title": "中文条目"},
            {"language": "zh-cn", "title": "另一中文条目"},
            {"language": "vi", "title": "tiếng Việt"},
        ]
        assert _filter_entries_by_language(zh_only_entries, "en") == []

    # --- Full-path blocked behavior (delivery_gate_configs passed) ----------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_full_path_zero_kept_with_gates_blocks(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock,
        tmp_path: Path,
    ) -> None:
        # zh/vi-only KB (zero en) + a config file that EXISTS and declares
        # ai-commercial WITHOUT a default_language key: the seed "en" filter
        # drops every entry, so the empty-entries branch runs.  With gates
        # passed, _apply_min_content_guard forces delivery_blocked=True.
        cfg_path = _write_tmp_config(
            tmp_path, "  - name: ai-commercial\n    active: true\n"
        )
        mock_kb.return_value = _digest_mock_store(_ZH_ONLY_ENTRIES)
        mock_group.return_value = []
        mock_synthesis.return_value = "Overview."
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            result = generate_report(
                domain="ai-commercial",
                period="weekly",
                format="markdown",
                delivery_gate_configs={"D1": {"action": "block"}},
            )
        assert isinstance(result, DeliveryOutput)
        assert result.delivery_blocked is True
        assert any("min-content guard" in w for w in result.warnings)

    # --- Full-path empty-shell behavior (no gates — CLI/MCP default) --------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_full_path_zero_kept_no_gates_returns_empty_shell(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Same seed-en scenario, but WITHOUT delivery_gate_configs (the CLI/MCP
        # default): the empty-entries branch returns the rendered empty-shell
        # string — _apply_min_content_guard is only invoked when gates are
        # passed (the guard call sits inside the ``delivery_gate_configs is
        # not None`` conditional in generate_report).
        cfg_path = _write_tmp_config(
            tmp_path, "  - name: ai-commercial\n    active: true\n"
        )
        mock_kb.return_value = _digest_mock_store(_ZH_ONLY_ENTRIES)
        mock_group.return_value = []
        mock_synthesis.return_value = "Overview."
        with patch("autoinfo.output.get_config_path", return_value=cfg_path):
            body = generate_report(
                domain="ai-commercial",
                period="weekly",
                format="markdown",
            )
        assert isinstance(body, str)
        assert "This edition has no curated items yet." in body
        assert "中文" not in body
        assert "Overview." not in body
