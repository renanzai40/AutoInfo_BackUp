"""Teaching-layer staleness tests (backup issue #60).

When freshness filtering (include_stale=False) removes EVERY candidate entry
from the teaching layer (tutorial/presentation), the product must not be
silently regenerated from an old corpus (e.g. 2024 Corriere after the ANSA
source swap). Mirror the digest stale-source guard (#52): raise
StaleSourceError in the plain path, block in the DeliveryOutput path, and
respect the freshness threshold on regenerated teaching-layer products.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import (
    DeliveryOutput,
    StaleSourceError,
    generate_presentation,
    generate_tutorial,
)


def _entry(eid: str, collected_at: str, title: str = "item") -> dict[str, Any]:
    return {
        "entry_id": eid,
        "title": f"{title} {eid}",
        "domain": "italian-learning",
        "tier": "01-Raw",
        "source_url": f"https://example.com/{eid}",
        "source_type": "rss",
        "source_platform": "rss",
        "language": "it",
        "collected_at": collected_at,
        "summary": f"summary {eid}",
        "tags": "[]",
        "quality_tier": 1,
        "relevance_score": 80.0,
    }


def _stale_entries(n: int = 2) -> list[dict[str, Any]]:
    # 2020 is far older than any TTL, so freshness score is 0.0 (< threshold).
    return [_entry(f"stale-{i}", "2020-01-01T00:00:00+00:00", title="Corriere") for i in range(n)]


def _fresh_entry() -> dict[str, Any]:
    return _entry("fresh-0", "2026-08-25T00:00:00+00:00", title="ANSA")


def _mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = entries
    return store


class TestTutorialStaleness:
    @patch("autoinfo.output.KBStore")
    def test_all_stale_raises_stalesourceerror(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        with pytest.raises(StaleSourceError):
            generate_tutorial(
                domain="italian-learning",
                format="markdown",
                include_stale=False,
            )

    @patch("autoinfo.output.KBStore")
    def test_fresh_entry_keeps_tutorial_alive(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries() + [_fresh_entry()])
        # A fresh entry must keep the tutorial alive (no raise); with the
        # KB-only content the LLM is called and a tutorial is produced.
        with patch("autoinfo.output._call_llm_for_tutorial", return_value={}):
            body = generate_tutorial(
                domain="italian-learning",
                format="markdown",
                include_stale=False,
            )
        assert isinstance(body, str)
        assert "ANSA fresh-0" in body
        assert "Corriere stale-0" not in body

    @patch("autoinfo.output.KBStore")
    def test_include_stale_true_keeps_old_corpus(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        with patch("autoinfo.output._call_llm_for_tutorial", return_value={}):
            body = generate_tutorial(
                domain="italian-learning",
                format="markdown",
                include_stale=True,
            )
        assert isinstance(body, str)
        assert "Corriere stale-0" in body

    @patch("autoinfo.output.KBStore")
    def test_delivery_gates_path_blocks_not_raises(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        result = generate_tutorial(
            domain="italian-learning",
            format="markdown",
            include_stale=False,
            delivery_gate_configs={"D1": {"action": "block"}},
        )
        assert isinstance(result, DeliveryOutput)
        assert result.delivery_blocked is True
        assert any("STALE_SOURCE" in w for w in result.warnings)


class TestPresentationStaleness:
    @patch("autoinfo.output.KBStore")
    def test_all_stale_raises_stalesourceerror(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries())
        with pytest.raises(StaleSourceError):
            generate_presentation(
                domain="italian-learning",
                topic="current events",
                format="markdown",
                include_stale=False,
            )

    @patch("autoinfo.output.KBStore")
    def test_fresh_entry_keeps_presentation_alive(self, mock_kb: MagicMock) -> None:
        mock_kb.return_value = _mock_store(_stale_entries() + [_fresh_entry()])
        with patch("autoinfo.output._call_llm_for_presentation", return_value={}):
            result = generate_presentation(
                domain="italian-learning",
                topic="current events",
                format="markdown",
                include_stale=False,
                allow_empty=True,
            )
        assert result is not None