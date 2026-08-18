"""Tests for the extended ``list_available_models`` MCP tool.

The tool now returns the full LLM model pool: the primary model, every
configured fallback entry, and every per-task model override.  The
primary entry keeps its historical shape (task/provider/model/
api_key_configured); fallback and task entries are appended with
additional fields (``inherits_provider``, ``max_tokens``).

``count`` must always equal ``len(models)``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.server import _handle_list_available_models


def _config_dict(
    *,
    provider: str = "openai",
    model: str = "deepseek-v4-flash",
    api_key: str = "",
    fallback: list[dict[str, Any]] | None = None,
    tasks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal config dict with optional llm.fallback / llm.tasks."""
    llm: dict[str, Any] = {"provider": provider, "model": model, "api_key": api_key}
    if fallback is not None:
        llm["fallback"] = fallback
    if tasks is not None:
        llm["tasks"] = tasks
    return {
        "project": {"name": "Test", "created_at": ""},
        "llm": llm,
        "domains": [],
    }


def _mock_load_config(config_dict: dict[str, Any]) -> Any:
    """Patch ``_load_config`` to return a config built from *config_dict*."""
    from autoinfo.config import _dict_to_config

    return patch.object(
        mcp_server, "_load_config", return_value=_dict_to_config(config_dict)
    )


class TestListAvailableModelsFullPool:
    def test_primary_fallback_and_task_entries(self) -> None:
        """1 fallback + 1 task → count == 3 with the expected entry shapes."""
        with _mock_load_config(
            _config_dict(
                fallback=[{"model": "mimo-v2.5"}],
                tasks={"extraction": {"model": "gpt-4o", "max_tokens": 4096}},
            )
        ):
            result = _handle_list_available_models()

        assert result["count"] == 3
        assert result["count"] == len(result["models"])

        task_names = [m["task"] for m in result["models"]]
        assert task_names == ["default", "fallback:mimo-v2.5", "extraction"]

        # Primary entry keeps its historical shape
        primary = result["models"][0]
        assert primary["task"] == "default"
        assert primary["provider"] == "openai"
        assert primary["model"] == "deepseek-v4-flash"
        assert primary["api_key_configured"] is False

        # Fallback entry: empty provider → inherits_provider True
        fb = result["models"][1]
        assert fb["task"] == "fallback:mimo-v2.5"
        assert fb["model"] == "mimo-v2.5"
        assert fb["provider"] == ""
        assert fb["inherits_provider"] is True
        assert fb["api_key_configured"] is False

        # Task entry carries max_tokens
        task = result["models"][2]
        assert task["task"] == "extraction"
        assert task["model"] == "gpt-4o"
        assert task["provider"] == ""
        assert task["inherits_provider"] is True
        assert task["max_tokens"] == 4096
        assert task["api_key_configured"] is False

    def test_no_fallback_or_tasks_backward_compatible(self) -> None:
        """Empty pool → count == 1, single primary entry (backward compat)."""
        with _mock_load_config(_config_dict()):
            result = _handle_list_available_models()

        assert result["count"] == 1
        assert result["count"] == len(result["models"])
        model = result["models"][0]
        assert model["task"] == "default"
        assert model["provider"] == "openai"
        assert model["model"] == "deepseek-v4-flash"
        assert "api_key_configured" in model

    def test_fallback_with_explicit_provider(self) -> None:
        """Explicit fallback provider → inherits_provider False."""
        with _mock_load_config(
            _config_dict(fallback=[{"provider": "openrouter", "model": "gpt-4o"}])
        ):
            result = _handle_list_available_models()

        assert result["count"] == 2
        fb = result["models"][1]
        assert fb["provider"] == "openrouter"
        assert fb["inherits_provider"] is False

    def test_task_inherits_primary_provider(self) -> None:
        """Task with only a model → empty provider + inherits_provider True."""
        with _mock_load_config(
            _config_dict(tasks={"summarization": {"model": "claude-3"}})
        ):
            result = _handle_list_available_models()

        assert result["count"] == 2
        task = result["models"][1]
        assert task["task"] == "summarization"
        assert task["model"] == "claude-3"
        assert task["provider"] == ""
        assert task["inherits_provider"] is True

    def test_api_key_configured_reflects_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback entries inherit the primary key → api_key_configured True."""
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test")
        with _mock_load_config(_config_dict(fallback=[{"model": "mimo-v2.5"}])):
            result = _handle_list_available_models()

        assert result["models"][0]["api_key_configured"] is True
        assert result["models"][1]["api_key_configured"] is True

    def test_error_branch_preserved(self) -> None:
        """Missing config → existing error envelope, count == 0."""
        with patch.object(
            mcp_server, "_load_config", side_effect=FileNotFoundError("no config")
        ):
            result = _handle_list_available_models()

        assert result["count"] == 0
        assert result["models"] == []
        assert "error_code" in result
        assert "message" in result
        assert result["actionable"] is True
