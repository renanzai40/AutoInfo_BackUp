"""Tool-description audit tests (D-工-1 evidence, best-practice-review).

Locks the behavior of ``scripts/tool_desc_audit.py`` so the audit the
best-practice review dimension relies on stays deterministic:

1. All 145 declared tools are parsed (matches ``get_tool_count``).
2. Verb-first naming — ``email_config`` is the only non-verb-style name;
   namespace+verb names (``enduser_create``, ``soft_delete_entry``,
   ``knowledge_graph_export``) are NOT violations.
3. The four D-工-1 metrics (param count / enum / default / description
   length) are computed and reported in ``summary``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
AUDIT_SCRIPT = ROOT / "scripts" / "tool_desc_audit.py"


@pytest.fixture(scope="module")
def tool_audit():
    spec = importlib.util.spec_from_file_location("tool_desc_audit", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(tool_audit):
    return tool_audit.audit_tools(SERVER_SRC.read_text(encoding="utf-8"))


def test_all_145_tools_parsed(result):
    assert result["declared"] == 145


def test_email_config_is_only_verb_violation(result):
    assert result["violations"]["not_verb_first"] == ["email_config"]


def test_namespace_verb_names_are_not_violations(result):
    tools = {t["name"]: t for t in result["tools"]}
    for name in (
        "enduser_create",
        "soft_delete_entry",
        "knowledge_graph_export",
        "health_check",
        "topic_group_add",
    ):
        assert tools[name]["namespace_verb"] is True, name


def test_verb_first_ratio_high(result):
    # 99.3% verb-style (verb-first + namespace+verb); keep >= 98% as the
    # regression floor so the D-工-1 evidence stays strong.
    assert result["summary"]["verb_style_ratio"] >= 0.98


def test_summary_metrics_present(result):
    s = result["summary"]
    for key in (
        "declared",
        "verb_style_ratio",
        "param_count_avg",
        "over_8_params",
        "short_desc_lt10",
        "no_enum_tools",
        "enum_params_total",
        "default_params_total",
    ):
        assert key in s, key


def test_over_8_params_are_the_known_heavy_tools(result):
    assert set(result["violations"]["over_8_params"]) == {
        "add_source",
        "generate_digest",
        "generate_report",
        "search_knowledge_base",
    }


def test_per_tool_row_shape(result):
    tools = {t["name"]: t for t in result["tools"]}
    row = tools["add_source"]
    assert row["verb_first"] is True
    assert row["param_count"] == 12
    assert row["desc_words"] > 10
    assert row["enum_params"] >= 0
