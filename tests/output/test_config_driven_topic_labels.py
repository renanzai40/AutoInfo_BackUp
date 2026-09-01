"""Todo 5 — config-driven topic labels for keyword groups (#120, C5).

Keyword-group section headers must never render as bare ``name.title()``
keyword words ("Apple", "Policy") — end users cannot tell a real topic from a
pipeline category.  ``_keyword_group_entries`` now resolves each keyword group
to a user-facing label in priority order:

(a) the domain's CURRENT ``TopicConfig`` (``group`` if set else ``name``),
(b) the curated synonym map (``_THEME_SYNONYMS``),
(c) otherwise the group's entries fold into "Additional Topics".

CRITICAL GUARDRAIL: ``_GENERIC_THEME_LABELS`` must NOT be extended with
domain words like "apple"/"policy" — that blocklist also runs on the LLM happy
path in ``_merge_theme_groups``, so adding "apple" would strip a legitimate
real "Apple" theme from LLM-success output.  Bare-word suppression lives ONLY
in the keyword/degraded path.

RED→GREEN: these tests fail on pre-todo-5 code (bare ``name.title()`` headers
render as ``## Apple``; no ``_keyword_topic_labels`` helper).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    _THEME_SYNONYMS,
    _keyword_group_entries,
    _keyword_topic_labels,
    _merge_theme_groups,
)

# The pinned todo-4 honesty marker — asserted byte-for-byte.
MARKER = "> *Grouped by source \u2014 not semantic topics*"

_SOURCE_TYPES = ("rss", "api", "web")


def _kw_entry(eid: str, title: str) -> dict[str, Any]:
    return {
        "entry_id": eid,
        "title": title,
        "summary": "developments across the tracked sources.",
        "source_url": f"https://x.com/{eid}",
        "source_type": "rss",
        "source_platform": "techcrunch",
    }


def _entry(i: int) -> dict[str, Any]:
    return {
        "entry_id": f"e{i}",
        "title": f"AI funding round {i}",
        "summary": f"Startup {i} raised $20M.",
        "source_url": f"https://techcrunch.com/{i}",
        "source_type": _SOURCE_TYPES[i % len(_SOURCE_TYPES)],
        "source_platform": "techcrunch",
        "domain": "medical-research",
        "relevance_score": 90.0 - (i % 10),
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    }


def _store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = list(entries)
    store.list_kb_tier.return_value = []
    store.promote_kb_draft.return_value = {}
    store.flag_for_knowledge_base.return_value = {}
    return store


def _stub_summary() -> dict[str, Any]:
    return {
        "executive_summary": "This report covers the tracked developments.",
        "key_findings": [],
        "recommendations": [],
    }


def _column_template() -> Any:
    from autoinfo.output import PRODUCT_TEMPLATES

    for row in PRODUCT_TEMPLATES:
        if row["name"] == "column":
            return row["template"]
    raise AssertionError("column ProductTemplate row missing from PRODUCT_TEMPLATES")


def _column_entries(n: int) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": f"entry-{i:03d}",
            "title": f"Research finding {i} on IVF time-lapse imaging",
            "language": "en",
            "summary": (
                f"Study {i} reports improved live birth rates with time-lapse "
                "imaging in a prospective cohort."
            ),
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{10000000 + i}/",
            "source_type": "api",
            "source_platform": "pubmed",
            "relevance_score": 90.0 - i,
            "tags": '["IVF", "embryo"]',
            "tier": "01-Raw",
            "collected_at": "2026-07-15T10:00:00Z",
        }
        for i in range(1, n + 1)
    ]


def _column_synthesis() -> dict[str, Any]:
    return {
        "executive_summary": "This week's column covers ten studies on IVF.",
        "key_findings": [
            {"topic": "Time-lapse imaging", "detail": "Live birth rates improved."},
        ],
        "trends": ["Time-lapse imaging adoption"],
        "recommendations": ["Consider time-lapse imaging as standard of care."],
    }


# ---------------------------------------------------------------------------
# label resolution in `_keyword_group_entries`
# ---------------------------------------------------------------------------


def test_bare_keyword_blocked() -> None:
    """A bare keyword NOT in any map must fold into "Additional Topics" —
    never render as a ``## Apple`` header."""
    entries = [
        _kw_entry("e1", "Apple launches new chip"),
        _kw_entry("e2", "Apple reports record services revenue"),
    ]
    with (
        patch("autoinfo.output._keyword_topic_labels", return_value={}),
        patch("autoinfo.output._load_keyword_topics", return_value=["apple"]),
    ):
        groups = _keyword_group_entries(entries, domain="d")

    assert groups is None, (
        "all-unmapped keyword match must fall back (None), not render a bare "
        f"keyword header: {groups}"
    )
    # Mixed fixture: one resolvable keyword + one bare keyword → the bare one
    # folds into "Additional Topics".
    with (
        patch(
            "autoinfo.output._keyword_topic_labels",
            return_value={"funding": "Funding & M&A"},
        ),
        patch(
            "autoinfo.output._load_keyword_topics",
            return_value=["funding", "apple"],
        ),
    ):
        groups = _keyword_group_entries(
            [_kw_entry("e1", "Apple launches new chip"),
             _kw_entry("e2", "Series A funding round")],
            domain="d",
        )

    assert groups is not None
    themes = [g["theme"] for g in groups]
    assert not any(t == "Apple" for t in themes), (
        f"bare keyword rendered as a header: {themes}"
    )
    assert "Additional Topics" in themes, themes
    apple_group = next(g for g in groups if g["theme"] == "Additional Topics")
    assert {e["entry_id"] for e in apple_group["entries"]} == {"e1"}, (
        "bare-keyword entries must be preserved in Additional Topics"
    )
    funding_group = next(g for g in groups if g["theme"] == "Funding & M&A")
    assert {e["entry_id"] for e in funding_group["entries"]} == {"e2"}


