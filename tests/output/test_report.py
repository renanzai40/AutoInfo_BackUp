"""Tests for structured report generation — ``autoinfo.output.generate_report``.

Covers:

- ``generate_report`` with no entries → empty report message
- ``generate_report`` with entries → LLM thematic grouping → rendered template
- Fallback grouping when LLM call fails
- Fallback executive summary when LLM call fails
- Unsupported format raises ``ValueError``
- Invalid period raises ``ValueError``
- CLI wiring — ``autoinfo output report --domain X`` invokes ``generate_report``
- Report types — ``standard``, ``industry``, ``competitive``, ``trend``, ``daily-briefing``
- Invalid report type raises ``ValueError``
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult

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
            "summary": "Early childhood experiences shape brain plasticity.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
            "source_type": "rss",
            "source_platform": "feed",
            "relevance_score": 78.0,
            "tags": '["neuroplasticity", "development"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-16T10:00:00Z",
        },
        {
            "entry_id": "entry-003",
            "title": "Synaptic pruning mechanisms in adolescents",
            "summary": "Adolescent brain undergoes significant synaptic pruning.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654322/",
            "source_type": "api",
            "source_platform": "pubmed",
            "relevance_score": 85.0,
            "tags": '["neuroplasticity", "adolescent"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-17T10:00:00Z",
        },
    ]


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
                    "description": "Brain plasticity across different developmental stages.",
                    "entry_ids": ["entry-002", "entry-003"],
                },
            ],
        },
    )


def _make_grouping_result_extra() -> ExtractionResult:
    """Return grouping with an extra theme to validate catch-all handling.

    Two groups so the anti-collapse retry (`output/__init__.py:3243-3272`) is
    not triggered; the second theme references an unknown entry id and is
    dropped after mapping, leaving entry-002/003 ungrouped.
    """
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "IVF & Reproductive Medicine",
                    "description": "IVF treatment outcomes.",
                    "entry_ids": ["entry-001"],
                },
                {
                    "theme": "Follow-up Research",
                    "description": "Theme whose entries are unknown to the KB.",
                    "entry_ids": ["entry-999"],
                },
            ],
        },
    )


def _make_summary_result(summary_text: str = "") -> ExtractionResult:
    """Return an ExtractionResult with executive summary custom fields."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Executive Summary",
        custom_fields={
            "executive_summary": summary_text or (
                "This report covers three entries across two key themes. "
                "IVF treatment continues to advance with time-lapse imaging "
                "improving outcomes. Neuroplasticity research highlights "
                "critical periods in both early childhood and adolescence."
            ),
        },
    )


