"""Tests for the Playwright-based web content extractor (PlaywrightWebHandler).

Tests the two-phase fallback strategy:

1. **Quick path** — httpx + trafilatura (same as ``WebHandler``)
2. **Playwright fallback** — headless Chromium for JS-heavy pages

Uses ``unittest.mock`` to simulate browser behaviour — no real browser
or network calls in these tests.  The module-level ``_PLAYWRIGHT_AVAILABLE``
flag is patched where necessary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.collectors.web_playwright import (
    _PLAYWRIGHT_AVAILABLE,
    PlaywrightWebHandler,
    _make_item_id,
)
from autoinfo.models import Item

# Paths
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> PlaywrightWebHandler:
    """Return a default :class:`PlaywrightWebHandler` instance."""
    return PlaywrightWebHandler()


@pytest.fixture
def sample_html() -> str:
    """Return the content of ``web-article.html`` fixture."""
    path = FIXTURES / "web-article.html"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Module-level imports & flags
# ---------------------------------------------------------------------------


class TestModuleBasics:
    """Verify the module loads correctly regardless of playwright installation."""

    def test_module_importable(self) -> None:
        """The module should import without error even without playwright."""
        from autoinfo.collectors import web_playwright  # noqa: F811

        assert web_playwright is not None

    def test_playwright_available_flag(self) -> None:
        """``_PLAYWRIGHT_AVAILABLE`` is ``False`` when playwright not installed."""
        # In test/CI environments playwright is typically not installed;
        # if it is, the flag will be True, which is also valid.
        assert isinstance(_PLAYWRIGHT_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# Quick path (httpx + trafilatura)
# ---------------------------------------------------------------------------


class TestQuickPath:
    """Verify the quick path (delegated to WebHandler) works first."""

    def test_quick_path_returns_items(self, handler: PlaywrightWebHandler) -> None:
        """When the quick path succeeds, Playwright fallback is never called."""
        with patch.object(
            handler._web_handler, "fetch", return_value=[MagicMock(spec=Item)]
        ) as mock_fetch:
            with patch.object(handler, "_fetch_via_playwright") as mock_fallback:
                items = handler.fetch("https://example.com/article")

        assert len(items) == 1
        mock_fetch.assert_called_once_with("https://example.com/article")
        mock_fallback.assert_not_called()

    def test_quick_path_empty_triggers_fallback(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """When the quick path returns empty, Playwright fallback runs."""
        mock_fallback_item = MagicMock(spec=Item)

        with patch.object(
            handler._web_handler, "fetch", return_value=[]
        ) as mock_fetch:
            with patch.object(
                handler, "_fetch_via_playwright", return_value=[mock_fallback_item]
            ) as mock_fallback:
                items = handler.fetch("https://example.com/spa")

        assert len(items) == 1
        mock_fetch.assert_called_once_with("https://example.com/spa")
        mock_fallback.assert_called_once_with("https://example.com/spa")

    def test_quick_path_and_fallback_both_empty(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """When both paths yield nothing, an empty list is returned."""
        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch.object(handler, "_fetch_via_playwright", return_value=[]):
                items = handler.fetch("https://example.com/empty")
        assert items == []


# ---------------------------------------------------------------------------
# Playwright fallback — mocked browser
# ---------------------------------------------------------------------------


def _make_mock_page(html_content: str = "<html><body>Mocked</body></html>") -> MagicMock:
    """Build a mock Playwright ``Page`` that returns *html_content*."""
    page = MagicMock()
    page.content.return_value = html_content
    return page


def _make_mock_browser(page: MagicMock | None = None) -> MagicMock:
    """Build a mock Playwright ``Browser`` that opens *page* via a context."""
    browser = MagicMock()
    if page is not None:
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
    return browser


@patch("autoinfo.collectors.web_playwright._PLAYWRIGHT_AVAILABLE", True)
class TestPlaywrightFallback:
    """Verify the Playwright fallback path (browser-launched extraction).

    All tests in this class run with ``_PLAYWRIGHT_AVAILABLE = True`` so
    that the fallback code path is exercised.
    """

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_fallback_returns_item(self, handler: PlaywrightWebHandler) -> None:
        """When quick path is empty, Playwright + trafilatura yields an Item."""
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )

                items = handler.fetch("https://example.com/spa")

        assert len(items) == 1
        assert isinstance(items[0], Item)
        # Verify the mock page was navigated
        page.goto.assert_called_once_with(
            "https://example.com/spa", wait_until="networkidle", timeout=60000
        )

    def test_fallback_sets_renderer_metadata(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """Items extracted via Playwright should have ``renderer: playwright``."""
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )

                items = handler.fetch("https://example.com/spa")

        assert len(items) == 1
        assert items[0].raw_data.get("renderer") == "playwright"

    def test_fallback_closes_browser(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """The browser instance should be closed after extraction."""
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )

                handler.fetch("https://example.com/spa")

        browser.close.assert_called_once()

    # ------------------------------------------------------------------
    # Empty / no-content scenarios
    # ------------------------------------------------------------------

    def test_fallback_empty_when_no_content(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """When trafilatura finds nothing in the rendered page, returns empty."""
        # trafilatura.bare_extraction returns None when no content found
        page = _make_mock_page("<html><body></body></html>")
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )

                items = handler.fetch("https://example.com/empty-spa")

        assert items == []

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_navigation_failure(self, handler: PlaywrightWebHandler) -> None:
        """When ``page.goto`` raises, handler returns empty list (no crash)."""
        page = MagicMock()
        page.goto.side_effect = Exception("Navigation timeout")
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )

                items = handler.fetch("https://example.com/slow-spa")

        assert items == []

    def test_browser_launch_failure(self, handler: PlaywrightWebHandler) -> None:
        """When browser launch fails, handler returns empty list."""
        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.side_effect = (
                    Exception("Browser binary not found")
                )

                items = handler.fetch("https://example.com/spa")

        assert items == []

    def test_extraction_exception(self, handler: PlaywrightWebHandler) -> None:
        """When trafilatura raises during extraction, returns empty list."""
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )
                with patch(
                    "autoinfo.collectors.web_playwright.trafilatura.bare_extraction",
                    side_effect=Exception("Extraction crashed"),
                ):
                    items = handler.fetch("https://example.com/spa")

        assert items == []

    def test_page_content_returns_none(self, handler: PlaywrightWebHandler) -> None:
        """When ``_render_page`` returns ``None`` (navigation failure), empty list."""
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._sync_playwright"
            ) as mock_pw:
                mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                    browser
                )
                with patch.object(
                    handler, "_render_page", return_value=None
                ) as mock_render:
                    items = handler.fetch("https://example.com/spa")

        assert items == []
        mock_render.assert_called_once()


# ---------------------------------------------------------------------------
# Playwright not installed
# ---------------------------------------------------------------------------


class TestPlaywrightNotInstalled:
    """Behaviour when playwright is absent from the environment."""

    def test_fallback_returns_empty_when_not_installed(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """When ``_PLAYWRIGHT_AVAILABLE`` is False, fallback returns empty."""
        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._PLAYWRIGHT_AVAILABLE", False
            ):
                items = handler.fetch("https://example.com/spa")

        assert items == []

    def test_fallback_never_calls_playwright_when_not_installed(
        self, handler: PlaywrightWebHandler
    ) -> None:
        """When ``_PLAYWRIGHT_AVAILABLE`` is False, playwright is never imported."""
        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._PLAYWRIGHT_AVAILABLE", False
            ):
                with patch(
                    "autoinfo.collectors.web_playwright._sync_playwright"
                ) as mock_sync:
                    handler.fetch("https://example.com/spa")

        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestPlaywrightWebHandlerConfig:
    """Verify handler configuration."""

    def test_default_source_name(self) -> None:
        """Default source_name should be 'web'."""
        handler = PlaywrightWebHandler()
        assert handler.source_name == "web"

    def test_custom_source_name(self) -> None:
        """Custom source_name should propagate to the internal WebHandler."""
        handler = PlaywrightWebHandler(source_name="my-web")
        assert handler.source_name == "my-web"
        assert handler._web_handler.source_name == "my-web"

    def test_handler_never_raises(self, handler: PlaywrightWebHandler) -> None:
        """Calling ``fetch`` should never raise, regardless of input."""
        bad_inputs = [
            "",
            "not-a-url",
            "https://",
        ]
        for url in bad_inputs:
            items = handler.fetch(url)
            assert items == [], f"Expected empty list for URL: {url!r}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Corner cases for the Playwright web handler."""

    def test_make_item_id_consistency(self) -> None:
        """Same URL → same deterministic Item ID."""
        id1 = _make_item_id("https://example.com/article")
        id2 = _make_item_id("https://example.com/article")
        assert id1 == id2
        assert len(id1) == 16
        assert id1.isalnum()

    def test_make_item_id_different_urls(self) -> None:
        """Different URLs → different Item IDs."""
        id1 = _make_item_id("https://example.com/article-1")
        id2 = _make_item_id("https://example.com/article-2")
        assert id1 != id2
