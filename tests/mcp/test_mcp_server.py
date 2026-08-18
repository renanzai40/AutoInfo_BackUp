# mypy: ignore-errors
"""Tests for the AutoInfo MCP server.

Covers:
    - Tool registration (``list_tools`` returns 6 tools with correct schemas)
    - ``health_check`` response structure
    - ``diagnose_system`` response structure (with/without config)
    - ``collect_sources`` dispatches to ``run_collection``
    - ``process_collection`` dispatches to ``run_processing``
    - ``list_summaries`` dispatches to ``KBStore.list_entries``
    - ``get_kb_entry`` returns entry or ``NotFound`` error
    - Error handling for unknown tools and runtime exceptions
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, TextContent

from autoinfo.config import Config, DomainConfig
from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.server import (
    _error_response,
    _handle_activate_domain,
    _handle_add_source,
    _handle_add_sources,
    _handle_collect_sources,
    _handle_create_kb_entry,
    _handle_deactivate_domain,
    _handle_diagnose_system,
    _handle_generate_presentation,
    _handle_generate_tutorial,
    _handle_get_collection_progress,
    _handle_get_collection_status,
    _handle_get_domain_config,
    _handle_get_domain_schema,
    _handle_get_kb_entry,
    _handle_get_processing_progress,
    _handle_health_check,
    _handle_init_project,
    _handle_list_keywords,
    _handle_list_summaries,
    _handle_process_collection,
    _handle_test_source,
    _suggest_extract_fields,
)

# ======================================================================
# _handle_health_check
# ======================================================================


class TestHealthCheck:
    def test_returns_status_ok(self) -> None:
        result = _handle_health_check()
        assert result["status"] == "ok"
        assert "version" in result
        assert result["tools_count"] >= 23

    def test_version_matches_package(self) -> None:
        from autoinfo import __version__

        result = _handle_health_check()
        assert result["version"] == __version__


# ======================================================================
# _handle_diagnose_system
# ======================================================================


class TestDiagnoseSystem:
    def test_returns_all_sections_when_no_config(self) -> None:
        """Without a config file, all sections are still present."""
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_diagnose_system()

        assert "llm" in result
        assert "sources" in result
        assert "disk" in result
        assert "db" in result

        # LLM not configured when there's no config
        assert result["llm"]["configured"] is False

    def test_llm_configured_when_config_found(self, tmp_path: Path) -> None:
        """With a config file, LLM details are populated."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "llm:\n"
            "  provider: openrouter\n"
            "  model: deepseek/deepseek-chat\n"
            "  api_key: sk-test\n"
            "project:\n"
            "  name: Test\n"
            "domains:\n"
            "  - name: medical-research\n"
            "    active: true\n"
            "    sources:\n"
            "      - name: pubmed\n"
            "        type: api\n"
            "        url: https://eutils.ncbi.nlm.nih.gov\n"
            "    topics:\n"
            "      - name: IVF\n"
            "        keywords: [IVF, embryo]\n",
        )

        with (
            patch("autoinfo.config.get_config_path", return_value=config_path),
            patch("autoinfo.config.load_config") as mock_load,
        ):
            from autoinfo.config import (
                Config,
                DomainConfig,
                LLMConfig,
                ProjectConfig,
                SourceConfig,
            )

            mock_load.return_value = Config(
                project=ProjectConfig(name="Test"),
                llm=LLMConfig(
                    provider="openrouter",
                    model="deepseek/deepseek-chat",
                    api_key="sk-test",
                ),
                domains=[
                    DomainConfig(
                        name="medical-research",
                        active=True,
                        sources=[
                            SourceConfig(
                                name="pubmed",
                                type="api",
                                url="https://eutils.ncbi.nlm.nih.gov",
                            ),
                        ],
                    ),
                ],
            )
            result = _handle_diagnose_system()

        assert result["llm"]["configured"] is True
        assert result["llm"]["provider"] == "openrouter"
        assert result["llm"]["model"] == "deepseek/deepseek-chat"
        assert result["llm"]["key_configured"] is True

    def test_sources_parsed_from_config(self) -> None:
        """Active domain sources appear in the sources section."""
        with (
            patch("autoinfo.config.get_config_path") as mock_path,
            patch("autoinfo.config.load_config") as mock_load,
        ):
            mock_path.return_value = Path("/fake/.autoinfo/config.yaml")

            from autoinfo.config import (
                Config,
                DomainConfig,
                LLMConfig,
                ProjectConfig,
                SourceConfig,
            )

            mock_load.return_value = Config(
                project=ProjectConfig(name="Test"),
                llm=LLMConfig(provider="openai", model="gpt-4o-mini"),
                domains=[
                    DomainConfig(
                        name="ai-commercial",
                        active=True,
                        sources=[
                            SourceConfig(name="hackernews", type="rss"),
                            SourceConfig(name="techcrunch", type="rss"),
                        ],
                    ),
                ],
            )
            result = _handle_diagnose_system()

        assert result["sources"]["count"] == 2
        names = {s["name"] for s in result["sources"]["items"]}
        assert names == {"hackernews", "techcrunch"}

    def test_disk_sections_present(self) -> None:
        """Disk section shows directory existence."""
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_diagnose_system()

        assert "collections_dir_exists" in result["disk"]
        assert "knowledge_dir_exists" in result["disk"]

    def test_db_section_present(self) -> None:
        """DB section shows whether autoinfo.db exists."""
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_diagnose_system()

        assert "exists" in result["db"]


