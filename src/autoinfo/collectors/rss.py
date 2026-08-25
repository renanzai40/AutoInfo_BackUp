"""RSS/Atom feed handler using feedparser.

Provides the :class:`RSSHandler` class which fetches and parses RSS 2.0
and Atom feeds into :class:`Item <autoinfo.models.Item>` instances.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import timezone
from typing import Any

import feedparser
import httpx

from autoinfo.collectors.base import BaseHandler, SourceFailure
from autoinfo.collectors.web import WebHandler
from autoinfo.models import Item

# feedparser 6.x has no timeout support; fetch over httpx with a bounded
# timeout first so a hung feed cannot stall the whole collect run.
_RSS_FETCH_TIMEOUT = 30  # seconds

# Identifying user agent — sent both on the httpx fetch and to feedparser.
# Bare ``python-httpx/*`` UAs are UA-blocked by some feeds (e.g. CNBC)
# while a named agent string is accepted (#288). Browser-shaped UA since
# 2026-08-25: card-verified feeds like retailwire.com 403 bare/named agent
# strings but serve a browser UA (backup-repo #24 run); the trailing
# AutoInfo token keeps the request identifiable for ToS compliance.
_RSS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 AutoInfo/1.9"
)

logger = logging.getLogger(__name__)

FULLTEXT_MAX_CHARS = 8000

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class RSSHandler(BaseHandler):
    """Fetch and parse RSS/Atom feeds into :class:`Item` instances.

    Supports both RSS 2.0 and Atom formats transparently — *feedparser*
    normalises both to the same ``feed.entries`` interface.

    Usage::

        handler = RSSHandler()
        items = handler.fetch("https://hnrss.org/frontpage?count=3")
        for item in items:
            print(item.title, item.source_url)
    """

    def __init__(self, source_name: str = "rss", fetch_depth: str = "abstract") -> None:
        self.source_name = source_name
        self.fetch_depth = fetch_depth

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> list[Item]:
        """Fetch and parse a single RSS/Atom feed.

        Parameters
        ----------
        url : str
            The feed URL to fetch.

        Returns
        -------
        list[Item]
            Parsed items.

        Raises
        ------
        SourceFailure
            On network failure, malformed XML, an HTTP error status, or a
            zero-entry feed — so a dead feed surfaces as an explicit
            structured failure instead of a silent empty list (issue #135).
        """
        try:
            # Local file (path or file:// URI — tests/offline fixtures)
            # parses directly; remote URLs are fetched over httpx with a
            # bounded timeout — feedparser itself has no timeout and can
            # hang on a dead feed. file:// paths may carry URL-encoded
            # characters (e.g. %E8 for non-ASCII) — decode before isfile.
            local_path = (
                urllib.parse.unquote(url[7:]) if url.startswith("file://") else url
            )
            if os.path.isfile(local_path):
                with open(local_path, "rb") as fh:
                    parsed = feedparser.parse(fh.read(), agent=_RSS_USER_AGENT)
            else:
                resp = httpx.get(
                    url,
                    timeout=_RSS_FETCH_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": _RSS_USER_AGENT},
                )
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content, agent=_RSS_USER_AGENT)
        except httpx.TimeoutException as exc:
            logger.error("RSS fetch timed out for %s: %s", url, exc)
            raise SourceFailure(f"RSS fetch timed out for {url}: {exc}") from exc
        except (httpx.HTTPError, Exception) as exc:
            logger.error("RSS fetch failed for %s: %s", url, exc)
            raise SourceFailure(f"RSS fetch failed for {url}: {exc}") from exc

        # -- HTTP error status: dead or misconfigured feed ------------------
        feed_status = getattr(parsed, "status", None)
        if feed_status is not None and feed_status >= 400:
            logger.error("RSS feed returned HTTP %s for %s", feed_status, url)
            raise SourceFailure(f"RSS feed returned HTTP {feed_status} for {url}")

        # -- bozo bit: feedparser could not fully parse the feed ----------
        if parsed.bozo and not parsed.entries:
            bozo_exception = parsed.get("bozo_exception", None)
            logger.error(
                "RSS parse error for %s (bozo): %s",
                url,
                bozo_exception or "unknown",
            )
            raise SourceFailure(
                f"RSS parse error for {url} (bozo): {bozo_exception or 'unknown'}"
            )

        # -- Ensure we have entries ---------------------------------------
        if not parsed.entries:
            logger.warning("RSS feed returned zero entries: %s", url)
            raise SourceFailure(f"RSS feed returned zero entries: {url}")

        items: list[Item] = []
        web_handler = WebHandler() if self.fetch_depth == "fulltext" else None
        for i, entry in enumerate(parsed.entries):
            try:
                item = self._entry_to_item(entry, url, self.source_name)
                if web_handler is not None:
                    self._enrich_fulltext(item, web_handler)
                items.append(item)
            except Exception as exc:
                logger.warning(
                    "Skipping entry %d in %s: %s", i, url, exc,
                )
                continue

        return items

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_to_item(entry: dict[str, Any], feed_url: str, source_name: str = "rss") -> Item:
        """Convert a feedparser entry ``dict`` into an :class:`Item`.

        Parameters
        ----------
        entry : dict
            A single entry from ``parsed.entries`` (feedparser's
            normalised ``FeedParserDict``).
        feed_url : str
            The original feed URL (used as a fallback for source_url).

        Returns
        -------
        Item
        """
        title = entry.get("title", "")
        link = entry.get("link", feed_url)
        summary = (
            entry.get("summary")
            or entry.get("description")
            or entry.get("content", [{}])[0].get("value", "")
            or ""
        )

        published = entry.get("published") or entry.get("updated") or ""
        collected_at = _normalise_date(published)

        return Item(
            id=_make_item_id(feed_url, link),
            source_name=source_name,
            source_type="rss",
            source_platform=source_name,
            source_url=link,
            title=title,
            content=summary,
            content_type="text",
            collected_at=collected_at,
            raw_data={"feed_url": feed_url},
        )

    def _enrich_fulltext(self, item: Item, web_handler: WebHandler) -> None:
        """Replace the feed summary with the fetched article body (fulltext mode).

        Fetches ``item.source_url`` (the entry ``link``) through the web.py
        trafilatura path, truncating to ``FULLTEXT_MAX_CHARS``.  On any
        failure the original summary is kept and a debug log is emitted —
        one bad article must not break the whole feed.
        """
        link = item.source_url
        try:
            fetched = web_handler.fetch(link)
            body = fetched[0].content if fetched else ""
        except Exception as exc:
            logger.debug("Fulltext fetch failed for %s: %s", link, exc)
            return
        if not body:
            logger.debug("No extractable fulltext for %s", link)
            return
        item.content = body[:FULLTEXT_MAX_CHARS]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _make_item_id(feed_url: str, item_link: str) -> str:
    """Produce a stable-ish item identifier from feed + entry URLs."""
    import hashlib

    raw = f"{feed_url}::{item_link}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _normalise_date(date_str: str) -> str:
    """Try to parse *date_str* into ISO-8601 (UTC).

    Returns an empty string if the date cannot be parsed.
    """
    if not date_str:
        return ""

    # feedparser may return a time.struct_time via ``parsed_parsed``,
    # but the string form is more portable; use python-dateutil if
    # available, otherwise a simple fallback.
    try:
        from datetime import datetime

        from dateutil import parser as dateutil_parser

        dt: datetime = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        pass

    # Last-resort: just return the raw string so caller has something.
    return date_str
