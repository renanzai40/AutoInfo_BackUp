"""Tests for the ``init_project`` MCP tool.

Covers:
    - Tool registration in ``list_tools()``
    - Happy path: init with valid domain creates .autoinfo/
    - Idempotency: calling twice returns "skipped"
    - Invalid domain: graceful error (not typer.Exit)
    - dry_run=True: no files are written
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.types import TextContent, Tool

from autoinfo.mcp.server import _handle_init_project, list_tools


# ======================================================================
# Tool registration
# ======================================================================


class TestToolRegistration:
    """Verify ``init_project`` appears in the tool list with correct schema."""

    async def test_tool_exists(self) -> None:
        tools: list[Tool] = await list_tools()
        names = [t.name for t in tools]
        assert "init_project" in names

    async def test_tool_schema(self) -> None:
        tools: list[Tool] = await list_tools()
        tool = next(t for t in tools if t.name == "init_project")
        schema = tool.inputSchema
        assert "domain" in schema.get("properties", {})
        assert "project_name" in schema["properties"]
        assert "dry_run" in schema["properties"]
        assert "llm_provider" in schema["properties"]
        assert "llm_model" in schema["properties"]
        assert "llm_base_url" in schema["properties"]
        assert schema["required"] == ["domain"]
        # Domain should have an enum constraint
        assert "enum" in schema["properties"]["domain"]
        assert "llm_provider" not in schema["required"]
        assert "llm_model" not in schema["required"]
        assert "llm_base_url" not in schema["required"]


# ======================================================================
# Happy path
# ======================================================================


class TestInitSuccess:
    """Calling ``init_project`` with a valid domain creates ``.autoinfo/``."""

    def test_creates_autoinfo_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research")
        assert result["status"] == "success"
        assert result["domain"] == "medical-research"
        assert (tmp_path / ".autoinfo").is_dir()
        assert (tmp_path / ".autoinfo" / "config.yaml").is_file()
        assert (tmp_path / "knowledge" / "01-Raw").is_dir()

    def test_creates_with_project_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research", project_name="My Project")
        assert result["status"] == "success"
        assert result["project_name"] == "My Project"

    def test_ai_commercial_domain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="ai-commercial")
        assert result["status"] == "success"
        assert (tmp_path / ".autoinfo" / "config.yaml").is_file()

    def test_language_learning_domain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="language-learning")
        assert result["status"] == "success"
        assert (tmp_path / ".autoinfo" / "config.yaml").is_file()


# ======================================================================
# Idempotency
# ======================================================================


class TestInitIdempotent:
    """Calling ``init_project`` twice should skip the second time."""

    def test_second_call_returns_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        # First call
        first = _handle_init_project(domain="medical-research")
        assert first["status"] == "success"

        # Second call — should skip
        second = _handle_init_project(domain="medical-research")
        assert second["status"] == "skipped"
        assert "Already initialized" in second["message"]

    def test_skipped_does_not_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _handle_init_project(domain="medical-research")

        # Record original config content
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        original_content = config_path.read_text()

        # Call again (skipped)
        _handle_init_project(domain="ai-commercial")  # different domain
        # Config should NOT have been overwritten with ai-commercial
        assert config_path.read_text() == original_content


# ======================================================================
# Invalid domain
# ======================================================================


class TestInitInvalidDomain:
    """Invalid domain should produce a graceful error, not a crash."""

    def test_unknown_domain_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="nonexistent-domain")
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"
        # .autoinfo should NOT have been created
        assert not (tmp_path / ".autoinfo").exists()

    def test_empty_domain_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="")
        assert "error_code" in result

    def test_error_is_not_exit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The error should NOT be a typer.Exit or sys.exit — it must be
        a graceful error dict that the MCP framework can return."""
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="garbage")
        assert isinstance(result, dict)
        assert "error_code" in result
        assert "message" in result


# ======================================================================
# Dry run
# ======================================================================