# ======================================================================
# Error response format
# ======================================================================


class TestErrorResponse:
    def test_includes_required_fields(self) -> None:
        exc = ValueError("Invalid domain name")
        result = _error_response(exc)

        assert len(result) == 1
        content = result[0]
        assert isinstance(content, TextContent)
        assert content.type == "text"

        data = json.loads(content.text)
        # Envelope shape
        assert data["success"] is False
        # ValueError maps to VALIDATION_ERROR via exception→ErrorCode mapping
        assert data["error"]["code"] == "ValidationError"
        assert "Invalid domain name" in data["error"]["message"]
        assert data["error"]["actionable"] is True

    def test_handles_arbitrary_exception_types(self) -> None:
        exc = RuntimeError("Connection refused")
        result = _error_response(exc)
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert data["error"]["code"] == "InternalError"


# ======================================================================
# Tool registration (list_tools)
# ======================================================================


class TestToolRegistration:
    @pytest.mark.asyncio
    async def test_lists_at_least_twenty_three_tools(self) -> None:
        tools = await mcp_server.list_tools()
        assert len(tools) >= 23

        names = {t.name for t in tools}
        assert {
            "health_check",
            "diagnose_system",
            "collect_sources",
            "get_collection_progress",
            "get_collection_status",
            "process_collection",
            "get_processing_progress",
            "list_summaries",
            "get_kb_entry",
            "list_domains",
            "get_domain_schema",
            "list_available_models",
            "get_effective_llm_config",
            "activate_domain",
            "deactivate_domain",
            "get_domain_config",
            "add_source",
            "add_sources",
            "remove_source",
            "test_source",
            "list_sources",
            "add_topic",
            "remove_topic",
            "list_keywords",
            "search_knowledge_base",
            "flag_for_knowledge_base",
            "get_summary",
            "list_output_templates",
            "generate_tutorial",
            "generate_presentation",
        }.issubset(names)

    @pytest.mark.asyncio
    async def test_each_tool_has_input_schema(self) -> None:
        tools = await mcp_server.list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"

    @pytest.mark.asyncio
    async def test_required_params_are_marked(self) -> None:
        tools = await mcp_server.list_tools()
        by_name = {t.name: t for t in tools}

        # Tools with no required params
        assert "required" not in by_name["health_check"].inputSchema or \
               by_name["health_check"].inputSchema["required"] is None

        # TRIAGE #56 (stale): collect_sources domain is now intentionally
        # optional (domain-less collection) — schema has required: []
        schema = by_name["collect_sources"].inputSchema
        assert "domain" not in schema.get("required", [])

        # Process requires domain
        schema = by_name["process_collection"].inputSchema
        assert "domain" in schema.get("required", [])

        # List summaries requires domain
        schema = by_name["list_summaries"].inputSchema
        assert "domain" in schema.get("required", [])

        # Get KB entry requires entry_id
        schema = by_name["get_kb_entry"].inputSchema
        assert "entry_id" in schema.get("required", [])


# ======================================================================
# call_tool dispatch  (exercised via request_handlers)
# ======================================================================


class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_health_check_dispatches_correctly(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="health_check", arguments={}),
        )
        result = await handler(request)
        assert result is not None
        call_result = result.root
        assert len(call_result.content) == 1
        data = json.loads(call_result.content[0].text)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="nonexistent", arguments={}),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)
        # Envelope shape
        assert data["success"] is False
        assert data["error"]["code"] == "UnknownTool"
        assert data["error"]["actionable"] is False

    @pytest.mark.asyncio
    async def test_missing_required_argument_returns_error(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_kb_entry",
                arguments={},  # entry_id is required
            ),
        )
        result = await handler(request)
        call_result = result.root
        assert call_result.isError or len(call_result.content) > 0


# ======================================================================
# Handler-level integration with mocked dependencies
# ======================================================================


