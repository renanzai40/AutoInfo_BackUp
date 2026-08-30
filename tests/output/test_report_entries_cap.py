"""PR #106 — report/column must cap KB entries at 200 before thematic grouping,
and ``_group_by_theme`` must fall back to deterministic grouping on a chaotic
LLM theme burst (>20 themes or >6 single-entry groups).

Backup issue #106: financial-intelligence (470 entries) report/column blew past
the CLI timeout because an uncapped ``list_entries(limit=5000)`` fed all 470
entries into ``_group_by_theme`` → 59 LLM batches ÷ 4 workers × ~30s+ each →
0-byte output.  ``generate_digest`` already caps at ``query_limit=200`` (and
tutorial at 10 per #103) — this locks the same cap, plus the chaos guard, for
the report/column path (#178 protocol).

RED→GREEN: these tests fail on pre-#106 code (no cap, no guard) and pass after
the fix.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import _group_by_theme

# Vary source_type so the deterministic fallback can split into ≥2 source
# groups (otherwise ``_deterministic_grouping`` may return None when fewer than
# two distinct topics are detectable).
_SOURCE_TYPES = ("rss", "api", "web")


def _entry(i: int) -> dict[str, Any]:
    return {
        "entry_id": f"e{i}",
        "title": f"AI funding round {i}",
        "summary": f"Startup {i} raised $20M.",
        "source_url": f"https://techcrunch.com/{i}",
        "source_type": _SOURCE_TYPES[i % len(_SOURCE_TYPES)],
        "source_platform": "techcrunch",
        "relevance_score": 90 - (i % 10),
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    }


def _call_report(domain: str, format: str = "markdown") -> str:
    from autoinfo.output import generate_report

    return generate_report(domain=domain, format=format)


def _stub_summary() -> dict[str, Any]:
    return {
        "executive_summary": "This report covers the tracked developments.",
        "key_findings": [],
        "recommendations": [],
    }


class TestReportEntriesCap:
    """PR #106 — the report path caps KB entries at 200 before grouping."""

    def test_thick_domain_caps_entries_before_grouping(self) -> None:
        """500 KB entries → exactly 200 reach the grouping stage (entry #201
        never does), aligned with ``generate_digest``'s ``query_limit=200``."""
        entries = [_entry(i) for i in range(1, 501)]
        captured: dict[str, int] = {}

        def _fake_group_by_theme(
            extractor: object,
            ents: list[dict[str, Any]],
            domain: str = "",
            domains: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            captured["count"] = len(ents)
            return [{"theme": "General", "description": "", "entries": list(ents)}]

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch(
                "autoinfo.output._group_by_theme",
                side_effect=_fake_group_by_theme,
            ),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value=_stub_summary(),
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = entries
            mock_kb_cls.return_value = mock_store
            _call_report("medical-research")

        assert captured["count"] == 200, (
            f"expected 200 entries to reach grouping, got {captured['count']} "
            "(report must cap entries at 200 per #106)"
        )

    def test_thin_domain_passes_all_entries_through(self) -> None:
        """3 KB entries (well under 200) pass through untouched."""
        entries = [_entry(i) for i in range(1, 4)]
        captured: dict[str, int] = {}

        def _fake_group_by_theme(
            extractor: object,
            ents: list[dict[str, Any]],
            domain: str = "",
            domains: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            captured["count"] = len(ents)
            return [{"theme": "General", "description": "", "entries": list(ents)}]

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch(
                "autoinfo.output._group_by_theme",
                side_effect=_fake_group_by_theme,
            ),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value=_stub_summary(),
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = entries
            mock_kb_cls.return_value = mock_store
            _call_report("medical-research")

        assert captured["count"] == 3, f"thin domain truncated: {captured['count']}"


class TestGroupingChaosGuard:
    """PR #106 — ``_group_by_theme`` falls back to deterministic grouping on a
    chaotic LLM burst (>20 themes or >6 single-entry groups) so the oversized
    synthesis prompt downstream never times out producing 0-byte output."""

    @staticmethod
    def _group(llm_groups: list[dict[str, Any]], n_entries: int = 25) -> list[dict[str, Any]]:
        entries = [_entry(i) for i in range(1, n_entries + 1)]
        with patch("autoinfo.output._run_grouping_batches", return_value=llm_groups):
            return _group_by_theme(MagicMock(), entries, domain="ai-commercial")

    def test_more_than_twenty_themes_falls_back_to_deterministic(self) -> None:
        """25 single-entry themes (>20) — the garbage burst must not survive."""
        chaos = [
            {"theme": f"Chaos-Theme-{i}", "description": "", "entries": [_entry(i)]}
            for i in range(1, 26)
        ]
        result = self._group(chaos, n_entries=25)

        assert not any(g["theme"].startswith("Chaos-Theme-") for g in result), (
            "chaotic LLM burst survived; chaos guard must fall back to deterministic grouping"
        )
        total = sum(len(g["entries"]) for g in result)
        assert total == 25, f"deterministic fallback lost entries: {total}"

    def test_more_than_six_single_entry_themes_falls_back(self) -> None:
        """12 themes but 8 single-entry (>6) with ≤20 themes — the second
        chaos threshold also triggers the fallback."""
        grouped: list[dict[str, Any]] = [
            {"theme": f"Single-{i}", "description": "", "entries": [_entry(i)]} for i in range(1, 9)
        ]
        grouped.append(
            {
                "theme": "Bulk",
                "description": "",
                "entries": [_entry(i) for i in range(9, 26)],
            }
        )
        result = self._group(grouped, n_entries=25)

        assert not any(g["theme"].startswith("Single-") for g in result), (
            "single-entry theme burst survived; chaos guard must fall back to "
            "deterministic grouping"
        )
        total = sum(len(g["entries"]) for g in result)
        assert total == 25, f"deterministic fallback lost entries: {total}"

    def test_bounded_grouping_is_preserved(self) -> None:
        """A sane LLM grouping (2 themes, no single-entry explosion) is kept."""
        grouped = [
            {
                "theme": "Alpha",
                "description": "",
                "entries": [_entry(i) for i in range(1, 14)],
            },
            {
                "theme": "Beta",
                "description": "",
                "entries": [_entry(i) for i in range(14, 26)],
            },
        ]
        result = self._group(grouped, n_entries=25)

        themes = [g["theme"] for g in result]
        assert "Alpha" in themes and "Beta" in themes
        total = sum(len(g["entries"]) for g in result)
        assert total == 25