def test_group_name_resolved() -> None:
    """A keyword matching a TopicConfig group/name renders that label, not the
    bare keyword."""
    entries = [
        _kw_entry("e1", "Series A funding round"),
        _kw_entry("e2", "Apple launches new chip"),
    ]
    with (
        patch(
            "autoinfo.output._keyword_topic_labels",
            return_value={"funding": "Funding & M&A"},
        ),
        patch("autoinfo.output._load_keyword_topics", return_value=["funding"]),
    ):
        groups = _keyword_group_entries(entries, domain="d")

    assert groups is not None
    themes = [g["theme"] for g in groups]
    assert "Funding & M&A" in themes, themes
    funding_group = next(g for g in groups if g["theme"] == "Funding & M&A")
    assert {e["entry_id"] for e in funding_group["entries"]} == {"e1"}
    assert {e["entry_id"] for g in groups for e in g["entries"]} == {
        "e1", "e2",
    }, "every entry must survive the label resolution"


def test_synonym_resolved() -> None:
    """A keyword matching ``_THEME_SYNONYMS`` renders the canonical label."""
    assert _THEME_SYNONYMS["llm"] == "large language models"
    entries = [
        _kw_entry("e1", "LLM model training breakthrough"),
        _kw_entry("e2", "Apple launches new chip"),
    ]
    with (
        patch("autoinfo.output._keyword_topic_labels", return_value={}),
        patch("autoinfo.output._load_keyword_topics", return_value=["llm"]),
    ):
        groups = _keyword_group_entries(entries, domain="d")

    assert groups is not None
    themes = [g["theme"] for g in groups]
    assert "Large Language Models" in themes, themes
    llm_group = next(g for g in groups if g["theme"] == "Large Language Models")
    assert {e["entry_id"] for e in llm_group["entries"]} == {"e1"}
    assert {e["entry_id"] for g in groups for e in g["entries"]} == {
        "e1", "e2",
    }, "every entry must survive the label resolution"


def test_llm_happy_path_untouched() -> None:
    """A real semantic theme "Apple" from the LLM is NOT stripped — the
    blocklist / near-dup / merge passes must leave it alone (the guardrail:
    ``_GENERIC_THEME_LABELS`` does not contain domain words)."""
    entry = _kw_entry("e1", "Apple WWDC keynote")
    result = _merge_theme_groups([
        {"theme": "Apple", "description": "About Apple.", "entries": [entry]},
    ])

    assert [g["theme"] for g in result] == ["Apple"], [
        g["theme"] for g in result
    ]
    assert {e["entry_id"] for g in result for e in g["entries"]} == {"e1"}


def test_fail_open_no_config() -> None:
    """`_keyword_topic_labels` returns {} for an unreadable/missing config and
    `_keyword_group_entries` still works — bare keywords fold, never crash."""
    with patch(
        "autoinfo.output.get_config_path", return_value=None
    ):
        labels = _keyword_topic_labels("any-domain")
    assert labels == {}

    with (
        patch("autoinfo.output._keyword_topic_labels", return_value={}),
        patch("autoinfo.output._load_keyword_topics", return_value=["apple"]),
    ):
        groups = _keyword_group_entries(
            [_kw_entry("e1", "Apple launches new chip")], domain="d"
        )
    assert groups is None


# ---------------------------------------------------------------------------
# entry-level column path: todo-4 marker present + no bare keyword header
# ---------------------------------------------------------------------------


def test_column_entry_level_annotated_no_bare_keyword() -> None:
    """The column-digest entry-level fallback renders the todo-4 honesty
    marker and never a bare keyword ``## `` header."""
    from autoinfo.output import generate_digest

    entries = _column_entries(10)
    with (
        patch("autoinfo.output.KBStore", return_value=_store(entries)),
        patch(
            "autoinfo.output._call_llm_for_digest",
            return_value=_column_synthesis(),
        ),
    ):
        out = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            product_template=_column_template(),
            include_stale=True,
        )
    assert isinstance(out, str)

    assert MARKER in out, "entry-level column fallback must carry the marker"
    deep_dive_idx = out.index("## Deep Dive")
    marker_idx = out.index(MARKER)
    assert deep_dive_idx < marker_idx, "marker must appear inside the Deep Dive"
    assert "## Apple" not in out, "bare keyword header leaked into column"
