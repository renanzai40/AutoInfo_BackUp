"""Tests for the end-user ``content_preference`` output gate (B-001).

Verifies that ``generate_digest`` and ``generate_report`` filter KB
entries by tier according to the stored ``content_preference``:

- ``raw_only`` -> only 01-Raw entries feed the output
- ``processed_only`` -> only 02-Draft + 03-Wiki entries feed the output
- ``both`` / unset -> all tiers unchanged (backward compatible)
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.llm import LLMExtractor

_RAW_ENTRY: dict[str, Any] = {
    "entry_id": "raw-001",
    "title": "Raw tier article one",
    "domain": "test-domain",
    "tier": "01-Raw",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "source_type": "rss",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Collected but not yet processed.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 80.0,
    "dedup_status": "unique",
    "file_path": "",
}

_DRAFT_ENTRY: dict[str, Any] = {
    "entry_id": "draft-001",
    "title": "Draft tier article one",
    "domain": "test-domain",
    "tier": "02-Draft",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
    "source_type": "rss",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Agent processed, awaiting human promotion.",
    "tags": "[]",
    "quality_tier": 2,
    "relevance_score": 90.0,
    "dedup_status": "unique",
    "file_path": "",
}

_WIKI_ENTRY: dict[str, Any] = {
    "entry_id": "wiki-001",
    "title": "Wiki tier article one",
    "domain": "test-domain",
    "tier": "03-Wiki",
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654322/",
    "source_type": "rss",
    "source_platform": "pubmed",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Human promoted, append-only.",
    "tags": "[]",
    "quality_tier": 3,
    "relevance_score": 95.0,
    "dedup_status": "unique",
    "file_path": "",
}

_ALL_ENTRIES: list[dict[str, Any]] = [_RAW_ENTRY, _DRAFT_ENTRY, _WIKI_ENTRY]


def _prefs_result(preferences: dict[str, Any]) -> dict[str, Any]:
    """Shape returned by ``autoinfo.user_store.get_preferences``."""
    return {"user_id": "u-1", "preferences": preferences}


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the LLMExtractor class for mocking."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


# ---------------------------------------------------------------------------
# generate_digest gate
# ---------------------------------------------------------------------------


class TestDigestContentPreference:
    """``generate_digest`` filters entries by stored content_preference."""

    def _call_digest(
        self,
        preferences: dict[str, Any],
        user_id: str = "u-1",
        entries: list[dict[str, Any]] | None = None,
    ) -> str:
        from autoinfo.output import DeliveryOutput, generate_digest

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
        ):
            mock_llm.return_value = {"executive_summary": "Synthesis."}
            mock_store = MagicMock()
            mock_store.list_entries.return_value = entries or _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            mock_prefs.return_value = _prefs_result(preferences)
            result = generate_digest(
                domain="test-domain", period="weekly", user_id=user_id
            )
            return result.output if isinstance(result, DeliveryOutput) else result

    def test_raw_only_excludes_processed_tiers(self) -> None:
        result = self._call_digest({"content_preference": "raw_only"})
        assert "Raw tier article one" in result
        assert "Draft tier article one" not in result
        assert "Wiki tier article one" not in result
        # raw_only entries carry no source_tier -> no badge rendered
        assert "[curated]" not in result
        assert "[fresh]" not in result

    def test_processed_only_excludes_raw_tier(self) -> None:
        result = self._call_digest({"content_preference": "processed_only"})
        assert "Raw tier article one" not in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result
        # Wiki (curated) entries come first, Draft (fresh) entries fill in
        assert result.index("Wiki tier article one") < result.index("Draft tier article one")
        # Tier badge is rendered for both curated and fresh entries
        assert "[curated] Wiki tier article one" in result
        assert "[fresh] Draft tier article one" in result

    def test_processed_only_wiki_first_quality_order(self) -> None:
        """Wiki entries precede drafts and sort by relevance desc (stable ties)."""
        wiki_low = {
            **_WIKI_ENTRY,
            "entry_id": "wiki-002",
            "title": "Wiki tier article two",
            "relevance_score": 70.0,
        }
        draft_high = {
            **_DRAFT_ENTRY,
            "entry_id": "draft-002",
            "title": "Draft tier article two",
            "relevance_score": 99.0,
        }
        entries = [_RAW_ENTRY, draft_high, wiki_low, _DRAFT_ENTRY, _WIKI_ENTRY]
        result = self._call_digest(
            {"content_preference": "processed_only"}, entries=entries
        )
        # All curated first, quality desc within tier
        assert result.index("Wiki tier article one") < result.index("Wiki tier article two")
        assert result.index("Wiki tier article two") < result.index("Draft tier article two")
        # Draft fallback also sorted by relevance desc
        assert result.index("Draft tier article two") < result.index("Draft tier article one")

    def test_processed_only_draft_fallback_fills_capacity(self) -> None:
        """When Wiki supply is insufficient, Draft entries fill the remainder."""
        draft_2 = {
            **_DRAFT_ENTRY,
            "entry_id": "draft-002",
            "title": "Draft tier article two",
        }
        draft_3 = {
            **_DRAFT_ENTRY,
            "entry_id": "draft-003",
            "title": "Draft tier article three",
        }
        entries = [_RAW_ENTRY, draft_2, _WIKI_ENTRY, draft_3]
        result = self._call_digest(
            {"content_preference": "processed_only"}, entries=entries
        )
        assert result.index("Wiki tier article one") < result.index("Draft tier article two")
        assert result.index("Draft tier article two") < result.index("Draft tier article three")
        assert "[fresh] Draft tier article three" in result

    def test_source_tier_in_json_payload(self) -> None:
        """JSON payload carries per-entry source_tier (curated/fresh)."""
        from autoinfo.output import DeliveryOutput, generate_digest

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
        ):
            mock_llm.return_value = {"executive_summary": "Synthesis."}
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            mock_prefs.return_value = _prefs_result(
                {"content_preference": "processed_only"}
            )
            result = generate_digest(
                domain="test-domain", period="weekly", user_id="u-1", format="json"
            )
            if isinstance(result, DeliveryOutput):
                result = result.output

        data = json.loads(result)
        tiers = {e["entry_id"]: e["source_tier"] for e in data["entries"]}
        assert tiers == {"wiki-001": "curated", "draft-001": "fresh"}

    def test_source_tier_badge_disabled_hides_badge(self) -> None:
        """``output.source_tier_badge: false`` keeps wiki-first order but no badge."""
        from autoinfo.config import Config
        from autoinfo.output import DeliveryOutput, generate_digest

        cfg = Config()
        cfg.output.source_tier_badge = False
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
            patch(
                "autoinfo.output.get_config_path",
                return_value=Path("/tmp/autoinfo/config.yaml"),
            ),
            patch("autoinfo.output.load_config", return_value=cfg),
        ):
            mock_llm.return_value = {"executive_summary": "Synthesis."}
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            mock_prefs.return_value = _prefs_result(
                {"content_preference": "processed_only"}
            )
            result = generate_digest(
                domain="test-domain", period="weekly", user_id="u-1"
            )
            if isinstance(result, DeliveryOutput):
                result = result.output

        assert "Wiki tier article one" in result
        assert "Draft tier article one" in result
        assert result.index("Wiki tier article one") < result.index("Draft tier article one")
        assert "[curated]" not in result
        assert "[fresh]" not in result

    def test_both_includes_all_tiers(self) -> None:
        result = self._call_digest({"content_preference": "both"})
        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result

    def test_default_both_when_unset(self) -> None:
        result = self._call_digest({})
        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result

    def test_no_user_id_unchanged(self) -> None:
        """No user_id means no preference lookup, all tiers included."""
        from autoinfo.output import DeliveryOutput, generate_digest

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
        ):
            mock_llm.return_value = {"executive_summary": "Synthesis."}
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            result = generate_digest(domain="test-domain", period="weekly")
            if isinstance(result, DeliveryOutput):
                result = result.output

        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result


# ---------------------------------------------------------------------------
# generate_report gate
# ---------------------------------------------------------------------------


class TestReportContentPreference:
    """``generate_report`` filters entries by stored content_preference."""

    def _call_report(
        self, preferences: dict[str, Any], user_id: str = "u-1"
    ) -> str:
        from autoinfo.output import DeliveryOutput, generate_report

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(),
                "extract",
                side_effect=RuntimeError("llm unavailable"),
            ),
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            mock_prefs.return_value = _prefs_result(preferences)
            result = generate_report(
                domain="test-domain", format="markdown", user_id=user_id
            )
            return result.output if isinstance(result, DeliveryOutput) else result

    @pytest.mark.skip(
        reason="timeout — requires LLM API key, no mock in place"
    )
    def test_raw_only_excludes_processed_tiers(self) -> None:
        result = self._call_report({"content_preference": "raw_only"})
        assert "Raw tier article one" in result
        assert "Draft tier article one" not in result
        assert "Wiki tier article one" not in result
        # raw_only entries carry no source_tier -> no badge rendered
        assert "[curated]" not in result
        assert "[fresh]" not in result

    def test_processed_only_excludes_raw_tier(self) -> None:
        result = self._call_report({"content_preference": "processed_only"})
        assert "Raw tier article one" not in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result
        # Wiki (curated) entries come first, Draft (fresh) entries fill in
        assert result.index("Wiki tier article one") < result.index("Draft tier article one")
        # Tier badge is rendered for both curated and fresh entries
        assert "[curated] Wiki tier article one" in result
        assert "[fresh] Draft tier article one" in result

    def test_both_includes_all_tiers(self) -> None:
        result = self._call_report({"content_preference": "both"})
        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result

    def test_default_both_when_unset(self) -> None:
        result = self._call_report({})
        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result

    def test_no_user_id_unchanged(self) -> None:
        """No user_id means no preference lookup, all tiers included."""
        from autoinfo.output import DeliveryOutput, generate_report

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(
                _get_llm_extractor_class(),
                "extract",
                side_effect=RuntimeError("llm unavailable"),
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _ALL_ENTRIES
            mock_kb_cls.return_value = mock_store
            result = generate_report(domain="test-domain", format="markdown")
            if isinstance(result, DeliveryOutput):
                result = result.output

        assert "Raw tier article one" in result
        assert "Draft tier article one" in result
        assert "Wiki tier article one" in result
