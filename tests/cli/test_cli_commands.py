"""Tests for CLI commands: status, doctor, summaries.

Uses ``CliRunner`` and mocks to avoid side effects like HTTP calls or
SQLite database files.  Working directory changes are handled by
patching ``autoinfo.config.get_config_path`` or by invoking from a
temp directory without a config.
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
# Sample test data
# ---------------------------------------------------------------------------

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

_MOCK_STATUS_RESULT = {
    "domains": [
        {
            "name": "medical-research",
            "items_today": 5,
            "total_entries": 42,
            "source_health": [
                {
                    "name": "pubmed",
                    "status": "healthy",
                    "last_run": "2026-07-20T10:00:00Z",
                    "total_runs": 12,
                }
            ],
        }
    ],
}

_MOCK_DOCTOR_RESULT = {
    "python": {"status": "ok", "version": "3.11.5"},
    "config": {
        "status": "ok",
        "path": "/tmp/.autoinfo/config.yaml",
        "errors": [],
    },
    "llm": {
        "status": "ok",
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "key_configured": True,
    },
    "sources": [
        {"name": "pubmed", "status": "ok", "latency_ms": 123.4},
    ],
}

_MOCK_DOCTOR_FAILED = {
    "python": {"status": "ok", "version": "3.11.0"},
    "config": {
        "status": "error",
        "path": None,
        "errors": ["No configuration file found"],
    },
    "llm": {
        "status": "error",
        "provider": "",
        "model": "",
        "key_configured": False,
    },
    "sources": [],
}

_MOCK_SUMMARIES_ENTRIES = [
    {
        "entry_id": "kb-entry-001",
        "title": "Improved IVF outcomes with time-lapse embryo imaging",
        "domain": "medical-research",
        "summary": (
            "A large RCT showing time-lapse imaging improves live birth rates "
            "(48.2% vs 39.5%)."
        ),
        "relevance_score": 92.0,
        "collected_at": "2026-07-15T10:30:00Z",
        "source_url": "https://example.com/article1",
        "source_type": "api",
        "source_platform": "pubmed",
        "quality_tier": 1,
        "dedup_status": "unique",
        "file_path": "",
        "tags": '["IVF", "embryo imaging"]',
    },
    {
        "entry_id": "kb-entry-002",
        "title": "CRISPR-based gene editing in human embryos",
        "domain": "medical-research",
        "summary": "Review of ethical and technical challenges in embryo gene editing.",
        "relevance_score": 78.5,
        "collected_at": "2026-07-14T08:15:00Z",
        "source_url": "https://example.com/article2",
        "source_type": "api",
        "source_platform": "pubmed",
        "quality_tier": 1,
        "dedup_status": "unique",
        "file_path": "",
        "tags": '["CRISPR", "gene editing"]',
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a valid ``.autoinfo/config.yaml``.

    Returns the path to the config file.
    """
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_SAMPLE_CONFIG, fh, default_flow_style=False)
    return config_path


@pytest.fixture
def cli_runner() -> Any:
    """Return a CliRunner instance."""
    from typer.testing import CliRunner

    return CliRunner()


