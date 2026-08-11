"""Tests for the YouTube Data API handler.

Uses ``unittest.mock.patch`` to mock HTTP responses so tests are
deterministic and fast — no real API calls.

Test categories:
- Handler construction and config parsing
- Fetch with mock HTTP responses
- Field mapping correctness
- Error handling (HTTP errors, network errors, non-JSON, missing API key)
- Rate limiting
- to_item conversion
- requires_key check
- fetch_captions
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.youtube import YouTubeHandler
from autoinfo.models import Item

# ---------------------------------------------------------------------------
# Sample YouTube Data API v3 search response
# ---------------------------------------------------------------------------

SAMPLE_YOUTUBE_RESPONSE: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"abc123"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 42, "resultsPerPage": 10},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"etag1"',
            "id": {
                "kind": "youtube#video",
                "videoId": "dQw4w9WgXcQ",
            },
            "snippet": {
                "publishedAt": "2009-10-25T06:57:33Z",
                "channelId": "UCuAXFkgsw1L7xaCfnd5JJOw",
                "title": "Rick Astley - Never Gonna Give You Up",
                "description": "The official video for Rick Astley's classic hit.",
                "channelTitle": "Rick Astley",
                "thumbnails": {
                    "default": {
                        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
                        "width": 120,
                        "height": 90,
                    },
                    "medium": {
                        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
                        "width": 320,
                        "height": 180,
                    },
                    "high": {
                        "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                        "width": 480,
                        "height": 360,
                    },
                },
                "liveBroadcastContent": "none",
                "publishTime": "2009-10-25T06:57:33Z",
            },
        },
        {
            "kind": "youtube#searchResult",
            "etag": '"etag2"',
            "id": {
                "kind": "youtube#video",
                "videoId": "kXYiU_JCYtU",
            },
            "snippet": {
                "publishedAt": "2007-10-29T00:00:00Z",
                "channelId": "UC_xYMXx_-mAzheKyEtwM8Gg",
                "title": "Numb - Linkin Park",
                "description": "Numb from the album Meteora.",
                "channelTitle": "Linkin Park",
                "thumbnails": {
                    "default": {
                        "url": "https://i.ytimg.com/vi/kXYiU_JCYtU/default.jpg",
                        "width": 120,
                        "height": 90,
                    },
                },
                "liveBroadcastContent": "none",
                "publishTime": "2007-10-29T00:00:00Z",
            },
        },
    ],
}

SAMPLE_EMPTY_RESPONSE: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"empty456"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 0, "resultsPerPage": 0},
    "items": [],
}

SAMPLE_SINGLE_RESPONSE: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"single789"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"etag3"',
            "id": {
                "kind": "youtube#video",
                "videoId": "jNQXAC9IVRw",
            },
            "snippet": {
                "publishedAt": "2005-04-23T22:32:31Z",
                "channelId": "UC4QobU6STFB0P71PMvOGN5A",
                "title": "Me at the zoo",
                "description": "The first YouTube video ever uploaded.",
                "channelTitle": "jawed",
                "thumbnails": {
                    "default": {
                        "url": "https://i.ytimg.com/vi/jNQXAC9IVRw/default.jpg",
                        "width": 120,
                        "height": 90,
                    },
                },
                "liveBroadcastContent": "none",
                "publishTime": "2005-04-23T22:32:31Z",
            },
        },
    ],
}

SAMPLE_RESPONSE_NO_THUMBNAILS: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"nothumbs"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"etag4"',
            "id": {"kind": "youtube#video", "videoId": "noThumb123"},
            "snippet": {
                "publishedAt": "2020-01-01T00:00:00Z",
                "channelId": "UCtest",
                "title": "No Thumbnail Video",
                "description": "This video has no thumbnails configured.",
                "channelTitle": "Test Channel",
                "liveBroadcastContent": "none",
            },
        },
    ],
}

SAMPLE_RESPONSE_NO_DESCRIPTION: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"nodesc"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"etag5"',
            "id": {"kind": "youtube#video", "videoId": "noDesc456"},
            "snippet": {
                "publishedAt": "2021-06-15T12:00:00Z",
                "channelId": "UCnodesc",
                "title": "No Description",
                "channelTitle": "Node Channel",
                "thumbnails": {},
                "liveBroadcastContent": "none",
            },
        },
    ],
}

SAMPLE_MULTI_PAGE_RESPONSE_PAGE1: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"page1"',
    "nextPageToken": "CDIQAA",
    "regionCode": "US",
    "pageInfo": {"totalResults": 100, "resultsPerPage": 10},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"p1e1"',
            "id": {"kind": "youtube#video", "videoId": "video001"},
            "snippet": {
                "publishedAt": "2026-01-01T00:00:00Z",
                "channelId": "UCmulti",
                "title": "Video 001",
                "description": "First page video.",
                "channelTitle": "MultiPage Channel",
                "thumbnails": {"default": {"url": "https://i.ytimg.com/vi/video001/default.jpg"}},
                "liveBroadcastContent": "none",
            },
        },
    ],
}

SAMPLE_MULTI_PAGE_RESPONSE_PAGE2: dict[str, Any] = {
    "kind": "youtube#searchListResponse",
    "etag": '"page2"',
    "regionCode": "US",
    "pageInfo": {"totalResults": 100, "resultsPerPage": 10},
    "items": [
        {
            "kind": "youtube#searchResult",
            "etag": '"p2e1"',
            "id": {"kind": "youtube#video", "videoId": "video002"},
            "snippet": {
                "publishedAt": "2026-01-02T00:00:00Z",
                "channelId": "UCmulti2",
                "title": "Video 002",
                "description": "Second page video.",
                "channelTitle": "MultiPage Channel",
                "thumbnails": {"default": {"url": "https://i.ytimg.com/vi/video002/default.jpg"}},
                "liveBroadcastContent": "none",
            },
        },
    ],
}

# SAMPLE CAPTIONS RESPONSE
SAMPLE_CAPTIONS_RESPONSE: dict[str, Any] = {
    "kind": "youtube#captionListResponse",
    "etag": '"cap123"',
    "items": [
        {
            "kind": "youtube#caption",
            "etag": '"cetag1"',
            "id": "AUieDaYb_caption_english",
            "snippet": {
                "videoId": "dQw4w9WgXcQ",
                "lastUpdated": "2024-01-01T00:00:00Z",
                "trackKind": "standard",
                "language": "en",
                "name": "English",
                "audioTrackType": "unknown",
                "isCC": False,
                "isLarge": False,
                "isEasyReader": False,
                "isDraft": False,
                "isAutoSynced": False,
                "status": "serving",
            },
        },
    ],
}

# SRT payload returned by the captions.download endpoint (tfmt=srt)
SAMPLE_SRT_TRANSCRIPT: str = (
    "1\r\n"
    "00:00:00,000 --> 00:00:03,000\r\n"
    "Never gonna give you up\r\n"
    "Never gonna let you down\r\n"
    "\r\n"
    "2\r\n"
    "00:00:03,000 --> 00:00:06,000\r\n"
    "Never gonna run around and desert you\r\n"
)

EXPECTED_TRANSCRIPT_TEXT: str = (
    "Never gonna give you up Never gonna let you down\n"
    "Never gonna run around and desert you"
)


# ---------------------------------------------------------------------------
# Helper: create a mock httpx.Response
# ---------------------------------------------------------------------------


def _mock_response(data: dict[str, Any]) -> MagicMock:
    """Create a mock httpx.Response that returns the given JSON data."""
    mock = MagicMock(spec=httpx.Response)
    mock.json.return_value = data
    mock.raise_for_status.return_value = None
    return mock


def _mock_text_response(text: str) -> MagicMock:
    """Create a mock httpx.Response that returns raw text (e.g. SRT)."""
    mock = MagicMock(spec=httpx.Response)
    mock.text = text
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests: handler existence and construction
# ---------------------------------------------------------------------------


class TestYouTubeHandlerExists:
    """Verify the handler class is importable and constructable."""

    def test_handler_is_importable(self) -> None:
        """YouTubeHandler should be accessible from youtube module."""
        assert YouTubeHandler is not None

    def test_creates_with_default_config(self) -> None:
        """Handler instantiates with empty config dict."""
        handler = YouTubeHandler({})
        assert handler.source_type == "youtube"
        assert handler.config == {}
        assert handler.api_key == ""
        assert handler.query == ""
        assert handler.max_rps == 1.0

    def test_creates_with_full_config(self) -> None:
        """Handler picks up all config keys correctly."""
        config = {
            "query": "machine learning",
            "api_key": "test-key-123",
            "channel_id": "UCsomeChannel",
            "order": "date",
            "max_rps": 2.5,
        }
        handler = YouTubeHandler(config)
        assert handler.config == config
        assert handler.api_key == "test-key-123"
        assert handler.query == "machine learning"
        assert handler.channel_id == "UCsomeChannel"
        assert handler.order == "date"
        assert handler.max_rps == 2.5

    def test_source_type_is_youtube(self) -> None:
        """The source_type class attribute must be 'youtube'."""
        assert YouTubeHandler.source_type == "youtube"

    def test_subclass_of_base_handler(self) -> None:
        """YouTubeHandler should be a subclass of BaseHandler."""
        from autoinfo.collectors.base import BaseHandler

        assert issubclass(YouTubeHandler, BaseHandler)

    def test_api_key_from_env_var(self) -> None:
        """When config has no api_key, fall back to AUTOINFO_YOUTUBE_API_KEY env var."""
        with patch.dict(os.environ, {"AUTOINFO_YOUTUBE_API_KEY": "env-key-456"}, clear=False):
            handler = YouTubeHandler({"query": "test"})
            assert handler.api_key == "env-key-456"

    def test_config_api_key_takes_precedence_over_env(self) -> None:
        """Config dict api_key should take precedence over env var."""
        with patch.dict(os.environ, {"AUTOINFO_YOUTUBE_API_KEY": "env-key-789"}, clear=False):
            handler = YouTubeHandler({"query": "test", "api_key": "config-key-priority"})
            assert handler.api_key == "config-key-priority"


# ---------------------------------------------------------------------------
# Tests: fetch returns a list
# ---------------------------------------------------------------------------


class TestYouTubeFetch:
    """Tests for the fetch method."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_returns_list(self, mock_get: MagicMock) -> None:
        """fetch() should return a list of dicts."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({"query": "rick astley", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert isinstance(items, list)
        assert len(items) == 2

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_each_item_is_dict(self, mock_get: MagicMock) -> None:
        """Each returned item must be a dict."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({"query": "rick astley", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        for item in items:
            assert isinstance(item, dict)

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_respects_limit(self, mock_get: MagicMock) -> None:
        """fetch should respect the limit argument."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({"query": "rick astley", "api_key": "test-key"})
        items = handler.fetch(limit=1)

        assert len(items) == 1

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_uses_correct_endpoint(self, mock_get: MagicMock) -> None:
        """fetch should call the YouTube Data API v3 search endpoint with correct params."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({"query": "machine learning", "api_key": "test-key"})
        handler.fetch(limit=5)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "www.googleapis.com/youtube/v3/search" in url
        assert "q=machine+learning" in url
        assert "part=snippet" in url
        assert "key=test-key" in url
        assert "type=video" in url
        assert "maxResults=5" in url

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_includes_channel_id_when_configured(self, mock_get: MagicMock) -> None:
        """When channel_id is set, include it in the request."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({
            "query": "tutorials",
            "api_key": "test-key",
            "channel_id": "UCtestChannel",
        })
        handler.fetch(limit=5)

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "channelId=UCtestChannel" in url

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_includes_order_when_configured(self, mock_get: MagicMock) -> None:
        """When order is set, include it in the request."""
        mock_get.return_value = _mock_response(SAMPLE_YOUTUBE_RESPONSE)

        handler = YouTubeHandler({
            "query": "tutorials",
            "api_key": "test-key",
            "order": "date",
        })
        handler.fetch(limit=5)

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "order=date" in url


# ---------------------------------------------------------------------------
# Tests: empty response / missing API key
# ---------------------------------------------------------------------------


class TestYouTubeFetchEmpty:
    """Tests for empty or no-result responses."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_handles_empty_results(self, mock_get: MagicMock) -> None:
        """An empty items list should return an empty list."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        handler = YouTubeHandler({"query": "NONEXISTENT_QUERY_99999", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_handles_missing_items_key(self, mock_get: MagicMock) -> None:
        """Response without an 'items' key should return empty list."""
        mock_get.return_value = _mock_response({"kind": "youtube#searchListResponse"})

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    def test_fetch_limit_zero_returns_empty(self) -> None:
        """A limit of 0 should result in an empty list without API call."""
        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=0)

        assert items == []

    def test_fetch_no_api_key_returns_empty(self) -> None:
        """Without an API key, fetch should return empty list and log warning."""
        handler = YouTubeHandler({"query": "test"})  # no api_key
        handler.query = "test"
        items = handler.fetch(limit=10)

        assert items == []

    def test_fetch_empty_query_returns_empty(self) -> None:
        """With an empty query, fetch should return empty list and log warning."""
        handler = YouTubeHandler({"query": "", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: field mapping
# ---------------------------------------------------------------------------


class TestYouTubeFieldMapping:
    """Tests for mapping YouTube JSON fields to AutoInfo item format."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_id(self, mock_get: MagicMock) -> None:
        """id should come from the id.videoId field."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["id"] == "jNQXAC9IVRw"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_title(self, mock_get: MagicMock) -> None:
        """title should come from snippet.title."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["title"] == "Me at the zoo"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_content(self, mock_get: MagicMock) -> None:
        """content should come from snippet.description."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["content"] == "The first YouTube video ever uploaded."

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_author(self, mock_get: MagicMock) -> None:
        """author should come from snippet.channelTitle."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["author"] == "jawed"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_published_date(self, mock_get: MagicMock) -> None:
        """published_date should come from snippet.publishedAt."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["published_date"] == "2005-04-23T22:32:31Z"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_source_url(self, mock_get: MagicMock) -> None:
        """source_url should be https://www.youtube.com/watch?v={videoId}."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["source_url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_channel_id(self, mock_get: MagicMock) -> None:
        """channel_id should come from snippet.channelId."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["channel_id"] == "UC4QobU6STFB0P71PMvOGN5A"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_channel_title(self, mock_get: MagicMock) -> None:
        """channel_title should come from snippet.channelTitle."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["channel_title"] == "jawed"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_thumbnail_url(self, mock_get: MagicMock) -> None:
        """thumbnail_url should be the default thumbnail URL."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert "default.jpg" in items[0]["thumbnail_url"]

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_missing_thumbnails(self, mock_get: MagicMock) -> None:
        """When thumbnails are missing, thumbnail_url should be empty string."""
        mock_get.return_value = _mock_response(SAMPLE_RESPONSE_NO_THUMBNAILS)

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["thumbnail_url"] == ""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_missing_description(self, mock_get: MagicMock) -> None:
        """When description is missing, content should be empty string."""
        mock_get.return_value = _mock_response(SAMPLE_RESPONSE_NO_DESCRIPTION)

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items[0]["content"] == ""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_field_mapping_all_expected_fields_present(self, mock_get: MagicMock) -> None:
        """Every returned item must have all expected keys."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        expected_fields = {
            "id", "title", "content", "author", "published_date",
            "source_url", "channel_id", "channel_title", "thumbnail_url",
        }
        for item in items:
            for field in expected_fields:
                assert field in item, f"Item missing field: {field}"


