"""Social / Video publishing delivery adapter for AutoInfo.

Provides a generic webhook-based publishing channel that formats KB content
as social-media posts and POSTs them to platform API endpoints via Bearer-token
authentication.

No platform-specific OAuth — uses API tokens/keys configured per platform.
Content is automatically truncated to each platform's character limit and
media attachments (image URLs, video URLs) are included in the outgoing
payload when present in the KB content.

Design
------
* :class:`SocialPlatformConfig` — per-platform configuration dataclass
* :class:`SocialDeliveryChannel` — DeliveryChannel ABC implementation
* Registered as ``"social_publish"`` in the channel registry
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Any

import httpx

from autoinfo.delivery import DeliveryChannel, _now_utc
from autoinfo.models import DeliveryResult, Product

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default character limits per platform (in characters)
_PLATFORM_CHAR_LIMITS: dict[str, int] = {
    "mastodon": 500,
    "bluesky": 300,
    "linkedin": 3000,
    "threads": 500,
    "x": 280,  # Twitter/X — kept for generic reference
    "generic": 1024,
}

_RETRIES = 3
"""Number of retry attempts for transient failures."""

_DEFAULT_TIMEOUT = 10.0
"""HTTP request timeout in seconds."""


# ---------------------------------------------------------------------------
# SocialPlatformConfig
# ---------------------------------------------------------------------------


@dataclass
class SocialPlatformConfig:
    """Configuration for a social media publishing platform.

    Parameters
    ----------
    platform:
        Platform identifier — one of ``mastodon``, ``bluesky``,
        ``linkedin``, ``threads``, ``x``, or ``generic``.
    api_endpoint:
        Full URL of the platform's content-posting API endpoint
        (e.g. ``https://mastodon.social/api/v1/statuses``).
    auth_token:
        Bearer token for API authentication.  Stored as an
        environment-variable reference (``${VAR_NAME}``) when
        configured via the MCP tool; at runtime the caller
        resolves it to the actual token.
    char_limit:
        Maximum characters per post.  When ``0`` (default) the
        limit is looked up from :data:`_PLATFORM_CHAR_LIMITS` based
        on the *platform* key.
    post_format:
        Template format — ``"plain"`` or ``"markdown"``.  Defaults
        to ``"plain"``.
    extra_headers:
        Additional HTTP headers sent with each request.
    """

    platform: str
    api_endpoint: str = ""
    auth_token: str = ""
    char_limit: int = 0
    post_format: str = "plain"
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def effective_char_limit(self) -> int:
        """Return the character limit, falling back to the platform default."""
        if self.char_limit > 0:
            return self.char_limit
        return _PLATFORM_CHAR_LIMITS.get(self.platform, _PLATFORM_CHAR_LIMITS["generic"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars* characters with an ellipsis.

    If the text fits within the limit it is returned unchanged.
    Otherwise it is cut at the last space before the limit and
    ``"…"`` is appended.  The total length (including ellipsis)
    will be at most *max_chars*.

    When *max_chars* is 1 or less, only the ellipsis is returned.

    Examples
    --------
    >>> _truncate_text("hello world", 20)
    'hello world'
    >>> len(_truncate_text("a" * 500, 280))
    280
    """
    text = str(text) if text else ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "\u2026"
    # Try to break at the last space before the cutoff
    cut = text[: max_chars - 1].rstrip()
    return cut + "\u2026"


def _format_post(
    payload: dict[str, Any],
    platform_config: SocialPlatformConfig,
) -> dict[str, Any]:
    """Build a social-media post body from *payload*.

    Extracts ``title`` and ``content``, combines them into a post
    body, truncates to the platform's character limit, and includes
    any media URLs found in the payload.

    Parameters
    ----------
    payload:
        Content dict — expected keys: ``title``, ``content``,
        ``url``, ``image_urls``, ``video_url``.
    platform_config:
        Per-platform configuration (determines character limit,
        post format).

    Returns
    -------
    dict
        A dict ready to be JSON-serialised and POSTed to the
        platform API.  Shape follows a generic webhook convention:
        ``{"text": …, "media": […], "link": …}``.
    """
    title = payload.get("title", "")
    content = payload.get("content", "")
    url = payload.get("url", "")
    image_urls = payload.get("image_urls", [])
    video_url = payload.get("video_url", "")

    # Build body text: "title – content… url"
    parts: list[str] = []
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    body_text = " ".join(parts)

    char_limit = platform_config.effective_char_limit

    # Reserve space for the URL if present (20 chars for " — url" postfix)
    if url and char_limit > 40:
        url_postfix = f"\n\n{url}"
        body_text = _truncate_text(body_text, char_limit - len(url_postfix))
        body_text += url_postfix
    else:
        body_text = _truncate_text(body_text, char_limit)

    post: dict[str, Any] = {
        "text": body_text,
        "platform": platform_config.platform,
        "format": platform_config.post_format,
    }

    # Media attachments
    media: list[dict[str, str]] = []
    if isinstance(image_urls, list):
        for img_url in image_urls:
            if isinstance(img_url, str) and img_url.strip():
                media.append({"type": "image", "url": img_url.strip()})
    if video_url and isinstance(video_url, str) and video_url.strip():
        media.append({"type": "video", "url": video_url.strip()})
    if media:
        post["media"] = media

    if url:
        post["link"] = url

    return post


def _resolve_auth_token(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> str | None:
    """Resolve the auth token from config or payload.

    Looks up ``auth_token`` in *config* first, then *payload*.
    Strips env-var reference syntax ``${…}`` and resolves from
    ``os.environ`` if present.

    Returns
    -------
    str or None
        The resolved token, or ``None`` if not configured.
    """
    import os as _os

    token: str | None = config.get("auth_token") or payload.get("auth_token")
    if not token:
        return None

    # Unwrap ${VAR_NAME} references
    if isinstance(token, str) and token.startswith("${") and token.endswith("}"):
        var_name = token[2:-1]
        token = _os.environ.get(var_name, token)

    return token if token else None


# ---------------------------------------------------------------------------
# SocialDeliveryChannel
# ---------------------------------------------------------------------------


class SocialDeliveryChannel(DeliveryChannel):
    """Deliver content to social media platforms via generic webhook POST.

    Formats KB content (title + body + media) into platform-appropriate
    posts and POSTs them to each recipient URL using Bearer-token
    authentication.  This is the **RSS-to-social bridge** — incoming
    KB items flow through this channel to become published social
    media posts.

    Configuration
    -------------
    Required keys in ``product.config`` (or per-recipient config):

    * ``auth_token`` — Bearer token (or ``${ENV_VAR}`` reference)
    * ``platform`` — one of ``mastodon``, ``bluesky``, ``linkedin``,
      ``threads``, ``x``, ``generic``

    Optional:

    * ``api_endpoint`` — overrides the URL derived from *recipients*
    * ``char_limit`` — overrides the platform default
    * ``post_format`` — ``"plain"`` (default) or ``"markdown"``

    Payload keys understood by ``send()``:

    * ``title`` — post title / headline
    * ``content`` — post body (truncated to platform limit)
    * ``url`` — link included at the end of the post
    * ``image_urls`` — list of image URLs to attach
    * ``video_url`` — single video URL to attach

    .. note::

       This adapter uses a **generic webhook pattern**.  It does not
       implement platform-specific OAuth flows, timeline polling, or
       engagement analytics.  Publishing is one-way: AutoInfo → Platform.
    """

    @property
    def name(self) -> str:
        return "social_publish"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        product: Product,
        payload: dict[str, Any],
        recipients: list[str],
    ) -> DeliveryResult:
        """Deliver *payload* as a social media post.

        Parameters
        ----------
        product:
            Product being delivered.  ``.config`` carries platform
            configuration (auth_token, platform, api_endpoint, …).
        payload:
            Content to publish (title, content, url, image_urls, …).
        recipients:
            Platform API endpoint URLs.  Each entry is POSTed to
            individually.  When empty the endpoint is read from
            ``product.config["api_endpoint"]``.

        Returns
        -------
        DeliveryResult
        """
        config = product.config or {}

        # Resolve auth token
        auth_token = _resolve_auth_token(config, payload)
        if not auth_token:
            return DeliveryResult(
                product_id=product.id,
                channel=self.name,
                status="failed",
                timestamp=_now_utc(),
                recipient_count=0,
                error="auth_token is required (set in config or payload; "
                "supports ${ENV_VAR} references)",
            )

        # Build platform config
        platform = config.get("platform") or payload.get("platform", "generic")
        api_endpoint = config.get("api_endpoint", "")
        char_limit = config.get("char_limit", 0)
        post_format = config.get("post_format", "plain")
        extra_headers = config.get("extra_headers", {})

        platform_config = SocialPlatformConfig(
            platform=platform,
            api_endpoint=api_endpoint,
            auth_token=auth_token,
            char_limit=int(char_limit) if char_limit else 0,
            post_format=str(post_format),
            extra_headers=dict(extra_headers) if extra_headers else {},
        )

        # Format the post body
        post_body = _format_post(payload, platform_config)

        # Resolve target endpoint URLs
        urls: list[str]
        if recipients:
            urls = list(recipients)
        elif api_endpoint:
            urls = [api_endpoint]
        else:
            return DeliveryResult(
                product_id=product.id,
                channel=self.name,
                status="failed",
                timestamp=_now_utc(),
                recipient_count=0,
                error=(
                    "No platform endpoint provided.  Pass via recipients, "
                    'config["api_endpoint"], or payload["api_endpoint"].'
                ),
            )

        # Deliver to each endpoint
        failed: list[str] = []
        success_count = 0

        for url in urls:
            try:
                self._post_to_platform(url, post_body, platform_config)
                success_count += 1
            except Exception as exc:
                logger.warning("Social publish to %s failed: %s", url, exc)
                failed.append(url)

        all_succeeded = len(failed) == 0
        return DeliveryResult(
            product_id=product.id,
            channel=self.name,
            status="success" if all_succeeded else "partial",
            timestamp=_now_utc(),
            recipient_count=success_count,
            error=(
                None
                if all_succeeded
                else f"{len(failed)} platform endpoint(s) failed"
            ),
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Return ``True`` when *config* contains an auth token.

        An API endpoint is recommended but not strictly required
        at validation time (it can be supplied per-invocation).
        """
        token = config.get("auth_token", "")
        return bool(token and isinstance(token, str) and len(token.strip()) > 0)

    def health_check(self) -> dict[str, Any]:
        import os as _os

        start = _time.time()
        try:
            token = _os.environ.get("SOCIAL_PUBLISH_TOKEN", "")
            endpoint = _os.environ.get("SOCIAL_PUBLISH_ENDPOINT", "")
            if not token:
                latency = (_time.time() - start) * 1000
                return {
                    "healthy": False,
                    "latency_ms": latency,
                    "error": "missing config: SOCIAL_PUBLISH_TOKEN not set",
                    "channel": "social_publish",
                }
            if not endpoint:
                latency = (_time.time() - start) * 1000
                return {
                    "healthy": False,
                    "latency_ms": latency,
                    "error": "missing config: SOCIAL_PUBLISH_ENDPOINT not set",
                    "channel": "social_publish",
                }
            # Quick connectivity check — HEAD request
            with httpx.Client(timeout=5.0) as client:
                resp = client.head(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                )
            latency = (_time.time() - start) * 1000
            healthy = resp.status_code < 500
            return {
                "healthy": healthy,
                "latency_ms": latency,
                "error": None if healthy else f"HTTP {resp.status_code}",
                "channel": "social_publish",
            }
        except Exception as e:
            latency = (_time.time() - start) * 1000
            return {
                "healthy": False,
                "latency_ms": latency,
                "error": str(e),
                "channel": "social_publish",
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _post_to_platform(
        url: str,
        body: dict[str, Any],
        config: SocialPlatformConfig,
        retries: int = _RETRIES,
    ) -> None:
        """POST *body* to *url* as a social media post.

        Uses Bearer token authentication.  Retries on 5xx and
        network errors with exponential backoff.  2xx is success,
        4xx is terminal (logged and raised).

        Raises
        ------
        httpx.HTTPStatusError
            On 4xx auth/permission errors (terminal — no retry).
        httpx.TimeoutException / httpx.NetworkError
            When all retries are exhausted.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.auth_token}",
        }
        headers.update(config.extra_headers)

        for attempt in range(retries):
            try:
                with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                    resp = client.post(url, json=body, headers=headers)

                if resp.status_code < 400:
                    return  # 2xx — success
                if resp.status_code < 500:
                    # 4xx — client error (e.g. bad token, permission denied)
                    logger.error(
                        "Social platform %s returned %d: %s",
                        config.platform,
                        resp.status_code,
                        resp.text[:500],
                    )
                    raise httpx.HTTPStatusError(
                        f"Platform {config.platform} returned "
                        f"{resp.status_code}: {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )
                # 5xx — server error, will retry
                logger.warning(
                    "Social platform %s returned 5xx %d (attempt %d/%d)",
                    config.platform,
                    resp.status_code,
                    attempt + 1,
                    retries,
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == retries - 1:
                    raise
            except httpx.HTTPStatusError:
                raise  # 4xx — no retry
            _time.sleep(2**attempt)  # 2s, 4s, 8s

        # If we exhaust retries on 5xx, the last exception will have been
        # raised inside the loop.  This line is a safeguard.
        raise RuntimeError(
            f"Failed to publish to {config.platform} after {retries} retries"
        )
