"""SEC EDGAR company filings handler.

Fetches recent SEC filings (8-K / 10-K / 10-Q) for configured tickers
using a two-step process:

1. ``GET https://www.sec.gov/files/company_tickers.json`` → ticker → CIK map
2. ``GET https://data.sec.gov/submissions/CIK##########.json`` → recent filings

The SEC fair-access policy requires a descriptive ``User-Agent`` on EVERY
request and a request rate at or below 10 requests/second — both enforced
here (see :meth:`_headers` and :meth:`_wait_for_rate_limit`).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from autoinfo.collectors.base import BaseHandler
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT: int = 15  # seconds
DEFAULT_LIMIT: int = 10
DEFAULT_RATE_LIMIT: float = 0.1  # seconds between requests (<= 10 req/s)
DEFAULT_USER_AGENT: str = "AutoInfoResearch/1.0 (contact: ops@autoinfo.ai)"
COMPANY_TICKERS_URL: str = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL: str = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL: str = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
)
INTERESTING_FORMS: frozenset[str] = frozenset({"8-K", "10-K", "10-Q"})


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class SecEdgarHandler(BaseHandler):
    """Fetch recent company filings from the SEC EDGAR submissions API.

    Usage::

        handler = SecEdgarHandler(config={
            "tickers": "AAPL,MSFT",
            "rate_limit": 0.1,
        })
        items = handler.fetch(limit=10)

    Config keys (all optional):

    * ``tickers`` — comma/space separated tickers (default ``"AAPL"``)
    * ``forms`` — comma/space separated SEC form allowlist (default
      ``"8-K,10-K,10-Q"`` = :data:`INTERESTING_FORMS`); only filings whose
      form is in this set are returned, e.g. ``"10-K"`` restricts the
      handler to annual reports only
    * ``limit`` — max filings per ticker (default 10)
    * ``rate_limit`` — seconds to wait between requests (default 0.1)
    * ``user_agent`` — descriptive UA for SEC fair access (default
      ``AutoInfoResearch/1.0 (contact: ops@autoinfo.ai)``)
    * ``timeout`` — HTTP timeout in seconds (default 15)
    """

    source_type: str = "sec_edgar"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the handler from a settings dict.

        Args:
            config: The ``settings`` dict of a
                :class:`autoinfo.config.SourceConfig`.
        """
        config = config or {}
        self.source_config: dict[str, Any] = config
        self.source_name: str = str(config.get("source_name") or "SEC EDGAR")
        tickers_raw: str = str(config.get("tickers") or "AAPL")
        self.tickers: list[str] = [
            t.strip().upper()
            for t in tickers_raw.replace(";", ",").split(",")
            if t.strip()
        ]
        self.limit: int = int(config.get("limit") or DEFAULT_LIMIT)
        forms_raw = config.get("forms")
        if forms_raw is None:
            self.forms: frozenset[str] = INTERESTING_FORMS
        elif isinstance(forms_raw, str):
            self.forms = frozenset(
                f.strip().upper()
                for f in forms_raw.replace(";", ",").split(",")
                if f.strip()
            )
        else:
            self.forms = frozenset(
                str(f).strip().upper() for f in forms_raw if str(f).strip()
            )
        rate_limit = config.get("rate_limit")
        self.rate_limit: float = (
            float(rate_limit) if rate_limit is not None else DEFAULT_RATE_LIMIT
        )
        self.timeout: int = int(config.get("timeout") or DEFAULT_TIMEOUT)
        self.user_agent: str = str(
            config.get("user_agent") or DEFAULT_USER_AGENT
        )
        self._cik_map: dict[str, dict[str, Any]] = {}
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # SEC fair-access compliance
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Headers for every SEC request — descriptive UA is mandatory."""
        return {"User-Agent": self.user_agent}

    def _wait_for_rate_limit(self) -> None:
        """Sleep as needed to stay within the configured req/s budget."""
        if self._last_request_time == 0.0:
            self._last_request_time = time.time()
            return

        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # SEC EDGAR API
    # ------------------------------------------------------------------

    def _load_ticker_map(self) -> dict[str, dict[str, Any]]:
        """Fetch the ticker → CIK map, keyed by uppercase ticker."""
        self._wait_for_rate_limit()
        resp = httpx.get(
            COMPANY_TICKERS_URL, headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        result: dict[str, dict[str, Any]] = {}
        for row in data.values():
            ticker: str = str(row.get("ticker") or "").upper()
            if ticker:
                result[ticker] = row
        return result

    def _lookup_cik(self, ticker: str) -> tuple[str, str]:
        """Resolve a ticker to ``(cik, company_name)``, caching the map."""
        if not self._cik_map:
            self._cik_map = self._load_ticker_map()
        entry = self._cik_map.get(ticker.upper())
        if not entry:
            return "", ""
        return str(entry.get("cik_str") or ""), str(entry.get("title") or "")

    def _fetch_filings(
        self, cik: str, company: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch recent 8-K / 10-K / 10-Q filings for a CIK."""
        if limit <= 0:
            return []
        self._wait_for_rate_limit()
        url = SUBMISSIONS_URL.format(cik=int(cik))
        resp = httpx.get(url, headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        recent: dict[str, Any] = (data.get("filings") or {}).get("recent") or {}

        forms: list[Any] = recent.get("form") or []
        accessions: list[Any] = recent.get("accessionNumber") or []
        dates: list[Any] = recent.get("filingDate") or []
        primary_docs: list[Any] = recent.get("primaryDocument") or []
        report_dates: list[Any] = recent.get("reportDate") or []
        n = min(
            len(forms), len(accessions), len(dates), len(primary_docs)
        )

        filings: list[dict[str, Any]] = []
        for i in range(n):
            form: str = str(forms[i])
            if form not in self.forms:
                continue
            accession: str = str(accessions[i])
            accession_clean: str = accession.replace("-", "")
            primary_doc: str = str(primary_docs[i])
            date: str = str(dates[i]) if i < len(dates) else ""
            report_date: str = str(report_dates[i]) if i < len(report_dates) else ""
            filings.append(
                {
                    "form": form,
                    "company": company,
                    "ticker": self._ticker_for_cik(cik),
                    "cik": cik,
                    "date": date,
                    "report_date": report_date,
                    "accession": accession,
                    "primary_document": primary_doc,
                    "title": f"{form} {company} ({date})",
                    "source_url": ARCHIVE_URL.format(
                        cik=cik,
                        accession=accession_clean,
                        primary_doc=primary_doc,
                    ),
                }
            )
            if len(filings) >= limit:
                break
        return filings

    def _ticker_for_cik(self, cik: str) -> str:
        """Reverse-lookup the ticker for a CIK from the cached map."""
        for ticker, row in self._cik_map.items():
            if str(row.get("cik_str")) == cik:
                return ticker
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, query: str = "", limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:  # type: ignore[override]
        """Fetch recent filings for all configured tickers.

        Args:
            query: Ignored (SEC has no query param on submissions).
            limit: Maximum total filings to return (default 10).

        Returns:
            List of filing dicts with ``form``, ``company``, ``date``,
            ``accession`` and ``source_url`` keys.  Returns an empty
            list on error — never raises.
        """
        if limit <= 0:
            return []
        try:
            results: list[dict[str, Any]] = []
            for ticker in self.tickers:
                try:
                    cik, company = self._lookup_cik(ticker)
                    if not cik:
                        logger.warning(
                            "SEC EDGAR: no CIK found for ticker %s", ticker
                        )
                        continue
                    filings = self._fetch_filings(
                        cik, company, limit - len(results)
                    )
                    results.extend(filings)
                except Exception as exc:
                    logger.warning(
                        "SEC EDGAR ticker %s fetch failed: %s", ticker, exc
                    )
                    continue
                if len(results) >= limit:
                    break
            return results[:limit]
        except Exception as exc:
            logger.error("SEC EDGAR fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Conversion to Item
    # ------------------------------------------------------------------

    def to_item(self, payload: dict[str, Any]) -> Item:
        """Convert a filing dict to an :class:`Item` dataclass."""
        form: str = str(payload.get("form") or "")
        company: str = str(payload.get("company") or self.source_name)
        date: str = str(payload.get("date") or "")
        accession: str = str(payload.get("accession") or "")
        accession_clean: str = accession.replace("-", "")
        cik: str = str(payload.get("cik") or "")
        primary_doc: str = str(payload.get("primary_document") or "")

        source_url: str = str(payload.get("source_url") or "")
        if not source_url and cik and accession_clean and primary_doc:
            source_url = ARCHIVE_URL.format(
                cik=cik, accession=accession_clean, primary_doc=primary_doc
            )

        title: str = str(payload.get("title") or "")
        if not title:
            title = f"{form} {company} ({date})".strip()

        excerpt = json.dumps(
            {
                k: payload.get(k)
                for k in (
                    "form",
                    "company",
                    "ticker",
                    "date",
                    "report_date",
                    "accession",
                    "source_url",
                )
            },
            ensure_ascii=False,
        )

        return Item(
            id=accession_clean,
            source_name=self.source_name,
            source_type="sec_edgar",
            source_url=source_url,
            title=title,
            content=excerpt,
            content_type="text",
            source_platform="sec_edgar",
            collected_at=datetime.now(timezone.utc).isoformat(),
            raw_data=payload,
        )
