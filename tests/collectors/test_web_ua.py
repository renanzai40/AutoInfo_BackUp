"""Tests for the web collector User-Agent header (issue #292).

The web collector previously sent NO ``User-Agent`` header on fulltext
fetches, causing HTTP 403 from sites like CNBC.  These tests lock the
fix: the httpx quick path must send a browser-like UA, and the Playwright
browser path must set the same UA on its context.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from autoinfo.collectors.web import USER_AGENT, WebHandler
from autoinfo.collectors.web_playwright import PlaywrightWebHandler

# ---------------------------------------------------------------------------
# Shared constant
# ---------------------------------------------------------------------------


class TestUserAgentConstant:
    """The shared UA constant must be a realistic browser-like string."""

    def test_constant_is_non_empty_browser_like(self) -> None:
        """USER_AGENT must be a non-empty Chrome/Mozilla UA string."""
        assert USER_AGENT
        assert "Mozilla" in USER_AGENT
        assert "Chrome" in USER_AGENT

    def test_playwright_reuses_web_constant(self) -> None:
        """web_playwright must reuse the same UA constant as web.py."""
        from autoinfo.collectors import web_playwright

        # web_playwright re-imports USER_AGENT from web.py (module attribute
        # exists at runtime) but does not re-export it in its public API, so
        # mypy cannot see it — the identity check is the point of this test.
        assert web_playwright.USER_AGENT is USER_AGENT  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# httpx quick path (WebHandler)
# ---------------------------------------------------------------------------


class TestWebFetchUserAgent:
    """The httpx fetch must carry the User-Agent header."""

    def test_web_fetch_sends_user_agent(self) -> None:
        """``_fetch_html`` must pass a browser-like User-Agent to httpx.get."""
        resp = httpx.Response(
            200,
            text="<html><body><p>hello</p></body></html>",
            headers={"content-type": "text/html"},
        )
        with patch("httpx.get", return_value=resp) as mock_get:
            handler = WebHandler()
            handler._fetch_html("https://example.com/article")

        mock_get.assert_called_once()
        kwargs = mock_get.call_args.kwargs
        headers = kwargs.get("headers", {})
        ua = headers.get("User-Agent", "")
        assert ua, "web fetch must send a User-Agent header"
        assert ua == USER_AGENT
        assert "Mozilla" in ua
        assert "Chrome" in ua

    def test_web_fetch_keeps_timeout_and_redirects(self) -> None:
        """Adding the header must not change timeout/redirect semantics."""
        resp = httpx.Response(
            200,
            text="<html><body><p>hello</p></body></html>",
            headers={"content-type": "text/html"},
        )
        with patch("httpx.get", return_value=resp) as mock_get:
            handler = WebHandler()
            handler._fetch_html("https://example.com/article")

        kwargs = mock_get.call_args.kwargs
        assert kwargs.get("timeout") == 30
        assert kwargs.get("follow_redirects") is True


# ---------------------------------------------------------------------------
# Playwright browser path
# ---------------------------------------------------------------------------


class TestPlaywrightUserAgent:
    """The Playwright browser context must carry the shared UA."""

    def test_playwright_context_sets_user_agent(self) -> None:
        """``browser.new_context`` must be called with the shared UA."""
        handler = PlaywrightWebHandler()
        with patch.object(handler._web_handler, "fetch", return_value=[]):
            with patch(
                "autoinfo.collectors.web_playwright._PLAYWRIGHT_AVAILABLE", True
            ):
                with patch(
                    "autoinfo.collectors.web_playwright._sync_playwright"
                ) as mock_pw:
                    browser = MagicMock()
                    mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = (
                        browser
                    )
                    handler.fetch("https://example.com/spa")

        browser.new_context.assert_called_once_with(user_agent=USER_AGENT)
