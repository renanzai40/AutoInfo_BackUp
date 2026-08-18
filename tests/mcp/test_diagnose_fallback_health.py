"""Tests for the ``fallback_health`` section of ``diagnose_system`` (issue #290).

Covers:
- No LLM config → ``fallback_health.configured == False``, count 0.
- Primary only → ``configured False``, count 0, primary fields populated.
- Primary + fallback → ``configured True``, count N; ``inherits_provider`` /
  ``inherits_key`` reflect the config semantics (empty provider inherits the
  primary provider; empty api_key inherits the primary key / ``${ENV}`` ref).
- The shared ``llm_fallback_health`` helper (config.py) drives the payload.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from autoinfo.config import Config, LLMConfig, ProjectConfig, llm_fallback_health
from autoinfo.mcp.server import _handle_diagnose_system


class TestDiagnoseFallbackHealth:
    """``diagnose_system`` carries a ``fallback_health`` section."""

    def test_no_config_fallback_not_configured(self) -> None:
        """Without a config file, fallback_health reports not configured."""
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_diagnose_system()

        fh = result["fallback_health"]
        assert fh["configured"] is False
        assert fh["count"] == 0
        assert fh["entries"] == []
        assert fh["primary"] == {
            "model": "",
            "provider": "",
            "reasoning_model": False,
            "json_mode": False,
        }

    def test_primary_only_not_configured(self, tmp_path: Path) -> None:
        """A primary model without fallback entries → configured False, count 0."""
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\nproject:\n  name: T\n"
        )
        with (
            patch("autoinfo.config.get_config_path", return_value=config_path),
            patch("autoinfo.config.load_config") as mock_load,
        ):
            mock_load.return_value = Config(
                project=ProjectConfig(name="T"),
                llm=LLMConfig(
                    provider="openai",
                    model="gpt-4o",
                    reasoning_model=True,
                    json_mode=True,
                ),
            )
            result = _handle_diagnose_system()

        fh = result["fallback_health"]
        assert fh["configured"] is False
        assert fh["count"] == 0
        assert fh["entries"] == []
        assert fh["primary"]["model"] == "gpt-4o"
        assert fh["primary"]["provider"] == "openai"
        assert fh["primary"]["reasoning_model"] is True
        assert fh["primary"]["json_mode"] is True

    def test_primary_with_fallback_configured(self, tmp_path: Path) -> None:
        """Primary + 1 fallback → configured True, count 1, inheritance flags."""
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\nproject:\n  name: T\n"
        )
        with (
            patch("autoinfo.config.get_config_path", return_value=config_path),
            patch("autoinfo.config.load_config") as mock_load,
        ):
            mock_load.return_value = Config(
                project=ProjectConfig(name="T"),
                llm=LLMConfig(
                    provider="openai",
                    model="gpt-4o",
                    fallback=[
                        LLMConfig(
                            model="mimo-v2.5",
                            base_url="https://opencode.ai/zen/go/v1",
                        ),
                    ],
                ),
            )
            result = _handle_diagnose_system()

        fh = result["fallback_health"]
        assert fh["configured"] is True
        assert fh["count"] == 1
        entry = fh["entries"][0]
        assert entry["model"] == "mimo-v2.5"
        # Empty provider → inherits the primary provider; empty api_key →
        # inherits the primary key (or its ${ENV} reference).
        assert entry["inherits_provider"] is True
        assert entry["inherits_key"] is True
        assert fh["primary"]["model"] == "gpt-4o"
        assert fh["primary"]["provider"] == "openai"

    def test_explicit_provider_and_key_do_not_inherit(self, tmp_path: Path) -> None:
        """Explicit provider / ${ENV} api_key on a fallback → no inheritance."""
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\nproject:\n  name: T\n"
        )
        with (
            patch("autoinfo.config.get_config_path", return_value=config_path),
            patch("autoinfo.config.load_config") as mock_load,
        ):
            mock_load.return_value = Config(
                project=ProjectConfig(name="T"),
                llm=LLMConfig(
                    provider="openai",
                    model="gpt-4o",
                    fallback=[
                        LLMConfig(
                            model="gpt-4o-mini",
                            provider="openrouter",
                            api_key="${AUTOINFO_LLM_API_KEY}",
                        ),
                    ],
                ),
            )
            result = _handle_diagnose_system()

        fh = result["fallback_health"]
        assert fh["configured"] is True
        entry = fh["entries"][0]
        assert entry["provider"] == "openrouter"
        assert entry["inherits_provider"] is False
        assert entry["inherits_key"] is False


class TestLlmFallbackHealthHelper:
    """The shared ``llm_fallback_health`` helper (config.py)."""

    def test_empty_llm_config(self) -> None:
        fh = llm_fallback_health(Config())
        assert fh["configured"] is False
        assert fh["count"] == 0
        assert fh["entries"] == []

    def test_fallback_inheritance_semantics(self) -> None:
        fh = llm_fallback_health(
            Config(
                llm=LLMConfig(
                    provider="openai",
                    model="gpt-4o",
                    fallback=[
                        LLMConfig(model="mimo-v2.5"),
                        LLMConfig(model="gpt-4o-mini", provider="openrouter"),
                        LLMConfig(
                            model="claude-sonnet",
                            api_key="${AUTOINFO_LLM_API_KEY}",
                        ),
                    ],
                ),
            )
        )
        assert fh["configured"] is True
        assert fh["count"] == 3
        # Empty provider + empty api_key → inherits both.
        assert fh["entries"][0]["inherits_provider"] is True
        assert fh["entries"][0]["inherits_key"] is True
        # Explicit provider → does not inherit provider.
        assert fh["entries"][1]["inherits_provider"] is False
        assert fh["entries"][1]["inherits_key"] is True
        # Explicit ${ENV} api_key → does not inherit key.
        assert fh["entries"][2]["inherits_provider"] is True
        assert fh["entries"][2]["inherits_key"] is False
