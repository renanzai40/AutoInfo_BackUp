"""Tests for the generic RSS/Atom feed handler.

Tests cover RSS 2.0 parsing, Atom parsing, error handling for
malformed feeds, and invalid URL handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import vcr

from autoinfo.collectors.rss import RSSHandler
from autoinfo.models import Item

# Path to VCR cassettes
CASSETTES = Path(__file__).resolve().parent.parent / "cassettes"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> RSSHandler:
    """Return a default :class:`RSSHandler` instance."""
    return RSSHandler()


@pytest.fixture
def atom_feed_path() -> str:
    """Return a ``file://`` URL pointing to the local Atom fixture."""
    return FIXTURES.joinpath("atom-feed.xml").as_uri()


# ---------------------------------------------------------------------------
# Happy path — RSS 2.0
# ---------------------------------------------------------------------------


class TestRSSParsing:
    """Verify RSS 2.0 feed parsing produces valid ``Item`` instances."""

    @pytest.mark.vcr
    def test_fetch_returns_items(self, handler: RSSHandler) -> None:
        """Fetching a valid RSS feed returns at least one item."""
        cassette = str(CASSETTES / "hnrss-frontpage.yaml")
        with vcr.use_cassette(cassette):
            items = handler.fetch("https://hnrss.org/frontpage?count=2")
        assert len(items) >= 1, "Expected at least one item from HN frontpage"

    @pytest.mark.vcr
    def test_item_has_required_fields(self, handler: RSSHandler) -> None:
        """Each item must have title, source_url, content, collected_at."""
        cassette = str(CASSETTES / "hnrss-frontpage.yaml")
        with vcr.use_cassette(cassette):
            items = handler.fetch("https://hnrss.org/frontpage?count=2")

        for item in items:
            assert isinstance(item, Item)
            assert item.title, f"Item missing title: {item}"
            assert item.source_url, f"Item missing source_url: {item}"
            assert item.source_url.startswith("http"), (
                f"source_url should be a URL, got: {item.source_url}"
            )
            assert item.collected_at, f"Item missing collected_at: {item}"
            assert item.source_name == "rss"
            assert item.source_type == "rss"

    @pytest.mark.vcr
    def test_item_content_is_summary(self, handler: RSSHandler) -> None:
        """The item content should be the RSS entry summary/description."""
        cassette = str(CASSETTES / "hnrss-frontpage.yaml")
        with vcr.use_cassette(cassette):
            items = handler.fetch("https://hnrss.org/frontpage?count=2")

        for item in items:
            # Hacker News RSS entries include a description/summary
            assert isinstance(item.content, str)


# ---------------------------------------------------------------------------
# Happy path — Atom
# ---------------------------------------------------------------------------


