"""Tests for the doctor CLI LLM hint (GitHub issue #110)."""

from typing import Any

import pytest

from autoinfo.cli.doctor import _print_human


def _result_with_llm_unconfigured() -> dict[str, Any]:
    return {
        "python": {"status": "ok", "version": "3.11.0"},
        "config": {"status": "ok", "path": ".autoinfo/config.yaml"},
        "llm": {
            "status": "error",
            "provider": "openai",
            "model": "gpt-4",
            "key_configured": False,
        },
        "sources": [],
    }


def test_doctor_llm_hint_points_to_mcp_tool(capsys: pytest.CaptureFixture[str]) -> None:
    """The LLM-not-configured hint must mention the real configure_llm() MCP tool.

    Regression: doctor.py used to print "Agent: call configure_llm(...)" which
    is meaningless for CLI users (no `autoinfo configure_llm` command exists).
    """
    _print_human(_result_with_llm_unconfigured())
    out = capsys.readouterr().out
    assert "MCP tool configure_llm()" in out


def test_doctor_llm_hint_mentions_env_var(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI users must be directed to the AUTOINFO_LLM_API_KEY env var."""
    _print_human(_result_with_llm_unconfigured())
    out = capsys.readouterr().out
    assert "AUTOINFO_LLM_API_KEY" in out


def test_doctor_llm_hint_keeps_docs_reference(capsys: pytest.CaptureFixture[str]) -> None:
    """The required-api-keys docs reference must remain."""
    _print_human(_result_with_llm_unconfigured())
    out = capsys.readouterr().out
    assert "docs/dev/required-api-keys.md" in out


# ---------------------------------------------------------------------------
# LLM fallback chain health (issue #290)
# ---------------------------------------------------------------------------


def _result_with_fallback_configured() -> dict[str, Any]:
    return {
        "python": {"status": "ok", "version": "3.11.0"},
        "config": {"status": "ok", "path": ".autoinfo/config.yaml"},
        "llm": {"status": "ok", "provider": "openai", "model": "deepseek-v4-flash"},
        "fallback_health": {
            "configured": True,
            "count": 1,
            "primary": {"provider": "openai", "model": "deepseek-v4-flash"},
            "entries": [
                {
                    "model": "mimo-v2.5",
                    "inherits_provider": True,
                    "inherits_key": True,
                }
            ],
        },
        "sources": [],
    }


def test_doctor_prints_fallback_chain_count(capsys: pytest.CaptureFixture[str]) -> None:
    """A configured fallback chain must print its count and entries."""
    _print_human(_result_with_fallback_configured())
    out = capsys.readouterr().out
    assert "LLM fallback chain: 1 fallback(s)" in out
    assert "mimo-v2.5" in out


def test_doctor_prints_inheritance_flags(capsys: pytest.CaptureFixture[str]) -> None:
    """Entries inheriting provider/key must be annotated."""
    _print_human(_result_with_fallback_configured())
    out = capsys.readouterr().out
    assert "inherits provider, key" in out


def test_doctor_prints_primary_flags(capsys: pytest.CaptureFixture[str]) -> None:
    """The primary model's reasoning/json-mode flags must render."""
    result = _result_with_fallback_configured()
    result["fallback_health"]["primary"] = {
        "provider": "openai",
        "model": "deepseek-r1",
        "reasoning_model": True,
        "json_mode": False,
    }
    _print_human(result)
    out = capsys.readouterr().out
    assert "openai/deepseek-r1 [reasoning_model]" in out


def test_doctor_prints_fallback_not_configured_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unconfigured fallback chain must print the setup hint."""
    result = _result_with_llm_unconfigured()
    result["fallback_health"] = {"configured": False, "count": 0}
    _print_human(result)
    out = capsys.readouterr().out
    assert "LLM fallback chain: not configured" in out
    assert "add llm.fallback" in out
