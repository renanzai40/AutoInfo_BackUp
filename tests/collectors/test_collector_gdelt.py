"""Tests for the GDELT DOC 2.0 news handler.

Uses ``unittest.mock.patch`` to mock HTTP responses so tests are
deterministic and fast — no real API calls.

Test categories:
- Handler construction and config parsing
- Fetch with mock HTTP responses
- Field mapping correctness
- Error handling (HTTP errors, network errors, non-JSON)
- Rate limiting (1 req / 5s)
- to_item conversion
- requires_key check
- Empty / edge-case handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from autoinfo.collectors.gdelt import GDELTHandler
from autoinfo.models import Item

# ---------------------------------------------------------------------------
# Sample GDELT DOC 2.0 API response (headline-level articles)
# ---------------------------------------------------------------------------

SAMPLE_GDELT_RESPONSE: dict[str, Any] = {
    "articles": [
        {
            "url": "https://example.com/news/ai-regulation-2025",
            "url_md5": "abc123def456",
            "title": "EU Passes Comprehensive AI Regulation Framework",
            "seendate": "20250715T120000Z",
            "sourcename": "TechCrunch",
            "domain": "techcrunch.com",
            "language": "English",
            "socialimage": "https://example.com/images/ai-reg.jpg",
            "tone": "-2.5",
        },
        {
            "url": "https://reuters.com/article/climate-summit",
            "url_md5": "789ghi012jkl",
            "title": "World Leaders Gather for Climate Summit in Geneva",
            "seendate": "20250714T080000Z",
            "sourcename": "Reuters",
            "domain": "reuters.com",
            "language": "English",
            "socialimage": "https://reuters.com/images/climate.jpg",
            "tone": "1.8",
        },
    ]
}

SAMPLE_EMPTY_RESPONSE: dict[str, Any] = {
    "articles": [],
}

SAMPLE_SINGLE_RESPONSE: dict[str, Any] = {
    "articles": [
        {
            "url": "https://bbc.com/news/tech-innovation",
            "url_md5": "single_md5_001",
            "title": "AI Breakthrough in Medical Diagnostics",
            "seendate": "20250801T090000Z",
            "sourcename": "BBC News",
            "domain": "bbc.com",
            "language": "English",
            "socialimage": "https://bbc.com/images/ai-med.jpg",
            "tone": "3.2",
        },
    ]
}

SAMPLE_RESPONSE_NO_URL: dict[str, Any] = {
    "articles": [
        {
            "title": "Article With No URL Field",
        },
    ]
}

SAMPLE_RESPONSE_NO_DOMAIN: dict[str, Any] = {
    "articles": [
        {
            "url": "https://unknown-news.example.org/article/42",
            "url_md5": "no_domain_md5",
            "title": "Local News Without Domain Field",
            "seendate": "20250720T000000Z",
            "sourcename": "Unknown News",
            "language": "English",
        }
    ]
}

SAMPLE_RESPONSE_MISSING_FIELDS: dict[str, Any] = {
    "articles": [
        {
            "url": "https://bare-minimum.example.com/",
            "title": "Bare Minimum Article",
        },
        {
            "url": "https://example.com/full-article",
            "url_md5": "full_md5_002",
            "title": "Full Featured Article",
            "seendate": "20250730T120000Z",
            "sourcename": "Example News",
            "domain": "example.com",
            "language": "French",
            "socialimage": "https://example.com/img.jpg",
            "tone": "0.0",
        },
    ]
}


# ---------------------------------------------------------------------------
# Helper: create a mock httpx.Response
# ---------------------------------------------------------------------------


def _mock_response(data: dict[str, Any]) -> MagicMock:
    """Create a mock httpx.Response that returns the given JSON data."""
    mock = MagicMock(spec=httpx.Response)
    mock.json.return_value = data
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests: handler existence and construction
# ---------------------------------------------------------------------------


class TestGDELTHandlerExists:
    """Verify the handler class is importable and constructable."""

    def test_handler_is_importable(self) -> None:
        """GDELTHandler should be accessible from the module."""
        assert GDELTHandler is not None

    def test_creates_with_default_config(self) -> None:
        """Handler instantiates with empty config dict."""
        handler = GDELTHandler({})
        assert handler.source_type == "gdelt"
        assert handler.config == {}
        assert handler.query == ""
        assert handler.timespan == "3m"
        assert handler.maxrecords == 25

    def test_creates_with_full_config(self) -> None:
        """Handler picks up all config keys correctly."""
        config = {
            "query": "AI regulation",
            "timespan": "7d",
            "maxrecords": 100,
        }
        handler = GDELTHandler(config)
        assert handler.config == config
        assert handler.query == "AI regulation"
        assert handler.timespan == "7d"
        assert handler.maxrecords == 100

    def test_creates_with_none_config(self) -> None:
        """Handler instantiates with None config (uses empty dict)."""
        handler = GDELTHandler(None)  # type: ignore[arg-type]
        assert handler.config == {}
        assert handler.query == ""

    def test_maxrecords_capped_at_250(self) -> None:
        """maxrecords should be capped at 250 (GDELT hard limit)."""
        handler = GDELTHandler({"maxrecords": 500})
        assert handler.maxrecords == 250

    def test_source_type_is_gdelt(self) -> None:
        """The source_type class attribute must be 'gdelt'."""
        assert GDELTHandler.source_type == "gdelt"

    def test_subclass_of_base_handler(self) -> None:
        """GDELTHandler should be a subclass of BaseHandler."""
        from autoinfo.collectors.base import BaseHandler

        assert issubclass(GDELTHandler, BaseHandler)


# ---------------------------------------------------------------------------
# Tests: fetch returns a list
# ---------------------------------------------------------------------------


class TestGDELTFetch:
    """Tests for the fetch method."""

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_returns_list(self, mock_get: MagicMock) -> None:
        """fetch() should return a list of dicts."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="AI regulation", limit=10)

        assert isinstance(items, list)
        assert len(items) == 2

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_each_item_is_dict(self, mock_get: MagicMock) -> None:
        """Each returned item must be a dict."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="AI regulation", limit=10)

        for item in items:
            assert isinstance(item, dict)

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_respects_limit(self, mock_get: MagicMock) -> None:
        """fetch should respect the limit argument."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="AI regulation", limit=1)

        assert len(items) == 1

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_uses_correct_endpoint(self, mock_get: MagicMock) -> None:
        """fetch should call the GDELT DOC 2.0 API with correct params."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler({"timespan": "7d"})
        handler.fetch(query="climate policy", limit=50)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "api.gdeltproject.org/api/v2/doc/doc" in url
        assert "query=climate+policy" in url
        assert "mode=artlist" in url
        assert "format=json" in url
        assert "maxrecords=50" in url
        assert "timespan=7d" in url

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_uses_configured_query(self, mock_get: MagicMock) -> None:
        """When no query argument is passed, uses self.query."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler({"query": "configured search"})
        handler.fetch(limit=5)

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "query=configured+search" in url

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_query_argument_overrides_config(self, mock_get: MagicMock) -> None:
        """Passing query as argument should override config.query."""
        mock_get.return_value = _mock_response(SAMPLE_GDELT_RESPONSE)

        handler = GDELTHandler({"query": "configured search"})
        handler.fetch(query="overridden search", limit=5)

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "query=overridden+search" in url


