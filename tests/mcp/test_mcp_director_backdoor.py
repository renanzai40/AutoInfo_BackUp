"""Server-level tests for the Director backdoor MCP tools (T5).

Covers the MCP surface:
  1. Tool manifest registration — ``demote_kb_wiki`` and ``force_promote``
     are registered; ``soft_delete_entry`` carries an ``actor`` param.
  2. ``DIRECTOR_ONLY`` error envelope — non-whitelisted actors get
     ``{success: false, error: {code: "DIRECTOR_ONLY", message, actionable: true}}``
     from both the dispatch guard (``call_tool``) and the handlers.
  3. The existing ``soft_delete_entry`` tool wires the same guard for
     tier==03-Wiki targets (store-level ``DirectorOnlyError`` → envelope).
  4. Happy paths — director actors pass through to the store.

Handlers construct ``KBStore()`` against the process CWD, so tests that
reach the store ``monkeypatch.chdir`` into a temp dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest

from autoinfo.kb import KBStore
from autoinfo.mcp.server import (
    _handle_demote_kb_wiki,
    _handle_force_promote,
    call_tool,
    list_tools,
)
from autoinfo.models import Item, KBEntry

# ===================================================================
# Fixtures / builders
# ===================================================================


@pytest.fixture
def kb_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir into a temp dir so ``KBStore()`` roots there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_scored_raw(store: KBStore) -> KBEntry:
    """Store a 01-Raw entry with full provenance + G1/G3 scores.

    Returns the stored :class:`KBEntry` — its ``entry_id`` is derived by
    ``store_entry`` (domain/slug), not from ``Item.id``.
    """
    item = Item(
        id="raw-001",
        source_name="pubmed",
        source_type="api",
        source_url="https://example.com/paper1",
        source_platform="pubmed",
        title="Raw source paper",
        content=(
            "Time-lapse embryo imaging has been proposed as a non-invasive "
            "method to improve embryo selection in IVF cycles."
        ),
        content_type="text",
        collected_at="2026-07-15T10:30:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=2,
    )
    return store.store_entry(item)


def _parse_envelope(text: str) -> dict[str, Any]:
    env = json.loads(text)
    assert isinstance(env, dict)
    return env


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call through ``call_tool`` and parse the envelope."""
    text = anyio.run(call_tool, name, arguments)[0].text
    return _parse_envelope(text)


# ===================================================================
# 1. Tool manifest registration
# ===================================================================


class TestToolManifest:
    def test_backdoor_tools_registered(self) -> None:
        tools = anyio.run(list_tools)
        names = {t.name for t in tools}
        assert "demote_kb_wiki" in names
        assert "force_promote" in names

    def test_soft_delete_entry_carries_actor_param(self) -> None:
        tools = anyio.run(list_tools)
        by_name = {t.name: t for t in tools}
        soft = by_name["soft_delete_entry"]
        assert "actor" in soft.inputSchema["properties"]

    def test_backdoor_tool_schemas_require_actor(self) -> None:
        """Actor is required on the backdoor tools — omitting it must be
        rejected, never silently defaulted to a privileged role."""
        tools = anyio.run(list_tools)
        by_name = {t.name: t for t in tools}
        assert by_name["demote_kb_wiki"].inputSchema["required"] == ["entry_id", "actor"]
        assert by_name["force_promote"].inputSchema["required"] == ["draft_id", "actor"]


# ===================================================================
# 2. DIRECTOR_ONLY envelope — dispatch-level guard
# ===================================================================


