"""Unpaywall / CORE academic OA full-text link collector.

Fetches scholarly article metadata and open-access full-text URLs from
the `Unpaywall API <https://unpaywall.org/products/api>`_ (free tier:
100 000 requests/day) and optionally from the
`CORE API <https://api.core.ac.uk/docs/swagger>`_ (requires API key).

**Metadata + OA link by default** — no PDF downloads, no full-text
parsing.  The ``is_oa`` field and ``best_oa_location.url`` drive the
``source_url`` of each item so downstream consumers can fetch the
full-text themselves if needed.

When ``fetch_depth == "fulltext"`` (injected into ``config`` by the
collection pipeline), the handler additionally extracts the OA full
text via the web.py trafilatura path (``WebHandler.fetch``) and stores
it in ``content``, truncated to a configurable cap.  Any extraction
failure degrades gracefully back to the mapped content (title).

Usage::

    handler = UnpaywallHandler({"query": "CRISPR gene editing"})
    articles = handler.fetch(limit=10)
    items = [handler.to_item(a) for a in articles]

    # Use CORE provider instead:
    handler = UnpaywallHandler({"query": "CRISPR", "provider": "core"})
"""

from __future__ import annotations

import logging
import os
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

UNPAYWALL_SEARCH_URL: str = "https://api.unpaywall.org/v2/search"
CORE_SEARCH_URL: str = "https://api.core.ac.uk/v3/search/works"

DEFAULT_TIMEOUT: int = 30  # seconds
DEFAULT_LIMIT: int = 10
MAX_LIMIT_UNPAYWALL: int = 50  # Unpaywall search returns 50 per page
MAX_LIMIT_CORE: int = 100  # CORE API max
MAX_RETRIES: int = 3
RETRY_DELAYS: list[int] = [2, 4, 8]  # exponential backoff in seconds

# Polite rate limiting: 1 request per second
MIN_REQUEST_INTERVAL: float = 1.0

# Max chars of OA fulltext kept in ``content`` (LLM cost control);
# overridable per source via the ``content_cap`` config key.
FULLTEXT_CONTENT_CAP: int = 8000

# HTTP headers
USER_AGENT: str = "mailto:autoinfo-collector@example.com"


# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------


def _map_unpaywall_item(response: dict[str, Any]) -> dict[str, Any]:
    """Map a single Unpaywall DOI object to a standardised dict.

    Args:
        response: The ``response`` field from an Unpaywall search result,
            which is a full DOI object.

    Returns:
        Dict with keys: ``id`` (DOI), ``title``, ``content`` (abstract-like
        from title), ``authors``, ``published_date``, ``journal``,
        ``publisher``, ``is_oa``, ``oa_status``, ``oa_url``,
        ``oa_url_pdf``, ``source_url`` (OA URL or DOI landing page).
    """
    doi: str = response.get("doi", "")
    title: str = response.get("title") or ""
    published_date: str = response.get("published_date") or ""
    journal: str = response.get("journal_name") or ""
    publisher: str = response.get("publisher") or ""
    is_oa: bool = bool(response.get("is_oa", False))
    oa_status: str = response.get("oa_status") or ""
    genre: str = response.get("genre") or ""

    # Authors
    z_authors: list[dict[str, Any]] = response.get("z_authors") or []
    authors: list[str] = []
    for a in z_authors:
        if isinstance(a, dict):
            given = a.get("given", "")
            family = a.get("family", "")
            name_parts = [p for p in [given, family] if p]
            if name_parts:
                authors.append(" ".join(name_parts))

    # OA location
    best_oa = response.get("best_oa_location")
    oa_url: str = ""
    oa_url_pdf: str = ""
    if isinstance(best_oa, dict):
        oa_url = best_oa.get("url") or ""
        oa_url_pdf = best_oa.get("url_for_pdf") or ""

    # source_url: prefer OA full-text URL, fall back to DOI landing page
    source_url: str = oa_url or oa_url_pdf or ""
    if not source_url:
        source_url = f"https://doi.org/{doi}" if doi else ""

    return {
        "id": doi,
        "title": title,
        "content": title,  # content = title for metadata-only collector
        "authors": authors,
        "published_date": published_date,
        "journal": journal,
        "publisher": publisher,
        "is_oa": is_oa,
        "oa_status": oa_status,
        "oa_url": oa_url,
        "oa_url_pdf": oa_url_pdf,
        "source_url": source_url,
        "genre": genre,
    }


