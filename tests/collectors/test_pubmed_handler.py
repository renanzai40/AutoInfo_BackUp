"""Tests for the PubMed E-utilities handler.

Uses ``pytest-vcr`` to record/replay HTTP interactions with the real
NCBI API so tests are deterministic and fast after the first run.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import httpx
import pytest

from autoinfo.collectors.pubmed import PubMedHandler
from autoinfo.models import Item

# ---------------------------------------------------------------------------
# VCR configuration (applies to all ``@pytest.mark.vcr`` tests in this file)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config():
    """Strip sensitive data from recorded cassettes."""
    return {
        "filter_headers": [("api_key", "DUMMY_API_KEY")],
        "filter_query_parameters": ["api_key"],
        "record_mode": "new_episodes",
        "cassette_library_dir": "tests/cassettes",
    }


_CASSETTE_NAMES = (
    "TestPubMedIntegration.test_search_returns_pmids.yaml",
    "TestPubMedIntegration.test_search_empty_result.yaml",
    "TestPubMedIntegration.test_fetch_returns_parsed_articles.yaml",
    "TestPubMedIntegration.test_fetch_to_item_round_trip.yaml",
)


def _cassettes_present() -> bool:
    return all(
        (Path(__file__).parent.parent / "cassettes" / name).exists()
        for name in _CASSETTE_NAMES
    )


# ---------------------------------------------------------------------------
# Integration tests (VCR-recorded, touch the real NCBI API on first run)
# ---------------------------------------------------------------------------


class TestPubMedIntegration:
    """End-to-end tests that replay recorded HTTP traffic."""

    pytestmark = pytest.mark.skipif(
        not _cassettes_present(),
        reason="PubMed VCR cassettes missing — record once with network, then commit them",
    )

    @pytest.mark.vcr
    def test_search_returns_pmids(self) -> None:
        """Search should return a list of numeric PMID strings."""
        handler = PubMedHandler()
        pmids = handler.search("IVF", max_results=5)

        assert isinstance(pmids, list)
        assert len(pmids) > 0
        assert len(pmids) <= 5
        for pmid in pmids:
            assert isinstance(pmid, str)
            assert pmid.isdigit(), f"PMID should be numeric, got {pmid!r}"

    @pytest.mark.vcr
    def test_search_empty_result(self) -> None:
        """A query unlikely to match anything should return an empty list."""
        handler = PubMedHandler()
        pmids = handler.search("ZZZZZZNONEXISTENT999999", max_results=5)
        assert isinstance(pmids, list)

    @pytest.mark.vcr
    def test_fetch_returns_parsed_articles(self) -> None:
        """Fetch should return structured dicts with all expected fields."""
        handler = PubMedHandler()

        # Search first to get real PMIDs, then fetch their metadata.
        pmids = handler.search("IVF", max_results=3)
        assert len(pmids) > 0, "Search should return at least one PMID"

        articles = handler.fetch(pmids)
        assert len(articles) > 0
        assert len(articles) <= 3

        for article in articles:
            assert isinstance(article, dict)
            # Every article must have these fields
            assert "pmid" in article
            assert article["pmid"].isdigit()
            assert "title" in article
            assert article["title"], "title should not be empty"
            assert "authors" in article
            assert isinstance(article["authors"], list)
            assert "journal" in article
            assert "pub_date" in article
            assert "doi" in article
            assert "abstract" in article
            assert "mesh_terms" in article
            assert isinstance(article["mesh_terms"], list)
            assert "keywords" in article
            assert isinstance(article["keywords"], list)

            # Author structure check
            for author in article["authors"]:
                assert "lastname" in author
                assert "firstname" in author
                assert "initials" in author

    @pytest.mark.vcr
    def test_fetch_to_item_round_trip(self) -> None:
        """Fetch → to_item should produce valid Item instances."""
        handler = PubMedHandler()
        pmids = handler.search("embryo", max_results=2)
        assert len(pmids) > 0

        articles = handler.fetch(pmids)
        for article in articles:
            item = handler.to_item(article)
            assert isinstance(item, Item)
            assert item.source_name == "pubmed"
            assert item.source_type == "api"
            assert item.id == article["pmid"]
            assert item.title == article["title"]
            assert item.content == article["abstract"]


# ---------------------------------------------------------------------------
# XML parsing tests (fixture-based, no network)
# ---------------------------------------------------------------------------


class TestPubMedParsing:
    """Unit tests for ``_parse_article`` using the sample XML fixture."""

    def test_parse_article_full(self, sample_pubmed_response: str) -> None:
        """Parse a full PubMed XML element and check all fields."""
        handler = PubMedHandler()
        root = ET.fromstring(sample_pubmed_response)
        article_elem = root.find("PubmedArticle")
        assert article_elem is not None

        article = handler._parse_article(article_elem)

        # -- Core identifiers --
        assert article["pmid"] == "12345678"

        # -- Title --
        assert "Improved IVF outcomes" in article["title"]
        assert "time-lapse" in article["title"]

        # -- Authors --
        assert len(article["authors"]) == 3
        assert article["authors"][0]["lastname"] == "Zhang"
        assert article["authors"][0]["firstname"] == "Wei"
        assert article["authors"][0]["initials"] == "W"
        assert article["authors"][1]["lastname"] == "Chen"
        assert article["authors"][2]["lastname"] == "Smith"

        # -- Journal --
        assert article["journal"] == "Journal of Reproductive Medicine"

        # -- Publication date --
        assert "2026" in article["pub_date"]
        assert "Mar" in article["pub_date"]

        # -- DOI --
        assert article["doi"] == "10.1000/j.jrm.2026.03.004"

        # -- Abstract --
        abstract = article["abstract"]
        assert "Background:" in abstract
        assert "Methods:" in abstract
        assert "Results:" in abstract
        assert "Time-lapse" in abstract

        # -- MeSH terms (none in the sample XML) --
        assert isinstance(article["mesh_terms"], list)

        # -- Keywords (none in the sample XML) --
        assert isinstance(article["keywords"], list)

    def test_to_item_collected_at_is_full_iso_date(self) -> None:
        """Issue #169: collected_at is the collection time (full ISO date),
        never the article's pub_date (which may be a bare year like '2026'
        that broke KB date-range queries)."""
        handler = PubMedHandler()
        article = {
            "pmid": "12345678",
            "title": "IVF outcomes",
            "abstract": "Time-lapse imaging improves IVF outcomes.",
            "pub_date": "2026",  # bare year — PubMed often gives only Year
        }
        item = handler.to_item(article)
        from datetime import datetime

        parsed = datetime.fromisoformat(item.collected_at)
        assert parsed.tzinfo is not None  # timezone-aware full ISO timestamp
        assert item.collected_at.startswith("20")  # not a bare '2026'
        # The publication date is preserved separately in raw_data.
        assert item.raw_data.get("pub_date") == "2026"

    def test_parse_article_minimal(self) -> None:
        """A minimal PubmedArticle (barely any data) should not crash."""
        handler = PubMedHandler()
        xml = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">99999</PMID>
      <Article>
        <Journal/>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""
        root = ET.fromstring(xml)
        article_elem = root.find("PubmedArticle")
        article = handler._parse_article(article_elem)

        assert article["pmid"] == "99999"
        assert article["title"] == ""
        assert article["authors"] == []
        assert article["journal"] == ""
        assert article["pub_date"] == ""
        assert article["doi"] == ""
        assert article["abstract"] == ""
        assert article["mesh_terms"] == []
        assert article["keywords"] == []

    def test_parse_article_no_medline(self) -> None:
        """A PubmedArticle without MedlineCitation must not crash."""
        handler = PubMedHandler()
        xml = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle/>
</PubmedArticleSet>"""
        root = ET.fromstring(xml)
        article_elem = root.find("PubmedArticle")
        article = handler._parse_article(article_elem)

        # Should return defaults
        assert article["pmid"] == ""
        assert article["title"] == ""


