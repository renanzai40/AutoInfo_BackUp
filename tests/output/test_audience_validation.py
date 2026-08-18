"""Tests for issue #297: audience validation inconsistency.

All four generators (report, digest, tutorial, presentation) must raise
``ValueError`` for invalid audience values and accept valid ones.
Previously, report/digest silently fell back to "general" while
tutorial/presentation raised — hiding user typos.

TDD: these tests should fail (RED) before the fix, pass (GREEN) after.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import (
    _VALID_AUDIENCES,
    generate_digest,
    generate_presentation,
    generate_report,
    generate_tutorial,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_AUDIENCE_LIST = sorted(_VALID_AUDIENCES)
_INVALID_AUDIENCES = ["investors", "general-public", "bogus", "xyzzy"]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": "IVF outcomes improve with time-lapse imaging.",
    "key_findings": [{"text": "Time-lapse improves birth rates.", "source_url": ""}],
    "recommendations": ["Expand access."],
    "trends": ["Growing adoption."],
}

_REAL_ENTRY: dict[str, Any] = {
    "entry_id": "real-001",
    "title": "IVF time-lapse imaging improves live birth rates",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Time-lapse imaging improves live birth rates (48.2% vs 39.5%).",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 92.0,
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if domain == "empty-domain":
        return []
    return [_REAL_ENTRY]


# ---------------------------------------------------------------------------
# Test: _normalize_report_audience raises on invalid input
# ---------------------------------------------------------------------------


class TestNormalizeReportAudience:
    """_normalize_report_audience must raise ValueError for invalid audiences."""

    def test_empty_string_resolves_to_general(self) -> None:
        from autoinfo.output import _normalize_report_audience

        assert _normalize_report_audience("") == "general"

    def test_valid_audiences_pass(self) -> None:
        from autoinfo.output import _normalize_report_audience

        for aud in _VALID_AUDIENCE_LIST:
            assert _normalize_report_audience(aud) == aud

    def test_invalid_audience_raises(self) -> None:
        from autoinfo.output import _normalize_report_audience

        with pytest.raises(ValueError, match="Invalid target_audience"):
            _normalize_report_audience("bogus")

    def test_invalid_message_names_value(self) -> None:
        from autoinfo.output import _normalize_report_audience

        with pytest.raises(ValueError, match="'investors'"):
            _normalize_report_audience("investors")

    def test_invalid_message_lists_valid_options(self) -> None:
        from autoinfo.output import _normalize_report_audience

        with pytest.raises(ValueError) as exc_info:
            _normalize_report_audience("bogus")
        msg = str(exc_info.value)
        for aud in _VALID_AUDIENCE_LIST:
            assert aud in msg


# ---------------------------------------------------------------------------
# Test: generate_report raises on invalid audience
# ---------------------------------------------------------------------------


class TestReportAudienceValidation:
    """generate_report must raise ValueError for invalid audience."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_valid_audience_passes(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda ext, prompt, field: (
                [{"theme": "General", "description": "All", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY]
        mock_kb.return_value = mock_store

        for aud in _VALID_AUDIENCE_LIST:
            result = generate_report(
                domain="medical-research",
                period="weekly",
                format="markdown",
                target_audience=aud,
            )
            assert hasattr(result, "output") or isinstance(result, str)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_invalid_audience_raises(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda ext, prompt, field: (
                [{"theme": "General", "description": "All", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY]
        mock_kb.return_value = mock_store

        for invalid in _INVALID_AUDIENCES:
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_report(
                    domain="medical-research",
                    period="weekly",
                    format="markdown",
                    target_audience=invalid,
                )

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_invalid_message_lists_valid_options(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        mock_synthesis.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda ext, prompt, field: (
                [{"theme": "General", "description": "All", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Summary."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY]
        mock_kb.return_value = mock_store

        with pytest.raises(ValueError) as exc_info:
            generate_report(
                domain="medical-research",
                period="weekly",
                format="markdown",
                target_audience="bogus",
            )
        msg = str(exc_info.value)
        for aud in _VALID_AUDIENCE_LIST:
            assert aud in msg


# ---------------------------------------------------------------------------
# Test: generate_digest raises on invalid audience
# ---------------------------------------------------------------------------


class TestDigestAudienceValidation:
    """generate_digest must raise ValueError for invalid audience."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_valid_audience_passes(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for aud in _VALID_AUDIENCE_LIST:
            result = generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                target_audience=aud,
            )
            assert hasattr(result, "output") or isinstance(result, str)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_invalid_audience_raises(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for invalid in _INVALID_AUDIENCES:
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_digest(
                    domain="medical-research",
                    period="weekly",
                    format="markdown",
                    target_audience=invalid,
                )

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_invalid_message_lists_valid_options(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        with pytest.raises(ValueError) as exc_info:
            generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                target_audience="bogus",
            )
        msg = str(exc_info.value)
        for aud in _VALID_AUDIENCE_LIST:
            assert aud in msg


# ---------------------------------------------------------------------------
# Test: generate_tutorial raises on invalid audience (already works)
# ---------------------------------------------------------------------------


class TestTutorialAudienceValidation:
    """generate_tutorial must raise ValueError for invalid audience."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_valid_audience_passes(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "learning_objectives": ["Understand IVF basics."],
            "sections": [{"title": "Introduction", "content": "IVF overview."}],
            "exercises": [{"question": "What is IVF?", "answer": "In vitro fertilization."}],
        }
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for aud in _VALID_AUDIENCE_LIST:
            result = generate_tutorial(
                domain="medical-research",
                format="markdown",
                target_audience=aud,
            )
            assert hasattr(result, "output") or isinstance(result, str)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_invalid_audience_raises(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "learning_objectives": ["Understand IVF basics."],
            "sections": [{"title": "Introduction", "content": "IVF overview."}],
            "exercises": [{"question": "What is IVF?", "answer": "In vitro fertilization."}],
        }
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for invalid in _INVALID_AUDIENCES:
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_tutorial(
                    domain="medical-research",
                    format="markdown",
                    target_audience=invalid,
                )


# ---------------------------------------------------------------------------
# Test: generate_presentation raises on invalid audience (already works)
# ---------------------------------------------------------------------------


class TestPresentationAudienceValidation:
    """generate_presentation must raise ValueError for invalid audience."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_valid_audience_passes(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "title": "IVF Overview",
            "slides": [
                {
                    "title": "Introduction",
                    "content": "IVF is a technique for assisting reproduction. " * 20,
                },
                {
                    "title": "Key Findings",
                    "content": "AI improves embryo selection accuracy significantly. " * 20,
                },
                {
                    "title": "Conclusion",
                    "content": (
                        "Time-lapse imaging combined with AI shows promise "
                        "for IVF outcomes. " * 20
                    ),
                },
            ],
        }
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for aud in _VALID_AUDIENCE_LIST:
            result = generate_presentation(
                domain="medical-research",
                topic="IVF",
                format="markdown",
                target_audience=aud,
            )
            assert hasattr(result, "output") or isinstance(result, str)

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_invalid_audience_raises(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "title": "IVF Overview",
            "slides": [
                {"title": "Introduction", "content": "IVF basics."},
                {"title": "Key Findings", "content": "AI improves outcomes."},
            ],
        }
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for invalid in _INVALID_AUDIENCES:
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_presentation(
                    domain="medical-research",
                    topic="IVF",
                    format="markdown",
                    target_audience=invalid,
                )


# ---------------------------------------------------------------------------
# Test: consistency contract — any invalid value raises in ALL four
# ---------------------------------------------------------------------------


class TestAudienceConsistencyContract:
    """Any invalid audience value must raise in ALL four generators."""

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    @patch("autoinfo.output._call_llm_for_digest")
    @patch("autoinfo.output._call_llm_for_tutorial")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_invalid_raises_in_all_generators(
        self,
        mock_pres: MagicMock,
        mock_tut: MagicMock,
        mock_digest_llm: MagicMock,
        mock_extract: MagicMock,
        mock_synth: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        """One invalid value raises in all four generators."""
        # Set up mocks for all generators
        mock_synth.return_value = "Executive summary."
        mock_extract.side_effect = (
            lambda ext, prompt, field: (
                [{"theme": "General", "description": "All", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Summary."
            )
        )
        mock_digest_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_tut.return_value = {
            "learning_objectives": ["Learn."],
            "sections": [{"title": "Intro", "content": "Content."}],
            "exercises": [],
        }
        mock_pres.return_value = {
            "title": "Slides",
            "slides": [{"title": "S1", "content": "C1"}],
        }
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        for invalid in _INVALID_AUDIENCES:
            # report
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_report(
                    domain="medical-research", period="weekly",
                    format="markdown", target_audience=invalid,
                )
            # digest
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_digest(
                    domain="medical-research", period="weekly",
                    format="markdown", target_audience=invalid,
                )
            # tutorial
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_tutorial(
                    domain="medical-research",
                    format="markdown", target_audience=invalid,
                )
            # presentation
            with pytest.raises(ValueError, match="Invalid target_audience"):
                generate_presentation(
                    domain="medical-research", topic="IVF",
                    format="markdown", target_audience=invalid,
                )
