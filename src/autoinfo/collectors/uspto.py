"""USPTO patent collector via PatentsView API.

Searches and fetches patent data using the free PatentsView REST API
(https://patentsview.org/).  Supports keyword queries and returns
structured patent metadata with field mapping to :class:`Item`.

The primary API (PatentsView) requires no authentication for basic
queries.  For higher rate limits, register for a PatentsView API key.
As a fallback, the USPTO patent search RSS feed is also supported.

Registration for API key (optional):
    https://patentsview.org/apis/api-key

USPTO Developer API (requires OAuth registration):
    https://developer.uspto.gov/api-catalog
    https://developer.uspto.gov/ds-api/patent/application/v1/
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import httpx

from autoinfo.collectors.base import BaseHandler, SourceFailure
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Primary: PatentsView API (free, no-auth for basic queries)
PATENTSVIEW_BASE_URL = "https://api.patentsview.org/patents/query"
PATENTSVIEW_DEFAULT_FIELDS = [
    "patent_number",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "app_date",
    "inventor_first_name",
    "inventor_last_name",
    "assignee_organization",
    "inventor_country",
    "patent_num_cited_by_us_patents",
    "patent_num_combined_citations",
]

# Fallback: USPTO RSS feed
USPTO_RSS_URL = "https://www.uspto.gov/feeds/patent_application.xml"

DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # exponential backoff in seconds
RATE_LIMIT_DEFAULT = 5  # requests / second (no API key)
RATE_LIMIT_WITH_KEY = 45  # requests / second (with API key)

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class USPTOHandler(BaseHandler):
    """Fetch patent data using the PatentsView API.

    Primary API is the free PatentsView REST endpoint.  Falls back
    to the USPTO patent application RSS feed if the PatentsView API
    is unavailable or when ``use_rss=True`` is passed.

    Usage::

        handler = USPTOHandler()
        patents = handler.fetch("gene editing", limit=10)
        for patent in patents:
            print(patent["title"], patent["patent_number"])

        # Convert to Item for KB storage
        items = [handler.to_item(p) for p in patents]

    The USPTO Developer API (``developer.uspto.gov``) requires OAuth
    registration.  If you have credentials, set the
    ``AUTOINFO_USPTO_API_KEY`` environment variable.
    """

    source_name: str = "uspto"

    def __init__(self, api_key: str | None = None, source_config: Any = None) -> None:
        """Initialise handler.

        Args:
            api_key: Optional PatentsView API key for higher rate
                limits (45 req/s instead of 5).  Falls back to the
                ``AUTOINFO_USPTO_API_KEY`` environment variable.
            source_config: Optional :class:`SourceConfig` for per-source
                settings (e.g. fetch_depth, rate_limit).
        """
        self.api_key = api_key or os.environ.get("AUTOINFO_USPTO_API_KEY", "")
        self.source_config = source_config
        self.max_rps = RATE_LIMIT_WITH_KEY if self.api_key else RATE_LIMIT_DEFAULT
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed under the rate limit."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        elapsed = time.time() - self._last_request_time
        min_interval = 1.0 / self.max_rps
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # HTTP request with retry
    # ------------------------------------------------------------------

    def _request(
        self,
        url: str,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue an HTTP request with rate limiting and exponential-backoff retry.

        Args:
            url: Fully qualified URL to fetch.
            method: HTTP method (``"GET"`` or ``"POST"``).
            json_body: Optional JSON body for POST requests.
            headers: Optional HTTP headers.

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
                if method == "POST":
                    response = httpx.post(
                        url,
                        json=json_body,
                        headers=headers,
                        timeout=DEFAULT_TIMEOUT,
                    )
                else:
                    response = httpx.get(
                        url,
                        headers=headers,
                        timeout=DEFAULT_TIMEOUT,
                    )
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAYS[attempt])

        raise RuntimeError("Unexpected: all retries exhausted") from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        query: str = "",
        limit: int = 10,
        use_rss: bool = False,
    ) -> list[dict[str, Any]]:
        """Search patents and return parsed patent dicts.

        By default uses the PatentsView REST API.  When *use_rss*
        is ``True`` or the PatentsView API is unavailable, falls
        back to the USPTO RSS feed.

        Args:
            query: Search term (e.g. ``"gene editing"``).  When empty,
                returns the most recent patents (RSS fallback) or runs
                a broad query (PatentsView).
            limit: Maximum number of patents to return (default 10).
            use_rss: If ``True``, use the USPTO RSS feed instead of
                the PatentsView API.

        Returns:
            List of parsed patent dictionaries, each with mapped fields.
        """
        limit = max(1, min(limit, 500))

        if use_rss:
            return self._fetch_rss(query, limit)

        try:
            return self._fetch_patentsview(query, limit)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (301, 302, 307, 308):
                # PatentsView was retired by USPTO (issue #135): the endpoint
                # 301-redirects to a data.uspto.gov transition guide, not to a
                # working API.  Surface an explicit structured failure instead
                # of silently returning [].
                raise SourceFailure(
                    "PatentsView API retired by USPTO (HTTP 301; migrated to "
                    "data.uspto.gov) — no keyless patent search API available"
                ) from exc
            logger.warning(
                "PatentsView API unavailable, falling back to RSS feed",
                exc_info=True,
            )
            return self._fetch_rss(query, limit)
        except Exception:
            logger.warning(
                "PatentsView API unavailable, falling back to RSS feed",
                exc_info=True,
            )
            return self._fetch_rss(query, limit)

    # ------------------------------------------------------------------
    # PatentsView API (primary)
    # ------------------------------------------------------------------

    def _fetch_patentsview(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Fetch patents via the PatentsView REST API.

        Uses a POST request with a JSON query body.  The PatentsView
        API uses a structured query language (not simple keyword search),
        so we construct a ``_text_any`` query for keyword matching.

        API docs: https://patentsview.org/apis/purpose
        """
        # Build the POST body — PatentsView uses a JSON query DSL
        body: dict[str, Any] = {
            "q": {},
            "f": PATENTSVIEW_DEFAULT_FIELDS,
            "o": {
                "page": 1,
                "per_page": limit,
            },
        }

        if query.strip():
            body["q"] = {"_text_any": {"patent_title": query}}

        # Sort by patent date descending (most recent first)
        body["o"]["sort"] = [{"patent_date": "desc"}]

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        resp = self._request(
            PATENTSVIEW_BASE_URL,
            method="POST",
            json_body=body,
            headers=headers,
        )
        data = resp.json()

        patents_raw = data.get("patents") or []
        return [self._map_patent(p) for p in patents_raw]

    # ------------------------------------------------------------------
    # USPTO RSS feed (fallback)
    # ------------------------------------------------------------------

    def _fetch_rss(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Fetch patents via the USPTO RSS feed.

        Parses the XML RSS feed at `USPTO_RSS_URL` and extracts patent
        titles and links.  The RSS feed provides limited metadata —
        only title, link, and publication date.

        This is a best-effort fallback when the PatentsView API is
        unavailable.
        """
        import xml.etree.ElementTree as ET

        # Build RSS URL with optional category filter from query
        url = USPTO_RSS_URL
        try:
            resp = self._request(url)
        except httpx.HTTPStatusError as exc:
            raise SourceFailure(
                f"USPTO RSS feed unavailable (HTTP {exc.response.status_code}): "
                f"{USPTO_RSS_URL}"
            ) from exc
        root = ET.fromstring(resp.text)

        patents: list[dict[str, Any]] = []
        items_found = 0

        for item_elem in root.findall(".//item"):
            if items_found >= limit:
                break

            title_elem = item_elem.find("title")
            link_elem = item_elem.find("link")
            date_elem = item_elem.find("pubDate")
            desc_elem = item_elem.find("description")

            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            published = date_elem.text.strip() if date_elem is not None and date_elem.text else ""
            description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

            # Extract patent application number from link/title if possible
            patent_number = self._extract_patent_number_from_rss(title, link)

            # Apply keyword filter if query provided
            if query.strip():
                ql = query.lower()
                if ql not in title.lower() and ql not in description.lower():
                    continue

            patents.append({
                "id": patent_number,
                "title": title,
                "abstract": description,
                "authors": [],  # RSS does not include inventor info
                "filed_date": "",
                "published_date": published,
                "patent_number": patent_number,
                "source_type": "rss",
            })
            items_found += 1

        return patents

    @staticmethod
    def _extract_patent_number_from_rss(title: str, link: str) -> str:
        """Try to extract a patent/application number from RSS metadata.

        Heuristic: look for patterns like US2024xxxxxx or US 2024/xxxxxx
        in the title or URL.
        """
        import re

        # Try title first — common format: "US 2024/0123456 A1"
        m = re.search(r"US\s*(\d{4}[/-]\d{4,})", title, re.IGNORECASE)
        if m:
            return "US" + m.group(1).replace("/", "").replace("-", "")

        # Try link — URL often contains the application number
        m = re.search(r"(\d{8,})", link)
        if m:
            return m.group(1)

        # Fallback: hash of the title for a stable identifier
        return str(hash(title) & 0xFFFFFFFF)

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_patent(patent: dict[str, Any]) -> dict[str, Any]:
        """Map raw PatentsView API patent dict to standardised fields.

        Args:
            patent: Raw patent dict from the API response.

        Returns:
            Parsed dict with standardised field names.
        """
        # Combine inventor first/last names
        inventors_raw: list[dict[str, str]] = patent.get("inventors") or []
        authors: list[str] = []
        for inv in inventors_raw:
            first = inv.get("inventor_first_name", "")
            last = inv.get("inventor_last_name", "")
            name = f"{first} {last}".strip()
            if name:
                authors.append(name)

        patent_number = patent.get("patent_number", "") or ""

        return {
            "id": patent_number,
            "patent_number": patent_number,
            "title": patent.get("patent_title") or "",
            "abstract": patent.get("patent_abstract") or "",
            "authors": authors,
            "filed_date": patent.get("app_date") or "",
            "published_date": patent.get("patent_date") or "",
            "assignee": patent.get("assignee_organization") or "",
            "cited_by_count": patent.get("patent_num_cited_by_us_patents") or 0,
            "total_citations": patent.get("patent_num_combined_citations") or 0,
            "source_type": "api",
        }

    # ------------------------------------------------------------------
    # Conversion to Item
    # ------------------------------------------------------------------

    def to_item(self, patent: dict[str, Any]) -> Item:
        """Convert a parsed patent dict to an :class:`Item` dataclass.

        Args:
            patent: Parsed patent dict as returned by :meth:`fetch`
                (already mapped by :meth:`_map_patent`).

        Returns:
            An :class:`Item` instance populated from the patent data.
        """
        patent_id: str = patent.get("id") or ""
        patent_number: str = patent.get("patent_number") or ""
        title: str = patent.get("title") or ""

        return Item(
            id=patent_id or str(uuid.uuid4()),
            source_name=self.source_name,
            source_type=patent.get("source_type", "api"),
            source_platform="uspto",
            source_url=(
                f"https://patents.google.com/patent/{patent_number}/en"
                if patent_number
                else ""
            ),
            title=title,
            content=patent.get("abstract") or "",
            content_type="text",
            collected_at=patent.get("published_date") or "",
            domain="medical-research",
            topic_tags=[],
            raw_data={
                "patent_number": patent_number,
                "authors": patent.get("authors") or [],
                "filed_date": patent.get("filed_date") or "",
                "published_date": patent.get("published_date") or "",
                "assignee": patent.get("assignee") or "",
                "cited_by_count": patent.get("cited_by_count") or 0,
                "total_citations": patent.get("total_citations") or 0,
            },
        )
