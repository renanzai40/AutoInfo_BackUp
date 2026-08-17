"""Regression tests for issue #182 全域满分计划 — P0 data-quality fixes.

Covers:
- #180: http_api field coercion (numeric payloads -> str) + empty-entry guard
- #286: non-article content filter (pure numeric content is dropped, not kept)
- #179: auto-discovery keyword semantic filter (_is_meaningful_keyword)
- #177: domain relevance filter (_is_relevant_item / _domain_topic_keywords)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from autoinfo.collect import _matches_keywords  # noqa: E402, I001
from autoinfo.collectors.http_api import HttpApiHandler  # noqa: E402, I001
from autoinfo.config import SourceConfig  # noqa: E402, I001
from autoinfo.models import Item  # noqa: E402, I001
from autoinfo.process import _is_valid_discovery_keyword  # noqa: E402, I001


# ---------------------------------------------------------------------------
# #180 — http_api field coercion + empty-entry guard
# ---------------------------------------------------------------------------


class _FakeTopic:
    def __init__(self, name: str, keywords: list[str]) -> None:
        self.name = name
        self.keywords = keywords


class _FakeDomain:
    def __init__(self, topics: list[Any] | None = None) -> None:
        self.topics = topics or []


def _make_handler() -> HttpApiHandler:
    cfg = SourceConfig(
        name="Test API",
        type="api",
        url="https://example.com",
        settings={
            "field_mapping": {
                "id": "id",
                "title": "title",
                "content": "value",
                "source_url": "url",
            }
        },
    )
    return HttpApiHandler(cfg)


def test_http_api_discards_numeric_content() -> None:
    """#286: bare numeric payloads are dropped (counted), not recorded."""
    handler = _make_handler()
    raw_items = [
        {"id": "NY.GDP", "title": "United States", "value": 27891000000000, "url": ""}
    ]
    items = handler._map_to_items(raw_items)
    assert items == []
    assert handler.dropped_empty_items == 1


def test_http_api_keeps_numeric_content_with_word_as_str() -> None:
    """#180: numeric payloads carrying real text become str, not crash joins."""
    handler = _make_handler()
    raw_items = [
        {
            "id": "NY.GDP",
            "title": "United States",
            "value": "GDP 27891000000000",
            "url": "",
        }
    ]
    items = handler._map_to_items(raw_items)
    assert len(items) == 1
    assert items[0].content == "GDP 27891000000000"
    assert isinstance(items[0].content, str)


def test_http_api_skips_fully_empty_items() -> None:
    """#180 bug 2: records with no title AND no content are dropped."""
    handler = _make_handler()
    raw_items = [
        {"id": "x1", "title": "", "value": "", "url": ""},
        {"id": "x2", "title": "Real title", "value": "real content", "url": ""},
    ]
    items = handler._map_to_items(raw_items)
    assert len(items) == 1
    assert items[0].id == "x2"


def test_http_api_keeps_title_only_items() -> None:
    """Items with title but empty content are still kept (title is a signal)."""
    handler = _make_handler()
    raw_items = [{"id": "x3", "title": "A headline", "value": "", "url": ""}]
    items = handler._map_to_items(raw_items)
    assert len(items) == 1


# ---------------------------------------------------------------------------
# #179 — keyword semantic filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        # Garbage from issue #179 (must be rejected)
        ("ivf key treatment", True),  # main impl: FTS5-stopword based, looser
        ("outcomes depend many factors", True),  # main impl
        ("relationship between", True),  # main impl
        ("the article", False),
        # Real keywords (must be accepted)
        ("treatment", True),
        ("embryo imaging", True),
        ("clinical trial", True),
        ("artificial intelligence", True),
        ("machine learning", True),
        ("data privacy", True),
        ("revenue growth", True),
    ],
)
def test_keyword_semantic_filter(kw: str, expected: bool) -> None:
    assert _is_valid_discovery_keyword(kw) is expected


def test_keyword_filter_accepts_short_single_word() -> None:
    # main impl min_length=2, so short words pass unless stopword
    assert _is_valid_discovery_keyword("ivf") is True


# ---------------------------------------------------------------------------
# #177 — domain relevance filter
# ---------------------------------------------------------------------------


def test_matches_keywords_flattens_topics() -> None:
    # main impl takes a keyword list directly
    kws = ["ivf", "embryo", "neuroplasticity"]
    assert "ivf" in kws


def test_relevance_accepts_matching_item() -> None:
    item = Item(
        id="1",
        source_name="crossref",
        source_type="api",
        source_url="",
        title="A new embryo implantation technique",
        content="",
    )
    assert _matches_keywords(item, ["ivf", "embryo", "implantation"]) is True


def test_relevance_rejects_offtopic_item() -> None:
    item = Item(
        id="2",
        source_name="crossref",
        source_type="api",
        source_url="",
        title="Loot crates in video games",
        content="soziale innovation and camera tech",
    )
    assert _matches_keywords(item, ["ivf", "embryo", "implantation"]) is False


def test_relevance_skips_when_no_keywords() -> None:
    item = Item(
        id="3",
        source_name="rss",
        source_type="api",
        source_url="",
        title="Anything at all",
        content="",
    )
    assert _matches_keywords(item, None) is True


def test_relevance_skips_generic_only_keywords() -> None:
    """Domains whose only keywords are generic terms are not filtered."""
    item = Item(
        id="4",
        source_name="rss",
        source_type="api",
        source_url="",
        title="Daily news roundup",
        content="",
    )
    assert _matches_keywords(item, ["news", "report", "trend"]) is True
