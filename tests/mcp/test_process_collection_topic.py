"""MCP ``process_collection`` topic parameter tests (issue #68, PART A).

The ``process_collection`` tool schema must expose an optional ``topic``
property (defaulting to the union of all the domain's topic keywords) and
``_handle_process_collection`` must forward it into ``run_processing``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.server import _handle_process_collection
from autoinfo.process import ProcessResult


async def test_process_collection_schema_has_topic() -> None:
    """The registered ``process_collection`` tool carries a ``topic``
    property in its input schema."""
    tools = await mcp_server.list_tools()
    by_name = {t.name: t for t in tools}
    tool = by_name["process_collection"]
    assert tool.inputSchema is not None
    properties = tool.inputSchema.get("properties", {})
    assert "topic" in properties, (
        "process_collection inputSchema is missing the 'topic' property"
    )
    assert properties["topic"].get("type") == "string"
    assert "union" in properties["topic"].get("description", "").lower() or (
        "defaults" in properties["topic"].get("description", "").lower()
    )
    # topic is optional — the required list only contains domain
    assert "topic" not in tool.inputSchema.get("required", [])


def test_handle_process_collection_forwards_topic() -> None:
    """``_handle_process_collection(domain=..., topic=...)`` forwards the
    topic kwarg into ``run_processing``."""
    with patch("autoinfo.process.run_processing") as mock_proc:
        mock_proc.return_value = ProcessResult(domain="x", total_items=1)
        result = _handle_process_collection(domain="x", topic="t")

    assert result["domain"] == "x"
    kwargs: dict[str, Any] = mock_proc.call_args.kwargs
    assert kwargs.get("topic") == "t", (
        f"run_processing was not called with topic='t' (kwargs={kwargs})"
    )
    assert kwargs.get("domain") == "x"
