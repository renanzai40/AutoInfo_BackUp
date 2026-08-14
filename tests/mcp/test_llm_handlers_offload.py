"""Tests: 14 synchronous LLM-required MCP handlers are offloaded via asyncio.to_thread.

Todo 7 of the llm-concurrency-remediation plan.

Every member of ``_LLM_REQUIRED_TOOLS`` that is a *synchronous* handler and
not already offloaded must be dispatched through ``asyncio.to_thread`` so the
asyncio event loop stays responsive while the (potentially slow) LLM call is
in flight — mirroring the existing pattern used for ``collect_sources`` /
``process_collection`` / ``batch_run`` (issue #136).

Excluded on purpose (16 members - 2 = 14):
  * ``process_collection``  — already offloaded via to_thread
  * ``batch_run``           — already offloaded via to_thread
  * ``run_validation_scenario`` — async handler, awaited directly; not in
    ``_LLM_REQUIRED_TOOLS`` (the scenario engine reports per-step
    ``unconfigured`` itself, so the dispatch-level LLM guard would block
    scenarios that need no LLM at all)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest

from autoinfo.mcp import server as mcp_server

# The exact 14 synchronous LLM-required handlers that must be offloaded.
# (tool name, handler module attribute)
OFFLOADED_HANDLERS: list[tuple[str, str]] = [
    ("suggest_keywords", "_handle_suggest_keywords"),
    ("classify_cefr", "_handle_classify_cefr"),
    ("cefr_batch", "_handle_cefr_batch"),
    ("extract_fields", "_handle_extract_fields"),
    ("generate_digest", "_handle_generate_digest"),
    ("generate_report", "_handle_generate_report"),
    ("generate_cross_domain_report", "_handle_generate_cross_domain_report"),
    ("generate_tutorial", "_handle_generate_tutorial"),
    ("generate_presentation", "_handle_generate_presentation"),
    ("localize_content", "_handle_localize_content"),
    ("query_collected", "_handle_query_collected"),
    ("recommend_content", "_handle_recommend_content"),
    ("simplify_content", "_handle_simplify_content"),
    ("promote_kb_draft", "_handle_promote_kb_draft"),
]


def _assert_exact_14() -> None:
    """Guard the member set: exactly these 14 must be offloaded (16 - 2)."""
    assert len(OFFLOADED_HANDLERS) == 14, "exactly 14 sync LLM handlers"
    assert len({name for name, _ in OFFLOADED_HANDLERS}) == 14, "no duplicates"


def test_exactly_14_sync_llm_handlers_listed() -> None:
    """The test matrix itself must stay at exactly 14 handlers (16 - 2)."""
    _assert_exact_14()
    all_llm_required = mcp_server._LLM_REQUIRED_TOOLS
    names = {name for name, _ in OFFLOADED_HANDLERS}
    assert names <= all_llm_required
    # the two remaining excluded members are the already-offloaded ones
    # (run_validation_scenario is async and not LLM-required — see module doc)
    assert all_llm_required - names == {
        "process_collection",
        "batch_run",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,handler_name", OFFLOADED_HANDLERS)
async def test_sync_llm_handler_offloaded_via_to_thread(
    tool_name: str, handler_name: str
) -> None:
    """Dispatch of each sync LLM handler goes through asyncio.to_thread exactly once."""
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    stub_result = {"success": True, "data": {"offloaded": True}}

    async def tracking_to_thread(
        func: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        calls.append((func, args, kwargs))
        return stub_result

    with (
        patch.object(mcp_server, "_is_llm_configured", return_value=True),
        patch("autoinfo.mcp.server.asyncio.to_thread", tracking_to_thread),
    ):
        result = await mcp_server.call_tool(tool_name, {})

    assert json.loads(result[0].text)["success"] is True
    assert len(calls) == 1, (
        f"{tool_name}: expected exactly one asyncio.to_thread call, got {len(calls)}"
    )
    func, _args, _kwargs = calls[0]
    assert func is getattr(mcp_server, handler_name), (
        f"{tool_name}: offloaded callable must be {handler_name}, got {func!r}"
    )


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_while_handler_blocks() -> None:
    """A long-blocking sync handler must not freeze the event loop.

    The mocked handler blocks for 5s.  With ``asyncio.to_thread`` offload, an
    ``asyncio.sleep(0.1)`` timer running on the same loop completes BEFORE the
    handler returns.  If the handler ran on the loop, the timer could only
    complete after the handler finished, flipping the completion order.
    """
    completion: list[str] = []

    def blocking_handler(**kwargs: object) -> dict[str, object]:
        time.sleep(5.0)
        return {"success": True, "data": {"ok": True}}

    async def run_tool() -> None:
        await mcp_server.call_tool("simplify_content", {})
        completion.append("tool")

    async def run_timer() -> None:
        await asyncio.sleep(0.1)
        completion.append("timer")

    with (
        patch.object(mcp_server, "_is_llm_configured", return_value=True),
        patch.object(mcp_server, "_handle_simplify_content", blocking_handler),
    ):
        await asyncio.gather(run_tool(), run_timer())

    assert completion == ["timer", "tool"], (
        "timer must complete while the 5s handler is in flight — "
        f"event loop was blocked, got {completion}"
    )
