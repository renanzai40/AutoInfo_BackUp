"""Tests for the 3-layer product quality guardrail (issue #298) + the MCP
digest/report false-noop gate (issue #10).

Covers:
- ``_filter_product_entries`` — drops empty / test / placeholder entries
- Default delivery-gate config resolution from the domain config
- ``generate_tutorial`` / ``generate_presentation`` accept ``delivery_gate_configs``
- D1 completeness on the RENDERED body (not just the synthesis dict)
- Min-content guard: zero usable entries -> flagged/blocked output
- MCP digest/report preview gate: the staleness fallback must not be suppressed
- LLM product judge: stub judge -> retry/block behavior
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.config import Config, DeliveryGateConfig, DomainConfig
from autoinfo.output import (
    DeliveryOutput,
    _apply_delivery_gates,
    _filter_product_entries,
    _resolve_delivery_gate_configs,
    generate_digest,
    generate_presentation,
    generate_report,
    generate_tutorial,
)

# ---------------------------------------------------------------------------
# Sample entries
# ---------------------------------------------------------------------------

_REAL_ENTRY: dict[str, Any] = {
    "entry_id": "real-001",
    "title": "Improved IVF outcomes with time-lapse embryo imaging",
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

_REAL_ENTRY_2: dict[str, Any] = {
    "entry_id": "real-002",
    "title": "AI-driven embryo selection: a systematic review",
    "domain": "medical-research",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
    "source_type": "api",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=2)).isoformat(),
    "summary": "AI models show promise but lack prospective validation.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 85.0,
}

_EMPTY_ENTRY: dict[str, Any] = {
    "entry_id": "empty-001",
    "title": "   ",
    "summary": "",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/11111111/",
    "source_platform": "pubmed",
}

_TEST_URL_ENTRY: dict[str, Any] = {
    "entry_id": "test-url-001",
    "title": "Some realistic-looking title",
    "summary": "Some summary",
    "source_url": "https://example.org/test-article",
    "source_platform": "pubmed",
}

_TEST_ORG_URL_ENTRY: dict[str, Any] = {
    "entry_id": "test-org-001",
    "title": "Another realistic-looking title",
    "summary": "Another summary",
    "source_url": "https://example.org/placeholder",
    "source_platform": "pubmed",
}

_TEST_TITLE_ENTRY: dict[str, Any] = {
    "entry_id": "test-title-001",
    "title": "Get Test",
    "summary": "Some summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/22222222/",
    "source_platform": "pubmed",
}

_ENTRY_A_ENTRY: dict[str, Any] = {
    "entry_id": "entry-a-001",
    "title": "Entry A",
    "summary": "Some summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/33333333/",
    "source_platform": "pubmed",
}

_PARITY_ENTRY: dict[str, Any] = {
    "entry_id": "parity-001",
    "title": "parity-t1",
    "summary": "Some summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/44444444/",
    "source_platform": "pubmed",
}

_VALIDATION_IMPORT_ENTRY: dict[str, Any] = {
    "entry_id": "vi-001",
    "title": "validation import fixture",
    "summary": "Some summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/55555555/",
    "source_platform": "pubmed",
}

_CUSTOM_FIELD_TEST_ENTRY: dict[str, Any] = {
    "entry_id": "cf-test-001",
    "title": "Real title with test flag",
    "summary": "Real summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/66666666/",
    "source_platform": "pubmed",
    "custom_fields": json.dumps({"test": True}),
}

_STATUS_TEST_ENTRY: dict[str, Any] = {
    "entry_id": "status-test-001",
    "title": "Real title with test status",
    "summary": "Real summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/77777777/",
    "source_platform": "pubmed",
    "custom_fields": json.dumps({"status": "test"}),
}

_TEST_PLATFORM_ENTRY: dict[str, Any] = {
    "entry_id": "platform-test-001",
    "title": "Real title from a test fixture platform",
    "summary": "Real summary",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/88888888/",
    "source_platform": "test-fixture",
}

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's key developments focus on IVF technology advancements "
        "including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": "Significant improvement in live birth rates in a large RCT.",
        },
        {
            "topic": "AI embryo selection",
            "detail": "Promising but lacks prospective clinical validation.",
        },
    ],
    "trends": [
        "Increasing integration of AI/ML in reproductive medicine",
        "Growing evidence for time-lapse imaging benefits",
    ],
    "recommendations": [
        "Consider time-lapse imaging as standard of care",
        "Support prospective AI validation trials",
    ],
}

_TUTORIAL_RESULT: dict[str, Any] = {
    "title": "IVF Technology — Tutorial",
    "duration": "45 minutes",
    "prerequisites": "Basic biology knowledge",
    "objectives": [
        "Understand time-lapse imaging fundamentals",
        "Apply AI-driven embryo selection concepts",
    ],
    "content": [
        {
            "heading": "Introduction to Time-Lapse Imaging",
            "body": "Time-lapse imaging leverages continuous embryo monitoring.",
        },
        {
            "heading": "AI in Embryo Selection",
            "body": "AI models show promise but lack prospective validation.",
        },
    ],
    "exercises": [
        {
            "title": "Key finding recap",
            "description": "Summarize the main finding of the time-lapse study.",
        },
    ],
    "summary": "This tutorial covers IVF technology in medical research.",
    "further_reading": ["Time-Lapse Imaging Review", "AI Embryo Selection Survey"],
}

_PRESENTATION_RESULT: dict[str, Any] = {
    "title": "IVF Technology — Presentation",
    "description": "Overview of IVF technology advancements in medical research.",
    "slides": [
        {
            "title": "Title Slide",
            "content": "IVF Technology in Medicine",
            "bullets": ["Time-lapse imaging", "AI embryo selection", "Clinical trials"],
            "notes": "Welcome slide",
        },
        {
            "title": "Time-Lapse Imaging",
            "content": "Continuous embryo monitoring improves live birth rates.",
            "bullets": ["48.2% vs 39.5% live birth", "Large randomized trial", "Standard of care"],
            "notes": None,
        },
        {
            "title": "AI Embryo Selection",
            "content": "AI models show promise but lack prospective validation.",
            "bullets": ["Systematic review", "Promising results", "Needs validation"],
            "notes": None,
        },
        {
            "title": "Recommendations",
            "content": "Adopt time-lapse imaging and support AI validation trials.",
            "bullets": ["Standard of care", "Prospective trials", "Registry data"],
            "notes": None,
        },
        {
            "title": "Conclusion",
            "content": "IVF technology is advancing rapidly with measurable gains.",
            "bullets": ["Time-lapse imaging", "AI selection", "Future directions"],
            "notes": None,
        },
    ],
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return real entries, or empty for 'empty-domain'."""
    if domain == "empty-domain":
        return []
    return [_REAL_ENTRY, _REAL_ENTRY_2]


