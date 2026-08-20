"""Tests for the SEC EDGAR company filings handler.

Verifies the two-step fetch:

1. ``GET https://www.sec.gov/files/company_tickers.json`` → ticker → CIK map
2. ``GET https://data.sec.gov/submissions/CIK##########.json`` → recent filings

Also verifies the SEC fair-access contract: a descriptive ``User-Agent`` on
EVERY request and rate limiting (default 0.1 s between requests = <=10 req/s).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.sec_edgar import (
    DEFAULT_USER_AGENT,
    INTERESTING_FORMS,
    SecEdgarHandler,
)
from autoinfo.config import SourceConfig


@pytest.fixture
def sec_config() -> SourceConfig:
    """SEC EDGAR source config — matching the config-first handler family."""
    return SourceConfig(
        name="SEC EDGAR",
        type="sec_edgar",
        url="https://www.sec.gov",
        settings={"tickers": "AAPL", "rate_limit": 0.0},
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _fake_response(json_payload: object) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_payload
    resp.raise_for_status.return_value = None
    return resp


def _tickers_payload() -> dict[str, Any]:
    """company_tickers.json: a compact ticker → CIK map."""
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }


def _submissions_payload() -> dict[str, Any]:
    """Submissions JSON: recent filings array with 8-K / 10-K / 10-Q / 4."""
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-25-000001",
                    "0000320193-25-000002",
                    "0000320193-25-000003",
                    "0000320193-25-000004",
                ],
                "filingDate": [
                    "2025-01-15",
                    "2025-01-10",
                    "2024-11-01",
                    "2025-01-05",
                ],
                "reportDate": [
                    "2025-01-10",
                    "2025-01-03",
                    "2024-09-28",
                    "2024-12-31",
                ],
                "form": ["8-K", "10-K", "10-Q", "4"],
                "primaryDocument": [
                    "0000320193-25-000001.htm",
                    "aapl-20250927.htm",
                    "aapl-10q.htm",
                    "ex1.htm",
                ],
                "items": ["2.02", "", "", ""],
                "primaryDocDescription": [
                    "Current report",
                    "Annual report",
                    "Quarterly report",
                    "Form 4",
                ],
            }
        },
    }


def _make_side_effect(
    tickers_payload: object,
    submissions_payload: object,
) -> Any:
    """Side effect routing company_tickers.json vs data.sec.gov/submissions/."""

    def side_effect(url: str, **kwargs: object) -> MagicMock:
        if "company_tickers.json" in url:
            return _fake_response(tickers_payload)
        if "data.sec.gov/submissions/" in url:
            return _fake_response(submissions_payload)
        return _fake_response({})

    return side_effect


def _extract_user_agents(mock_get: MagicMock) -> list[str]:
    """Pull the User-Agent header off every captured request."""
    uas: list[str] = []
    for call in mock_get.call_args_list:
        headers = call.kwargs.get("headers") or {}
        uas.append(headers.get("User-Agent", ""))
    return uas


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSecEdgarHandler:
    def test_handler_attributes(self, sec_config: SourceConfig) -> None:
        handler = SecEdgarHandler(config=sec_config.settings)
        assert handler.source_type == "sec_edgar"
        assert handler.tickers == ["AAPL"]
        assert handler.rate_limit == 0.0

    def test_defaults_when_config_empty(self) -> None:
        handler = SecEdgarHandler()
        assert handler.source_type == "sec_edgar"
        assert handler.tickers == ["AAPL"]
        assert handler.rate_limit == 0.1
        assert handler.user_agent == DEFAULT_USER_AGENT

    def test_tickers_parsed_from_csv(self) -> None:
        handler = SecEdgarHandler(config={"tickers": "aapl, msft;tsla"})
        assert handler.tickers == ["AAPL", "MSFT", "TSLA"]

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_fetch_returns_only_interesting_filings(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(config=sec_config.settings)
        raw_items = handler.fetch(limit=10)

        # 4 filings in the fixture, but form "4" must be filtered out.
        assert len(raw_items) == 3
        forms = [r["form"] for r in raw_items]
        assert forms == ["8-K", "10-K", "10-Q"]
        assert all(f in ("8-K", "10-K", "10-Q") for f in forms)

        first = raw_items[0]
        assert first["company"] == "Apple Inc."
        assert first["date"] == "2025-01-15"
        assert first["accession"] == "0000320193-25-000001"
        assert first["source_url"] == (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019325000001/0000320193-25-000001.htm"
        )
        assert first["title"] == "8-K Apple Inc. (2025-01-15)"

    def test_forms_defaults_to_interesting_forms(self) -> None:
        handler = SecEdgarHandler()
        assert handler.forms == INTERESTING_FORMS
        handler = SecEdgarHandler(config={"forms": "10-K, 8-K"})
        assert handler.forms == frozenset({"10-K", "8-K"})

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_forms_allowlist_restricts_filings(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        # Config with a restricted allowlist: only 10-K filings may pass.
        handler = SecEdgarHandler(
            config={"tickers": "AAPL", "forms": "10-K", "rate_limit": 0.0}
        )
        raw_items = handler.fetch(limit=10)

        # The fixture carries 8-K / 10-K / 10-Q / 4 — only 10-K survives.
        assert len(raw_items) == 1
        assert raw_items[0]["form"] == "10-K"
        assert raw_items[0]["title"] == "10-K Apple Inc. (2025-01-10)"

        # Default config keeps all three interesting forms.
        default = SecEdgarHandler(config=sec_config.settings)
        assert default.forms == INTERESTING_FORMS
        default_items = default.fetch(limit=10)
        assert [r["form"] for r in default_items] == ["8-K", "10-K", "10-Q"]

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_user_agent_present_on_every_request(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(config=sec_config.settings)
        handler.fetch(limit=10)

        uas = _extract_user_agents(mock_get)
        assert len(uas) == 2  # one ticker-map request + one submissions request
        assert all(ua == DEFAULT_USER_AGENT for ua in uas), f"missing UA: {uas}"

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_custom_user_agent_used(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(
            config={"tickers": "AAPL", "user_agent": "MyResearch/2.0 (contact: me@example.com)"}
        )
        handler.fetch(limit=10)

        uas = _extract_user_agents(mock_get)
        assert uas, "no requests captured"
        assert all(ua == "MyResearch/2.0 (contact: me@example.com)" for ua in uas)

    @patch("autoinfo.collectors.sec_edgar.time.sleep")
    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_rate_limit_sleep_enforced(
        self, mock_get: MagicMock, mock_sleep: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())
        # Two requests happen back-to-back in the same instant → both must sleep.
        handler = SecEdgarHandler(
            config={"tickers": "AAPL,MSFT", "rate_limit": 0.1}
        )
        handler.fetch(limit=5)

        # 1 ticker-map + 1 AAPL submissions + 1 MSFT submissions = 3 requests.
        assert len(mock_get.call_args_list) == 3
        assert mock_sleep.call_count >= 2, (
            f"expected throttled sleep between requests, got {mock_sleep.call_count}"
        )

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_ticker_map_cached_across_fetches(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(config=sec_config.settings)
        handler.fetch(limit=10)
        handler.fetch(limit=10)

        ticker_calls = [
            c for c in mock_get.call_args_list if "company_tickers.json" in c.args[0]
        ]
        assert len(ticker_calls) == 1, "ticker map must be cached in memory"

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_unknown_ticker_skipped(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(config={"tickers": "NOPE"})
        items = handler.fetch(limit=10)
        assert items == []

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_fetch_403_returns_empty(self, mock_get: MagicMock) -> None:
        def side_effect(url: str, **kwargs: object) -> MagicMock:
            if "company_tickers.json" in url:
                resp = _fake_response({})
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "403 Forbidden",
                    request=httpx.Request("GET", url),
                    response=httpx.Response(403),
                )
                return resp
            return _fake_response({})

        mock_get.side_effect = side_effect
        handler = SecEdgarHandler()
        assert handler.fetch(limit=5) == []

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_fetch_network_error_returns_empty(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = httpx.NetworkError("Connection refused")
        handler = SecEdgarHandler(config=sec_config.settings)
        assert handler.fetch(limit=5) == []

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_fetch_zero_limit_returns_empty(self, mock_get: MagicMock) -> None:
        handler = SecEdgarHandler()
        assert handler.fetch(limit=0) == []
        mock_get.assert_not_called()

    @patch("autoinfo.collectors.sec_edgar.httpx.get")
    def test_fetch_limit_respected(
        self, mock_get: MagicMock, sec_config: SourceConfig
    ) -> None:
        mock_get.side_effect = _make_side_effect(_tickers_payload(), _submissions_payload())

        handler = SecEdgarHandler(config=sec_config.settings)
        items = handler.fetch(limit=2)
        assert len(items) == 2

    def test_to_item_fields(self, sec_config: SourceConfig) -> None:
        handler = SecEdgarHandler(config=sec_config.settings)
        payload = {
            "form": "8-K",
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "cik": "320193",
            "date": "2025-01-15",
            "accession": "0000320193-25-000001",
            "primary_document": "0000320193-25-000001.htm",
            "source_url": (
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019325000001/0000320193-25-000001.htm"
            ),
        }
        item = handler.to_item(payload)

        assert item.id == "000032019325000001"
        assert item.title == "8-K Apple Inc. (2025-01-15)"
        assert item.source_url == payload["source_url"]
        assert item.source_type == "sec_edgar"
        assert item.source_platform == "sec_edgar"
        assert item.source_name == "SEC EDGAR"
        # content is a raw JSON excerpt of the filing
        assert json.loads(item.content)["form"] == "8-K"
        assert item.raw_data == payload

    def test_to_item_builds_source_url_from_parts(self) -> None:
        handler = SecEdgarHandler()
        item = handler.to_item(
            {
                "form": "10-Q",
                "company": "MICROSOFT CORP",
                "cik": "789019",
                "date": "2025-04-20",
                "accession": "0000789019-25-000010",
                "primary_document": "msft-10q.htm",
            }
        )
        assert item.source_url == (
            "https://www.sec.gov/Archives/edgar/data/789019/"
            "000078901925000010/msft-10q.htm"
        )
        assert item.title == "10-Q MICROSOFT CORP (2025-04-20)"
        assert item.id == "000078901925000010"
