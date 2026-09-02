"""PubMed E-utilities handler.

Searches and fetches articles via the NCBI PubMed API using
``esearch`` (JSON) and ``efetch`` (XML) endpoints.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # exponential backoff in seconds
RATE_LIMIT_DEFAULT = 3  # requests / second (no API key)
RATE_LIMIT_WITH_KEY = 10  # requests / second (with API key)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class PubMedHandler(BaseHandler):
    """Fetch PubMed articles using NCBI E-utilities.

    Usage::

        handler = PubMedHandler()
        pmids = handler.search("IVF breakthroughs", max_results=5)
        articles = handler.fetch(pmids)
        items = [handler.to_item(a) for a in articles]
    """

    def __init__(self, api_key: str | None = None, source_config=None) -> None:
        """Initialise handler.

        Args:
            api_key: Optional NCBI API key for higher rate limits
                (10 req/s instead of 3). Falls back to the
                ``AUTOINFO_PUBMED_API_KEY`` environment variable.
            source_config: Optional :class:`SourceConfig` for fetch_depth
                and other per-source settings.
        """
        self.api_key = api_key or os.environ.get("AUTOINFO_PUBMED_API_KEY", "")
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
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAYS[attempt])

        # Unreachable — the loop always returns or raises on the last attempt.
        raise RuntimeError("Unexpected: all retries exhausted") from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> list[str]:
        """Search PubMed and return PMID strings.

        Args:
            query: Search term (e.g. ``"IVF breakthroughs"``).
            max_results: Maximum number of PMIDs to return (default 5).

        Returns:
            List of PMID strings (may be empty).
        """
        url = (
            f"{BASE_URL}esearch.fcgi"
            f"?db=pubmed&term={quote(query)}&retmax={max_results}&retmode=json"
        )
        if self.api_key:
            url += f"&api_key={self.api_key}"

        resp = self._request(url)
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])

    def fetch(self, pmids: list[str]) -> list[dict[str, Any]]:
        """Fetch full article metadata for one or more PMIDs.

        Args:
            pmids: List of PMID strings.

        Returns:
            List of parsed article dictionaries, one per PMID.
        """
        joined = ",".join(pmids)
        url = (
            f"{BASE_URL}efetch.fcgi"
            f"?db=pubmed&id={joined}&retmode=xml"
        )
        if self.api_key:
            url += f"&api_key={self.api_key}"

        resp = self._request(url)
        root = ET.fromstring(resp.text)

        articles: list[dict[str, Any]] = []
        for elem in root.findall("PubmedArticle"):
            articles.append(self._parse_article(elem))

        # -- Optionally enrich with PMC full text ---------------------------
        if self.source_config is not None and self.source_config.fetch_depth in ("fulltext", "auto"):
            self._enrich_fulltext(articles)

        return articles

    def _enrich_fulltext(self, articles: list[dict[str, Any]]) -> None:
        """Replace abstract with PMC full text for articles that have a PMC ID.

        Called from :meth:`fetch` when ``fetch_depth`` is ``"fulltext"`` or
        ``"auto"``.  On failure in ``"auto"`` mode the original abstract is
        kept; in ``"fulltext"`` mode a warning is logged.
        """
        for article in articles:
            pmc_id = article.get("pmc_id", "")
            if not pmc_id:
                if self.source_config and self.source_config.fetch_depth == "fulltext":
                    logger.warning(
                        "fetch_depth=fulltext but no PMC ID for PMID %s",
                        article.get("pmid", "unknown"),
                    )
                continue
            full_text = self._fetch_pmc_fulltext(pmc_id)
            if full_text:
                article["abstract"] = full_text
            elif self.source_config and self.source_config.fetch_depth == "fulltext":
                logger.warning(
                    "fetch_depth=fulltext but PMC full text unavailable for PMC %s (PMID %s)",
                    pmc_id, article.get("pmid", "unknown"),
                )

    def _fetch_pmc_fulltext(self, pmc_id: str) -> str | None:
        """Fetch full text from PMC for a given PMC ID.

        Uses the NCBI E-utilities efetch endpoint with ``db=pmc`` to
        retrieve the article XML and extracts all paragraph text from
        ``<body>`` sections.

        Returns ``None`` on any error (network, XML parsing, or no body
        content).
        """
        try:
            url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
                f"efetch.fcgi?db=pmc&id={pmc_id}&retmode=xml"
            )
            if self.api_key:
                url += f"&api_key={self.api_key}"
            resp = self._request(url)
            root = ET.fromstring(resp.text)
            paragraphs: list[str] = []
            for p_elem in root.iter("p"):
                text = "".join(p_elem.itertext()).strip()
                if text:
                    paragraphs.append(text)
            return "\n\n".join(paragraphs) if paragraphs else None
        except Exception:
            logger.warning(
                "Failed to fetch PMC full text for %s", pmc_id, exc_info=True,
            )
            return None

    @staticmethod
    def _parse_article(elem: ET.Element) -> dict[str, Any]:
        """Parse a ``<PubmedArticle>`` XML element into a structured dict.

        Extracted fields: pmid, title, authors, journal, pub_date, doi,
        abstract, mesh_terms, keywords.
        """
        medline = elem.find("MedlineCitation")
        article_data = medline.find("Article") if medline is not None else None

        # -- pmid --
        pmid = _element_text(medline, "PMID") or ""

        # -- title --
        title = _element_text(article_data, "ArticleTitle") or ""

        # -- journal --
        journal = _element_text(article_data, "Journal/Title") or ""

        # -- pub_date --
        pub_date = ""
        if article_data is not None:
            ji = article_data.find("Journal/JournalIssue")
            if ji is not None:
                pd = ji.find("PubDate")
                if pd is not None:
                    parts = []
                    for tag in ("Year", "Month", "Day"):
                        t = pd.findtext(tag)
                        if t:
                            parts.append(t)
                    pub_date = " ".join(parts)

        # -- authors --
        authors: list[dict[str, str]] = []
        if article_data is not None:
            author_list = article_data.find("AuthorList")
            if author_list is not None:
                for author in author_list.findall("Author"):
                    last = author.findtext("LastName") or ""
                    first = author.findtext("ForeName") or ""
                    initials = author.findtext("Initials") or ""
                    if last or first:
                        authors.append(
                            {
                                "lastname": last,
                                "firstname": first,
                                "initials": initials,
                            }
                        )

        # -- doi --
        doi = _find_doi(elem, article_data)

        # -- abstract --
        abstract_parts: list[str] = []
        if article_data is not None:
            abstract = article_data.find("Abstract")
            if abstract is not None:
                for at in abstract.findall("AbstractText"):
                    label = at.get("Label", "")
                    text = at.text or ""
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)

        # -- mesh_terms --
        mesh_terms: list[str] = []
        if medline is not None:
            mesh_list = medline.find("MeshHeadingList")
            if mesh_list is not None:
                for mh in mesh_list.findall("MeshHeading"):
                    desc = mh.find("DescriptorName")
                    if desc is not None and desc.text:
                        mesh_terms.append(desc.text)

        # -- keywords --
        keywords: list[str] = []
        if medline is not None:
            for kw_list in medline.findall("KeywordList"):
                for kw in kw_list.findall("Keyword"):
                    if kw.text:
                        keywords.append(kw.text)

        # -- pmc_id --
        pmc_id = ""
        pubmed_data = elem.find("PubmedData")
        if pubmed_data is not None:
            id_list = pubmed_data.find("ArticleIdList")
            if id_list is not None:
                for aid in id_list.findall("ArticleId"):
                    if aid.get("IdType") == "pmc":
                        pmc_id = aid.text or ""
                        break

        return {
            "pmid": pmid,
            "title": title,
            "authors": authors,
            "journal": journal,
            "pub_date": pub_date,
            "doi": doi,
            "abstract": "\n".join(abstract_parts),
            "mesh_terms": mesh_terms,
            "keywords": keywords,
            "pmc_id": pmc_id,
        }

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
        pmid = article.get("pmid", "")
        return Item(
            id=pmid or str(uuid.uuid4()),
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url=(
                f"{BASE_URL}efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
                if pmid
                else ""
            ),
            title=article.get("title", ""),
            content=article.get("abstract", ""),
            content_type="text",
            # Issue #169: collected_at must be the COLLECTION time (full ISO
            # date), never the article's pub_date — PubMed often only provides
            # a bare year ("2026") which broke date-range KB queries.  The
            # publication date stays in raw_data["pub_date"].
            collected_at=datetime.now(timezone.utc).isoformat(),
            domain="medical-research",
            topic_tags=list(article.get("keywords", [])),
            raw_data={
                "pmid": pmid,
                "pmc_id": article.get("pmc_id", ""),
                "authors": article.get("authors", []),
                "journal": article.get("journal", ""),
                "pub_date": article.get("pub_date", ""),
                "doi": article.get("doi", ""),
                "mesh_terms": article.get("mesh_terms", []),
            },
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _element_text(parent: ET.Element | None, path: str) -> str | None:
    """Return the text content of *path* under *parent*, or ``None``."""
    if parent is None:
        return None
    elem = parent.find(path)
    return elem.text if elem is not None and elem.text else None


def _find_doi(
    elem: ET.Element,
    article_data: ET.Element | None,
) -> str:
    """Extract the DOI from a ``<PubmedArticle>`` element.

    Checks ``ELocationID`` first, then falls back to ``ArticleIdList``.
    """
    # Try ELocationID (preferred)
    if article_data is not None:
        for eloc in article_data.findall("ELocationID"):
            if eloc.get("EIdType") == "doi":
                return eloc.text or ""

    # Fallback to ArticleIdList inside PubmedData
    pubmed_data = elem.find("PubmedData")
    if pubmed_data is not None:
        id_list = pubmed_data.find("ArticleIdList")
        if id_list is not None:
            for aid in id_list.findall("ArticleId"):
                if aid.get("IdType") == "doi":
                    return aid.text or ""

    return ""
