"""Tool similarity audit tests (D-工-7 evidence, best-practice-review).

Locks the behavior of ``scripts/tool_similarity_audit.py`` so the D-工-7
boundary-health evidence stays deterministic:

1. All 145 tools are parsed.
2. **Zero name-boundary collisions** — no two tools share the same
   first-segment + noun-stem (no ``same_stem_verb_pairs``): every tool
   name is uniquely distinguishable by name alone.
3. **Distinct stems for distinct products** — the ``generate_*`` output
   family (digest/report/tutorial/presentation) each carries a distinct
   noun stem, so they are *not* a same-stem family; their boundary risk is
   purely descriptive and surfaces in the Jaccard-overlap findings.
4. Family and per-tool row shapes are stable.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
AUDIT_SCRIPT = ROOT / "scripts" / "tool_similarity_audit.py"


@pytest.fixture(scope="module")
def similarity_audit() -> Any:
    spec = importlib.util.spec_from_file_location(
        "tool_similarity_audit", AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(similarity_audit: Any) -> dict[str, Any]:
    return similarity_audit.audit_similarity(
        SERVER_SRC.read_text(encoding="utf-8")
    )


def test_all_145_tools_parsed(result: dict[str, Any]) -> None:
    assert result["total"] == 145


def test_zero_same_stem_verb_name_collisions(result: dict[str, Any]) -> None:
    # Name-level boundary health: every tool name is unique by
    # first-segment + noun-stem. No ambiguity from names alone.
    assert result["summary"]["same_stem_verb_pairs"] == 0


def test_families_detected(result: dict[str, Any]) -> None:
    # >= 20 noun-stem families with >= 2 members exist (shared nouns across
    # the surface are the norm — the boundary check is on *verb* collisions).
    assert result["summary"]["family_count"] >= 20


def test_generate_family_has_distinct_stems(result: dict[str, Any]) -> None:
    # generate_digest / generate_report / generate_tutorial /
    # generate_presentation / generate_cross_domain_report each carries a
    # distinct noun stem, so no same-stem family exists for them — names
    # alone disambiguate.
    stems = {
        t["stem"] for t in result["tools"]
        if t["first"] == "generate"
    }
    assert len(stems) == 5
    assert stems == {
        "digest", "report", "tutorial", "presentation", "cross_domain_report",
    }


def test_high_overlap_pairs_include_generate_family(result: dict[str, Any]) -> None:
    pairs = result["violations"]["high_desc_overlap"]
    pair_names = {(p["a"], p["b"]) for p in pairs}
    assert ("generate_digest", "generate_report") in pair_names
    assert ("generate_presentation", "generate_tutorial") in pair_names


def test_overlap_sorted_descending(result: dict[str, Any]) -> None:
    pairs = result["violations"]["high_desc_overlap"]
    jaccards = [p["jaccard"] for p in pairs]
    assert jaccards == sorted(jaccards, reverse=True)


def test_per_tool_row_shape(result: dict[str, Any]) -> None:
    tools = {t["name"]: t for t in result["tools"]}
    row = tools["generate_digest"]
    assert row["first"] == "generate"
    assert row["stem"] == "digest"
    assert isinstance(row["segments"], list)
