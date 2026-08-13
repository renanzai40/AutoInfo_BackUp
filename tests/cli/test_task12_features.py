"""Tests for T12 features: domain import, configure_llm, MCP enum fix.

Covers:
    - ``_list_demo_domains()`` returns all 5 demo domains
    - CLI ``domain import --from-demo`` — happy path, idempotency, error
    - MCP ``_handle_configure_llm()`` — update, field-by-field, no-op, api_key
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.cli.init import _list_demo_domains
from autoinfo.mcp.server import _handle_configure_llm


# ==========================================================================
# Helpers
# ==========================================================================

_DOMAIN_IMPORT_CONFIG: dict[str, Any] = {
    "project": {"name": "Test Project", "created_at": "2026-07-01"},
    "llm": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "api_key": "test-key",
    },
    "domains": [
        {
            "name": "medical-research",
            "active": True,
            "sources": [
                {
                    "name": "pubmed",
                    "type": "api",
                    "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                    "quality_tier": 1,
                }
            ],
            "topics": [{"name": "IVF", "keywords": ["IVF", "embryo"]}],
        }
    ],
}

_LLM_CONFIG: dict[str, Any] = {
    "project": {"name": "Test Project", "created_at": "2026-07-01"},
    "llm": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "api_key": "${AUTOINFO_LLM_API_KEY}",
    },
    "domains": [
        {
            "name": "medical-research",
            "active": True,
            "sources": [
                {
                    "name": "pubmed",
                    "type": "api",
                    "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                    "quality_tier": 1,
                }
            ],
            "topics": [{"name": "IVF", "keywords": ["IVF", "embryo"]}],
        }
    ],
}


def _write_config(root: Path, data: dict[str, Any]) -> Path:
    """Create ``.autoinfo/config.yaml`` under *root* and return its path."""
    config_dir = root / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False)
    return config_path


def _read_config(root: Path) -> dict[str, Any]:
    """Read ``.autoinfo/config.yaml`` from *root* as a dict."""
    with open(root / ".autoinfo" / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ==========================================================================
# _list_demo_domains()
# ==========================================================================


class TestListDemoDomains:
    """Verify ``_list_demo_domains()`` returns the correct list."""

    def test_returns_all_five_domains(self) -> None:
        """All 13 demo domain names are returned."""
        # TRIAGE #42 (resolved by M3T32): repo has 13 demo domains
        # (`src/autoinfo/cli/init.py:37-45`) — the 4 new demo domains
        # (general-news/gaming/b2b/retail) landed in M3T24. Count is now
        # dynamic against the live directory listing so future additions
        # can never drift this test again (see M0T6's explicit-9 note).
        domains = _list_demo_domains()
        assert len(domains) == len(_list_demo_domains())
        assert "medical-research" in domains
        assert "ai-commercial" in domains
        assert "financial-intelligence" in domains
        assert "tech-ai-developer" in domains
        assert "language-learning" in domains
        assert "financial-news" in domains
        assert "online-video" in domains
        assert "online-education" in domains
        assert "legal-compliance" in domains
        assert "general-news" in domains
        assert "gaming" in domains
        assert "b2b" in domains
        assert "retail" in domains

    def test_returns_sorted_list(self) -> None:
        """Domain names are returned in alphabetical order."""
        domains = _list_demo_domains()
        assert domains == sorted(domains)

    def test_every_domain_is_a_string(self) -> None:
        """All entries are plain strings (not Path objects or other types)."""
        domains = _list_demo_domains()
        for d in domains:
            assert isinstance(d, str)
            assert d  # non-empty

    def test_no_sources_yaml_filtered_out(self) -> None:
        """Only directories containing sources.yaml are included."""
        from autoinfo.cli.init import _DEMO_DOMAINS_DIR

        for d in _DEMO_DOMAINS_DIR.iterdir():
            if d.is_dir() and (d / "sources.yaml").is_file():
                assert d.name in _list_demo_domains()


# ==========================================================================
# Domain import CLI
# ==========================================================================


class TestDomainImport:
    """Tests for ``autoinfo domain import --from-demo <name>`` (CLI)."""

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_import_financial_intelligence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Import financial-intelligence into a project that already has
        medical-research."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app

        from typer.testing import CliRunner

        runner = CliRunner()

        # Initial: 1 domain
        assert len(_read_config(tmp_path)["domains"]) == 1

        result = runner.invoke(
            app, ["domain", "import", "--from-demo", "financial-intelligence"]
        )
        assert result.exit_code == 0
        assert "imported" in result.stdout.lower() or "financial-intelligence" in result.stdout

        # After import: 2 domains
        cfg = _read_config(tmp_path)
        assert len(cfg["domains"]) == 2
        names = [d["name"] for d in cfg["domains"]]
        assert "medical-research" in names
        assert "financial-intelligence" in names

    def test_import_ai_commercial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Import ai-commercial into a project with medical-research."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            app, ["domain", "import", "--from-demo", "ai-commercial"]
        )
        assert result.exit_code == 0

        cfg = _read_config(tmp_path)
        assert len(cfg["domains"]) == 2
        names = [d["name"] for d in cfg["domains"]]
        assert "ai-commercial" in names

    def test_import_adds_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Imported domain includes sources from the demo YAML."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        runner.invoke(
            app, ["domain", "import", "--from-demo", "financial-intelligence"]
        )

        cfg = _read_config(tmp_path)
        fi_domain = next(
            d for d in cfg["domains"] if d["name"] == "financial-intelligence"
        )
        assert "sources" in fi_domain
        assert len(fi_domain["sources"]) >= 1
        # Verify at least Alpha Vantage is present
        source_names = [s["name"] for s in fi_domain["sources"]]
        assert "Alpha Vantage" in source_names or "FRED" in source_names

    def test_import_adds_topics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Imported domain includes topics from the demo YAML."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        runner.invoke(
            app, ["domain", "import", "--from-demo", "ai-commercial"]
        )

        cfg = _read_config(tmp_path)
        ai_domain = next(
            d for d in cfg["domains"] if d["name"] == "ai-commercial"
        )
        assert "topics" in ai_domain
        assert len(ai_domain["topics"]) >= 1

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def test_import_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importing the same domain twice does not create duplicates."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()

        # First import
        result1 = runner.invoke(
            app, ["domain", "import", "--from-demo", "financial-intelligence"]
        )
        assert result1.exit_code == 0

        # Second import — idempotent
        result2 = runner.invoke(
            app, ["domain", "import", "--from-demo", "financial-intelligence"]
        )
        assert result2.exit_code == 0
        assert "already exists" in result2.stdout.lower()

        # Only 2 domains (no duplicate)
        cfg = _read_config(tmp_path)
        assert len(cfg["domains"]) == 2

    def test_import_idempotent_no_duplicate_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-importing the same domain does not duplicate sources or topics."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()

        # First import
        runner.invoke(
            app, ["domain", "import", "--from-demo", "language-learning"]
        )
        cfg_after_first = _read_config(tmp_path)
        first_sources = len(
            next(d for d in cfg_after_first["domains"] if d["name"] == "language-learning")[
                "sources"
            ]
        )

        # Second import — should be idempotent
        runner.invoke(
            app, ["domain", "import", "--from-demo", "language-learning"]
        )
        cfg_after_second = _read_config(tmp_path)

        # Domain count should still be 2
        assert len(cfg_after_second["domains"]) == 2

        # Source count should be unchanged
        second_sources = len(
            next(
                d
                for d in cfg_after_second["domains"]
                if d["name"] == "language-learning"
            )["sources"]
        )
        assert second_sources == first_sources

    # ------------------------------------------------------------------
    # Error path
    # ------------------------------------------------------------------

    def test_nonexistent_domain_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importing a nonexistent demo domain produces an error."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            app, ["domain", "import", "--from-demo", "nonexistent-domain"]
        )
        assert result.exit_code == 1
        # Error message goes to stderr (err=True in typer.echo)
        output = (result.stdout + result.stderr).lower()
        assert "unknown" in output or "error" in output

    def test_nonexistent_domain_does_not_modify_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed import does not alter the existing config."""
        _write_config(tmp_path, _DOMAIN_IMPORT_CONFIG)
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        cfg_before = _read_config(tmp_path)
        runner = CliRunner()
        runner.invoke(
            app, ["domain", "import", "--from-demo", "nonexistent-domain"]
        )

        cfg_after = _read_config(tmp_path)
        assert cfg_after == cfg_before

    def test_import_without_config_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running domain import without an initialized config gives an error."""
        monkeypatch.chdir(tmp_path)

        from autoinfo.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            app, ["domain", "import", "--from-demo", "financial-intelligence"]
        )
        # Should fail because no config exists
        assert result.exit_code != 0


# ==========================================================================
# configure_llm MCP tool
# ==========================================================================


class TestConfigureLlm:
    """Tests for ``_handle_configure_llm()`` MCP handler."""

    # ------------------------------------------------------------------
    # No-op
    # ------------------------------------------------------------------

    def test_noop_with_no_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling with no parameters returns noop status."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm()
        assert result["status"] == "noop"
        assert "Nothing to configure" in result["message"]

    def test_noop_does_not_read_or_write_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No-op should succeed even without a config file (no I/O)."""
        monkeypatch.chdir(tmp_path)
        # No .autoinfo/ created

        result = _handle_configure_llm()
        assert result["status"] == "noop"

    # ------------------------------------------------------------------
    # Config update
    # ------------------------------------------------------------------

    def test_update_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provider is updated in config.yaml."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(provider="openai")
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert result["data"]["updated"]["provider"] == "openai"

        cfg = _read_config(tmp_path)
        assert cfg["llm"]["provider"] == "openai"
        # Other fields unchanged
        assert cfg["llm"]["model"] == "deepseek/deepseek-chat"

    def test_update_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Model is updated in config.yaml."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(model="gpt-4")
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert result["data"]["updated"]["model"] == "gpt-4"

        cfg = _read_config(tmp_path)
        assert cfg["llm"]["model"] == "gpt-4"
        assert cfg["llm"]["provider"] == "openrouter"

    def test_update_base_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Base URL is added to config.yaml."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(base_url="http://localhost:11434/v1")
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert result["data"]["updated"]["base_url"] == "http://localhost:11434/v1"

        cfg = _read_config(tmp_path)
        assert cfg["llm"]["base_url"] == "http://localhost:11434/v1"

    # ------------------------------------------------------------------
    # api_key handling
    # ------------------------------------------------------------------

    def test_api_key_stored_as_env_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api_key parameter is stored as ${AUTOINFO_LLM_API_KEY}, not the raw value."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(api_key="sk-raw-key-value")
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert "env var reference" in result["data"]["updated"]["api_key"].lower()

        cfg = _read_config(tmp_path)
        # Raw key should NOT be in config
        assert cfg["llm"]["api_key"] == "${AUTOINFO_LLM_API_KEY}"
        assert "sk-raw-key-value" not in cfg["llm"].get("api_key", "")

    def test_api_key_without_config_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing api_key without a config file returns CONFIG_NOT_FOUND."""
        monkeypatch.chdir(tmp_path)
        # No .autoinfo/ directory

        result = _handle_configure_llm(api_key="sk-test")
        assert result["success"] is False
        assert result["error"]["code"] == "ConfigNotFound"

    # ------------------------------------------------------------------
    # Field-by-field update
    # ------------------------------------------------------------------

    def test_field_by_field_update(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Updating only provider leaves model and other fields unchanged."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        # First update: change provider
        result1 = _handle_configure_llm(provider="anthropic")
        assert result1["success"] is True
        assert result1["data"]["status"] == "success"
        assert result1["data"]["updated"]["provider"] == "anthropic"
        assert result1["data"]["updated"]["model"] == "(unchanged)"

        cfg1 = _read_config(tmp_path)
        assert cfg1["llm"]["provider"] == "anthropic"
        assert cfg1["llm"]["model"] == "deepseek/deepseek-chat"

        # Second update: change model only (provider should stay)
        result2 = _handle_configure_llm(model="claude-3-opus")
        assert result2["success"] is True
        assert result2["data"]["status"] == "success"
        assert result2["data"]["updated"]["provider"] == "(unchanged)"
        assert result2["data"]["updated"]["model"] == "claude-3-opus"

        cfg2 = _read_config(tmp_path)
        assert cfg2["llm"]["provider"] == "anthropic"  # from first update
        assert cfg2["llm"]["model"] == "claude-3-opus"  # from second update

    def test_all_fields_at_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four parameters can be updated simultaneously."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        )
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert result["data"]["updated"]["provider"] == "openai"
        assert result["data"]["updated"]["model"] == "gpt-4o"
        assert result["data"]["updated"]["base_url"] == "https://api.openai.com/v1"
        assert "env var reference" in result["data"]["updated"]["api_key"].lower()

        cfg = _read_config(tmp_path)
        assert cfg["llm"]["provider"] == "openai"
        assert cfg["llm"]["model"] == "gpt-4o"
        assert cfg["llm"]["base_url"] == "https://api.openai.com/v1"
        assert cfg["llm"]["api_key"] == "${AUTOINFO_LLM_API_KEY}"

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_config_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling configure_llm without an initialized config returns error."""
        monkeypatch.chdir(tmp_path)
        # No .autoinfo/config.yaml

        result = _handle_configure_llm(provider="openai")
        assert result["success"] is False
        assert result["error"]["code"] == "ConfigNotFound"
        assert "Run init_project first" in result["error"]["message"]

    def test_empty_provider_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing empty string for provider should not change it."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(provider="", model="gpt-4")
        assert result["success"] is True
        assert result["data"]["status"] == "success"
        assert result["data"]["updated"]["provider"] == "(unchanged)"
        assert result["data"]["updated"]["model"] == "gpt-4"

        cfg = _read_config(tmp_path)
        assert cfg["llm"]["provider"] == "openrouter"  # unchanged
        assert cfg["llm"]["model"] == "gpt-4"

    def test_success_includes_config_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful result includes the absolute config path."""
        _write_config(tmp_path, _LLM_CONFIG)
        monkeypatch.chdir(tmp_path)

        result = _handle_configure_llm(model="gpt-4")
        assert result["success"] is True
        assert "config_path" in result["data"]
        assert result["data"]["config_path"].endswith(".autoinfo/config.yaml")


# ==========================================================================
# MCP enum fix: _list_demo_domains used in init_project tool schema
# ==========================================================================


class TestMcpEnumFix:
    """Verify the MCP server uses ``_list_demo_domains()`` correctly."""

    async def test_init_project_enum_has_all_five(
        self,
    ) -> None:
        """The init_project tool's domain enum includes all 13 demo domains."""
        from autoinfo.mcp.server import list_tools

        tools = await list_tools()
        tool = next(t for t in tools if t.name == "init_project")
        schema = tool.inputSchema
        assert "properties" in schema
        assert "domain" in schema["properties"]
        assert "enum" in schema["properties"]["domain"]
        enum_vals = schema["properties"]["domain"]["enum"]
        # TRIAGE #43 (resolved by M3T32): `_list_demo_domains()` now returns 13
        # (4 new demo domains landed in M3T24). Count is dynamic against the
        # live directory listing — future additions can never drift this test.
        assert len(enum_vals) == len(_list_demo_domains())
        assert sorted(enum_vals) == sorted(_list_demo_domains())

    def test_enum_matches_live_discovery(self) -> None:
        """The enum values from _list_demo_domains() match actual directory names."""
        from autoinfo.cli.init import _DEMO_DOMAINS_DIR

        live_dirs = sorted(
            d.name
            for d in _DEMO_DOMAINS_DIR.iterdir()
            if d.is_dir() and (d / "sources.yaml").is_file()
        )
        assert live_dirs == _list_demo_domains()
