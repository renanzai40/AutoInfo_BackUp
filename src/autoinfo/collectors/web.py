"""Web page content extractor using trafilatura.

Fetches HTML from URLs and extracts clean article content via
trafilatura's extraction pipeline.  Handles metadata (title, author,
date) and provides configurable output options.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx
import trafilatura

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # exponential backoff in seconds

# Browser-like User-Agent — many sites (e.g. CNBC) return HTTP 403 when a
# request carries no UA header.  Shared with web_playwright.py.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class WebHandler(BaseHandler):
    """Fetch web pages and extract structured content via trafilatura.

    Usage::

        handler = WebHandler()
        items = handler.fetch("https://example.com/article")
        for item in items:
            print(item.title, item.content[:100])
    """

    source_name: str
    extract_only_text: bool
    include_links: bool
    include_images: bool

    def __init__(
        self,
        source_name: str = "web",
        extract_only_text: bool = True,
        include_links: bool = False,
        include_images: bool = False,
    ) -> None:
        self.source_name = source_name
        self.extract_only_text = extract_only_text
        self.include_links = include_links
        self.include_images = include_images

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> list[Item]:
        """Fetch a URL and extract its content as a single Item.

        Parameters
        ----------
        url : str
            The web page URL to fetch.

        Returns
        -------
        list[Item]
            A list with a single :class:`Item` if extraction succeeds,
            or an empty list on any error (network failure, non-HTML
            content, extraction failure).  This method **never** raises.
        """
        html = self._fetch_html(url)
        if html is None:
            return []

        item = self._extract(html, url)
        if item is None:
            return []

        return [item]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_html(self, url: str) -> str | None:
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = httpx.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()

                # -- Content-Type check ----------------------------------
                content_type = (response.headers.get("content-type") or "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    logger.warning("Non-HTML content at %s: %s", url, content_type)
                    return None

                return response.text

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    logger.error(
                        "Failed to fetch %s after %d attempts: %s",
                        url,
                        MAX_RETRIES,
                        exc,
                    )
                    return None
                time.sleep(RETRY_DELAYS[attempt])

            except httpx.HTTPStatusError as exc:
                logger.error("HTTP error fetching %s: %s", url, exc)
                return None

            except httpx.InvalidURL as exc:
                logger.error("Invalid URL %s: %s", url, exc)
                return None

            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", url, exc)
                return None

        # Unreachable — loop always returns or falls through.
        raise RuntimeError("Unexpected: all retries exhausted") from last_exc

    def _extract(self, html: str, url: str) -> Item | None:
        """Run trafilatura extraction on *html* and return an :class:`Item`.

        Returns ``None`` when trafilatura cannot extract meaningful
        content (empty page, video-only, etc.).
        """
        try:
            # bare_extraction returns trafilatura.settings.Document at runtime,
            # but type stubs claim dict[str, Any]; coerce for the checker.
            result: Any = trafilatura.bare_extraction(
                html,
                url=url,
                include_links=self.include_links,
                include_images=self.include_images,
                with_metadata=True,
            )
        except Exception as exc:
            logger.error("Trafilatura extraction failed for %s: %s", url, exc)
            return None

        if result is None or not result.text:
            logger.warning("No extractable content found at %s", url)
            return None

        title = result.title or ""
        author = result.author or ""
        date = result.date or ""
        text = result.text or ""

        item_id = _make_item_id(url)

        return Item(
            id=item_id,
            source_name=self.source_name,
            source_type="web",
            source_platform=self.source_name,
            source_url=url,
            title=title,
            content=text,
            content_type="text",
            collected_at=date,
            raw_data={
                "author": author,
                "date": date,
            },
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _make_item_id(url: str) -> str:
    """Produce a stable item identifier from a URL.

    Uses SHA-256 of the URL, truncated to 16 hex characters.
    """
    return hashlib.sha256(url.encode()).hexdigest()[:16]
