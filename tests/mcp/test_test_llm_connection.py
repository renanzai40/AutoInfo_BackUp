"""Tests for the ``test_llm_connection`` MCP tool (todo 2 of
model-pool-improvements).

Mirrors the ``test_source`` error-envelope contract:

- handler-internal key validation (NOT the dispatcher guard) — an explicit
  ``api_key`` param must bypass the key check even when config/env have no
  key, so the tool must NOT be added to ``_LLM_REQUIRED_TOOLS``;
- mock success through the REAL ``call_with_fallback`` path, patched only at
  the ``LLMExtractor._get_litellm`` seam (never mocking ``call_with_fallback``
  itself);
- TIMEOUT / INTERNAL_ERROR failure classification from the exception cause
  chain (``call_with_fallback`` wraps the last error as ``__cause__``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

from autoinfo.llm import LLMExtractor
from autoinfo.mcp.errors import ErrorCode
from autoinfo.mcp.server import _handle_test_llm_connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response() -> SimpleNamespace:
    """A minimal litellm completion response with content 'OK'."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
    )


def _make_litellm(
    return_value: object | None = None, side_effect: Exception | None = None
) -> mock.MagicMock:
    """Build a fake litellm module whose completion returns/raises as given."""
    m = mock.MagicMock()
    if side_effect is not None:
        m.completion.side_effect = side_effect
    else:
        m.completion.return_value = return_value
    return m


# ---------------------------------------------------------------------------
# Critical constraint: NOT in the dispatcher guard
# ---------------------------------------------------------------------------


def test_tool_not_in_dispatcher_guard() -> None:
    """``test_llm_connection`` must NOT be in ``_LLM_REQUIRED_TOOLS``.

    ``_is_llm_configured()`` only checks config/env keys, never call params —
    adding the tool to the guard would make explicit ``api_key``/``provider``
    overrides permanently unreachable through the MCP surface.
    """
    from autoinfo.mcp.server import _LLM_REQUIRED_TOOLS

    assert "test_llm_connection" not in _LLM_REQUIRED_TOOLS


# ---------------------------------------------------------------------------
# ① No key and no params → LLM_NOT_CONFIGURED (handler-internal check)
# ---------------------------------------------------------------------------


def test_no_key_no_params_returns_llm_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No config file, no env key, no params → LLM_NOT_CONFIGURED envelope."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)

    result = _handle_test_llm_connection()

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.LLM_NOT_CONFIGURED.value
    assert result["error"]["actionable"] is True
    assert "required-api-keys.md" in result["error"]["message"]


def test_placeholder_key_without_env_counts_as_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``${ENV}`` placeholder with no backing env var is NOT a real key."""
    (tmp_path / ".autoinfo").mkdir()
    (tmp_path / ".autoinfo" / "config.yaml").write_text(
        "llm:\n  provider: openai\n  model: deepseek-v4-flash\n"
        "  api_key: ${AUTOINFO_LLM_API_KEY}\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)

    result = _handle_test_llm_connection()

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.LLM_NOT_CONFIGURED.value


# ---------------------------------------------------------------------------
# ② Explicit api_key param → skips key check, mock success
# ---------------------------------------------------------------------------


def test_explicit_api_key_skips_key_check_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit ``api_key`` bypasses the key check even with no config/env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)

    mock_lm = _make_litellm(return_value=_ok_response())
    with mock.patch.object(
        LLMExtractor, "_get_litellm", return_value=mock_lm
    ) as mock_get:
        result = _handle_test_llm_connection(
            provider="openai", model="gpt-4o-mini", api_key="sk-test"
        )

    # Real call path triggered: call_with_fallback → _get_litellm → completion
    mock_get.assert_called_once()
    mock_lm.completion.assert_called_once()

    assert result["connectable"] is True
    assert result["tested_model"] == "openai/gpt-4o-mini"
    assert isinstance(result["latency_ms"], (int, float))
    assert result["latency_ms"] >= 0
    assert result["config_source"] == "params"
    assert "openai/gpt-4o-mini" in result["message"]


# ---------------------------------------------------------------------------
# ③ No params but config/env has key → mock success, config_source == "config"
# ---------------------------------------------------------------------------


def test_env_key_no_params_succeeds_with_config_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env key alone (no config file) → success, ``config_source == 'config'``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-env")

    mock_lm = _make_litellm(return_value=_ok_response())
    with mock.patch.object(
        LLMExtractor, "_get_litellm", return_value=mock_lm
    ) as mock_get:
        result = _handle_test_llm_connection()

    mock_get.assert_called_once()
    assert result["connectable"] is True
    assert result["config_source"] == "config"
    assert result["tested_model"]  # non-empty


def test_config_file_key_no_params_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config file with a resolved key (no params) → success, 'config'."""
    (tmp_path / ".autoinfo").mkdir()
    (tmp_path / ".autoinfo" / "config.yaml").write_text(
        "llm:\n  provider: openai\n  model: deepseek-v4-flash\n"
        "  api_key: ${AUTOINFO_LLM_API_KEY}\n"
        "  base_url: https://opencode.ai/zen/go/v1\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-config")

    mock_lm = _make_litellm(return_value=_ok_response())
    with mock.patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
        result = _handle_test_llm_connection()

    assert result["connectable"] is True
    assert result["config_source"] == "config"
    assert result["tested_model"] == "openai/deepseek-v4-flash"


# ---------------------------------------------------------------------------
# ④ Failure classification from the exception cause chain
# ---------------------------------------------------------------------------


def test_timeout_exception_classifies_as_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``httpx.TimeoutException`` from completion → TIMEOUT envelope."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-env")

    mock_lm = _make_litellm(side_effect=httpx.TimeoutException("timed out"))
    with mock.patch.object(
        LLMExtractor, "_get_litellm", return_value=mock_lm
    ) as mock_get:
        result = _handle_test_llm_connection()

    mock_get.assert_called_once()
    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.TIMEOUT.value
    assert result["error"]["actionable"] is True


def _chained(inner: Exception) -> RuntimeError:
    """Build ``RuntimeError("wrapped") from inner`` (raise-only syntax)."""
    try:
        raise RuntimeError("wrapped") from inner
    except RuntimeError as exc:
        return exc


def test_nested_timeout_in_cause_chain_classifies_as_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout buried deeper in the cause chain still classifies as TIMEOUT."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-env")

    outer = _chained(httpx.TimeoutException("connect timed out"))

    mock_lm = _make_litellm(side_effect=outer)
    with mock.patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
        result = _handle_test_llm_connection()

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.TIMEOUT.value


def test_plain_runtime_error_classifies_as_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain non-timeout error (non-429/5xx) → INTERNAL_ERROR envelope."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-env")

    mock_lm = _make_litellm(side_effect=RuntimeError("boom"))
    with mock.patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
        result = _handle_test_llm_connection()

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert result["error"]["actionable"] is True
    assert "boom" in result["error"]["message"]


# ---------------------------------------------------------------------------
# Registration: tools/list exposes the tool with the expected schema
# ---------------------------------------------------------------------------


def test_tool_registered_in_list_tools() -> None:
    """``tools/list`` exposes ``test_llm_connection`` with 4 optional params."""
    from autoinfo.mcp.server import list_tools

    tools = asyncio.run(list_tools())
    names = [t.name for t in tools]
    assert "test_llm_connection" in names

    tool = next(t for t in tools if t.name == "test_llm_connection")
    props = tool.inputSchema["properties"]
    assert set(props) == {"provider", "model", "base_url", "api_key"}
    assert tool.inputSchema.get("required", []) == []