class TestCollectSources:
    @patch(
        "autoinfo.mcp.server._load_config",
        return_value=Config(domains=[DomainConfig(name="medical-research")]),
    )
    @patch("autoinfo.collect.run_collection")
    def test_dispatches_to_run_collection(
        self, mock_run: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_run.return_value = {
            "collection_id": "col-001",
            "domain": "medical-research",
            "total_found": 5,
            "total_new": 3,
        }

        result = _handle_collect_sources(
            domain="medical-research",
            topic="IVF",
            limit=10,
        )

        mock_run.assert_called_once_with(
            domain="medical-research",
            topic="IVF",
            limit=10,
        )
        assert result["collection_id"] == "col-001"

    @patch(
        "autoinfo.mcp.server._load_config",
        return_value=Config(domains=[DomainConfig(name="medical-research")]),
    )
    @patch("autoinfo.collect.run_collection")
    def test_dry_run_passed_through(
        self, mock_run: MagicMock, mock_config: MagicMock
    ) -> None:
        _handle_collect_sources(domain="medical-research", dry_run=True)
        mock_run.assert_called_once_with(domain="medical-research", dry_run=True)

    @patch("autoinfo.mcp.server._load_config", return_value=Config())
    def test_nonexistent_domain_returns_not_found(
        self, mock_config: MagicMock
    ) -> None:
        result = _handle_collect_sources(domain="nonexistent-domain")
        assert result["success"] is False
        assert result["error"]["code"] == "DomainNotFound"
        assert "not configured" in result["error"]["message"]
        assert result["error"]["actionable"] is True


class TestProcessCollection:
    @patch("autoinfo.process.run_processing")
    def test_dispatches_to_run_processing(self, mock_proc: MagicMock) -> None:
        from autoinfo.process import ProcessResult

        mock_proc.return_value = ProcessResult(
            domain="medical-research",
            total_items=10,
            passed_gates=8,
            kb_entries_created=8,
            duration_s=1.23,
        )

        result = _handle_process_collection(
            domain="medical-research",
            model="deepseek/deepseek-chat",
        )

        mock_proc.assert_called_once_with(
            domain="medical-research",
            model="deepseek/deepseek-chat",
        )
        assert result["domain"] == "medical-research"
        assert result["kb_entries_created"] == 8
        assert result["total_items"] == 10

    @patch("autoinfo.process.run_processing")
    def test_model_optional(self, mock_proc: MagicMock) -> None:
        from autoinfo.process import ProcessResult

        mock_proc.return_value = ProcessResult(domain="test")
        _handle_process_collection(domain="test")
        mock_proc.assert_called_once_with(domain="test")

    @patch("autoinfo.process.run_processing")
    def test_batch_size_passed_through(self, mock_proc: MagicMock) -> None:
        from autoinfo.process import ProcessResult

        mock_proc.return_value = ProcessResult(
            domain="medical-research",
            total_items=10,
            processed_count=3,
            remaining_count=7,
            is_complete=False,
        )

        result = _handle_process_collection(
            domain="medical-research", batch_size=3
        )

        mock_proc.assert_called_once_with(
            domain="medical-research", batch_size=3
        )
        assert result["total_items"] == 10
        assert result["processed_count"] == 3
        assert result["remaining_count"] == 7
        assert result["is_complete"] is False


class TestGetProcessingProgress:
    @patch("autoinfo.process.get_processing_progress")
    def test_returns_progress(self, mock_progress: MagicMock) -> None:
        mock_progress.return_value = {
            "total_items": 10,
            "processed_count": 3,
            "remaining_count": 7,
            "is_complete": False,
        }

        result = _handle_get_processing_progress(domain="medical-research")

        mock_progress.assert_called_once_with(domain="medical-research")
        assert result["total_items"] == 10
        assert result["processed_count"] == 3
        assert result["remaining_count"] == 7
        assert result["is_complete"] is False

    @patch("autoinfo.process.get_processing_progress")
    def test_complete_progress(self, mock_progress: MagicMock) -> None:
        mock_progress.return_value = {
            "total_items": 10,
            "processed_count": 10,
            "remaining_count": 0,
            "is_complete": True,
        }

        result = _handle_get_processing_progress(domain="medical-research")

        assert result["is_complete"] is True
        assert result["remaining_count"] == 0


class TestListSummaries:
    # TRIAGE #70 (regression): `_handle_list_summaries` short-circuits on
    # `_detect_kb_status()` (server.py:720-732) before reaching the mocked
    # `KBStore.list_entries`. Stub the status to "operational" so the store
    # is actually exercised hermetically (no dependency on cwd knowledge/).
    @patch("autoinfo.mcp.server._detect_kb_status", return_value="operational")
    @patch("autoinfo.kb.KBStore")
    def test_dispatches_to_kb_store(self, mock_kb: MagicMock, mock_status: MagicMock) -> None:
        mock_instance = mock_kb.return_value
        mock_instance.list_entries.return_value = [
            {"entry_id": "e1", "title": "Entry 1"},
            {"entry_id": "e2", "title": "Entry 2"},
        ]

        result = _handle_list_summaries(
            domain="medical-research",
            limit=10,
            offset=0,
        )

        mock_instance.list_entries.assert_called_once_with(
            "medical-research",
            limit=10,
            offset=0,
        )
        assert result["count"] == 2
        assert result["domain"] == "medical-research"

    @patch("autoinfo.mcp.server._detect_kb_status", return_value="operational")
    @patch("autoinfo.kb.KBStore")
    def test_empty_result(
        self, mock_kb: MagicMock, mock_status: MagicMock
    ) -> None:
        mock_instance = mock_kb.return_value
        mock_instance.list_entries.return_value = []

        result = _handle_list_summaries(domain="nonexistent")
        assert result["count"] == 0
        assert result["entries"] == []


class TestGetKBEntry:
    @patch("autoinfo.kb.KBStore")
    def test_returns_entry_when_found(self, mock_kb: MagicMock) -> None:
        mock_instance = mock_kb.return_value
        mock_instance.get_entry.return_value = {
            "entry_id": "med-ivf-001",
            "title": "IVF Study",
            "domain": "medical-research",
            "content": "Full content here",
        }

        result = _handle_get_kb_entry(entry_id="med-ivf-001")
        assert result["entry_id"] == "med-ivf-001"
        assert result["title"] == "IVF Study"

    @patch("autoinfo.kb.KBStore")
    def test_returns_not_found_when_missing(self, mock_kb: MagicMock) -> None:
        mock_instance = mock_kb.return_value
        mock_instance.get_entry.return_value = None

        result = _handle_get_kb_entry(entry_id="nonexistent")
        assert result["success"] is False
        assert result["error"]["code"] == "NotFound"
        assert "nonexistent" in result["error"]["message"]


# ======================================================================
# _handle_get_collection_progress / _handle_get_collection_status
# ======================================================================


class TestCollectionProgressStatus:
    def setup_method(self) -> None:
        """No-op: tests use _save_job_state with unique ids to avoid interference."""

    def test_get_collection_progress_idle(self) -> None:
        result = _handle_get_collection_progress(domain="test-nonexistent-xyz")
        assert result["domain"] == "test-nonexistent-xyz"
        assert result["status"] == "idle"
        assert result["progress_pct"] == 0.0

    def test_get_collection_progress_all(self) -> None:
        from autoinfo.mcp.server import _save_job_state

        _save_job_state("job-test-all", "collection", "test-all-progress", "running", 50.0, {
            "started_at": "2026-01-01T00:00:00",
            "completed_at": "",
            "items_collected": 5,
            "errors": 1,
            "items_per_source": {"src1": 3},
            "duration_s": 0.0,
        })
        result = _handle_get_collection_progress(domain="")
        assert result["count"] >= 1
        domains = result["domains"]
        assert "test-all-progress" in domains
        assert domains["test-all-progress"]["status"] == "running"
        assert domains["test-all-progress"]["items_collected"] == 5

    def test_get_collection_status_with_state(self) -> None:
        from autoinfo.mcp.server import _save_job_state

        _save_job_state("job-test-status", "collection", "test-status-domain", "completed", 100.0, {
            "started_at": "2026-01-01T00:00:00",
            "completed_at": "2026-01-01T01:00:00",
            "items_collected": 10,
            "errors": 0,
            "items_per_source": {"pubmed": 10},
            "duration_s": 0.0,
        })
        result = _handle_get_collection_status(domain="test-status-domain")
        assert result["domain"] == "test-status-domain"
        assert result["status"] == "completed"
        assert result["items_collected"] == 10
        assert result["duration_s"] > 0

    def test_get_collection_status_idle(self) -> None:
        result = _handle_get_collection_status(domain="nonexistent")
        assert result["domain"] == "nonexistent"
        assert result["status"] == "idle"
        assert result["items_collected"] == 0


# ======================================================================
# _handle_activate_domain / _handle_deactivate_domain / _handle_get_domain_config
# ======================================================================


class TestDomainLifecycle:
    def test_activate_existing_domain(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n  - name: medical\n    active: false\n    sources: []\n    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_activate_domain(name="medical")

        assert result["domain"] == "medical"
        assert result["active"] is True

    def test_activate_nonexistent_domain(self) -> None:
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_activate_domain(name="nonexistent")
        assert "error_code" in result

    def test_deactivate_existing_domain(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n  - name: medical\n    active: true\n    sources: []\n    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_deactivate_domain(name="medical")

        assert result["domain"] == "medical"
        assert result["active"] is False

    def test_get_domain_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical\n"
            "    active: true\n"
            "    extract_fields: [methodology]\n"
            "    sources:\n"
            "      - name: pubmed\n"
            "        type: api\n"
            "        url: https://eutils.ncbi.nlm.nih.gov\n"
            "    topics:\n"
            "      - name: IVF\n"
            "        keywords: [IVF, embryo]\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_get_domain_config(name="medical")

        assert result["domain"] == "medical"
        assert result["active"] is True
        assert result["source_count"] == 1
        assert result["topic_count"] == 1
        assert "methodology" in result["extract_fields"]

    def test_get_domain_config_nonexistent(self) -> None:
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_get_domain_config(name="nonexistent")
        assert "error_code" in result


# ======================================================================
# _handle_list_keywords
# ======================================================================


class TestListKeywords:
    def test_list_keywords_all(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics:\n"
            "      - name: IVF\n"
            "        keywords: [IVF, embryo]\n"
            "        group: fertility\n"
            "        relevance_threshold: 50\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_list_keywords(domain="medical")

        assert result["domain"] == "medical"
        assert result["count"] == 1
        assert result["topics"][0]["name"] == "IVF"
        assert result["topics"][0]["group"] == "fertility"
        assert result["topics"][0]["relevance_threshold"] == 50

    def test_list_keywords_filtered_by_topic(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics:\n"
            "      - name: IVF\n"
            "        keywords: [IVF]\n"
            "      - name: Cancer\n"
            "        keywords: [cancer]\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_list_keywords(domain="medical", topic="IVF")

        assert result["count"] == 1
        assert result["topics"][0]["name"] == "IVF"

    def test_list_keywords_domain_not_found(self) -> None:
        with patch("autoinfo.config.get_config_path", return_value=None):
            result = _handle_list_keywords(domain="nonexistent")
        assert "error_code" in result


# ======================================================================
# _handle_generate_tutorial / _handle_generate_presentation
# ======================================================================


class TestGenerateOutput:
    @patch("autoinfo.output.generate_tutorial")
    def test_generate_tutorial(self, mock_gen: MagicMock) -> None:
        mock_gen.return_value = "# Tutorial\n\nContent here"
        result = _handle_generate_tutorial(
            domain="medical-research",
            topic="IVF",
            format="markdown",
        )
        assert result["success"] is True
        assert result["domain"] == "medical-research"
        assert "# Tutorial" in result["content"]

        mock_gen.assert_called_once_with(
            domain="medical-research", format="markdown", custom_instructions="", user_id=""
        )

    @patch("autoinfo.output.generate_tutorial")
    def test_generate_tutorial_error(self, mock_gen: MagicMock) -> None:
        mock_gen.side_effect = ValueError("Invalid domain")
        result = _handle_generate_tutorial(domain="bad")
        assert "error_code" in result

    @patch("autoinfo.output.generate_presentation")
    def test_generate_presentation(self, mock_gen: MagicMock) -> None:
        mock_gen.return_value = "# Slide 1\n\nContent"
        result = _handle_generate_presentation(
            domain="medical-research",
            topic="IVF breakthroughs",
            slides=10,
        )
        assert result["success"] is True
        assert result["domain"] == "medical-research"
        assert result["slides"] == 10
        assert "# Slide 1" in result["content"]

        mock_gen.assert_called_once_with(
            domain="medical-research",
            topic="IVF breakthroughs",
            slide_count=10,
            format="markdown",
            custom_instructions="",
            user_id="",
        )


# ======================================================================
# _handle_test_source — suggested_extract_fields
# ======================================================================


class TestTestSourceFields:
    @patch("autoinfo.mcp.server.httpx.get")
    @patch("autoinfo.mcp.server.httpx.head")
    def test_suggested_fields_for_api(self, mock_head: MagicMock, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/xml"}
        mock_response.text = "<rss><item>test</item></rss>"
        mock_response.content = b"test"
        mock_get.return_value = mock_response

        result = _handle_test_source(
            url="https://eutils.ncbi.nlm.nih.gov",
            type="api",
        )
        assert result["reachable"] is True
        assert "suggested_extract_fields" in result
        assert result["suggested_extract_fields"] == ["pmid", "doi", "authors", "journal"]

    @patch("autoinfo.mcp.server.httpx.get")
    @patch("autoinfo.mcp.server.httpx.head")
    def test_suggested_fields_for_rss(self, mock_head: MagicMock, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/rss+xml"}
        mock_response.text = "<rss version='2.0'><channel><title>Test</title></channel></rss>"
        mock_response.content = b"test"
        mock_head.return_value = mock_response

        result = _handle_test_source(
            url="https://example.com/rss",
            type="rss",
        )
        assert result["reachable"] is True
        assert result["suggested_extract_fields"] == ["title", "pub_date", "description"]

    def test_suggested_fields_default(self) -> None:
        result = _suggest_extract_fields("unknown")
        assert result == ["title", "description"]


# ======================================================================
# _handle_test_source - key requirement warning (D4)
# ======================================================================


class TestTestSourceKeyWarning:
    @patch("autoinfo.mcp.server.httpx.get")
    @patch("autoinfo.mcp.server.httpx.head")
    def test_warns_when_required_key_missing(
        self,
        mock_head: MagicMock,
        mock_get: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("AUTOINFO_NYT_API_KEY", raising=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = "{}"
        mock_response.content = b"{}"
        mock_head.return_value = mock_response
        mock_get.return_value = mock_response

        result = _handle_test_source(
            url="https://api.nytimes.com/svc",
            type="nyt",
        )
        assert result["reachable"] is True
        assert result["key_required"] is True
        assert result["key_configured"] is False
        assert "warning" in result
        assert "AUTOINFO_NYT_API_KEY" in result["warning"]
        assert "docs/dev/required-api-keys.md" in result["warning"]

    @patch("autoinfo.mcp.server.httpx.get")
    @patch("autoinfo.mcp.server.httpx.head")
    def test_no_warning_when_key_configured(
        self,
        mock_head: MagicMock,
        mock_get: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AUTOINFO_NYT_API_KEY", "test-key-value")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = "{}"
        mock_response.content = b"{}"
        mock_head.return_value = mock_response
        mock_get.return_value = mock_response

        result = _handle_test_source(
            url="https://api.nytimes.com/svc",
            type="nyt",
        )
        assert result["reachable"] is True
        assert result["key_required"] is True
        assert result["key_configured"] is True
        assert "warning" not in result

    @patch("autoinfo.mcp.server.httpx.get")
    @patch("autoinfo.mcp.server.httpx.head")
    def test_keyless_source_reports_no_requirement(
        self,
        mock_head: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/xml"}
        mock_response.text = "<rss><item>test</item></rss>"
        mock_response.content = b"test"
        mock_head.return_value = mock_response
        mock_get.return_value = mock_response

        result = _handle_test_source(
            url="https://example.com/feed",
            type="rss",
        )
        assert result["reachable"] is True
        assert result["key_required"] is False
        assert result["key_configured"] is True
        assert "warning" not in result

    def test_missing_key_never_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("AUTOINFO_NYT_API_KEY", raising=False)
        with patch("autoinfo.mcp.server.httpx.get", side_effect=ConnectionError("refused")):
            result = _handle_test_source(
                url="https://api.nytimes.com/svc",
                type="nyt",
            )
        assert result["success"] is False
        assert "error" in result
        assert "AUTOINFO_NYT_API_KEY" in result["error"]["message"]


# ======================================================================
# _handle_init_project - next_steps key detection (D4 / B-006)
# ======================================================================


class TestInitProjectNextSteps:
    def test_next_steps_include_missing_key_steps(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for var in (
            "AUTOINFO_AP_API_KEY",
            "AUTOINFO_REUTERS_API_KEY",
            "AUTOINFO_YOUTUBE_API_KEY",
            "AUTOINFO_NYT_API_KEY",
            "AUTOINFO_SPOTIFY_CLIENT_ID",
            "AUTOINFO_SPOTIFY_CLIENT_SECRET",
            "AUTOINFO_QUANDL_API_KEY",
            "AUTOINFO_UNPAYWALL_EMAIL",
            "AUTOINFO_CORE_API_KEY",
            "KAGGLE_USERNAME",
            "KAGGLE_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        result = _handle_init_project(domain="tech-ai-developer", dry_run=True)

        assert result["status"] == "dry_run"
        next_steps = result["next_steps"]
        assert len(next_steps) > 4
        assert next_steps[0].startswith("configure_llm")
        # index 1 is the model-pool configuration example (see
        # TestInitProjectNextStepsPoolExample in test_init_project_pool_examples.py)
        assert next_steps[2] == "collect_sources(domain='tech-ai-developer')"
        assert next_steps[3] == "process_collection(domain='tech-ai-developer')"
        assert any("AUTOINFO_SPOTIFY_CLIENT_ID" in s for s in next_steps)
        assert any("AUTOINFO_SPOTIFY_CLIENT_SECRET" in s for s in next_steps)
        assert any("docs/dev/required-api-keys.md" in s for s in next_steps)

    def test_next_steps_unchanged_for_keyless_domain(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result = _handle_init_project(domain="medical-research", dry_run=True)

        assert result["status"] == "dry_run"
        next_steps = result["next_steps"]
        assert len(next_steps) == 4
        assert next_steps == [
            "configure_llm(api_key='...', provider='...', model='...')",
            (
                "configure_llm(llm_fallback=[{'model': 'mimo-v2.5', "
                "'base_url': 'https://opencode.ai/zen/go/v1'}], "
                "llm_tasks={'extraction': {'model': 'deepseek-v4-flash'}}); "
                "verify with test_llm_connection()"
            ),
            "collect_sources(domain='medical-research')",
            "process_collection(domain='medical-research')",
        ]


# ======================================================================
# _handle_add_source — quality tier warning
# ======================================================================


class TestAddSourceQualityWarning:
    def test_no_warning_for_tier_1(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_source(
                name="pubmed",
                url="https://eutils.ncbi.nlm.nih.gov",
                type="api",
                domain="medical",
            )

        assert result["created"] is True
        assert "warning" not in result

    def test_warning_for_existing_tier_3_source(self, tmp_path: Path) -> None:
        """When a source already exists in config with tier 3+, the dedup path warns."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical\n"
            "    active: true\n"
            "    sources:\n"
            "      - name: blog\n"
            "        type: web\n"
            "        url: https://example.com/blog\n"
            "        quality_tier: 4\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_source(
                name="blog",
                url="https://example.com/blog",
                type="web",
                domain="medical",
            )

        assert result["created"] is False
        assert "warning" in result
        assert "Quality tier 3+" in result["warning"]


# ======================================================================
# _handle_add_source / _handle_add_sources — requires_key derivation (D4)
# ======================================================================


class TestAddSourceRequiresKey:
    """add_source/add_sources derive and persist requires_key from source type."""

    def test_derives_true_for_key_requiring_type(self, tmp_path: Path) -> None:
        """A known key-requiring type (nyt) gets requires_key=True without the param."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: news\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_source(
                name="NYT",
                url="https://api.nytimes.com/svc",
                type="nyt",
                domain="news",
            )

            assert result["created"] is True
            assert result["source"]["requires_key"] is True

            schema = _handle_get_domain_schema("news")
            nyt_schema = next(s for s in schema["sources"] if s["name"] == "NYT")
            assert nyt_schema["requires_key"] is True

    def test_derives_false_for_keyless_type(self, tmp_path: Path) -> None:
        """A keyless type (rss) defaults to requires_key=False."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: news\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_source(
                name="feed",
                url="https://example.com/feed",
                type="rss",
                domain="news",
            )

        assert result["created"] is True
        assert result["source"]["requires_key"] is False

    def test_explicit_param_overrides_derivation(self, tmp_path: Path) -> None:
        """Generic api source with requires_key=True persists; get_domain_schema shows it."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: fin\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_source(
                name="alpha-vantage",
                url="https://www.alphavantage.co/query",
                type="api",
                domain="fin",
                requires_key=True,
            )

            assert result["created"] is True
            assert result["source"]["requires_key"] is True

            schema = _handle_get_domain_schema("fin")
            source_schema = next(
                s for s in schema["sources"] if s["name"] == "alpha-vantage"
            )
            assert source_schema["requires_key"] is True

    def test_add_sources_batch_forwards_settings_and_requires_key(
        self, tmp_path: Path
    ) -> None:
        """Batch add forwards per-source settings and requires_key to add_source."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\nllm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: fin\n"
            "    active: true\n"
            "    sources: []\n"
            "    topics: []\n"
        )

        with patch("autoinfo.mcp.server._config_path", return_value=config_path):
            result = _handle_add_sources(
                sources=[
                    {
                        "name": "nytimes",
                        "url": "https://api.nytimes.com/svc",
                        "type": "nyt",
                        "domain": "fin",
                    },
                    {
                        "name": "alpha",
                        "url": "https://www.alphavantage.co/query",
                        "type": "api",
                        "domain": "fin",
                        "requires_key": True,
                        "settings": {"query_param": "function"},
                    },
                ]
            )

            assert result["total"] == 2
            assert result["succeeded"] == 2

            schema = _handle_get_domain_schema("fin")
            by_name = {s["name"]: s for s in schema["sources"]}
            assert by_name["nytimes"]["requires_key"] is True  # derived from type
            assert by_name["alpha"]["requires_key"] is True  # explicit param
            assert by_name["alpha"]["url"] == "https://www.alphavantage.co/query"

            from autoinfo.config import load_config

            config = load_config(config_path)
            alpha = next(s for s in config.domains[0].sources if s.name == "alpha")
            assert alpha.settings.get("query_param") == "function"


# ======================================================================
# G3 multi-language relevance scoring
# ======================================================================


class TestG3MultiLanguage:
    def test_multi_language_keywords_dict(self) -> None:
        from autoinfo.quality import G3RelevanceScoring

        scorer = G3RelevanceScoring()
        item = MagicMock()
        item.title = "试管婴儿新突破"
        item.content = "胚胎研究取得重大进展"

        keywords: dict[str, list[str]] = {
            "en": ["IVF", "embryo"],
            "zh": ["试管婴儿", "胚胎"],
        }

        result = scorer.check(item=item, topic_keywords=keywords, threshold=30)
        # Should match "试管婴儿" and "胚胎" in the Chinese text = 2/4 matches = 50
        assert result.score >= 40.0
        assert result.passed is True
        assert result.flagged is False

    def test_multi_language_no_match(self) -> None:
        from autoinfo.quality import G3RelevanceScoring

        scorer = G3RelevanceScoring()
        item = MagicMock()
        item.title = "Python programming guide"
        item.content = "How to write better Python code"

        keywords: dict[str, list[str]] = {
            "en": ["IVF", "embryo"],
            "zh": ["试管婴儿", "胚胎"],
        }

        result = scorer.check(item=item, topic_keywords=keywords, threshold=30)
        # None of the keywords match — score = 0, flagged
        assert result.score < 30.0
        assert result.passed is False
        assert result.flagged is True

    def test_backwards_compatible_list(self) -> None:
        from autoinfo.quality import G3RelevanceScoring

        scorer = G3RelevanceScoring()
        item = MagicMock()
        item.title = "IVF breakthrough"
        item.content = "New embryo research"

        # Old-style list[str] must still work
        result = scorer.check(item=item, topic_keywords=["IVF", "embryo"], threshold=30)
        assert result.score >= 50.0
        assert result.passed is True


# ======================================================================
# #148 — MCP collect_sources offload + limit pass-through
# ======================================================================


class TestCollectSourcesOffload:
    """collect_sources is dispatched via asyncio.to_thread and passes limit."""

    @pytest.mark.asyncio
    async def test_collect_sources_dispatch_offloaded(self) -> None:
        """The collect_sources dispatch runs the handler in a worker thread."""
        import asyncio

        recorded: dict[str, object] = {}
        real_to_thread = asyncio.to_thread
        stub_result = {"success": True, "data": {"total_new": 0}}

        async def tracking_to_thread(func: object, *args: object, **kwargs: object):
            recorded["func"] = func
            recorded["args"] = (args, kwargs)
            return await real_to_thread(func, *args, **kwargs)

        with (
            patch.object(
                mcp_server, "_handle_collect_sources", return_value=stub_result
            ) as mock_handler,
            patch("autoinfo.mcp.server.asyncio.to_thread", tracking_to_thread),
        ):
            result = await mcp_server.call_tool(
                "collect_sources",
                {"domain": "medical-research", "limit": 3, "dry_run": True},
            )

        assert json.loads(result[0].text)["success"] is True
        assert recorded["func"] is mock_handler
        kwargs = dict(recorded["args"][1])
        assert kwargs["limit"] == 3
        assert kwargs["domain"] == "medical-research"

    @pytest.mark.asyncio
    async def test_collect_sources_schema_exposes_limit(self) -> None:
        """The tool schema advertises the limit param so agents can bound time."""
        tools = await mcp_server.list_tools()
        by_name = {t.name: t for t in tools}
        props = by_name["collect_sources"].inputSchema["properties"]
        assert "limit" in props
        assert props["limit"]["type"] == "integer"


# ======================================================================
# create_kb_entry (issue #279 — min content length guard)
# ======================================================================


class TestCreateKBEntryContentGuard:
    """_handle_create_kb_entry rejects content shorter than 50 chars.

    The KBStore is never touched for short content — the handler rejects
    up front with the canonical error envelope, matching the guard that
    process/import paths already enforce (MIN_KB_CONTENT_CHARS).
    """

    def test_short_content_returns_validation_error_envelope(self) -> None:
        """10-char content returns success=False + VALIDATION_ERROR."""
        result = _handle_create_kb_entry(
            domain="medical-research",
            title="t",
            content="x" * 10,
            source_url="https://e",
            source_type="web",
        )

        assert result["success"] is False
        assert result["error"]["code"] == "ValidationError"
        assert result["error"]["message"] == (
            "content must be at least 50 characters"
        )
        assert result["error"]["actionable"] is True

    def test_whitespace_only_content_rejected(self) -> None:
        """Whitespace-only content (stripped length 0) is rejected."""
        result = _handle_create_kb_entry(
            domain="medical-research",
            title="t",
            content="   \n  ",
            source_url="https://e",
            source_type="web",
        )

        assert result["success"] is False
        assert result["error"]["code"] == "ValidationError"
        assert result["error"]["message"] == (
            "content must be at least 50 characters"
        )

