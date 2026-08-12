"""Tests for D11 — ``magazine-digest`` ProductTemplate + template variant.

Covers:

- ``list_output_templates()`` count == 8 (B24 column + D11 magazine-digest
  both landed — M5T42 owns the test_mcp_v2 count flip to 8 ONCE)
- The ``magazine-digest`` row exists with ``access_level == "free"`` (per
  plan recommendation — free product, licensing ceiling stays in place)
- ``generate_digest`` renders through the magazine-digest template variant
  (``magazine-digest.md.j2``) when the magazine row's ``ProductTemplate`` is
  passed — cover-style header + per-title (source_platform) clusters
- Regression: the plain ``digest`` row's template still renders the standard
  ``digest.md.j2`` family (identity lookup must not change existing behavior)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    generate_digest,
    list_output_templates,
)

# ===================================================================
# Sample data
# ===================================================================

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "title": "The Quiet AI Revolution in Newsrooms",
        "summary": "Newsrooms are quietly adopting AI tools for copy editing.",
        "source_url": "https://www.theatlantic.com/tech/archive/2026/07/ai-newsrooms/",
        "source_type": "rss",
        "source_platform": "the-atlantic",
        "relevance_score": 91.0,
        "tags": '["AI", "journalism"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-29T10:00:00Z",
    },
    {
        "entry_id": "entry-002",
        "title": "Why Wired Readers Trust Slow Journalism",
        "summary": "Long-form reporting builds trust in an age of speed.",
        "source_url": "https://www.wired.com/story/slow-journalism-trust/",
        "source_type": "rss",
        "source_platform": "wired",
        "relevance_score": 84.0,
        "tags": '["journalism", "trust"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-29T11:00:00Z",
    },
    {
        "entry_id": "entry-003",
        "title": "The Week in Climate Policy",
        "summary": "Three nations announced new emissions targets this week.",
        "source_url": "https://time.com/climate-policy-week/",
        "source_type": "rss",
        "source_platform": "time",
        "relevance_score": 77.0,
        "tags": '["climate", "policy"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-30T09:00:00Z",
    },
]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "Magazine coverage this week spans AI in newsrooms, the value of "
        "slow journalism, and a flurry of climate policy announcements."
    ),
    "key_findings": [
        {"topic": "AI adoption", "detail": "Newsrooms are scaling AI quietly."},
    ],
    "trends": ["Trust-centric journalism", "Climate policy momentum"],
    "recommendations": ["Watch the Atlantic AI desk."],
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Return sample entries for any domain (mirrors test_digest helper)."""
    return _SAMPLE_ENTRIES


def _magazine_template() -> ProductTemplate:
    """Return the ``magazine-digest`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "magazine-digest":
            return row["template"]
    raise AssertionError(
        "magazine-digest ProductTemplate row missing from PRODUCT_TEMPLATES"
    )


def _digest_template() -> ProductTemplate:
    """Return the base ``digest`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "digest":
            return row["template"]
    raise AssertionError("digest ProductTemplate row missing from PRODUCT_TEMPLATES")


# ===================================================================
# Test: registry
# ===================================================================


class TestMagazineRegistry:
    """``magazine-digest`` is a first-class, free product template."""

    def test_list_output_templates_count_is_eight(self) -> None:
        """B24 column + D11 magazine-digest bring the count to 8."""
        result = list_output_templates(domain="general-news")
        assert result["count"] == 8
        names = [t["name"] for t in result["templates"]]
        assert "magazine-digest" in names

    def test_magazine_digest_row_is_free(self) -> None:
        """The magazine-digest row requires no paid subscription (D11)."""
        row = next(r for r in PRODUCT_TEMPLATES if r["name"] == "magazine-digest")
        assert row["access_level"] == "free"
        assert row["template"].access_level == "free"
        assert isinstance(row["template"], ProductTemplate)

    def test_magazine_digest_row_description(self) -> None:
        """The row advertises the per-title RSS magazine digest."""
        row = next(r for r in PRODUCT_TEMPLATES if r["name"] == "magazine-digest")
        assert "Magazine" in row["description"]
        assert "RSS" in row["description"]


# ===================================================================
# Test: render dispatch through the magazine variant
# ===================================================================


class TestMagazineRender:
    """``generate_digest`` renders via ``magazine-digest.md.j2``."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_generate_digest_renders_magazine_variant(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Passing the magazine ProductTemplate renders the magazine layout.

        The digest LLM seam (``_call_llm_for_digest``) is patched at the
        function level, so no ``usage`` object reaches the cost meter — the
        mocked synthesis is a plain dict (no MagicMock token counters).
        """
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="general-news",
            period="weekly",
            product_template=_magazine_template(),
        )

        assert isinstance(result, str)
        # Cover-style header markers
        assert "Magazine Digest" in result
        assert "general-news" in result
        # Per-title clusters (grouped by source_platform)
        assert "the-atlantic" in result
        assert "wired" in result
        assert "time" in result
        # Entries inside their title clusters
        assert "The Quiet AI Revolution in Newsrooms" in result
        assert "Why Wired Readers Trust Slow Journalism" in result
        assert "The Week in Climate Policy" in result
        # Executive summary pulled through the cover header
        assert "AI in newsrooms" in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_row_still_renders_standard_template(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """The base digest row's template keeps rendering ``digest.md.j2``.

        Guards the identity-lookup dispatch: existing rows must render
        their usual template family (no FileNotFoundError regression).
        """
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research",
            period="weekly",
            product_template=_digest_template(),
        )

        assert isinstance(result, str)
        # Standard digest.md.j2 markers
        assert "Weekly Digest" in result
        assert "## Entries" in result
        # NOT magazine markers
        assert "Magazine Digest" not in result

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_magazine_render_free_user_no_gate(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """A free magazine template never triggers the G15 gate, even with user_id."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="general-news",
            period="weekly",
            product_template=_magazine_template(),
            user_id="free-user",
        )

        assert isinstance(result, str)
        assert "Access level required" not in result
        assert "The Quiet AI Revolution in Newsrooms" in result
