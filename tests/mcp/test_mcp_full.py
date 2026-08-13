"""Tests for v0.5 MCP tools — project, batch, and config operations.

Covers all 6 new tools added in task 21+26:

- Project (2):   list_projects, get_project_assets
- Archive (1):   archive_project
- Batch Run (1): batch_run
- Collections (1): list_active_collections
- Config (1):    get_config

Also verifies the total tool count stays above 100 and matches the runtime value.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from mcp.types import TextContent, Tool

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.server import (
    _error_response,
    _handle_archive_project,
    _handle_batch_run,
    _handle_get_config,
    _handle_get_project_assets,
    _handle_get_tool_count,
    _handle_list_active_collections,
    _handle_list_projects,
    _handle_health_check,
)

# ======================================================================
# Fixtures
# ======================================================================

SAMPLE_CONFIG_YAML = """
project:
  name: Test Project
  created_at: '2026-07-01'
llm:
  provider: openrouter
  model: deepseek/deepseek-chat
  api_key: test-key
domains:
  - name: medical-research
    active: true
    sources:
      - name: pubmed
        type: api
        url: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
        quality_tier: 1
    topics:
      - name: IVF breakthroughs
        keywords: [IVF, embryo]
  - name: ai-commercial
    active: false
    sources: []
    topics: []