# ---------------------------------------------------------------------------
# Tests: empty response / edge cases
# ---------------------------------------------------------------------------


class TestGDELTFetchEmpty:
    """Tests for empty or no-result responses."""

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_handles_empty_results(self, mock_get: MagicMock) -> None:
        """An empty articles list should return an empty list."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="NONEXISTENT_QUERY_99999", limit=10)

        assert items == []

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_handles_missing_articles_key(self, mock_get: MagicMock) -> None:
        """Response without an 'articles' key should return empty list."""
        mock_get.return_value = _mock_response({})

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items == []

    def test_fetch_limit_zero_returns_empty(self) -> None:
        """A limit of 0 should result in an empty list without API call."""
        handler = GDELTHandler({"query": "test"})
        items = handler.fetch(query="test", limit=0)

        assert items == []

    def test_fetch_empty_query_returns_empty(self) -> None:
        """With an empty query, fetch should return empty list and log warning."""
        handler = GDELTHandler()
        items = handler.fetch(query="", limit=10)

        assert items == []

    def test_fetch_empty_query_no_config_returns_empty(self) -> None:
        """With no query passed and no config query, return empty."""
        handler = GDELTHandler({})
        items = handler.fetch(limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: field mapping
# ---------------------------------------------------------------------------


class TestGDELTFieldMapping:
    """Tests for mapping GDELT JSON fields to standardised item format."""

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_id(self, mock_get: MagicMock) -> None:
        """id should come from url_md5 field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["id"] == "single_md5_001"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_title(self, mock_get: MagicMock) -> None:
        """title should come from title field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["title"] == "AI Breakthrough in Medical Diagnostics"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_source_url(self, mock_get: MagicMock) -> None:
        """source_url should come from url field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["source_url"] == "https://bbc.com/news/tech-innovation"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_published_date(self, mock_get: MagicMock) -> None:
        """published_date should come from seendate."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["published_date"] == "20250801T090000Z"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_source_name(self, mock_get: MagicMock) -> None:
        """source_name should come from sourcename."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["source_name"] == "BBC News"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_domain(self, mock_get: MagicMock) -> None:
        """domain should come from domain field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["domain"] == "bbc.com"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_tone(self, mock_get: MagicMock) -> None:
        """tone should be parsed as float from tone field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items[0]["tone"] == 3.2

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_all_expected_fields_present(self, mock_get: MagicMock) -> None:
        """Every returned item must have all expected keys."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        expected_fields = {
            "id", "title", "content", "source_url", "published_date",
            "source_name", "domain", "language", "image_url", "tone",
        }
        for item in items:
            for field in expected_fields:
                assert field in item, f"Item missing field: {field}"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_missing_domain_falls_back_to_url(self, mock_get: MagicMock) -> None:
        """When domain field is missing, extract from url."""
        mock_get.return_value = _mock_response(SAMPLE_RESPONSE_NO_DOMAIN)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        # The mapped domain should be empty since extraction happens
        # in to_item(), not _map_article()
        assert items[0]["domain"] == ""

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_field_mapping_missing_fields_get_defaults(self, mock_get: MagicMock) -> None:
        """Missing fields should get empty string defaults."""
        mock_get.return_value = _mock_response(SAMPLE_RESPONSE_MISSING_FIELDS)

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert len(items) == 2
        # First item has bare minimum fields
        assert items[0]["title"] == "Bare Minimum Article"
        assert items[0]["id"] == str(hash("https://bare-minimum.example.com/"))
        assert items[0]["source_url"] == "https://bare-minimum.example.com/"
        assert items[0]["published_date"] == ""
        # Second item has all fields
        assert items[1]["id"] == "full_md5_002"
        assert items[1]["title"] == "Full Featured Article"
        assert items[1]["source_name"] == "Example News"


# ---------------------------------------------------------------------------
# Tests: error handling (graceful degradation)
# ---------------------------------------------------------------------------


class TestGDELTErrorHandling:
    """Tests for HTTP errors, non-JSON responses, and network failures."""

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_http_error_returns_empty(self, mock_get: MagicMock) -> None:
        """HTTP errors should return empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_get.return_value = mock_response

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items == []

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_network_error_returns_empty(self, mock_get: MagicMock) -> None:
        """Network errors should return empty list."""
        mock_get.side_effect = httpx.NetworkError("Connection refused")

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items == []

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_timeout_returns_empty(self, mock_get: MagicMock) -> None:
        """Timeout errors should return empty list gracefully."""
        mock_get.side_effect = httpx.TimeoutException(
            "Request timed out",
            request=MagicMock(),
        )

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items == []

    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_fetch_non_json_response_handled_gracefully(self, mock_get: MagicMock) -> None:
        """If API returns non-JSON, handle gracefully with empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = ValueError("Expecting value: line 1 column 1")
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = GDELTHandler()
        items = handler.fetch(query="test", limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: rate limiting (1 req / 5s)
# ---------------------------------------------------------------------------


class TestGDELTRateLimit:
    """Tests for rate limiter behaviour."""

    @patch("autoinfo.collectors.gdelt.time.sleep")
    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_rate_limit_first_call_no_sleep(
        self, mock_get: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """First call should not block (no previous request recorded)."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        handler = GDELTHandler()

        handler.fetch(query="test", limit=5)

        # First call should not trigger sleep
        mock_sleep.assert_not_called()

    @patch("autoinfo.collectors.gdelt.time.sleep")
    @patch("autoinfo.collectors.gdelt.time.time")
    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_rate_limit_enforces_5s_min_interval(
        self, mock_get: MagicMock, mock_time: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Back-to-back calls should be spaced by at least 5 seconds."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        # First call: time returns 1000.0
        mock_time.return_value = 1000.0
        handler = GDELTHandler()
        handler.fetch(query="test", limit=5)
        # After first call, _last_request_time should be 1000.0

        # Second call: time returns 1001.0 (only 1s elapsed)
        mock_time.return_value = 1001.0
        handler.fetch(query="test", limit=5)

        # Should have called sleep for ~4 seconds (5 - 1)
        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg >= 3.9, f"Expected sleep >= 3.9s, got {sleep_arg}"

    @patch("autoinfo.collectors.gdelt.time.sleep")
    @patch("autoinfo.collectors.gdelt.time.time")
    @patch("autoinfo.collectors.gdelt.httpx.get")
    def test_rate_limit_no_sleep_when_enough_time_elapsed(
        self, mock_get: MagicMock, mock_time: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """When enough time has elapsed, no sleep should occur."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        # First call: time = 1000.0
        mock_time.return_value = 1000.0
        handler = GDELTHandler()
        handler.fetch(query="test", limit=5)

        # Second call: time = 1010.0 (10s elapsed, > 5s interval)
        mock_time.return_value = 1010.0
        handler.fetch(query="test", limit=5)

        # Should not sleep since 10s > 5s
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: to_item conversion
# ---------------------------------------------------------------------------


class TestGDELTToItem:
    """Tests for ``GDELTHandler.to_item()``."""

    def test_to_item_complete(self) -> None:
        """A fully populated article dict converts to a correct Item."""
        handler = GDELTHandler()
        article = {
            "id": "abc123def456",
            "title": "EU Passes Comprehensive AI Regulation Framework",
            "content": "EU Passes Comprehensive AI Regulation Framework",
            "source_url": "https://example.com/news/ai-regulation-2025",
            "published_date": "20250715T120000Z",
            "source_name": "TechCrunch",
            "domain": "techcrunch.com",
            "language": "English",
            "image_url": "https://example.com/images/ai-reg.jpg",
            "tone": -2.5,
        }

        item = handler.to_item(article)

        assert isinstance(item, Item)
        assert item.id == "abc123def456"
        assert item.source_name == "gdelt"
        assert item.source_type == "gdelt"
        assert item.source_platform == "gdelt"
        assert item.source_url == "https://example.com/news/ai-regulation-2025"
        assert item.title == "EU Passes Comprehensive AI Regulation Framework"
        assert item.content == "EU Passes Comprehensive AI Regulation Framework"
        assert item.content_type == "text"
        assert item.collected_at == "20250715T120000Z"
        assert item.domain == "techcrunch.com"
        assert item.language == "English"
        assert "gdelt_article_id" in item.raw_data
        assert item.raw_data["gdelt_article_id"] == "abc123def456"
        assert item.raw_data["source_name"] == "TechCrunch"
        assert item.raw_data["article_domain"] == "techcrunch.com"
        assert item.raw_data["published_date"] == "20250715T120000Z"
        assert item.raw_data["image_url"] == "https://example.com/images/ai-reg.jpg"
        assert item.raw_data["tone"] == -2.5

    def test_to_item_empty_id_uses_uuid(self) -> None:
        """When id is empty, a UUID should be generated as the item id."""
        handler = GDELTHandler()
        article = {
            "id": "",
            "title": "No ID Article",
            "content": "",
            "source_url": "",
            "published_date": "",
            "source_name": "",
            "domain": "",
            "language": "",
            "image_url": "",
            "tone": 0.0,
        }

        item = handler.to_item(article)

        assert item.id
        assert item.id != ""
        assert "-" in item.id  # UUID contains hyphens

    def test_to_item_extracts_domain_from_url(self) -> None:
        """When domain field is empty, extract from source_url."""
        handler = GDELTHandler()
        article = {
            "id": "test_md5",
            "title": "Domain from URL Test",
            "content": "",
            "source_url": "https://www.nytimes.com/article/test",
            "published_date": "",
            "source_name": "NYT",
            "domain": "",  # Empty — should extract from URL
            "language": "",
            "image_url": "",
            "tone": 0.0,
        }

        item = handler.to_item(article)

        assert item.domain == "www.nytimes.com"

    def test_to_item_empty_source_url_handled(self) -> None:
        """When source_url is empty, it defaults to empty string."""
        handler = GDELTHandler()
        article = {
            "id": "123",
            "title": "No URL",
            "content": "",
            "source_url": "",
            "published_date": "",
            "source_name": "",
            "domain": "",
            "language": "",
            "image_url": "",
            "tone": 0.0,
        }

        item = handler.to_item(article)

        assert item.source_url == ""

    def test_to_item_minimal_article(self) -> None:
        """An article dict with only id and title converts correctly."""
        handler = GDELTHandler()
        article = {
            "id": "42",
            "title": "Minimal",
            "content": "",
            "source_url": "",
            "published_date": "",
            "source_name": "",
            "domain": "",
            "language": "",
            "image_url": "",
            "tone": 0.0,
        }

        item = handler.to_item(article)

        assert item.id == "42"
        assert item.title == "Minimal"
        assert item.source_type == "gdelt"


# ---------------------------------------------------------------------------
# Tests: requires_key
# ---------------------------------------------------------------------------


class TestGDELTRequiresKey:
    """Tests for requires_key static method."""

    def test_requires_key_returns_false(self) -> None:
        """GDELT DOC 2.0 API is free — requires_key should return False."""
        assert GDELTHandler.requires_key() is False


# ---------------------------------------------------------------------------
# Tests: fetch_depth=fulltext article body enrichment
# ---------------------------------------------------------------------------


class TestGDELTFulltext:
    """Tests for ``fetch_depth="fulltext"`` article body enrichment.

    When fulltext is enabled, each article's ``source_url`` is fetched via
    the web.py trafilatura path and the title-only content is replaced by
    the extracted article body (truncated to the 8000-char cap).  Failures
    degrade per-article to the title — one blocked URL must never break
    the batch.  The default (non-fulltext) behavior is unchanged.
    """

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_fulltext_replaces_title_with_article_body(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """Fulltext content should come from the fetched article body."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)
        mock_item = MagicMock()
        mock_item.content = "Full article body fetched from the source page."
        mock_web.return_value = [mock_item]

        handler = GDELTHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="test", limit=10)

        assert (
            items[0]["content"]
            == "Full article body fetched from the source page."
        )
        mock_web.assert_called_once_with("https://bbc.com/news/tech-innovation")

        item = handler.to_item(items[0])
        assert item.content == "Full article body fetched from the source page."

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_fulltext_empty_extraction_keeps_title(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """When extraction yields nothing, the title-only content is kept."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)
        mock_web.return_value = []

        handler = GDELTHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="test", limit=10)

        assert items[0]["content"] == "AI Breakthrough in Medical Diagnostics"
        assert items[0]["title"] == "AI Breakthrough in Medical Diagnostics"

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_fulltext_extraction_raising_keeps_title(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """A raising extraction must degrade to the title, not break the batch."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)
        mock_web.side_effect = RuntimeError("network down")

        handler = GDELTHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="test", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == items[0]["title"]

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_fulltext_content_truncated_at_cap(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """Fetched bodies longer than 8000 chars must be truncated."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)
        mock_item = MagicMock()
        mock_item.content = "x" * 20000
        mock_web.return_value = [mock_item]

        handler = GDELTHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="test", limit=10)

        assert len(items[0]["content"]) == 8000

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_default_fetch_depth_does_not_fetch_fulltext(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """Default (non-fulltext) behavior must remain title-only."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = GDELTHandler()  # default fetch_depth
        items = handler.fetch(query="test", limit=10)

        assert items[0]["content"] == "AI Breakthrough in Medical Diagnostics"
        mock_web.assert_not_called()

    @patch("autoinfo.collectors.gdelt.httpx.get")
    @patch("autoinfo.collectors.web.WebHandler.fetch")
    def test_fulltext_missing_url_keeps_title(
        self, mock_web: MagicMock, mock_get: MagicMock
    ) -> None:
        """Articles without a source_url keep their title-only content."""
        mock_get.return_value = _mock_response(SAMPLE_RESPONSE_NO_URL)

        handler = GDELTHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="test", limit=10)

        assert items[0]["content"] == "Article With No URL Field"
        mock_web.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: note method
# ---------------------------------------------------------------------------


class TestGDELTNote:
    """Tests for the note static method."""

    def test_note_returns_headline_level_warning(self) -> None:
        """note() should mention the headline-level limitation."""
        note = GDELTHandler.note()
        assert note is not None
        assert "HEADLINE" in note
        assert "full" in note.lower() or "not" in note.lower()

    def test_note_mentions_gdelt_doc(self) -> None:
        """note() should reference GDELT DOC."""
        note = GDELTHandler.note()
        assert note is not None
        assert "GDELT" in note
