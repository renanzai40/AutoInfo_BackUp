# mypy: ignore-errors
"""Issue #135 — dead-source detection: no silent "0 found".

Verifies:
* the arXiv demo feed uses the working ``q-bio`` RSS endpoint (``bio`` is a
  dead archive that answers HTTP 400)
* ``semantic-scholar`` / ``uspto`` (type=api) dispatch to their dedicated
  handlers instead of the generic ``HttpApiHandler``
* ``USPTOHandler`` surfaces an explicit structured failure when the retired
  PatentsView endpoint answers a redirect
* a handler raising ``SourceFailure`` produces per-source ``status="error"``
  with a ``source_failed`` marker that validation can assert on (failed, not
  passed-0-found)
* ``HttpApiHandler`` / ``RSSHandler`` failures are no longer silent ``[]``
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml

from autoinfo.collect import _build_handler, _fetch_items, run_collection
from autoinfo.collectors.base import SourceFailure
from autoinfo.collectors.http_api import HttpApiHandler
from autoinfo.collectors.rss import RSSHandler
from autoinfo.collectors.semantic_scholar import SemanticScholarHandler
from autoinfo.collectors.uspto import USPTOHandler
from autoinfo.config import SourceConfig

DEMO_DIR = Path(__file__).resolve().parents[2] / "src" / "autoinfo" / "data" / "domains"
SCENARIOS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "autoinfo" / "mcp" / "scenarios"
)


def _load_sources(domain: str) -> list[dict]:
    with open(DEMO_DIR / domain / "sources.yaml") as fh:
        return yaml.safe_load(fh)["sources"]


# ---------------------------------------------------------------------------
# arXiv feed URL (config level)
# ---------------------------------------------------------------------------


class TestArxivConfig:
    def test_medical_research_arxiv_uses_q_bio_feed(self) -> None:
        arxiv = next(s for s in _load_sources("medical-research") if s["name"] == "arXiv")
        assert arxiv["url"] == "https://rss.arxiv.org/rss/q-bio"

    def test_collectors_e2e_scenario_uses_q_bio_feed(self) -> None:
        with open(SCENARIOS_DIR / "collectors-e2e.yaml") as fh:
            data = yaml.safe_load(fh)
        step = next(s for s in data["steps"] if "arXiv" in s.get("name", ""))
        assert step["arguments"]["url"] == "https://rss.arxiv.org/rss/q-bio"


# ---------------------------------------------------------------------------
# Dispatch routing to dedicated handlers
# ---------------------------------------------------------------------------


class TestDispatchRouting:
    def test_semantic_scholar_dispatches_to_dedicated_handler(self) -> None:
        cfg = SourceConfig(
            name="semantic-scholar",
            type="api",
            url="https://api.semanticscholar.org/graph/v1",
        )
        handler = _build_handler(cfg)
        assert isinstance(handler, SemanticScholarHandler)
        assert not isinstance(handler, HttpApiHandler)

    def test_uspto_dispatches_to_dedicated_handler(self) -> None:
        cfg = SourceConfig(
            name="uspto",
            type="api",
            url="https://api.patentsview.org/patents/query",
        )
        handler = _build_handler(cfg)
        assert isinstance(handler, USPTOHandler)
        assert not isinstance(handler, HttpApiHandler)

    def test_fetch_items_semantic_scholar_path_returns_items(self) -> None:
        cfg = SourceConfig(
            name="semantic-scholar",
            type="api",
            url="https://api.semanticscholar.org/graph/v1",
        )
        handler = _build_handler(cfg)
        resp = httpx.Response(
            200,
            json={
                "total": 1,
                "offset": 0,
                "data": [
                    {
                        "paperId": "p1",
                        "title": "A Paper",
                        "abstract": "An abstract",
                        "authors": [{"name": "A. Author"}],
                        "citationCount": 1,
                        "publicationDate": "2026-01-01",
                    }
                ],
            },
            request=httpx.Request("GET", "http://test"),
        )
        with patch("httpx.get", return_value=resp):
            items = _fetch_items(handler, cfg, topic="", limit=5)

        assert len(items) == 1
        assert items[0].source_name == "semantic_scholar"
        assert items[0].title == "A Paper"


# ---------------------------------------------------------------------------
# USPTO retired API -> explicit structured failure
# ---------------------------------------------------------------------------


class TestUsptoFailure:
    def test_fetch_raises_source_failure_on_retired_api(self) -> None:
        resp = httpx.Response(
            301,
            request=httpx.Request("POST", "https://api.patentsview.org/patents/query"),
        )
        with patch("httpx.post", return_value=resp):
            with pytest.raises(SourceFailure) as exc_info:
                USPTOHandler().fetch("CRISPR", limit=5)

        assert "PatentsView API retired by USPTO" in exc_info.value.reason

    def test_dead_rss_fallback_raises_source_failure(self) -> None:
        post_req = httpx.Request("POST", "https://api.patentsview.org/patents/query")
        post_err = httpx.HTTPStatusError(
            "server error",
            request=post_req,
            response=httpx.Response(500, request=post_req),
        )
        get_req = httpx.Request(
            "GET", "https://www.uspto.gov/feeds/patent_application.xml"
        )
        get_err = httpx.HTTPStatusError(
            "not found",
            request=get_req,
            response=httpx.Response(404, request=get_req),
        )
        with patch("httpx.post", side_effect=post_err):
            with patch("httpx.get", side_effect=get_err):
                with pytest.raises(SourceFailure) as exc_info:
                    USPTOHandler().fetch("CRISPR", limit=5)

        assert "RSS feed unavailable" in exc_info.value.reason
        assert "404" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Handler failures are never silent
# ---------------------------------------------------------------------------


class TestNoSilentFailure:
    def test_http_api_failure_raises_source_failure(self) -> None:
        cfg = SourceConfig(
            name="dead-api",
            type="api",
            url="https://dead.example/api",
            settings={},
        )
        handler = HttpApiHandler(cfg)
        with patch(
            "autoinfo.collectors.http_api.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(SourceFailure) as exc_info:
                handler.fetch("https://dead.example/api")

        assert "HTTP API fetch failed" in exc_info.value.reason

    def test_rss_failure_raises_source_failure(self) -> None:
        with patch("feedparser.parse", side_effect=Exception("boom")):
            with pytest.raises(SourceFailure) as exc_info:
                RSSHandler().fetch("https://example.com/feed")

        assert "RSS fetch failed" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Pipeline-level marker: failed, not passed-0-found
# ---------------------------------------------------------------------------


class TestPipelineFailureMarker:
    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_dead_source_surfaces_source_failed_marker(
        self, mock_load_config, mock_get_config_path, tmp_path
    ) -> None:
        from autoinfo.config import (
            Config,
            DomainConfig,
            LLMConfig,
            ProjectConfig,
        )

        config = Config(
            project=ProjectConfig(name="t", created_at="x"),
            llm=LLMConfig(provider="openrouter", model="m", api_key="k"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(
                            name="uspto",
                            type="api",
                            url="https://api.patentsview.org/patents/query",
                        ),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = tmp_path / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch(
            "autoinfo.collect._fetch_items",
            side_effect=SourceFailure(
                "PatentsView API retired by USPTO (HTTP 301; migrated to data.uspto.gov)"
            ),
        ):
            result = run_collection(domain="medical-research", dry_run=True)

        per_source = result["per_source"][0]
        assert per_source["status"] == "error"
        assert per_source["source_failed"] is True
        assert per_source["items_found"] == 0
        assert per_source["errors"][0]["source_failed"] is True
        assert "retired by USPTO" in per_source["errors"][0]["reason"]
        # A dead source must never be reported as a successful 0-found run
        assert per_source["status"] != "success"


# ---------------------------------------------------------------------------
# Feed-style API sources must collect without a topic (AC4 collection gaps)
# ---------------------------------------------------------------------------


class TestFeedStyleApiDispatch:
    """The #182 no-query guard applies to query-driven sources only.

    Feed-style API sources (no ``query_param`` configured — fixed-URL JSON
    feeds like apple-music / mastodon / zhihu-daily / coursera / World Bank)
    are the API equivalent of an RSS feed: they fetch their configured URL
    as-is with an empty query.  The guard introduced by #182 (skip API
    sources with empty query) must NOT short-circuit them, or they can never
    be collected.
    """

    def test_feed_style_api_source_fetches_without_query(self) -> None:
        cfg = SourceConfig(
            name="apple-music",
            type="api",
            url="https://rss.marketingtools.apple.com/api/v2/us/music/most-recent/25/explicit.json",  # noqa: E501
            settings={
                "json_path": "$.feed.results",
                "field_mapping": {
                    "id": "id",
                    "title": "artistName + name",
                    "source_url": "url",
                    "content": "content",
                },
            },
        )
        handler = _build_handler(cfg)
        assert isinstance(handler, HttpApiHandler)
        resp = httpx.Response(
            200,
            json={
                "feed": {
                    "results": [
                        {
                            "id": "1",
                            "artistName": "A",
                            "name": "Song",
                            "url": "https://music.apple.com/song/1",
                            "content": "lyrics",
                        }
                    ]
                }
            },
            request=httpx.Request("GET", cfg.url),
        )
        with patch("httpx.get", return_value=resp):
            items = _fetch_items(handler, cfg, topic="", limit=5)

        assert len(items) == 1
        assert items[0].source_name == "apple-music"

    def test_query_driven_api_source_still_skipped_without_query(self) -> None:
        cfg = SourceConfig(
            name="GitHub Trending",
            type="api",
            url="https://api.github.com/search/repositories",
            settings={
                "query_param": "q",
                "json_path": "items",
                "field_mapping": {
                    "id": "id",
                    "title": "full_name",
                    "content": "description",
                    "source_url": "html_url",
                },
            },
        )
        handler = _build_handler(cfg)
        assert isinstance(handler, HttpApiHandler)
        with patch("httpx.get") as mock_get:
            items = _fetch_items(handler, cfg, topic="", limit=5)

        assert items == []
        mock_get.assert_not_called()

    def test_query_driven_api_source_fetches_with_topic(self) -> None:
        cfg = SourceConfig(
            name="GitHub Trending",
            type="api",
            url="https://api.github.com/search/repositories",
            settings={
                "query_param": "q",
                "json_path": "items",
                "field_mapping": {
                    "id": "id",
                    "title": "full_name",
                    "content": "description",
                    "source_url": "html_url",
                },
            },
        )
        handler = _build_handler(cfg)
        resp = httpx.Response(
            200,
            json={"items": [{"id": 1, "full_name": "octo/repo", "description": "d"}]},
            request=httpx.Request("GET", cfg.url),
        )
        with patch("httpx.get", return_value=resp) as mock_get:
            items = _fetch_items(handler, cfg, topic="AI", limit=5)

        assert len(items) == 1
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["q"] == "AI"
