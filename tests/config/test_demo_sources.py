"""Tests for demo domain source YAML config files.

Verifies that all 5 demo domains have their expected sources defined
with valid structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

DEMO_DIR = Path(__file__).resolve().parents[2] / "src" / "autoinfo" / "data" / "domains"

# TRIAGE #45-49 (stale): EXPECTED snapshot drifted from the current YAML —
# voa-learning-english removed from language-learning, and the source counts
# grew (medical-research 7, financial-intelligence 7, tech-ai-developer 8).
# old = pre-existing sources, new = later additions; old+new totals the live
# source list for each domain (`src/autoinfo/data/domains/*/sources.yaml`).
# M3T30 added Finnhub to financial-intelligence (6→7, SEC EDGAR replaced 1:1).
EXPECTED = {
    "medical-research": {
        "old": ["pubmed"],
        "new": ["semantic-scholar", "arXiv", "CrossRef", "dblp", "openalex", "uspto"],
    },
    "ai-commercial": {
        "old": ["techcrunch", "producthunt"],
        "new": ["Crunchbase", "36kr"],
    },
    "language-learning": {
        "old": ["project-gutenberg"],
        "new": ["news-in-levels", "commonlit"],
    },
    "financial-intelligence": {
        "old": ["Alpha Vantage", "FRED"],
        "new": [
            "Finnhub",
            "SEC EDGAR",
            "Twelve Data",
            "World Bank Data",
            "Quandl/Nasdaq Data Link",
            # #288 (2026-08-17): keyless finance news RSS feeds
            "CNBC Investing",
            "TheStreet",
            "MarketWatch Markets (DJ)",
        ],
    },
    "tech-ai-developer": {
        "old": ["GitHub Trending", "HackerNews API"],
        "new": [
            "Substack RSS (tech) — Pragmatic Engineer",
            "Stack Exchange",
            "ProductHunt",
            "Reddit",
            "Spotify AI Podcasts",
            "Bilibili (B站)",
        ],
    },
}


def _load_sources(domain: str) -> list[dict[str, Any]]:
    path = DEMO_DIR / domain / "sources.yaml"
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return list(data["sources"])


@pytest.mark.parametrize("domain, old, new", [
    (
        "medical-research",
        ["pubmed"],
        ["semantic-scholar", "arXiv", "CrossRef", "dblp", "openalex", "uspto"],
    ),
    ("ai-commercial", ["techcrunch", "producthunt"], ["Crunchbase", "36kr"]),
    (
        "language-learning",
        ["project-gutenberg"],
        ["news-in-levels", "commonlit"],
    ),
    (
        "financial-intelligence",
        ["Alpha Vantage", "FRED"],
        [
            "Finnhub",
            "SEC EDGAR",
            "Twelve Data",
            "World Bank Data",
            "Quandl/Nasdaq Data Link",
            "CNBC Investing",
            "TheStreet",
            "MarketWatch Markets (DJ)",
        ],
    ),
    (
        "tech-ai-developer",
        ["GitHub Trending", "HackerNews API"],
        [
            "Substack RSS (tech) — Pragmatic Engineer",
            "Stack Exchange",
            "ProductHunt",
            "Reddit",
            "Spotify AI Podcasts",
            "Bilibili (B站)",
        ],
    ),
])
class TestDemoSources:
    def test_old_sources_preserved(self, domain: str, old: list[str], new: list[str]) -> None:
        sources = _load_sources(domain)
        names = [s["name"] for s in sources]
        for name in old:
            assert name in names, f"{domain}: expected existing source {name!r} to be preserved"

    def test_new_sources_added(self, domain: str, old: list[str], new: list[str]) -> None:
        sources = _load_sources(domain)
        names = [s["name"] for s in sources]
        for name in new:
            assert name in names, f"{domain}: expected new source {name!r} to be present"

    def test_required_fields(self, domain: str, old: list[str], new: list[str]) -> None:
        sources = _load_sources(domain)
        for src in sources:
            assert "name" in src
            assert "type" in src
            assert "url" in src
            assert "quality_tier" in src
            assert isinstance(src["quality_tier"], int)

    def test_total_count(self, domain: str, old: list[str], new: list[str]) -> None:
        sources = _load_sources(domain)
        expected_count = len(old) + len(new)
        assert len(sources) == expected_count, (
            f"{domain}: expected {expected_count} sources, got {len(sources)}"
        )