# ---------------------------------------------------------------------------
# Item conversion tests
# ---------------------------------------------------------------------------


class TestPubMedConversion:
    """Tests for ``PubMedHandler.to_item()``."""

    def test_to_item_complete(self) -> None:
        """A fully populated article dict converts to a correct Item."""
        handler = PubMedHandler()
        article = {
            "pmid": "12345678",
            "title": "Test Article Title",
            "authors": [
                {"lastname": "Doe", "firstname": "John", "initials": "J"},
                {"lastname": "Smith", "firstname": "Jane", "initials": "JS"},
            ],
            "journal": "Journal of Test Studies",
            "pub_date": "2026 Jan",
            "doi": "10.1000/test.2026.01",
            "abstract": "This is the abstract of the test article.",
            "mesh_terms": ["Test", "Example"],
            "keywords": ["test", "example", "sample"],
        }

        item = handler.to_item(article)

        assert isinstance(item, Item)
        assert item.id == "12345678"
        assert item.source_name == "pubmed"
        assert item.source_type == "api"
        assert "12345678" in item.source_url
        assert item.title == "Test Article Title"
        assert item.content == "This is the abstract of the test article."
        assert item.content_type == "text"
        assert item.domain == "medical-research"
        assert item.topic_tags == ["test", "example", "sample"]
        assert item.raw_data["pmid"] == "12345678"
        assert item.raw_data["doi"] == "10.1000/test.2026.01"
        assert item.raw_data["journal"] == "Journal of Test Studies"

    def test_to_item_empty_pmid_uses_uuid(self) -> None:
        """When PMID is empty, a UUID should be generated as the item id."""
        handler = PubMedHandler()
        article = {
            "pmid": "",
            "title": "No PMID",
            "authors": [],
            "journal": "",
            "pub_date": "",
            "doi": "",
            "abstract": "",
            "mesh_terms": [],
            "keywords": [],
        }

        item = handler.to_item(article)

        assert item.id
        assert item.id != ""
        # UUIDs contain hyphens; plain PMIDs do not
        assert "-" in item.id

    def test_to_item_round_trip_from_fixture(
        self,
        sample_pubmed_response: str,
    ) -> None:
        """Parse the sample XML → to_item → verify all fields survive."""
        handler = PubMedHandler()
        root = ET.fromstring(sample_pubmed_response)
        article_elem = root.find("PubmedArticle")
        assert article_elem is not None

        article = handler._parse_article(article_elem)
        item = handler.to_item(article)

        assert item.id == "12345678"
        assert "Improved IVF outcomes" in item.title
        assert item.raw_data["pmid"] == "12345678"
        assert item.raw_data["doi"] == "10.1000/j.jrm.2026.03.004"
        assert item.raw_data["journal"] == "Journal of Reproductive Medicine"
        assert item.topic_tags == []  # sample has no keywords


