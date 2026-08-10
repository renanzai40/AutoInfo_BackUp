"""Tests for the deterministic topic-keyword relevance filter (#177).

The collection pipeline must:
- keep an item iff at least one configured topic keyword matches
  (case-insensitive, token-level, partial-word aware) its title or content
  — but only for *cross-disciplinary search platforms* (OpenAlex, DBLP,
  generic web, Semantic Scholar/CrossRef APIs, unscoped Google News);
- count dropped items in ``CollectionResult.items_filtered`` and surface
  them in the per-source collection log entry;
- never filter *curated niche feeds* (publication RSS like retail-dive,
  provider APIs like pubmed) — the source itself is the relevance signal
  (#177 over-filtering regression);
- never filter when the domain/topic has no keywords configured;
- pass topic keywords into the OpenAlex ``search=`` query param so the API
  query itself is topical (falling back to the topic name without keywords).

All tests use fakes/monkeypatching — no real network or LLM calls.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from autoinfo.config import (
    Config,
    DomainConfig,
    LLMConfig,
    ProjectConfig,
    SourceConfig,
    TopicConfig,
)
from autoinfo.models import Item

# ======================================================================
# Fakes & helpers
# ======================================================================


class FakeOpenAlexHandler:
    """Minimal OpenAlex stand-in whose ``fetch`` records its arguments."""

    source_type = "openalex"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, limit: int = 10, query: str = "") -> list[dict]:
        self.calls.append({"limit": limit, "query": query})
        return []


def _make_item(item_id: str, title: str, content: str = "") -> Item:
    return Item(
        id=item_id,
        source_name="test-rss",
        source_type="rss",
        source_url=f"https://example.com/{item_id}",
        title=title,
        content=content,
        collected_at="2026-07-20T00:00:00Z",
    )


def _make_config(
    topics: list[TopicConfig],
    source_type: str = "openalex",
    source_name: str = "openalex",
    source_url: str = "https://api.openalex.org/works",
) -> Config:
    return Config(
        project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
        llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
        domains=[
            DomainConfig(
                name="medical-research",
                active=True,
                sources=[
                    SourceConfig(
                        name=source_name,
                        type=source_type,
                        url=source_url,
                        quality_tier=1,
                    ),
                ],
                topics=topics,
            ),
        ],
    )


def _run_collection(
    items: list[Item],
    topics: list[TopicConfig],
    topic: str = "",
    source_type: str = "openalex",
    source_name: str = "openalex",
    source_url: str = "https://api.openalex.org/works",
):
    """Run a dry-run collection with mocked config/fetch — no network."""
    from autoinfo.collect import run_collection

    config = _make_config(
        topics=topics,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
    )
    with patch("autoinfo.collect.get_config_path"), patch(
        "autoinfo.collect.load_config"
    ) as mock_load:
        mock_load.return_value = config
        with patch("autoinfo.collect._fetch_items", return_value=items):
            return run_collection(
                domain="medical-research",
                topic=topic,
                limit=10,
                dry_run=True,
            )


def _source_result(result: dict) -> dict:
    assert len(result["per_source"]) == 1
    return result["per_source"][0]


# ======================================================================
# Deterministic keyword filter (cross-disciplinary sources)
# ======================================================================


class TestRelevanceFilter:
    """Items must be kept iff a topic keyword matches title or content."""

    def test_keyword_in_title_keeps_item(self):
        """Case-insensitive keyword match in the title is kept."""
        result = _run_collection(
            items=[_make_item("a1", "CRISPR gene editing breakthrough")],
            topics=[TopicConfig(name="gene editing", keywords=["crispr"])],
        )
        src = _source_result(result)
        assert src["items_found"] == 1
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_keyword_in_content_keeps_item(self):
        """Keyword appearing only in the body still keeps the item."""
        result = _run_collection(
            items=[
                _make_item(
                    "b1",
                    "Unrelated headline",
                    content="The trial reports a CRISPR-based therapy for sickle cell.",
                )
            ],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR"])],
        )
        src = _source_result(result)
        assert src["items_found"] == 1
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_no_keyword_match_filters_item_and_counts(self):
        """An item matching no keyword is dropped and counted."""
        result = _run_collection(
            items=[
                _make_item("c1", "Quantum computing advances", content="Nothing relevant here."),
            ],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
        )
        src = _source_result(result)
        assert src["items_found"] == 1
        assert src["items_filtered"] == 1
        assert src["items_new"] == 0

    def test_mixed_items_filter_only_non_matching(self):
        """Only the non-matching items are dropped; matching ones flow on."""
        result = _run_collection(
            items=[
                _make_item("m1", "CRISPR clinical trial published"),
                _make_item("m2", "Quantum computing advances"),
                _make_item("m3", "Embryo selection ethics review", content="body text"),
            ],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
        )
        src = _source_result(result)
        assert src["items_found"] == 3
        assert src["items_filtered"] == 1
        assert src["items_new"] == 2

    def test_log_run_records_items_filtered(self, tmp_path, monkeypatch):
        """The per-source run log entry carries the filtered count."""
        from autoinfo.collect import _log_run

        monkeypatch.chdir(tmp_path)
        _log_run(
            "medical-research",
            "test-rss",
            "col-filtered",
            items_found=5,
            items_new=3,
            items_filtered=2,
        )
        runs_path = tmp_path / "collections" / "medical-research" / "test-rss" / "_runs.json"
        runs = json.loads(runs_path.read_text(encoding="utf-8"))
        assert runs[-1]["items_found"] == 5
        assert runs[-1]["items_new"] == 3
        assert runs[-1]["items_filtered"] == 2


# ======================================================================
# Token-level partial-word matching
# ======================================================================


class TestPartialWordMatching:
    """Keyword matching is token-level, partial-word aware (#177 fix)."""

    def test_hyphenated_multiword_keyword_matches(self):
        """"supply chain" matches "supply-chain disruptions" (hyphenated)."""
        result = _run_collection(
            items=[_make_item("h1", "supply-chain disruptions hit retailers")],
            topics=[TopicConfig(name="retail", keywords=["supply chain"])],
        )
        src = _source_result(result)
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_inflected_word_matches(self):
        """"retail" matches "retailers" — inflection/plural tolerance."""
        result = _run_collection(
            items=[_make_item("i1", "Retailers slash prices in Q3")],
            topics=[TopicConfig(name="retail", keywords=["retail"])],
        )
        src = _source_result(result)
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_multiword_keyword_requires_all_words(self):
        """"supply chain" does not match an item with only "supply"."""
        result = _run_collection(
            items=[_make_item("s1", "supply shortages everywhere")],
            topics=[TopicConfig(name="retail", keywords=["supply chain"])],
        )
        src = _source_result(result)
        assert src["items_filtered"] == 1
        assert src["items_new"] == 0

    def test_min_keywords_floor(self):
        """min_keywords=2 requires two distinct keywords to match."""
        from autoinfo.collect import _matches_keywords

        item = _make_item("f1", "Launch event announced today")
        keywords = ["launch", "funding"]
        assert _matches_keywords(item, keywords, min_keywords=1) is True
        assert _matches_keywords(item, keywords, min_keywords=2) is False


# ======================================================================
# Source-type awareness — curated feeds must never be filtered (#177)
# ======================================================================


class TestSourceTypeAwareness:
    """Only cross-disciplinary platforms are keyword-filtered (#177)."""

    def test_curated_publisher_rss_keeps_everything(self):
        """#177 regression: retail-dive RSS is curated — nothing filtered."""
        result = _run_collection(
            items=[
                _make_item("r1", "Will people pay more for Under Armour?"),
                _make_item("r2", "Whole Foods expands private label"),
            ],
            topics=[TopicConfig(name="retail trends", keywords=["supply chain", "e-commerce"])],
            source_type="rss",
            source_name="retail-dive",
            source_url="https://www.retaildive.com/feeds/news/",
        )
        src = _source_result(result)
        assert src["items_found"] == 2
        assert src["items_filtered"] == 0
        assert src["items_new"] == 2

    def test_pubmed_api_keeps_everything(self):
        """Provider API (pubmed) is topical by construction — not filtered."""
        result = _run_collection(
            items=[
                _make_item(
                    "p1",
                    "A randomized trial of IVF outcomes",
                    content="Nothing about the configured keywords.",
                ),
            ],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
            source_type="api",
            source_name="pubmed",
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_semantic_scholar_api_is_filtered(self):
        """Cross-disciplinary Semantic Scholar API is filtered by name marker."""
        result = _run_collection(
            items=[_make_item("s1", "Quantum computing advances")],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
            source_type="api",
            source_name="semantic-scholar",
            source_url="https://api.semanticscholar.org/graph/v1/paper/search",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 1
        assert src["items_new"] == 0

    def test_crossref_api_is_filtered(self):
        """Cross-disciplinary CrossRef API is filtered by name marker."""
        result = _run_collection(
            items=[_make_item("c1", "Quantum computing advances")],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
            source_type="api",
            source_name="crossref",
            source_url="https://api.crossref.org/works",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 1
        assert src["items_new"] == 0

    def test_dblp_and_web_are_filtered(self):
        """DBLP and generic web sources are cross-disciplinary."""
        from autoinfo.collect import _is_cross_disciplinary_source

        for stype in ("dblp", "web"):
            assert _is_cross_disciplinary_source(
                SourceConfig(name="sr", type=stype, url="https://example.com"),
            ) is True, f"{stype} should be cross-disciplinary"

    def test_generic_api_is_not_filtered(self):
        """A generic HttpApi source (e.g. coursera) is topical by construction."""
        from autoinfo.collect import _is_cross_disciplinary_source

        assert _is_cross_disciplinary_source(
            SourceConfig(name="coursera", type="api", url="https://example.com"),
        ) is False

    def test_google_news_unscoped_is_filtered(self):
        """An unscoped Google News search RSS is a cross-disciplinary feed."""
        result = _run_collection(
            items=[_make_item("g1", "Quantum computing advances")],
            topics=[TopicConfig(name="gene editing", keywords=["CRISPR", "embryo"])],
            source_type="rss",
            source_name="google-news",
            source_url="https://news.google.com/rss/search?q=medical+research&hl=en-US",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 1
        assert src["items_new"] == 0

    def test_google_news_site_scoped_is_not_filtered(self):
        """A site-scoped Google News query is effectively a curated feed."""
        result = _run_collection(
            items=[_make_item("g2", "retail supply chain news")],
            topics=[TopicConfig(name="retail", keywords=["CRISPR", "embryo"])],
            source_type="rss",
            source_name="google-news-ebrun",
            source_url="https://news.google.com/rss/search?q=site:ebrun.com+retail&hl=zh-CN",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1

    def test_plain_feed_url_is_not_filtered(self):
        """A non-Google News RSS feed is curated, never filtered."""
        from autoinfo.collect import _is_cross_disciplinary_source

        assert _is_cross_disciplinary_source(
            SourceConfig(
                name="techcrunch",
                type="rss",
                url="https://techcrunch.com/feed/",
            ),
        ) is False


# ======================================================================
# Keyword-less domains must never be filtered
# ======================================================================


class TestNoKeywordsNoFilter:
    """Domains/topics without keywords behave exactly as before (#177)."""

    def test_domain_without_topics_keeps_everything(self):
        """No topics configured → no filtering at all."""
        result = _run_collection(
            items=[
                _make_item("n1", "Anything at all"),
                _make_item("n2", "Completely unrelated content"),
            ],
            topics=[],
        )
        src = _source_result(result)
        assert src["items_found"] == 2
        assert src["items_filtered"] == 0
        assert src["items_new"] == 2

    def test_topic_without_keywords_keeps_everything(self):
        """A named topic with an empty keyword list → no filtering."""
        result = _run_collection(
            items=[_make_item("n3", "Anything at all")],
            topics=[TopicConfig(name="gene editing", keywords=[])],
            topic="gene editing",
        )
        src = _source_result(result)
        assert src["items_filtered"] == 0
        assert src["items_new"] == 1


# ======================================================================
# OpenAlex topical query
# ======================================================================


class TestOpenAlexTopicQuery:
    """OpenAlex API query must be built from topic keywords (#177)."""

    def test_fetch_items_passes_topic_keywords_as_query(self):
        """``_fetch_items`` forwards joined topic keywords as the query."""
        from autoinfo.collect import _fetch_items

        handler = FakeOpenAlexHandler()
        source = SourceConfig(name="openalex", type="openalex", settings={})
        items = _fetch_items(
            handler, source, topic="", limit=5, keywords=["CRISPR", "gene editing"]
        )
        assert items == []
        assert handler.calls[-1] == {"limit": 5, "query": "CRISPR gene editing"}

    def test_fetch_items_falls_back_to_topic_name_without_keywords(self):
        """Without keywords, the topic name becomes the query."""
        from autoinfo.collect import _fetch_items

        handler = FakeOpenAlexHandler()
        source = SourceConfig(name="openalex", type="openalex", settings={})
        _fetch_items(handler, source, topic="cancer research", limit=5, keywords=[])
        assert handler.calls[-1] == {"limit": 5, "query": "cancer research"}

    def test_handler_fetch_builds_search_param_from_query(self):
        """The handler encodes the query override into the ``search=`` param."""
        from autoinfo.collectors.openalex import OpenAlexHandler

        captured: dict[str, str] = {}

        def fake_get(url, timeout=None, headers=None):
            captured["url"] = url

            class FakeResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"results": []}

            return FakeResponse()

        with patch("autoinfo.collectors.openalex.httpx.get", side_effect=fake_get):
            handler = OpenAlexHandler({})
            handler.fetch(limit=5, query="CRISPR gene")

        assert "search=CRISPR%20gene" in captured["url"]

    def test_handler_fetch_falls_back_to_config_query(self):
        """Empty query override keeps the configured query (current behavior)."""
        from autoinfo.collectors.openalex import OpenAlexHandler

        captured: dict[str, str] = {}

        def fake_get(url, timeout=None, headers=None):
            captured["url"] = url

            class FakeResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"results": []}

            return FakeResponse()

        with patch("autoinfo.collectors.openalex.httpx.get", side_effect=fake_get):
            handler = OpenAlexHandler({"query": "cancer"})
            handler.fetch(limit=5, query="")

        assert "search=cancer" in captured["url"]
