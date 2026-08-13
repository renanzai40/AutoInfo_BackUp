"""Tests for v0.2 MCP tools — discovery, source/topic management, KB stubs.

Covers all 14 new tools added in task 4:

- Discovery (4):        list_domains, get_domain_schema, list_available_models,
                        get_effective_llm_config
- Source Management (5): add_source, add_sources, remove_source, test_source,
                        list_sources
- Topic Management (2): add_topic, remove_topic
- KB / Output (3):      search_knowledge_base (stub), flag_for_knowledge_base (stub),
                        list_output_templates
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, TextContent

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.errors import ErrorCode
from autoinfo.mcp.server import (
    _error_response,
    _handle_add_source,
    _handle_add_sources,
    _handle_add_topic,
    _handle_get_domain_schema,
    _handle_get_effective_llm_config,
    _handle_list_available_models,
    _handle_list_domains,
    _handle_list_output_templates,
    _handle_list_sources,
    _handle_remove_source,
    _handle_remove_topic,
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
"""


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary project with a valid ``.autoinfo/config.yaml``.

    Changes the CWD to *tmp_path* so that ``_load_config`` / ``_save_config``
    operate on the temporary config.  Restores CWD after the test.
    """
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(SAMPLE_CONFIG_YAML, encoding="utf-8")

    cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


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


def _mock_load_config(config_dict: dict | None = None):
    """Patch ``_load_config`` to return a config built from *config_dict*."""
    from autoinfo.config import _dict_to_config

    data = config_dict or _MINIMAL_CONFIG
    return patch.object(mcp_server, "_load_config", return_value=_dict_to_config(data))


def _mock_save_config():
    """Patch ``_save_config`` to a no-op."""
    return patch.object(mcp_server, "_save_config", lambda config: None)


# ======================================================================
# Discovery tools
# ======================================================================


class TestListDomains:
    def test_returns_domains_from_config(self, tmp_config: Path) -> None:
        result = _handle_list_domains()
        assert result["count"] >= 1
        names = {d["name"] for d in result["domains"]}
        assert "medical-research" in names

    def test_source_and_topic_counts(self, tmp_config: Path) -> None:
        result = _handle_list_domains()
        for domain in result["domains"]:
            if domain["name"] == "medical-research":
                assert domain["source_count"] == 1
                assert domain["topic_count"] == 1

    def test_handles_missing_config(self) -> None:
        with patch.object(mcp_server, "_load_config", side_effect=FileNotFoundError("no config")):
            result = _handle_list_domains()
            assert result["count"] == 0
            assert "error_code" in result


class TestGetDomainSchema:
    def test_returns_schema_for_known_domain(self, tmp_config: Path) -> None:
        result = _handle_get_domain_schema(domain="medical-research")
        assert "error_code" not in result
        assert result["domain"] == "medical-research"
        assert "extract_fields" in result
        assert "output_templates" in result
        assert "sources" in result
        assert "topics" in result
        # output_templates is a list of dicts; check name field
        template_names = {t["name"] for t in result["output_templates"]}
        assert "digest" in template_names

    def test_sources_in_schema(self, tmp_config: Path) -> None:
        result = _handle_get_domain_schema(domain="medical-research")
        source_names = {s["name"] for s in result["sources"]}
        assert "pubmed" in source_names

    def test_topics_in_schema(self, tmp_config: Path) -> None:
        result = _handle_get_domain_schema(domain="medical-research")
        topic_names = {t["name"] for t in result["topics"]}
        assert "IVF breakthroughs" in topic_names

    def test_unknown_domain_returns_error(self, tmp_config: Path) -> None:
        result = _handle_get_domain_schema(domain="nonexistent")
        assert result["success"] is False
        assert result["error"]["code"] == "DomainNotFound"

    def test_extract_fields_structure(self, tmp_config: Path) -> None:
        result = _handle_get_domain_schema(domain="medical-research")
        fields = result["extract_fields"]
        assert "tl_dr" in fields
        assert "key_points" in fields
        assert "entities" in fields
        assert "relevance_score" in fields


class TestListAvailableModels:
    def test_returns_configured_models(self, tmp_config: Path) -> None:
        result = _handle_list_available_models()
        assert result["count"] >= 1
        model = result["models"][0]
        assert "provider" in model
        assert "model" in model
        assert "task" in model

    def test_handles_missing_config(self) -> None:
        with patch.object(mcp_server, "_load_config", side_effect=FileNotFoundError("no config")):
            result = _handle_list_available_models()
            assert result["count"] == 0


class TestGetEffectiveLLMConfig:
    @patch("autoinfo.config.get_config_path")
    @patch("autoinfo.config.load_config")
    def test_returns_llm_config(self, mock_load: MagicMock, mock_path: MagicMock) -> None:
        from autoinfo.config import Config, LLMConfig, ProjectConfig

        mock_path.return_value = Path("/fake/.autoinfo/config.yaml")
        mock_load.return_value = Config(
            project=ProjectConfig(name="Test"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="sk-test"),
        )

        result = _handle_get_effective_llm_config(task="extraction")
        assert result["provider"] == "openrouter"
        assert result["model"] == "deepseek/deepseek-chat"
        assert result["task"] == "extraction"

    @patch("autoinfo.config.get_config_path", return_value=None)
    def test_raises_on_no_config(self, mock_path: MagicMock) -> None:
        result = _handle_get_effective_llm_config(task="extraction")
        assert "error_code" in result


# ======================================================================
# Source management tools
# ======================================================================


class TestAddSource:
    def test_adds_new_source(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="test-feed",
            url="https://example.com/rss",
            type="rss",
            domain="medical-research",
        )
        assert result["created"] is True
        assert result["source"]["name"] == "test-feed"
        assert result["source_id"] == "medical-research:test-feed"

    def test_idempotent_same_url_and_type(self, tmp_config: Path) -> None:
        # First add creates
        r1 = _handle_add_source(
            name="dup-source",
            url="https://example.com/dup",
            type="api",
            domain="medical-research",
        )
        assert r1["created"] is True
        first_id = r1["source_id"]

        # Second add with same url+type returns existing (even if name differs)
        r2 = _handle_add_source(
            name="dup-source-different-name",
            url="https://example.com/dup",
            type="api",
            domain="medical-research",
        )
        assert r2["created"] is False
        assert r2["source_id"] == first_id

    def test_unknown_domain_returns_error(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="test", url="https://example.com", domain="nonexistent"
        )
        assert "error_code" in result
        assert result["error_code"] == "DomainNotFound"

    def test_persists_to_config(self, tmp_config: Path) -> None:
        _handle_add_source(
            name="persist-test",
            url="https://example.com/persist",
            type="rss",
            domain="medical-research",
        )
        # Reload config and verify
        from autoinfo.config import load_config

        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {s.name for s in domain.sources}
        assert "persist-test" in names


class TestAddSources:
    def test_batch_adds_sources(self, tmp_config: Path) -> None:
        sources = [
            {
                "name": "src-a",
                "url": "https://a.example.com",
                "type": "api",
                "domain": "medical-research",
            },
            {
                "name": "src-b",
                "url": "https://b.example.com",
                "type": "rss",
                "domain": "medical-research",
            },
        ]
        result = _handle_add_sources(sources=sources)
        assert result["total"] == 2
        assert result["succeeded"] == 2
        assert result["errored"] == 0

    def test_per_source_error_isolation(self, tmp_config: Path) -> None:
        sources = [
            {"name": "good", "url": "https://good.example.com", "domain": "medical-research"},
            {"name": "bad", "url": "https://bad.example.com", "domain": "nonexistent-domain"},
        ]
        result = _handle_add_sources(sources=sources)
        assert result["total"] == 2
        assert result["succeeded"] >= 1
        assert result["errored"] >= 1

    def test_returns_results_with_indices(self, tmp_config: Path) -> None:
        sources = [
            {"name": "src-c", "url": "https://c.example.com", "domain": "medical-research"},
        ]
        result = _handle_add_sources(sources=sources)
        assert result["results"][0]["index"] == 0


class TestRemoveSource:
    def test_removes_existing_source(self, tmp_config: Path) -> None:
        # First add a source
        _handle_add_source(
            name="to-remove",
            url="https://remove.example.com",
            type="api",
            domain="medical-research",
        )
        # Then remove it
        result = _handle_remove_source(source_id="medical-research:to-remove", confirm=True)
        assert result["removed"] is True

    def test_returns_error_for_nonexistent_source(self, tmp_config: Path) -> None:
        result = _handle_remove_source(source_id="medical-research:nonexistent", confirm=True)
        assert "error_code" in result
        assert result["error_code"] == "SourceNotFound"

    def test_returns_error_for_malformed_id(self, tmp_config: Path) -> None:
        result = _handle_remove_source(source_id="no-colon-here", confirm=True)
        assert "error_code" in result
        assert "InvalidSourceId" in result["error_code"]

    def test_removed_source_no_longer_in_config(self, tmp_config: Path) -> None:
        _handle_add_source(
            name="remove-me",
            url="https://remove.example.com",
            type="api",
            domain="medical-research",
        )
        _handle_remove_source(source_id="medical-research:remove-me", confirm=True)

        from autoinfo.config import load_config

        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {s.name for s in domain.sources}
        assert "remove-me" not in names


class TestListSources:
    def test_lists_sources_for_domain(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="medical-research")
        assert result["count"] >= 1
        names = {s["name"] for s in result["sources"]}
        assert "pubmed" in names

    def test_sources_have_source_id(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="medical-research")
        for source in result["sources"]:
            assert "source_id" in source
            assert source["source_id"].startswith("medical-research:")

    def test_unknown_domain_returns_error(self, tmp_config: Path) -> None:
        result = _handle_list_sources(domain="nonexistent")
        assert "error_code" in result


class TestTestSource:
    def test_unreachable_url_returns_error(self) -> None:
        with patch("httpx.get", side_effect=Exception("Connection refused")):
            from autoinfo.mcp.server import _handle_test_source

            result = _handle_test_source(url="https://nonexistent.example.com")
            assert result["success"] is False
            assert "error" in result

    def test_timeout_returns_structured_error(self) -> None:
        from httpx import TimeoutException

        with patch("httpx.get", side_effect=TimeoutException("timed out")):
            from autoinfo.mcp.server import _handle_test_source

            result = _handle_test_source(url="https://slow.example.com")
            assert result["success"] is False
            assert result["error"]["code"] == ErrorCode.TIMEOUT.value

    def test_successful_response(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"key": "value"}'
        mock_response.content = b'{"key": "value"}'

        with patch("httpx.get", return_value=mock_response):
            from autoinfo.mcp.server import _handle_test_source

            result = _handle_test_source(url="https://api.example.com/data")
            assert result["reachable"] is True
            assert result["status_code"] == 200
            assert result["format"] == "json"


# ======================================================================
# Topic management tools
# ======================================================================


class TestAddTopic:
    def test_adds_new_topic(self, tmp_config: Path) -> None:
        result = _handle_add_topic(
            domain="medical-research",
            name="Gene Therapy",
            keywords=["gene", "therapy", "CRISPR"],
        )
        assert result["created"] is True
        assert result["topic"]["name"] == "Gene Therapy"
        assert "CRISPR" in result["topic"]["keywords"]

    def test_idempotent_same_name(self, tmp_config: Path) -> None:
        r1 = _handle_add_topic(domain="medical-research", name="Unique Topic")
        assert r1["created"] is True

        r2 = _handle_add_topic(domain="medical-research", name="Unique Topic")
        assert r2["created"] is False

    def test_unknown_domain_returns_error(self, tmp_config: Path) -> None:
        result = _handle_add_topic(domain="nonexistent", name="Topic")
        assert "error_code" in result

    def test_persists_to_config(self, tmp_config: Path) -> None:
        _handle_add_topic(
            domain="medical-research", name="New Topic", keywords=["new"]
        )
        from autoinfo.config import load_config

        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {t.name for t in domain.topics}
        assert "New Topic" in names


class TestRemoveTopic:
    def test_removes_existing_topic(self, tmp_config: Path) -> None:
        _handle_add_topic(domain="medical-research", name="Temp Topic")
        result = _handle_remove_topic(
            domain="medical-research", topic_id="medical-research:Temp Topic", confirm=True
        )
        assert result["removed"] is True

    def test_uses_plain_name_as_topic_id(self, tmp_config: Path) -> None:
        _handle_add_topic(domain="medical-research", name="Plain Name")
        result = _handle_remove_topic(
            domain="medical-research", topic_id="Plain Name", confirm=True
        )
        assert result["removed"] is True

    def test_returns_error_for_nonexistent_topic(self, tmp_config: Path) -> None:
        result = _handle_remove_topic(
            domain="medical-research", topic_id="nonexistent", confirm=True
        )
        assert "error_code" in result
        assert result["error_code"] == "TopicNotFound"

    def test_removed_topic_no_longer_in_config(self, tmp_config: Path) -> None:
        _handle_add_topic(domain="medical-research", name="Remove Me")
        _handle_remove_topic(
            domain="medical-research", topic_id="medical-research:Remove Me", confirm=True
        )

        from autoinfo.config import load_config

        config = load_config(Path.cwd() / ".autoinfo" / "config.yaml")
        domain = [d for d in config.domains if d.name == "medical-research"][0]
        names = {t.name for t in domain.topics}
        assert "Remove Me" not in names


# ======================================================================
# Output / KB stubs
# ======================================================================


class TestListOutputTemplates:
    def test_returns_templates(self) -> None:
        result = _handle_list_output_templates(domain="medical-research")
        assert result["count"] == 8
        template_names = {t["name"] for t in result["templates"]}
        assert "digest" in template_names
        assert "report" in template_names
        assert "tutorial" in template_names
        assert "presentation" in template_names
        assert "premium-briefing" in template_names
        assert "enterprise-briefing" in template_names

    def test_works_without_domain(self) -> None:
        result = _handle_list_output_templates()
        assert result["count"] == 8


class TestSearchKnowledgeBaseStub:
    # TRIAGE #71 (regression): `_handle_search_knowledge_base` short-circuits
    # on `_detect_kb_status()` (`server.py:2068-2079`) — the "empty" branch
    # returns a `count` key, not the legacy `total_count`. Stub the status so
    # the test is hermetic (CI has no `knowledge/` dir → "uninitialized").
    @patch("autoinfo.mcp.server._detect_kb_status", return_value="empty")
    def test_returns_result_not_stub(self, mock_status: MagicMock) -> None:
        from autoinfo.mcp.server import _handle_search_knowledge_base

        result = _handle_search_knowledge_base(
            query="test", domain="medical-research"
        )
        assert "entries" in result
        assert "count" in result

    @patch("autoinfo.mcp.server._detect_kb_status", return_value="operational")
    def test_forwards_custom_fields_filter(
        self, mock_status: MagicMock
    ) -> None:
        """output-quality-mega todo 25: the faceted filter key
        ``filter_custom_fields`` must reach ``KBStore.search_knowledge_base``
        through the existing tool — no new tool is added."""
        from autoinfo.mcp.server import _handle_search_knowledge_base

        with patch("autoinfo.kb.KBStore") as kb_cls:
            kb = MagicMock()
            kb.search_knowledge_base.return_value = {"entries": [], "count": 0}
            kb_cls.return_value = kb

            _handle_search_knowledge_base(
                query="IVF",
                domain="medical-research",
                filter_custom_fields={"product_analysis.action_required": ""},
            )

            kwargs = kb.search_knowledge_base.call_args.kwargs
            assert kwargs["filter_custom_fields"] == {
                "product_analysis.action_required": ""
            }
            assert kwargs["query"] == "IVF"

    @patch("autoinfo.mcp.server._detect_kb_status", return_value="operational")
    def test_without_custom_fields_filter_defaults_none(
        self, mock_status: MagicMock
    ) -> None:
        """Default search behaviour unchanged: no filter_custom_fields is sent."""
        from autoinfo.mcp.server import _handle_search_knowledge_base

        with patch("autoinfo.kb.KBStore") as kb_cls:
            kb = MagicMock()
            kb.search_knowledge_base.return_value = {"entries": [], "count": 0}
            kb_cls.return_value = kb

            _handle_search_knowledge_base(query="IVF", domain="medical-research")

            kwargs = kb.search_knowledge_base.call_args.kwargs
            assert kwargs.get("filter_custom_fields") is None


class TestFlagForKnowledgeBaseStub:
    def test_returns_result_not_stub(self) -> None:
        from autoinfo.mcp.server import _handle_flag_for_knowledge_base

        result = _handle_flag_for_knowledge_base(
            summary_id="nonexistent-summary",
            tags=["important"],
            importance=5,
        )
        # Entry won't be found, but it should not raise NotImplementedError
        assert "flagged" in result or "error_code" in result


# ======================================================================
# Tool registration (list_tools returns 20)
# ======================================================================


class TestToolRegistrationV2:
    @pytest.mark.asyncio
    async def test_lists_twenty_tools(self) -> None:
        tools = await mcp_server.list_tools()
        assert len(tools) >= 65

    @pytest.mark.asyncio
    async def test_all_new_tools_present(self) -> None:
        tools = await mcp_server.list_tools()
        names = {t.name for t in tools}
        expected = {
            "list_domains",
            "get_domain_schema",
            "list_available_models",
            "get_effective_llm_config",
            "add_source",
            "add_sources",
            "remove_source",
            "test_source",
            "list_sources",
            "add_topic",
            "remove_topic",
            "search_knowledge_base",
            "flag_for_knowledge_base",
            "list_output_templates",
            "get_processing_progress",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    @pytest.mark.asyncio
    async def test_each_new_tool_has_input_schema(self) -> None:
        tools = await mcp_server.list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"

    @pytest.mark.asyncio
    async def test_new_tools_required_params(self) -> None:
        tools = await mcp_server.list_tools()
        by_name = {t.name: t for t in tools}

        schema = by_name["add_source"].inputSchema
        assert "name" in schema.get("required", [])
        assert "url" in schema.get("required", [])
        assert "domain" in schema.get("required", [])

        schema = by_name["remove_source"].inputSchema
        assert "source_id" in schema.get("required", [])

        schema = by_name["get_domain_schema"].inputSchema
        assert "domain" in schema.get("required", [])

        schema = by_name["add_topic"].inputSchema
        assert "domain" in schema.get("required", [])
        assert "name" in schema.get("required", [])

        schema = by_name["test_source"].inputSchema
        assert "url" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_output_tools_accept_product_param(self) -> None:
        """generate_digest and generate_report schemas declare the product param."""
        tools = await mcp_server.list_tools()
        by_name = {t.name: t for t in tools}

        digest_schema = by_name["generate_digest"].inputSchema
        assert "product" in digest_schema["properties"]
        assert digest_schema["properties"]["product"]["type"] == "string"
        assert "product" not in digest_schema.get("required", [])

        report_schema = by_name["generate_report"].inputSchema
        assert "product" in report_schema["properties"]
        assert report_schema["properties"]["product"]["type"] == "string"
        assert "product" not in report_schema.get("required", [])

    @pytest.mark.asyncio
    async def test_search_schema_declares_custom_fields_filter(self) -> None:
        """output-quality-mega todo 25: the existing search tool's schema
        carries the new faceted filter key — no new tool is added."""
        tools = await mcp_server.list_tools()
        by_name = {t.name: t for t in tools}

        schema = by_name["search_knowledge_base"].inputSchema
        props = schema["properties"]
        assert "filter_custom_fields" in props
        assert props["filter_custom_fields"]["type"] == "object"
        assert "filter_custom_fields" not in schema.get("required", [])


# ======================================================================
# call_tool dispatch for new tools
# ======================================================================


class TestNewToolDispatch:
    @pytest.mark.asyncio
    async def test_list_domains_dispatches(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="list_domains", arguments={}),
        )
        with _mock_load_config():
            result = await handler(request)
        data = json.loads(result.root.content[0].text)
        # Envelope shape
        assert data["success"] is True
        assert "domains" in data["data"]

    @pytest.mark.asyncio
    async def test_get_domain_schema_dispatches(self, tmp_config: Path) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_domain_schema",
                arguments={"domain": "medical-research"},
            ),
        )
        result = await handler(request)
        data = json.loads(result.root.content[0].text)
        assert data["success"] is True
        assert data["data"]["domain"] == "medical-research"

    @pytest.mark.asyncio
    async def test_list_output_templates_dispatches(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="list_output_templates",
                arguments={"domain": "test"},
            ),
        )
        result = await handler(request)
        data = json.loads(result.root.content[0].text)
        assert data["success"] is True
        assert data["data"]["count"] == 8

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="nonexistent_v2", arguments={}),
        )
        result = await handler(request)
        data = json.loads(result.root.content[0].text)
        assert data["success"] is False
        assert data["error"]["code"] == "UnknownTool"
        assert data["error"]["actionable"] is False

    @pytest.mark.asyncio
    # TRIAGE #72 (regression): same `count` vs `total_count` shape drift as
    # #71 (`server.py:2074-2078`) — stub `_detect_kb_status` to "empty" so
    # the dispatch path returns the deterministic short-circuit shape.
    @patch("autoinfo.mcp.server._detect_kb_status", return_value="empty")
    async def test_implemented_tool_returns_result(self, mock_status: MagicMock) -> None:
        """search_knowledge_base is now implemented, not a stub."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="search_knowledge_base",
                arguments={"query": "test"},
            ),
        )
        result = await handler(request)
        data = json.loads(result.root.content[0].text)
        assert data["success"] is True
        assert "entries" in data["data"]
        assert "count" in data["data"]

