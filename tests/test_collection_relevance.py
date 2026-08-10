"""Tests for the deterministic topic-keyword relevance filter (#177).

The collection pipeline must:
- keep an item iff at least one configured topic keyword appears
  (case-insensitive substring match) in its title or content,
- count dropped items in ``CollectionResult.items_filtered`` and surface
  them in the per-source collection log entry,
- never filter when the domain/topic has no keywords configured
  (identical behavior to before the filter existed),
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


def _make_config(topics: list[TopicConfig]) -> Config:
    return Config(
        project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
        llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
        domains=[
            DomainConfig(
                name="medical-research",
                active=True,
                sources=[
                    SourceConfig(
                        name="test-rss",
                        type="rss",
                        url="https://example.com/feed",
                        quality_tier=1,
                    ),
                ],
                topics=topics,
            ),
        ],
    )


def _run_collection(items: list[Item], topics: list[TopicConfig], topic: str = ""):
    """Run a dry-run collection with mocked config/fetch — no network."""
    from autoinfo.collect import run_collection

    config = _make_config(topics=topics)
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
# Deterministic keyword filter
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