# ---------------------------------------------------------------------------
# _filter_product_entries
# ---------------------------------------------------------------------------


class TestFilterProductEntries:
    def test_mixed_list_yields_only_real_entries(self) -> None:
        """A mixed list (real + empty + test) yields only the real entries."""
        mixed = [
            _REAL_ENTRY,
            _EMPTY_ENTRY,
            _TEST_URL_ENTRY,
            _TEST_TITLE_ENTRY,
            _REAL_ENTRY_2,
        ]
        result = _filter_product_entries(mixed)
        assert [e["entry_id"] for e in result] == ["real-001", "real-002"]

    def test_drops_empty_title_and_summary(self) -> None:
        result = _filter_product_entries([_EMPTY_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_drops_example_dot_org_url(self) -> None:
        result = _filter_product_entries([_TEST_ORG_URL_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_keeps_example_dot_com_url(self) -> None:
        """example.com was relaxed out of the URL markers (9b0bf13) — the RFC
        2606 reserved domain is used by legitimate fixtures, so an entry whose
        only test signal is example.com must be kept."""
        entry = dict(_TEST_URL_ENTRY)
        entry["entry_id"] = "example-com-001"
        entry["source_url"] = "https://example.com/test-article"
        result = _filter_product_entries([entry, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["example-com-001", "real-001"]

    def test_drops_test_titles(self) -> None:
        result = _filter_product_entries(
            [_TEST_TITLE_ENTRY, _ENTRY_A_ENTRY, _PARITY_ENTRY, _REAL_ENTRY]
        )
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_drops_validation_import_title(self) -> None:
        result = _filter_product_entries([_VALIDATION_IMPORT_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_drops_custom_field_test_flag(self) -> None:
        result = _filter_product_entries([_CUSTOM_FIELD_TEST_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_drops_status_test(self) -> None:
        result = _filter_product_entries([_STATUS_TEST_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_drops_test_source_platform(self) -> None:
        result = _filter_product_entries([_TEST_PLATFORM_ENTRY, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_handles_custom_fields_as_dict(self) -> None:
        entry = dict(_CUSTOM_FIELD_TEST_ENTRY)
        entry["custom_fields"] = {"test": True}
        result = _filter_product_entries([entry, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]

    def test_handles_missing_fields(self) -> None:
        result = _filter_product_entries([{"entry_id": "bare"}, _REAL_ENTRY])
        assert [e["entry_id"] for e in result] == ["real-001"]


# ---------------------------------------------------------------------------
# Delivery-gate config resolution
# ---------------------------------------------------------------------------


class TestDeliveryGateConfigResolution:
    def test_resolve_from_domain_config(self) -> None:
        cfg = Config()
        cfg.domains = [
            DomainConfig(
                name="medical-research",
                delivery_gates={
                    "D1": DeliveryGateConfig(
                        name="D1", enabled=True, action_on_failure="block"
                    ),
                },
            )
        ]
        with (
            patch(
                "autoinfo.output.get_config_path",
                return_value=Path("/tmp/fake/config.yaml"),
            ),
            patch("autoinfo.output.load_config", return_value=cfg),
        ):
            resolved = _resolve_delivery_gate_configs("medical-research", None)
        assert resolved == {"D1": {"enabled": True, "action_on_failure": "block"}}

    def test_resolve_falls_back_to_global_config(self) -> None:
        cfg = Config()
        cfg.delivery_gates = {
            "D2": DeliveryGateConfig(
                name="D2", enabled=True, action_on_failure="fallback"
            ),
        }
        with (
            patch(
                "autoinfo.output.get_config_path",
                return_value=Path("/tmp/fake/config.yaml"),
            ),
            patch("autoinfo.output.load_config", return_value=cfg),
        ):
            resolved = _resolve_delivery_gate_configs("medical-research", None)
        assert resolved == {"D2": {"enabled": True, "action_on_failure": "fallback"}}

    def test_resolve_none_when_no_config(self) -> None:
        with patch("autoinfo.output.get_config_path", return_value=None):
            assert _resolve_delivery_gate_configs("medical-research", None) is None

    def test_explicit_config_wins(self) -> None:
        explicit = {"D1": {"action": "block"}}
        assert _resolve_delivery_gate_configs("medical-research", explicit) is explicit

    def test_bypass_sentinel_returns_none(self) -> None:
        from autoinfo.output import _DELIVERY_GATES_BYPASS

        assert _resolve_delivery_gate_configs("medical-research", _DELIVERY_GATES_BYPASS) is None

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_resolves_delivery_gates_from_domain_config(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """Default generate_digest resolves delivery-gate config from the domain
        config when present -> returns DeliveryOutput with populated gate_results."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        cfg = Config()
        cfg.domains = [
            DomainConfig(
                name="medical-research",
                delivery_gates={
                    "D1": DeliveryGateConfig(
                        name="D1", enabled=True, action_on_failure="block"
                    ),
                },
            )
        ]
        with (
            patch(
                "autoinfo.output.get_config_path",
                return_value=Path("/tmp/fake/config.yaml"),
            ),
            patch("autoinfo.output.load_config", return_value=cfg),
        ):
            result = generate_digest(
                domain="medical-research", period="weekly", format="json"
            )

        assert isinstance(result, DeliveryOutput)
        assert "D1-ProductCompleteness" in result.gate_results
        assert result.gate_results["D1-ProductCompleteness"].passed is True

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_report_synthesis")
    @patch("autoinfo.output._llm_json_extract")
    def test_report_resolves_delivery_gates_from_domain_config(
        self,
        mock_extract: MagicMock,
        mock_synthesis: MagicMock,
        mock_kb: MagicMock,
    ) -> None:
        """Default generate_report resolves delivery-gate config from the domain
        config when present -> returns DeliveryOutput with populated gate_results."""
        mock_synthesis.return_value = "Executive summary for the report."
        mock_extract.side_effect = (
            lambda extractor, prompt, field: (
                [{"theme": "General", "description": "All entries", "entry_ids": ["real-001"]}]
                if field == "groups"
                else "Executive summary for the report."
            )
        )
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY, _REAL_ENTRY_2]
        mock_kb.return_value = mock_store

        cfg = Config()
        cfg.domains = [
            DomainConfig(
                name="medical-research",
                delivery_gates={
                    "D1": DeliveryGateConfig(
                        name="D1", enabled=True, action_on_failure="block"
                    ),
                },
            )
        ]
        with (
            patch(
                "autoinfo.output.get_config_path",
                return_value=Path("/tmp/fake/config.yaml"),
            ),
            patch("autoinfo.output.load_config", return_value=cfg),
        ):
            result = generate_report(
                domain="medical-research", format="markdown", period="weekly"
            )

        assert isinstance(result, DeliveryOutput)
        assert "D1-ProductCompleteness" in result.gate_results

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_digest_no_config_returns_str(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """When config resolution yields nothing, generate_digest returns a plain str."""
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb.return_value = mock_store

        with patch("autoinfo.output.get_config_path", return_value=None):
            result = generate_digest(domain="medical-research", period="weekly")

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# generate_tutorial / generate_presentation accept delivery_gate_configs
# ---------------------------------------------------------------------------


class TestTutorialPresentationDeliveryGates:
    @patch("autoinfo.output._llm_key_available", return_value=False)
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_tutorial_accepts_delivery_gate_configs(
        self, mock_llm: MagicMock, mock_kb: MagicMock, mock_key: MagicMock
    ) -> None:
        """generate_tutorial accepts delivery_gate_configs and runs D-gates."""
        mock_llm.return_value = _TUTORIAL_RESULT
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY, _REAL_ENTRY_2]
        mock_kb.return_value = mock_store

        result = generate_tutorial(
            domain="medical-research",
            target_audience="student",
            format="markdown",
            delivery_gate_configs={"D1": {"action": "block"}},
        )

        assert isinstance(result, DeliveryOutput)
        assert "D1-ProductCompleteness" in result.gate_results
        assert result.gate_results["D1-ProductCompleteness"].passed is True

    @patch("autoinfo.output._llm_key_available", return_value=False)
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_presentation")
    def test_presentation_accepts_delivery_gate_configs(
        self, mock_llm: MagicMock, mock_kb: MagicMock, mock_key: MagicMock
    ) -> None:
        """generate_presentation accepts delivery_gate_configs and runs D-gates."""
        mock_llm.return_value = _PRESENTATION_RESULT
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_REAL_ENTRY, _REAL_ENTRY_2]
        mock_kb.return_value = mock_store

        result = generate_presentation(
            domain="medical-research",
            topic="IVF",
            format="markdown",
            delivery_gate_configs={"D1": {"action": "block"}},
        )

        assert isinstance(result, DeliveryOutput)
        assert "D1-ProductCompleteness" in result.gate_results


# ---------------------------------------------------------------------------
# D1 on the rendered body
# ---------------------------------------------------------------------------


class TestD1OnRenderedBody:
    def test_d1_blocks_on_rendered_body_with_empty_required_section(self) -> None:
        """D1 must fail when a required section is empty in the RENDERED body,
        even if the synthesis dict would be non-empty."""
        body = (
            "# Test Report\n\n"
            "## Executive Summary\n\n"
            "A real executive summary with enough content to be non-trivial.\n\n"
            "## Key Findings\n\n"
            "## Recommendations\n\n"
            "A real recommendation with enough content to be non-trivial.\n"
        )
        result = _apply_delivery_gates(
            rendered_output=body,
            output_format="markdown",
            entries=[_REAL_ENTRY],
            context={"llm_synthesis": _SAMPLE_LLM_SYNTHESIS},
            product_type="PROCESSED",
            delivery_gate_configs={"D1": {"action": "block"}},
        )

        assert result.delivery_blocked is True
        d1 = result.gate_results.get("D1-ProductCompleteness")
        assert d1 is not None
        assert d1.passed is False

    @patch("autoinfo.output._llm_key_available", return_value=False)
    def test_d1_passes_on_complete_rendered_body(self, mock_key: MagicMock) -> None:
        """D1 passes when all required sections are non-empty in the body."""
        body = (
            "# Test Report\n\n"
            "## Executive Summary\n\n"
            "A real executive summary with enough content to be non-trivial.\n\n"
            "## Key Findings\n\n"
            "A real key finding with enough content to be non-trivial.\n\n"
            "## Recommendations\n\n"
            "A real recommendation with enough content to be non-trivial.\n"
        )
        result = _apply_delivery_gates(
            rendered_output=body,
            output_format="markdown",
            entries=[_REAL_ENTRY],
            context={},
            product_type="PROCESSED",
            delivery_gate_configs={"D1": {"action": "block"}},
        )

        assert result.delivery_blocked is False
        d1 = result.gate_results.get("D1-ProductCompleteness")
        assert d1 is not None
        assert d1.passed is True


# ---------------------------------------------------------------------------
# Min-content guard
# ---------------------------------------------------------------------------


class TestMinContentGuard:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_min_content_guard_blocks_all_test_entries(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """A product whose entries are ALL test/placeholder entries is blocked,
        not silently shipped as an empty shell."""
        mock_llm.return_value = {}
        mock_store = MagicMock()
        mock_store.list_entries.return_value = [_TEST_URL_ENTRY, _TEST_TITLE_ENTRY]
        mock_kb.return_value = mock_store

        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            delivery_gate_configs={"D1": {"action": "block"}},
        )

        assert isinstance(result, DeliveryOutput)
        assert result.delivery_blocked is True
        assert any("min-content guard" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# MCP digest/report false-noop gate (issue #10)
# ---------------------------------------------------------------------------


class TestMcpFalseNoopGate:
    def test_digest_handler_not_noop_when_stale_fallback_would_produce_content(
        self,
    ) -> None:
        """With entries only OUTSIDE the period window, _handle_generate_digest
        must return content (matching generate_digest's staleness fallback),
        not a false 'noop'."""
        from autoinfo.mcp.server import _handle_generate_digest

        def _side_effect(**kwargs: Any) -> list[dict[str, Any]]:
            if "date_from" in kwargs:
                return []  # no entries in the period window
            return [_REAL_ENTRY]  # entries exist in the full domain set

        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _side_effect
        with (
            patch("autoinfo.kb.KBStore", return_value=mock_store),
            patch(
                "autoinfo.output.generate_digest",
                return_value="# Weekly Digest -- test\n\ncontent",
            ),
        ):
            result = _handle_generate_digest(
                domain="medical-research", period="weekly", format="markdown"
            )

        assert result["success"] is True
        assert result.get("status") != "noop"
        assert "# Weekly Digest" in result["content"]

    def test_report_handler_not_noop_when_stale_fallback_would_produce_content(
        self,
    ) -> None:
        """Same false-noop protection for _handle_generate_report."""
        from autoinfo.mcp.server import _handle_generate_report

        def _side_effect(**kwargs: Any) -> list[dict[str, Any]]:
            if "date_from" in kwargs:
                return []
            return [_REAL_ENTRY]

        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _side_effect
        with (
            patch("autoinfo.kb.KBStore", return_value=mock_store),
            patch(
                "autoinfo.output.generate_report",
                return_value="# Monthly Report -- test\n\ncontent",
            ),
        ):
            result = _handle_generate_report(
                domain="medical-research", period="monthly", format="markdown"
            )

        assert result["success"] is True
        assert result.get("status") != "noop"
        assert "# Monthly Report" in result["content"]

    def test_digest_handler_still_noop_when_domain_has_no_entries(self) -> None:
        """When the domain genuinely has NO entries at all, 'noop' is preserved."""
        from autoinfo.mcp.server import _handle_generate_digest

        mock_store = MagicMock()
        mock_store.list_entries.return_value = []
        with (
            patch("autoinfo.kb.KBStore", return_value=mock_store),
            patch("autoinfo.output.generate_digest"),
        ):
            result = _handle_generate_digest(
                domain="medical-research", period="weekly", format="markdown"
            )

        assert result.get("status") == "noop"


# ---------------------------------------------------------------------------
# LLM product judge
# ---------------------------------------------------------------------------


class TestProductJudge:
    def _complete_body(self) -> str:
        return (
            "# Test Report\n\n"
            "## Executive Summary\n\n"
            "A real executive summary with enough content to be non-trivial.\n\n"
            "## Key Findings\n\n"
            "A real key finding with enough content to be non-trivial.\n\n"
            "## Recommendations\n\n"
            "A real recommendation with enough content to be non-trivial.\n"
        )

    def test_judge_blocks_on_bad_body(self) -> None:
        """A stub judge reporting a bad body blocks delivery."""
        with (
            patch("autoinfo.output._llm_key_available", return_value=True),
            patch(
                "autoinfo.output.call_with_fallback",
                return_value=json.dumps({"ok": False, "reason": "body is garbled"}),
            ),
        ):
            result = _apply_delivery_gates(
                rendered_output=self._complete_body(),
                output_format="markdown",
                entries=[_REAL_ENTRY],
                context={},
                product_type="PROCESSED",
                delivery_gate_configs={"D1": {"action": "block"}},
            )

        assert result.delivery_blocked is True
        assert any("product judge" in w for w in result.warnings)

    def test_judge_retries_once_then_blocks(self) -> None:
        """The judge retries once with escalating context before blocking."""
        with (
            patch("autoinfo.output._llm_key_available", return_value=True),
            patch(
                "autoinfo.output.call_with_fallback",
                side_effect=[
                    json.dumps({"ok": False, "reason": "garbled"}),
                    json.dumps({"ok": False, "reason": "still garbled"}),
                ],
            ) as mock_call,
        ):
            result = _apply_delivery_gates(
                rendered_output=self._complete_body(),
                output_format="markdown",
                entries=[_REAL_ENTRY],
                context={},
                product_type="PROCESSED",
                delivery_gate_configs={"D1": {"action": "block"}},
            )

        assert result.delivery_blocked is True
        assert mock_call.call_count == 2

    def test_judge_passes_on_good_body(self) -> None:
        """A stub judge reporting a good body does not block."""
        with (
            patch("autoinfo.output._llm_key_available", return_value=True),
            patch(
                "autoinfo.output.call_with_fallback",
                return_value=json.dumps({"ok": True, "reason": ""}),
            ),
        ):
            result = _apply_delivery_gates(
                rendered_output=self._complete_body(),
                output_format="markdown",
                entries=[_REAL_ENTRY],
                context={},
                product_type="PROCESSED",
                delivery_gate_configs={"D1": {"action": "block"}},
            )

        assert result.delivery_blocked is False