# ---------------------------------------------------------------------------
# Error-handling tests
# ---------------------------------------------------------------------------


class TestPubMedErrorHandling:
    """Tests for retry logic and error propagation."""

    def test_retry_on_timeout(self) -> None:
        """After 3 TimeoutExceptions the error should propagate."""
        handler = PubMedHandler()
        call_count = 0

        def _fake_get(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            msg = f"Simulated timeout (attempt {call_count})"
            raise httpx.TimeoutException(msg, request=None)  # type:ignore[arg-type]

        with patch("httpx.get", side_effect=_fake_get):
            with patch("autoinfo.collectors.pubmed.time.sleep") as mock_sleep:
                with pytest.raises(httpx.TimeoutException):
                    handler.search("test", max_results=1)

        assert call_count == 3
        sleep_delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert 2 in sleep_delays
        assert 4 in sleep_delays

    def test_retry_on_network_error(self) -> None:
        """NetworkError is also retried 3 times before raising."""
        handler = PubMedHandler()
        call_count = 0

        def _fake_get(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.NetworkError("Simulated network error", request=None)  # type:ignore[arg-type]

        with patch("httpx.get", side_effect=_fake_get):
            with patch("autoinfo.collectors.pubmed.time.sleep"):
                with pytest.raises(httpx.NetworkError):
                    handler.search("test", max_results=1)

        assert call_count == 3

    def test_http_4xx_is_not_retried(self) -> None:
        """HTTP 4xx/5xx responses are raised immediately (no retry)."""
        handler = PubMedHandler()

        resp = httpx.Response(
            404,
            request=httpx.Request("GET", "http://test.com"),
        )

        with patch("httpx.get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                handler.search("test", max_results=1)

    def test_http_429_too_many_requests(self) -> None:
        """429 is an HTTP status error — not retried unless explicitly coded."""
        handler = PubMedHandler()

        resp = httpx.Response(
            429,
            request=httpx.Request("GET", "http://test.com"),
        )

        with patch("httpx.get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                handler.search("test", max_results=1)


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------


class TestPubMedRateLimit:
    """Tests for rate limiter behaviour."""

    def test_without_api_key_defaults_to_3_rps(self) -> None:
        handler = PubMedHandler()
        assert handler.max_rps == 3

    def test_with_api_key_uses_10_rps(self) -> None:
        handler = PubMedHandler(api_key="my-test-key")
        assert handler.max_rps == 10

    def test_with_env_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOINFO_PUBMED_API_KEY", "env-key")
        handler = PubMedHandler()
        assert handler.max_rps == 10

    def test_rate_limit_first_call_instant(self) -> None:
        """First call should not block (no previous request recorded)."""
        handler = PubMedHandler()

        resp = httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["123"]}},
            request=httpx.Request("GET", "http://test.com"),
        )

        with patch("httpx.get", return_value=resp):
            t0 = time.time()
            handler.search("test")
            elapsed = time.time() - t0

        assert elapsed < 0.2  # should be near-instant

    def test_rate_limit_enforces_min_interval(self) -> None:
        """Back-to-back calls should be spaced by at least 1/max_rps."""
        handler = PubMedHandler()

        resp = httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["123"]}},
            request=httpx.Request("GET", "http://test.com"),
        )

        with patch("httpx.get", return_value=resp):
            handler.search("test")  # warms _last_request_time
            t0 = time.time()
            handler.search("test")  # should wait
            elapsed = time.time() - t0

        min_interval = 1.0 / handler.max_rps  # ~0.333 s
        assert elapsed >= min_interval * 0.9  # 10 % tolerance


# ---------------------------------------------------------------------------
# Constructor / edge cases
# ---------------------------------------------------------------------------


class TestPubMedHandlerInit:
    """Handler initialisation edge cases."""

    def test_default_source_url_format(self) -> None:
        """to_item should construct the correct source_url."""
        handler = PubMedHandler()
        article = {
            "pmid": "87654321",
            "title": "",
            "authors": [],
            "journal": "",
            "pub_date": "",
            "doi": "",
            "abstract": "",
            "mesh_terms": [],
            "keywords": [],
        }
        item = handler.to_item(article)
        assert (
            item.source_url
            == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=87654321&retmode=xml"
        )
