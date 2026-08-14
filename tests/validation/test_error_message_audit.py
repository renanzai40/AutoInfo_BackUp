"""Error-message audit tests (D-工-4 evidence, best-practice-review).

Locks the behavior of ``scripts/error_message_audit.py`` so the D-工-4
evidence the best-practice review depends on stays deterministic:

1. All error envelope call sites in ``server.py`` are parsed (109 sites:
   error_response / error_dict / _error_dict).
2. **Actionability** — every explicit-message site (``error_response`` /
   ``error_dict``) carries a fix hint; the strong claim that
   ``no_fix_hint_sites == 0`` is the regression floor.
3. **Raw-exception leakage** — ``_error_dict(exc)`` builds
   ``message_str = str(exc)``; the audit flags every such site as a
   raw-exception site. The floor (>= 50 of 109) documents that the
   majority of error responses expose the raw exception string verbatim.
4. **429 Retry-After** — RATE_LIMITED call sites should carry a retry /
   backoff hint; the audit reports them (0 today — rate limiting is not
   surfaced through the MCP error envelope).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
AUDIT_SCRIPT = ROOT / "scripts" / "error_message_audit.py"


@pytest.fixture(scope="module")
def error_audit():
    spec = importlib.util.spec_from_file_location(
        "error_message_audit", AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(error_audit):
    return error_audit.audit_errors(SERVER_SRC.read_text(encoding="utf-8"))


def test_all_error_sites_parsed(result):
    assert result["total_sites"] == 109


def test_call_site_kind_breakdown(result):
    from collections import Counter

    kinds = Counter(s["call"] for s in result["sites"])
    assert kinds["_error_dict"] == 65
    assert kinds["error_response"] == 43
    assert kinds["error_dict"] == 1


def test_every_explicit_message_has_fix_hint(result):
    # The strong D-工-4 claim: no explicit-message site lacks a fix hint.
    assert result["summary"]["no_fix_hint_sites"] == 0


def test_raw_exception_sites_are_majority(result):
    # _error_dict(exc) → message == str(exc): raw exception string leaked
    # into the agent-facing envelope. Floor >= 50 documents the pattern.
    assert result["summary"]["raw_exception_sites"] >= 50


def test_raw_exception_lines_match_error_dict_sites(result):
    raw = result["violations"]["raw_exception"]
    # every raw-exception line is a _error_dict call site
    by_line = {s["line"]: s["call"] for s in result["sites"]}
    for line in raw:
        assert by_line[line] == "_error_dict", line


def test_rate_limited_reporting_shape(result):
    v = result["violations"]["rate_limited_no_retry"]
    assert isinstance(v, list)
    assert result["summary"]["rate_limited_sites"] == 0


def test_sites_sorted_by_line(result):
    lines = [s["line"] for s in result["sites"]]
    assert lines == sorted(lines)