# ======================================================================
# Error response format verification
# ======================================================================


class TestErrorResponseV2:
    def test_error_includes_required_fields(self) -> None:
        # TRIAGE #73 (regression): 51dbc69 maps ValueError → VALIDATION_ERROR
        # at server.py:6173-6174 — missing/required params are a client-side
        # validation error, not an internal one. Test asserted the legacy code.
        exc = ValueError("Test error")
        result = _error_response(exc)

        assert len(result) == 1
        content = result[0]
        assert isinstance(content, TextContent)

        data = json.loads(content.text)
        # Envelope shape
        assert data["success"] is False
        assert "error" in data
        assert data["error"]["code"] == "ValidationError"
        assert "message" in data["error"]
        assert "actionable" in data["error"]

    def test_add_source_domain_not_found(self, tmp_config: Path) -> None:
        result = _handle_add_source(
            name="x", url="https://x.com", domain="missing-domain"
        )
        assert "error_code" in result
        assert result["error_code"] == "DomainNotFound"

    def test_remove_source_not_found(self, tmp_config: Path) -> None:
        result = _handle_remove_source(source_id="medical-research:ghost", confirm=True)
        assert "error_code" in result
        assert result["error_code"] == "SourceNotFound"

    def test_add_topic_domain_not_found(self, tmp_config: Path) -> None:
        result = _handle_add_topic(domain="missing", name="t")
        assert "error_code" in result

    def test_remove_topic_not_found(self, tmp_config: Path) -> None:
        result = _handle_remove_topic(domain="medical-research", topic_id="ghost", confirm=True)
        assert "error_code" in result


# ======================================================================
# health_check reports 20 tools
# ======================================================================


class TestHealthCheckV2:
    def test_reports_20_tools(self) -> None:
        from autoinfo.mcp.server import _handle_health_check

        result = _handle_health_check()
        assert result["tools_count"] >= 70
