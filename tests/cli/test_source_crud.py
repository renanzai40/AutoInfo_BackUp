"""Tests for Source CRUD — CLI commands and MCP tool handlers.

Covers:

- CLI: ``autoinfo sources add | list | remove | test | add-sources``
- MCP:  ``_handle_add_source`` validation (URL format, type enum, idempotency)
- Config persistence: modifications are written to and readable from YAML
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from autoinfo.config import load_config
from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.errors import ErrorCode
from autoinfo.mcp.server import (
    _handle_add_source,
    _handle_list_sources,
    _handle_remove_source,
    _handle_test_source,
)

# NOTE: CLI tests use a standalone Typer app instead of autoinfo.cli.app
# because Typer 0.27.0 has a Python 3.14 compatibility issue when
# inspecting functions whose parameters shadow builtins (e.g. ``def list``
# with ``list[str]`` annotations in kb.py).  This is a pre-existing
# codebase issue, not introduced here.
from autoinfo.cli.sources import app as _sources_app

# ======================================================================
# Sample config for tests
# ======================================================================

_SAMPLE_CONFIG = {
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
            "topics": [{"name": "IVF breakthroughs", "keywords": ["IVF", "embryo"]}],
        }
    ],
}

_MINIMAL_CONFIG = {
    "project": {"name": "Test", "created_at": ""},
    "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": ""},
    "domains": [
        {
            "name": "test-domain",
            "active": True,
            "sources": [],
            "topics": [],
        }
    ],
}

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary project with ``.autoinfo/config.yaml``.

    Changes CWD so that ``_load_config`` / ``get_config_path`` pick up
    the temporary config.  Restores CWD after the test.
    """
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_SAMPLE_CONFIG, fh, default_flow_style=False)

    cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


@pytest.fixture
def empty_domain_config(tmp_path: Path) -> Path:
    """Config with a single domain that has zero sources."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_MINIMAL_CONFIG, fh, default_flow_style=False)

    cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a CliRunner for CLI invocation tests."""
    return CliRunner()


# ======================================================================
# MCP: _validate_url / _validate_source_type (validation helpers)
# ======================================================================


class TestMCPValidation:
    def test_validate_url_valid(self) -> None:
        assert mcp_server._validate_url("https://example.com") is None
        assert mcp_server._validate_url("http://example.com/rss") is None

    def test_validate_url_missing_protocol(self) -> None:
        err = mcp_server._validate_url("ftp://bad.com")
        assert err is not None
        assert "http" in err.lower()

    def test_validate_url_empty(self) -> None:
        err = mcp_server._validate_url("")
        assert err is not None

    def test_validate_url_no_host(self) -> None:
        err = mcp_server._validate_url("https://")
        assert err is not None

    def test_validate_type_valid(self) -> None:
        assert mcp_server._validate_source_type("rss") is None
        assert mcp_server._validate_source_type("api") is None
        assert mcp_server._validate_source_type("web") is None

    def test_validate_type_invalid(self) -> None:
        err = mcp_server._validate_source_type("ftp")
        assert err is not None
        assert "rss" in err
        assert "api" in err
        assert "web" in err

    def test_validate_type_empty(self) -> None:
        err = mcp_server._validate_source_type("")
        assert err is not None


# ======================================================================
# MCP: _handle_add_source
# ======================================================================


class TestMCPAddSource:
    def test_adds_new_source(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="new-feed", url="https://example.com/rss", type="rss", domain="medical-research"
        )
        assert result["created"] is True
        assert result["source"]["name"] == "new-feed"
        assert result["source_id"] == "medical-research:new-feed"

    def test_idempotent_same_url_and_type(self, tmp_config: Path) -> None:
        r1 = _handle_add_source(
            name="first", url="https://example.com/dup", type="api", domain="medical-research"
        )
        assert r1["created"] is True

        r2 = _handle_add_source(
            name="second", url="https://example.com/dup", type="api", domain="medical-research"
        )
        assert r2["created"] is False
        assert r2["source"]["name"] == "first"  # keeps original name

    def test_rejects_invalid_url(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="bad", url="not-a-url", type="api", domain="medical-research"
        )
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"

    def test_rejects_invalid_type(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="bad", url="https://example.com", type="smtp", domain="medical-research"
        )
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"

    def test_unknown_domain(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="test", url="https://example.com", domain="nonexistent"
        )
        assert result["error_code"] == "DomainNotFound"

    def test_persists_to_config(self, tmp_config: Path) -> None:
        _handle_add_source(
            name="persist-check",
            url="https://example.com/persist",
            type="web",
            domain="medical-research",
        )
        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {s.name for s in domain.sources}
        assert "persist-check" in names