def _make_empty_extraction() -> ExtractionResult:
    """Return an ExtractionResult with no custom fields (LLM failure mock)."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Empty",
        custom_fields={},
    )


# ===================================================================
# Test: generate_report
# ===================================================================


class TestGenerateReport:
    """``generate_report()`` — structured report generation."""

    def test_empty_entries_returns_empty_message(self) -> None:
        """No KB entries yields a brief empty-report message (#342: neutral
        prose, never a ``_No ..._`` / ``No knowledge base entries`` marker)."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            report = _call_report("test-domain")

        assert "This edition has no curated items yet" in report
        assert "test-domain" in report
        assert "No knowledge base entr" not in report
        assert "_No " not in report

    def test_unsupported_format_raises_value_error(self) -> None:
        """Formats other than 'markdown', 'json', 'html' raise ``ValueError``."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            with pytest.raises(ValueError, match="Unsupported output format"):
                _call_report("test-domain", format="pdf")

    def test_happy_path_renders_complete_report(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """Full flow: entries → LLM grouping → template → rendered markdown."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
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
        # Title
        assert "# medical-research — Report" in report

        # Executive summary section
        assert "## Executive Summary" in report
        assert "IVF treatment" in report
        assert "Neuroplasticity" in report

        # Sections header
        assert "## Sections" in report

        # Themed section titles
        assert "### IVF & Reproductive Medicine" in report
        assert "### Neuroplasticity & Brain Development" in report

        # Items table within sections
        assert "Improved IVF outcomes with time-lapse imaging" in report
        assert "Neuroplasticity in early childhood development" in report
        assert "Synaptic pruning mechanisms in adolescents" in report

        # References
        assert "## References" in report
        assert "https://pubmed.ncbi.nlm.nih.gov/12345678/" in report
        assert "https://pubmed.ncbi.nlm.nih.gov/87654321/" in report
        assert "https://pubmed.ncbi.nlm.nih.gov/87654322/" in report

        # Metadata
        assert "**Domain**: medical-research" in report
        assert "**Generated**:" in report
        assert "medical-research" in report

    def test_llm_grouping_failure_falls_back_to_single_group(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """When LLM grouping fails, entries fall back to source-type groups."""
        mock_extract = MagicMock(
            side_effect=[
                _make_empty_extraction(),  # grouping fails → no custom fields
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        # TRIAGE #50 (stale): the grouping fallback (f83bd8d,
        # `output/__init__.py:3275-3317`) now splits by domain/source_type
        # instead of lumping everything under "General". All sample entries
        # have no domain key → single "Unknown" domain → source_type split
        # (api ×2, rss ×1).
        assert "### General" not in report
        assert "### Platform & API News" in report
        assert "### Industry News & Analysis" in report
        # All three entries appear
        assert "Improved IVF outcomes" in report
        assert "Neuroplasticity in early childhood" in report
        assert "Synaptic pruning" in report

    def test_llm_grouping_exception_falls_back(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """When LLM grouping raises, entries fall back to source-type groups."""
        mock_extract = MagicMock(
            side_effect=[
                Exception("LLM unavailable"),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        # TRIAGE #51 (stale): same source_type-split fallback as #50.
        assert "### Platform & API News" in report
        assert "### Industry News & Analysis" in report
        assert "Improved IVF outcomes" in report

    def test_executive_summary_failure_falls_back(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """When LLM executive summary fails, a bullet-list fallback is used."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_empty_extraction(),  # summary fails → empty
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        # Fallback summary mentions theme names and entry counts
        assert "This report covers" in report
        assert "IVF & Reproductive Medicine" in report
        assert "Neuroplasticity & Brain Development" in report

    def test_executive_summary_exception_falls_back(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """When LLM executive summary raises, a bullet-list fallback is used."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                Exception("LLM timeout"),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        assert "This report covers" in report

    def test_fallback_sections_non_empty_after_llm_empty_synthesis(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """Issue #217: when every LLM synthesis path comes back empty, the
        report's deterministic fallback must still carry non-empty
        key_findings / recommendations derived from the real entries, so
        D1 (product completeness) does not block the report."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_empty_extraction(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        # Fallback sections are entry-derived, never empty (D1 passes).
        assert "This report covers" in report
        assert "## Key Findings" in report
        assert "IVF" in report or "time-lapse" in report
        """Entries not matched by LLM grouping appear in 'Additional Topics'."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result_extra(),  # only entry-001 grouped
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research")

        # entry-002 and entry-003 are ungrouped → catch-all appears
        assert "### Additional Topics" in report
        assert "Neuroplasticity in early childhood" in report
        assert "Synaptic pruning" in report

    def test_render_with_collection_id(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``collection_id`` appears in the rendered report metadata."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                "medical-research", collection_id="col-20260715-abc123"
            )

        assert "col-20260715-abc123" in report


# ===================================================================
# Test: Report types
# ===================================================================


class TestReportTypes:
    """``generate_report(report_type=...)`` — specialized report types."""

    def test_standard_type_is_unchanged(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``report_type="standard"`` produces same output as omitting the parameter."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report_default = _call_report("medical-research")
            report_explicit = _call_report(
                "medical-research", report_type="standard"
            )

        # Both should have same structure
        assert "# medical-research — Report" in report_default
        assert "# medical-research — Report" in report_explicit
        assert "## Executive Summary" in report_default
        assert "## Executive Summary" in report_explicit
        assert "## Sections" in report_default
        assert "## Sections" in report_explicit

    def test_industry_type_produces_report(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``report_type="industry"`` produces a valid structured report."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research", report_type="industry")

        assert "medical-research" in report
        assert "## Executive Summary" in report
        assert "## Sections" in report

    def test_competitive_type_produces_report(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``report_type="competitive"`` produces a valid structured report."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research", report_type="competitive")

        assert "medical-research" in report
        assert "## Executive Summary" in report
        assert "## Sections" in report

    def test_trend_type_produces_report(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``report_type="trend"`` produces a valid structured report."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report("medical-research", report_type="trend")

        assert "medical-research" in report
        assert "## Executive Summary" in report
        assert "## Sections" in report

    def test_daily_briefing_type_produces_report(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """``report_type="daily-briefing"`` produces a valid structured report."""
        mock_extract = MagicMock(
            side_effect=[
                _make_grouping_result(),
                _make_summary_result(),
            ]
        )

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                return_value="",
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            report = _call_report(
                "medical-research", report_type="daily-briefing"
            )

        assert "medical-research" in report
        assert "## Executive Summary" in report
        assert "## Sections" in report

    def test_invalid_report_type_raises_value_error(self) -> None:
        """Unknown ``report_type`` raises ``ValueError``."""
        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_store = MagicMock()
            mock_store.list_entries.return_value = []
            mock_kb_cls.return_value = mock_store

            with pytest.raises(ValueError, match="Unknown report type"):
                _call_report("test-domain", report_type="nonexistent")

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period raises ValueError."""
        from autoinfo.output import generate_report

        with pytest.raises(ValueError, match="Invalid period"):
            generate_report(domain="test", period="yearly")

    def test_type_prompt_injected_into_executive_summary(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        """Type-specific prompt text reaches the executive summary LLM call."""
        mock_extract = MagicMock(
            side_effect=[_make_grouping_result()]
        )

        mock_summary = "Custom industry summary."

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract", mock_extract
            ),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value=mock_summary,
            ) as mock_exec,
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            _call_report("medical-research", report_type="industry")

        mock_exec.assert_called_once()
        # The custom_instructions arg should contain the industry prompt
        # (passed as the 4th positional argument)
        args = mock_exec.call_args.args
        instructions = args[3] if len(args) > 3 else ""
        assert "Industry Overview" in instructions
        assert "Key Developments" in instructions

    def test_standard_type_passes_empty_instructions(
        self, sample_entries: list[dict[str, Any]]
    ) -> None:
        (
            """``report_type="standard"`` passes empty/unchanged custom_instructions"""
            """ to executive summary."""
        )
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(), "extract",
                MagicMock(side_effect=[_make_grouping_result()]),
            ),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value="Standard summary.",
            ) as mock_exec,
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = sample_entries
            mock_kb_cls.return_value = mock_store

            _call_report(
                "medical-research",
                report_type="standard",
                custom_instructions="Focus on safety.",
            )

        args = mock_exec.call_args.args
        instructions = args[3] if len(args) > 3 else ""
        assert "Focus on safety." in instructions
        # Standard type should NOT inject any type-specific prompt
        assert "Industry Overview" not in instructions
        assert "Market Players" not in instructions
        assert "Trend Overview" not in instructions
        assert "Top Stories" not in instructions


# ===================================================================
# Test: CLI wiring
# ===================================================================


# CLI tests skipped due to typer + Python 3.14 incompatibility
# (inspect.signature(eval_str=True) fails on Python 3.14 + typer 0.12)
# Issue affects ALL CLI tests across the project, not just report.
# Re-enable when upstream typer fixes eval_str compatibility with Python 3.14.


class TestReportCli:
    """``autoinfo output report`` CLI command."""

    @patch("autoinfo.output.generate_report")
    def test_report_help(
        self, mock_generate: MagicMock
    ) -> None:
        """``--help`` shows expected parameters."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_report")
    def test_report_missing_domain(
        self, mock_generate: MagicMock
    ) -> None:
        """Missing ``--domain`` shows error."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_report")
    def test_report_invokes_generate_report(
        self, mock_generate: MagicMock
    ) -> None:
        """``output report --domain X`` calls ``generate_report`` and echoes result."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_report")
    def test_report_with_collection_id(
        self, mock_generate: MagicMock
    ) -> None:
        """``--collection-id`` is passed through to ``generate_report``."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_report")
    def test_report_format_option_passed_through(
        self, mock_generate: MagicMock
    ) -> None:
        """``--format`` is passed through to ``generate_report``."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")

    @patch("autoinfo.output.generate_report")
    def test_report_handles_value_error(
        self, mock_generate: MagicMock
    ) -> None:
        """ValueError from ``generate_report`` prints error and exits non-zero."""
        pytest.skip("typer broken on Python 3.14 (inspect.signature eval_str)")


# ===================================================================
# Helpers
# ===================================================================


def _call_report(
    domain: str,
    collection_id: str | None = None,
    format: str = "markdown",
    report_type: str = "standard",
    custom_instructions: str = "",
) -> str:
    """Call ``generate_report`` from ``autoinfo.output``."""
    from autoinfo.output import generate_report

    return cast(
        str,
        generate_report(
            domain=domain,
            collection_id=collection_id,
            format=format,
            report_type=report_type,
            custom_instructions=custom_instructions,
        ),
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the ``LLMExtractor`` class from ``autoinfo.llm``."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


# ===================================================================
# Glued Key Findings parsing (issue #14)
# ===================================================================


def _parse_report_markdown(content: str) -> dict[str, Any]:
    """Call the module-level report parser directly (issue #14)."""
    from autoinfo.output import _parse_report_markdown

    return _parse_report_markdown(content)


GLUED_KF_MD = """\
## Executive Summary
AI funding and model releases moved this week.

## Key Findings
""" + (
    "- AI Regulation and Safety: rogue-model oversight tightened "
    "(Source: https://example.com/rogue)"
    "- Venture Capital and Funding: Series A rounds accelerate "
    "(Source: https://example.com/vc)"
    "- Legal and Regulatory Actions: antitrust review opens "
    "(Source: https://example.com/legal)"
) + """

## Recommendations
- Monitor regulatory shifts
- Track funding rounds
"""


class TestGluedKeyFindings:
    """Issue #14: the LLM sometimes glues Key Findings bullets onto one line
    (`- a (Source: u)- b (Source: u)- c`); the parser must split them into
    distinct items instead of returning ONE giant bullet."""

    def test_glued_key_findings_split_into_multiple_items(self) -> None:
        parsed = _parse_report_markdown(GLUED_KF_MD)

        assert len(parsed["key_findings"]) == 3
        assert parsed["key_findings"] == [
            "AI Regulation and Safety: rogue-model oversight tightened "
            "(Source: https://example.com/rogue)",
            "Venture Capital and Funding: Series A rounds accelerate "
            "(Source: https://example.com/vc)",
            "Legal and Regulatory Actions: antitrust review opens "
            "(Source: https://example.com/legal)",
        ]
        assert len(set(parsed["key_findings"])) == 3
        assert all(")- " not in item for item in parsed["key_findings"])

    def test_parsed_kf_items_never_contain_glued_separator(self) -> None:
        head = "## Executive Summary\nCoverage summary.\n\n"
        glued_inputs = [
            (
                head
                + "## Key Findings\n"
                "- A: outcome one (Source: https://example.com/a)"
                "- B: outcome two (Source: https://example.com/b)"
            ),
            (
                head
                + "## Key Findings\n"
                "- first finding with a trailing close paren) and more text "
                "(Source: https://example.com/x)- second finding "
                "(Source: https://example.com/y)"
            ),
            (
                head
                + "## Key Findings\n"
                "- 1. first (Source: https://example.com/1)- 2. second "
                "(Source: https://example.com/2)- 3. third "
                "(Source: https://example.com/3)"
            ),
        ]
        for md in glued_inputs:
            items = _parse_report_markdown(md)["key_findings"]
            assert items, f"expected at least one item for: {md!r}"
            assert len(items) >= 2, f"glued run not split: {items!r}"
            for item in items:
                assert ")- " not in item, f"glued separator inside item: {item!r}"
                assert not item.endswith(")-"), f"item ends with glue: {item!r}"