# ---------------------------------------------------------------------------
# autoinfo status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Tests for ``autoinfo status``."""

    @patch("autoinfo.status.show_status")
    def test_status_human_default(
        self, mock_show: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """Status produces human-readable output with domain name."""
        mock_show.return_value = _MOCK_STATUS_RESULT

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "medical-research" in result.stdout
        assert "5" in result.stdout  # items_today
        assert "42" in result.stdout  # total_entries
        assert "healthy" in result.stdout

    @patch("autoinfo.status.show_status")
    def test_status_json(
        self, mock_show: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """--json flag produces parseable JSON."""
        mock_show.return_value = _MOCK_STATUS_RESULT

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(app, ["status", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "domains" in data
        assert data["domains"][0]["name"] == "medical-research"
        assert data["domains"][0]["items_today"] == 5
        assert data["domains"][0]["total_entries"] == 42

    @patch("autoinfo.status.show_status")
    def test_status_json_output_flag(
        self, mock_show: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """Verify that --json output is properly formatted JSON."""
        mock_show.return_value = _MOCK_STATUS_RESULT

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(app, ["status", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        # Validate structure
        assert isinstance(data["domains"], list)
        domain = data["domains"][0]
        assert "items_today" in domain
        assert "total_entries" in domain
        assert "source_health" in domain
        assert isinstance(domain["source_health"], list)

    @patch("autoinfo.status.show_status")
    def test_status_domain_filter(
        self, mock_show: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """--domain filter is passed to show_status()."""
        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(
                app,
                ["status", "--domain", "medical-research"],
            )

        assert result.exit_code == 0
        mock_show.assert_called_once_with(domain="medical-research")

    def test_status_no_config_shows_friendly_error(
        self, cli_runner: Any, tmp_path: Path
    ) -> None:
        """Without config, status prints a friendly error (not traceback)."""
        # Patch at the usage site because status.py imports get_config_path at module level
        with patch("autoinfo.status.get_config_path", return_value=None):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# autoinfo doctor
# ---------------------------------------------------------------------------


class TestDoctorCommand:
    """Tests for ``autoinfo doctor``."""

    @patch("autoinfo.doctor.run_doctor")
    def test_doctor_human_ok(
        self, mock_run: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """Doctor with healthy system shows check indicators."""
        mock_run.return_value = _MOCK_DOCTOR_RESULT

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Python" in result.stdout
        assert "Config" in result.stdout
        assert "LLM" in result.stdout
        assert "Sources" in result.stdout

    @patch("autoinfo.doctor.run_doctor")
    def test_doctor_json(
        self, mock_run: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """--json flag produces parseable JSON."""
        mock_run.return_value = _MOCK_DOCTOR_RESULT

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(app, ["doctor", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["python"]["status"] == "ok"
        assert data["config"]["status"] == "ok"
        assert data["llm"]["key_configured"] is True
        assert len(data["sources"]) == 1

    @patch("autoinfo.doctor.run_doctor")
    def test_doctor_detects_missing_config(
        self, mock_run: MagicMock, cli_runner: Any, tmp_path: Path
    ) -> None:
        """Doctor exits with error when config is missing."""
        mock_run.return_value = _MOCK_DOCTOR_FAILED

        with patch("autoinfo.config.get_config_path", return_value=None):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 1
        assert "Config" in result.output
        assert "No configuration file found" in result.output

    @patch("autoinfo.doctor.run_doctor")
    def test_doctor_json_detects_missing_config(
        self, mock_run: MagicMock, cli_runner: Any, tmp_path: Path
    ) -> None:
        """Doctor --json returns error status for missing config."""
        mock_run.return_value = _MOCK_DOCTOR_FAILED

        with patch("autoinfo.config.get_config_path", return_value=None):
            result = cli_runner.invoke(app, ["doctor", "--json"])

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["config"]["status"] == "error"
        assert data["llm"]["key_configured"] is False


# ---------------------------------------------------------------------------
# autoinfo summaries
# ---------------------------------------------------------------------------


class TestSummariesCommand:
    """Tests for ``autoinfo summaries``."""

    @patch("autoinfo.kb.KBStore")
    def test_summaries_human(
        self, mock_kb_store: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """Summaries lists entries in human-readable format."""
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _MOCK_SUMMARIES_ENTRIES
        mock_kb_store.return_value = mock_store

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(
                app,
                ["summaries", "list", "--domain", "medical-research"],
            )

        assert result.exit_code == 0
        assert "kb-entry-001" in result.stdout
        assert "IVF" in result.stdout
        assert "92" in result.stdout  # relevance_score

    @patch("autoinfo.kb.KBStore")
    def test_summaries_json(
        self, mock_kb_store: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """--json flag produces parseable JSON."""
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _MOCK_SUMMARIES_ENTRIES
        mock_kb_store.return_value = mock_store

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(
                app,
                ["summaries", "list", "--domain", "medical-research", "--json"],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)
        assert data["count"] == 2
        assert data["items"][0]["entry_id"] == "kb-entry-001"
        assert data["items"][1]["entry_id"] == "kb-entry-002"

    @patch("autoinfo.kb.KBStore")
    def test_summaries_empty(
        self, mock_kb_store: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """Summaries with no entries shows empty message."""
        mock_store = MagicMock()
        mock_store.list_entries.return_value = []
        mock_kb_store.return_value = mock_store

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(
                app,
                ["summaries", "list", "--domain", "medical-research"],
            )

        assert result.exit_code == 0
        assert "No entries found" in result.stdout

    @patch("autoinfo.kb.KBStore")
    def test_summaries_with_limit_offset(
        self, mock_kb_store: MagicMock, cli_runner: Any, tmp_config_dir: Path
    ) -> None:
        """--limit and --offset are passed to list_entries."""
        mock_store = MagicMock()
        mock_store.list_entries.return_value = _MOCK_SUMMARIES_ENTRIES[:1]
        mock_kb_store.return_value = mock_store

        with patch("autoinfo.cli.summaries.get_config_path", return_value=tmp_config_dir):
            result = cli_runner.invoke(
                app,
                [
                    "summaries", "list",
                    "--domain", "medical-research",
                    "--limit", "1",
                    "--offset", "0",
                ],
            )

        assert result.exit_code == 0
        mock_store.list_entries.assert_called_once_with(
            domain="medical-research",
            date_from=None,
            limit=1,
            offset=0,
        )

    def test_summaries_no_config_shows_friendly_error(
        self, cli_runner: Any, tmp_path: Path
    ) -> None:
        """Without config, summaries prints friendly error (not traceback)."""
        # Patch at the usage site because summaries imports get_config_path at module level
        with patch("autoinfo.cli.summaries.get_config_path", return_value=None):
            result = cli_runner.invoke(
                app,
                ["summaries", "list", "--domain", "medical-research"],
            )

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# autoinfo init (integration smoke test)
# ---------------------------------------------------------------------------


class TestInitCommand:
    """Smoke tests for ``autoinfo init`` (requires demo data files)."""

    def test_init_lists_demo_domains(
        self, cli_runner: Any
    ) -> None:
        """``autoinfo init --list-domains`` lists available demo domains."""
        result = cli_runner.invoke(app, ["init", "--list-domains"])
        assert result.exit_code == 0
        assert "medical-research" in result.output

    def test_init_creates_all_dirs_with_demo(
        self, cli_runner: Any, tmp_path: Path
    ) -> None:
        """``autoinfo init --demo medical-research`` creates all REQUIRED_SUBDIRS."""
        from autoinfo.cli.init import _REQUIRED_SUBDIRS

        with patch.object(Path, "cwd", return_value=tmp_path):
            result = cli_runner.invoke(app, ["init", "--demo", "medical-research"])

        assert result.exit_code == 0, f"init failed: {result.output}"
        assert "✅ AutoInfo initialized for 'medical-research'." in result.output

        for sub in _REQUIRED_SUBDIRS:
            d = tmp_path / sub
            assert d.is_dir(), f"expected directory {d} to exist"

    @pytest.mark.skip(
        reason="interactive init requires a real TTY; CliRunner provides a StringIO stdin"
    )
    def test_init_interactive_flow(
        self, cli_runner: Any, tmp_path: Path
    ) -> None:
        """Interactive wizard creates directories and respects user choices."""
        from autoinfo.cli.init import _REQUIRED_SUBDIRS

        user_input = "3\nopenrouter\nsk-test-123\n"

        with patch.object(Path, "cwd", return_value=tmp_path):
            result = cli_runner.invoke(
                app, ["init", "--interactive"], input=user_input
            )

        assert result.exit_code == 0, f"interactive init failed: {result.output}"
        assert "✅ AutoInfo initialized for 'medical-research'." in result.output
        assert "Using provider: openrouter" in result.output
        assert "AUTOINFO_LLM_API_KEY set for this session." in result.output

        for sub in _REQUIRED_SUBDIRS:
            d = tmp_path / sub
            assert d.is_dir(), f"expected directory {d} to exist"


# ---------------------------------------------------------------------------
# autoinfo output --user-id forwarding
# ---------------------------------------------------------------------------


class TestOutputCommandUserID:
    """``--user-id`` is forwarded to the underlying ``generate_*`` functions.

    The output commands import the ``generate_*`` functions inside each
    command body (``from autoinfo.output import generate_*``), so patching
    the module attribute is sufficient — the import resolves at call time.
    Omitting ``--user-id`` must preserve the previous behavior
    (``user_id=""`` → no content-preference filtering).
    """

    @patch("autoinfo.output.generate_digest", return_value="# digest")
    def test_digest_forwards_user_id(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output digest --user-id X`` passes user_id to generate_digest."""
        result = cli_runner.invoke(
            app,
            ["output", "digest", "--domain", "medical-research", "--user-id", "user-123"],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            period="weekly",
            format="markdown",
            custom_instructions="",
            target_audience="",
            include_stale=False,
            recipients=None,
            user_id="user-123",
            max_items=0,
        )

    @patch("autoinfo.output.generate_digest", return_value="# digest")
    def test_digest_omitted_user_id_defaults_to_empty(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--user-id`` keeps prior behavior (user_id="")."""
        result = cli_runner.invoke(
            app, ["output", "digest", "--domain", "medical-research"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            period="weekly",
            format="markdown",
            custom_instructions="",
            target_audience="",
            include_stale=False,
            recipients=None,
            user_id="",
            max_items=0,
        )

    @patch("autoinfo.output.generate_report", return_value="# report")
    def test_report_forwards_user_id(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output report --user-id X`` passes user_id to generate_report."""
        result = cli_runner.invoke(
            app,
            ["output", "report", "--domain", "medical-research", "--user-id", "user-123"],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            format="markdown",
            target_audience="",
            report_type="standard",
            user_id="user-123",
        )

    @patch("autoinfo.output.generate_report", return_value="# report")
    def test_report_omitted_user_id_defaults_to_empty(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--user-id`` keeps prior behavior (user_id="")."""
        result = cli_runner.invoke(
            app, ["output", "report", "--domain", "medical-research"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            format="markdown",
            target_audience="",
            report_type="standard",
            user_id="",
        )

    @patch("autoinfo.output.generate_report", return_value="# report")
    def test_report_cross_domain_keeps_user_id(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Cross-domain ``--domains X --domains Y`` keeps user_id forwarding."""
        result = cli_runner.invoke(
            app,
            [
                "output", "report",
                "--domains", "medical-research",
                "--domains", "ai-commercial",
                "--user-id", "user-123",
            ],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            format="markdown",
            target_audience="",
            report_type="standard",
            user_id="user-123",
            domains=["medical-research", "ai-commercial"],
        )

    @patch("autoinfo.output.generate_tutorial", return_value="# tutorial")
    def test_tutorial_forwards_user_id(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output tutorial --user-id X`` passes user_id to generate_tutorial."""
        result = cli_runner.invoke(
            app,
            ["output", "tutorial", "--domain", "medical-research", "--user-id", "user-123"],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            target_audience="student",
            format="markdown",
            user_id="user-123",
        )

    @patch("autoinfo.output.generate_tutorial", return_value="# tutorial")
    def test_tutorial_omitted_user_id_defaults_to_empty(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--user-id`` keeps prior behavior (user_id="")."""
        result = cli_runner.invoke(
            app, ["output", "tutorial", "--domain", "medical-research"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            target_audience="student",
            format="markdown",
            user_id="",
        )

    @patch("autoinfo.output.generate_presentation", return_value="# pres")
    def test_presentation_forwards_user_id(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output presentation --user-id X`` passes user_id to generate_presentation."""
        result = cli_runner.invoke(
            app,
            [
                "output", "presentation",
                "--domain", "medical-research",
                "--topic", "IVF",
                "--user-id", "user-123",
            ],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            topic="IVF",
            slide_count=10,
            target_audience="executive",
            format="markdown",
            user_id="user-123",
        )

    @patch("autoinfo.output.generate_presentation", return_value="# pres")
    def test_presentation_omitted_user_id_defaults_to_empty(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--user-id`` keeps prior behavior (user_id="")."""
        result = cli_runner.invoke(
            app,
            [
                "output", "presentation",
                "--domain", "medical-research",
                "--topic", "IVF",
            ],
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(
            domain="medical-research",
            topic="IVF",
            slide_count=10,
            target_audience="executive",
            format="markdown",
            user_id="",
        )
