"""Backward-compatibility tests for v0.1.1.

Verifies that all v0.1 behaviour is preserved after the v0.1.1 changes
(config expansion, CLI stubs, MCP tools) and that the new schema fields
have safe defaults when loading old configuration files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.cli import app
from autoinfo.config import LLMConfig, load_config
from autoinfo.mcp import server as mcp_server

# ---------------------------------------------------------------------------
# v0.1-format config: does NOT have ``tasks`` or ``fallback`` keys
# ---------------------------------------------------------------------------

V01_CONFIG = {
    "project": {"name": "v0.1 Project", "created_at": "2026-07-01"},
    "llm": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "api_key": "sk-old-key",
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
            "topics": [{"name": "IVF breakthroughs", "keywords": ["IVF", "embryo"]}],
        }
    ],
}

# ---------------------------------------------------------------------------
# v0.1.1-format config: includes ``tasks`` and ``fallback``
# ---------------------------------------------------------------------------

V011_CONFIG = {
    "project": {"name": "v0.1.1 Project", "created_at": "2026-07-20"},
    "llm": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "api_key": "sk-new-key",
        # New v0.1.1 fields
        "fallback": [
            {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-fallback"}
        ],
        "tasks": {
            "extraction": {
                "model": "gpt-4o",
                "provider": "openai",
                "max_tokens": 4096,
            },
            "summarization": {
                "model": "deepseek/deepseek-chat",
                "provider": "openrouter",
                "max_tokens": 2048,
            },
        },
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
            "topics": [{"name": "IVF breakthroughs", "keywords": ["IVF", "embryo"]}],
        }
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(root: Path, config_dict: dict[str, Any]) -> Path:
    """Write ``.autoinfo/config.yaml`` under *root* and return its path."""
    config_dir = root / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(config_dict, fh, default_flow_style=False, sort_keys=False)
    return config_path


# ===================================================================
# 1. Old config still loads
# ===================================================================


class TestOldConfigStillLoads:
    """v0.1-format configs (without tasks/fallback) load without error."""

    def test_old_config_loads_successfully(self, tmp_path: Path) -> None:
        """``load_config()`` succeeds for a v0.1-format config."""
        cfg_path = _write_config(tmp_path, V01_CONFIG)
        cfg = load_config(cfg_path)

        # -- Old fields still work --
        assert cfg.project.name == "v0.1 Project"
        assert cfg.llm.provider == "openrouter"
        assert cfg.llm.model == "deepseek/deepseek-chat"
        assert cfg.llm.api_key == "sk-old-key"
        assert len(cfg.domains) == 1
        assert cfg.domains[0].name == "medical-research"
        assert len(cfg.domains[0].sources) == 1
        assert cfg.domains[0].sources[0].name == "pubmed"

    def test_old_config_has_new_field_defaults(self, tmp_path: Path) -> None:
        """New fields ``tasks`` and ``fallback`` default to empty."""
        cfg_path = _write_config(tmp_path, V01_CONFIG)
        cfg = load_config(cfg_path)

        # tasks and fallback are new v0.1.1 fields — absent in old configs
        assert cfg.llm.tasks == {}, (
            f"Expected tasks to default to {{}}, got {cfg.llm.tasks!r}"
        )
        assert cfg.llm.fallback == [], (
            f"Expected fallback to default to [], got {cfg.llm.fallback!r}"
        )

    def test_old_config_validates_cleanly(self, tmp_path: Path) -> None:
        """``validate_config()`` returns empty errors for a valid old config."""
        from autoinfo.config import validate_config

        cfg_path = _write_config(tmp_path, V01_CONFIG)
        cfg = load_config(cfg_path)
        errors = validate_config(cfg)
        assert errors == [], f"Expected clean validation, got: {errors}"

    def test_old_config_with_minimal_fields(self, tmp_path: Path) -> None:
        """Minimal v0.1 config (project + llm only) still loads."""
        minimal = {
            "project": {"name": "Minimal"},
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-minimal",
            },
            "domains": [
                {
                    "name": "test-domain",
                    "active": True,
                    "sources": [{"name": "pubmed", "type": "api", "url": "https://example.com"}],
                    "topics": [],
                }
            ],
        }
        cfg_path = _write_config(tmp_path, minimal)
        cfg = load_config(cfg_path)
        assert cfg.llm.tasks == {}
        assert cfg.llm.fallback == []


# ===================================================================
# 2. New config has defaults
# ===================================================================


class TestNewConfigHasDefaults:
    """v0.1.1-format configs load and new fields have correct defaults."""

    def test_new_config_loads(self, tmp_path: Path) -> None:
        """v0.1.1 config with tasks/fallback loads successfully."""
        cfg_path = _write_config(tmp_path, V011_CONFIG)
        cfg = load_config(cfg_path)

        # Base fields still work
        assert cfg.llm.provider == "openrouter"
        assert cfg.llm.model == "deepseek/deepseek-chat"

    def test_new_config_tasks_defaults_when_absent(self, tmp_path: Path) -> None:
        """When ``llm.tasks`` is absent, it defaults to an empty dict."""
        cfg_path = _write_config(tmp_path, V01_CONFIG)
        cfg = load_config(cfg_path)
        assert cfg.llm.tasks == {}

    def test_new_config_fallback_defaults_when_absent(self, tmp_path: Path) -> None:
        """When ``llm.fallback`` is absent, it defaults to an empty list."""
        cfg_path = _write_config(tmp_path, V01_CONFIG)
        cfg = load_config(cfg_path)
        assert cfg.llm.fallback == []

    def test_llm_config_dataclass_defaults(self) -> None:
        """``LLMConfig()`` with no args produces safe defaults."""
        cfg = LLMConfig()
        assert cfg.provider == ""
        assert cfg.model == ""
        assert cfg.api_key == ""
        assert cfg.tasks == {}
        assert cfg.fallback == []

    def test_llm_task_config_defaults(self) -> None:
        """``LLMTaskConfig()`` with no args produces safe defaults."""
        from autoinfo.config import LLMTaskConfig

        tcfg = LLMTaskConfig()
        assert tcfg.model == ""
        assert tcfg.provider == ""
        assert tcfg.max_tokens == 0


# ===================================================================
# 3. All v0.1 tests still pass
# ===================================================================


class TestAllV01TestsPass:
    """Existing v0.1 test suite still passes after v0.1.1 changes."""

    V01_TEST_FILES = [
        "tests/cli/test_cli_commands.py",
        "tests/collectors/test_collection.py",
        "tests/integration/test_integration.py",
        "tests/kb/test_kb.py",
        "tests/llm/test_llm.py",
        "tests/mcp/test_mcp_server.py",
        "tests/kb/test_process.py",
        "tests/collectors/test_pubmed_handler.py",
        "tests/llm/test_quality.py",
        "tests/collectors/test_rss_handler.py",
    ]

    @pytest.mark.slow
    def test_all_v01_tests_pass(self) -> None:
        """Run all v0.1 test files as a subprocess and verify exit code 0."""
        project_root = Path(__file__).resolve().parents[2]
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *self.V01_TEST_FILES,
            "-v",
            "--tb=short",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Print output for debugging on failure
        if result.returncode != 0:
            print("=== STDOUT ===")
            print(result.stdout[-2000:])
            print("=== STDERR ===")
            print(result.stderr[-2000:])

        assert result.returncode == 0, (
            f"v0.1 test suite exited with code {result.returncode}, "
            f"expected 0. See output above."
        )

        # Verify all tests were collected (sanity check)
        assert "passed" in result.stdout, (
            "No 'passed' in pytest output — test collection may be empty"
        )


# ===================================================================
# 4. CLI stubs register correctly
# ===================================================================


class TestCliStubsRegister:
    """All expected CLI commands appear in ``autoinfo --help``."""

    EXPECTED_COMMANDS = {
        "init",
        "doctor",
        "collect",
        "process",
        "status",
        "summaries",
    }

    def test_help_lists_all_commands(self, cli_runner: Any) -> None:
        """``autoinfo --help`` lists all v0.1 commands."""
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0, (
            f"CLI --help exited with code {result.exit_code}\n"
            f"stderr: {result.stderr}"
        )

        output = result.stdout
        for cmd in sorted(self.EXPECTED_COMMANDS):
            assert cmd in output, (
                f"Command '{cmd}' not found in --help output"
            )

    def test_each_command_has_help(self, cli_runner: Any) -> None:
        """Each subcommand has its own ``--help`` that returns exit code 0."""
        for cmd in sorted(self.EXPECTED_COMMANDS):
            result = cli_runner.invoke(app, [cmd, "--help"])
            assert result.exit_code == 0, (
                f"'{cmd} --help' exited with code {result.exit_code}\n"
                f"stderr: {result.stderr}"
            )

    def test_global_json_flag_listed(self, cli_runner: Any) -> None:
        """Global ``--json`` flag appears in top-level help."""
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--json" in result.stdout, (
            "Global --json flag not listed in --help"
        )


# ===================================================================
# 5. MCP tools correct
# ===================================================================


class TestMcpNewTools:
    """MCP tool manifest includes expected tools."""

    EXPECTED_TOOLS = {
        "health_check",
        "diagnose_system",
        "collect_sources",
        "process_collection",
        "list_summaries",
        "get_kb_entry",
    }

    @pytest.mark.asyncio
    async def test_tool_count(self) -> None:
        """MCP server lists the expected number of tools."""
        tools = await mcp_server.list_tools()
        assert len(tools) >= 6, (
            f"Expected at least 6 tools, got {len(tools)}"
        )

    @pytest.mark.asyncio
    async def test_tool_names(self) -> None:
        """All expected tool names are present in the manifest."""
        tools = await mcp_server.list_tools()
        tool_names = {t.name for t in tools}
        assert self.EXPECTED_TOOLS.issubset(tool_names), (
            f"Missing tools: {self.EXPECTED_TOOLS - tool_names}"
        )

    @pytest.mark.asyncio
    async def test_each_tool_has_description(self) -> None:
        """Every tool has a non-empty description."""
        tools = await mcp_server.list_tools()
        for tool in tools:
            assert tool.description, (
                f"Tool '{tool.name}' has empty description"
            )

    @pytest.mark.asyncio
    async def test_each_tool_has_input_schema(self) -> None:
        """Every tool declares an input schema."""
        tools = await mcp_server.list_tools()
        for tool in tools:
            assert tool.inputSchema is not None, (
                f"Tool '{tool.name}' has no inputSchema"
            )
            assert tool.inputSchema.get("type") == "object", (
                f"Tool '{tool.name}' inputSchema type is not 'object'"
            )

    @pytest.mark.asyncio
    async def test_health_check_tools_count(self) -> None:
        """``health_check`` tool returns a tools_count >= 6."""
        result = mcp_server._handle_health_check()
        assert result["tools_count"] >= 6, (
            f"Expected tools_count >= 6, got {result['tools_count']}"
        )


# ===================================================================
# 6. Integration: init → config load
# ===================================================================


class TestInitIntegration:
    """``autoinfo init --demo medical-research`` produces a loadable config."""

    def test_init_exit_code_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``autoinfo init --demo medical-research`` exits 0."""
        from typer.testing import CliRunner

        from autoinfo.cli import app

        # TRIAGE #60 (regression) + cwd-leak fix: #106 (79b188a) moved the
        # runtime dirs from `.autoinfo/knowledge/...` to project root
        # (`src/autoinfo/cli/init.py:135-140`). monkeypatch.chdir restores
        # cwd after the test (leaked chdir broke test_bug_40).
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["init", "--demo", "medical-research"])
        assert result.exit_code == 0, f"init failed: {result.output}"

        config_path = tmp_path / ".autoinfo" / "config.yaml"
        assert config_path.is_file(), "config.yaml was not created"
        assert (tmp_path / "knowledge" / "01-Raw").is_dir()
        assert (tmp_path / "collections").is_dir()
        assert (tmp_path / "outputs").is_dir()

    def test_init_config_loads_with_new_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Generated config loads with new schema (tasks/fallback have defaults)."""
        from typer.testing import CliRunner

        from autoinfo.cli import app

        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["init", "--demo", "medical-research"])
        assert result.exit_code == 0, f"init failed: {result.output}"
        config_path = tmp_path / ".autoinfo" / "config.yaml"

        # Load via the new config loader
        cfg = load_config(config_path)

        # Old fields still work
        assert cfg.llm.provider == "openrouter"
        assert "deepseek" in cfg.llm.model

        # New fields have defaults
        assert cfg.llm.tasks == {}, (
            f"Expected tasks={{}}, got {cfg.llm.tasks!r}"
        )
        assert cfg.llm.fallback == [], (
            f"Expected fallback=[], got {cfg.llm.fallback!r}"
        )

        # Domain structure is intact
        assert len(cfg.domains) == 1
        assert cfg.domains[0].name == "medical-research"

    def test_init_config_validates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generated config passes validation."""
        from autoinfo.cli.init import init
        from autoinfo.config import validate_config

        # TRIAGE #61 (regression): direct `init(demo=...)` call leaves the
        # `--list-domains` OptionInfo object truthy (`src/autoinfo/cli/init.py:194-198`)
        # → prints usage and creates nothing. Pass the flag explicitly.
        monkeypatch.chdir(tmp_path)
        init(demo=["medical-research"], list_domains=False, name="")
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        cfg = load_config(config_path)
        errors = validate_config(cfg)
        assert errors == [], f"Validation errors on init-generated config: {errors}"