# ---------------------------------------------------------------------------
# Tests: pagination
# ---------------------------------------------------------------------------


class TestYouTubePagination:
    """Tests for multi-page API results."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_paginates_across_pages(self, mock_get: MagicMock) -> None:
        """When nextPageToken is present, fetch should follow pages."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_MULTI_PAGE_RESPONSE_PAGE1),
            _mock_response(SAMPLE_MULTI_PAGE_RESPONSE_PAGE2),
        ]

        handler = YouTubeHandler({"query": "multi page test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert len(items) == 2
        assert items[0]["id"] == "video001"
        assert items[1]["id"] == "video002"
        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Tests: error handling (graceful degradation)
# ---------------------------------------------------------------------------


class TestYouTubeErrorHandling:
    """Tests for HTTP errors, non-JSON responses, and network failures."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_http_error_returns_partial(self, mock_get: MagicMock) -> None:
        """HTTP errors should return what we have (empty list on first call)."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_get.return_value = mock_response

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_network_error_returns_empty(self, mock_get: MagicMock) -> None:
        """Network errors should return empty list."""
        mock_get.side_effect = httpx.NetworkError("Connection refused")

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_timeout_returns_empty(self, mock_get: MagicMock) -> None:
        """Timeout errors should return empty list gracefully."""
        mock_get.side_effect = httpx.TimeoutException(
            "Request timed out",
            request=MagicMock(),
        )

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_non_json_response_handled_gracefully(self, mock_get: MagicMock) -> None:
        """If API returns non-JSON, handle gracefully with empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = ValueError("Expecting value: line 1 column 1")
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert items == []

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_malformed_item_gets_empty_defaults(self, mock_get: MagicMock) -> None:
        """A malformed item with missing fields gets empty string defaults."""
        response = {
            "kind": "youtube#searchListResponse",
            "pageInfo": {"totalResults": 2},
            "items": [
                {
                    # Missing both id and snippet — gets empty defaults
                    "kind": "youtube#searchResult",
                },
                {  # Good item
                    "kind": "youtube#searchResult",
                    "id": {"kind": "youtube#video", "videoId": "goodOne"},
                    "snippet": {
                        "publishedAt": "2026-01-01T00:00:00Z",
                        "channelId": "UCgood",
                        "title": "Good Video",
                        "description": "This one works.",
                        "channelTitle": "Good Channel",
                        "thumbnails": {},
                        "liveBroadcastContent": "none",
                    },
                },
            ],
        }

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        # _map_video handles missing keys gracefully — both items returned
        assert len(items) == 2
        assert items[0]["id"] == ""  # malformed item gets empty id
        assert items[0]["title"] == ""
        assert items[1]["id"] == "goodOne"
        assert items[1]["title"] == "Good Video"


# ---------------------------------------------------------------------------
# Tests: rate limiting
# ---------------------------------------------------------------------------


class TestYouTubeRateLimit:
    """Tests for rate limiter behaviour."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_rate_limit_first_call_instant(self, mock_get: MagicMock) -> None:
        """First call should not block (no previous request recorded)."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        handler = YouTubeHandler({"query": "test", "api_key": "test-key"})

        t0 = time.time()
        handler.fetch(limit=5)
        elapsed = time.time() - t0

        assert elapsed < 0.3  # should be near-instant

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_rate_limit_enforces_min_interval(self, mock_get: MagicMock) -> None:
        """Back-to-back calls should be spaced by at least 1/max_rps."""
        mock_get.return_value = _mock_response(SAMPLE_EMPTY_RESPONSE)

        handler = YouTubeHandler({
            "query": "test",
            "api_key": "test-key",
            "max_rps": 5,
        })
        assert handler.max_rps == 5.0

        handler.fetch(limit=5)  # warms _last_request_time
        t0 = time.time()
        handler.fetch(limit=5)  # should wait
        elapsed = time.time() - t0

        min_interval = 1.0 / handler.max_rps  # 0.2 s
        assert elapsed >= min_interval * 0.9  # 10 % tolerance


# ---------------------------------------------------------------------------
# Tests: to_item conversion
# ---------------------------------------------------------------------------


class TestYouTubeToItem:
    """Tests for ``YouTubeHandler.to_item()``."""

    def test_to_item_complete(self) -> None:
        """A fully populated video dict converts to a correct Item."""
        handler = YouTubeHandler({"api_key": "dummy"})
        video = {
            "id": "dQw4w9WgXcQ",
            "title": "Rick Astley - Never Gonna Give You Up",
            "content": "The official video.",
            "author": "Rick Astley",
            "published_date": "2009-10-25T06:57:33Z",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
            "channel_title": "Rick Astley",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
        }

        item = handler.to_item(video)

        assert isinstance(item, Item)
        assert item.id == "dQw4w9WgXcQ"
        assert item.source_name == "youtube"
        assert item.source_type == "youtube"
        assert item.source_platform == "youtube"
        assert item.source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert item.title == "Rick Astley - Never Gonna Give You Up"
        assert item.content == "The official video."
        assert item.content_type == "text"
        assert item.collected_at == "2009-10-25T06:57:33Z"
        assert "video_id" in item.raw_data
        assert item.raw_data["video_id"] == "dQw4w9WgXcQ"
        assert item.raw_data["author"] == "Rick Astley"
        assert item.raw_data["channel_id"] == "UCuAXFkgsw1L7xaCfnd5JJOw"
        assert item.raw_data["channel_title"] == "Rick Astley"
        assert item.raw_data["thumbnail_url"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg"

    def test_to_item_empty_id_uses_uuid(self) -> None:
        """When id is empty, a UUID should be generated as the item id."""
        handler = YouTubeHandler({"api_key": "dummy"})
        video = {
            "id": "",
            "title": "No ID",
            "content": "",
            "author": "",
            "published_date": "",
            "source_url": "",
            "channel_id": "",
            "channel_title": "",
            "thumbnail_url": "",
        }

        item = handler.to_item(video)

        assert item.id
        assert item.id != ""
        assert "-" in item.id  # UUID contains hyphens

    def test_to_item_constructs_source_url_from_id(self) -> None:
        """When source_url is empty but id is present, construct it."""
        handler = YouTubeHandler({"api_key": "dummy"})
        video = {
            "id": "jNQXAC9IVRw",
            "title": "Me at the zoo",
            "content": "",
            "author": "",
            "published_date": "",
            "source_url": "",
            "channel_id": "",
            "channel_title": "",
            "thumbnail_url": "",
        }

        item = handler.to_item(video)

        assert item.source_url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


# ---------------------------------------------------------------------------
# Tests: requires_key
# ---------------------------------------------------------------------------


class TestYouTubeRequiresKey:
    """Tests for requires_key static method."""

    def test_requires_key_returns_true(self) -> None:
        """YouTube Data API always requires an API key."""
        assert YouTubeHandler.requires_key() is True


# ---------------------------------------------------------------------------
# Tests: fetch_captions
# ---------------------------------------------------------------------------


class TestYouTubeFetchCaptions:
    """Tests for the fetch_captions method."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_returns_caption_info(self, mock_get: MagicMock) -> None:
        """fetch_captions should return caption metadata for a video."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_CAPTIONS_RESPONSE),
            _mock_text_response(SAMPLE_SRT_TRANSCRIPT),
        ]

        handler = YouTubeHandler({"api_key": "test-key", "max_rps": 1000})
        result = handler.fetch_captions("dQw4w9WgXcQ")

        assert result is not None
        assert result["caption_id"] == "AUieDaYb_caption_english"
        assert result["language"] == "en"
        assert result["track_kind"] == "standard"

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_empty_items_returns_none(self, mock_get: MagicMock) -> None:
        """When no captions exist, return None."""
        mock_get.return_value = _mock_response({"kind": "youtube#captionListResponse", "items": []})

        handler = YouTubeHandler({"api_key": "test-key"})
        result = handler.fetch_captions("noCaptionsVideo")

        assert result is None

    def test_fetch_captions_no_api_key_returns_none(self) -> None:
        """Without an API key, fetch_captions should return None."""
        handler = YouTubeHandler({"query": "test"})  # no api_key
        result = handler.fetch_captions("dQw4w9WgXcQ")
        assert result is None

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_network_error_returns_none(self, mock_get: MagicMock) -> None:
        """Network errors should return None gracefully."""
        mock_get.side_effect = httpx.NetworkError("Connection refused")

        handler = YouTubeHandler({"api_key": "test-key"})
        result = handler.fetch_captions("dQw4w9WgXcQ")

        assert result is None

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_non_json_returns_none(self, mock_get: MagicMock) -> None:
        """Non-JSON response should return None."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = ValueError("Expecting value")
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = YouTubeHandler({"api_key": "test-key"})
        result = handler.fetch_captions("dQw4w9WgXcQ")

        assert result is None

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_downloads_transcript(self, mock_get: MagicMock) -> None:
        """fetch_captions should download and parse the SRT transcript."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_CAPTIONS_RESPONSE),
            _mock_text_response(SAMPLE_SRT_TRANSCRIPT),
        ]

        handler = YouTubeHandler({"api_key": "test-key", "max_rps": 1000})
        result = handler.fetch_captions("dQw4w9WgXcQ")

        assert result is not None
        assert result["caption_id"] == "AUieDaYb_caption_english"
        assert result["language"] == "en"
        assert result["track_kind"] == "standard"
        assert result["name"] == "English"
        assert result["transcript"] == EXPECTED_TRANSCRIPT_TEXT

        # Second request must hit the captions.download endpoint with tfmt=srt
        download_url = mock_get.call_args_list[1][0][0]
        assert "/youtube/v3/captions/AUieDaYb_caption_english" in download_url
        assert "tfmt=srt" in download_url

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_captions_download_failure_returns_empty_transcript(
        self, mock_get: MagicMock,
    ) -> None:
        """A failed transcript download should keep metadata with empty transcript."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_CAPTIONS_RESPONSE),
            httpx.NetworkError("Connection refused"),
        ]

        handler = YouTubeHandler({"api_key": "test-key", "max_rps": 1000})
        result = handler.fetch_captions("dQw4w9WgXcQ")

        assert result is not None
        assert result["caption_id"] == "AUieDaYb_caption_english"
        assert result["transcript"] == ""


# ---------------------------------------------------------------------------
# Tests: fetch with fetch_depth=fulltext transcript enrichment
# ---------------------------------------------------------------------------


class TestYouTubeFetchFulltext:
    """Tests for fetch() transcript enrichment when fetch_depth is fulltext."""

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_fulltext_content_contains_transcript(self, mock_get: MagicMock) -> None:
        """With fetch_depth=fulltext, item content should carry the transcript."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_SINGLE_RESPONSE),
            _mock_response(SAMPLE_CAPTIONS_RESPONSE),
            _mock_text_response(SAMPLE_SRT_TRANSCRIPT),
        ]

        handler = YouTubeHandler({
            "query": "first video",
            "api_key": "test-key",
            "fetch_depth": "fulltext",
            "max_rps": 1000,
        })
        items = handler.fetch(limit=10)

        assert len(items) == 1
        assert "Never gonna give you up" in items[0]["content"]
        assert EXPECTED_TRANSCRIPT_TEXT in items[0]["content"]

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_default_uses_description(self, mock_get: MagicMock) -> None:
        """Default (non-fulltext) fetch keeps description content and skips captions."""
        mock_get.return_value = _mock_response(SAMPLE_SINGLE_RESPONSE)

        handler = YouTubeHandler({"query": "first video", "api_key": "test-key"})
        items = handler.fetch(limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "The first YouTube video ever uploaded."
        mock_get.assert_called_once()  # search only — no captions calls

    @patch("autoinfo.collectors.youtube.httpx.get")
    def test_fetch_fulltext_falls_back_to_description(self, mock_get: MagicMock) -> None:
        """When transcript is unavailable, fulltext fetch falls back to description."""
        mock_get.side_effect = [
            _mock_response(SAMPLE_SINGLE_RESPONSE),
            _mock_response({"kind": "youtube#captionListResponse", "items": []}),
        ]

        handler = YouTubeHandler({
            "query": "first video",
            "api_key": "test-key",
            "fetch_depth": "fulltext",
            "max_rps": 1000,
        })
        items = handler.fetch(limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "The first YouTube video ever uploaded."


# ---------------------------------------------------------------------------
# Tests: _map_video static method
# ---------------------------------------------------------------------------


class TestYouTubeMapVideo:
    """Tests for the _map_video static method."""

    def test_map_video_handles_invalid_id_structure(self) -> None:
        """If item['id'] is not a dict, handle gracefully."""
        item = {
            "kind": "youtube#searchResult",
            "id": "plain_string_not_dict",
            "snippet": {
                "publishedAt": "2026-01-01T00:00:00Z",
                "channelId": "UCtest",
                "title": "Test",
                "description": "Desc",
                "channelTitle": "Test Channel",
                "thumbnails": {},
                "liveBroadcastContent": "none",
            },
        }
        result = YouTubeHandler._map_video(item)
        assert result["id"] == ""

    def test_map_video_handles_empty_snippet(self) -> None:
        """If snippet is empty/missing, all fields should fall back to defaults."""
        item = {
            "kind": "youtube#searchResult",
            "id": {"kind": "youtube#video", "videoId": "vid123"},
        }
        result = YouTubeHandler._map_video(item)
        assert result["id"] == "vid123"
        assert result["title"] == ""
        assert result["content"] == ""
        assert result["author"] == ""
        assert result["source_url"] == "https://www.youtube.com/watch?v=vid123"
