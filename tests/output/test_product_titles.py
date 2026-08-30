"""Tests for issue #318 — product-specific H1 titles.

Before the fix, ``generate_digest`` hardcoded the H1 product word to
``"Digest"`` regardless of ``product_template`` (``context["title"] =
f"{period_label} Digest — {domain}"``), so every ``--product`` rendered
``# Weekly Digest — <domain>``.  ``generate_report`` likewise hardcoded
``"Report"`` in ``ReportData.title`` regardless of product.

Covers:

- The 8 product families (digest, report, tutorial, presentation,
  premium-briefing, column, magazine-digest, enterprise-briefing) each render
  a distinct H1 that matches the product name + domain on the
  digest-with-product-template path (``generate_digest(product_template=
  <registry row>)``)
- The ``period`` label drives the Daily/Weekly/Monthly prefix
  (``period="daily"`` → ``Daily …``, ``period="weekly"`` → ``Weekly …``)
- The report path (``generate_report(product_template=…)``) is product-aware
  too, following its existing ``{domain} — {product word}`` title shape
- Backward compatibility: the default digest (no ``product_template``) and
  the default report (no ``product_template``, incl. ``report_type="column"``)
  keep their historical titles byte-identical
- ``_product_h1_word`` maps every resolved family to its H1 word
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult
from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    _product_h1_word,
    generate_digest,
    generate_report,
)

# ===================================================================
# Sample data
# ===================================================================

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "title": "Improved IVF outcomes with time-lapse imaging",
        "language": "en",
        "summary": "Time-lapse imaging improves live birth rates in IVF.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "source_type": "api",
        "source_platform": "pubmed",
        "relevance_score": 92.0,
        "tags": '["IVF", "embryo"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    },
    {
        "entry_id": "entry-002",
        "title": "AI embryo selection: a systematic review",
        "language": "en",
        "summary": "AI models show promise but lack prospective validation.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
        "source_type": "api",
        "source_platform": "pubmed",
        "relevance_score": 85.0,
        "tags": '["AI", "IVF"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-16T10:00:00Z",
    },
]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's key developments focus on IVF technology advancements "
        "including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": "Significant improvement in live birth rates.",
        },
        {
            "topic": "AI embryo selection",
            "detail": "Promising but lacks prospective clinical validation.",
        },
    ],
    "trends": ["Increasing integration of AI/ML in reproductive medicine"],
    "recommendations": ["Support prospective AI validation trials."],
}

# Product family → expected H1 product word (issue #318; tutorial +
# presentation = issue #99 — every registry family carries its word).
_EXPECTED_H1_WORDS: dict[str, str] = {
    "digest": "Digest",
    "report": "Report",
    "tutorial": "Tutorial",
    "presentation": "Presentation",
    "premium-briefing": "Premium Briefing",
    "column": "Column",
    "magazine-digest": "Magazine Digest",
    "enterprise-briefing": "Enterprise Briefing",
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


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return cast(ProductTemplate, row["template"])
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _render_digest(
    *,
    product_template: ProductTemplate | None = None,
    period: str = "weekly",
) -> str:
    """Render a digest through generate_digest with the shared mocks."""
    with (
        patch("autoinfo.output.KBStore") as mock_kb_cls,
        patch("autoinfo.output._call_llm_for_digest") as mock_llm,
    ):
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb_cls.return_value = mock_store
        result = generate_digest(
            domain="medical-research",
            period=period,
            format="markdown",
            product_template=product_template,
        )
    assert isinstance(result, str)
    return result


def _h1(markdown: str) -> str:
    """Return the first ``# `` heading line of a rendered markdown doc."""
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line
    raise AssertionError(f"no H1 (# ) line found in output:\n{markdown[:500]}")


def _make_grouping_result() -> ExtractionResult:
    """Return an ExtractionResult with thematic grouping custom fields."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "IVF & Reproductive Medicine",
                    "description": (
                        "Advancements in IVF treatment and assisted "
                        "reproductive technologies."
                    ),
                    "entry_ids": ["entry-001"],
                },
                {
                    "theme": "Neuroplasticity & Brain Development",
                    "description": (
                        "Brain plasticity across different developmental stages."
                    ),
                    "entry_ids": ["entry-002"],
                },
            ],
        },
    )


def _make_summary_result() -> ExtractionResult:
    """Return an ExtractionResult with executive summary custom fields."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Executive Summary",
        custom_fields={
            "executive_summary": (
                "This briefing covers two key themes. IVF treatment continues "
                "to advance with time-lapse imaging improving outcomes."
            ),
        },
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the ``LLMExtractor`` class from ``autoinfo.llm``."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


