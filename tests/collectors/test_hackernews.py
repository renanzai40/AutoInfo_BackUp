"""Tests for the HackerNews handler.

Verifies the two-step fetch: GET /topstories.json → array of int ids → GET /item/{id}.json per id.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.hackernews import HackerNewsHandler
from autoinfo.config import SourceConfig


@pytest.fixture
def hn_config() -> SourceConfig:
    """Real HN Firebase config — matching sources.yaml after fix."""
    return SourceConfig(
        name="HackerNews API",
        type="hackernews",
        url="https://hacker-news.firebasedatabase.app/v0",
        settings={"rate_limit": 100},
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _fake_response(json_payload: object) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_payload
    resp.raise_for_status.return_value = None
    return resp


TOP_STORIES = [1, 2, 3]

STORY_PAYLOADS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "title": "Story One", "text": "", "by": "author1", "url": "https://example.com/1"},
    2: {"id": 2, "title": "Story Two", "text": "Content of story two.", "by": "author2", "url": ""},
    3: {
        "id": 3,
        "title": "",
        "text": "No title, only text content here for story three.",
        "by": "author3",
        "url": "https://example.com/3",
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHackerNewsHandler:
    def test_handler_attributes(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        assert handler.source_type == "hackernews"
        assert handler.source_name == "HackerNews API"

    @patch("autoinfo.collectors.hackernews.httpx.get")
    def test_fetch_returns_items(self, mock_get: MagicMock, hn_config: SourceConfig) -> None:
        def side_effect(url: str, **kwargs: Any) -> MagicMock:
            if "topstories" in url:
                return _fake_response(TOP_STORIES)
            # /item/{id}.json — extract id from URL
            for sid in TOP_STORIES:
                if f"/item/{sid}" in url:
                    return _fake_response(STORY_PAYLOADS[sid])
            return _fake_response({})

        mock_get.side_effect = side_effect

        handler = HackerNewsHandler(hn_config)
        raw_items = handler.fetch(limit=3)
        items = [handler.to_item(r) for r in raw_items]

        assert len(items) == 3

        # First item — link post: source_url is the ORIGINAL article, not the
        # HN discussion page (provenance must point at the source content).
        assert items[0].id == "1"
        assert items[0].title == "Story One"
        assert items[0].source_url == "https://example.com/1"
        assert items[0].source_type == "hackernews"
        assert items[0].source_name == "HackerNews API"

        # Second item — has title and text; no source_url in payload
        assert items[1].id == "2"
        assert items[1].title == "Story Two"
        assert items[1].content == "Content of story two."
        assert items[1].source_url == "https://news.ycombinator.com/item?id=2"

        # Third item — no title, text only
        assert items[2].id == "3"
        assert items[2].title == "No title, only text content here for story three."[:80]

    @patch("autoinfo.collectors.hackernews.httpx.get")
    def test_fetch_calls_topstories_first(
        self, mock_get: MagicMock, hn_config: SourceConfig
    ) -> None:
        def side_effect(url: str, **kwargs: Any) -> MagicMock:
            if "topstories" in url:
                return _fake_response(TOP_STORIES)
            for sid in TOP_STORIES:
                if f"/item/{sid}" in url:
                    return _fake_response(STORY_PAYLOADS[sid])
            return _fake_response({})

        mock_get.side_effect = side_effect

        handler = HackerNewsHandler(hn_config)
        handler.fetch(limit=3)

        # Verify topstories.json called
        calls = [call.args[0] for call in mock_get.call_args_list]
        assert any("/topstories.json" in c for c in calls), f"topstories.json not in calls: {calls}"

    @patch("autoinfo.collectors.hackernews.httpx.get")
    def test_fetch_calls_item_endpoints(self, mock_get: MagicMock, hn_config: SourceConfig) -> None:
        def side_effect(url: str, **kwargs: Any) -> MagicMock:
            if "topstories" in url:
                return _fake_response(TOP_STORIES)
            for sid in TOP_STORIES:
                if f"/item/{sid}" in url:
                    return _fake_response(STORY_PAYLOADS[sid])
            return _fake_response({})

        mock_get.side_effect = side_effect

        handler = HackerNewsHandler(hn_config)
        handler.fetch(limit=2)

        calls = [call.args[0] for call in mock_get.call_args_list]
        # Should include item/1.json and item/2.json but NOT item/3.json
        assert any("/item/1" in c for c in calls)
        assert any("/item/2" in c for c in calls)
        assert not any("/item/3" in c for c in calls)

    @patch("autoinfo.collectors.hackernews.httpx.get")
    def test_fetch_network_error_returns_empty(
        self, mock_get: MagicMock, hn_config: SourceConfig
    ) -> None:
        mock_get.side_effect = httpx.NetworkError("Connection refused")
        handler = HackerNewsHandler(hn_config)
        items = handler.fetch(limit=5)
        assert items == []

    @patch("autoinfo.collectors.hackernews.httpx.get")
    def test_fetch_topstories_empty_returns_empty(
        self, mock_get: MagicMock, hn_config: SourceConfig
    ) -> None:
        mock_get.return_value = _fake_response([])
        handler = HackerNewsHandler(hn_config)
        items = handler.fetch(limit=5)
        assert items == []

    def test_to_item_builds_source_url(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 42, "title": "Test", "by": "tester", "text": ""})
        assert item.id == "42"
        assert item.source_url == "https://news.ycombinator.com/item?id=42"
        assert item.source_type == "hackernews"
        assert item.source_platform == "hackernews"

    def test_to_item_no_title_uses_text(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 7, "text": "Short story content", "by": "anon"})
        assert item.title == "Short story content"

    def test_to_item_no_text_or_title(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 99})
        assert item.title == "HN story 99"
        assert item.id == "99"

    def test_to_item_prefers_article_url_over_hn_page(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 5, "title": "T", "url": "https://blog.example.com/post"})
        assert item.source_url == "https://blog.example.com/post"

    def test_to_item_falls_back_to_hn_page_without_article_url(
        self, hn_config: SourceConfig
    ) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 5, "title": "T", "url": ""})
        assert item.source_url == "https://news.ycombinator.com/item?id=5"

    def test_to_item_strips_html_from_text(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        item = handler.to_item({"id": 6, "title": "T", "text": "<p>Hello &amp; <b>world</b></p>"})
        assert item.content == "Hello & world"

    @patch("autoinfo.collectors.web.WebHandler")
    def test_to_item_fulltext_fetches_article_body_when_configured(
        self, mock_web: MagicMock
    ) -> None:
        mock_web.return_value.fetch.return_value = [
            SimpleNamespace(content="Full article body text")
        ]
        cfg = SourceConfig(
            name="HackerNews API",
            type="hackernews",
            url="https://hacker-news.firebasedatabase.app/v0",
            fetch_depth="fulltext",
        )
        handler = HackerNewsHandler(cfg)
        item = handler.to_item(
            {"id": 7, "title": "T", "url": "https://blog.example.com/x", "text": ""}
        )
        assert item.content == "Full article body text"

    def test_to_item_skips_fulltext_fetch_by_default(self, hn_config: SourceConfig) -> None:
        handler = HackerNewsHandler(hn_config)
        with patch("autoinfo.collectors.web.WebHandler") as mock_web:
            item = handler.to_item(
                {"id": 8, "title": "T", "url": "https://blog.example.com/y", "text": ""}
            )
        mock_web.assert_not_called()
        assert item.content == ""

    @patch("autoinfo.collectors.web.WebHandler")
    def test_to_item_fulltext_failure_degrades_to_empty(self, mock_web: MagicMock) -> None:
        mock_web.return_value.fetch.side_effect = RuntimeError("network down")
        cfg = SourceConfig(
            name="HackerNews API",
            type="hackernews",
            url="https://hacker-news.firebasedatabase.app/v0",
            fetch_depth="fulltext",
        )
        handler = HackerNewsHandler(cfg)
        item = handler.to_item(
            {"id": 9, "title": "T", "url": "https://blog.example.com/z", "text": ""}
        )
        assert item.content == ""
        assert item.title == "T"
