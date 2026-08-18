"""Tests for ``autoinfo init`` LLM fallback-chain guidance (issue #290).

Covers:
- After config is written, init prints fallback-chain guidance mirroring the
  MCP ``init_project`` next_steps: how to add a fallback model, how to set
  ``reasoning_model``, and a connectivity-check hint.
- Minimal validation: an empty LLM provider is rejected; the validation
  helper rejects an empty model when a model is required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import typer

from autoinfo.cli.init import _run_init, _validate_llm_inputs, init


class TestInitFallbackGuidance:
    """``_run_init`` prints fallback-chain / reasoning / connectivity guidance."""

    def test_prints_fallback_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Next-steps output must guide the fallback chain, reasoning_model, connectivity."""
        monkeypatch.chdir(tmp_path)
        _run_init(["medical-research"], tmp_path / ".autoinfo")

        out = capsys.readouterr().out.lower()
        assert "fallback" in out, "init must mention the LLM fallback chain"
        assert "reasoning_model" in out, "init must mention reasoning_model"
        assert "test_llm_connection" in out or "doctor" in out, (
            "init must hint at a connectivity check"
        )

    def test_demo_init_prints_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The ``--demo`` path (non-interactive) prints the same guidance."""
        monkeypatch.chdir(tmp_path)
        init(demo=["medical-research"], name=None, interactive=True,
             list_domains=False, model=None)

        out = capsys.readouterr().out.lower()
        assert "fallback" in out
        assert "reasoning_model" in out


class TestInitValidation:
    """Minimal validation of entered LLM values."""

    def _run_interactive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        answers: list[str],
    ) -> None:
        """Drive the interactive wizard with canned answers."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        answers_iter = iter(answers)

        def fake_prompt(text: str, *args: Any, **kwargs: Any) -> Any:
            value = next(answers_iter)
            conv = kwargs.get("type")
            return conv(value) if conv is not None else value

        monkeypatch.setattr(typer, "prompt", fake_prompt)
        init(demo=None, name=None, interactive=True, list_domains=False, model=None)

    def test_empty_provider_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty LLM provider must abort init with a non-zero exit."""
        with pytest.raises(typer.Exit) as excinfo:
            self._run_interactive(
                tmp_path, monkeypatch, ["MyProject", "1", "", "", ""]
            )
        assert excinfo.value.exit_code == 1

    def test_validation_helper_rejects_empty_provider_and_model(self) -> None:
        """The validation helper rejects empty provider/model, accepts valid input.

        An empty *model* is only rejected when ``model_required=True`` — the
        interactive wizard treats an empty model as "use the template default".
        """
        assert _validate_llm_inputs("", "gpt-4o") is not None
        assert _validate_llm_inputs("openai", "", model_required=True) is not None
        assert _validate_llm_inputs("openai", "gpt-4o") is None