# ======================================================================
# MCP: _handle_list_sources
# ======================================================================


class TestMCPListSources:
    def test_lists_sources(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="medical-research")
        assert result["count"] >= 1
        names = {s["name"] for s in result["sources"]}
        assert "pubmed" in names

    def test_sources_include_source_id(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="medical-research")
        for s in result["sources"]:
            assert "source_id" in s
            assert s["source_id"].startswith("medical-research:")

    def test_unknown_domain_returns_error(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="nope")
        assert result.get("error_code") == "DomainNotFound"


# ======================================================================
# MCP: _handle_remove_source
# ======================================================================


class TestMCPRemoveSource:
    def test_removes_existing_source(self, tmp_config: Path) -> None:
        _handle_add_source(
            name="to-remove", url="https://example.com/remove", type="api", domain="medical-research"
        )
        result = _handle_remove_source(source_id="medical-research:to-remove")
        assert result["removed"] is True

    def test_removed_source_gone_from_config(self, tmp_config: Path) -> None:
        _handle_add_source(
            name="gone-soon", url="https://example.com/gone", type="api", domain="medical-research"
        )
        _handle_remove_source(source_id="medical-research:gone-soon")
        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {s.name for s in domain.sources}
        assert "gone-soon" not in names

    def test_returns_error_for_nonexistent(self, tmp_config: Path) -> None:
        result = _handle_remove_source(source_id="medical-research:ghost")
        assert result.get("error_code") == "SourceNotFound"

    def test_rejects_malformed_id(self, tmp_config: Path) -> None:
        result = _handle_remove_source(source_id="bad-id-no-colon")
        assert "InvalidSourceId" in result.get("error_code", "")


# ======================================================================
# MCP: _handle_test_source
# ======================================================================


class TestMCPTestSource:
    def test_rejects_invalid_url(self) -> None:
        result = _handle_test_source(url="invalid")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert result["error"]["actionable"] is True

    def test_rejects_invalid_type(self) -> None:
        result = _handle_test_source(url="https://example.com", type="bad")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert result["error"]["actionable"] is True

    def test_timeout_returns_structured_error(self) -> None:
        from httpx import TimeoutException

        with patch("httpx.get", side_effect=TimeoutException("timed out")):
            result = _handle_test_source(url="https://slow.example.com")
            assert result["success"] is False
            assert result["error"]["code"] == ErrorCode.TIMEOUT.value
            assert result["error"]["actionable"] is True

    def test_successful_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"key": "value"}'
        mock_resp.content = b'{"key": "value"}'

        with patch("httpx.get", return_value=mock_resp):
            result = _handle_test_source(url="https://api.example.com/data")
            assert result["reachable"] is True
            assert result["status_code"] == 200
            assert result["format"] == "json"


# ======================================================================
# CLI: autoinfo sources add
# ======================================================================


class TestCLIAdd:
    def test_adds_source(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        result = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "cli-feed",
                "--url", "https://cli.example.com/rss",
                "--type", "rss",
                "--domain", "medical-research",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "added" in result.stdout.lower()

    def test_add_persists_to_yaml(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "yaml-check",
                "--url", "https://yaml.example.com",
                "--type", "web",
                "--domain", "medical-research",
            ],
        )
        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {s.name for s in domain.sources}
        assert "yaml-check" in names

    def test_idempotent_add(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        r1 = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "dup-cli",
                "--url", "https://dup.example.com",
                "--type", "api",
                "--domain", "medical-research",
            ],
        )
        assert r1.exit_code == 0, r1.stdout

        r2 = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "dup-cli-2",
                "--url", "https://dup.example.com",
                "--type", "api",
                "--domain", "medical-research",
            ],
        )
        assert r2.exit_code == 0, r2.stdout
        assert "already exists" in r2.stdout.lower()

    def test_rejects_invalid_url(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        result = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "bad",
                "--url", "not-a-url",
                "--type", "api",
                "--domain", "medical-research",
            ],
        )
        assert result.exit_code != 0
        output = result.output.lower()
        assert "http" in output or "error" in output

    def test_rejects_invalid_type(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        result = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "bad",
                "--url", "https://example.com",
                "--type", "invalid-type",
                "--domain", "medical-research",
            ],
        )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_unknown_domain(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        result = cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "test",
                "--url", "https://example.com",
                "--type", "api",
                "--domain", "nonexistent",
            ],
        )
        assert result.exit_code != 0
        assert "not configured" in result.output.lower()


# ======================================================================
# CLI: autoinfo sources list
# ======================================================================