def _render_report(
    *,
    product_template: ProductTemplate | None = None,
    report_type: str = "standard",
) -> str:
    """Render a report through generate_report with the shared mocks."""
    mock_extract = MagicMock(
        side_effect=[
            _make_grouping_result(),
            _make_summary_result(),
        ]
    )
    with (
        patch("autoinfo.output.KBStore") as mock_kb_cls,
        patch.object(_get_llm_extractor_class(), "extract", mock_extract),
        patch(
            "autoinfo.output._call_llm_for_report_synthesis",
            return_value="",
        ),
    ):
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        mock_kb_cls.return_value = mock_store
        result = generate_report(
            domain="medical-research",
            format="markdown",
            report_type=report_type,
            product_template=product_template,
        )
    assert isinstance(result, str)
    return result


# ===================================================================
# Unit tests: _product_h1_word
# ===================================================================


class TestProductH1Word:
    """``_product_h1_word`` maps every resolved family to its H1 word."""

    def test_maps_all_product_families(self) -> None:
        """Each family resolves to its product-specific H1 word."""
        for family, word in _EXPECTED_H1_WORDS.items():
            assert _product_h1_word(family) == word

    def test_unknown_family_falls_back_to_default(self) -> None:
        """Unknown families fall back to the caller-provided default."""
        assert _product_h1_word("bogus-family") == "Digest"
        assert _product_h1_word("bogus-family", default="Report") == "Report"


# ===================================================================
# Digest path: product-aware H1 titles (issue #318)
# ===================================================================


class TestDigestProductH1Titles:
    """``generate_digest(product_template=…)`` renders a product-specific H1."""

    @pytest.mark.parametrize("family", sorted(_EXPECTED_H1_WORDS))
    def test_digest_h1_matches_product_word_and_domain(
        self, family: str
    ) -> None:
        """The H1 is ``# Weekly {product word} — medical-research``."""
        result = _render_digest(product_template=_registry_template(family))
        expected = f"# Weekly {_EXPECTED_H1_WORDS[family]} \u2014 medical-research"
        assert _h1(result) == expected

    def test_all_product_h1s_are_distinct(self) -> None:
        """The product H1s all differ from each other (acceptance #318/#99)."""
        h1s = {
            family: _h1(
                _render_digest(product_template=_registry_template(family))
            )
            for family in _EXPECTED_H1_WORDS
        }
        assert len(set(h1s.values())) == len(_EXPECTED_H1_WORDS)
        # Each H1 embeds its own product word + the domain.
        for family, h1 in h1s.items():
            assert _EXPECTED_H1_WORDS[family] in h1
            assert "medical-research" in h1

    def test_period_label_drives_daily_prefix(self) -> None:
        """``period="daily"`` yields a ``Daily`` prefix on every product."""
        for family in _EXPECTED_H1_WORDS:
            result = _render_digest(
                product_template=_registry_template(family), period="daily"
            )
            expected = f"# Daily {_EXPECTED_H1_WORDS[family]} \u2014 medical-research"
            assert _h1(result) == expected

    def test_period_label_drives_weekly_prefix(self) -> None:
        """``period="weekly"`` yields a ``Weekly`` prefix on every product."""
        for family in _EXPECTED_H1_WORDS:
            result = _render_digest(
                product_template=_registry_template(family), period="weekly"
            )
            expected = f"# Weekly {_EXPECTED_H1_WORDS[family]} \u2014 medical-research"
            assert _h1(result) == expected

    def test_default_digest_h1_unchanged(self) -> None:
        """No product_template → the historical ``Weekly Digest`` H1 (byte-identical)."""
        result = _render_digest()
        assert _h1(result) == "# Weekly Digest \u2014 medical-research"


# ===================================================================
# Report path: product-aware H1 titles (issue #318)
# ===================================================================


class TestReportProductH1Titles:
    """``generate_report(product_template=…)`` renders a product-specific H1."""

    @pytest.mark.parametrize(
        ("family", "report_type"),
        [
            ("premium-briefing", "standard"),
            ("column", "column"),
            ("enterprise-briefing", "standard"),
        ],
    )
    def test_report_h1_matches_product_word(
        self, family: str, report_type: str
    ) -> None:
        """The report H1 is ``# medical-research — {product word}``."""
        result = _render_report(
            product_template=_registry_template(family),
            report_type=report_type,
        )
        expected = f"# medical-research \u2014 {_EXPECTED_H1_WORDS[family]}"
        assert _h1(result) == expected

    def test_default_report_h1_unchanged(self) -> None:
        """No product_template → the historical ``medical-research — Report`` H1."""
        result = _render_report(report_type="standard")
        assert _h1(result) == "# medical-research \u2014 Report"

    def test_default_column_report_h1_unchanged(self) -> None:
        """``report_type="column"`` without a template keeps ``— Report`` (T40)."""
        result = _render_report(report_type="column")
        assert _h1(result) == "# medical-research \u2014 Report"
