"""G3 topic-keyword resolution tests (issue #68, PART A).

``run_processing`` resolves ``topic_keywords`` for the G3 relevance gate.
Before the fix, an omitted ``topic`` left ``topic_keywords=[]`` even when the
domain had configured topics — every digest Relevance rendered ``—/100``.
After the fix, an omitted ``topic`` falls back to the UNION of all the
domain's topic keyword lists (dedup preserving order); a domain with no
topics at all keeps ``topic_keywords=[]`` so the locked G3
empty-keywords→score-0 contract (tests/llm/test_quality.py) is untouched.

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item
from autoinfo.process import run_processing

_CONFIG_YAML = {
    "project": {"name": "Test Project", "created_at": "2026-07-01"},
    "llm": {
        "provider": "openai",
        "model": "test/test",
        "api_key": "test-key",
    },
    "domains": [
        {
            "name": "french-learning",
            "active": True,
            "topics": [
                {
                    "name": "france-politics",
                    "keywords": ["actualité", "politique", "gouvernement", "élections"],
                },
                {
                    "name": "france-economy",
                    "keywords": ["économie", "budget", "croissance", "inflation"],
                },
            ],
        }
    ],
}


def _write_config(root: Path, config_yaml: dict) -> None:
    """Write ``.autoinfo/config.yaml`` under *root*."""
    config_dir = root / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(config_yaml, allow_unicode=True),
        encoding="utf-8",
    )


def _write_cached_item(
    root: Path, domain: str, item: dict
) -> None:
    """Write one cached raw item under ``collections/<domain>/<source>/<date>/``."""
    item_dir = root / "collections" / domain / "rss" / "2026-07-15"
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "fr-item-1.json").write_text(
        json.dumps(item, ensure_ascii=False), encoding="utf-8"
    )


def _base_item(title: str, domain: str = "french-learning") -> dict:
    return {
        "id": "fr-item-1",
        "source_name": "rss",
        "source_type": "rss",
        "source_platform": "rss",
        "source_url": "https://example.com/fr/1",
        "title": title,
        "content": (
            "Un résumé détaillé de la situation actuelle en France métropolitaine "
            "pour ce tour d'horizon hebdomadaire de la presse."
        ),
        "content_type": "text",
        "collected_at": "2026-07-15T10:00:00Z",
        "language": "",
        "domain": domain,
        "topic_tags": [],
        "quality_tier": 1,
    }


def _extraction(item: Item) -> ExtractionResult:
    return ExtractionResult(
        item_id=item.id,
        title=item.title,
        tl_dr="A summary of the article.",
        key_points=["A key point"],
        entities=[],
        relevance_score=0.0,
    )


def _stored_entries(root: Path, domain: str) -> list[dict]:
    """Return the entries persisted in the tmp KB via a fresh KBStore."""
    store = KBStore(base_path=root / "knowledge", min_content_chars=0)
    return store.list_entries(domain, limit=100)


class TestTopicKeywordUnion:
    def test_run_processing_union_keywords_gives_nonzero_relevance(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitted ``topic`` + domain topics → G3 gets the union of keyword
        lists, so an item matching any topic keyword scores > 0."""
        monkeypatch.chdir(tmp_path)
        _write_config(tmp_path, _CONFIG_YAML)
        _write_cached_item(
            tmp_path,
            "french-learning",
            _base_item("Le gouvernement face aux élections"),
        )
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")
        with patch.object(
            LLMExtractor,
            "extract",
            side_effect=lambda item, schema=None: _extraction(item),  # noqa: ARG005
        ):
            result = run_processing(domain="french-learning")

        assert result.kb_entries_created == 1, result.errors
        entries = _stored_entries(tmp_path, "french-learning")
        assert len(entries) == 1
        score = entries[0].get("relevance_score", 0.0)
        assert score > 0, (
            "G3 relevance score stayed 0 with omitted topic — topic_keywords "
            "were not resolved from the domain's topic union"
        )
        # Surface evidence: the tags were also derived from title-matched
        # keywords (PART B) since the collectors set no topic_tags.
        assert "gouvernement" in (entries[0].get("tags") or [])

    def test_run_processing_domain_without_topics_still_scores_zero(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A domain with NO topics keeps ``topic_keywords=[]`` — the locked
        G3 empty-keywords→score-0 contract is preserved (regression guard)."""
        monkeypatch.chdir(tmp_path)
        config = dict(_CONFIG_YAML)
        config["domains"] = [{"name": "no-topics", "active": True, "topics": []}]
        _write_config(tmp_path, config)
        _write_cached_item(
            tmp_path, "no-topics", _base_item("Some headline", domain="no-topics")
        )
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "1")
        with patch.object(
            LLMExtractor,
            "extract",
            side_effect=lambda item, schema=None: _extraction(item),  # noqa: ARG005
        ):
            result = run_processing(domain="no-topics")

        assert result.kb_entries_created == 1, result.errors
        entries = _stored_entries(tmp_path, "no-topics")
        assert len(entries) == 1
        assert entries[0].get("relevance_score", None) == 0.0
