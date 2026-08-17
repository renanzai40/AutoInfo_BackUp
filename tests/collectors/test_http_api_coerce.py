"""Regression tests for #180: str coercion and empty-item dropping.

Covers four behaviours introduced to fix the ``TypeError: sequence item 1:
expected str instance, int found`` crash on HTTP-API sources (e.g. World
Bank) that return numeric field values, and the garbage empty-content KB
entries produced by sources with no ``field_mapping`` (e.g. Alpha Vantage):

(a) A pure-numeric field value in a fake World-Bank-style payload is not
    article-like content (issue #286) — the item is dropped and counted,
    instead of producing a garbage KB entry.
(b) An item whose title AND content are both empty after mapping is dropped,
    and the drop is counted on the handler (``dropped_empty_items``) and
    reported in its log output.
(c) ``kb._build_body`` with a non-str content part no longer raises
    (direct unit test of the crash site).
(d) ``Item.from_dict`` coerces an ``int`` content to ``str`` and ``None``
    title to ``""``.

All tests use fake payloads and a monkeypatched ``httpx.get`` — no real
network or LLM calls.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.http_api import HttpApiHandler, is_article_like_content
from autoinfo.config import SourceConfig
from autoinfo.kb import _build_body
from autoinfo.models import Item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _world_bank_config() -> SourceConfig:
    """World-Bank-style source: numeric values come back in the payload."""
    return SourceConfig(
        name="World Bank Data",
        type="api",
        url="https://api.worldbank.org/v2/country",
        settings={
            "json_path": "$",
            "field_mapping": {
                "id": "date",
                "title": "country",
                "content": "value",
            },
        },
    )


def _alpha_vantage_config() -> SourceConfig:
    """Alpha-Vantage-style source: no ``field_mapping`` configured."""
    return SourceConfig(
        name="Alpha Vantage",
        type="api",
        url="https://www.alphavantage.co/query",
        settings={
            "json_path": "$",
            "field_mapping": {
                "id": "symbol",
                "title": "name",
                "content": "description",
            },
        },
    )


def _mock_http(payload: Any) -> MagicMock:
    """Build a mocked httpx.Response returning ``payload`` as JSON."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = payload
    mock_response.raise_for_status.return_value = None
    return mock_response


# ---------------------------------------------------------------------------
# (a) Pure-numeric content is dropped (#286); numeric content that carries
#     a word is kept and stays str (#180)
# ---------------------------------------------------------------------------


@patch("autoinfo.collectors.http_api.httpx.get")
def test_numeric_content_item_dropped_and_counted(
    mock_get: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Bare numeric content (issue #286) is dropped and counted, not recorded."""
    config = _world_bank_config()
    mock_get.return_value = _mock_http(
        [
            {"country": "United States", "value": 12345, "date": "2023"},
            {"country": "China", "value": 67890.5, "date": "2022"},
        ]
    )

    handler = HttpApiHandler(config)
    caplog.set_level(logging.INFO, logger="autoinfo.collectors.http_api")
    items = handler.fetch(config.url, limit=10)

    assert items == []
    assert handler.dropped_empty_items == 2
    assert any("non-article" in record.getMessage() for record in caplog.records)


@patch("autoinfo.collectors.http_api.httpx.get")
def test_numeric_content_with_word_is_kept(mock_get: MagicMock) -> None:
    """Numeric content carrying a word survives and stays str (#180/#286)."""
    config = _world_bank_config()
    mock_get.return_value = _mock_http(
        [
            {"country": "United States", "value": "GDP 12345", "date": "2023"},
        ]
    )

    handler = HttpApiHandler(config)
    items = handler.fetch(config.url, limit=10)

    assert len(items) == 1
    assert items[0].content == "GDP 12345"
    assert isinstance(items[0].content, str)

    # Downstream crash site (issue #180): _build_body must not raise.
    body = _build_body(items[0])
    assert "12345" in body
    assert "## Original Content" in body


# ---------------------------------------------------------------------------
# (a') is_article_like_content unit tests (#286)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # Pure numbers / symbols / whitespace -> not article-like (#286)
        ("30769700000000", False),
        ("12345", False),
        ("67890.5", False),
        ("3.07697e13", False),
        ("", False),
        ("   ", False),
        ("!!! ### +++", False),
        # Numbers + short code-like letter runs (<3 consecutive) -> dropped
        ("a1b2c3d4", False),
        ("12ab 34cd 56", False),
        # Numbers + a real word run (>=3 consecutive letters) -> kept
        ("12345abc", True),
        ("GDP 12345", True),
        ("USD 30769700000000", True),
        # Normal prose -> kept
        ("This is a normal article about economic growth.", True),
        ("The quick brown fox jumps over the lazy dog 123 times.", True),
        # CJK prose (each ideograph is a word) -> kept
        ("中国GDP增长百分之五", True),
        ("日本語の経済ニュースです", True),
    ],
)
def test_is_article_like_content(content: str, expected: bool) -> None:
    assert is_article_like_content(content) is expected