def _map_core_item(work: dict[str, Any]) -> dict[str, Any]:
    """Map a single CORE API work object to a standardised dict.

    Args:
        work: Raw work object from the CORE ``results`` list.

    Returns:
        Dict with keys matching the Unpaywall-mapped format for
        downstream interchangeability.
    """
    doi: str = work.get("doi") or ""
    title: str = work.get("title") or ""
    abstract: str = work.get("abstract") or ""
    published_date: str = work.get("publishedDate") or ""
    if not published_date:
        published_date = str(work.get("yearPublished", ""))
    journal: str = work.get("journal") or ""
    publisher: str = work.get("publisher") or ""

    # Authors
    authors_raw = work.get("authors") or []
    authors: list[str] = []
    for a in authors_raw:
        if isinstance(a, str):
            authors.append(a)
        elif isinstance(a, dict):
            name = a.get("name", "")
            if name:
                authors.append(name)

    # OA links from CORE
    download_url: str = work.get("downloadUrl") or ""
    full_text_url: str = work.get("fullText") or ""
    source_url: str = (
        download_url
        or full_text_url
        or work.get("sourceFulltextUrls", [None])[0]
        or ""
    )
    if not source_url and doi:
        source_url = f"https://doi.org/{doi}"

    is_oa: bool = bool(download_url or full_text_url)

    return {
        "id": doi,
        "title": title,
        "content": abstract or title,
        "authors": authors,
        "published_date": published_date,
        "journal": journal,
        "publisher": publisher,
        "is_oa": is_oa,
        "oa_status": "",
        "oa_url": source_url,
        "oa_url_pdf": "",
        "source_url": source_url,
        "genre": "",
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class UnpaywallHandler(BaseHandler):
    """Fetch OA metadata + full-text links from Unpaywall or CORE.

    Supports two backends via ``provider`` config key:

    * ``"unpaywall"`` (default) — free search API, 100k req/day.
      Requires ``AUTOINFO_UNPAYWALL_EMAIL`` env var.
    * ``"core"`` — CORE API v3, requires ``AUTOINFO_CORE_API_KEY``.

    Usage::

        handler = UnpaywallHandler({"query": "CRISPR"})
        results = handler.fetch(limit=10)
        items = [handler.to_item(r) for r in results]
    """

    source_type: str = "unpaywall"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise handler.

        Args:
            config: Dictionary with optional keys:
                - ``query``: search query string (default ``""``)
                - ``provider``: ``"unpaywall"`` (default) or ``"core"``
                - ``is_oa``: filter by OA status (Unpaywall only;
                  default ``None`` = no filter)
                - ``max_rps``: requests per second rate limit
                  (default ``1.0``)
                - ``fetch_depth``: ``"fulltext"`` enables OA full-text
                  extraction via the web.py trafilatura path
                  (default ``None`` = metadata only)
                - ``content_cap``: max chars of extracted full text
                  (default :data:`FULLTEXT_CONTENT_CAP`)
        """
        if config is None:
            config = {}
        self.config: dict[str, Any] = config
        self.provider: str = config.get("provider", "unpaywall").lower()
        self.max_rps: float = float(config.get("max_rps", 1.0))
        self.content_cap: int = int(
            config.get("content_cap", FULLTEXT_CONTENT_CAP)
        )
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Key check
    # ------------------------------------------------------------------

    def _has_credentials(self) -> bool:
        """Check whether the required credential for the active provider
        is present in the environment."""
        if self.provider == "core":
            return bool(os.environ.get("AUTOINFO_CORE_API_KEY"))
        return bool(os.environ.get("AUTOINFO_UNPAYWALL_EMAIL"))

    @staticmethod
    def requires_key() -> bool:
        """Return ``True`` — credentials (email or API key) are always
        required for this handler."""
        return True

    # ------------------------------------------------------------------
    # API note
    # ------------------------------------------------------------------

    @staticmethod
    def note() -> str | None:
        """Return a note about the handler's content-depth behaviour."""
        return (
            "Unpaywall/CORE collector fetches metadata + OA links; with "
            "fetch_depth=fulltext it also extracts the OA full text via "
            "the web.py trafilatura path. "
            "Use the returned source_url to access the full text externally."
        )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed under the rate limit."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        min_interval = (
            1.0 / self.max_rps if self.max_rps > 0 else MIN_REQUEST_INTERVAL
        )
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # HTTP request with retry
    # ------------------------------------------------------------------

    def _request(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue a GET request with rate limiting and exponential-backoff retry.

        Args:
            url: Fully qualified URL to fetch.
            headers: Optional extra HTTP headers.

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
                response = httpx.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    headers=headers or {},
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                # Do not retry 4xx/5xx — propagate immediately
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    raise
                logger.debug(
                    "Retry %d/%d after error: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )
                time.sleep(RETRY_DELAYS[attempt])

        raise RuntimeError("Unexpected: all retries exhausted") from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        query: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Fetch OA metadata from Unpaywall or CORE.

        Args:
            query: Search query string. Falls back to
                ``self.config["query"]`` if empty.
            limit: Maximum number of results to return (default 10).

        Returns:
            List of article dicts, each with standardised fields.
            When ``fetch_depth == "fulltext"``, articles carrying an OA
            URL are enriched with the extracted full text in ``content``
            (truncated to ``content_cap``); extraction failures keep the
            mapped content (title for Unpaywall).
            Returns an empty list on error, missing credentials,
            or if *limit* ≤ 0.
        """
        if limit <= 0:
            return []

        q = (query or self.config.get("query", "") or "").strip()
        if not q:
            logger.warning(
                "Unpaywall fetch called with empty query; returning []."
            )
            return []

        # Guard: missing credentials → graceful degradation
        if not self._has_credentials():
            missing = (
                "AUTOINFO_UNPAYWALL_EMAIL"
                if self.provider == "unpaywall"
                else "AUTOINFO_CORE_API_KEY"
            )
            logger.warning(
                "Unpaywall fetch: %s not set in environment; returning [].",
                missing,
            )
            return []

        if self.provider == "core":
            articles = self._fetch_core(q, limit)
        else:
            articles = self._fetch_unpaywall(q, limit)

        if self.config.get("fetch_depth") == "fulltext":
            return [self._maybe_fetch_fulltext(a) for a in articles]
        return articles

    # ------------------------------------------------------------------
    # Fulltext enrichment (fetch_depth == "fulltext")
    # ------------------------------------------------------------------

    def _maybe_fetch_fulltext(self, article: dict[str, Any]) -> dict[str, Any]:
        """Attempt OA full-text extraction for *article*.

        Active only when ``fetch_depth == "fulltext"`` and the article
        carries an OA URL.  Reuses the web.py trafilatura path
        (``WebHandler.fetch``) to fetch and extract the open-access
        page; tries ``oa_url`` then ``oa_url_pdf``.  Replaces ``content``
        with the extracted text truncated to :attr:`content_cap`.

        On any failure (no OA URL, fetch error, empty extraction) the
        article is returned unchanged with a warning logged — collection
        never breaks.
        """
        candidates = [
            str(article.get("oa_url") or "").strip(),
            str(article.get("oa_url_pdf") or "").strip(),
        ]
        attempted: str = ""
        for url in candidates:
            if not url:
                continue
            attempted = url
            try:
                items = WebHandler().fetch(url)
            except Exception as exc:
                logger.debug("OA fulltext fetch raised for %s: %s", url, exc)
                continue
            if items:
                text = (items[0].content or "").strip()
                if text:
                    article["content"] = text[: self.content_cap]
                    return article

        if attempted:
            logger.warning(
                "Unpaywall fulltext extraction failed for %s; "
                "keeping mapped content for '%s'.",
                attempted,
                article.get("title") or article.get("id") or "",
            )
        return article

    # ------------------------------------------------------------------
    # Unpaywall backend
    # ------------------------------------------------------------------

    def _fetch_unpaywall(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch from the Unpaywall search API.

        GET https://api.unpaywall.org/v2/search?query=...&email=...&page=N
        """
        email = os.environ.get("AUTOINFO_UNPAYWALL_EMAIL", "")

        params: dict[str, Any] = {
            "query": query,
            "email": email,
        }

        # Optional is_oa filter from config
        if "is_oa" in self.config:
            params["is_oa"] = str(self.config["is_oa"]).lower()

        enc = urlencode(params)
        url = f"{UNPAYWALL_SEARCH_URL}?{enc}"

        all_articles: list[dict[str, Any]] = []

        try:
            resp = self._request(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "?"
            logger.warning(
                "Unpaywall API HTTP error %s for query '%s': %s",
                status,
                query,
                exc,
            )
            return []
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "Unpaywall API network error for query '%s': %s",
                query,
                exc,
            )
            return []
        except Exception as exc:
            logger.warning(
                "Unpaywall API unexpected error for query '%s': %s",
                query,
                exc,
                exc_info=True,
            )
            return []

        # Parse JSON
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "Unpaywall API returned non-JSON for query '%s': %s",
                query,
                exc,
            )
            return []

        results: list[dict[str, Any]] = data.get("results") or []
        for result in results:
            try:
                response_obj = result.get("response")
                if not isinstance(response_obj, dict):
                    continue
                article = _map_unpaywall_item(response_obj)
                all_articles.append(article)
            except Exception as exc:
                logger.debug(
                    "Failed to map Unpaywall item: %s", exc, exc_info=True
                )
                continue

        return all_articles[:limit]

    # ------------------------------------------------------------------
    # CORE backend
    # ------------------------------------------------------------------

    def _fetch_core(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch from the CORE API v3.

        GET https://api.core.ac.uk/v3/search/works?q=...&limit=N
        Authorization: Bearer <AUTOINFO_CORE_API_KEY>
        """
        api_key = os.environ.get("AUTOINFO_CORE_API_KEY", "")
        page_size = min(limit, MAX_LIMIT_CORE)

        params: dict[str, Any] = {
            "q": query,
            "limit": page_size,
        }
        enc = urlencode(params)
        url = f"{CORE_SEARCH_URL}?{enc}"

        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {api_key}",
        }

        all_articles: list[dict[str, Any]] = []

        try:
            resp = self._request(url, headers=headers)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "?"
            logger.warning(
                "CORE API HTTP error %s for query '%s': %s",
                status,
                query,
                exc,
            )
            return []
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "CORE API network error for query '%s': %s",
                query,
                exc,
            )
            return []
        except Exception as exc:
            logger.warning(
                "CORE API unexpected error for query '%s': %s",
                query,
                exc,
                exc_info=True,
            )
            return []

        # Parse JSON
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "CORE API returned non-JSON for query '%s': %s",
                query,
                exc,
            )
            return []

        results: list[dict[str, Any]] = data.get("results") or []
        for work in results:
            try:
                article = _map_core_item(work)
                all_articles.append(article)
            except Exception as exc:
                logger.debug(
                    "Failed to map CORE item: %s", exc, exc_info=True
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
        doi = article.get("id") or ""
        oa_url = article.get("oa_url") or ""

        return Item(
            id=doi or str(uuid.uuid4()),
            source_name="unpaywall",
            source_type="unpaywall",
            source_platform="unpaywall",
            source_url=article.get("source_url") or "",
            title=article.get("title") or "",
            content=article.get("content") or "",
            content_type="text",
            collected_at=article.get("published_date") or "",
            language="",
            domain="",
            topic_tags=[],
            raw_data={
                "doi": doi,
                "authors": article.get("authors") or [],
                "published_date": article.get("published_date") or "",
                "journal": article.get("journal") or "",
                "publisher": article.get("publisher") or "",
                "is_oa": article.get("is_oa", False),
                "oa_status": article.get("oa_status") or "",
                "oa_url": oa_url,
                "oa_url_pdf": article.get("oa_url_pdf") or "",
                "genre": article.get("genre") or "",
                "provider": self.provider,
            },
        )
