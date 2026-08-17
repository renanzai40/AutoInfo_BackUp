"""Generic HTTP JSON API collector for non-PubMed API sources.

Provides :class:`HttpApiHandler` — a configurable handler that fetches
data from any HTTP JSON API and maps responses to :class:`Item` instances.

Configuration is driven entirely by the source's ``settings`` dict in
the YAML source configuration.  No hardcoded endpoints, paths, or field
names — everything is configurable per-source.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import trafilatura

from autoinfo.collectors.base import BaseHandler, SourceFailure
from autoinfo.config import SourceConfig
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# Sentinel to allow dispatch in collect.py to recognise this handler type
# without importing the class (avoids circular imports).
_HANDLER_MARKER = "HttpApiHandler"


class HttpApiHandler(BaseHandler):
    """Generic HTTP JSON API collector.

    Fetches data from a JSON API endpoint, extracts items using a
    configurable JSON path, maps response fields to :class:`Item`
    attributes, and returns a list of items.

    **Configuration** (via ``SourceConfig.settings``):

    +----------------------+---------------------------------------------------+
    | Setting              | Description                                       |
    +======================+===================================================+
    | ``query_param``      | Query parameter name for search terms             |
    |                      | (default: ``"q"``).                               |
    +----------------------+---------------------------------------------------+
    | ``json_path``        | Dot-separated JSON path to the array of items     |
    |                      | in the response (e.g. ``"message.items"``).       |
    |                      | If empty, the entire response is treated as a     |
    |                      | single item wrapped in a list.                    |
    +----------------------+---------------------------------------------------+
    | ``json_path: "$"``   | The entire HTTP response body IS the array of     |
    |                      | items (e.g. a Mastodon public timeline returns a  |
    |                      | top-level JSON array).  ``"$.field"`` selects an  |
    |                      | array nested under a key (Bluesky ``"$.posts"``). |
    +----------------------+---------------------------------------------------+
    | ``field_mapping``    | Dict mapping :class:`Item` field names to JSON    |
    |                      | paths in each raw item.  Supported item fields:   |
    |                      | ``id``, ``title``, ``content``, ``source_url``.   |
    |                      | JSON paths support dot-notation and array         |
    |                      | indexing (e.g. ``"title[0]"``).                   |
    +----------------------+---------------------------------------------------+
    | ``api_key``          | API key string.  Alternatively, set the           |
    |                      | ``AUTOINFO_HTTP_API_KEY`` environment variable.   |
    +----------------------+---------------------------------------------------+
    | ``auth_mode``        | How to pass ``api_key``: ``"header"`` (Bearer     |
    |                      | token) or ``"query"`` (``?api_key=...``).         |
    |                      | Default: ``"header"``.                            |
    +----------------------+---------------------------------------------------+
    | ``params``           | Extra query parameters to include in every        |
    |                      | request (dict).                                   |
    +----------------------+---------------------------------------------------+
    | ``headers``          | Extra HTTP headers to include in every request    |
    |                      | (dict).                                           |
    +----------------------+---------------------------------------------------+
    | ``rate_limit``       | Minimum delay in seconds between requests.        |
    |                      | Default: ``1.0``.                                 |
    +----------------------+---------------------------------------------------+
    | ``timeout``          | Request timeout in seconds.  Default: ``30``.     |
    +----------------------+---------------------------------------------------+
    | ``page_param``       | Query parameter name for pagination offset/page   |
    |                      | (e.g. ``"offset"``, ``"page"``).                  |
    +----------------------+---------------------------------------------------+
    | ``page_size_param``  | Query parameter name for page size                |
    |                      | (default: ``"rows"``).                            |
    +----------------------+---------------------------------------------------+
    | ``page_size``        | Number of items per page (default: 20).           |
    +----------------------+---------------------------------------------------+
    | ``max_pages``        | Maximum number of pages to fetch (default: 3).    |
    +----------------------+---------------------------------------------------+

    Usage::

        config = SourceConfig(
            name="CrossRef",
            type="api",
            url="https://api.crossref.org/works",
            settings={
                "query_param": "query",
                "json_path": "message.items",
                "field_mapping": {
                    "id": "DOI",
                    "title": "title[0]",
                    "content": "abstract",
                    "source_url": "URL",
                },
            },
        )
        handler = HttpApiHandler(config)
        items = handler.fetch(config.url, query="CRISPR", limit=5)
    """

    # Class-level marker so dispatch in collect.py can identify this
    # handler without importing the class (avoiding potential circular
    # imports).
    _handler_type: str = _HANDLER_MARKER

    def __init__(self, source_config: SourceConfig) -> None:
        """Initialise the handler from a :class:`SourceConfig`.

        All per-source configuration is read from
        ``source_config.settings``.  ``source_config.fetch_depth`` is
        available for handlers that need to control content depth
        (e.g. ``"abstract"`` vs ``"fulltext"``), though most HTTP API
        sources already return full content by default.
        """
        self.source_config = source_config
        self.source_name = source_config.name
        self._settings = source_config.settings
        self._last_request_time = 0.0
        # Count of items dropped because both title and content were empty
        # after field mapping (issue #180 — e.g. sources with no
        # ``field_mapping`` produce whole-dict items with no usable fields).
        self.dropped_empty_items: int = 0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the next request is allowed under the rate limit."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        rate_limit = float(self._settings.get("rate_limit", 1.0))
        if rate_limit <= 0:
            return

        elapsed = time.time() - self._last_request_time
        min_interval = 1.0 / rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str, query: str = "", limit: int = 20) -> list[Item]:
        """Fetch items from the configured API endpoint.

        Parameters
        ----------
        url : str
            The base URL of the API endpoint (from ``SourceConfig.url``).
        query : str
            Optional search query to pass as a query parameter.
        limit : int
            Maximum number of items to return (default 20).  Pagination
            may be used to gather items across multiple requests.

        Returns
        -------
        list[Item]
            Collected items.

        Raises
        ------
        SourceFailure
            On any HTTP/network/parse failure, so a dead source surfaces
            as an explicit structured failure instead of a silent empty
            list (issue #135).
        """
        timeout = float(self._settings.get("timeout", 30))

        try:
            all_items: list[dict[str, Any]] = []
            page = 0
            page_size = int(self._settings.get("page_size", 20))
            max_pages = int(self._settings.get("max_pages", 3))

            while len(all_items) < limit and page < max_pages:
                params = self._build_request_params(query, page, page_size)
                headers = self._build_request_headers()

                self._wait_for_rate_limit()
                kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
                # Passing an empty params dict to httpx.get strips the URL's
                # own query string (Stack Exchange 400 regression) — feed-style
                # URLs carry their query params inline and need none from here.
                if params:
                    kwargs["params"] = params
                response = httpx.get(url, **kwargs)
                response.raise_for_status()
                data = response.json()

                items_chunk = self._extract_items_list(data)
                if not items_chunk:
                    # No more items — break pagination loop
                    break

                all_items.extend(items_chunk)
                page += 1

                # If chunk is smaller than page_size, we've hit the end
                if len(items_chunk) < page_size:
                    break

        except Exception as exc:
            logger.error(
                "HTTP API fetch failed for %s (source: %s): %s",
                url,
                self.source_name,
                exc,
            )
            raise SourceFailure(
                f"HTTP API fetch failed for {url} (source: {self.source_name}): {exc}"
            ) from exc

        return self._map_to_items(all_items[:limit])

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_request_params(self, query: str, page: int, page_size: int) -> dict[str, Any]:
        """Construct the query parameter dict for a request.

        Merges static ``params`` from settings with dynamic parameters
        (query, pagination) and optional API key as query param.
        """
        params: dict[str, Any] = dict(self._settings.get("params", {}))

        # -- Query ----------------------------------------------------------
        # Only inject the topic when the source explicitly configures a
        # query_param name.  Feed-style sources (fixed-URL JSON feeds with
        # json_path + field_mapping, no query_param) never receive a query —
        # inventing a default name (e.g. "q") appends ?q= to an endpoint
        # that answers 404 on unexpected params (apple-music regression).
        query_param = self._settings.get("query_param", "")
        if query and query_param:
            params[query_param] = query

        # -- Pagination -----------------------------------------------------
        page_param = self._settings.get("page_param", "")
        page_size_param = self._settings.get("page_size_param", "rows")
        if page_param and page > 0:
            params[page_param] = page * page_size
        if page_size_param and page > 0:
            params[page_size_param] = page_size

        # -- API key as query param -----------------------------------------
        api_key = self._get_api_key()
        auth_mode = self._settings.get("auth_mode", "header")
        if api_key and auth_mode == "query":
            params["api_key"] = api_key

        return params

    def _build_request_headers(self) -> dict[str, str]:
        """Construct the HTTP headers dict for a request."""
        headers: dict[str, str] = dict(self._settings.get("headers", {}))

        api_key = self._get_api_key()
        auth_mode = self._settings.get("auth_mode", "header")
        if api_key and auth_mode == "header":
            headers["Authorization"] = f"Bearer {api_key}"

        return headers

    def _get_api_key(self) -> str:
        """Resolve API key: settings dict first, then environment variable."""
        return self._settings.get("api_key") or os.environ.get("AUTOINFO_HTTP_API_KEY", "")

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    def _extract_items_list(self, data: Any) -> list[dict[str, Any]]:
        """Extract the array of raw items from the API response.

        Uses ``json_path`` from settings to locate the item array:

        * ``"$"`` — the entire HTTP response body IS the array of items
          (e.g. a Mastodon public timeline returns a top-level JSON
          array).
        * ``"$.field"`` — the array lives under ``field`` of the
          response object (Bluesky-style ``"$.posts"``).
        * ``"a.b.c"`` — existing dot-path semantics on a dict response
          (e.g. CrossRef ``"message.items"``); unchanged.
        * empty — the entire response is treated as a single item
          wrapped in a list.
        """
        json_path = self._settings.get("json_path", "")

        # "$" — the response body itself is the item array.
        if json_path == "$":
            if isinstance(data, list):
                return data
            if not data:
                return []
            logger.warning(
                "json_path '$' but response for source '%s' is not a JSON array",
                self.source_name,
            )
            return []

        if not json_path:
            return [data] if data else []

        # "$.field" — array under a key, same semantics as "field".
        if json_path.startswith("$."):
            json_path = json_path[2:]

        result = _traverse_json(data, json_path)
        if result is None:
            logger.warning(
                "JSON path '%s' returned None for source '%s'",
                json_path,
                self.source_name,
            )
            return []
        if not isinstance(result, list):
            return [result]
        return result

    # ------------------------------------------------------------------
    # Item mapping
    # ------------------------------------------------------------------

    def _map_to_items(self, raw_items: list[dict[str, Any]]) -> list[Item]:
        """Convert a list of raw API item dicts into :class:`Item` instances.

        Uses ``field_mapping`` from settings to pluck values from each
        raw item.  Items that cannot be mapped are logged and skipped.
        """
        field_mapping: dict[str, str] = self._settings.get("field_mapping", {})
        items: list[Item] = []
        collected_at = datetime.now(timezone.utc).isoformat()

        for i, raw in enumerate(raw_items):
            try:
                content = _coerce_str(_get_field(raw, field_mapping.get("content", "")))

                # CrossRef-specific fallback: if the content field (abstract) is empty
                # AND the source is CrossRef, try to scrape the DOI landing page.
                if (
                    not content
                    and self.source_config.name.lower() == "crossref"
                    and self.source_config.fetch_depth in (None, "abstract", "fulltext")
                ):
                    doi_url = _get_field(raw, field_mapping.get("source_url", ""))
                    if doi_url:
                        try:
                            scraped = _scrape_doi_page(doi_url, timeout=10)
                            if scraped:
                                content = scraped
                        except Exception as scrape_exc:
                            logger.debug(
                                "CrossRef scrape fallback failed for %s: %s",
                                doi_url,
                                scrape_exc,
                            )

                title = _coerce_str(_get_field(raw, field_mapping.get("title", "")))
                source_url = (
                    _coerce_str(_get_field(raw, field_mapping.get("source_url", "")))
                    or self.source_config.url
                )
                content_type = (
                    _coerce_str(_get_field(raw, field_mapping.get("content_type", "")))
                    or "text"
                )

                # Issue #180: sources without a field_mapping (e.g. Alpha
                # Vantage) produce whole-dict items with empty title AND
                # content — drop them instead of writing garbage KB entries.
                if not title and not content:
                    self.dropped_empty_items += 1
                    logger.info(
                        "Dropping empty item %d from source '%s' "
                        "(no title and no content after field mapping)",
                        i,
                        self.source_name,
                    )
                    continue

                # Issue #286: JSON APIs (e.g. World Bank) return bare
                # numeric/symbol values ("30769700000000") as content.  Such
                # content is not article prose and must not enter the KB —
                # drop it on the same empty-item counting path.  MIN_KB_
                # CONTENT_CHARS alone can't catch long concatenated numbers.
                if content and not is_article_like_content(content):
                    self.dropped_empty_items += 1
                    logger.info(
                        "Dropping non-article item %d from source '%s' "
                        "(content contains no word-like text, "
                        "e.g. a bare numeric value)",
                        i,
                        self.source_name,
                    )
                    continue

                item = Item(
                    id=_get_field(raw, field_mapping.get("id", "")) or _make_stable_id(raw, i),
                    source_name=self.source_name,
                    source_type="api",
                    source_url=source_url,
                    title=title,
                    content=content,
                    content_type=content_type,
                    source_platform=self.source_config.name,
                    collected_at=collected_at,
                    raw_data=raw,
                )
                items.append(item)
            except Exception as exc:
                logger.warning(
                    "Skipping item %d from source '%s': %s",
                    i,
                    self.source_name,
                    exc,
                )
                continue

        return items


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _traverse_json(data: dict[str, Any], dot_path: str) -> Any:
    """Traverse a nested dict/list by dot-separated path.

    Parameters
    ----------
    data : dict
        The JSON response dict.
    dot_path : str
        Dot-separated path, e.g. ``"message.items"``.

    Returns
    -------
    Any
        The value at the path, or ``None`` if any segment is missing.
    """
    current: Any = data
    for key in dot_path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return None
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if 0 <= idx < len(current) else None
            if current is None:
                return None
        else:
            return None
    return current


def _coerce_str(value: Any) -> str:
    """Coerce a raw API field value to ``str``; ``None`` becomes ``""``.

    HTTP JSON APIs (e.g. World Bank) return numeric values for
    string-intended fields.  Coercing here keeps ``Item.title`` /
    ``Item.content`` as ``str`` so downstream joins (``kb._build_body``)
    cannot raise ``TypeError`` (issue #180).
    """
    return "" if value is None else str(value)


# Issue #286: content is article-like when it carries word-like text —
# a run of >=3 consecutive ASCII letters (every real English word is
# >=3 letters; 2-letter tokens like "US"/"AI" are codes, not prose), or
# any CJK ideograph / kana / hangul (each character is itself a word in
# Chinese/Japanese/Korean, keeping CEFR EN/ZH/JA content intact).
_ARTICLE_LIKE_RE = re.compile(r"[a-zA-Z]{3,}|[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7a3]")


def is_article_like_content(content: str) -> bool:
    """Return whether ``content`` looks like article prose, not raw data.

    HTTP JSON APIs (e.g. World Bank) return bare numeric values
    (``"30769700000000"``) for string-intended fields; such content is
    not an article and must be filtered out at collection time (issue
    #286).

    Parameters
    ----------
    content : str
        The item's content (already coerced to ``str``).

    Returns
    -------
    bool
        ``True`` if ``content`` contains at least one word-like run
        (>=3 consecutive ASCII letters, or any CJK ideograph/kana/
        hangul), ``False`` for pure numbers, symbols, whitespace, or
        short code-like tokens.
    """
    return bool(_ARTICLE_LIKE_RE.search(content or ""))


def _get_field(data: dict[str, Any], path: str) -> Any:
    """Extract a single field value from a raw item dict.

    Supports simple key access (``"DOI"``), dot-separated nesting
    (``"author.name"``), and array indexing (``"title[0]"``).

    Parameters
    ----------
    data : dict
        The raw item dict.
    path : str
        Field path expression.

    Returns
    -------
    Any
        The extracted value, or an empty string if the path is empty or
        cannot be resolved.
    """
    if not path:
        return ""

    # -- Fast path: single dict key -----------------------------------------
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', path):
        return data.get(path, "")

    # -- Array indexing: key[N] ---------------------------------------------
    m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\[(\d+)\]$', path)
    if m:
        key, idx = m.group(1), int(m.group(2))
        val = data.get(key)
        if isinstance(val, (list, tuple)) and idx < len(val):
            return val[idx]
        return ""

    # -- Dot-separated path: a.b.c ------------------------------------------
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict):
            # Handle nested array index within dot path: "a[0].b"
            m2 = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\[(\d+)\]$', key)
            if m2:
                dict_key, idx = m2.group(1), int(m2.group(2))
                current = current.get(dict_key)
                if isinstance(current, (list, tuple)) and idx < len(current):
                    current = current[idx]
                else:
                    return ""
            else:
                current = current.get(key, "")
        else:
            return ""
    return current


def _make_stable_id(raw: dict[str, Any], index: int) -> str:
    """Produce a stable-ish ID from raw item data.

    Hashes the serialised dict so the same data always yields the same ID.
    Falls back to index-position based ID if hashing fails.
    """
    try:
        raw_str = str(sorted(raw.items()))
    except Exception:
        return f"api-item-{index}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def _scrape_doi_page(doi_url: str, timeout: int = 10) -> str:
    """Fetch and extract readable text from a DOI landing page.

    Used as a fallback when the CrossRef API returns an empty abstract.
    Uses ``httpx`` for the HTTP request and ``trafilatura`` for text
    extraction from the HTML response.

    Parameters
    ----------
    doi_url : str
        The DOI URL (e.g. ``https://doi.org/10.xxxx/xxxxx``).
    timeout : int
        HTTP request timeout in seconds (default 10).

    Returns
    -------
    str
        Extracted text content, or empty string on failure.
    """
    try:
        resp = httpx.get(
            doi_url,
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; AutoInfo/1.8; "
                    "+https://github.com/1StepMore/AutoInfo)"
                ),
            },
        )
        resp.raise_for_status()
        text = trafilatura.extract(
            resp.text,
            output_format="text",
            include_links=False,
            include_images=False,
            no_fallback=False,
        )
        return (text or "").strip()
    except Exception as exc:
        logger.debug("DOI page scrape failed for %s: %s", doi_url, exc)
        return ""