# ---------------------------------------------------------------------------
# (b) Empty title+content items are dropped and counted
# ---------------------------------------------------------------------------


@patch("autoinfo.collectors.http_api.httpx.get")
def test_empty_title_and_content_item_dropped_and_counted(
    mock_get: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Items with both title and content empty are dropped; drop counted."""
    config = _alpha_vantage_config()
    mock_get.return_value = _mock_http(
        [
            {"symbol": "AAPL", "name": "Apple", "description": "Apple Inc."},
            {"symbol": "MSFT"},  # no name/description -> empty title+content
        ]
    )

    handler = HttpApiHandler(config)
    caplog.set_level(logging.INFO, logger="autoinfo.collectors.http_api")
    items = handler.fetch(config.url, limit=10)

    assert len(items) == 1
    assert items[0].id == "AAPL"
    assert handler.dropped_empty_items == 1

    # The drop is reported in the handler's log output.
    assert any("empty item" in record.getMessage() for record in caplog.records)


@patch("autoinfo.collectors.http_api.httpx.get")
def test_title_only_item_is_kept(mock_get: MagicMock) -> None:
    """An item with a title but no content is still kept (not dropped)."""
    config = _alpha_vantage_config()
    mock_get.return_value = _mock_http(
        [
            {"symbol": "AAPL", "name": "Apple", "description": ""},
            {"symbol": "MSFT", "name": "", "description": "Microsoft Corp."},
        ]
    )

    handler = HttpApiHandler(config)
    items = handler.fetch(config.url, limit=10)

    assert len(items) == 2
    assert handler.dropped_empty_items == 0


# ---------------------------------------------------------------------------
# (c) kb._build_body tolerates non-str content parts
# ---------------------------------------------------------------------------


def test_build_body_does_not_raise_on_int_content() -> None:
    """Direct unit test of the crash site: int content no longer raises."""
    item = Item(
        id="x",
        source_name="World Bank Data",
        source_type="api",
        source_url="https://api.worldbank.org/v2/country",
        title="United States",
        content="",
    )
    # Simulate a non-str value that slipped through the untyped collection
    # boundary (raw API JSON) — the crash site _build_body must tolerate it.
    object.__setattr__(item, "content", 12345)
    body = _build_body(item)
    assert "12345" in body
    assert "## Original Content" in body


# ---------------------------------------------------------------------------
# (d) Item.from_dict coerces content/title to str
# ---------------------------------------------------------------------------


def test_item_from_dict_coerces_int_content_to_str() -> None:
    item = Item.from_dict({
        "id": "x",
        "source_name": "World Bank Data",
        "source_type": "api",
        "source_url": "https://api.worldbank.org/v2/country",
        "title": "United States",
        "content": 12345,
    })
    assert item.content == "12345"
    assert isinstance(item.content, str)


def test_item_from_dict_coerces_none_title_to_empty() -> None:
    item = Item.from_dict({
        "id": "x",
        "source_name": "World Bank Data",
        "source_type": "api",
        "source_url": "https://api.worldbank.org/v2/country",
        "title": None,
        "content": None,
    })
    assert item.title == ""
    assert item.content == ""
