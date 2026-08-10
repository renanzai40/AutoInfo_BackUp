"""OpenAlex academic collector handler.

Fetches scholarly works from the OpenAlex REST API
(https://api.openalex.org/works) and maps them to AutoInfo's
internal item format.

OpenAlex is a free, open index of scholarly papers, authors,
institutions, and venues.  No API key is required.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.openalex.org/works"
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_RATE_LIMIT = 10  # requests / second (standard pool)
POLITE_RATE_LIMIT = 100  # requests / second (polite pool with email)
USER_AGENT = "mailto:autoinfo-collector@example.com"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class OpenAlexHandler(BaseHandler):
    """Fetch scholarly works from the OpenAlex API.

    Usage::

        handler = OpenAlexHandler({"query": "CRISPR gene editing"})
        articles = handler.fetch(limit=10)
        items = [handler.to_item(a) for a in articles]
    """

    source_type: str = "openalex"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise handler.

        Args:
            config: Dictionary with optional keys:
                - ``query``: search query string (default ``""``)
                - ``filters``: OpenAlex filter string (e.g.
                  ``"publication_year:2024"``)
                - ``rate_limit_per_second``: requests/second cap
                  (default 10)
        """
        if config is None:
            config = {}
        self.config: dict[str, Any] = config
        self.rate_limit = config.get("rate_limit_per_second", DEFAULT_RATE_LIMIT)
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
        min_interval = 1.0 / self.rate_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # Abstract reconstruction
    # ------------------------------------------------------------------

    @staticmethod
    def _reconstruct_abstract(
        inverted_index: dict[str, list[int]] | None,
    ) -> str:
        """Reconstruct a plain-text abstract from an OpenAlex inverted index.

        An inverted index maps each word to the list of positions where
        it appears in the original text.  This method sorts all
        (position, word) pairs and concatenates them in order.

        Args:
            inverted_index: The ``abstract_inverted_index`` from an
                OpenAlex work object, or ``None``/``{}``.

        Returns:
            Reconstructed plain-text abstract string.  Returns ``""``
            for an empty or missing index.
        """
        if not inverted_index:
            return ""

        word_positions: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        word_positions.sort(key=lambda pair: pair[0])
        return " ".join(word for _, word in word_positions)

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_work_to_article(work: dict[str, Any]) -> dict[str, Any]:
        """Map a single OpenAlex work JSON object to AutoInfo article dict.

        Args:
            work: Raw work object from the ``results`` list.

        Returns:
            Dict with keys: ``id``, ``title``, ``abstract``,
            ``authors``, ``cited_by_count``, ``published_date``.
        """
        # -- id: prefer DOI, fall back to OpenAlex work ID --
        work_id = work.get("id", "")

        # -- title --
        title = work.get("title", "")

        # -- abstract from inverted index --
        inverted = work.get("abstract_inverted_index")
        abstract = OpenAlexHandler._reconstruct_abstract(inverted)

        # -- authors (names only, no affiliations) --
        authors: list[str] = []
        for authorship in work.get("authorships", []) or []:
            author_obj = authorship.get("author") if isinstance(authorship, dict) else None
            if author_obj and isinstance(author_obj, dict):
                name = author_obj.get("display_name", "")
                if name:
                    authors.append(name)

        # -- cited_by_count --
        cited_by_count = work.get("cited_by_count", 0)

        # -- publication_date --
        published_date = work.get("publication_date", "")

        return {
            "id": work_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "cited_by_count": cited_by_count,
            "published_date": published_date,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, limit: int = 10, query: str = "") -> list[dict[str, Any]]:
        """Fetch works from the OpenAlex API.

        Args:
            limit: Maximum number of results to return (default 10).
            query: Topic query override. When non-empty it takes precedence
                over the configured ``query`` so collection can pass topic
                keywords into the API ``search`` param (#177).

        Returns:
            List of article dicts, each with keys ``id``, ``title``,
            ``abstract``, ``authors``, ``cited_by_count``,
            ``published_date``.  Returns an empty list on error.
        """
        if limit <= 0:
            return []

        # -- Build query parameters --
        params: dict[str, Any] = {}

        search_query = query or self.config.get("query", "")
        if search_query:
            params["search"] = search_query

        extra_filters = self.config.get("filters", "")
        if extra_filters:
            params["filter"] = extra_filters

        params["per_page"] = min(limit, 200)  # OpenAlex max per_page is 200

        # -- Build URL with search param --
        url = BASE_URL
        if params:
            # Manually encode the query string so we control the format
            query_parts: list[str] = []
            for key, value in params.items():
                query_parts.append(f"{key}={quote(str(value))}")
            url += "?" + "&".join(query_parts)

        # -- Make HTTP request --
        self._wait_for_rate_limit()

        try:
            response = httpx.get(
                url,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OpenAlex HTTP error %s for URL %s",
                exc.response.status_code if exc.response else "?",
                url,
                exc_info=True,
            )
            return []
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "OpenAlex network error for URL %s: %s",
                url,
                exc,
            )
            return []
        except Exception as exc:
            logger.warning(
                "OpenAlex unexpected error for URL %s: %s",
                url,
                exc,
                exc_info=True,
            )
            return []

        # -- Parse JSON response --
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(
                "OpenAlex returned non-JSON response for URL %s: %s",
                url,
                exc,
            )
            return []

        results = data.get("results", [])
        if not results:
            return []

        # -- Map each work to article dict --
        articles: list[dict[str, Any]] = []
        for work in results:
            article = self._map_work_to_article(work)
            articles.append(article)

        # -- Apply limit --
        return articles[:limit]

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
        work_id = article.get("id", "")
        return Item(
            id=work_id or str(uuid.uuid4()),
            source_name="openalex",
            source_type="api",
            source_platform="openalex",
            source_url=(
                f"https://api.openalex.org/works/{work_id}"
                if work_id
                else ""
            ),
            title=article.get("title", ""),
            content=article.get("abstract", ""),
            content_type="text",
            collected_at=article.get("published_date", ""),
            domain="medical-research",
            topic_tags=[],
            raw_data={
                "authors": article.get("authors", []),
                "cited_by_count": article.get("cited_by_count", 0),
                "published_date": article.get("published_date", ""),
            },
        )
