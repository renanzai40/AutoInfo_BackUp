# mypy: ignore-errors
"""Tests for the generic HTTP JSON API collector (:class:`HttpApiHandler`).

Verifies:
* Handler instantiation and configuration
* JSON response parsing with configurable json_path
* Field mapping with dot-notation and array indexing
* Dispatch routing in ``collect.py`` for non-pubmed API sources
* Error handling (network errors, malformed JSON, missing fields)
* CrossRef-specific config
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collect import _build_handler
from autoinfo.collectors.base import SourceFailure
from autoinfo.collectors.http_api import HttpApiHandler, _get_field, _traverse_json
from autoinfo.config import SourceConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crossref_config() -> SourceConfig:
    return SourceConfig(
        name="CrossRef",
        type="api",
        url="https://api.crossref.org/works",
        settings={
            "query_param": "query",
            "json_path": "message.items",
            "field_mapping": {
                "id": "DOI",
                "title": "title",
                "content": "abstract",
                "source_url": "URL",
            },
        },
    )


@pytest.fixture
def hackernews_config() -> SourceConfig:
    return SourceConfig(
        name="HackerNews API",
        type="api",
        url="https://hacker-news.firebasedatabase.app/v0",
        settings={
            "json_path": "",
            "field_mapping": {
                "id": "id",
                "title": "title",
                "content": "content",
                "source_url": "url",
            },
        },
    )


@pytest.fixture
def stacked_config() -> SourceConfig:
    return SourceConfig(
        name="Stack Exchange",
        type="api",
        url="https://api.stackexchange.com/2.3/questions?order=desc&sort=activity&site=stackoverflow&pagesize=10",
        settings={
            "query_param": "q",
            "json_path": "items",
            "field_mapping": {
                "id": "question_id",
                "title": "title",
                "content": "body_markdown",
                "source_url": "link",
            },
            "api_key": "test-stackexchange-key",
            "auth_mode": "query",
        },
    )


@pytest.fixture
def minimal_config() -> SourceConfig:
    """SourceConfig with no settings — tests defaults."""
    return SourceConfig(
        name="Minimal API",
        type="api",
        url="https://example.com/api",
    )


# ---------------------------------------------------------------------------
# Sample response data
# ---------------------------------------------------------------------------

SAMPLE_CROSSREF_RESPONSE: dict[str, Any] = {
    "status": "ok",
    "message": {
        "total-results": 2,
        "items": [
            {
                "DOI": "10.1234/crossref.001",
                "title": "A Study of CRISPR Applications",
                "abstract": "This paper explores CRISPR gene editing techniques.",
                "URL": "https://doi.org/10.1234/crossref.001",
                "author": [{"given": "Jane", "family": "Doe"}],
            },
            {
                "DOI": "10.1234/crossref.002",
                "title": "Advances in Genome Engineering",
                "abstract": "A review of recent advances in genome engineering.",
                "URL": "https://doi.org/10.1234/crossref.002",
                "author": [{"given": "John", "family": "Smith"}],
            },
        ],
    },
}

SAMPLE_CROSSREF_SINGLE: dict[str, Any] = {
    "status": "ok",
    "message": {
        "total-results": 1,
        "items": [
            {
                "DOI": "10.1234/single.001",
                "title": "Single Paper",
                "abstract": "Short abstract.",
                "URL": "https://doi.org/10.1234/single.001",
            },
        ],
    },
}

SAMPLE_SE_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "question_id": 12345,
            "title": "How to use async in Python?",
            "body_markdown": "I need help with async/await in Python 3.",
            "link": "https://stackoverflow.com/q/12345",
        },
    ],
}

SAMPLE_NO_JSON_PATH_RESPONSE: dict[str, Any] = {
    "id": 999,
    "title": "Single Item Response",
    "content": "This API returns a single item, not a list.",
    "url": "https://example.com/item/999",
}


# ---------------------------------------------------------------------------
# Tests: _traverse_json helper
# ---------------------------------------------------------------------------


class TestTraverseJson:
    def test_simple_path(self) -> None:
        data = {"a": {"b": {"c": 42}}}
        assert _traverse_json(data, "a.b.c") == 42

    def test_single_level(self) -> None:
        data = {"items": [1, 2, 3]}
        assert _traverse_json(data, "items") == [1, 2, 3]

    def test_missing_key_returns_none(self) -> None:
        data = {"a": {"b": 1}}
        assert _traverse_json(data, "a.c") is None

    def test_intermediate_non_dict_returns_none(self) -> None:
        data = {"a": "not_a_dict"}
        assert _traverse_json(data, "a.b.c") is None


# ---------------------------------------------------------------------------
# Tests: _get_field helper
# ---------------------------------------------------------------------------


class TestGetField:
    def test_simple_key(self) -> None:
        data = {"DOI": "10.1234/test"}
        assert _get_field(data, "DOI") == "10.1234/test"

    def test_missing_key_returns_empty(self) -> None:
        data = {"title": "Hello"}
        assert _get_field(data, "missing") == ""

    def test_array_index(self) -> None:
        data = {"title": ["First Title", "Second Title"]}
        assert _get_field(data, "title[0]") == "First Title"
        assert _get_field(data, "title[1]") == "Second Title"

    def test_array_index_out_of_range(self) -> None:
        data = {"title": ["Only One"]}
        assert _get_field(data, "title[5]") == ""

    def test_array_index_non_list(self) -> None:
        data = {"title": "Not a list"}
        assert _get_field(data, "title[0]") == ""

    def test_dot_path(self) -> None:
        data = {"author": {"name": "Jane", "email": "jane@test.com"}}
        assert _get_field(data, "author.name") == "Jane"
        assert _get_field(data, "author.email") == "jane@test.com"

    def test_dot_path_missing(self) -> None:
        data = {"author": {"name": "Jane"}}
        assert _get_field(data, "author.email") == ""

    def test_empty_path(self) -> None:
        assert _get_field({"x": 1}, "") == ""

    def test_nested_array_in_dot_path(self) -> None:
        data = {"authors": [{"name": "Jane"}, {"name": "John"}]}
        assert _get_field(data, "authors[1].name") == "John"


# ---------------------------------------------------------------------------
# Tests: HttpApiHandler construction
# ---------------------------------------------------------------------------


class TestHttpApiHandlerConstruction:
    def test_creates_with_crossref_config(self, crossref_config: SourceConfig) -> None:
        handler = HttpApiHandler(crossref_config)
        assert handler.source_name == "CrossRef"
        assert handler.source_config is crossref_config
        assert handler._handler_type == "HttpApiHandler"

    def test_creates_with_minimal_config(self, minimal_config: SourceConfig) -> None:
        handler = HttpApiHandler(minimal_config)
        assert handler.source_name == "Minimal API"
        assert handler._settings == {}


# ---------------------------------------------------------------------------
# Tests: HttpApiHandler.fetch with mocked httpx
# ---------------------------------------------------------------------------


class TestHttpApiHandlerFetch:
    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_crossref_items(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CROSSREF_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        items = handler.fetch(crossref_config.url, query="CRISPR", limit=5)

        assert len(items) == 2
        assert items[0].id == "10.1234/crossref.001"
        assert items[0].title == "A Study of CRISPR Applications"
        assert items[0].content == "This paper explores CRISPR gene editing techniques."
        assert items[0].source_url == "https://doi.org/10.1234/crossref.001"
        assert items[0].source_type == "api"
        assert items[0].source_name == "CrossRef"

        # Verify the request was made with correct parameters
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["query"] == "CRISPR"

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_no_json_path_treats_response_as_single_item(
        self, mock_get: MagicMock, hackernews_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_NO_JSON_PATH_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(hackernews_config)
        items = handler.fetch(hackernews_config.url, limit=5)

        assert len(items) == 1
        assert items[0].id == 999  # JSON integer id comes through as-is
        assert items[0].title == "Single Item Response"
        assert items[0].content == "This API returns a single item, not a list."

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_with_api_key_as_query_param(
        self, mock_get: MagicMock, stacked_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_SE_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(stacked_config)
        items = handler.fetch(stacked_config.url, query="async", limit=5)

        assert len(items) == 1
        assert items[0].id == 12345
        assert items[0].title == "How to use async in Python?"

        # API key should be in query params, not header
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["api_key"] == "test-stackexchange-key"
        assert "q" in call_kwargs["params"]

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_empty_response(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {"message": {"items": []}}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        items = handler.fetch(crossref_config.url, query="NONEXISTENT", limit=5)

        assert items == []

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_respects_limit(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        # Create a response with many items
        many_items: dict[str, list[dict[str, Any]]] = {"message": {"items": []}}
        for i in range(10):
            many_items["message"]["items"].append({
                "DOI": f"10.1234/test.{i:03d}",
                "title": f"Paper {i}",
                "abstract": f"Abstract {i}",
                "URL": f"https://doi.org/10.1234/test.{i:03d}",
            })

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = many_items
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        items = handler.fetch(crossref_config.url, limit=3)

        assert len(items) == 3

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_network_error_raises_source_failure(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        mock_get.side_effect = httpx.NetworkError("Connection refused")

        handler = HttpApiHandler(crossref_config)
        with pytest.raises(SourceFailure):
            handler.fetch(crossref_config.url, query="test", limit=5)

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_http_error_raises_source_failure(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        with pytest.raises(SourceFailure):
            handler.fetch(crossref_config.url, query="test", limit=5)

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_malformed_json_raises_source_failure(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        with pytest.raises(SourceFailure):
            handler.fetch(crossref_config.url, query="test", limit=5)

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_skips_malformed_items(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        """Items with no mapped title AND no content are dropped (issue #180)."""
        response = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/good.001",
                        "title": "Good Paper",
                        "abstract": "Good abstract.",
                        "URL": "https://doi.org/10.1234/good.001",
                    },
                    {
                        # Missing title + abstract -> empty item, dropped
                        "DOI": "10.1234/bad.001",
                    },
                ],
            },
        }

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(crossref_config)
        items = handler.fetch(crossref_config.url, query="test", limit=5)

        # Only the good item survives; the empty one is dropped and counted.
        assert len(items) == 1
        assert items[0].title == "Good Paper"
        assert handler.dropped_empty_items == 1

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_with_api_key_header_mode(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        config = SourceConfig(
            name="Protected API",
            type="api",
            url="https://api.example.com/data",
            settings={
                "api_key": "secret-key-123",
                "auth_mode": "header",
                "json_path": "results",
                "field_mapping": {
                    "id": "id",
                    "title": "name",
                },
            },
        )

        response_data = {"results": [{"id": "1", "name": "Test Item"}]}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, limit=5)

        assert len(items) == 1
        assert items[0].title == "Test Item"

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer secret-key-123"

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_passes_configured_url_verbatim(
        self, mock_get: MagicMock, stacked_config: SourceConfig
    ) -> None:
        """Regression: httpx.get must receive the configured URL exactly,
        not a bare base. Catches missing urljoin / items_path bugs."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {"items": []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(stacked_config)
        handler.fetch(stacked_config.url, limit=5)

        # First positional arg to httpx.get MUST be the full configured URL
        url_arg = mock_get.call_args.args[0]
        assert url_arg == stacked_config.url, (
            f"Expected httpx.get URL to be the configured URL exactly.\n"
            f"  Configured: {stacked_config.url}\n"
            f"  Actual:     {url_arg}"
        )
        assert "questions" in url_arg, "URL must include /questions path"
        assert "site=stackoverflow" in url_arg, "URL must include site param"

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_json_path_root_array_returns_all_items(
        self, mock_get: MagicMock
    ) -> None:
        """json_path: "$" treats the whole response body as the item array
        (e.g. Mastodon public timeline returns a top-level JSON array)."""
        config = SourceConfig(
            name="Mastodon API",
            type="api",
            url="https://mastodon.example/api/v1/timelines/public",
            settings={
                "json_path": "$",
                "field_mapping": {
                    "id": "id",
                    "title": "content",
                    "content": "content",
                    "source_url": "url",
                },
            },
        )

        response_body = [
            {
                "id": "1",
                "content": "<p>First toot</p>",
                "url": "https://mastodon.example/@alice/1",
            },
            {
                "id": "2",
                "content": "<p>Second toot</p>",
                "url": "https://mastodon.example/@bob/2",
            },
            {
                "id": "3",
                "content": "<p>Third toot</p>",
                "url": "https://mastodon.example/@carol/3",
            },
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = response_body
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, limit=10)

        assert len(items) == 3
        assert [item.id for item in items] == ["1", "2", "3"]
        assert items[0].source_url == "https://mastodon.example/@alice/1"

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_json_path_dollar_nested_array(
        self, mock_get: MagicMock
    ) -> None:
        """json_path: "$.field" still resolves an array under a dict key
        (regression — Bluesky-style ``"$.posts"``)."""
        config = SourceConfig(
            name="Bluesky API",
            type="api",
            url="https://bsky.example/xrpc/app.bsky.feed.getTimeline",
            settings={
                "json_path": "$.posts",
                "field_mapping": {
                    "id": "cid",
                    "title": "post.text",
                    "content": "post.text",
                    "source_url": "uri",
                },
            },
        )

        response_body = {
            "cursor": "next-page",
            "posts": [
                {
                    "cid": "cid-1",
                    "uri": "at://did:plc:alice",
                    "post": {"text": "First post"},
                },
                {
                    "cid": "cid-2",
                    "uri": "at://did:plc:bob",
                    "post": {"text": "Second post"},
                },
            ],
        }
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = response_body
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, limit=10)

        assert len(items) == 2
        assert [item.id for item in items] == ["cid-1", "cid-2"]
        assert items[0].title == "First post"


# ---------------------------------------------------------------------------
# Tests: HTTP API dispatch in collect.py
# ---------------------------------------------------------------------------


class TestHttpApiDispatch:
    def test_non_pubmed_api_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="CrossRef",
            type="api",
            url="https://api.crossref.org/works",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)
        assert handler.source_name == "CrossRef"

    def test_unpaywall_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="Unpaywall",
            type="api",
            url="https://api.unpaywall.org/v2",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)
        assert handler.source_name == "Unpaywall"

    def test_alpha_vantage_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="Alpha Vantage",
            type="api",
            url="https://www.alphavantage.co/query",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)

    def test_github_trending_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="GitHub Trending",
            type="api",
            url="https://api.github.com/repos",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)

    def test_hackernews_api_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="HackerNews API",
            type="api",
            url="https://hacker-news.firebaseio.com/v0",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)

    def test_pubmed_still_dispatches_to_pubmed_handler(self) -> None:
        config = SourceConfig(
            name="pubmed",
            type="api",
            url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        )
        handler = _build_handler(config)
        # PubMed should NOT be HttpApiHandler
        assert not isinstance(handler, HttpApiHandler)
        # Should still be a handler (PubMedHandler)
        assert handler is not None

    def test_producthunt_dispatches_to_http_api(self) -> None:
        config = SourceConfig(
            name="producthunt",
            type="api",
            url="https://api.producthunt.com/v2/api/graphql",
        )
        handler = _build_handler(config)
        assert isinstance(handler, HttpApiHandler)

    def test_all_financial_api_sources_dispatch(self) -> None:
        for name in ["Alpha Vantage", "FRED", "Twelve Data", "World Bank Data"]:
            config = SourceConfig(name=name, type="api", url=f"https://api.example.com/{name}")
            handler = _build_handler(config)
            assert isinstance(handler, HttpApiHandler), f"{name} should dispatch to HttpApiHandler"

    def test_all_tech_api_sources_dispatch(self) -> None:
        for name in ["GitHub Trending", "HackerNews API", "Stack Exchange", "ProductHunt"]:
            config = SourceConfig(name=name, type="api", url=f"https://api.example.com/{name}")
            handler = _build_handler(config)
            assert isinstance(handler, HttpApiHandler), f"{name} should dispatch to HttpApiHandler"


# ---------------------------------------------------------------------------
# Tests: feed-style API sources fetch without a query (AC4 collection gaps)
# ---------------------------------------------------------------------------
# Feed-style sources (fixed-URL JSON feeds like apple-music, mastodon,
# zhihu-daily, coursera, World Bank) are the API equivalent of an RSS feed:
# they carry no `query_param` setting and must fetch their configured URL
# as-is.  Query-driven sources (CrossRef, GitHub Trending, bluesky) declare
# `query_param` and need a topic.  The collect.py #182 guard must only skip
# the former — never the latter.


class TestFeedStyleApiSources:
    """Feed-style API sources fetch their fixed URL without a query."""

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_fetch_without_query_does_not_inject_q_param(
        self, mock_get: MagicMock
    ) -> None:
        """A feed-style source with no query_param must NOT get ?q= appended.

        Regression for the apple-music 404: the old default injected
        ``query_param="q"`` into a fixed-URL feed, breaking the endpoint.
        """
        config = SourceConfig(
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
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {
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
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, query="", limit=5)

        assert len(items) == 1
        call_kwargs = mock_get.call_args.kwargs
        assert "q" not in call_kwargs.get("params", {}), (
            "Feed-style source must not receive ?q= — the endpoint 404s on "
            "unexpected query params"
        )

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_query_injected_only_into_configured_query_param(
        self, mock_get: MagicMock
    ) -> None:
        """A query is injected ONLY into an explicitly configured query_param.

        Existing behaviour (CrossRef ``query_param: query``, GitHub Trending
        ``query_param: q``) is preserved; no default param name is invented.
        """
        config = SourceConfig(
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
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {
            "items": [{"id": 1, "full_name": "octo/repo", "description": "d"}]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, query="AI", limit=5)

        assert len(items) == 1
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["q"] == "AI"

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_feed_style_url_embedded_query_preserved(
        self, mock_get: MagicMock
    ) -> None:
        """A feed-style source whose URL embeds query params (Stack Exchange)
        must fetch as-is — httpx must NOT receive an empty ``params`` dict.

        Regression for the Stack Exchange 400: passing ``params={}`` to
        httpx.get strips the URL's own query string
        (``?order=desc&...&site=stackoverflow``), yielding a bare endpoint.
        When the built params dict is empty, no ``params`` kwarg may be
        passed at all.
        """
        config = SourceConfig(
            name="Stack Exchange",
            type="api",
            url="https://api.stackexchange.com/2.3/questions?order=desc&sort=activity&site=stackoverflow&pagesize=10",  # noqa: E501
            settings={
                "json_path": "items",
                "field_mapping": {
                    "id": "question_id",
                    "title": "title",
                    "content": "body",
                    "source_url": "link",
                },
            },
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {
            "items": [
                {
                    "question_id": 42,
                    "title": "Q",
                    "body": "body",
                    "link": "https://stackoverflow.com/q/42",
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, query="", limit=5)

        assert len(items) == 1
        call_kwargs = mock_get.call_args.kwargs
        # The URL itself must be passed untouched (query string intact)…
        url_arg = mock_get.call_args.args[0]
        assert "site=stackoverflow" in url_arg
        # …and an empty params dict must never reach httpx (it would strip
        # the URL's own query string → 400 on the real endpoint).
        assert "params" not in call_kwargs, (
            "Empty params dict must not be passed to httpx.get — it strips "
            "URL-embedded query params (Stack Exchange 400 regression)"
        )


# ---------------------------------------------------------------------------
# Tests: _handler_type marker for dispatch in _fetch_items
# ---------------------------------------------------------------------------


class TestHandlerMarker:
    def test_http_api_handler_has_correct_marker(self) -> None:
        config = SourceConfig(
            name="Test API",
            type="api",
            url="https://example.com/api",
        )
        handler = HttpApiHandler(config)
        assert getattr(handler, "_handler_type", "") == "HttpApiHandler"

    def test_marker_does_not_exist_on_non_http_api_handlers(self) -> None:
        """Ensure no marker leak to other handler types."""
        from autoinfo.collectors.rss import RSSHandler

        rss = RSSHandler(source_name="test-rss")
        assert getattr(rss, "_handler_type", "") == ""


# ---------------------------------------------------------------------------
# Tests: pagination
# ---------------------------------------------------------------------------


class TestPagination:
    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_pagination_fetches_multiple_pages(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        """When a page returns items, the handler requests the next page."""
        config = SourceConfig(
            name="Paginated API",
            type="api",
            url="https://api.example.com/data",
            settings={
                "json_path": "results",
                "page_param": "offset",
                "page_size": 2,
                "page_size_param": "limit",
                "max_pages": 3,
                "field_mapping": {
                    "id": "id",
                    "title": "name",
                },
            },
        )

        call_count = [0]

        def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            call_count[0] += 1
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.raise_for_status.return_value = None
            # Page 1: 2 items, Page 2: 1 item (done)
            if call_count[0] == 1:
                mock_resp.json.return_value = {
                    "results": [
                        {"id": "1", "name": "Item 1"},
                        {"id": "2", "name": "Item 2"},
                    ],
                }
            else:
                mock_resp.json.return_value = {
                    "results": [
                        {"id": "3", "name": "Item 3"},
                    ],
                }
            return mock_resp

        mock_get.side_effect = side_effect

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, limit=10)

        assert len(items) == 3
        assert [item.id for item in items] == ["1", "2", "3"]
        assert call_count[0] == 2  # 2 pages fetched (3rd not needed — chunk < page_size)

    @patch("autoinfo.collectors.http_api.httpx.get")
    def test_pagination_stops_at_limit(
        self, mock_get: MagicMock, crossref_config: SourceConfig
    ) -> None:
        config = SourceConfig(
            name="Paginated Limit API",
            type="api",
            url="https://api.example.com/data",
            settings={
                "json_path": "results",
                "page_param": "offset",
                "page_size": 5,
                "page_size_param": "limit",
                "max_pages": 10,
                "field_mapping": {
                    "id": "id",
                    "title": "name",
                },
            },
        )

        # Page returns 5 items but limit is 2
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {
            "results": [
                {"id": "1", "name": "Item 1"},
                {"id": "2", "name": "Item 2"},
                {"id": "3", "name": "Item 3"},
                {"id": "4", "name": "Item 4"},
                {"id": "5", "name": "Item 5"},
            ],
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, limit=2)

        assert len(items) == 2
        # Only 1 page call was made (limit satisfied fast)
        assert mock_get.call_count == 1
