"""Tests for issue #342: magazine-digest and tutorial products never render
placeholder empty-states (``_No articles found..._`` / ``_No objectives
defined._`` / ``_No exercises provided._`` / ``_No references provided._`` /
``No knowledge base entries found...``).

Four layers are locked:

1. ``_report_data_to_dict`` emits a top-level ``entries`` list built from the
   report references — the report-path magazine product (``generate_report``
   with the ``magazine-digest`` template) reads that list for its per-title
   clusters, so it renders real content instead of the empty-state.
2. The digest-path tutorial (``generate_digest`` with the tutorial template)
   fills ``objectives``/``content``/``exercises``/``further_reading`` from the
   real entries via ``_entry_derived_sections`` — the same helper the real
   ``generate_tutorial`` uses.
3. ``generate_tutorial`` with an unusable (empty) LLM result still renders
   KB-derived content.
4. The zero-entry paths (``generate_tutorial`` and ``_render_empty_report``)
   emit neutral prose that matches neither the ``_No [^_]+_`` placeholder
   regex nor the ``No knowledge base entr(?:y|ies) ...`` regex.

TDD: these tests fail (RED) on main, pass (GREEN) after the #342 fix.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

from autoinfo import validation_matrix as vm
from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    ReportData,
    _report_data_to_dict,
    generate_digest,
    generate_tutorial,
)

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "language": "en",
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
        "language": "en",
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
]


def _tutorial_template() -> ProductTemplate:
    """Return the ``tutorial`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "tutorial":
            return cast(ProductTemplate, row["template"])
    raise AssertionError("tutorial ProductTemplate row missing from PRODUCT_TEMPLATES")


def _magazine_template() -> ProductTemplate:
    """Return the ``magazine-digest`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "magazine-digest":
            return cast(ProductTemplate, row["template"])
    raise AssertionError(
        "magazine-digest ProductTemplate row missing from PRODUCT_TEMPLATES"
    )


def _assert_no_placeholder(text: str, domain: str, product: str) -> None:
    """Assert the rendered product passes the matrix ``_no_placeholder`` gate."""
    result = vm._no_placeholder(text, domain, product)
    assert result.passed, (
        f"placeholder residue in {product} for {domain}: {result.details!r}\n"
        f"{text[:2000]}"
    )


class TestReportDataToDictEntries:
    """``_report_data_to_dict`` carries a top-level ``entries`` list (#342)."""

    def test_entries_built_from_references_with_expected_keys(self) -> None:
        report_data = ReportData(
            title="Weekly Report — general-news",
            generated_at="2026-08-03T00:00:00+00:00",
            domain="general-news",
            executive_summary="Overview.",
            references=[
                {
                    "title": "The Quiet AI Revolution in Newsrooms",
                    "source_url": "https://www.theatlantic.com/tech/archive/2026/07/ai-newsrooms/",
                    "source_type": "rss",
                    "source_platform": "the-atlantic",
                    "domain": "general-news",
                },
                {
                    "title": "Why Wired Readers Trust Slow Journalism",
                    "source_url": "https://www.wired.com/story/slow-journalism-trust/",
                    "source_type": "rss",
                    "source_platform": "wired",
                    "domain": "general-news",
                },
            ],
        )

        flat = _report_data_to_dict(report_data)

        assert "entries" in flat, "top-level entries key missing"
        assert len(flat["entries"]) == 2
        first = flat["entries"][0]
        assert first["title"] == "The Quiet AI Revolution in Newsrooms"
        assert first["summary"] == ""
        assert first["source_url"] == (
            "https://www.theatlantic.com/tech/archive/2026/07/ai-newsrooms/"
        )
        assert first["source_type"] == "rss"
        assert first["source_platform"] == "the-atlantic"
        assert first["relevance_score"] is None
        assert first["collected_at"] == ""

    def test_report_path_magazine_renders_real_clusters(self) -> None:
        """Rendering the magazine template through the report dict shows real
        per-title clusters, never the ``_No articles found..._`` empty-state."""
        report_data = ReportData(
            title="Weekly Magazine Digest — general-news",
            generated_at="2026-08-03T00:00:00+00:00",
            domain="general-news",
            executive_summary="Overview.",
            references=[
                {
                    "title": "The Quiet AI Revolution in Newsrooms",
                    "source_url": "https://www.theatlantic.com/tech/archive/2026/07/ai-newsrooms/",
                    "source_type": "rss",
                    "source_platform": "the-atlantic",
                    "domain": "general-news",
                },
            ],
        )

        flat = _report_data_to_dict(report_data)
        out = _magazine_template().render("magazine-digest", "md", flat)

        assert "The Quiet AI Revolution in Newsrooms" in out
        assert "the-atlantic" in out
        assert "_No articles found" not in out
        _assert_no_placeholder(out, "general-news", "magazine-digest")