class TestDispatchGuard:
    def test_dispatch_force_promote_refused_for_non_director(self) -> None:
        text = anyio.run(call_tool, "force_promote", {"draft_id": "x", "actor": "agent"})[0].text
        env = _parse_envelope(text)
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"
        assert "agent" in env["error"]["message"]
        assert env["error"]["actionable"] is True

    def test_dispatch_demote_refused_for_non_director(self) -> None:
        text = anyio.run(
            call_tool, "demote_kb_wiki", {"entry_id": "x", "actor": "not-director"}
        )[0].text
        env = _parse_envelope(text)
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"

    def test_dispatch_default_actor_refused(self, kb_dir: Path) -> None:
        """No actor argument → defaults to non-privileged 'agent' → the
        dispatch guard refuses with DIRECTOR_ONLY (never silently treated
        as director)."""
        text = anyio.run(call_tool, "force_promote", {"draft_id": "ghost"})[0].text
        env = _parse_envelope(text)
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"

    def test_dispatch_actor_env_whitelist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AUTOINFO_DIRECTOR_ACTORS controls who passes the dispatch guard."""
        monkeypatch.setenv("AUTOINFO_DIRECTOR_ACTORS", "alice")
        text = anyio.run(call_tool, "force_promote", {"draft_id": "x", "actor": "director"})[0].text
        env = _parse_envelope(text)
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"
        # Alice passes the guard and hits the store (entry not found error)
        text = anyio.run(
            call_tool, "force_promote", {"draft_id": "ghost", "actor": "alice"}
        )[0].text
        env = _parse_envelope(text)
        assert env["error"]["code"] != "DIRECTOR_ONLY"


# ===================================================================
# 3. DIRECTOR_ONLY envelope — handler level
# ===================================================================


class TestHandlerEnvelope:
    def test_handle_force_promote_refused_for_non_director(self) -> None:
        result = _handle_force_promote(draft_id="x", actor="agent")
        assert result["success"] is False
        assert result["error"]["code"] == "DIRECTOR_ONLY"
        assert result["error"]["actionable"] is True

    def test_handle_demote_refused_for_non_director(self) -> None:
        result = _handle_demote_kb_wiki(entry_id="x", actor="agent-editor")
        assert result["success"] is False
        assert result["error"]["code"] == "DIRECTOR_ONLY"
        assert "AUTOINFO_DIRECTOR_ACTORS" in result["error"]["message"]

    def test_handle_force_promote_success_path(
        self, kb_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Director actor: force-promote succeeds end to end via the handler."""
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id], title="MCP force promote draft"
        )

        result = _handle_force_promote(draft_id=draft.entry_id, actor="director")

        assert result["status"] == "promoted"
        new_path = Path(result["new_path"])
        assert "03-Wiki" in new_path.parts
        raw_text = new_path.read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        import yaml

        fm = yaml.safe_load(raw_text[3:end])
        assert fm["promotion_source"] == "director"
        assert fm["promoted_by"] == "director"

    def test_handle_demote_success_path(
        self, kb_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(raw_ids=[raw.entry_id], title="MCP demote draft")
        store.force_promote_kb_draft(draft_id=draft.entry_id, caller="director")

        result = _handle_demote_kb_wiki(entry_id=draft.entry_id, actor="director")

        assert result["status"] == "demoted"
        assert "02-Draft" in Path(result["new_path"]).parts
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None and meta["tier"] == "02-Draft"


# ===================================================================
# 4. soft_delete_entry MCP tool — 03-Wiki guard wiring
# ===================================================================


class TestSoftDeleteMcpGuard:
    """Exercises the soft_delete_entry MCP tool through the real dispatch
    (``call_tool``) so both success and failure return canonical envelopes."""

    def _wiki_entry(self, kb_dir: Path) -> str:
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(raw_ids=[raw.entry_id], title="Soft delete wiki")
        store.force_promote_kb_draft(draft_id=draft.entry_id, caller="director")
        return draft.entry_id

    def test_soft_delete_wiki_refused_for_non_director(self, kb_dir: Path) -> None:
        eid = self._wiki_entry(kb_dir)
        env = _call_tool("soft_delete_entry", {"entry_id": eid, "actor": "agent"})
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"
        # Entry remains
        store = KBStore()
        meta = store.index.get_entry(eid)
        assert meta is not None and meta["deleted"] == 0

    def test_soft_delete_wiki_allowed_for_director(self, kb_dir: Path) -> None:
        eid = self._wiki_entry(kb_dir)
        env = _call_tool("soft_delete_entry", {"entry_id": eid, "actor": "director"})
        assert env["success"] is True
        store = KBStore()
        meta = store.index.get_entry(eid)
        assert meta is not None and meta["deleted"] == 1

    def test_soft_delete_purge_wiki_refused_for_non_director(
        self, kb_dir: Path
    ) -> None:
        eid = self._wiki_entry(kb_dir)
        env = _call_tool(
            "soft_delete_entry", {"entry_id": eid, "purge": True, "actor": "agent"}
        )
        assert env["success"] is False
        assert env["error"]["code"] == "DIRECTOR_ONLY"
        store = KBStore()
        assert store.index.get_entry(eid) is not None

    def test_soft_delete_purge_wiki_allowed_for_director(self, kb_dir: Path) -> None:
        eid = self._wiki_entry(kb_dir)
        env = _call_tool(
            "soft_delete_entry", {"entry_id": eid, "purge": True, "actor": "director"}
        )
        assert env["success"] is True
        store = KBStore()
        assert store.index.get_entry(eid) is None

    def test_soft_delete_raw_unaffected_for_any_actor(self, kb_dir: Path) -> None:
        """01-Raw soft-delete keeps working for non-director actors."""
        store = KBStore()
        raw = make_scored_raw(store)
        env = _call_tool(
            "soft_delete_entry", {"entry_id": raw.entry_id, "actor": "agent"}
        )
        assert env["success"] is True
        meta = store.index.get_entry(raw.entry_id)
        assert meta is not None and meta["deleted"] == 1
