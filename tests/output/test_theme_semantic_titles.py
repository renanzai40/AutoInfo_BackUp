"""Issue #311 — report section titles are semantic themes, not raw keyword
dumps or duplicated titles.

Verifies:
(a) the thematic-grouping prompts instruct the LLM to emit SHORT SEMANTIC
    titles (noun phrases, never raw keyword lists or joined keyword strings);
(b) near-duplicate theme titles (case / "&" / "and" / word-order variants)
    are merged by ``_merge_theme_groups`` so a report never shows two
    sections that name the same theme;
(c) ``_group_by_theme`` returns only unique section titles.

Issue #9 — generic theme labels (``### New`` / ``### Year`` / ``### User``)
must never surface in a report section heading, and keyword grouping on
ai-commercial English titles must produce meaningful theme groups (via the
demo-domain seed merge, not a fallback-when-empty):
(d) ``_merge_theme_groups`` drops blocklisted generic labels and merges
    synonyms (Year / The Year) while preserving every entry;
(e) ``_keyword_group_entries`` on ai-commercial entries with English titles
    ("Series A funding round" / "GPT-5 model release") returns keyword groups
    instead of ``None`` (pre-fix it returned ``None``);
(f) fragment keywords (``lui`` / ``ota`` / ``gui``) do not create generic
    theme groups;
(g) the CJK-keyword path does not regress — Chinese-only keyword tables still
    normalize and match without breaking.
"""

from __future__ import annotations

from typing import Any

from autoinfo.llm import LLMExtractor
from autoinfo.output import (
    _group_batch_by_theme,
    _group_by_theme,
    _keyword_group_entries,
    _merge_theme_groups,
)

# ---------------------------------------------------------------------------
# Fixtures + recording mocked LLM
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, custom_fields: dict[str, Any]) -> None:
        self.custom_fields = custom_fields


class _RecordingExtractor(LLMExtractor):
    """Deterministic mocked LLMExtractor that records every prompt it sees."""

    def __init__(self, groups: list[dict[str, Any]]) -> None:
        self.groups = groups
        self.prompts: list[str] = []

    def extract(self, item: Any, schema: Any = None) -> Any:
        self.prompts.append(item.content)
        return _FakeResult({"groups": self.groups})


def _make_entries(n: int) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": f"e{i}",
            "title": f"Title {i}",
            "summary": f"Summary {i} for entry {i}.",
            "source_url": f"https://example.com/{i}",
            "source_type": "rss",
            "source_platform": "test",
            "domain": "test-domain",
        }
        for i in range(1, n + 1)
    ]


def _group(theme: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"theme": theme, "description": f"About {theme}.", "entries": entries}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_grouping_prompt_instructs_semantic_titles() -> None:
    """The grouping prompt must demand short semantic theme titles (noun
    phrases of 2-6 words) instead of raw keyword lists."""
    entries = _make_entries(4)
    extractor = _RecordingExtractor([
        {"theme": "Theme A", "entry_ids": ["e1", "e2"]},
        {"theme": "Theme B", "entry_ids": ["e3", "e4"]},
    ])

    _group_batch_by_theme(extractor, entries, domain="test-domain")

    prompt = extractor.prompts[0].lower()
    assert "semantic" in prompt, (
        "grouping prompt does not instruct semantic theme titles"
    )
    assert "2-6 words" in prompt, (
        "grouping prompt does not constrain title length to 2-6 words"
    )


def test_near_duplicate_theme_titles_merged() -> None:
    """Case / separator / conjunction variants of the same theme are one
    theme — never two report sections."""
    entries = _make_entries(4)
    result = _merge_theme_groups([
        _group("AI Funding & M&A", entries[:2]),
        _group("AI Funding and M&A", entries[2:]),
    ])

    assert len(result) == 1, (
        f"near-duplicate themes were not merged, got {len(result)} groups"
    )


def test_group_by_theme_returns_unique_section_titles() -> None:
    """Case-variant, '&'/'and' and word-order duplicates must collapse into
    one theme so the final report has no duplicated section headings."""
    entries = _make_entries(3)
    extractor = _RecordingExtractor([
        {"theme": "AI Funding & M&A", "entry_ids": ["e1"]},
        {"theme": "AI Funding and M&A", "entry_ids": ["e2"]},
        {"theme": "AI M&A Funding", "entry_ids": ["e3"]},
    ])

    result = _group_by_theme(extractor, entries, domain="test-domain")

    themes = [g["theme"] for g in result]
    assert len(set(themes)) == len(themes), (
        f"duplicated section titles in report: {themes}"
    )
    assert len(result) == 1, (
        f"near-duplicate themes survived grouping, got {len(result)} groups: "
        f"{themes}"
    )


