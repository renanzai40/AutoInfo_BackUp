"""YouTube Data API v3 handler.

Searches and fetches YouTube video metadata using the YouTube Data API v3
(``https://www.googleapis.com/youtube/v3/search``).  Requires an API key
configured via config dict or the ``AUTOINFO_YOUTUBE_API_KEY`` environment
variable.

Quota: each search request consumes 100 units of the daily 10,000-unit quota
(free tier).  Caption fetching requires ``AUTOINFO_YOUTUBE_API_KEY`` (marked as
``requires_key``).
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.googleapis.com/youtube/v3/search"
CAPTIONS_BASE_URL = "https://www.googleapis.com/youtube/v3/captions"

DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # exponential backoff in seconds

# YouTube Data API v3 quota (free tier): 10,000 units / day
# Each search.list call costs 100 units
QUOTA_PER_SEARCH = 100
DAILY_QUOTA = 10_000
MAX_RESULTS_PER_PAGE = 50  # YouTube max is 50 per page


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class YouTubeHandler(BaseHandler):
    """Fetch YouTube video metadata using the YouTube Data API v3.

    Usage::

        handler = YouTubeHandler({"query": "machine learning", "api_key": "..."})
        videos = handler.fetch(limit=10)
        for video in videos:
            print(video["title"], video["author"])

        # Convert to Item for KB storage
        items = [handler.to_item(v) for v in videos]

    An API key is required.  Set it via the ``api_key`` config key or the
    ``AUTOINFO_YOUTUBE_API_KEY`` environment variable.
    """

    source_type: str = "youtube"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise handler.

        Args:
            config: Dictionary with optional keys:
                - ``query``: search query string (default ``""``)
                - ``api_key``: YouTube Data API v3 key (falls back to env var
                  ``AUTOINFO_YOUTUBE_API_KEY``)
                - ``rate_limit``: maximum search requests per hour (default
                  ``100`` — the daily quota in search-equivalent units)
                - ``channel_id``: restrict to a specific channel (optional)
                - ``order``: sort order — ``"date"``, ``"rating"``,
                  ``"relevance"``, ``"title"``, ``"viewCount"``
                  (default ``"relevance"``)
                - ``max_rps``: maximum requests per second (default ``1.0``)
        """
        if config is None:
            config = {}
        self.config: dict[str, Any] = config

        # API key — config dict takes precedence over env var
        self.api_key: str = config.get("api_key", "") or os.environ.get(
            "AUTOINFO_YOUTUBE_API_KEY", ""
        )

        self.query: str = config.get("query", "")
        self.channel_id: str = config.get("channel_id", "")
        self.order: str = config.get("order", "relevance")

        # Rate limiting — requests per second
        self.max_rps: float = float(config.get("max_rps", 1.0))
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed under the rate limit."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        elapsed = time.time() - self._last_request_time
        min_interval = 1.0 / self.max_rps if self.max_rps > 0 else 0.0
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
            httpx.TimeoutException: After 3 retries all timed out.
            httpx.NetworkError: After 3 retries all failed.
            httpx.HTTPStatusError: On 4xx/5xx response (not retried).
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
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, limit: int = 10) -> list[dict[str, Any]]:
        """Search YouTube and return parsed video dicts.

        Args:
            limit: Maximum number of videos to return (default 10,
                max 50 per request).  If *limit* exceeds 50, multiple
                paginated requests are made (each consuming 100 quota).

        Returns:
            List of parsed video dictionaries, each with mapped fields:
            ``id``, ``title``, ``content``, ``author``, ``published_date``,
            ``source_url``, ``channel_id``, ``channel_title``,
            ``thumbnail_url``.  When ``fetch_depth == "fulltext"`` is set
            in the handler config, ``content`` is enriched with the
            caption transcript (falling back to the description when the
            transcript is unavailable).  Returns an empty list on error.
        """
        if not self.api_key:
            logger.warning("YouTube API key is required. Set AUTOINFO_YOUTUBE_API_KEY.")
            return []

        if limit <= 0:
            return []

        query = self.query.strip()
        if not query:
            logger.warning("YouTube fetch called with empty query; returning empty list.")
            return []

        page_size = min(limit, MAX_RESULTS_PER_PAGE)
        all_videos: list[dict[str, Any]] = []
        next_page_token: str | None = None
        pages_requested = 0

        while len(all_videos) < limit:
            pages_requested += 1
            page_size_this = min(limit - len(all_videos), MAX_RESULTS_PER_PAGE)

            # Build query parameters
            params: dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "maxResults": page_size_this,
                "type": "video",
                "order": self.order,
                "key": self.api_key,
            }
            if self.channel_id:
                params["channelId"] = self.channel_id
            if next_page_token:
                params["pageToken"] = next_page_token

            url = f"{BASE_URL}?{urlencode(params)}"

            try:
                resp = self._request(url)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "YouTube API HTTP error %s for query '%s': %s",
                    exc.response.status_code if exc.response else "?",
                    query,
                    exc,
                )
                return all_videos  # return what we have
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning(
                    "YouTube API network error for query '%s': %s",
                    query,
                    exc,
                )
                return all_videos

            # Parse JSON response
            try:
                data = resp.json()
            except ValueError as exc:
                logger.warning(
                    "YouTube API returned non-JSON response for query '%s': %s",
                    query,
                    exc,
                )
                return all_videos

            items_raw = data.get("items") or []
            if not items_raw:
                break

            for item in items_raw:
                try:
                    video = self._map_video(item)
                    if self.config.get("fetch_depth") == "fulltext":
                        self._enrich_fulltext(video)
                    all_videos.append(video)
                except Exception as exc:
                    logger.debug(
                        "Failed to map YouTube item: %s",
                        exc,
                        exc_info=True,
                    )
                    continue

            # Check for more pages
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

        return all_videos[:limit]

    def fetch_captions(
        self,
        video_id: str,
        language: str = "en",
    ) -> dict[str, Any] | None:
        """Fetch captions for a single video.

        **⚠ Requires API key** — the Captions API is a separate
        authenticated endpoint.  ``AUTOINFO_YOUTUBE_API_KEY`` must be set.

        Args:
            video_id: YouTube video ID.
            language: Preferred caption language (default ``"en"``).

        Returns:
            Dict with ``caption_id``, ``language``, ``track_kind``,
            ``name``, and ``transcript`` (the downloaded caption track
            parsed to plain text; ``""`` when the download fails), or
            ``None`` if not available or on error.
        """
        if not self.api_key:
            logger.warning("Cannot fetch captions without API key.")
            return None

        params: dict[str, Any] = {
            "part": "snippet",
            "videoId": video_id,
            "key": self.api_key,
        }
        url = f"{CAPTIONS_BASE_URL}?{urlencode(params)}"

        try:
            resp = self._request(url)
        except Exception as exc:
            logger.warning(
                "Captions API request failed for video %s: %s",
                video_id,
                exc,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        items = data.get("items") or []
        if not items:
            return None

        # Prefer matching language, fall back to first available
        matching = [c for c in items if language in c.get("snippet", {}).get("language", "")]
        chosen = matching[0] if matching else items[0]
        snippet = chosen.get("snippet", {})
        return {
            "caption_id": chosen.get("id", ""),
            "language": snippet.get("language", ""),
            "track_kind": snippet.get("trackKind", ""),
            "name": snippet.get("name", ""),
            "transcript": self._download_transcript(chosen.get("id", "")),
        }

    def _download_transcript(self, caption_id: str) -> str:
        """Download and parse the SRT transcript for a caption track.

        Uses the Captions API download endpoint (``tfmt=srt``) through the
        same :meth:`_request` machinery as the metadata list call, then
        strips SRT timing blocks to plain text.  Returns an empty string
        on any failure (missing id, HTTP/network error, unparseable text).
        """
        if not caption_id:
            return ""
        url = (
            f"{CAPTIONS_BASE_URL}/{caption_id}"
            f"?{urlencode({'key': self.api_key, 'tfmt': 'srt'})}"
        )
        try:
            resp = self._request(url)
        except Exception as exc:
            logger.warning(
                "Caption track download failed for caption %s: %s",
                caption_id,
                exc,
            )
            return ""
        return self._parse_srt(resp.text)

    @staticmethod
    def _parse_srt(srt_text: str) -> str:
        """Convert SRT subtitle text to plain transcript text.

        Each SRT block is ``index``, ``timestamp``, then text lines; the
        index and timestamp lines are stripped and remaining text joined.

        Args:
            srt_text: Raw SRT caption payload.

        Returns:
            Plain-text transcript, or ``""`` when nothing parseable.
        """
        paragraphs: list[str] = []
        for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 3:
                continue
            paragraphs.append(" ".join(lines[2:]))
        return "\n".join(paragraphs)

    def _enrich_fulltext(self, video: dict[str, Any]) -> None:
        """Replace description content with the caption transcript.

        Called from :meth:`fetch` when the handler config has
        ``fetch_depth == "fulltext"``.  On failure (no captions, failed
        download, no video id) the description content is kept as-is.
        """
        video_id = video.get("id") or ""
        if not video_id:
            return
        captions = self.fetch_captions(video_id)
        transcript = (captions or {}).get("transcript") or ""
        if transcript:
            video["content"] = transcript
            return
        logger.warning(
            "fetch_depth=fulltext but transcript unavailable for video %s; "
            "falling back to description",
            video_id,
        )

    @staticmethod
    def requires_key() -> bool:
        """Return ``True`` — the YouTube Data API always requires a key."""
        return True

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_video(item: dict[str, Any]) -> dict[str, Any]:
        """Map a raw YouTube Data API search result item to standardised fields.

        Args:
            item: Raw JSON item from the ``items`` list in the API response.
                Each item has ``id`` (containing ``videoId``) and ``snippet``.

        Returns:
            Parsed dict with standardised field names: ``id``, ``title``,
            ``content``, ``author``, ``published_date``, ``source_url``,
            ``channel_id``, ``channel_title``, ``thumbnail_url``.
        """
        video_id_obj = item.get("id") or {}
        video_id = video_id_obj.get("videoId", "") if isinstance(video_id_obj, dict) else ""

        snippet = item.get("snippet") or {}
        channel_id = snippet.get("channelId", "")

        return {
            "id": video_id,
            "title": snippet.get("title", "") or "",
            "content": snippet.get("description", "") or "",
            "author": snippet.get("channelTitle", "") or "",
            "published_date": snippet.get("publishedAt", "") or "",
            "source_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
            "channel_id": channel_id,
            "channel_title": snippet.get("channelTitle", "") or "",
            "thumbnail_url": (
                snippet.get("thumbnails", {})
                .get("default", {})
                .get("url", "")
                or ""
            ),
        }

    # ------------------------------------------------------------------
    # Conversion to Item
    # ------------------------------------------------------------------

    def to_item(self, video: dict[str, Any]) -> Item:
        """Convert a parsed video dict to an :class:`Item` dataclass.

        Args:
            video: Parsed video dict as returned by :meth:`fetch`
                (already mapped by :meth:`_map_video`).

        Returns:
            An :class:`Item` instance populated from the video data.
        """
        video_id: str = video.get("id") or ""
        title: str = video.get("title") or ""

        return Item(
            id=video_id or str(uuid.uuid4()),
            source_name="youtube",
            source_type="youtube",
            source_platform="youtube",
            source_url=video.get("source_url") or (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
            ),
            title=title,
            content=video.get("content") or "",
            content_type="text",
            collected_at=video.get("published_date") or "",
            domain="",
            topic_tags=[],
            raw_data={
                "video_id": video_id,
                "author": video.get("author") or "",
                "channel_id": video.get("channel_id") or "",
                "channel_title": video.get("channel_title") or "",
                "published_date": video.get("published_date") or "",
                "thumbnail_url": video.get("thumbnail_url") or "",
            },
        )
