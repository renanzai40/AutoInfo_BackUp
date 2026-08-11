"""Tests for the Unpaywall / CORE academic OA collector handler.

Uses ``unittest.mock.patch`` to mock HTTP responses so tests are
deterministic and fast — no real API calls, no real credentials.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.unpaywall import FULLTEXT_CONTENT_CAP, UnpaywallHandler
from autoinfo.models import Item

# ---------------------------------------------------------------------------
# Sample API response data
# ---------------------------------------------------------------------------

SAMPLE_UNPAYWALL_RESPONSE: dict[str, Any] = {
    "results": [
        {
            "response": {
                "doi": "10.1038/nature21369",
                "title": "Microenvironmental regulation of tumour angiogenesis",
                "is_oa": True,
                "oa_status": "gold",
                "published_date": "2017-02-16",
                "journal_name": "Nature",
                "publisher": "Springer Nature",
                "genre": "journal-article",
                "best_oa_location": {
                    "url": "https://www.nature.com/articles/nature21369",
                    "url_for_pdf": "https://www.nature.com/articles/nature21369.pdf",
                    "host_type": "publisher",
                },
                "z_authors": [
                    {"given": "Michele", "family": "De Palma"},
                    {"given": "Luigi", "family": "Naldini"},
                ],
            },
            "score": 0.95,
            "snippet": "<b>Microenvironmental</b> regulation",
        },
        {
            "response": {
                "doi": "10.1126/science.aam8992",
                "title": "A second title about embryo development",
                "is_oa": False,
                "oa_status": "closed",
                "published_date": "2018-05-10",
                "journal_name": "Science",
                "publisher": "AAAS",
                "genre": "journal-article",
                "best_oa_location": None,
                "z_authors": [],
            },
            "score": 0.88,
            "snippet": "embryo development",
        },
    ],
}

SAMPLE_UNPAYWALL_EMPTY: dict[str, Any] = {"results": []}

SAMPLE_UNPAYWALL_SINGLE_OA: dict[str, Any] = {
    "results": [
        {
            "response": {
                "doi": "10.1000/test.2026",
                "title": "Test Paper with OA Fulltext",
                "is_oa": True,
                "oa_status": "green",
                "published_date": "2026-01-15",
                "journal_name": "Test Journal",
                "publisher": "Test Publisher",
                "genre": "journal-article",
                "best_oa_location": {
                    "url": "https://repository.example.com/paper123",
                    "url_for_pdf": "https://repository.example.com/paper123.pdf",
                    "host_type": "repository",
                },
                "z_authors": [
                    {"given": "John", "family": "Smith"},
                    {"given": "Jane", "family": "Doe"},
                ],
            },
            "score": 1.0,
        }
    ]
}

SAMPLE_UNPAYWALL_NON_OA: dict[str, Any] = {
    "results": [
        {
            "response": {
                "doi": "10.9999/nonoa.2026",
                "title": "Paywalled Paper",
                "is_oa": False,
                "oa_status": "closed",
                "published_date": "2025-12-01",
                "journal_name": "Paywalled Journal",
                "publisher": "Paywalled Publisher",
                "genre": "journal-article",
                "best_oa_location": None,
                "z_authors": [],
            },
            "score": 0.5,
        }
    ]
}

SAMPLE_CORE_RESPONSE: dict[str, Any] = {
    "results": [
        {
            "id": "C123456",
            "doi": "10.1038/nature21369",
            "title": "Microenvironmental regulation of tumour angiogenesis",
            "abstract": "Tumour angiogenesis is regulated by the microenvironment.",
            "publishedDate": "2017-02-16",
            "yearPublished": 2017,
            "journal": "Nature",
            "publisher": "Springer Nature",
            "authors": ["Michele De Palma", "Luigi Naldini"],
            "downloadUrl": "https://core.ac.uk/download/123456.pdf",
            "fullText": "https://core.ac.uk/reader/123456",
        },
        {
            "id": "C654321",
            "doi": "10.1126/science.aam8992",
            "title": "A second title about embryo development",
            "abstract": "",
            "publishedDate": "",
            "yearPublished": 2018,
            "journal": "Science",
            "publisher": "AAAS",
            "authors": [],
            "downloadUrl": "",
            "fullText": "",
        },
    ]
}

SAMPLE_CORE_EMPTY: dict[str, Any] = {"results": []}


# ---------------------------------------------------------------------------
# Tests: handler existence and construction
# ---------------------------------------------------------------------------


class TestUnpaywallHandlerExists:
    """Verify the handler class is importable and constructable."""

    def test_handler_is_importable(self) -> None:
        """UnpaywallHandler should be accessible from unpaywall module."""
        assert UnpaywallHandler is not None

    def test_creates_with_default_config(self) -> None:
        """Handler instantiates with an empty config dict."""
        handler = UnpaywallHandler({})
        assert handler.source_type == "unpaywall"
        assert handler.config == {}
        assert handler.provider == "unpaywall"
        assert handler.max_rps == 1.0

    def test_creates_with_full_config(self) -> None:
        """Handler picks up query, provider, and rate limit."""
        config = {
            "query": "CRISPR",
            "provider": "core",
            "is_oa": True,
            "max_rps": 5,
        }
        handler = UnpaywallHandler(config)
        assert handler.config == config
        assert handler.provider == "core"
        assert handler.max_rps == 5

    def test_source_type_is_unpaywall(self) -> None:
        """The source_type class attribute must be 'unpaywall'."""
        assert UnpaywallHandler.source_type == "unpaywall"

    def test_requires_key_returns_true(self) -> None:
        """Credentials (email or API key) are always required."""
        assert UnpaywallHandler.requires_key() is True


# ---------------------------------------------------------------------------
# Tests: fetch returns a list
# ---------------------------------------------------------------------------


class TestUnpaywallFetch:
    """Tests for the fetch method (Unpaywall provider)."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_returns_list(self, mock_get: MagicMock) -> None:
        """fetch() should return a list of dicts."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="tumour angiogenesis", limit=10)

        assert isinstance(items, list)
        assert len(items) == 2

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_each_item_is_dict(self, mock_get: MagicMock) -> None:
        """Each returned item must be a dict."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="tumour angiogenesis", limit=10)

        for item in items:
            assert isinstance(item, dict)

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_respects_limit(self, mock_get: MagicMock) -> None:
        """fetch should respect the limit argument."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="tumour angiogenesis", limit=1)

        assert len(items) == 1

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_uses_correct_endpoint(self, mock_get: MagicMock) -> None:
        """fetch should call the Unpaywall /v2/search endpoint."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"query": "embryo development"})
        handler.fetch(limit=5)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "api.unpaywall.org/v2/search" in url
        assert "embryo%20development" in url or "embryo+development" in url
        assert "tester%40example.com" in url or "tester@example.com" in url

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_uses_config_query_fallback(self, mock_get: MagicMock) -> None:
        """fetch() should fall back to config['query'] when no query arg."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"query": "CRISPR"})
        items = handler.fetch(limit=5)

        assert len(items) == 2
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "CRISPR" in url

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_empty_query_returns_empty(self, mock_get: MagicMock) -> None:
        """Empty query (no arg and no config) should return [] without HTTP."""
        handler = UnpaywallHandler({})
        items = handler.fetch(limit=5)

        assert items == []
        mock_get.assert_not_called()

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_limit_zero_returns_empty(self, mock_get: MagicMock) -> None:
        """A limit of 0 should result in an empty list."""
        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=0)

        assert items == []
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: empty response handling
# ---------------------------------------------------------------------------


class TestUnpaywallFetchEmpty:
    """Tests for empty or no-result responses."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_handles_empty_results(self, mock_get: MagicMock) -> None:
        """An empty results list should return an empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_EMPTY
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="NONEXISTENTQUERY999999", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_handles_missing_results_key(self, mock_get: MagicMock) -> None:
        """Response without a 'results' key should return empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {"message": "no data"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_skips_non_dict_result(self, mock_get: MagicMock) -> None:
        """A result entry without a 'response' dict should be skipped."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {
            "results": [{"score": 0.5, "response": None}]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: missing-credential graceful degradation
# ---------------------------------------------------------------------------


class TestUnpaywallGracefulDegradation:
    """Tests for missing email / API key behaviour."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    def test_fetch_missing_email_returns_empty(self, mock_get: MagicMock) -> None:
        """Without AUTOINFO_UNPAYWALL_EMAIL, fetch returns [] and no HTTP."""
        # Ensure the env var is absent
        os.environ.pop("AUTOINFO_UNPAYWALL_EMAIL", None)

        handler = UnpaywallHandler({})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []
        mock_get.assert_not_called()

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    def test_fetch_missing_core_key_returns_empty(self, mock_get: MagicMock) -> None:
        """Without AUTOINFO_CORE_API_KEY, CORE fetch returns [] and no HTTP."""
        os.environ.pop("AUTOINFO_CORE_API_KEY", None)

        handler = UnpaywallHandler({"provider": "core"})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: error handling (graceful degradation)
# ---------------------------------------------------------------------------


class TestUnpaywallErrorHandling:
    """Tests for HTTP errors, non-JSON responses, and network failures."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_http_error_returns_empty(self, mock_get: MagicMock) -> None:
        """HTTP errors should log + return empty list (graceful degradation)."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_network_error_returns_empty(self, mock_get: MagicMock) -> None:
        """Network errors should return empty list."""
        mock_get.side_effect = httpx.NetworkError("Connection refused")

        handler = UnpaywallHandler({})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_timeout_returns_empty(self, mock_get: MagicMock) -> None:
        """Timeout errors should return empty list gracefully."""
        mock_get.side_effect = httpx.TimeoutException(
            "Request timed out",
            request=MagicMock(),
        )

        handler = UnpaywallHandler({})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_non_json_response_handled_gracefully(
        self, mock_get: MagicMock
    ) -> None:
        """If API returns non-JSON, handle gracefully with empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = ValueError(
            "Expecting value: line 1 column 1"
        )
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: field mapping
# ---------------------------------------------------------------------------


class TestUnpaywallFieldMapping:
    """Tests for mapping Unpaywall JSON fields to standardised dicts."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_id(self, mock_get: MagicMock) -> None:
        """id should come from the DOI."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["id"] == "10.1000/test.2026"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_title(self, mock_get: MagicMock) -> None:
        """title should come from the API title field."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["title"] == "Test Paper with OA Fulltext"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_authors(self, mock_get: MagicMock) -> None:
        """Authors should be a list of combined given+family names."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        authors = items[0]["authors"]
        assert isinstance(authors, list)
        assert len(authors) == 2
        assert "John Smith" in authors
        assert "Jane Doe" in authors

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_is_oa_true(self, mock_get: MagicMock) -> None:
        """is_oa should be True for OA articles."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["is_oa"] is True
        assert items[0]["oa_status"] == "green"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_oa_url_source_url(self, mock_get: MagicMock) -> None:
        """source_url should be the OA full-text URL when available."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["oa_url"] == "https://repository.example.com/paper123"
        assert items[0]["oa_url_pdf"] == "https://repository.example.com/paper123.pdf"
        assert items[0]["source_url"] == "https://repository.example.com/paper123"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_non_oa_falls_back_to_doi_page(
        self, mock_get: MagicMock
    ) -> None:
        """Non-OA articles should fall back to the DOI landing page."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_NON_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["is_oa"] is False
        assert items[0]["oa_url"] == ""
        assert items[0]["source_url"] == "https://doi.org/10.9999/nonoa.2026"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_field_mapping_all_expected_fields_present(
        self, mock_get: MagicMock
    ) -> None:
        """Every returned item must have all expected keys."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_SINGLE_OA
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        expected_fields = {
            "id", "title", "content", "authors", "published_date",
            "journal", "publisher", "is_oa", "oa_status",
            "oa_url", "oa_url_pdf", "source_url", "genre",
        }
        for item in items:
            for field in expected_fields:
                assert field in item, f"Item missing field: {field}"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fetch_is_oa_filter_in_url(self, mock_get: MagicMock) -> None:
        """is_oa config should be passed through to the API query."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"query": "CRISPR", "is_oa": True})
        handler.fetch(limit=5)

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "is_oa=true" in url


# ---------------------------------------------------------------------------
# Tests: CORE provider
# ---------------------------------------------------------------------------


class TestCoreProvider:
    """Tests for the CORE API provider backend."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_fetch_returns_list(self, mock_get: MagicMock) -> None:
        """CORE fetch should return a list of dicts."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CORE_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        items = handler.fetch(query="tumour angiogenesis", limit=10)

        assert isinstance(items, list)
        assert len(items) == 2

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_fetch_uses_correct_endpoint(self, mock_get: MagicMock) -> None:
        """CORE fetch should call api.core.ac.uk/v3/search/works."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CORE_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        handler.fetch(query="embryo development", limit=5)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else ""
        assert "api.core.ac.uk/v3/search/works" in url
        assert "embryo%20development" in url or "embryo+development" in url

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_fetch_sends_auth_header(self, mock_get: MagicMock) -> None:
        """CORE fetch should send an Authorization Bearer header."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CORE_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        handler.fetch(query="CRISPR", limit=5)

        call_args = mock_get.call_args
        kwargs = call_args[1] if len(call_args) > 1 else {}
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer core-test-key-123"

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_field_mapping(self, mock_get: MagicMock) -> None:
        """CORE work objects should map to standardised fields."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CORE_RESPONSE
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["id"] == "10.1038/nature21369"
        assert items[0]["title"] == "Microenvironmental regulation of tumour angiogenesis"
        assert items[0]["content"] == (
            "Tumour angiogenesis is regulated by the microenvironment."
        )
        assert items[0]["is_oa"] is True
        assert items[0]["source_url"] == "https://core.ac.uk/download/123456.pdf"
        assert items[0]["authors"] == ["Michele De Palma", "Luigi Naldini"]

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_empty_results(self, mock_get: MagicMock) -> None:
        """CORE empty results should return empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_CORE_EMPTY
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        items = handler.fetch(query="NONEXISTENT", limit=10)

        assert items == []

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_CORE_API_KEY": "core-test-key-123"})
    def test_core_http_error_returns_empty(self, mock_get: MagicMock) -> None:
        """CORE HTTP errors should return empty list."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"provider": "core"})
        items = handler.fetch(query="CRISPR", limit=10)

        assert items == []


# ---------------------------------------------------------------------------
# Tests: rate limiting
# ---------------------------------------------------------------------------


class TestUnpaywallRateLimit:
    """Tests for rate limiter behaviour."""

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_rate_limit_first_call_instant(self, mock_get: MagicMock) -> None:
        """First call should not block (no previous request recorded)."""
        import time

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_EMPTY
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({})
        t0 = time.time()
        handler.fetch(query="anything", limit=5)
        elapsed = time.time() - t0

        assert elapsed < 0.3  # should be near-instant

    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_rate_limit_enforces_min_interval(self, mock_get: MagicMock) -> None:
        """Back-to-back calls should be spaced by at least 1/max_rps."""
        import time

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = SAMPLE_UNPAYWALL_EMPTY
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        handler = UnpaywallHandler({"max_rps": 5})
        assert handler.max_rps == 5

        handler.fetch(query="anything", limit=5)  # warms _last_request_time
        t0 = time.time()
        handler.fetch(query="anything", limit=5)  # should wait
        elapsed = time.time() - t0

        min_interval = 1.0 / handler.max_rps  # 0.2 s
        assert elapsed >= min_interval * 0.9  # 10 % tolerance


# ---------------------------------------------------------------------------
# Tests: to_item conversion
# ---------------------------------------------------------------------------


class TestUnpaywallToItem:
    """Tests for ``UnpaywallHandler.to_item()``."""

    def test_to_item_complete(self) -> None:
        """A fully populated article dict converts to a correct Item."""
        from autoinfo.models import Item

        handler = UnpaywallHandler({})
        article = {
            "id": "10.1000/test.2026",
            "title": "Test Article Title",
            "content": "Test Article Title",
            "authors": ["John Smith", "Jane Doe"],
            "published_date": "2026-01-15",
            "journal": "Test Journal",
            "publisher": "Test Publisher",
            "is_oa": True,
            "oa_status": "green",
            "oa_url": "https://repository.example.com/paper123",
            "oa_url_pdf": "https://repository.example.com/paper123.pdf",
            "source_url": "https://repository.example.com/paper123",
            "genre": "journal-article",
        }

        item = handler.to_item(article)

        assert isinstance(item, Item)
        assert item.id == "10.1000/test.2026"
        assert item.source_name == "unpaywall"
        assert item.source_type == "unpaywall"
        assert item.source_platform == "unpaywall"
        assert item.title == "Test Article Title"
        assert item.content == "Test Article Title"
        assert item.content_type == "text"
        assert item.source_url == "https://repository.example.com/paper123"
        assert item.collected_at == "2026-01-15"
        assert item.raw_data["doi"] == "10.1000/test.2026"
        assert item.raw_data["authors"] == ["John Smith", "Jane Doe"]
        assert item.raw_data["is_oa"] is True
        assert item.raw_data["oa_url"] == "https://repository.example.com/paper123"
        assert item.raw_data["oa_url_pdf"] == (
            "https://repository.example.com/paper123.pdf"
        )
        assert item.raw_data["provider"] == "unpaywall"

    def test_to_item_empty_id_uses_uuid(self) -> None:
        """When id is empty, a UUID should be generated as the item id."""

        handler = UnpaywallHandler({})
        article = {
            "id": "",
            "title": "No DOI",
            "content": "",
            "authors": [],
            "published_date": "",
            "journal": "",
            "publisher": "",
            "is_oa": False,
            "oa_status": "",
            "oa_url": "",
            "oa_url_pdf": "",
            "source_url": "",
            "genre": "",
        }

        item = handler.to_item(article)

        assert item.id
        assert item.id != ""
        assert "-" in item.id  # UUID contains hyphens

    def test_to_item_non_oa_source_url_doi_page(self) -> None:
        """Non-OA items should carry the DOI page as source_url."""
        handler = UnpaywallHandler({})
        article = {
            "id": "10.9999/nonoa.2026",
            "title": "Paywalled",
            "content": "Paywalled",
            "authors": [],
            "published_date": "",
            "journal": "",
            "publisher": "",
            "is_oa": False,
            "oa_status": "closed",
            "oa_url": "",
            "oa_url_pdf": "",
            "source_url": "https://doi.org/10.9999/nonoa.2026",
            "genre": "",
        }

        item = handler.to_item(article)

        assert item.source_url == "https://doi.org/10.9999/nonoa.2026"
        assert item.raw_data["is_oa"] is False


# ---------------------------------------------------------------------------
# Tests: fetch_depth == "fulltext" OA content extraction
# ---------------------------------------------------------------------------


class TestUnpaywallFulltextFetchDepth:
    """Tests for the ``fetch_depth == "fulltext"`` content-depth mode.

    In fulltext mode the handler reuses the web.py trafilatura path
    (``WebHandler.fetch``) to extract OA full text into ``content``;
    any failure must degrade gracefully to the mapped content (title).
    """

    LONG_EXTRACTED_TEXT: str = (
        "This is the extracted full text of the open access article. "
        "It contains several sentences of substantive scholarly "
        "discussion that go far beyond the article title."
    ) * 5

    @staticmethod
    def _mock_unpaywall_response(
        payload: dict[str, Any], mock_get: MagicMock
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

    @staticmethod
    def _extracted_item(text: str) -> Item:
        return Item(
            id="web-item",
            source_name="web",
            source_type="web",
            source_url="https://repository.example.com/paper123",
            title="",
            content=text,
        )

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_extracts_oa_content(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """fetch_depth=fulltext with oa_url yields content length >> title."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        mock_web_fetch.return_value = [
            self._extracted_item(self.LONG_EXTRACTED_TEXT)
        ]

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="anything", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == self.LONG_EXTRACTED_TEXT
        assert len(items[0]["content"]) > len(items[0]["title"]) * 5
        # The web.py path must be called with the OA URL.
        mock_web_fetch.assert_called_once_with(
            "https://repository.example.com/paper123"
        )

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_empty_extraction_keeps_title(
        self,
        mock_get: MagicMock,
        mock_web_fetch: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Empty extraction should keep the title and log a warning."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        mock_web_fetch.return_value = []

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        with caplog.at_level(
            logging.WARNING, logger="autoinfo.collectors.unpaywall"
        ):
            items = handler.fetch(query="anything", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "Test Paper with OA Fulltext"
        assert any(
            r.levelno == logging.WARNING and "fulltext" in r.message
            for r in caplog.records
        )

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_extraction_raise_keeps_title(
        self,
        mock_get: MagicMock,
        mock_web_fetch: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A raising extraction should keep the title and log a warning."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        mock_web_fetch.side_effect = RuntimeError("extraction boom")

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        with caplog.at_level(
            logging.WARNING, logger="autoinfo.collectors.unpaywall"
        ):
            items = handler.fetch(query="anything", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "Test Paper with OA Fulltext"
        assert any(
            r.levelno == logging.WARNING and "fulltext" in r.message
            for r in caplog.records
        )

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_no_oa_url_unchanged(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """fetch_depth=fulltext without an OA URL leaves content unchanged."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_NON_OA, mock_get)

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="anything", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "Paywalled Paper"
        mock_web_fetch.assert_not_called()

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_default_fetch_depth_unchanged(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """Without fetch_depth=fulltext, content stays the title."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)

        handler = UnpaywallHandler({})
        items = handler.fetch(query="anything", limit=10)

        assert len(items) == 1
        assert items[0]["content"] == "Test Paper with OA Fulltext"
        mock_web_fetch.assert_not_called()

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_truncates_to_cap(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """Extracted content should be truncated to the 8000-char cap."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        mock_web_fetch.return_value = [self._extracted_item("x" * 20000)]

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["content"] == "x" * FULLTEXT_CONTENT_CAP
        assert len(items[0]["content"]) == FULLTEXT_CONTENT_CAP

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_content_cap_configurable(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """The content cap should be overridable via config."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        mock_web_fetch.return_value = [self._extracted_item("y" * 5000)]

        handler = UnpaywallHandler(
            {"fetch_depth": "fulltext", "content_cap": 100}
        )
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["content"] == "y" * 100

    @patch("autoinfo.collectors.unpaywall.WebHandler.fetch")
    @patch("autoinfo.collectors.unpaywall.httpx.get")
    @patch.dict(os.environ, {"AUTOINFO_UNPAYWALL_EMAIL": "tester@example.com"})
    def test_fulltext_mode_falls_back_to_oa_url_pdf(
        self, mock_get: MagicMock, mock_web_fetch: MagicMock
    ) -> None:
        """When oa_url extraction is empty, oa_url_pdf should be tried."""
        self._mock_unpaywall_response(SAMPLE_UNPAYWALL_SINGLE_OA, mock_get)
        # First attempt (oa_url) empty, second attempt (oa_url_pdf) yields text.
        mock_web_fetch.side_effect = [
            [],
            [self._extracted_item(self.LONG_EXTRACTED_TEXT)],
        ]

        handler = UnpaywallHandler({"fetch_depth": "fulltext"})
        items = handler.fetch(query="anything", limit=10)

        assert items[0]["content"] == self.LONG_EXTRACTED_TEXT
        assert mock_web_fetch.call_count == 2
        assert mock_web_fetch.call_args_list[0].args[0] == (
            "https://repository.example.com/paper123"
        )
        assert mock_web_fetch.call_args_list[1].args[0] == (
            "https://repository.example.com/paper123.pdf"
        )
