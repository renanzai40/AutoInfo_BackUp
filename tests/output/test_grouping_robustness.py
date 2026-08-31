"""Todo 3 — grouping robustness scoped to the degraded path (C3, #120).

The LLM grouping path already has: the anti-collapse retry inside
``_llm_group_batch``, batch chunking (``_GROUPING_BATCH_SIZE``), bounded
concurrency (``_GROUPING_MAX_WORKERS`` + the per-provider semaphore in
``call_with_fallback``), and the #106 chaos guard.  This file locks that
behavior with regression tests and verifies the NARROW addition: a degraded-
path-only 8-12 topic count nudge on ``_merge_theme_groups``.

Verifies:
1. the anti-collapse retry fires exactly once on a <=1-group result (no
   unbounded retry loop);
2. the chaos guard still falls back to deterministic grouping on >20 themes;
3. the degraded deterministic path nudges >12 near-duplicate groups down to
   <=12 topics WITHOUT dropping entries (reassign, never discard);
4. the LLM happy path is byte-identical — ``_merge_theme_groups`` WITHOUT
   ``target_count`` returns the exact pre-change output on an LLM-success
   fixture;
5. repeated faults terminate (no infinite loop under
   ``AUTOINFO_FAULT_INJECT=group:fail``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    _group_by_theme,
    _llm_group_batch,
    _merge_theme_groups,
)

_SOURCE_TYPES = ("rss", "api", "web")


def _entry(i: int) -> dict[str, Any]:
    return {
        "entry_id": f"e{i}",
        "title": f"AI funding round {i}",
        "summary": f"Startup {i} raised $20M.",
        "source_url": f"https://techcrunch.com/{i}",
        "source_type": _SOURCE_TYPES[i % len(_SOURCE_TYPES)],
        "source_platform": "techcrunch",
    }


def _group(theme: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"theme": theme, "description": f"About {theme}.", "entries": entries}


# ---------------------------------------------------------------------------
# 14 near-duplicate theme titles that stay 14 under the pre-change merge logic
# (each pair's Jaccard similarity sits below the existing 0.6 near-dup
# threshold but above the nudge's 0.4 floor — so they only collapse when the
# degraded-path ``target_count`` is applied).
# ---------------------------------------------------------------------------

_NEAR_DUP_THEMES = [
    "AI Funding & M&A Momentum",
    "AI Funding and M&A Deals",
    "GPU Cloud Infrastructure Buildout",
    "GPU Cloud Data Center Expansion",
    "Reproductive Health Outcomes",
    "Reproductive Health Clinical Results",
    "Semiconductor Manufacturing Capacity",
    "Semiconductor Chip Manufacturing Ramp",
    "Model Releases & LLM Advances",
    "LLM Model Release Progress",
    "Startup Growth & Market Expansion",
    "Startup Market Growth Strategy",
    "Regulatory & Policy Shifts",
    "Policy & Regulatory Changes",
]


def _near_dup_groups() -> list[dict[str, Any]]:
    return [
        _group(theme, [_entry(i)])
        for i, theme in enumerate(_NEAR_DUP_THEMES, 1)
    ]


# Captured on the PRE-CHANGE base (HEAD 3a044c0) with the exact fixture above:
# ``_merge_theme_groups(groups)`` without any nudge keeps all 14 groups.
_LLM_SUCCESS_GOLDEN = (
    "[{'theme': 'AI Funding & M&A Momentum', 'description': 'About AI Funding "
    "& M&A Momentum.', 'entries': [{'entry_id': 'e1', 'title': 'AI funding "
    "round 1', 'summary': 'Startup 1 raised $20M.', 'source_url': "
    "'https://techcrunch.com/1', 'source_type': 'api', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'AI Funding and M&A Deals', 'description': "
    "'About AI Funding and M&A Deals.', 'entries': [{'entry_id': 'e2', "
    "'title': 'AI funding round 2', 'summary': 'Startup 2 raised $20M.', "
    "'source_url': 'https://techcrunch.com/2', 'source_type': 'web', "
    "'source_platform': 'techcrunch'}]}, {'theme': 'GPU Cloud Infrastructure "
    "Buildout', 'description': 'About GPU Cloud Infrastructure Buildout.', "
    "'entries': [{'entry_id': 'e3', 'title': 'AI funding round 3', "
    "'summary': 'Startup 3 raised $20M.', 'source_url': "
    "'https://techcrunch.com/3', 'source_type': 'rss', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'GPU Cloud Data Center Expansion', "
    "'description': 'About GPU Cloud Data Center Expansion.', 'entries': "
    "[{'entry_id': 'e4', 'title': 'AI funding round 4', 'summary': 'Startup 4 "
    "raised $20M.', 'source_url': 'https://techcrunch.com/4', 'source_type': "
    "'api', 'source_platform': 'techcrunch'}]}, {'theme': 'Reproductive "
    "Health Outcomes', 'description': 'About Reproductive Health Outcomes.', "
    "'entries': [{'entry_id': 'e5', 'title': 'AI funding round 5', "
    "'summary': 'Startup 5 raised $20M.', 'source_url': "
    "'https://techcrunch.com/5', 'source_type': 'web', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'Reproductive Health Clinical Results', "
    "'description': 'About Reproductive Health Clinical Results.', 'entries': "
    "[{'entry_id': 'e6', 'title': 'AI funding round 6', 'summary': 'Startup 6 "
    "raised $20M.', 'source_url': 'https://techcrunch.com/6', 'source_type': "
    "'rss', 'source_platform': 'techcrunch'}]}, {'theme': 'Semiconductor "
    "Manufacturing Capacity', 'description': 'About Semiconductor "
    "Manufacturing Capacity.', 'entries': [{'entry_id': 'e7', 'title': 'AI "
    "funding round 7', 'summary': 'Startup 7 raised $20M.', 'source_url': "
    "'https://techcrunch.com/7', 'source_type': 'api', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'Semiconductor Chip Manufacturing Ramp', "
    "'description': 'About Semiconductor Chip Manufacturing Ramp.', "
    "'entries': [{'entry_id': 'e8', 'title': 'AI funding round 8', "
    "'summary': 'Startup 8 raised $20M.', 'source_url': "
    "'https://techcrunch.com/8', 'source_type': 'web', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'Model Releases & LLM Advances', "
    "'description': 'About Model Releases & LLM Advances.', 'entries': "
    "[{'entry_id': 'e9', 'title': 'AI funding round 9', 'summary': 'Startup 9 "
    "raised $20M.', 'source_url': 'https://techcrunch.com/9', 'source_type': "
    "'rss', 'source_platform': 'techcrunch'}]}, {'theme': 'LLM Model Release "
    "Progress', 'description': 'About LLM Model Release Progress.', "
    "'entries': [{'entry_id': 'e10', 'title': 'AI funding round 10', "
    "'summary': 'Startup 10 raised $20M.', 'source_url': "
    "'https://techcrunch.com/10', 'source_type': 'api', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'Startup Growth & Market Expansion', "
    "'description': 'About Startup Growth & Market Expansion.', 'entries': "
    "[{'entry_id': 'e11', 'title': 'AI funding round 11', 'summary': "
    "'Startup 11 raised $20M.', 'source_url': 'https://techcrunch.com/11', "
    "'source_type': 'web', 'source_platform': 'techcrunch'}]}, {'theme': "
    "'Startup Market Growth Strategy', 'description': 'About Startup Market "
    "Growth Strategy.', 'entries': [{'entry_id': 'e12', 'title': 'AI funding "
    "round 12', 'summary': 'Startup 12 raised $20M.', 'source_url': "
    "'https://techcrunch.com/12', 'source_type': 'rss', 'source_platform': "
    "'techcrunch'}]}, {'theme': 'Regulatory & Policy Shifts', 'description': "
    "'About Regulatory & Policy Shifts.', 'entries': [{'entry_id': 'e13', "
    "'title': 'AI funding round 13', 'summary': 'Startup 13 raised $20M.', "
    "'source_url': 'https://techcrunch.com/13', 'source_type': 'api', "
    "'source_platform': 'techcrunch'}]}, {'theme': 'Policy & Regulatory "
    "Changes', 'description': 'About Policy & Regulatory Changes.', "
    "'entries': [{'entry_id': 'e14', 'title': 'AI funding round 14', "
    "'summary': 'Startup 14 raised $20M.', 'source_url': "
    "'https://techcrunch.com/14', 'source_type': 'web', 'source_platform': "
    "'techcrunch'}]}]"
)


def test_anticollapse_retry_fires_exactly_once() -> None:
    """(1) A <=1-group LLM result triggers exactly ONE strict retry — never a
    loop.  ``_llm_json_extract`` is called twice total (initial + retry)."""
    entries = [_entry(i) for i in range(1, 9)]
    collapsed = [{"theme": "General", "entry_ids": [f"e{i}" for i in range(1, 9)]}]
    recovered = [
        {"theme": "Alpha", "entry_ids": ["e1", "e2", "e3", "e4"]},
        {"theme": "Beta", "entry_ids": ["e5", "e6", "e7", "e8"]},
    ]

    with patch(
        "autoinfo.output._llm_json_extract",
        side_effect=[collapsed, recovered],
    ) as mock_extract:
        groups = _llm_group_batch(MagicMock(), entries, domain="ai-commercial")

    assert mock_extract.call_count == 2, (
        f"expected exactly 1 retry (2 calls), got {mock_extract.call_count}"
    )
    assert groups is not None and len(groups) == 2, groups


def test_chaos_guard_still_falls_back_on_twenty_plus_themes() -> None:
    """(2) #106 chaos guard: a >20-theme burst still falls back to
    deterministic grouping — no garbage themes survive, no entry is lost."""
    chaos = [
        {"theme": f"Chaos-Theme-{i}", "description": "", "entries": [_entry(i)]}
        for i in range(1, 26)
    ]
    with (
        patch("autoinfo.output._run_grouping_batches", return_value=chaos),
        patch("autoinfo.output.fault_inject.maybe_fault"),
    ):
        result = _group_by_theme(MagicMock(), [_entry(i) for i in range(1, 26)])

    assert not any(g["theme"].startswith("Chaos-Theme-") for g in result), (
        "chaotic burst survived; the chaos guard must fall back"
    )
    assert sum(len(g["entries"]) for g in result) == 25, "entries lost in fallback"


def test_degraded_deterministic_nudges_to_twelve_without_dropping() -> None:
    """(3) ``_merge_theme_groups(groups, target_count=(8, 12))`` on a >12-group
    deterministic result merges near-duplicates down to <=12 topics and every
    entry survives (reassigned, never dropped)."""
    groups = _near_dup_groups()
    assert len(groups) == 14, "fixture must start above the 12 cap"

    nudged = _merge_theme_groups(groups, target_count=(8, 12))

    assert len(nudged) <= 12, (
        f"nudge left {len(nudged)} groups, expected <= 12"
    )
    total = sum(len(g["entries"]) for g in nudged)
    assert total == 14, f"nudge dropped entries: {total} != 14"
    assert {e["entry_id"] for g in nudged for e in g["entries"]} == {
        f"e{i}" for i in range(1, 15)
    }, "all entry ids must survive the nudge"


def test_happy_path_byte_identical_without_target_count() -> None:
    """(4) ``_merge_theme_groups`` WITHOUT ``target_count`` returns the exact
    pre-change output on an LLM-success fixture (near-dup merge only, no count
    nudge).  The golden was captured on HEAD 3a044c0."""
    groups = _near_dup_groups()

    result = _merge_theme_groups(groups)

    assert repr(result) == _LLM_SUCCESS_GOLDEN, (
        "happy path diverged from the pre-change output — the nudge must be "
        "flag-gated off when target_count is None"
    )


def test_no_infinite_loop_on_repeated_faults() -> None:
    """(5) Under ``AUTOINFO_FAULT_INJECT=group:fail`` ``_group_by_theme``
    terminates: the fault path falls back to deterministic grouping (sanitized
    by the nudge) and every entry is returned — no unbounded retry."""
    entries = [_entry(i) for i in range(1, 26)]
    with patch("autoinfo.output.fault_inject.maybe_fault", side_effect=ConnectionError("fault")):
        result = _group_by_theme(MagicMock(), entries, domain="ai-commercial")

    assert result, "fault path returned no groups"
    assert sum(len(g["entries"]) for g in result) == 25, "fault path lost entries"
    themes = [g["theme"] for g in result]
    assert len(set(themes)) == len(themes), "duplicated themes after fallback"
