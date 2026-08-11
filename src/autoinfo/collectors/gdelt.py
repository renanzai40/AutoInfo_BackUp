"""GDELT DOC 2.0 API handler — headline-level global news coverage.

Fetches news article headlines, summaries, and source URLs via the free
GDELT DOC 2.0 API (``https://api.gdeltproject.org/api/v2/doc/doc``).
No authentication required.

.. caution::

    This handler returns **headline-level** data only — ``title``,
    ``summary`` snippet, ``source_url``, and ``published_date``.
    It does **not** fetch full article text (cost, rate, and
    paywall concerns).  Use this for news discovery and trending
    topic surveillance.

Usage::

    handler = GDELTHandler({"query": "climate change", "maxrecords": 50})
    articles = handler.fetch(query="AI regulation", limit=30)
    items = [handler.to_item(article) for article in articles]
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.collectors.web import WebHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL: str = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMEOUT: int = 30  # seconds
DEFAULT_LIMIT: int = 25
MAX_LIMIT: int = 250  # GDELT DOC 2.0 artlist hard cap
MAX_RETRIES: int = 3
RETRY_DELAYS: list[int] = [2, 4, 8]  # exponential backoff in seconds

# Polite rate limiting: 1 request per 5 seconds (free tier)
MIN_REQUEST_INTERVAL: float = 5.0

# Default timespan: 3 months (in months)
DEFAULT_TIMESPAN: str = "3m"

# Fulltext enrichment: truncation cap for fetched article bodies (controls LLM cost)
FULLTEXT_CONTENT_CAP: int = 8000


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class GDELTHandler(BaseHandler):
    """Fetch news article headlines from the GDELT DOC 2.0 API.

    The GDELT DOC 2.0 API is free, no authentication required.
    Returns **headline-level** articles (title + summary snippet + URL),
    not full text.

    Usage::

        handler = GDELTHandler({"query": "AI policy"})
        articles = handler.fetch(limit=30)
    """

    source_type: str = "gdelt"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise handler.

        Args:
            config: Dictionary with optional keys:
                - ``query``: default search query (default ``""``)
                - ``timespan``: date window e.g. ``"3m"``, ``"7d"``
                  (default ``"3m"`` — 3 months)
                - ``maxrecords``: max articles per request
                  (default ``25``, hard cap 250)
        """
        if config is None:
            config = {}
        self.config: dict[str, Any] = config
        self.query: str = config.get("query", "")
        self.timespan: str = config.get("timespan", DEFAULT_TIMESPAN)
        self.maxrecords: int = min(
            int(config.get("maxrecords", DEFAULT_LIMIT)), MAX_LIMIT
        )
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed (polite: 1 req / 5 s)."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        min_interval = MIN_REQUEST_INTERVAL
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # HTTP request with retry
    # ------------------------------------------------------------------

    def _request(self, url: str) -> httpx.Response:
        """Issue a GET request with rate limiting and exponential-backoff retry.

        Args:
            url: Fully qualified URL to fetch.

        Returns:
            HTTP response object.

        Raises:
            httpx.TimeoutException: After retries exhausted.
            httpx.NetworkError: After retries exhausted.
            httpx.HTTPStatusError: On 4xx/5xx (not retried).
        """
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            self._wait_for_rate_limit()
            try:
                response = httpx.get(url, timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                # Do not retry 4xx/5xx — propagate immediately
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAYS[attempt])

        raise RuntimeError("Unexpected: all retries exhausted") from last_exc

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_article(item: dict[str, Any]) -> dict[str, Any]:
        """Map a raw GDELT article dict to standardised fields.

        Args:
            item: Raw JSON article from the GDELT ``articles`` list.

        Returns:
            Parsed dict with standardised field names: ``id``, ``title``,
            ``content``, ``source_url``, ``published_date``,
            ``source_name``, ``domain``, ``language``, ``image_url``.
        """
        title: str = item.get("title") or ""
        source_url: str = item.get("url") or ""
        published_date: str = item.get("seendate") or ""
        source_name: str = item.get("sourcename") or ""
        domain: str = item.get("domain") or ""
        language: str = item.get("language") or ""
        image_url: str = item.get("socialimage") or ""
        tone: float = float(item.get("tone", 0.0))
        url_md5: str = item.get("url_md5") or ""

        # Use url_md5 as a stable ID if available, else hash the url
        article_id: str = url_md5 if url_md5 else str(hash(source_url))

        # Summary snippet — GDELT does not include full text; use title
        # as both title and content preview
        content: str = title

        return {
            "id": article_id,
            "title": title,
            "content": content,
            "source_url": source_url,
            "published_date": published_date,
            "source_name": source_name,
            "domain": domain,
            "language": language,
            "image_url": image_url,
            "tone": tone,
        }

    def _enrich_fulltext(self, article: dict[str, Any]) -> None:
        """Replace title-only content with the article body from its URL.

        Fetches the article's ``source_url`` via the web.py trafilatura
        path and stores the extracted text (truncated to
        :data:`FULLTEXT_CONTENT_CAP`) as ``content``.  Any failure —
        missing URL, network error, empty extraction — keeps the title
        content and logs at debug level, so one blocked article never
        breaks the batch.
        """
        url = article.get("source_url") or ""
        if not url:
            logger.debug(
                "GDELT fulltext: no source_url for article '%s'; "
                "keeping title content.",
                article.get("title", ""),
            )
            return

        try:
            web_items = WebHandler().fetch(url)
        except Exception as exc:
            logger.debug(
                "GDELT fulltext extraction failed for %s: %s; "
                "keeping title content.",
                url,
                exc,
            )
            return

        body = web_items[0].content if web_items else ""
        if not body:
            logger.debug(
                "GDELT fulltext extraction returned no content for %s; "
                "keeping title content.",
                url,
            )
            return

        article["content"] = body[:FULLTEXT_CONTENT_CAP]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        query: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Fetch news article headlines from the GDELT DOC 2.0 API.

        Args:
            query: Search query string (e.g. ``"climate policy"``).
                Falls back to ``self.query`` if empty.
            limit: Maximum number of articles to return (default 25,
                max 250).

        Returns:
            List of parsed article dicts, each with standardised fields.
            Returns an empty list on error or if *limit* ≤ 0.
        """
        if limit <= 0:
            return []

        search_query = (query or self.query).strip()
        if not search_query:
            logger.warning(
                "GDELT fetch called with empty query; returning empty list."
            )
            return []

        page_size = min(limit, MAX_LIMIT)

        params: dict[str, Any] = {
            "query": search_query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": page_size,
            "timespan": self.timespan,
        }
        url = f"{BASE_URL}?{urlencode(params)}"

        all_articles: list[dict[str, Any]] = []

        try:
            resp = self._request(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "?"
            logger.warning(
                "GDELT API HTTP error %s for query '%s': %s",
                status,
                search_query,
                exc,
            )
            return []
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "GDELT API network error for query '%s': %s",
                search_query,
                exc,
            )
            return []

        # Parse JSON response
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "GDELT API returned non-JSON for query '%s': %s",
                search_query,
                exc,
            )
            return []

        articles: list[dict[str, Any]] = data.get("articles") or []
        fulltext_enabled = self.config.get("fetch_depth") == "fulltext"
        for item in articles:
            try:
                article = self._map_article(item)
                if fulltext_enabled:
                    self._enrich_fulltext(article)
                all_articles.append(article)
            except Exception as exc:
                logger.debug(
                    "Failed to map GDELT article: %s",
                    exc,
                    exc_info=True,
                )
                continue

        return all_articles[:limit]

    # ------------------------------------------------------------------
    # Conversion to Item
    # ------------------------------------------------------------------

    def to_item(self, article: dict[str, Any]) -> Item:
        """Convert a parsed article dict to an :class:`Item` dataclass.

        Args:
            article: Parsed article dict as returned by :meth:`fetch`.

        Returns:
            An :class:`Item` instance populated from the article data.
        """
        article_id: str = article.get("id") or ""
        title: str = article.get("title") or ""

        # Extract domain from source_url
        source_url: str = article.get("source_url") or ""
        article_domain: str = article.get("domain") or ""
        if not article_domain and source_url:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(source_url)
                article_domain = parsed.netloc or ""
            except Exception:
                pass

        return Item(
            id=article_id or str(uuid.uuid4()),
            source_name="gdelt",
            source_type="gdelt",
            source_platform="gdelt",
            source_url=source_url,
            title=title,
            content=article.get("content") or "",
            content_type="text",
            collected_at=article.get("published_date") or "",
            language=article.get("language") or "",
            domain=article_domain,
            topic_tags=[],
            raw_data={
                "gdelt_article_id": article_id,
                "source_name": article.get("source_name") or "",
                "article_domain": article_domain,
                "published_date": article.get("published_date") or "",
                "image_url": article.get("image_url") or "",
                "tone": article.get("tone") or 0.0,
                "language": article.get("language") or "",
            },
        )

    # ------------------------------------------------------------------
    # Source metadata
    # ------------------------------------------------------------------

    @staticmethod
    def requires_key() -> bool:
        """Return ``False`` — the GDELT DOC 2.0 API requires no auth."""
        return False

    @staticmethod
    def note() -> str | None:
        """Return a note about headline-level coverage."""
        return (
            "GDELT DOC 2.0 returns HEADLINE-level data only (title + "
            "URL + seendate). Full article text is NOT fetched. Use "
            "this for news discovery and trending topic surveillance, "
            "not for full-text extraction."
        )