class TestDigestPathTutorialFill:
    """The digest path renders the tutorial template with real content (#342)."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_generate_digest_tutorial_has_objectives_and_content(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """generate_digest with the tutorial template + entries + empty LLM
        renders objectives/content derived from the entries."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="general-news",
            period="weekly",
            format="markdown",
            product_template=_tutorial_template(),
            language="en",  # explicit param: general-news gained a seed
            # default_language=zh (#28), which would filter the en fixtures.
        )

        assert isinstance(result, str)
        assert "The Quiet AI Revolution in Newsrooms" in result
        assert "## Learning Objectives" in result
        assert "## Content" in result
        assert "_No objectives defined." not in result
        assert "_No exercises provided." not in result
        assert "_No references provided." not in result
        _assert_no_placeholder(result, "general-news", "tutorial")

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_generate_digest_tutorial_zero_entries_neutral(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """A zero-entry digest-path tutorial renders neutral prose, never a
        placeholder."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.return_value = []
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="general-news",
            period="weekly",
            format="markdown",
            product_template=_tutorial_template(),
        )

        assert isinstance(result, str)
        assert "No knowledge base entr" not in result
        assert "_No " not in result
        _assert_no_placeholder(result, "general-news", "tutorial")


class TestGenerateTutorialNoPlaceholder:
    """``generate_tutorial`` never emits placeholder empty-states (#342)."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_generate_tutorial_empty_llm_result_passes_gate(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """An unusable (empty) LLM result falls back to KB-derived content."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        mock_kb.return_value = mock_store

        result = generate_tutorial(domain="general-news", format="markdown")

        assert isinstance(result, str)
        assert "The Quiet AI Revolution in Newsrooms" in result
        _assert_no_placeholder(result, "general-news", "tutorial")

    @patch("autoinfo.output.KBStore")
    def test_generate_tutorial_zero_entries_neutral(
        self, mock_kb: MagicMock,
    ) -> None:
        """The zero-entry path renders neutral prose, never a placeholder."""
        mock_store = MagicMock()
        mock_store.list_entries.return_value = []
        mock_kb.return_value = mock_store

        result = generate_tutorial(domain="general-news", format="markdown")

        assert isinstance(result, str)
        assert "No knowledge base entr" not in result
        assert "_No " not in result
        _assert_no_placeholder(result, "general-news", "tutorial")


class TestGenerateTutorialStringExercises:
    """LLM results whose ``exercises`` list carries plain strings (instead of
    dicts) must render the string as the exercise title — never Jinja's
    ``<built-in method title of str object>`` leak (backup-repo #22-#37
    matrix `_no_placeholder` P0 on gaming tutorial)."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_string_exercises_render_as_titles(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "title": "gaming — Tutorial",
            "duration": "30 minutes",
            "prerequisites": "None",
            "objectives": ["Learn about game releases"],
            "content": [{"heading": "Game releases", "body": "Body text"}],
            "exercises": [
                "What is the key finding in 'GTA 6 legal updates'?",
                {"title": "Dict exercise", "description": "dict desc"},
                42,
            ],
            "summary": "Summary text",
            "further_reading": [],
        }
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _SAMPLE_ENTRIES
        mock_kb.return_value = mock_store

        result = generate_tutorial(domain="gaming", format="markdown")

        assert isinstance(result, str)
        assert "built-in method" not in result, (
            f"Jinja method-object leaked into tutorial render:\n{result[:1500]}"
        )
        # string exercises render their content as the exercise title
        assert "What is the key finding" in result
        _assert_no_placeholder(result, "gaming", "tutorial")