# ===================================================================
# 7. Collect + process smoke test (mocked)
# ===================================================================


class TestCollectProcessPipeline:
    """Collect + process pipeline works with new config schema."""

    DOMAIN = "medical-research"

    SAMPLE_ITEMS = [
        {
            "id": "pmid-bc-001",
            "source_name": "pubmed",
            "source_type": "api",
            "source_platform": "pubmed",
            "source_url": "https://example.com/bc-1",
            "title": "Backward compat test article 1",
            "content": "Content about IVF treatment and embryo selection.",
            "collected_at": "2026-07-20T10:00:00Z",
        },
        {
            "id": "pmid-bc-002",
            "source_name": "pubmed",
            "source_type": "api",
            "source_platform": "pubmed",
            "source_url": "https://example.com/bc-2",
            "title": "Backward compat test article 2",
            "content": "Content about neuroplasticity and brain development.",
            "collected_at": "2026-07-20T11:00:00Z",
        },
    ]

    def _prepare_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Create project with v0.1.1 config (with tasks/fallback)."""
        monkeypatch.chdir(tmp_path)
        _write_config(tmp_path, V011_CONFIG)
        (tmp_path / "collections").mkdir(exist_ok=True)
        (tmp_path / "knowledge").mkdir(exist_ok=True)

    def test_collect_smoke(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Collection runs without error with new config."""
        self._prepare_project(tmp_path, monkeypatch)

        from autoinfo.collect import run_collection
        from autoinfo.models import Item

        sample_items = [Item(**item) for item in self.SAMPLE_ITEMS]

        with patch("autoinfo.collect._fetch_items", return_value=sample_items):
            result = run_collection(
                domain=self.DOMAIN,
                topic="IVF",
                limit=10,
                dry_run=False,
            )

        # #177: the topic-keyword relevance filter is source-type aware — it
        # applies only to cross-disciplinary search platforms (OpenAlex,
        # Semantic Scholar, CrossRef, ...). PubMed is a topical provider API,
        # so neither article is keyword-filtered.
        assert result["total_found"] == 2
        assert result["total_new"] == 2
        assert result["items_filtered"] == 0
        assert result["domain"] == self.DOMAIN
        assert result["dry_run"] is False

    def test_process_smoke(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Processing runs without error with new config."""
        self._prepare_project(tmp_path, monkeypatch)

        from autoinfo.collect import run_collection
        from autoinfo.models import Item
        from autoinfo.process import run_processing

        sample_items = [Item(**item) for item in self.SAMPLE_ITEMS]

        # Collect first
        with patch("autoinfo.collect._fetch_items", return_value=sample_items):
            run_collection(domain=self.DOMAIN, topic="IVF", limit=10, dry_run=False)

        # Mock LLM for processing
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "tl_dr": "Test backward compat summary.",
            "key_points": ["Point 1", "Point 2"],
            "entities": [],
            "relevance_score": 85.0,
        })
        # TRIAGE #62 (regression): cost-meter MagicMock binding
        # (`process.py:690` → `cost.py:159`) — real int token counters so
        # `CostMeter().log_llm_tokens` gets ints, not MagicMocks.
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_llm.completion.return_value = mock_response

        from autoinfo.llm import LLMExtractor

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_llm):
            proc_result = run_processing(domain=self.DOMAIN)

        assert proc_result.total_items >= 1
        assert proc_result.kb_entries_created >= 1
        assert proc_result.errors == []

    def test_collect_dry_run_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dry-run collection works with new config."""
        self._prepare_project(tmp_path, monkeypatch)

        from autoinfo.collect import run_collection
        from autoinfo.models import Item

        sample_items = [Item(**item) for item in self.SAMPLE_ITEMS]

        with patch("autoinfo.collect._fetch_items", return_value=sample_items):
            result = run_collection(
                domain=self.DOMAIN,
                topic="IVF",
                limit=10,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["total_found"] == 2
        # No file should have been cached
        cached = list(Path("collections").rglob("*.json")) if Path("collections").exists() else []
        assert len(cached) == 0, "Dry-run should not create cached files"
