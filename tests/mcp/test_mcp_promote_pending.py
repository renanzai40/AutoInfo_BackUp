"""Server-level tests for the MCP ``promote_pending`` sweep tool (T6).

Covers the MCP surface:
  1. Tool manifest registration — ``promote_pending`` is registered with a
     required ``domain`` param and an ``actor`` param.
  2. Handler behavior — ``_handle_promote_pending`` returns a batch summary
     with promoted/rejected/failed per entry and never raises.
  3. Dispatch — the tool routes through ``call_tool``.

Handlers construct ``KBStore()`` against the process CWD, so tests that
reach the store ``monkeypatch.chdir`` into a temp dir.  G4 is an LLM
call and is monkeypatched (no real LLM is ever invoked).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml

from autoinfo.config import QualityGateConfig
from autoinfo.kb import KBStore
from autoinfo.mcp.server import (
    _handle_promote_pending,
    call_tool,
    list_tools,
)
from autoinfo.models import Item, KBEntry
from autoinfo.quality import QualityResult

# ===================================================================
# Fixtures / builders
# ===================================================================


@pytest.fixture
def kb_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir into a temp dir so ``KBStore()`` roots there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def patch_g4(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Monkeypatch the admission gate's G4 checker (pass by default)."""
    current = {"passed": True}

    class _FakeG4:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def check(
            self,
            item: object,
            extraction: object,
            gate_config: QualityGateConfig | None = None,  # noqa: ARG002
        ) -> QualityResult:
            if current["passed"]:
                return QualityResult(
                    gate_name="G4-SummaryFactual",
                    passed=True,
                    score=1.0,
                    details={"contradiction": False},
                )
            return QualityResult(
                gate_name="G4-SummaryFactual",
                passed=False,
                flagged=True,
                score=0.0,
                details={"contradiction": True, "action": "block"},
            )

    monkeypatch.setattr("autoinfo.promotion.G4FactualConsistency", _FakeG4)

    def set_passed(passed: bool) -> None:
        current["passed"] = passed

    return set_passed


def make_scored_raw(store: KBStore) -> KBEntry:
    """Store a 01-Raw entry with full provenance + G1/G3 scores."""
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
    g3 = QualityResult(gate_name="G3-RelevanceScoring", passed=True, score=85.0)
    g1 = QualityResult(
        gate_name="G1-SourceAuthority",
        passed=True,
        score=0.0,
        details={"source_score": 72.0},
    )
    return store.store_entry(
        item,
        quality_results={"G3-RelevanceScoring": g3, "G1-SourceAuthority": g1},
    )


def _tier(store: KBStore, entry_id: str) -> str:
    """Read the index tier for *entry_id* (asserts the row exists)."""
    meta = store.index.get_entry(entry_id)
    assert meta is not None
    return str(meta["tier"])


def _assert_tier(store: KBStore, entry_id: str, expected: str) -> None:
    """Assert *entry_id* currently lives in the *expected* tier."""
    assert _tier(store, entry_id) == expected


def _file_path(store: KBStore, entry_id: str) -> str:
    """Read the index file_path for *entry_id* (asserts the row exists)."""
    meta = store.index.get_entry(entry_id)
    assert meta is not None
    return str(meta["file_path"])


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call through ``call_tool`` and parse the envelope."""
    text = anyio.run(call_tool, name, arguments)[0].text
    env = json.loads(text)
    assert isinstance(env, dict)
    return env


# ===================================================================
# 1. Tool manifest registration
# ===================================================================


class TestToolManifest:
    def test_promote_pending_registered(self) -> None:
        tools = anyio.run(list_tools)
        names = {t.name for t in tools}
        assert "promote_pending" in names

    def test_promote_pending_schema(self) -> None:
        tools = anyio.run(list_tools)
        by_name = {t.name: t for t in tools}
        schema = by_name["promote_pending"].inputSchema
        assert schema["required"] == ["domain"]
        assert "domain" in schema["properties"]
        assert "actor" in schema["properties"]


# ===================================================================
# 2. Handler behavior
# ===================================================================


class TestHandlePromotePending:
    def test_handler_promotes_eligible_and_summarizes(
        self,
        kb_dir: Path,
        patch_g4: Callable[[bool], None],
    ) -> None:
        patch_g4(True)
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="MCP sweep draft",
            summary="Time-lapse embryo imaging improves IVF selection.",
        )

        result = _handle_promote_pending(domain="medical-research")

        assert result["domain"] == "medical-research"
        assert result["total"] == 1
        assert result["promoted"][0]["entry_id"] == draft.entry_id
        assert result["rejected"] == []
        assert result["failed"] == []
        _assert_tier(store, draft.entry_id, "03-Wiki")

    def test_handler_reports_rejections_not_raises(
        self,
        kb_dir: Path,
        patch_g4: Callable[[bool], None],
    ) -> None:
        patch_g4(False)
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="MCP rejected draft",
        )

        result = _handle_promote_pending(domain="medical-research")

        assert result["promoted"] == []
        assert len(result["rejected"]) == 1
        assert result["rejected"][0]["entry_id"] == draft.entry_id
        assert "g4-factual-failed" in result["rejected"][0]["reasons"]
        # Draft untouched
        _assert_tier(store, draft.entry_id, "02-Draft")

    def test_handler_unknown_domain_empty_summary(
        self, kb_dir: Path
    ) -> None:
        result = _handle_promote_pending(domain="no-such-domain")
        assert result["domain"] == "no-such-domain"
        assert result["total"] == 0
        assert result["promoted"] == []


# ===================================================================
# 3. Dispatch
# ===================================================================


class TestDispatch:
    def test_dispatch_promote_pending(
        self,
        kb_dir: Path,
        patch_g4: Callable[[bool], None],
    ) -> None:
        patch_g4(True)
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="MCP dispatched draft",
        )

        env = _call_tool(
            "promote_pending", {"domain": "medical-research", "actor": "agent"}
        )

        assert env["success"] is True
        assert env["data"]["promoted"][0]["entry_id"] == draft.entry_id
        _assert_tier(store, draft.entry_id, "03-Wiki")

    def test_dispatch_promote_pending_records_actor(
        self,
        kb_dir: Path,
        patch_g4: Callable[[bool], None],
    ) -> None:
        patch_g4(True)
        store = KBStore()
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="MCP actor draft",
        )

        env = _call_tool(
            "promote_pending", {"domain": "medical-research", "actor": "scheduler"}
        )

        assert env["success"] is True
        wiki_path = _file_path(store, draft.entry_id)
        raw_text = Path(wiki_path).read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        fm = yaml.safe_load(raw_text[3:end])
        assert fm["promoted_by"] == "scheduler"
        assert fm["promotion_source"] == "agent"