class TestCLIList:
    def test_lists_sources(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        result = cli_runner.invoke(
            _sources_app, ["list", "--domain", "medical-research"]
        )
        assert result.exit_code == 0, result.stdout
        assert "pubmed" in result.stdout

    def test_json_output(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        result = cli_runner.invoke(
            _sources_app, ["list", "--domain", "medical-research", "--json"]
        )
        assert result.exit_code == 0, result.stdout
        data = json.loads(result.stdout)
        assert "domain" in data
        assert "sources" in data
        assert data["count"] >= 1

    def test_empty_list(self, cli_runner: CliRunner, empty_domain_config: Path) -> None:
        result = cli_runner.invoke(
            _sources_app, ["list", "--domain", "test-domain"]
        )
        assert result.exit_code == 0, result.stdout
        assert "no sources" in result.stdout.lower()

    def test_unknown_domain(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        result = cli_runner.invoke(
            _sources_app, ["list", "--domain", "unknown"]
        )
        assert result.exit_code != 0
        assert "not configured" in result.output.lower()


# ======================================================================
# CLI: autoinfo sources remove
# ======================================================================


class TestCLIRemove:
    def test_removes_source(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        # First add one
        cli_runner.invoke(
            _sources_app,
            [
                "add",
                "--name", "to-delete",
                "--url", "https://delete.example.com",
                "--type", "api",
                "--domain", "medical-research",
            ],
        )
        # Then remove
        result = cli_runner.invoke(
            _sources_app,
            ["remove", "--source-id", "medical-research:to-delete"],
        )
        assert result.exit_code == 0, result.stdout
        assert "removed" in result.stdout.lower()

    def test_remove_nonexistent(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        result = cli_runner.invoke(
            _sources_app,
            ["remove", "--source-id", "medical-research:phantom"],
        )
        assert result.exit_code != 0

    def test_remove_bad_format(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        result = cli_runner.invoke(
            _sources_app, ["remove", "--source-id", "bad-format"]
        )
        assert result.exit_code != 0


# ======================================================================
# CLI: autoinfo sources test
# ======================================================================


class TestCLITest:
    def test_rejects_invalid_url(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(
            _sources_app, ["test", "--url", "bad", "--type", "api"]
        )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_rejects_invalid_type(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(
            _sources_app,
            ["test", "--url", "https://example.com", "--type", "nope"],
        )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    @patch("httpx.get")
    def test_successful_test(
        self, mock_get: MagicMock, cli_runner: CliRunner
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"ok": true}'
        mock_resp.content = b'{"ok": true}'
        mock_get.return_value = mock_resp

        result = cli_runner.invoke(
            _sources_app,
            ["test", "--url", "https://api.example.com", "--type", "api"],
        )
        assert result.exit_code == 0, result.stdout
        assert "200" in result.stdout
        assert "json" in result.stdout.lower()


# ======================================================================
# CLI: autoinfo sources add-sources (batch)
# ======================================================================


class TestCLIAddSources:
    def test_batch_add(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        sources = [
            {"name": "batch-a", "url": "https://a.example.com", "type": "api", "domain": "medical-research"},
            {"name": "batch-b", "url": "https://b.example.com", "type": "rss", "domain": "medical-research"},
        ]
        json_path = Path.cwd() / "batch_sources.json"
        json_path.write_text(json.dumps(sources), encoding="utf-8")

        result = cli_runner.invoke(
            _sources_app, ["add-sources", "--file", str(json_path)]
        )
        assert result.exit_code == 0, result.stdout
        assert "added" in result.stdout.lower()
        assert "batch" in result.stdout.lower()

    def test_batch_add_invalid_source(
        self, cli_runner: CliRunner, tmp_config: Path
    ) -> None:
        sources = [
            {"name": "good", "url": "https://good.example.com", "domain": "medical-research"},
            {"name": "bad", "url": "bad-url", "domain": "medical-research"},
        ]
        json_path = Path.cwd() / "batch_mixed.json"
        json_path.write_text(json.dumps(sources), encoding="utf-8")

        result = cli_runner.invoke(
            _sources_app, ["add-sources", "--file", str(json_path)]
        )
        assert result.exit_code == 0, result.stdout
        assert "added" in result.stdout.lower()

    def test_batch_file_not_found(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(
            _sources_app, ["add-sources", "--file", "/nonexistent/sources.json"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_batch_invalid_json(self, cli_runner: CliRunner, tmp_config: Path) -> None:
        json_path = Path.cwd() / "bad.json"
        json_path.write_text("not json", encoding="utf-8")

        result = cli_runner.invoke(
            _sources_app, ["add-sources", "--file", str(json_path)]
        )
        assert result.exit_code != 0
        output = result.output.lower()
        assert "invalid json" in output or "error" in output
