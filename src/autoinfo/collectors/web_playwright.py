"""Playwright-based web page content extractor — fallback for JS-heavy pages.

Uses ``playwright`` (headless Chromium) to fetch and render web pages that
require JavaScript execution (SPA, client-rendered content, etc.), then
extracts clean article content via trafilatura.

Gracefully degrades when playwright is not installed — the module remains
importable but ``PlaywrightWebHandler`` is unavailable at runtime.

Usage::

    from autoinfo.collectors.web_playwright import PlaywrightWebHandler

    handler = PlaywrightWebHandler()
    items = handler.fetch("https://example.com/spa-page")
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import trafilatura

from autoinfo.collectors.web import USER_AGENT, WebHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency — playwright may not be installed
# ---------------------------------------------------------------------------

_PLAYWRIGHT_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright as _sync_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _sync_playwright = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30_000  # Playwright timeout in milliseconds
NAVIGATION_TIMEOUT = 60_000
WAIT_UNTIL = "networkidle"

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class PlaywrightWebHandler:
    """Fetch JS-heavy web pages via Playwright, extract with trafilatura.

    Works in two phases:

    1. **Quick path** — fetch HTML with httpx and extract via trafilatura
       (identical to :class:`WebHandler`).  If extraction succeeds the
       result is returned immediately.

    2. **Fallback path** — when the quick path yields no content (empty
       page, SPA that requires JS execution), launch headless Chromium via
       Playwright, wait for ``networkidle``, and run trafilatura on the
       rendered DOM.

    The fallback is fully automatic and transparent to the caller.
    """

    source_name: str

    def __init__(
        self,
        source_name: str = "web",
    ) -> None:
        self.source_name = source_name
        self._web_handler = WebHandler(source_name=source_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> list[Item]:
        """Fetch *url* and extract content, falling back to Playwright.

        Parameters
        ----------
        url : str
            The web page URL to fetch.

        Returns
        -------
        list[Item]
            A list with a single :class:`Item` if extraction succeeds,
            or an empty list on any error.  This method **never** raises.
        """
        # Phase 1 — quick path via httpx + trafilatura
        items = self._web_handler.fetch(url)
        if items:
            return items

        # Phase 2 — Playwright fallback for JS-rendered content
        return self._fetch_via_playwright(url)

    # ------------------------------------------------------------------
    # Playwright fallback
    # ------------------------------------------------------------------

    def _fetch_via_playwright(self, url: str) -> list[Item]:
        """Load *url* in headless Chromium and extract content.

        Returns an empty list when playwright is not installed, when the
        page fails to load, or when trafilatura still cannot extract
        meaningful content.
        """
        if not _PLAYWRIGHT_AVAILABLE or _sync_playwright is None:
            logger.warning(
                "Playwright is not installed. "
                "Install it with: pip install autoinfo[web] && playwright install"
            )
            return []

        try:
            with _sync_playwright() as pw:
                browser = self._launch_browser(pw)
                try:
                    # Carry the same browser-like UA as the httpx quick path
                    # so JS-rendered fetches are not blocked by UA checks.
                    context = browser.new_context(user_agent=USER_AGENT)
                    page = context.new_page()
                    html = self._render_page(page, url)
                    if html is None:
                        return []
                    item = self._extract(html, url)
                    return [item] if item is not None else []
                finally:
                    browser.close()
        except Exception as exc:
            logger.error("Playwright fallback failed for %s: %s", url, exc)
            return []

    def _launch_browser(self, pw: Any) -> Any:
        """Launch a headless Chromium instance.

        Parameters
        ----------
        pw : :class:`playwright.sync_api.PlaywrightContextManager`
            The Playwright context manager instance.

        Returns
        -------
        :class:`playwright.sync_api.Browser`
            A headless Chromium browser instance.
        """
        return pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

    def _render_page(self, page: Any, url: str) -> str | None:
        """Navigate to *url* and return the rendered HTML.

        Waits for ``networkidle`` to ensure SPA frameworks finish loading,
        then gives a brief 2 s settling period before grabbing page content.

        Returns ``None`` on navigation failure or timeout.
        """
        try:
            page.goto(url, wait_until=WAIT_UNTIL, timeout=NAVIGATION_TIMEOUT)
            # Give SPA frameworks a brief moment to finish rendering
            page.wait_for_timeout(2000)
            content: str = page.content()
            return content
        except Exception as exc:
            logger.error("Playwright navigation failed for %s: %s", url, exc)
            return None

    def _extract(self, html: str, url: str) -> Item | None:
        """Run trafilatura extraction on *html* and return an :class:`Item`.

        Returns ``None`` when trafilatura cannot extract meaningful content
        (empty page, video-only, etc.).
        """
        try:
            result: Any = trafilatura.bare_extraction(
                html,
                url=url,
                include_links=False,
                include_images=False,
                with_metadata=True,
            )
        except Exception as exc:
            logger.error("Trafilatura extraction failed for %s: %s", url, exc)
            return None

        if result is None or not result.text:
            logger.warning(
                "No extractable content found at %s (Playwright fallback)", url
            )
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
                "renderer": "playwright",
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
