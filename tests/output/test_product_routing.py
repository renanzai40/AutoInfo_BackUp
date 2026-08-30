"""Tests for product-type routing (output-quality-mega, todo 4 + todo 10).

Covers:

- ``_resolve_report_product_type`` mirrors the guard-first pattern of
  ``_resolve_digest_product_type``: a registry identity match resolves to
  its own template family only when the on-disk template exists; otherwise
  it falls back (never ``FileNotFoundError``)
- ``premium-briefing`` / ``enterprise-briefing`` passed via
  ``product_template`` render through their own template families
- existing callers without ``product_template`` are unchanged
  (``report_type="column"`` keeps the column family; everything else keeps
  the report family)
- ``_resolve_digest_product_type`` (the digest-side counterpart, added
  todo 10): the ``magazine-digest`` row resolves to its own family on the
  digest path, the base ``digest`` row stays on ``digest``, and the same
  guard-first on-disk fallback applies (no ``FileNotFoundError``)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult
from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    _resolve_digest_product_type,
    _resolve_report_product_type,
    generate_report,
)

# ===================================================================
# Fixtures & helpers
# ===================================================================


@pytest.fixture
def sample_entries() -> list[dict[str, Any]]:
    """Return synthetic KB entry dicts for report tests."""
    return [
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
            "title": "Neuroplasticity in early childhood development",
            "language": "en",
            "summary": "Early childhood experiences shape brain plasticity.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
            "source_type": "rss",
            "source_platform": "feed",
            "relevance_score": 78.0,
            "tags": '["neuroplasticity", "development"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-16T10:00:00Z",
        },
    ]


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return cast(ProductTemplate, row["template"])
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


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
                "to advance with time-lapse imaging improving outcomes. "
                "Neuroplasticity research highlights critical developmental "
                "periods."
            ),
        },
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the ``LLMExtractor`` class from ``autoinfo.llm``."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


# ===================================================================
# Resolver unit tests
# ===================================================================


class TestResolveReportProductType:
    """``_resolve_report_product_type`` routes registry templates by family."""

    def test_premium_briefing_resolves_when_template_on_disk(self) -> None:
        """The premium-briefing registry row maps to its own family (file exists)."""
        assert (
            _resolve_report_product_type(
                _registry_template("premium-briefing"), "md", "standard"
            )
            == "premium-briefing"
        )

    def test_enterprise_briefing_resolves_when_template_on_disk(self) -> None:
        """The enterprise-briefing registry row maps to its own family (file exists)."""
        assert (
            _resolve_report_product_type(
                _registry_template("enterprise-briefing"), "md", "standard"
            )
            == "enterprise-briefing"
        )

    def test_falls_back_to_report_when_template_file_absent(self, tmp_path: Path) -> None:
        """A registry row whose template file is missing falls back — no error.

        Guard-first: the on-disk existence check must never let a registry
        name point at a template that does not exist (FileNotFoundError trap
        from the T40 premium-briefing/enterprise-briefing rows).
        """
        with patch("autoinfo.output._TEMPLATES_DIR", tmp_path):
            assert (
                _resolve_report_product_type(
                    _registry_template("premium-briefing"), "md", "standard"
                )
                == "report"
            )

    def test_non_registry_template_falls_back_to_report(self) -> None:
        """A template outside the registry keeps the default report family."""
        custom = ProductTemplate(domain="medical-research", access_level="free")
        assert _resolve_report_product_type(custom, "md", "standard") == "report"

    def test_column_report_type_keeps_column_family(self) -> None:
        """``report_type="column"`` still resolves to the column family (T40)."""
        custom = ProductTemplate(domain="medical-research", access_level="free")
        assert _resolve_report_product_type(custom, "md", "column") == "column"

    def test_column_registry_row_resolves_via_on_disk_check(self) -> None:
        """The column registry row resolves to ``column`` (column.md.j2 exists)."""
        assert (
            _resolve_report_product_type(_registry_template("column"), "md", "column")
            == "column"
        )

    def test_report_row_resolves_to_report(self) -> None:
        """The report registry row resolves to ``report`` (report.md.j2 exists)."""
        assert (
            _resolve_report_product_type(_registry_template("report"), "md", "standard")
            == "report"
        )


class TestResolveDigestProductType:
    """``_resolve_digest_product_type`` (digest-path counterpart, todo 10).

    The report resolver mirrors this function; these unit tests pin the
    digest-side contract directly so a regression in either guard-first
    resolver is caught at unit level (the regression scenario
    regression-product-routing.yaml covers the end-to-end render).
    """

    def test_magazine_digest_resolves_when_template_on_disk(self) -> None:
        """The magazine-digest registry row maps to its own family (file exists)."""
        assert (
            _resolve_digest_product_type(_registry_template("magazine-digest"), "md")
            == "magazine-digest"
        )

    def test_digest_row_resolves_to_digest(self) -> None:
        """The base digest registry row keeps the default digest family."""
        assert (
            _resolve_digest_product_type(_registry_template("digest"), "md") == "digest"
        )

    def test_falls_back_to_digest_when_template_file_absent(self, tmp_path: Path) -> None:
        """A registry row whose template file is missing falls back — no error.

        Guard-first: the on-disk existence check must never let a registry
        name point at a template that does not exist (FileNotFoundError trap).
        """
        with patch("autoinfo.output._TEMPLATES_DIR", tmp_path):
            assert (
                _resolve_digest_product_type(
                    _registry_template("magazine-digest"), "md"
                )
                == "digest"
            )

    def test_non_registry_template_falls_back_to_digest(self) -> None:
        """A template outside the registry keeps the default digest family."""
        custom = ProductTemplate(domain="medical-research", access_level="free")
        assert _resolve_digest_product_type(custom, "md") == "digest"


# ===================================================================
# generate_report routing tests
# ===================================================================


class TestGenerateReportRouting:
    """``generate_report`` renders through the resolved template family."""

    def test_premium_briefing_renders_through_own_template(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """product_template=premium-briefing produces premium-briefing output.

        Distinct from the standard report: ``## Key Takeaways`` and the
        ``AutoInfo Premium Briefing`` footer are literal to
        ``premium-briefing.md.j2`` and absent from ``report.md.j2``.
        """
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
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            result = generate_report(
                domain="medical-research",
                format="markdown",
                report_type="standard",
                product_template=_registry_template("premium-briefing"),
            )

        assert isinstance(result, str)
        assert "## Key Takeaways" in result
        assert "AutoInfo Premium Briefing" in result
        assert "## Sections" not in result

    def test_standard_report_without_product_template_unchanged(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """Existing callers without ``product_template`` render report.md.j2."""
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
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            result = generate_report(
                domain="medical-research",
                format="markdown",
                report_type="standard",
            )

        assert isinstance(result, str)
        assert "# medical-research \u2014 Report" in result
        assert "## Sections" in result
        assert "AutoInfo Report" in result
        assert "## Key Takeaways" not in result
        assert "AutoInfo Premium Briefing" not in result
