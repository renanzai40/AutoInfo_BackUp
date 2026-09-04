"""Read-only MCP server mode (``autoinfo serve --agent``).

Hermetic tests for the plan todo-14 deliverable:

1. **Whitelist mechanism** — ``_READONLY_TOOLS`` constant = exactly the 4
   read-only tools; ``set_readonly_mode()`` toggles the gate.
2. **Double gate, gate 1 (tools/list)** — in readonly mode ``list_tools()``
   lists ONLY the 4 whitelisted tools; the default (full) mode still lists
   all 146 (regression assertion).
3. **Double gate, gate 2 (call dispatch)** — non-whitelisted tool calls in
   readonly mode return an explicit error envelope with
   ``code=READ_ONLY_SERVER`` (never silent), and the attempt is still
   written to the append-only audit log.
4. **LLM-guard interaction** — ``export_kb(format="agent")`` returns the
   JSON-LD ``@type`` via the pure-function path (``_export_agent_json``),
   with no LLM key configured.

Every test runs in a temp cwd (monkeypatch.chdir) and clears the mode flag
afterwards so the module-level state never leaks between tests.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from mcp.types import TextContent

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.errors import ErrorCode

# The 4 read-only tools (plan todo-14).  run_validation_scenario is
# EXPLICITLY EXCLUDED — its steps contain write ops (collect/promote/delete).
READONLY_TOOLS = frozenset({
    "search_knowledge_base",
    "get_kb_entry",
    "export_kb",
    "list_validation_scenarios",
})


@pytest.fixture(autouse=True)
def _restore_full_mode() -> None:
    """Guarantee the module-level readonly flag is reset after each test."""
    yield
    mcp_server.set_readonly_mode(False)


class TestWhitelistConstant:
    """``_READONLY_TOOLS`` is exactly the 4 read-only tools."""

    def test_readonly_tools_constant(self) -> None:
        assert mcp_server._READONLY_TOOLS == READONLY_TOOLS
        # run_validation_scenario must never be whitelisted
        assert "run_validation_scenario" not in mcp_server._READONLY_TOOLS

    def test_whitelisted_tools_are_real_tools(self) -> None:
        import asyncio

        tools = asyncio.run(mcp_server.list_tools())
        all_names = {t.name for t in tools}
        assert READONLY_TOOLS <= all_names


class TestReadonlyListTools:
    """Gate 1: readonly tools/list returns exactly the 4 whitelisted tools."""

    async def test_readonly_mode_lists_exactly_4_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        mcp_server.set_readonly_mode(True)
        tools = await mcp_server.list_tools()
        names = sorted(t.name for t in tools)
        assert names == sorted(READONLY_TOOLS)
        assert len(tools) == 4

    async def test_default_mode_still_lists_all_146_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: full (default) server mode is unchanged — 146 tools."""
        monkeypatch.chdir(tmp_path)
        assert mcp_server._is_readonly() is False
        tools = await mcp_server.list_tools()
        assert len(tools) == 146


class TestReadonlyCallGate:
    """Gate 2: non-whitelisted calls return an explicit READ_ONLY_SERVER error."""

    async def test_collect_sources_blocked_with_read_only_server_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        mcp_server.set_readonly_mode(True)
        result = await mcp_server.call_tool(
            "collect_sources", {"domain": "medical-research"}
        )
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        body = json.loads(result[0].text)
        assert body["success"] is False
        assert body["error"]["code"] == ErrorCode.READ_ONLY_SERVER.value
        assert body["error"]["message"], "error message must not be empty"
        assert body["error"]["actionable"] is True

    async def test_run_validation_scenario_also_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_validation_scenario is explicitly excluded from the whitelist."""
        monkeypatch.chdir(tmp_path)
        mcp_server.set_readonly_mode(True)
        result = await mcp_server.call_tool(
            "run_validation_scenario", {"scenario": "system-health"}
        )
        body = json.loads(result[0].text)
        assert body["success"] is False
        assert body["error"]["code"] == ErrorCode.READ_ONLY_SERVER.value

    async def test_blocked_call_still_writes_audit_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Audit: readonly-mode calls still write the dispatch audit row."""
        monkeypatch.chdir(tmp_path)
        mcp_server.set_readonly_mode(True)
        await mcp_server.call_tool(
            "collect_sources", {"domain": "medical-research"}
        )
        rows = _read_audit_rows(tmp_path / "autoinfo.db")
        collect_rows = [
            r for r in rows
            if r["resource_type"] == "collect_sources"
        ]
        assert collect_rows, (
            f"expected an audit row for collect_sources, got: {rows}"
        )
        assert collect_rows[0]["action"] == "tool_call"
        details = json.loads(collect_rows[0]["details"])
        assert details["result_code"] == "read_only"

    async def test_whitelisted_tool_still_dispatches_in_readonly_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitelisted names reach their real handlers (no false block)."""
        monkeypatch.chdir(tmp_path)
        mcp_server.set_readonly_mode(True)
        result = await mcp_server.call_tool("list_validation_scenarios", {})
        body = json.loads(result[0].text)
        assert body["success"] is True


class TestExportAgentPureFunction:
    """export_kb(format="agent") works with NO LLM key via the pure path."""

    async def test_export_agent_returns_at_type_without_llm_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)
        assert mcp_server._is_llm_configured() is False
        # export_kb requires a config file; init_project's audit writes (and
        # every dispatch) auto-create a bare autoinfo.db WITHOUT the entries
        # table, so rebuild a proper empty index db — the agent branch then
        # runs the pure _export_agent_json path with zero entries.
        init = await mcp_server.call_tool(
            "init_project", {"domain": "medical-research"}
        )
        assert json.loads(init[0].text)["success"] is True
        from autoinfo.kb import SQLiteIndex

        SQLiteIndex(tmp_path / "autoinfo.db").init_db()

        mcp_server.set_readonly_mode(True)
        result = await mcp_server.call_tool(
            "export_kb", {"domain": "medical-research", "format": "agent"}
        )
        body = json.loads(result[0].text)
        # export_kb's agent dict carries success=True → passes through the
        # call_tool envelope unwrapped; the JSON-LD @type must be present.
        assert body.get("@type") == "KnowledgeBaseExport", body
        assert body.get("@context"), body
        assert body.get("stats", {}).get("total_entries") == 0


def _read_audit_rows(db_path: Path) -> list[dict[str, object]]:
    """Read all rows from the audit_log table (hermetic, explicit path)."""
    assert db_path.is_file(), f"audit db missing: {db_path}"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY rowid"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