class TestInitDryRun:
    """``dry_run=True`` should return a preview without creating files."""

    def test_dry_run_returns_preview(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research", dry_run=True)
        assert result["status"] == "dry_run"
        assert ".autoinfo" in str(result.get("autoinfo_dir", ""))
        assert "would_create_dirs" in result or "would_create_files" in result

    def test_dry_run_does_not_create_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _handle_init_project(domain="medical-research", dry_run=True)
        # No files should have been created
        assert not (tmp_path / ".autoinfo").exists()

    def test_dry_run_with_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """dry_run=True should still work even when .autoinfo/ already exists."""
        monkeypatch.chdir(tmp_path)

        # First, actually init
        _handle_init_project(domain="medical-research")
        assert (tmp_path / ".autoinfo").exists()

        # Then dry_run — should NOT be "skipped" since dry_run takes priority
        # Actually, wait: if config exists AND dry_run, the handler returns
        # the dry_run preview (not "skipped") because dry_run is checked first.
        # Let's verify:
        result = _handle_init_project(domain="medical-research", dry_run=True)
        # It should still return a dry_run preview, not "skipped"
        assert result["status"] == "dry_run"


# ======================================================================
# Error handling
# ======================================================================


class TestInitErrorHandling:
    """Exceptions during init should be caught and returned as error dicts."""

    def test_exception_returns_internal_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If _run_init raises, the handler should catch and return an error dict."""
        monkeypatch.chdir(tmp_path)

        # Patch _ensure_dir to raise an OSError
        import autoinfo.cli.init as cli_init
        original = cli_init._ensure_dir

        def failing_mkdir(path: Path) -> bool:
            raise OSError(f"Cannot create {path}")

        monkeypatch.setattr(cli_init, "_ensure_dir", failing_mkdir)

        result = _handle_init_project(domain="medical-research")
        assert "error_code" in result
        assert result["error_code"] == "InternalError"
        assert "message" in result

        # Restore
        monkeypatch.setattr(cli_init, "_ensure_dir", original)


# ======================================================================
# LLM override params
# ======================================================================


class TestInitLlmOverride:
    """``llm_provider`` / ``llm_model`` / ``llm_base_url`` params should
    override the corresponding values in generated config.yaml."""

    def test_llm_provider_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="medical-research",
            llm_provider="openai",
        )
        assert result["status"] == "success"
        assert result["llm_provider"] == "openai"

        import yaml
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["llm"]["provider"] == "openai"
        # Other defaults should remain
        assert cfg["llm"]["model"] == "deepseek-v4-flash"

    def test_llm_model_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="medical-research",
            llm_model="gpt-4",
        )
        assert result["status"] == "success"
        assert result["llm_model"] == "gpt-4"

        import yaml
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["llm"]["model"] == "gpt-4"
        assert cfg["llm"]["provider"] == "openai"

    def test_llm_base_url_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="medical-research",
            llm_base_url="http://localhost:11434/v1",
        )
        assert result["status"] == "success"
        assert result["llm_base_url"] == "http://localhost:11434/v1"

        import yaml
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["llm"]["base_url"] == "http://localhost:11434/v1"

    def test_all_three_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="ai-commercial",
            llm_provider="anthropic",
            llm_model="claude-3-opus",
            llm_base_url="https://api.anthropic.com",
        )
        assert result["status"] == "success"

        import yaml
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["llm"]["provider"] == "anthropic"
        assert cfg["llm"]["model"] == "claude-3-opus"
        assert cfg["llm"]["base_url"] == "https://api.anthropic.com"

    def test_no_overrides_backwards_compatible(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling without LLM params should leave defaults intact."""
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(domain="medical-research")
        assert result["status"] == "success"
        assert result["llm_provider"] == "(default)"
        assert result["llm_model"] == "(default)"
        assert result["llm_base_url"] == "(default)"

        import yaml
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["llm"]["provider"] == "openai"
        assert cfg["llm"]["model"] == "deepseek-v4-flash"
        assert "base_url" not in cfg["llm"]

    def test_dry_run_includes_llm_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="medical-research",
            dry_run=True,
            llm_provider="openai",
            llm_model="gpt-4",
            llm_base_url="http://localhost:11434/v1",
        )
        assert result["status"] == "dry_run"
        assert result["llm_provider"] == "openai"
        assert result["llm_model"] == "gpt-4"
        assert result["llm_base_url"] == "http://localhost:11434/v1"
        # No files should have been created
        assert not (tmp_path / ".autoinfo").exists()

    def test_dry_run_defaults_shown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _handle_init_project(
            domain="medical-research",
            dry_run=True,
        )
        assert result["status"] == "dry_run"
        assert result["llm_provider"] == "(default)"
        assert result["llm_model"] == "(default)"
        assert result["llm_base_url"] == "(default)"
