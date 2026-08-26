"""Tests for the domain-level default language (issue #317).

A domain may declare a ``default_language`` so products for mixed-language
domains (e.g. ai-commercial: 36KR zh + TechCrunch/ProductHunt/Crunchbase en)
come out single-language without an explicit ``language`` param.

Resolution precedence (``_resolve_effective_language``):
1. explicit ``language`` param wins;
2. else the domain's configured ``default_language``;
3. else ``""`` (no filter — legacy behavior).

Cross-domain products never silently pick one domain's default: an explicit
param wins, otherwise no filtering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.config import DomainConfig, config_to_dict, load_config
from autoinfo.output import (
    DeliveryOutput,
    _resolve_effective_language,
    generate_digest,
    generate_report,
)


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


def _write_config(tmp_path: Path, domains: list[dict[str, Any]]) -> None:
    """Write a project config with the given domains under ``tmp_path``."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "project": {"name": "Test Project", "created_at": "2026-08-19"},
        "llm": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat",
            "api_key": "test-key",
        },
        "domains": domains,
    }
    with open(config_dir / "config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False)


def _ai_commercial_domain(default_language: str = "en") -> dict[str, Any]:
    return {
        "name": "ai-commercial",
        "active": True,
        "default_language": default_language,
        "sources": [
            {"name": "techcrunch", "type": "rss", "url": "https://techcrunch.com/feed/"},
            {"name": "36kr", "type": "rss", "url": "https://www.36kr.com/feed"},
        ],
    }


def _plain_domain(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "active": True,
        "sources": [
            {"name": "pubmed", "type": "api", "url": "https://eutils.ncbi.nlm.nih.gov/"},
        ],
    }


# Mixed zh/en entries for the ai-commercial domain (36KR zh + EN sources).
_MIXED_ENTRIES = [
    {
        "entry_id": "zh-001",
        "title": "中文 AI 融资动态",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://36kr.com/zh/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "zh",
        "collected_at": "2026-08-19",
        "summary": "中文摘要内容",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    },
    {
        "entry_id": "en-001",
        "title": "English AI funding round",
        "domain": "ai-commercial",
        "tier": "01-Raw",
        "source_url": "https://techcrunch.com/en/1",
        "source_type": "web",
        "source_platform": "web",
        "language": "en",
        "collected_at": "2026-08-19",
        "summary": "English summary content",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 85.0,
    },
]


def _digest_mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


# ---------------------------------------------------------------------------
# _resolve_effective_language
# ---------------------------------------------------------------------------


class TestResolveEffectiveLanguage:
    def test_explicit_param_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        assert _resolve_effective_language("zh", "ai-commercial") == "zh"

    def test_domain_default_when_param_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        assert _resolve_effective_language("", "ai-commercial") == "en"

    def test_empty_when_no_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # language-learning's demo seed declares NO default_language, so the
        # seed fallback finds nothing and the result stays "" (medical-research
        # has gained a seed default_language: en since the #19 fine-tune).
        _write_config(tmp_path, [_plain_domain("language-learning")])
        monkeypatch.chdir(tmp_path)
        assert _resolve_effective_language("", "language-learning") == ""

    def test_empty_when_cross_domain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_config(
            tmp_path,
            [_ai_commercial_domain(), _plain_domain("medical-research")],
        )
        monkeypatch.chdir(tmp_path)
        # Never silently pick one domain's default across multiple domains.
        assert _resolve_effective_language("", "ai-commercial", cross_domain=True) == ""

    def test_empty_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)  # no .autoinfo/config.yaml present
        assert _resolve_effective_language("", "ai-commercial") == ""


# ---------------------------------------------------------------------------
# DomainConfig model: parse + persist default_language
# ---------------------------------------------------------------------------


class TestDomainConfigDefaultLanguage:
    def test_parses_default_language(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        config = load_config(tmp_path / ".autoinfo" / "config.yaml")
        domain = next(d for d in config.domains if d.name == "ai-commercial")
        assert domain.default_language == "en"

    def test_defaults_to_empty(self) -> None:
        assert DomainConfig(name="medical-research").default_language == ""

    def test_persists_when_set(self) -> None:
        from autoinfo.config import Config

        cfg = DomainConfig(name="ai-commercial", default_language="en")
        config = Config(domains=[cfg])
        raw = config_to_dict(config)
        domain_raw = next(d for d in raw["domains"] if d["name"] == "ai-commercial")
        assert domain_raw["default_language"] == "en"

    def test_omits_when_empty(self) -> None:
        from autoinfo.config import Config

        cfg = DomainConfig(name="medical-research")
        config = Config(domains=[cfg])
        raw = config_to_dict(config)
        domain_raw = next(d for d in raw["domains"] if d["name"] == "medical-research")
        assert "default_language" not in domain_raw


# ---------------------------------------------------------------------------
# End-to-end: generate_digest applies the domain default
# ---------------------------------------------------------------------------


class TestDigestDomainDefault:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_domain_default_filters_to_en(
        self, mock_llm: MagicMock, mock_kb: MagicMock,
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ai-commercial default 'en' keeps English entries, drops zh."""
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_digest(
            domain="ai-commercial", period="weekly", format="markdown"
        ))
        assert "English AI funding round" in body
        assert "中文 AI 融资动态" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_explicit_language_overrides_domain_default(
        self, mock_llm: MagicMock, mock_kb: MagicMock,
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Explicit language='zh' overrides the domain default 'en'."""
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_digest(
            domain="ai-commercial", period="weekly", format="markdown",
            language="zh",
        ))
        assert "中文 AI 融资动态" in body
        assert "English AI funding round" not in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_no_default_keeps_legacy_behavior(
        self, mock_llm: MagicMock, mock_kb: MagicMock,
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A domain with no default keeps both languages (legacy).

        Uses language-learning (a demo domain whose seed declares no
        default_language) — medical-research gained a seed default_language
        in the #19 fine-tune, so the language filter would engage.
        """
        _write_config(tmp_path, [_plain_domain("language-learning")])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        entries = [
            {**e, "domain": "language-learning"} for e in _MIXED_ENTRIES
        ]
        mock_kb.return_value = _digest_mock_store(entries)
        body = _as_text(generate_digest(
            domain="language-learning", period="weekly", format="markdown"
        ))
        assert "English AI funding round" in body
        assert "中文 AI 融资动态" in body


class TestReportDomainDefault:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_domain_default_filters_to_en(
        self, mock_synthesis: MagicMock, mock_group: MagicMock,
        mock_kb: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """generate_report also applies the domain default language."""
        _write_config(tmp_path, [_ai_commercial_domain()])
        monkeypatch.chdir(tmp_path)
        mock_kb.return_value = _digest_mock_store(_MIXED_ENTRIES)
        mock_group.return_value = []
        mock_synthesis.return_value = "Overview."
        body = _as_text(generate_report(
            domain="ai-commercial", period="weekly", format="markdown"
        ))
        assert "English AI funding round" in body
        assert "中文 AI 融资动态" not in body
