"""Tests for the ``autoinfo init`` LLM model prompt (model-pool-improvements todo 4).

Covers:
- Interactive mode: the model prompt appears in the prompt chain and a typed
  model lands in ``config.yaml`` ``llm.model``.
- Empty model input falls back to the template default (deepseek-v4-flash,
  the issue #195 vendor-neutral template).
- ``--model`` non-interactive override wins over the template default.
- ``--demo`` path without ``--model`` is unchanged (template default preserved).
- The model prompt text surfaces provider candidates (openai/openrouter/ollama/
  custom base_url) — static text, no network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml

from autoinfo.cli.init import init


def _read_config(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"config.yaml not created at {path}"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


class TestInitModelPrompt:
    """Interactive init: model prompt appears and drives config llm.model."""

    def _run_interactive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        answers: list[str],
    ) -> list[str]:
        """Drive the interactive wizard with canned answers; return prompt texts."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        answers_iter = iter(answers)
        prompts: list[str] = []

        def fake_prompt(text: str, *args: Any, **kwargs: Any) -> Any:
            prompts.append(text)
            value = next(answers_iter)
            conv = kwargs.get("type")
            return conv(value) if conv is not None else value

        monkeypatch.setattr(typer, "prompt", fake_prompt)
        # Pass every param explicitly: unpassed Typer params default to truthy
        # OptionInfo objects, which would misroute the direct function call.
        init(demo=None, name=None, interactive=True, list_domains=False, model=None)
        return prompts

    def test_model_prompt_appears_and_sets_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Typing a model in the wizard writes it to config llm.model."""
        prompts = self._run_interactive(
            tmp_path,
            monkeypatch,
            ["MyProject", "1", "openrouter", "", "deepseek-v4-flash"],
        )

        model_prompt = next(p for p in prompts if "model" in p.lower())
        assert "openai" in model_prompt
        assert "openrouter" in model_prompt
        assert "ollama" in model_prompt
        assert "base_url" in model_prompt

        config = _read_config(tmp_path / ".autoinfo" / "config.yaml")
        assert config["llm"]["model"] == "deepseek-v4-flash"

    def test_empty_model_input_uses_template_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty model input keeps the template default (deepseek-v4-flash on openai,
        the issue #195 vendor-neutral shipped default)."""
        self._run_interactive(
            tmp_path,
            monkeypatch,
            ["MyProject", "1", "openrouter", "", ""],
        )

        config = _read_config(tmp_path / ".autoinfo" / "config.yaml")
        assert config["llm"]["model"] == "deepseek-v4-flash"
        assert config["llm"]["provider"] == "openai"

    def test_model_flag_non_interactive_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--model high-acc-model overrides the template default non-interactively."""
        monkeypatch.chdir(tmp_path)
        init(demo=["medical-research"], name=None, interactive=True,
             list_domains=False, model="high-acc-model")

        config = _read_config(tmp_path / ".autoinfo" / "config.yaml")
        assert config["llm"]["model"] == "high-acc-model"

    def test_demo_path_unchanged_without_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--demo without --model keeps the template default (no regression;
        now the issue #195 deployment-accurate deepseek-v4-flash/openai)."""
        monkeypatch.chdir(tmp_path)
        init(demo=["medical-research"], name=None, interactive=True,
             list_domains=False, model=None)

        config = _read_config(tmp_path / ".autoinfo" / "config.yaml")
        assert config["llm"]["model"] == "deepseek-v4-flash"
        assert config["llm"]["provider"] == "openai"
