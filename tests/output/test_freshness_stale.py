"""Tests for the stale-source guard (backup issue #52).

When freshness filtering removes *every* candidate entry, ``generate_digest``
must NOT silently produce an empty-shell product. In the plain (CLI/MCP) path
it raises ``StaleSourceError`` (a ``ValueError``); in the ``DeliveryOutput``
path it returns a blocked ``DeliveryOutput`` with a warning. A single fresh
entry keeps the digest alive, and ``include_stale=True`` disables the guard.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import DeliveryOutput, StaleSourceError, generate_digest


def _entry(eid: str, collected_at: str, title: str = "item") -> dict[str, Any]:
    return {
        "entry_id": eid,
        "title": f"{title} {eid}",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": f"https://example.com/{eid}",
        "source_type": "rss",
        "source_platform": "rss",
        "language": "en",
        "collected_at": collected_at,
        "summary": f"summary {eid}",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    }


def _stale_entries(n: int = 2) -> list[dict[str, Any]]:
    # 2020 is far older than any TTL, so freshness score is 0.0 (< threshold).
    return [_entry(f"stale-{i}", "2020-01-01T00:00:00+00:00") for i in range(n)]


def _mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


def _fail_open_sources(domain: str) -> list[Any]:
    """FAIL-OPEN (drift filter #119): this fixture KB is synthetic (hosts on
    example.com) — no real config sources match, so declare none active and
    keep everything (the tests exercise staleness, not source drift)."""
    del domain
    return []


class TestStaleSourceGuard:
    # --- RED: all entries stale -> plain path raises StaleSourceError --------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._get_domain_source_configs", side_effect=_fail_open_sources)
    def test_all_stale_raises_stalesourceerror(self, mock_src, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        with pytest.raises(StaleSourceError):
            generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                include_stale=False,
            )

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._get_domain_source_configs", side_effect=_fail_open_sources)
    def test_all_stale_is_valueerror_subclass(self, mock_src, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        with pytest.raises(ValueError):
            generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                include_stale=False,
            )

    # --- GREEN control: at least one fresh entry keeps the digest alive ------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._get_domain_source_configs", side_effect=_fail_open_sources)
    @patch("autoinfo.output._call_llm_for_digest")
    def test_mixed_fresh_and_stale_does_not_raise(
        self, mock_llm: MagicMock, mock_src, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        fresh = _entry("fresh-0", "2026-08-25T00:00:00+00:00", title="Fresh")
        entries = _stale_entries() + [fresh]
        mock_kb.return_value = _mock_store(entries)
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            include_stale=False,
        )
        assert result is not None
        assert "Fresh fresh-0" in result

    # --- GREEN control: include_stale=True disables the guard ----------------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._get_domain_source_configs", side_effect=_fail_open_sources)
    @patch("autoinfo.output._call_llm_for_digest")
    def test_include_stale_true_keeps_stale_entries(
        self, mock_llm: MagicMock, mock_src, mock_kb: MagicMock
    ) -> None:
        mock_llm.return_value = {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        }
        mock_kb.return_value = _mock_store(_stale_entries())
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            include_stale=True,
        )
        assert result is not None
        assert "stale-0" in result

    # --- RED: all entries stale -> DeliveryOutput path blocks ----------------
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._get_domain_source_configs", side_effect=_fail_open_sources)
    def test_all_stale_with_delivery_gates_blocks(self, mock_src, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            include_stale=False,
            delivery_gate_configs={"D1": {"action": "block"}},
        )
        assert isinstance(result, DeliveryOutput)
        assert result.delivery_blocked is True
        assert any("STALE_SOURCE" in w for w in result.warnings)
