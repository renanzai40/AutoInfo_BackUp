"""Tests for B24 — ``report_type="column"`` premium product.

Covers:

- ``"column"`` is a valid report type (``_VALID_REPORT_TYPES``)
- ``generate_report(report_type="column", user_id=..., product_template=column_row)``
  hits the G15 freemium gate and returns the blocked (access denied) message
  for a non-subscriber — via the real ``billing.check_access`` (no LLM key
  needed; the gate runs before any LLM work)
- ``generate_report(report_type="column")`` without ``user_id`` renders
  normally (free path — LLM mocked)
- Invalid report types still raise ``ValueError``
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.models import ExtractionResult
from autoinfo.output import PRODUCT_TEMPLATES, _VALID_REPORT_TYPES


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def sample_entries() -> list[dict[str, Any]]:
    """Return synthetic KB entry dicts for report tests."""
    return [
        {
            "entry_id": "entry-001",
            "title": "Improved IVF outcomes with time-lapse imaging",
            "summary": "Time-lapse imaging improves live birth rates in IVF.",
            "source_url": "https://example.com/ivf-1",
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
            "summary": "Early childhood experiences shape brain plasticity.",
            "source_url": "https://example.com/neuro-1",
            "source_type": "rss",
            "source_platform": "feed",
            "relevance_score": 78.0,
            "tags": '["neuroplasticity", "development"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-16T10:00:00Z",
        },
    ]


def _column_template() -> Any:
    """Return the ``column`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "column":
            return row["template"]
    raise AssertionError("column ProductTemplate row missing from PRODUCT_TEMPLATES")


def _make_grouping_result() -> ExtractionResult:
    """Return an ExtractionResult with thematic grouping custom fields."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "IVF & Reproductive Medicine",
                    "description": "Advancements in IVF treatment and assisted reproductive technologies.",
                    "entry_ids": ["entry-001"],
                },
                {
                    "theme": "Neuroplasticity & Brain Development",
                    "description": "Brain plasticity across different developmental stages.",
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
                "This column covers two key themes. IVF treatment continues "
                "to advance with time-lapse imaging improving outcomes. "
                "Neuroplasticity research highlights critical developmental "
                "periods."
            ),
        },
    )


# ===================================================================
# Test: registry
# ===================================================================


class TestColumnRegistry:
    """``report_type="column"`` is a first-class report type."""

    def test_column_is_a_valid_report_type(self) -> None:
        """``_VALID_REPORT_TYPES`` includes ``column`` (B24)."""
        assert "column" in _VALID_REPORT_TYPES

    def test_column_product_template_is_premium(self) -> None:
        """The ``column`` ProductTemplate row requires premium access."""
        row = next(r for r in PRODUCT_TEMPLATES if r["name"] == "column")
        assert row["access_level"] == "premium"
        assert row["template"].access_level == "premium"


# ===================================================================
# Test: G15 gate
# ===================================================================


class TestColumnG15Gate:
    """``report_type="column"`` + user_id hits the G15 freemium gate."""

    def test_nonsubscriber_gets_blocked_message(self) -> None:
        """A non-subscriber receives the G15 access-denied message, not content.

        Runs the real ``billing.check_access`` with a non-existent user — no
        API key and no LLM calls needed because the gate runs first.
        """
        result = _call_report(
            "medical-research",
            user_id="nonexistent-user",
            product_template=_column_template(),
        )

        assert isinstance(result, str)
        assert "premium content" in result or "Upgrade" in result
        assert "Access level required" in result
        assert "`premium`" in result
        # Content must never leak through the gate
        assert "Executive Summary" not in result
        assert "IVF treatment" not in result

    def test_nonsubscriber_block_runs_without_api_key(self) -> None:
        """The G15 block fires without any LLM configuration (no key needed)."""
        with patch.dict("os.environ", {}, clear=False):
            result = _call_report(
                "medical-research",
                user_id="nonexistent-user",
                product_template=_column_template(),
            )
        assert isinstance(result, str)
        assert "Access level required" in result


# ===================================================================
# Test: free path renders normally
# ===================================================================


class TestColumnFreePath:
    """Without ``user_id`` the column report renders normally (no gating)."""

    def test_no_user_id_renders_report(
        self, sample_entries: list[dict]
    ) -> None:
        """Free path: LLM mocked, full render through the report template."""
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

            report = _call_report("medical-research")

        # -- Assertions -------------------------------------------------------
        assert "# medical-research — Report" in report
        assert "## Executive Summary" in report
        assert "IVF treatment" in report
        assert "## References" in report
        assert "https://example.com/ivf-1" in report


# ===================================================================
# Test: invalid type still raises
# ===================================================================


class TestColumnValidation:
    """Invalid report types keep raising ``ValueError``."""

    def test_invalid_report_type_still_raises(self) -> None:
        """An unknown report type raises ``ValueError`` even for column glue."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            with pytest.raises(ValueError, match="Unknown report type"):
                _call_report("medical-research", report_type="bogus-type")


# ===================================================================
# Helpers
# ===================================================================


def _call_report(
    domain: str,
    user_id: str = "",
    product_template: Any = None,
    report_type: str = "column",
) -> str:
    """Call ``generate_report`` from ``autoinfo.output``."""
    from autoinfo.output import generate_report

    return generate_report(
        domain=domain,
        format="markdown",
        report_type=report_type,
        user_id=user_id,
        product_template=product_template,
    )


def _get_llm_extractor_class():
    """Return the ``LLMExtractor`` class from ``autoinfo.llm``."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor
