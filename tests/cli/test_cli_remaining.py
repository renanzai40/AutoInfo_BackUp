"""Tests for remaining CLI commands: sources health, kb list-tiers, output list-templates.

Uses ``CliRunner`` and patches to verify command registration, help text,
and basic functional paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_runner() -> Any:
    """Return a CliRunner instance."""
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with a valid config."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.dump({
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
    }), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# autoinfo sources health
# ---------------------------------------------------------------------------


class TestSourcesHealth:
    """Tests for ``autoinfo sources health`` command."""

    def test_health_shows_in_sources_help(self, cli_runner: Any) -> None:
        """``autoinfo sources --help`` lists the health subcommand."""
        result = cli_runner.invoke(app, ["sources", "--help"])
        assert result.exit_code == 0
        assert "health" in result.stdout

    def test_health_help_shows_options(self, cli_runner: Any) -> None:
        """``autoinfo sources health --help`` shows --source-id and --json."""
        result = cli_runner.invoke(app, ["sources", "health", "--help"])
        assert result.exit_code == 0
        assert "--source-id" in result.stdout
        assert "--json" in result.stdout

    def test_health_requires_source_id(self, cli_runner: Any) -> None:
        """Without --source-id, the command should fail."""
        result = cli_runner.invoke(app, ["sources", "health"])
        assert result.exit_code != 0

    def test_health_dispatches_to_get_source_health(
        self, cli_runner: Any, tmp_project: Path
    ) -> None:
        """With valid args, it calls get_source_health and prints status."""
        from autoinfo.status import get_source_health

        mock_result = {
            "source_id": "medical-research:pubmed",
            "status": "healthy",
            "total_runs": 12,
            "last_run": "2026-07-20T10:00:00Z",
            "latency_ms": 123.4,
        }

        with (
            patch("autoinfo.cli.sources.get_source_health", return_value=mock_result) as mock_fn,
            patch("autoinfo.config.get_config_path", return_value=tmp_project / ".autoinfo" / "config.yaml"),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "sources",
                    "health",
                    "--source-id",
                    "medical-research:pubmed",
                ],
            )
        assert result.exit_code == 0
        assert "healthy" in result.stdout
        assert "medical-research:pubmed" in result.stdout
        mock_fn.assert_called_once_with(source_id="medical-research:pubmed")

    def test_health_json_output(
        self, cli_runner: Any, tmp_project: Path
    ) -> None:
        """With --json flag, output is valid JSON."""
        mock_result = {
            "source_id": "medical-research:pubmed",
            "status": "healthy",
            "total_runs": 12,
        }

        with (
            patch("autoinfo.cli.sources.get_source_health", return_value=mock_result),
            patch("autoinfo.config.get_config_path", return_value=tmp_project / ".autoinfo" / "config.yaml"),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "sources",
                    "health",
                    "--source-id",
                    "medical-research:pubmed",
                    "--json",
                ],
            )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["status"] == "healthy"

    def test_health_handles_error(
        self, cli_runner: Any, tmp_project: Path
    ) -> None:
        """When get_source_health raises, the CLI shows an error and exits 1."""
        with (
            patch(
                "autoinfo.cli.sources.get_source_health",
                side_effect=RuntimeError("Connection failed"),
            ),
            patch("autoinfo.config.get_config_path", return_value=tmp_project / ".autoinfo" / "config.yaml"),
        ):
            result = cli_runner.invoke(
                app,
                ["sources", "health", "--source-id", "medical-research:pubmed"],
            )
        assert result.exit_code == 1
        assert "Connection failed" in result.stdout


# ---------------------------------------------------------------------------
# autoinfo kb list-tiers
# ---------------------------------------------------------------------------


class TestKbListTiers:
    """Tests for ``autoinfo kb list-tiers`` command."""

    def test_list_tiers_shows_in_kb_help(self, cli_runner: Any) -> None:
        """``autoinfo kb --help`` lists the list-tiers subcommand."""
        result = cli_runner.invoke(app, ["kb", "--help"])
        assert result.exit_code == 0
        assert "list-tiers" in result.stdout

    def test_list_tiers_help_shows_options(self, cli_runner: Any) -> None:
        """``autoinfo kb list-tiers --help`` shows --domain and --json."""
        result = cli_runner.invoke(app, ["kb", "list-tiers", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.stdout
        assert "--json" in result.stdout

    def test_list_tiers_requires_domain(self, cli_runner: Any) -> None:
        """Without --domain, the command should fail."""
        result = cli_runner.invoke(app, ["kb", "list-tiers"])
        assert result.exit_code != 0

    def test_list_tiers_returns_tier_info(
        self, cli_runner: Any, tmp_project: Path
    ) -> None:
        """With a valid domain, list-tiers prints the three standard tiers."""
        with (
            patch("autoinfo.kb.KBStore") as MockStore,
            patch("autoinfo.config.get_config_path", return_value=tmp_project / ".autoinfo" / "config.yaml"),
        ):
            instance = MockStore.return_value
            instance.count_entries_by_tier.return_value = 0

            result = cli_runner.invoke(
                app,
                ["kb", "list-tiers", "--domain", "medical-research"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "01-Raw" in result.stdout
        assert "02-Draft" in result.stdout
        assert "03-Wiki" in result.stdout

    def test_list_tiers_json_output(
        self, cli_runner: Any, tmp_project: Path
    ) -> None:
        """With --json, output is valid JSON with tier info."""
        with (
            patch("autoinfo.kb.KBStore") as MockStore,
            patch("autoinfo.config.get_config_path", return_value=tmp_project / ".autoinfo" / "config.yaml"),
        ):
            instance = MockStore.return_value
            instance.count_entries_by_tier.return_value = 0

            result = cli_runner.invoke(
                app,
                ["kb", "list-tiers", "--domain", "medical-research", "--json"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        assert parsed["count"] == 3
        tiers = {item["tier"] for item in parsed["items"]}
        assert "01-Raw" in tiers
        assert "02-Draft" in tiers
        assert "03-Wiki" in tiers


# ---------------------------------------------------------------------------
# autoinfo output list-templates
# ---------------------------------------------------------------------------


class TestOutputListTemplates:
    """Tests for ``autoinfo output list-templates`` command."""

    def test_list_templates_shows_in_output_help(self, cli_runner: Any) -> None:
        """``autoinfo output --help`` lists the list-templates subcommand."""
        result = cli_runner.invoke(app, ["output", "--help"])
        assert result.exit_code == 0
        assert "list-templates" in result.stdout

    def test_list_templates_help_shows_options(self, cli_runner: Any) -> None:
        """``autoinfo output list-templates --help`` shows --domain and --json."""
        result = cli_runner.invoke(app, ["output", "list-templates", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.stdout
        assert "--json" in result.stdout

    def test_list_templates_returns_known_types(self, cli_runner: Any) -> None:
        """list-templates returns the standard template types."""
        result = cli_runner.invoke(
            app,
            ["output", "list-templates"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "digest" in result.stdout
        assert "report" in result.stdout
        assert "tutorial" in result.stdout
        assert "presentation" in result.stdout

    def test_list_templates_with_domain(self, cli_runner: Any) -> None:
        """When a domain is specified, it's shown in the output."""
        result = cli_runner.invoke(
            app,
            ["output", "list-templates", "--domain", "medical-research"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "digest" in result.stdout

    def test_list_templates_json_output(self, cli_runner: Any) -> None:
        """With --json, output is valid JSON."""
        result = cli_runner.invoke(
            app,
            ["output", "list-templates", "--json"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "templates" in parsed
        names = {t["name"] for t in parsed["templates"]}
        assert "digest" in names
        assert "count" in parsed