# ---------------------------------------------------------------------------
# Issue #9 — generic-theme-label blocklist + synonym normalization + seed merge
# ---------------------------------------------------------------------------


def _kw_entry(
    eid: str, title: str, source_platform: str = "techcrunch"
) -> dict[str, Any]:
    return {
        "entry_id": eid,
        "title": title,
        "summary": "developments across the tracked sources.",
        "source_url": f"https://x.com/{eid}",
        "source_type": "rss",
        "source_platform": source_platform,
    }


def test_generic_theme_labels_blocklisted_and_synonyms_merged() -> None:
    """Year + The Year merge into one group; New / User are dropped; every
    entry survives (reassigned to a surviving group or Additional Topics)."""
    entries = {
        "e1": _kw_entry("e1", "Series A funding round"),
        "e2": _kw_entry("e2", "GPT-5 model release"),
        "e3": _kw_entry("e3", "GPU cloud adoption"),
        "e4": _kw_entry("e4", "data center buildout"),
    }
    result = _merge_theme_groups([
        _group("Year", [entries["e1"]]),
        _group("The Year", [entries["e2"]]),
        _group("New", [entries["e3"]]),
        _group("User", [entries["e4"]]),
    ])

    themes = [g["theme"] for g in result]
    assert not any(
        t in {"New", "Year", "The Year", "User"}
        for t in themes
    ), f"blocklisted generic labels survived: {themes}"
    assert "Year" not in themes and "The Year" not in themes, themes
    assert len(result) == 1, (
        f"Year/The Year did not merge into a single surviving group: {themes}"
    )
    assert {e["entry_id"] for e in result[0]["entries"]} == {
        "e1",
        "e2",
        "e3",
        "e4",
    }, "all entries must be preserved across the drop/merge"


def test_english_keyword_grouping_returns_groups_not_none() -> None:
    """(b) ai-commercial English titles produce keyword groups — the
    demo-domain seed merge (todo 3) makes this pass.  Pre-fix (no seed merge)
    this returned ``None`` because the runtime ``_keywords.yaml`` normalizes
    to CJK-empty / ASCII fragments that never match English titles."""
    entries = [
        _kw_entry("e1", "Series A funding round"),
        _kw_entry("e2", "GPT-5 model release"),
        _kw_entry("e3", "new venture capital fund"),
    ]
    groups = _keyword_group_entries(entries, domain="ai-commercial")

    assert groups is not None, (
        "ai-commercial English-titled entries must group into keyword themes"
    )
    themes = [g["theme"] for g in groups]
    assert not any(
        t in {"New", "Year", "The Year", "User"}
        for t in themes
    ), f"fragment-derived generic labels leaked into themes: {themes}"
    assert len(groups) >= 2, (
        "expected at least two distinct keyword themes, got: "
        f"{[(g['theme'], len(g['entries'])) for g in groups]}"
    )


def test_fragment_keywords_do_not_create_generic_groups() -> None:
    """(c) Fragment keywords (``lui`` / ``ota`` / ``gui``) must not produce
    generic theme groups of their own."""
    entries = [
        _kw_entry("e1", "Series A funding round"),
        _kw_entry("e2", "GPT-5 model release"),
    ]
    groups = _keyword_group_entries(entries, domain="ai-commercial") or []

    themes = [g["theme"] for g in groups]
    assert not any(
        t in {"Lui", "Ota", "Gui", "New", "Year", "User"}
        for t in themes
    ), f"fragment keywords created generic groups: {themes}"


def test_cjk_keyword_path_does_not_regress() -> None:
    """(d) CJK-only keywords are filtered by ``_normalize_text`` to ``""`` and
    must not crash or create generic groups; the seed merge still supplies
    meaningful English topics for the ai-commercial keyword classifier."""
    entries = [
        _kw_entry("e1", "Series A funding round"),
        _kw_entry("e2", "GPT-5 model release"),
    ]
    groups = _keyword_group_entries(entries, domain="ai-commercial") or []

    themes = [g["theme"] for g in groups]
    assert not any(
        t in {"New", "Year", "User"}
        for t in themes
    ), f"generic labels leaked from the CJK-keyword path: {themes}"


def test_normalize_theme_text_merges_synonyms() -> None:
    """Year / The Year normalize to the same key so the exact-name merge pass
    combines them before the blocklist runs."""
    from autoinfo.output import _normalize_theme_text

    assert _normalize_theme_text("Year") == _normalize_theme_text("The Year")
