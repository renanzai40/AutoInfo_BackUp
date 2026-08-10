"""Regression tests for #180: str coercion and empty-item dropping.

Covers four behaviours introduced to fix the ``TypeError: sequence item 1:
expected str instance, int found`` crash on HTTP-API sources (e.g. World
Bank) that return numeric field values, and the garbage empty-content KB
entries produced by sources with no ``field_mapping`` (e.g. Alpha Vantage):

(a) A numeric field value in a fake World-Bank-style payload is coerced to
    its ``str`` representation (``12345`` -> ``"12345"``) and the produced
    item no longer crashes downstream (``kb._build_body``).
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

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from autoinfo.collectors.http_api import HttpApiHandler
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
# (a) Numeric field values are coerced to str
# ---------------------------------------------------------------------------


@patch("autoinfo.collectors.http_api.httpx.get")
def test_numeric_field_value_coerced_to_string(mock_get: MagicMock) -> None:
    """World-Bank-style payload with int/float values -> str content."""
    config = _world_bank_config()
    mock_get.return_value = _mock_http(
        [
            {"country": "United States", "value": 12345, "date": "2023"},
            {"country": "China", "value": 67890.5, "date": "2022"},
        ]
    )

    handler = HttpApiHandler(config)
    items = handler.fetch(config.url, limit=10)

    assert len(items) == 2
    assert items[0].content == "12345"
    assert isinstance(items[0].content, str)
    assert items[1].content == "67890.5"
    assert isinstance(items[1].content, str)

    # Downstream crash site (issue #180): _build_body must not raise.
    body = _build_body(items[0])
    assert "12345" in body
    assert "## Original Content" in body


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
        content=12345,
    )
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