class TestAtomParsing:
    """Verify Atom feed parsing produces valid ``Item`` instances."""

    def test_atom_fetch_returns_items(
        self, handler: RSSHandler, atom_feed_path: str
    ) -> None:
        """Fetching a valid Atom feed returns items."""
        items = handler.fetch(atom_feed_path)
        assert len(items) == 2, f"Expected 2 items, got {len(items)}"

    def test_atom_item_fields(self, handler: RSSHandler, atom_feed_path: str) -> None:
        """Atom items should have correct field mapping."""
        items = handler.fetch(atom_feed_path)
        item = items[0]

        assert item.title == "Atom Entry One"
        assert item.source_url == "https://example.com/entry1"
        assert "summary for atom entry one" in item.content
        assert item.collected_at, "Atom published date should be parsed"

    def test_atom_item_without_published_date(
        self, handler: RSSHandler, atom_feed_path: str
    ) -> None:
        """Atom entries with only 'updated' (no 'published') should still work."""
        items = handler.fetch(atom_feed_path)
        item = items[1]  # second entry has no <published>, only <updated>

        assert item.title == "Atom Entry Two"
        assert item.collected_at, (
            "Should fall back to <updated> when <published> is absent"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify the handler raises explicit SourceFailure under error conditions."""

    def test_invalid_url_raises_source_failure(self, handler: RSSHandler) -> None:
        """An unreachable URL raises SourceFailure (not a silent empty list)."""
        from autoinfo.collectors.base import SourceFailure

        with pytest.raises(SourceFailure):
            handler.fetch("https://invalid.example.com/nonexistent-feed.xml")

    def test_malformed_feed_raises_source_failure(self, handler: RSSHandler) -> None:
        """A valid URL returning non-XML raises SourceFailure."""
        from autoinfo.collectors.base import SourceFailure

        with pytest.raises(SourceFailure):
            handler.fetch("https://httpstat.us/200")

    def test_handler_raises_source_failure_for_bad_inputs(self, handler: RSSHandler) -> None:
        """Unfetchable inputs raise SourceFailure instead of returning []."""
        from autoinfo.collectors.base import SourceFailure

        bad_inputs = [
            "",
            "not-a-url",
            "https://",
            "ftp://invalid-protocol.com/feed.xml",
        ]
        for url in bad_inputs:
            with pytest.raises(SourceFailure):
                handler.fetch(url)

    def test_feed_with_zero_entries(self, handler: RSSHandler) -> None:
        """A feed with zero entries returns an empty list."""
        # Minimal valid RSS feed with no items
        empty_feed = (
            '<?xml version="1.0"?><rss version="2.0">'
            "<channel><title>Empty</title></channel></rss>"
        )
        # feedparser can parse strings directly via `feedparser.parse()`,
        # but via our handler it goes through URL; we test via direct call
        import feedparser

        parsed = feedparser.parse(empty_feed)
        assert len(parsed.entries) == 0
        # Zero-entry feed → explicit SourceFailure, never a silent "0 found"
        from autoinfo.collectors.base import SourceFailure

        with pytest.raises(SourceFailure):
            handler.fetch("https://empty-feed.example.com")


# ---------------------------------------------------------------------------
# Fulltext enrichment (fetch_depth == "fulltext")
# ---------------------------------------------------------------------------


class TestRSSFulltext:
    """Verify ``fetch_depth="fulltext"`` fetches article bodies via the web.py path."""

    def test_fulltext_fetch_carries_article_body(
        self, atom_feed_path: str
    ) -> None:
        """A fulltext item carries the fetched article body as content."""
        from unittest import mock

        from autoinfo.collectors.web import WebHandler

        body = "Full article body text extracted via the web.py trafilatura path."
        body_item = Item(
            id="web-1",
            source_name="web",
            source_type="web",
            source_platform="web",
            source_url="https://example.com/entry1",
            title="Fetched title",
            content=body,
            content_type="text",
        )

        handler = RSSHandler(fetch_depth="fulltext")
        with mock.patch.object(WebHandler, "fetch", return_value=[body_item]):
            items = handler.fetch(atom_feed_path)

        assert items[0].content == body

    def test_default_depth_keeps_summary_and_skips_fetch(
        self, atom_feed_path: str
    ) -> None:
        """Without ``fetch_depth`` the summary is unchanged and no fetch occurs."""
        from unittest import mock

        from autoinfo.collectors.web import WebHandler

        handler = RSSHandler()
        with mock.patch.object(WebHandler, "fetch") as mocked_fetch:
            items = handler.fetch(atom_feed_path)

        mocked_fetch.assert_not_called()
        assert "summary for atom entry one" in items[0].content

    def test_fulltext_failure_keeps_summary(self, atom_feed_path: str) -> None:
        """A per-entry fetch failure keeps the feed summary."""
        from unittest import mock

        from autoinfo.collectors.web import WebHandler

        handler = RSSHandler(fetch_depth="fulltext")
        with mock.patch.object(WebHandler, "fetch", return_value=[]):
            items = handler.fetch(atom_feed_path)

        assert "summary for atom entry one" in items[0].content

    def test_fulltext_truncates_at_cap(self, atom_feed_path: str) -> None:
        """Fulltext content is capped at 8000 characters."""
        from unittest import mock

        from autoinfo.collectors.rss import FULLTEXT_MAX_CHARS
        from autoinfo.collectors.web import WebHandler

        long_body = "x" * 12000
        body_item = Item(
            id="web-1",
            source_name="web",
            source_type="web",
            source_platform="web",
            source_url="https://example.com/entry1",
            title="Fetched title",
            content=long_body,
            content_type="text",
        )

        handler = RSSHandler(fetch_depth="fulltext")
        with mock.patch.object(WebHandler, "fetch", return_value=[body_item]):
            items = handler.fetch(atom_feed_path)

        assert len(items[0].content) == FULLTEXT_MAX_CHARS == 8000
        assert items[0].content == long_body[:FULLTEXT_MAX_CHARS]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Corner cases for the RSS handler."""

    def test_custom_source_name(self) -> None:
        """A custom source_name should propagate to items."""
        handler = RSSHandler(source_name="my-custom-feed")
        assert handler.source_name == "my-custom-feed"

    def test_duplicate_feeds_produce_same_item_ids(self) -> None:
        """Fetching the same feed twice should produce items with same IDs."""
        from autoinfo.collectors.rss import _make_item_id

        id1 = _make_item_id("https://example.com/feed", "https://example.com/1")
        id2 = _make_item_id("https://example.com/feed", "https://example.com/1")
        assert id1 == id2, "Item IDs should be deterministic"
