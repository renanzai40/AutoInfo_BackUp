"""Yahoo Finance RSS feed handler using feedparser.

Provides the :class:`YahooFinanceHandler` class which fetches Yahoo Finance
RSS feeds and parses them into :class:`Item <autoinfo.models.Item>` instances.

No API key needed — RSS is public and ToS-compliant.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timezone
from typing import Any

import feedparser

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item
from autoinfo.textutil import clean_feed_text

logger = logging.getLogger(__name__)

# Default feed URL for Yahoo Finance market news
_DEFAULT_FEED_URL = "https://finance.yahoo.com/news/rssindex"


class YahooFinanceHandler(BaseHandler):
    """Fetch and parse Yahoo Finance RSS feeds into :class:`Item` instances.

    Uses feedparser to consume Yahoo Finance RSS feeds. Supports both the
    default market news feed and topic-specific RSS feeds.

    Usage::

        handler = YahooFinanceHandler(source_name="yahoo-finance-news")
        items = handler.fetch("https://finance.yahoo.com/news/rssindex")
        for item in items:
            print(item.title, item.source_url)
    """

    _handler_type: str = "YahooFinanceHandler"
    source_type: str = "yahoo_finance"

    def __init__(self, source_name: str = "yahoo_finance") -> None:
        self.source_name = source_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str | None = None) -> list[Item]:
        """Fetch and parse a Yahoo Finance RSS feed.

        Parameters
        ----------
        url : str, optional
            The feed URL to fetch.  Defaults to the market news feed
            at ``https://finance.yahoo.com/news/rssindex``.

        Returns
        -------
        list[Item]
            Parsed items.  Returns an empty list on any error (network
            failure, malformed XML, etc.) — this method **never** raises.
        """
        feed_url = url or _DEFAULT_FEED_URL

        try:
            parsed = feedparser.parse(feed_url, agent="AutoInfo/1.8 (autoinfo@example.com)")
        except Exception as exc:
            logger.error("Yahoo Finance RSS fetch failed for %s: %s", feed_url, exc)
            return []

        # -- bozo bit: feedparser could not fully parse the feed ----------
        if parsed.bozo and not parsed.entries:
            bozo_exception = parsed.get("bozo_exception", None)
            logger.error(
                "Yahoo Finance RSS parse error for %s (bozo): %s",
                feed_url,
                bozo_exception or "unknown",
            )
            return []

        # -- Ensure we have entries ---------------------------------------
        if not parsed.entries:
            logger.warning("Yahoo Finance RSS feed returned zero entries: %s", feed_url)
            return []

        items: list[Item] = []
        for i, entry in enumerate(parsed.entries):
            try:
                item = self._entry_to_item(entry, feed_url)
                items.append(item)
            except Exception as exc:
                logger.warning(
                    "Skipping entry %d in %s: %s",
                    i,
                    feed_url,
                    exc,
                )
                continue

        return items

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _entry_to_item(cls, entry: dict[str, Any], feed_url: str) -> Item:
        """Convert a feedparser entry ``dict`` into an :class:`Item`."""
        title = clean_feed_text(entry.get("title", ""))
        link = entry.get("link", feed_url)
        summary = clean_feed_text(
            entry.get("summary")
            or entry.get("description")
            or entry.get("content", [{}])[0].get("value", "")
            or ""
        )

        published = entry.get("published") or entry.get("updated") or ""
        collected_at = _normalise_date(published)

        return Item(
            id=_make_item_id(feed_url, link),
            source_name="yahoo_finance",
            source_type="yahoo_finance",
            source_platform="yahoo_finance",
            source_url=link,
            title=title,
            content=summary,
            content_type="text",
            collected_at=collected_at,
            raw_data={"feed_url": feed_url},
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _make_item_id(feed_url: str, item_link: str) -> str:
    """Produce a stable item identifier from feed + entry URLs."""
    raw = f"{feed_url}::{item_link}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _normalise_date(date_str: str) -> str:
    """Try to parse *date_str* into ISO-8601 (UTC).

    Returns an empty string if the date cannot be parsed.
    """
    if not date_str:
        return ""

    try:
        from dateutil import parser as dateutil_parser

        dt = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        pass

    return date_str
