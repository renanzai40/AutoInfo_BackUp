"""Issue #311 — report section titles are semantic themes, not raw keyword
dumps or duplicated titles.

Verifies:
(a) the thematic-grouping prompts instruct the LLM to emit SHORT SEMANTIC
    titles (noun phrases, never raw keyword lists or joined keyword strings);
(b) near-duplicate theme titles (case / "&" / "and" / word-order variants)
    are merged by ``_merge_theme_groups`` so a report never shows two
    sections that name the same theme;
(c) ``_group_by_theme`` returns only unique section titles.
"""

from __future__ import annotations

from typing import Any

from autoinfo.llm import LLMExtractor
from autoinfo.output import (
    _group_batch_by_theme,
    _group_by_theme,
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
