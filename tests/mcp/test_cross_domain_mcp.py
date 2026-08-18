"""Tests for the ``generate_cross_domain_report`` MCP tool.

Covers:
    - Tool registration in ``list_tools()``
    - Validation: at least 2 domains required
    - Validation: unknown domains rejected
    - Correct delegation to ``generate_report(domains=...)``
    - Correct dispatch via ``call_tool("generate_cross_domain_report", ...)``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import TextContent, Tool

from autoinfo.mcp.server import (
    _handle_generate_cross_domain_report,
    call_tool,
    list_tools,
)

# ======================================================================
# Tool registration
# ======================================================================


class TestToolRegistration:
    """Verify ``generate_cross_domain_report`` appears in the tool list."""

    async def test_tool_exists(self) -> None:
        tools: list[Tool] = await list_tools()
        names = [t.name for t in tools]
        assert "generate_cross_domain_report" in names

    async def test_tool_schema(self) -> None:
        tools: list[Tool] = await list_tools()
        tool = next(
            t for t in tools if t.name == "generate_cross_domain_report"
        )
        schema = tool.inputSchema
        properties = schema.get("properties", {})

        assert "domains" in properties
        assert properties["domains"]["type"] == "array"
        assert properties["domains"]["items"]["type"] == "string"
        assert "format" in properties
        assert "period" in properties
        assert "target_audience" in properties
        assert "report_type" in properties
        assert schema["required"] == ["domains"]


# ======================================================================
# Validation: domain checks
# ======================================================================


class TestValidation:
    """Domain validation and error handling."""

    def test_rejects_less_than_2_domains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_generate_cross_domain_report(
            domains=["medical-research"]
        )
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"
        assert "At least 2 domains" in result["message"]

    def test_rejects_empty_domains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_generate_cross_domain_report(domains=[])
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"

    def test_rejects_unknown_domain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # Initialize project so config exists
        _handle_init_project_direct(tmp_path, monkeypatch)
        result = _handle_generate_cross_domain_report(
            domains=["medical-research", "nonexistent-xyz"]
        )
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"
        assert "Unknown domain(s)" in result["message"]
        assert "nonexistent-xyz" in result["message"]


# ======================================================================
# Delegation to generate_report(domains=...)
# ======================================================================


class TestDelegation:
    """Handler must delegate to ``generate_report(domains=...)`` correctly."""

    def test_calls_generate_report_with_domains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        # Create a mock config with both domains
        mock_domain_a = MagicMock()
        mock_domain_a.name = "medical-research"
        mock_domain_a.active = True
        mock_domain_b = MagicMock()
        mock_domain_b.name = "ai-commercial"
        mock_domain_b.active = True
        mock_config = MagicMock()
        mock_config.domains = [mock_domain_a, mock_domain_b]

        with patch("autoinfo.mcp.server._load_config", return_value=mock_config):
            with patch(
                "autoinfo.output.generate_report", autospec=True
            ) as mock_gen:
                mock_gen.return_value = (
                    "# Cross-Domain Report\n\n## executive summary\n\nTest."
                )
                result = _handle_generate_cross_domain_report(
                    domains=["medical-research", "ai-commercial"],
                    format="markdown",
                    period="monthly",
                    target_audience="researchers",
                    report_type="trend",
                )

        # Verify delegation arguments
        mock_gen.assert_called_once_with(
            domain="medical-research",
            domains=["medical-research", "ai-commercial"],
            format="markdown",
            period="monthly",
            target_audience="researchers",
            report_type="trend",
            user_id="",
            language="",
        )

        # Verify result structure
        assert result["success"] is True
        assert result["domain"] == "medical-research"
        assert result["domains"] == ["medical-research", "ai-commercial"]
        assert result["format"] == "markdown"
        assert result["period"] == "monthly"
        assert result["content"] == mock_gen.return_value

    async def test_dispatches_via_call_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        # Create a mock config with both domains
        mock_domain_a = MagicMock()
        mock_domain_a.name = "medical-research"
        mock_domain_a.active = True
        mock_domain_b = MagicMock()
        mock_domain_b.name = "ai-commercial"
        mock_domain_b.active = True
        mock_config = MagicMock()
        mock_config.domains = [mock_domain_a, mock_domain_b]

        with patch("autoinfo.mcp.server._load_config", return_value=mock_config):
            with patch(
                "autoinfo.output.generate_report", autospec=True
            ) as mock_gen:
                mock_gen.return_value = (
                    "# Cross-Domain Report\n\n## executive summary\n\nTest via dispatch."
                )

                # generate_cross_domain_report is LLM-required; the guard in
                # call_tool reads the real config, not the mock above — patch
                # _is_llm_configured so the guard passes.
                with patch(
                    "autoinfo.mcp.server._is_llm_configured", return_value=True
                ):
                    result_list = await call_tool(
                        "generate_cross_domain_report",
                        {
                            "domains": ["medical-research", "ai-commercial"],
                            "format": "markdown",
                            "period": "week",
                            "report_type": "standard",
                        },
                    )

        assert len(result_list) == 1
        assert isinstance(result_list[0], TextContent)
        body = json.loads(result_list[0].text)
        assert body["success"] is True
        assert body["domain"] == "medical-research"
        assert body["domains"] == ["medical-research", "ai-commercial"]
        assert body["content"] == mock_gen.return_value


# ======================================================================
# Helpers
# ======================================================================


def _handle_init_project_direct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Initialize the project in tmp_path so domain config exists."""
    monkeypatch.chdir(tmp_path)
    from autoinfo.mcp.server import _handle_init_project

    result = _handle_init_project(domain="medical-research")
    assert result["status"] == "success"
    return result
