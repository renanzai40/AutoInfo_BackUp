"""HackerNews Firebase API handler.

Fetches top stories from the Hacker News API using a two-step process:

1. ``GET /v0/topstories.json`` → JSON array of integer story IDs
2. ``GET /v0/item/{id}.json`` → per-story payload

The HN Firebase API is free and requires no API key.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item
from autoinfo.textutil import clean_feed_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT: int = 15  # seconds
DEFAULT_LIMIT: int = 20
DEFAULT_RATE_LIMIT: float = 100.0  # requests per minute (HN is very permissive)
HN_ITEM_URL: str = "https://news.ycombinator.com/item?id={item_id}"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class HackerNewsHandler(BaseHandler):
    """Fetch top stories from the Hacker News Firebase API.

    Usage::

        handler = HackerNewsHandler(SourceConfig(
            name="HackerNews API",
            type="hackernews",
            url="https://hacker-news.firebasedatabase.app/v0",
        ))
        items = handler.fetch(limit=10)
    """

    source_type: str = "hackernews"

    def __init__(self, source_config: Any) -> None:
        """Initialise handler from a SourceConfig.

        Args:
            source_config: :class:`autoinfo.config.SourceConfig` with
                ``url`` set to the Firebase base URL and optional
                ``settings`` for ``rate_limit`` and ``timeout``.
        """
        self.source_config = source_config
        self.source_name: str = getattr(source_config, "name", "HackerNews API")
        self.base_url: str = (getattr(source_config, "url", "") or "").rstrip("/")
        settings: dict[str, Any] = getattr(source_config, "settings", None) or {}
        self.rate_limit: float = float(settings.get("rate_limit", DEFAULT_RATE_LIMIT))
        self.timeout: int = int(settings.get("timeout", DEFAULT_TIMEOUT))
        self.fetch_depth: str = str(getattr(source_config, "fetch_depth", "abstract") or "abstract")
        self._web_handler: Any = None
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed under the rate limit."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        min_interval = 60.0 / self.rate_limit if self.rate_limit > 0 else 0.0
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, query: str = "", limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:  # type: ignore[override]
        """Fetch top stories from Hacker News.

        Args:
            query: Ignored (HN has no search endpoint).  Always fetches
                top stories.
            limit: Maximum number of stories to return (default 20).

        Returns:
            List of parsed story dicts, each with ``id``, ``title``,
            ``content``, ``source_url``, and raw HN fields.
            Returns an empty list on error.
        """
        if limit <= 0:
            return []

        try:
            self._wait_for_rate_limit()
            top_url = f"{self.base_url}/topstories.json"
            resp = httpx.get(top_url, timeout=self.timeout)
            resp.raise_for_status()
            story_ids: list[int] = resp.json()
        except Exception as exc:
            logger.error("HackerNews topstories fetch failed: %s", exc)
            return []

        if not story_ids:
            return []

        stories: list[dict[str, Any]] = []
        for story_id in story_ids[:limit]:
            try:
                self._wait_for_rate_limit()
                item_url = f"{self.base_url}/item/{story_id}.json"
                resp = httpx.get(item_url, timeout=self.timeout)
                resp.raise_for_status()
                payload: dict[str, Any] = resp.json()
                if payload:
                    stories.append(payload)
            except Exception as exc:
                logger.warning("HackerNews item %s fetch failed: %s", story_id, exc)
                continue

        return stories

    # ------------------------------------------------------------------
    # Conversion to Item
    # ------------------------------------------------------------------

    def to_item(self, payload: dict[str, Any]) -> Item:
        """Convert a raw HN story dict to an :class:`Item` dataclass.

        Args:
            payload: Raw story dict from the HN Firebase API
                (``/item/{id}.json`` response).

        Returns:
            An :class:`Item` instance.
        """
        story_id: int = payload.get("id", 0)
        sid: str = str(story_id) if story_id else ""
        text: str = clean_feed_text(payload.get("text") or "")
        title: str = payload.get("title") or text[:80] or f"HN story {sid}"
        article_url: str = str(payload.get("url") or "")
        source_url: str = article_url or (HN_ITEM_URL.format(item_id=sid) if sid else "")

        content: str = text
        if not content and article_url and self.fetch_depth == "fulltext":
            content = self._fetch_article(article_url)

        return Item(
            id=sid,
            source_name=self.source_name,
            source_type="hackernews",
            source_url=source_url,
            title=title,
            content=content,
            content_type="text",
            source_platform="hackernews",
            collected_at=datetime.now(timezone.utc).isoformat(),
            raw_data=payload,
        )

    def _fetch_article(self, url: str) -> str:
        """Fetch the linked article body for a link-type HN story.

        HN link posts carry no ``text``; the only useful body lives at the
        story's ``url``.  Used when ``fetch_depth == "fulltext"``.  Failures
        degrade to an empty body rather than aborting the item.
        """
        from autoinfo.collectors.rss import FULLTEXT_MAX_CHARS
        from autoinfo.collectors.web import WebHandler

        if self._web_handler is None:
            self._web_handler = WebHandler()
        try:
            fetched = self._web_handler.fetch(url)
        except Exception as exc:
            logger.debug("HackerNews fulltext fetch failed for %s: %s", url, exc)
            return ""
        body = fetched[0].content if fetched else ""
        return body[:FULLTEXT_MAX_CHARS]
