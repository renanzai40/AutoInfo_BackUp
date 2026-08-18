"""Tests for model-pool examples in ``init_project`` next_steps and the
default config template.

Covers:
    - ``init_project`` next_steps documents the model-pool configuration
      example (``configure_llm(llm_fallback=..., llm_tasks=...)`` plus a
      ``test_llm_connection`` verification step).
    - ``data/default_config.yaml`` round-trips through ``load_config`` with
      the commented ``# fallback:`` / ``# tasks:`` examples NOT enabled
      (``llm.fallback == []``, ``llm.tasks == {}``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import autoinfo
from autoinfo.config import load_config
from autoinfo.mcp.server import _handle_init_project

_DEFAULT_CONFIG = (
    Path(autoinfo.__file__).resolve().parent / "data" / "default_config.yaml"
)


# ======================================================================
# init_project next_steps pool example
# ======================================================================


class TestInitProjectNextStepsPoolExample:
    """``init_project`` next_steps should document the model-pool example."""

    def test_next_steps_contains_pool_example(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research")
        assert result["status"] == "success"

        pool_lines = [
            s for s in result["next_steps"] if "configure_llm(llm_fallback=" in s
        ]
        assert pool_lines, (
            "next_steps should contain a configure_llm(llm_fallback=...) example"
        )
        line = pool_lines[0]
        assert "llm_tasks=" in line
        assert "test_llm_connection" in line
        assert "https://opencode.ai/zen/go/v1" in line

    def test_dry_run_next_steps_contains_pool_example(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research", dry_run=True)
        assert result["status"] == "dry_run"

        pool_lines = [
            s for s in result["next_steps"] if "configure_llm(llm_fallback=" in s
        ]
        assert pool_lines, (
            "dry_run next_steps should contain a configure_llm(llm_fallback=...) example"
        )
        line = pool_lines[0]
        assert "llm_tasks=" in line
        assert "test_llm_connection" in line


# ======================================================================
# default_config.yaml template pool examples
# ======================================================================


class TestDefaultConfigTemplatePoolExamples:
    """Commented model-pool examples in default_config.yaml must stay inert."""

    def test_default_config_round_trips_without_pool_fields(self) -> None:
        assert _DEFAULT_CONFIG.is_file(), f"missing {_DEFAULT_CONFIG}"
        config = load_config(_DEFAULT_CONFIG)
        assert config.llm.fallback == []
        assert config.llm.tasks == {}

    def test_default_config_contains_commented_examples(self) -> None:
        text = _DEFAULT_CONFIG.read_text(encoding="utf-8")
        assert "# fallback:" in text
        assert "# tasks:" in text
