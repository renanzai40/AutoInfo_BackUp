"""Tests requiring real external API access (PubMed, RSS, LLM).

Run with::

    AUTOINFO_RUN_REAL_API_TESTS=1 pytest -m real_api

The LLM test additionally requires ``AUTOINFO_LLM_API_KEY``.

All tests in this module are marked ``real_api`` and are **skipped by default**
in CI or normal test runs.  They require network access and, for the LLM test,
a valid LLM API key.
"""

from __future__ import annotations

import os

import pytest

from autoinfo.models import Item
from tests.conftest import HAVE_LLM_KEY, requires_llm_key

# ---------------------------------------------------------------------------
# All tests in this module skip by default.
# To run them:  AUTOINFO_RUN_REAL_API_TESTS=1 pytest -m real_api
# The LLM test additionally requires AUTOINFO_LLM_API_KEY.
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.real_api,
    pytest.mark.skipif(
        not os.environ.get("AUTOINFO_RUN_REAL_API_TESTS"),
        reason=(
            "Set AUTOINFO_RUN_REAL_API_TESTS=1 to run real API tests "
            "(or provide AUTOINFO_LLM_API_KEY for the LLM test)"
        ),
    ),
]


# ---------------------------------------------------------------------------
# PubMed  —  public NCBI E-utilities (no API key required)
# ---------------------------------------------------------------------------


class TestRealPubMed:
    """Real API test against NCBI PubMed E-utilities.

    Uses the public endpoint which allows up to 3 requests/second
    without an API key.  Skipped automatically unless ``-m real_api``
    is passed.
    """

    def test_real_pubmed_collect(self) -> None:
        """Actually call PubMed ``esearch`` and verify PMIDs are returned."""
        from autoinfo.collectors.pubmed import PubMedHandler

        handler = PubMedHandler()
        pmids = handler.search("CRISPR", max_results=3)

        assert isinstance(pmids, list)
        assert len(pmids) >= 1, "Expected at least one PMID for CRISPR"
        for pmid in pmids:
            assert isinstance(pmid, str), f"PMID should be a string, got {type(pmid)}"
            assert pmid.isdigit(), f"PMID should be numeric, got {pmid!r}"


# ---------------------------------------------------------------------------
# RSS  —  TechCrunch feed (no API key required)
# ---------------------------------------------------------------------------


class TestRealRSS:
    """Real API test against the TechCrunch RSS feed.

    TechCrunch was confirmed as reachable and returns a well-formed
    RSS 2.0 feed.  Skipped automatically unless ``-m real_api`` is passed.
    """

    def test_real_rss_collect(self) -> None:
        """Actually call TechCrunch RSS and verify entries have titles."""
        from autoinfo.collectors.rss import RSSHandler

        handler = RSSHandler(source_name="techcrunch")
        items = handler.fetch("https://techcrunch.com/feed/")

        assert isinstance(items, list)
        assert len(items) >= 1, "Expected at least one entry from TechCrunch"
        for item in items:
            assert isinstance(item, Item)
            assert item.title, f"Missing title in item: {item.id}"


# ---------------------------------------------------------------------------
# LLM  —  requires AUTOINFO_LLM_API_KEY (skipped otherwise)
# ---------------------------------------------------------------------------


@pytest.mark.llm
@requires_llm_key
class TestRealLLM:
    """Real API test against the configured LLM provider.

    Requires ``AUTOINFO_LLM_API_KEY`` to be set.  Uses the project's
    default LLM configuration (provider, model) to perform a real
    extraction call.
    """

    def test_real_llm_extraction(self) -> None:
        """Actually call the LLM and verify extraction returns non-empty."""
        from autoinfo.llm import LLMExtractor

        extractor = LLMExtractor()

        item = Item(
            id="real-llm-test",
            source_name="manual",
            source_type="manual",
            source_url="https://example.com/crispr-test",
            title="CRISPR-Cas9: A Revolutionary Gene-Editing Tool",
            content=(
                "CRISPR-Cas9 is a revolutionary gene-editing tool that allows "
                "scientists to edit DNA sequences with unprecedented precision. "
                "It has broad applications in medicine, agriculture, and "
                "fundamental biological research."
            ),
            domain="medical-research",
        )

        result = extractor.extract(item)

        assert result.tl_dr, "Expected non-empty TL;DR from LLM extraction"
