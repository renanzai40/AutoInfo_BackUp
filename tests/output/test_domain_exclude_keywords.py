"""Tests for the per-domain exclude_keywords cross-domain noise filter (#319).

ai-commercial (AI business) digests/magazine-digests contained medical
entries (贝达药业, EyePoint DURAVYU eye-drug phase III trial) even though the
G1-G3 relevance gates passed them.  The fix is a product-generation-layer
filter (NOT a gate change): ``DomainConfig.exclude_keywords`` declares a
per-domain blacklist, and ``generate_digest`` / ``generate_report`` (and the
cross-domain digest) drop entries whose title/summary/tags contain an
excluded keyword (substring match, casefold for latin, CJK-aware) BEFORE LLM
synthesis.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from autoinfo.config import Config, DomainConfig, config_to_dict, load_config
from autoinfo.output import (
    DeliveryOutput,
    _filter_entries_by_domain_exclusions,
    _get_domain_exclude_keywords,
    generate_digest,
    generate_presentation,
    generate_report,
    generate_tutorial,
)


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


def _write_config(tmp_path: Any, exclude_keywords: list[str]) -> None:
    """Write a minimal project config with an ai-commercial domain."""
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
                "exclude_keywords": exclude_keywords,
            },
            {
                "name": "medical-research",
                "active": True,
                "sources": [
                    {
                        "name": "pubmed",
                        "type": "api",
                        "url": "https://eutils.ncbi.nlm.nih.gov/",
                    }
                ],
                "topics": [],
            },
        ],
    }
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _entry(
    entry_id: str,
    title: str,
    summary: str = "Summary content for the entry.",
    tags: Any = "[]",
    domain: str = "ai-commercial",
) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "title": title,
        "summary": summary,
        "domain": domain,
        "tier": "01-Raw",
        "source_url": f"https://example.com/{entry_id}",
        "source_type": "rss",
        "source_platform": "techcrunch",
        "relevance_score": 85.0,
        "tags": tags,
        "collected_at": "2026-08-17",
    }


# ---------------------------------------------------------------------------
# _filter_entries_by_domain_exclusions (unit)
# ---------------------------------------------------------------------------


class TestFilterEntriesByDomainExclusions:
    def test_cjk_substring_in_title(self) -> None:
        entries = [
            _entry("e1", "贝达药业 2026 半年报"),
            _entry("e2", "AI startup raises series A"),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            return_value=["贝达药业", "DURAVYU"],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert [e["entry_id"] for e in kept] == ["e2"]

    def test_latin_case_insensitive_in_summary(self) -> None:
        entries = [
            _entry("e1", "EyePoint reports phase III", summary="DURAVYU eye drug trial"),
            _entry("e2", "LLM pricing war heats up"),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            return_value=["duravyu"],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert [e["entry_id"] for e in kept] == ["e2"]

    def test_keyword_in_tags(self) -> None:
        entries = [
            _entry("e1", "Phase III readout", tags='["DURAVYU", "ophthalmology"]'),
            _entry("e2", "New model release", tags='["LLM", "launch"]'),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            return_value=["duravyu"],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert [e["entry_id"] for e in kept] == ["e2"]

    def test_non_matching_entries_pass_through_unchanged(self) -> None:
        entries = [
            _entry("e1", "AI startup funding round"),
            _entry("e2", "Generative AI product launch"),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            return_value=["贝达药业", "DURAVYU"],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert kept == entries

    def test_empty_exclude_list_is_noop(self) -> None:
        entries = [
            _entry("e1", "贝达药业 半年报"),
            _entry("e2", "AI funding"),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            return_value=[],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert kept == entries

    def test_per_entry_domain_resolution(self) -> None:
        # A medical entry in the medical-research domain (empty exclude list)
        # is kept even though the primary domain would exclude it.
        entries = [
            _entry("e1", "贝达药业 半年报", domain="medical-research"),
            _entry("e2", "AI funding", domain="ai-commercial"),
        ]
        with patch(
            "autoinfo.output._get_domain_exclude_keywords",
            side_effect=lambda d: ["贝达药业"] if d == "ai-commercial" else [],
        ):
            kept = _filter_entries_by_domain_exclusions(entries, "ai-commercial")
        assert [e["entry_id"] for e in kept] == ["e1", "e2"]


# ---------------------------------------------------------------------------
# DomainConfig parses / persists exclude_keywords
# ---------------------------------------------------------------------------


class TestDomainConfigExcludeKeywords:
    def test_parses_from_yaml(self, tmp_path: Any) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        cfg = load_config(tmp_path / ".autoinfo" / "config.yaml")
        ai = next(d for d in cfg.domains if d.name == "ai-commercial")
        assert ai.exclude_keywords == ["贝达药业", "DURAVYU"]
        med = next(d for d in cfg.domains if d.name == "medical-research")
        assert med.exclude_keywords == []

    def test_default_empty(self) -> None:
        assert DomainConfig(name="x").exclude_keywords == []

    def test_serializes_to_dict(self) -> None:
        cfg = DomainConfig(name="ai-commercial", exclude_keywords=["贝达药业", "DURAVYU"])
        d = config_to_dict(Config(domains=[cfg]))
        assert d["domains"][0]["exclude_keywords"] == ["贝达药业", "DURAVYU"]

    def test_empty_exclude_keywords_omitted_from_dict(self) -> None:
        cfg = DomainConfig(name="plain")
        d = config_to_dict(Config(domains=[cfg]))
        assert "exclude_keywords" not in d["domains"][0]


# ---------------------------------------------------------------------------
# End-to-end: generate_digest with exclude_keywords
# ---------------------------------------------------------------------------


def _digest_mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


_MIXED_ENTRIES = [
    _entry("med-1", "贝达药业 2026 半年报", summary="医药公司业绩"),
    _entry("med-2", "EyePoint DURAVYU phase III", summary="眼药三期临床"),
    _entry("ai-1", "AI startup raises series A", summary="Venture funding"),
    _entry("ai-2", "Generative AI product launch", summary="New LLM features"),
]


class TestDigestExcludeKeywords:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_excluded_entries_absent_from_synthesis_and_body(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock, tmp_path: Any, monkeypatch: Any
    ) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb_store.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_digest(
            domain="ai-commercial", period="weekly", format="markdown"
        ))
        # Excluded medical entries never reach the LLM prompt nor the body.
        prompt = mock_llm.call_args[0][0]
        assert "贝达药业" not in prompt
        assert "DURAVYU" not in prompt
        assert "贝达药业" not in body
        assert "DURAVYU" not in body
        # Legitimate AI-commercial entries pass through.
        assert "AI startup raises series A" in body
        assert "Generative AI product launch" in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_empty_exclude_list_keeps_all(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock, tmp_path: Any, monkeypatch: Any
    ) -> None:
        _write_config(tmp_path, [])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb_store.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_digest(
            domain="ai-commercial", period="weekly", format="markdown"
        ))
        assert "贝达药业" in body
        assert "DURAVYU" in body

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_cross_domain_digest_filters_per_entry_domain(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock, tmp_path: Any, monkeypatch: Any
    ) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        ai_entries = [
            _entry("ai-med-1", "贝达药业 半年报", domain="ai-commercial"),
            _entry("ai-1", "AI startup funding", domain="ai-commercial"),
        ]
        med_entries = [
            _entry("med-1", "贝达药业 临床进展", domain="medical-research"),
            _entry("med-2", "IVF breakthrough", domain="medical-research"),
        ]
        store = MagicMock()
        store.list_entries.side_effect = lambda domain, **kw: (
            ai_entries if domain == "ai-commercial" else med_entries
        )
        mock_kb_store.return_value = store
        body = _as_text(generate_digest(
            domain="ai-commercial",
            domains=["ai-commercial", "medical-research"],
            period="weekly",
            format="markdown",
        ))
        # The ai-commercial medical entry is excluded; the medical-research
        # entry (its own domain has an empty exclude list) is kept.
        assert "贝达药业 半年报" not in body
        assert "贝达药业 临床进展" in body
        assert "AI startup funding" in body
        assert "IVF breakthrough" in body


# ---------------------------------------------------------------------------
# End-to-end: generate_report with exclude_keywords
# ---------------------------------------------------------------------------


class TestReportExcludeKeywords:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_excludes_cross_domain_entries(
        self,
        mock_synthesis: MagicMock,
        mock_group: MagicMock,
        mock_kb: MagicMock,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        mock_kb.return_value = _digest_mock_store(_MIXED_ENTRIES)
        mock_group.return_value = []
        mock_synthesis.return_value = "Overview."
        body = _as_text(generate_report(
            domain="ai-commercial", period="weekly", format="markdown"
        ))
        assert "贝达药业" not in body
        assert "DURAVYU" not in body
        assert "AI startup raises series A" in body
        assert "Generative AI product launch" in body


# ---------------------------------------------------------------------------
# End-to-end: generate_tutorial / generate_presentation with exclude_keywords
# ---------------------------------------------------------------------------


class TestTutorialExcludeKeywords:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_tutorial_excludes_noise_entries(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock, tmp_path: Any, monkeypatch: Any
    ) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        # Empty LLM result forces the KB-derived fallback path, which renders
        # entry titles/summaries verbatim — the strongest leak surface.
        mock_llm.return_value = {}
        mock_kb_store.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_tutorial(domain="ai-commercial", format="markdown"))
        assert "贝达药业" not in body
        assert "DURAVYU" not in body
        assert "AI startup raises series A" in body
        assert "Generative AI product launch" in body


class TestPresentationExcludeKeywords:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_presentation_excludes_noise_entries(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock, tmp_path: Any, monkeypatch: Any
    ) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        mock_llm.return_value = {
            "title": "AI deck",
            "description": "d",
            "slides": [
                {
                    "title": "AI startup raises series A",
                    "content": "Venture funding",
                    "bullets": ["Venture funding"],
                    "notes": "",
                }
            ],
        }
        mock_kb_store.return_value = _digest_mock_store(_MIXED_ENTRIES)
        body = _as_text(generate_presentation(
            domain="ai-commercial", topic="医药", format="markdown", allow_empty=True
        ))
        # The noise entries never reach the LLM prompt nor the rendered body.
        prompt = mock_llm.call_args[0][0]
        assert "贝达药业" not in prompt
        assert "DURAVYU" not in prompt
        assert "贝达药业" not in body
        assert "DURAVYU" not in body
        assert "AI startup raises series A" in body


# ---------------------------------------------------------------------------
# Seed fallback (issue #319): config lacking the key falls back to the
# demo-domain seed so existing projects filter without a config migration.
# ---------------------------------------------------------------------------


class TestSeedFallback:
    def test_seed_fallback_when_config_lacks_key(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        # Runtime config WITHOUT exclude_keywords (the pre-#319 live shape).
        cfg_dir = tmp_path / ".autoinfo"
        cfg_dir.mkdir(parents=True)
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
        monkeypatch.chdir(tmp_path)
        assert _get_domain_exclude_keywords("ai-commercial") == ["贝达药业", "DURAVYU"]

    def test_explicit_empty_list_wins_over_seed(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        # An explicitly declared empty list means "no filtering" — the seed
        # fallback must NOT override it (backward compatible).
        _write_config(tmp_path, [])
        monkeypatch.chdir(tmp_path)
        assert _get_domain_exclude_keywords("ai-commercial") == []

    def test_unknown_domain_returns_empty(self, tmp_path: Any, monkeypatch: Any) -> None:
        _write_config(tmp_path, ["贝达药业", "DURAVYU"])
        monkeypatch.chdir(tmp_path)
        # No demo seed exists for this domain -> [] (no filtering).
        assert _get_domain_exclude_keywords("no-such-domain") == []