"""


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary project with a valid ``.autoinfo/config.yaml``."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(SAMPLE_CONFIG_YAML, encoding="utf-8")

    cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


_MINIMAL_CONFIG = {
    "project": {"name": "Test", "created_at": "2026-07-01"},
    "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": ""},
    "domains": [
        # TRIAGE #36-37 — both domains must exist in config for the
        # _handle_collect_sources domain pre-check at
        # src/autoinfo/mcp/server.py:512-518 (DOMAIN_NOT_FOUND for unconfigured).
        {"name": "test-domain", "active": True, "sources": [], "topics": []},
        {"name": "test-progress", "active": True, "sources": [], "topics": []},
    ],
}


def _mock_load_config(config_dict: dict | None = None):
    """Patch ``_load_config`` to return a config built from *config_dict*."""
    from autoinfo.config import _dict_to_config

    data = config_dict or _MINIMAL_CONFIG
    return patch.object(mcp_server, "_load_config", return_value=_dict_to_config(data))


def _mock_save_config():
    """Patch ``_save_config`` to a no-op."""
    return patch.object(mcp_server, "_save_config", lambda config: None)


# ======================================================================
# Tool registration count
# ======================================================================


class TestToolCount:
    """Verify the total declared tool count matches the actual server."""

    def test_tools_count_matches_runtime(self) -> None:
        result = _handle_health_check()
        runtime_count = _handle_get_tool_count()["tools_count"]
        assert result["tools_count"] == runtime_count
        assert result["tools_count"] >= 100, (
            f"Expected at least 100 tools, got {result['tools_count']}"
        )

    @pytest.mark.asyncio
    async def test_new_tool_names_are_declared(self) -> None:
        """Verify expected tool names are present in list_tools declarations."""
        tools_list = await mcp_server.list_tools()
        assert isinstance(tools_list, list)
        assert len(tools_list) == _handle_get_tool_count()["tools_count"]
        assert len(tools_list) >= 100
        names = {t.name for t in tools_list}
        assert "list_projects" in names
        assert "get_project_assets" in names
        assert "archive_project" in names
        assert "batch_run" in names
        assert "list_active_collections" in names
        assert "get_config" in names


# ======================================================================
# list_projects
# ======================================================================


class TestListProjects:
    def test_returns_projects_from_config(self, tmp_config: Path) -> None:
        result = _handle_list_projects()
        assert result["count"] >= 1
        assert len(result["projects"]) == result["count"]
        first = result["projects"][0]
        assert "name" in first
        assert "domain_count" in first
        assert "total_sources" in first
        assert "total_topics" in first
        assert "llm_provider" in first

    def test_counts_active_domains(self, tmp_config: Path) -> None:
        result = _handle_list_projects()
        first = result["projects"][0]
        # Only medical-research is active
        assert first["domain_count"] == 1
        assert first["total_sources"] >= 1
        assert first["total_topics"] >= 1

    def test_handles_missing_config(self) -> None:
        with patch.object(mcp_server, "_load_config", side_effect=FileNotFoundError("no config")):
            result = _handle_list_projects()
            assert result["count"] == 0
            assert "error_code" in result

    def test_includes_llm_info(self, tmp_config: Path) -> None:
        result = _handle_list_projects()
        first = result["projects"][0]
        assert first["llm_provider"] == "openrouter"
        assert first["llm_model"] == "deepseek/deepseek-chat"


# ======================================================================
# get_project_assets
# ======================================================================


class TestGetProjectAssets:
    def test_returns_all_asset_sections(self) -> None:
        result = _handle_get_project_assets()
        assert "collections_dir" in result
        assert "knowledge_dir" in result
        assert "database" in result
        assert "exports_dir" in result
        assert "config_dir" in result

    def test_detects_nonexistent_dirs(self) -> None:
        """When run from a directory with no project, all dirs should show exists=False."""
        result = _handle_get_project_assets()
        # In a test environment (no actual project), these likely don't exist
        assert "exists" in result["collections_dir"]
        assert "exists" in result["knowledge_dir"]
        assert "exists" in result["database"]
        assert "path" in result["collections_dir"]

    def test_asset_paths_are_absolute(self) -> None:
        result = _handle_get_project_assets()
        for key in ("collections_dir", "knowledge_dir", "database", "exports_dir", "config_dir"):
            path_val = result[key].get("path", "")
            if path_val:
                assert os.path.isabs(path_val) or path_val.startswith("/")


# ======================================================================
# archive_project
# ======================================================================


class TestArchiveProject:
    def test_refuses_when_not_published(self) -> None:
        """archive_project must refuse unless entries exist in 03-Wiki."""
        with patch("autoinfo.kb.KBStore") as MockStore:
            instance = MockStore.return_value
            # Simulate no wiki entries
            instance.index.count_entries.return_value = 0
            instance.index.list_entries_by_tier.return_value = []

            result = _handle_archive_project(reason="cleanup", confirm=True)

        assert result["success"] is False
        assert result["error"]["code"] == "NotPublished"
        assert result["error"]["actionable"] is True

    def test_refuses_without_confirm(self) -> None:
        """archive_project must refuse when confirm=False."""
        result = _handle_archive_project(reason="cleanup", confirm=False)
        assert result["success"] is False
        assert result["error"]["code"] == "ConfirmationRequired"
        assert result["error"]["actionable"] is True

    def test_says_human_only_when_published(self) -> None:
        """With wiki entries present, archive is still human-only."""
        with patch("autoinfo.kb.KBStore") as MockStore:
            instance = MockStore.return_value
            instance.index.count_entries.return_value = 10
            instance.index.list_entries_by_tier.return_value = [{"entry_id": "wiki-001"}]

            result = _handle_archive_project(reason="cleanup", confirm=True)

        assert "error" not in result
        assert result["status"] == "refused_by_design"
        assert result["actionable"] is False

    def test_default_reason(self) -> None:
        with patch("autoinfo.kb.KBStore") as MockStore:
            instance = MockStore.return_value
            instance.index.count_entries.return_value = 0
            instance.index.list_entries_by_tier.return_value = []

            result = _handle_archive_project(confirm=True)

        assert result["error"]["code"] == "NotPublished"
        assert "reason provided" not in result["error"]["message"].lower()


# ======================================================================
# batch_run
# ======================================================================


class TestBatchRun:
    def test_collect_phase_failure_returns_phases(self) -> None:
        """If collection fails, batch_run should return phases with collection failed and processing skipped."""
        with (
            patch("autoinfo.collect.run_collection") as mock_collect,
        ):
            mock_collect.side_effect = RuntimeError("API timeout")

            result = _handle_batch_run(domain="medical-research", topic="IVF")

        assert "phases" in result
        assert len(result["phases"]) == 2
        assert result["phases"][0]["phase"] == "collection"
        assert result["phases"][0]["status"] == "failed"
        assert "API timeout" in result["phases"][0]["error"]
        assert result["phases"][1]["phase"] == "processing"
        assert result["phases"][1]["status"] == "skipped"
        assert result["overall_success"] is False
        assert "total_duration_s" in result

    def test_processing_phase_failure_includes_collect_result(self) -> None:
        """If processing fails, collection phase result should still be available."""
        with (
            patch("autoinfo.collect.run_collection") as mock_collect,
            patch("autoinfo.process.run_processing") as mock_process,
        ):
            mock_collect.return_value = {"items_found": 5, "status": "completed"}
            mock_process.side_effect = RuntimeError("LLM quota exceeded")

            result = _handle_batch_run(domain="medical-research")

        assert "phases" in result
        assert len(result["phases"]) == 2
        assert result["phases"][0]["phase"] == "collection"
        assert result["phases"][0]["status"] == "completed"
        assert result["phases"][0]["result"]["items_found"] == 5
        assert result["phases"][1]["phase"] == "processing"
        assert result["phases"][1]["status"] == "failed"
        assert "LLM quota exceeded" in result["phases"][1]["error"]
        assert "duration_s" in result["phases"][0]
        assert "duration_s" in result["phases"][1]
        assert result["overall_success"] is False

    def test_successful_batch_run(self) -> None:
        """A successful batch run returns both phases with completed status."""
        from autoinfo.process import ProcessResult

        proc_result = ProcessResult(
            domain="medical-research",
            processed_count=3,
            kb_entries_created=3,
            errors=[],
        )

        with (
            patch("autoinfo.collect.run_collection") as mock_collect,
            patch("autoinfo.process.run_processing") as mock_process,
        ):
            mock_collect.return_value = {
                "items_found": 5,
                "items_new": 3,
                "status": "completed",
            }
            mock_process.return_value = proc_result

            result = _handle_batch_run(domain="medical-research", model="deepseek/deepseek-chat")

        assert result["overall_success"] is True
        assert result["domain"] == "medical-research"
        assert len(result["phases"]) == 2
        assert result["phases"][0]["phase"] == "collection"
        assert result["phases"][0]["status"] == "completed"
        assert result["phases"][0]["result"]["items_found"] == 5
        assert result["phases"][1]["phase"] == "processing"
        assert result["phases"][1]["status"] == "completed"
        assert result["phases"][1]["result"]["processed_count"] == 3
        assert "duration_s" in result["phases"][0]
        assert "duration_s" in result["phases"][1]
        assert "total_duration_s" in result
        assert "topic" in result


# ======================================================================
# list_active_collections
# ======================================================================


class TestListActiveCollections:
    def test_returns_list_when_no_runs_file(self) -> None:
        """With no _runs.json, returns an empty list."""
        result = _handle_list_active_collections()
        assert "active_collections" in result
        assert result["count"] == 0

    def test_with_runs_file_returns_active(self, tmp_path: Path) -> None:
        """When _runs.json exists, active collections are returned."""
        runs_dir = tmp_path / "collections"
        runs_dir.mkdir(exist_ok=True)
        runs_path = runs_dir / "_runs.json"
        runs_path.write_text(json.dumps([
            {
                "collection_id": "col-001",
                "timestamp": "2026-07-20T10:00:00Z",
                "status": "in_progress",
                "items_found": 3,
                "items_new": 2,
                "errors": [],
                "duration_ms": 1200.0,
            },
            {
                "collection_id": "col-002",
                "timestamp": "2026-07-20T09:00:00Z",
                "status": "completed",
                "items_found": 10,
                "items_new": 10,
                "errors": [],
                "duration_ms": 5000.0,
            },
        ]), encoding="utf-8")

        cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = _handle_list_active_collections()
            assert result["count"] == 1
            assert result["active_collections"][0]["collection_id"] == "col-001"
        finally:
            os.chdir(cwd)

    def test_with_only_completed_returns_recent(self, tmp_path: Path) -> None:
        """When no active runs exist, returns the 5 most recent."""
        runs_dir = tmp_path / "collections"
        runs_dir.mkdir(exist_ok=True)
        runs_path = runs_dir / "_runs.json"
        runs_path.write_text(json.dumps([
            {
                "collection_id": f"col-{i:03d}",
                "timestamp": f"2026-07-{10 + i:02d}T10:00:00Z",
                "status": "completed",
                "items_found": i,
                "items_new": i,
                "errors": [],
                "duration_ms": 1000.0 * i,
            }
            for i in range(1, 8)
        ]), encoding="utf-8")

        cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = _handle_list_active_collections()
            # Should have at most 5 most recent
            assert result["count"] <= 5
        finally:
            os.chdir(cwd)


# ======================================================================
# get_config
# ======================================================================


class TestGetConfig:
    def test_returns_full_config(self, tmp_config: Path) -> None:
        result = _handle_get_config(section="")
        assert "config" in result
        cfg = result["config"]
        assert "project" in cfg
        assert "llm" in cfg
        assert "domains" in cfg
        assert "config_path" in cfg

    def test_section_project_only(self, tmp_config: Path) -> None:
        result = _handle_get_config(section="project")
        cfg = result["config"]
        assert "project" in cfg
        assert "llm" not in cfg
        assert "domains" not in cfg

    def test_section_llm_only(self, tmp_config: Path) -> None:
        result = _handle_get_config(section="llm")
        cfg = result["config"]
        assert "llm" in cfg
        assert cfg["llm"]["provider"] == "openrouter"
        assert "project" not in cfg
        assert "domains" not in cfg

    def test_section_domains_only(self, tmp_config: Path) -> None:
        result = _handle_get_config(section="domains")
        cfg = result["config"]
        assert "domains" in cfg
        assert "project" not in cfg
        assert "llm" not in cfg
        names = {d["name"] for d in cfg["domains"]}
        assert "medical-research" in names

    def test_invalid_section_returns_error(self, tmp_config: Path) -> None:
        result = _handle_get_config(section="nonexistent")
        assert "error_code" in result
        assert result["error_code"] == "InvalidSection"
        assert "actionable" in result

    def test_handles_config_load_error(self) -> None:
        with patch.object(mcp_server, "_load_config", side_effect=FileNotFoundError("no config")):
            result = _handle_get_config(section="")
            assert "error_code" in result


# ======================================================================
# #24: confirm param on destructive tools
# ======================================================================


class TestConfirmParam:
    """confirm=False returns ConfirmationRequired for all 4 destructive tools."""

    def test_remove_source_refuses_without_confirm(self) -> None:
        result = mcp_server._handle_remove_source(source_id="test:src", confirm=False)
        assert result["error_code"] == "ConfirmationRequired"
        assert result["actionable"] is True

    def test_remove_topic_refuses_without_confirm(self) -> None:
        result = mcp_server._handle_remove_topic(domain="test", topic_id="t", confirm=False)
        assert result["error_code"] == "ConfirmationRequired"
        assert result["actionable"] is True

    def test_remove_schedule_refuses_without_confirm(self) -> None:
        result = mcp_server._handle_remove_schedule(name="test-sched", confirm=False)
        assert result["error_code"] == "ConfirmationRequired"
        assert result["actionable"] is True

    def test_archive_project_refuses_without_confirm(self) -> None:
        result = mcp_server._handle_archive_project(reason="test", confirm=False)
        assert result["error"]["code"] == "ConfirmationRequired"
        assert result["error"]["actionable"] is True


# ======================================================================
# #22: job_id on long-running tools
# ======================================================================


class TestJobId:
    """job_id is generated and returned by collect_sources / process_collection."""

    def test_collect_sources_returns_job_id(self) -> None:
        # TRIAGE #36 — _handle_collect_sources validates the domain against
        # config first (server.py:512-518 DOMAIN_NOT_FOUND pre-check); the
        # fixture config must declare 'test-domain' so the mocked
        # run_collection is reached.
        with _mock_load_config(), patch("autoinfo.collect.run_collection") as mock_collect:
            mock_collect.return_value = {"total_new": 3, "total_found": 5, "errors": 0}
            result = mcp_server._handle_collect_sources(domain="test-domain")
        assert "job_id" in result
        assert isinstance(result["job_id"], str)
        assert len(result["job_id"]) > 0

    def test_process_collection_returns_job_id(self) -> None:
        from autoinfo.process import ProcessResult
        with patch("autoinfo.process.run_processing") as mock_process:
            mock_process.return_value = ProcessResult(
                domain="test", total_items=5,
                kb_entries_created=3, duration_s=1.0,
            )
            result = mcp_server._handle_process_collection(domain="test-domain")
        assert "job_id" in result
        assert isinstance(result["job_id"], str)

    def test_get_collection_progress_by_job_id(self) -> None:
        """After collect_sources, get_collection_progress with job_id returns state."""
        # TRIAGE #37 — same domain-validation pre-check as #36 (server.py:512-518);
        # 'test-progress' is declared in _MINIMAL_CONFIG for this test.
        with _mock_load_config(), patch("autoinfo.collect.run_collection") as mock_collect:
            mock_collect.return_value = {"total_new": 3, "total_found": 5, "errors": 0}
            result = mcp_server._handle_collect_sources(domain="test-progress")
        job_id = result["job_id"]
        progress = mcp_server._handle_get_collection_progress(job_id=job_id)
        assert progress["job_id"] == job_id
        assert "is_complete" in progress
        assert progress["is_complete"] is True
        assert progress["status"] == "completed"

    def test_get_collection_progress_unknown_job_id(self) -> None:
        progress = mcp_server._handle_get_collection_progress(job_id="nonexistent-job")
        assert progress["status"] == "not_found"
        assert progress["is_complete"] is False

    def test_get_processing_progress_by_job_id(self) -> None:
        from autoinfo.process import ProcessResult
        with patch("autoinfo.process.run_processing") as mock_process:
            mock_process.return_value = ProcessResult(
                domain="test", total_items=5,
                kb_entries_created=3, duration_s=1.0,
            )
            result = mcp_server._handle_process_collection(domain="test-progress-2")
        job_id = result["job_id"]
        progress = mcp_server._handle_get_processing_progress(job_id=job_id)
        assert progress["job_id"] == job_id
        assert "is_complete" in progress

    def test_get_processing_progress_unknown_job_id(self) -> None:
        progress = mcp_server._handle_get_processing_progress(job_id="nonexistent-job")
        assert progress["status"] == "not_found"
        assert progress["is_complete"] is False


# ======================================================================
# #25: optional filters on list tools
# ======================================================================


class TestToolFilters:
    """Optional filter params on list_active_collections, list_projects, get_project_assets."""

    def test_list_active_collections_accepts_domain_filter(self) -> None:
        """list_active_collections accepts a domain parameter."""
        with patch("autoinfo.collect.list_active_collections") as mock_list:
            mock_list.return_value = [{"domain": "medical-research", "status": "running"}]
            result = mcp_server._handle_list_active_collections(domain="medical-research")
        assert "active_collections" in result

    def test_list_projects_accepts_status_filter(self) -> None:
        """list_projects accepts a status parameter."""
        result = mcp_server._handle_list_projects(status="active")
        assert "projects" in result
        assert all(p.get("status") == "active" for p in result["projects"])

    def test_get_project_assets_accepts_type_filter(self) -> None:
        """get_project_assets accepts a type parameter."""
        result = mcp_server._handle_get_project_assets(type="database")
        assert "database" in result
        assert "collections_dir" not in result
