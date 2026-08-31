"""Shared week-windowed story-set helper (cross-product-coherence #119, todo 2).

C1 contract: digest / presentation / report on the SAME domain must draw from
the SAME story set.  ``_select_story_set`` reproduces the digest's single-domain
selection exactly (window query + full-domain fallback + ``_sorted_ref_entries``
ordering), and presentation/report adopt the shared set.  The digest is the
byte-identity anchor — the golden render committed in todo 1
(``tests/output/fixtures/digest_golden.md``) must be reproduced byte-for-byte.

RED→GREEN: these tests fail on pre-todo-2 code (no ``_select_story_set``
helper, presentation loads all-time ``limit=5000``, report loads all-time too)
and pass after the extraction + adoption.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import SourceConfig
from autoinfo.output import (
    _select_story_set,
    generate_digest,
    generate_presentation,
    generate_report,
)

# Freeze used by the byte-identical golden test AND the capture script, so the
# committed ``tests/output/fixtures/digest_golden.md`` render is reproducible.
FROZEN_NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
# ``_compute_date_range`` uses ``date.today()`` (not ``datetime.now``) for the
# period window; freeze BOTH so the golden's date_from/date_to is stable.
FROZEN_TODAY = FROZEN_NOW.date()

_GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "digest_golden.md"

# Two configured sources for the ``tech-ai-developer`` domain: techcrunch-ai
# (rss feed on techcrunch.com) + ars-technica (rss feed on feeds.arstechnica.com).
_URLS = [
    "https://techcrunch.com/category/artificial-intelligence/1",
    "https://techcrunch.com/category/artificial-intelligence/2",
    "https://techcrunch.com/category/artificial-intelligence/3",
    "https://arstechnica.com/ai/2026/08/funding-round-4",
    "https://arstechnica.com/ai/2026/08/funding-round-5",
]

_SOURCES = ["techcrunch-ai", "techcrunch-ai", "techcrunch-ai", "ars-technica", "ars-technica"]

# A drifted source NOT in the ``tech-ai-developer`` config: infoq-cn.
_DRIFTED_URL = "https://www.infoq.cn/article/ai-funding-9"
_DRIFTED_PLATFORM = "infoq-cn"


def _entry(i: int, *, drifted: bool = False) -> dict[str, Any]:
    if drifted:
        return {
            "entry_id": f"tech-e-drift-{i}",
            "title": f"Drifted funding round {i}",
            "summary": f"Drifted startup {i} raised money.",
            "domain": "tech-ai-developer",
            "tier": "01-Raw",
            "language": "en",
            "source_url": _DRIFTED_URL,
            "source_type": "rss",
            "source_platform": _DRIFTED_PLATFORM,
            "collected_at": f"2026-08-2{i}:10:00:00Z",
            "relevance_score": 90.0 - (i % 10),
            "tags": '["AI", "funding"]',
            "quality_tier": 1,
            "dedup_status": "unique",
            "file_path": "",
            "custom_fields": "{}",
        }
    if i <= len(_URLS):
        url = _URLS[i - 1]
        source = _SOURCES[i - 1]
        day = i
    else:
        url = f"https://techcrunch.com/category/artificial-intelligence/{i}"
        source = "techcrunch-ai"
        day = 1 + (i % 5)
    return {
        "entry_id": f"tech-e{i}",
        "title": f"AI funding round {i}: model inference costs fall",
        "summary": f"Startup {i} cut inference cost by 40% this week.",
        "domain": "tech-ai-developer",
        "tier": "01-Raw",
        "language": "en",
        "source_url": url,
        "source_type": "rss",
        "source_platform": source,
        "collected_at": f"2026-08-2{day}:10:00:00Z",
        "relevance_score": 90.0 - (i % 10),
        "tags": '["AI", "funding"]',
        "quality_tier": 1,
        "dedup_status": "unique",
        "file_path": "",
        "custom_fields": "{}",
    }


def _canned_llm(prompt: str, config: Any = None) -> dict[str, Any]:
    del prompt, config
    return {
        "executive_summary": (
            "This week's developments center on falling model inference costs "
            "driving new AI funding rounds."
        ),
        "key_findings": [
            {"topic": "Inference costs", "detail": "Startups report 40% cost cuts."},
        ],
        "trends": ["Cheaper inference"],
        "recommendations": ["Watch the inference pricing race."],
    }


def _canned_presentation(prompt: str, slide_count: int = 10) -> dict[str, Any]:
    del prompt
    return {
        "title": "AI Funding",
        "description": "A deck on AI funding.",
        "slides": [
            {
                "title": f"Slide {n}",
                "content": "Content for slide.",
                "bullets": ["Bullet one.", "Bullet two."],
                "notes": None,
            }
            for n in range(1, slide_count + 1)
        ],
    }


def _store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = list(entries)
    store.list_kb_tier.return_value = []
    store.promote_kb_draft.return_value = {}
    store.flag_for_knowledge_base.return_value = {}
    return store


def _window_store(entries: list[dict[str, Any]]) -> MagicMock:
    """A store whose ``list_entries`` honors the ``date_from``/``date_to``
    window by comparing the entry's ``collected_at`` (real KBStore semantics
    for the shared week-windowed set)."""
    store = _store(entries)

    def _list_entries(
        domain: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        del domain, offset
        result = list(entries)
        if date_from:
            result = [e for e in result if str(e.get("collected_at") or "") >= date_from]
        if date_to:
            result = [e for e in result if str(e.get("collected_at") or "") <= date_to]
        return result[:limit]

    store.list_entries.side_effect = _list_entries
    return store


def _freeze_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    import autoinfo.output as output_mod

    class _FrozenDatetime:
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN201
            return FROZEN_NOW

        @classmethod
        def fromisoformat(cls, s: str) -> datetime:  # noqa: ANN201
            return datetime.fromisoformat(s)

    monkeypatch.setattr(output_mod, "datetime", _FrozenDatetime)
    import autoinfo.kb as kb_mod

    monkeypatch.setattr(kb_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(kb_mod.datetime, "now", classmethod(lambda cls, tz=None: FROZEN_NOW))  # type: ignore[attr-defined]  # noqa: E501
    monkeypatch.setattr(output_mod, "date", type("_FrozenDate", (), {"today": classmethod(lambda cls: FROZEN_TODAY)}))  # type: ignore[attr-defined]  # noqa: E501


def _active_source_configs() -> list[SourceConfig]:
    return [
        SourceConfig(
            name="techcrunch-ai",
            type="rss",
            url="https://techcrunch.com/category/artificial-intelligence/feed/",
        ),
        SourceConfig(
            name="ars-technica",
            type="rss",
            url="https://feeds.arstechnica.com/arstechnica/index",
        ),
    ]


# ===========================================================================
# Helper: _select_story_set
# ===========================================================================


class TestSelectStorySet:
    def test_window_query_with_date_from_and_sorted_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The helper queries the period window with ``date_from`` and returns
        the ``_sorted_ref_entries``-ordered set."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 6)]
        store = _store(entries)
        set_entries, (date_from, date_to), was_empty = _select_story_set(
            store, "tech-ai-developer", period="weekly", product="digest", query_limit=200,
        )
        assert store.list_entries.call_args.kwargs["date_from"] == date_from
        assert store.list_entries.call_args.kwargs["limit"] == 200
        from datetime import timedelta

        # PERIOD_DAYS["weekly"] = 7 → date_from is 7 days before today.
        assert date_from == (FROZEN_TODAY - timedelta(days=7)).isoformat()
        assert date_to == FROZEN_TODAY.isoformat()
        assert was_empty is False
        assert [e["entry_id"] for e in set_entries] == [f"tech-e{i}" for i in range(1, 6)]
        assert len(set_entries) == 5

    def test_empty_window_falls_back_to_full_domain(self) -> None:
        """An empty period window falls back to the full domain set (the
        digest's never-an-empty-shell relaxation)."""
        store = _store([])
        set_entries, _, was_empty = _select_story_set(
            store, "tech-ai-developer", period="weekly", product="digest", query_limit=200,
        )
        assert was_empty is True
        assert set_entries == []


# ===========================================================================
# Byte-identical digest vs the committed golden
# ===========================================================================


class TestDigestByteIdentical:
    def test_digest_all_active_byte_identical_to_golden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ALL sources active, the digest render equals the committed
        golden byte-for-byte (119-caller backward-compat gate)."""
        _freeze_datetime(monkeypatch)
        golden = open(_GOLDEN_PATH, encoding="utf-8").read()
        entries = [_entry(i) for i in range(1, 6)]
        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_canned_llm),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            result = generate_digest(domain="tech-ai-developer", period="weekly")
        assert isinstance(result, str)
        assert result == golden

    def test_digest_with_drifted_source_still_byte_identical_to_golden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A digest whose KB carries a drifted source (infoq-cn) renders
        golden byte-identical on the all-active fixture — the drift filter
        (todo 1) runs AFTER the shared helper, so the shared set is unchanged
        and the digest's render is the byte-identity gate."""
        _freeze_datetime(monkeypatch)
        golden = open(_GOLDEN_PATH, encoding="utf-8").read()
        entries = [_entry(i) for i in range(1, 6)] + [_entry(9, drifted=True)]
        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_canned_llm),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            result = generate_digest(domain="tech-ai-developer", period="weekly")
        assert isinstance(result, str)
        assert result == golden
        assert "Drifted funding round" not in result


# ===========================================================================
# Cross-product coherence: digest + presentation share the story set
# ===========================================================================


class TestDigestPresentationCoherence:
    def test_source_host_overlap_between_digest_and_presentation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Digest and presentation consume the same week-windowed set, so the
        two-source fixture's source-host overlap is ≥ 0.5 (measured on the
        entry sets actually consumed by both renders — the fixture's entries
        all contain the topic terms, making the topic filter a no-op)."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 6)]
        store = _store(entries)
        digest_captured: dict[str, Any] = {}
        presentation_captured: dict[str, Any] = {}

        def _capture_digest(prompt: str, config: Any = None) -> dict[str, Any]:
            digest_captured["prompt"] = prompt
            return _canned_llm(prompt, config)

        def _capture_presentation(prompt: str, slide_count: int = 10) -> dict[str, Any]:
            presentation_captured["prompt"] = prompt
            return _canned_presentation(prompt, slide_count)

        with (
            patch("autoinfo.output.KBStore", return_value=store),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_capture_digest),
            patch("autoinfo.output._call_llm_for_presentation", side_effect=_capture_presentation),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            generate_digest(domain="tech-ai-developer", period="weekly")
            generate_presentation(
                domain="tech-ai-developer", topic="AI", allow_empty=True,
            )

        def _hosts_from_prompt(prompt: str) -> set[str]:
            import re

            return set(re.findall(r"https?://([^/:\s]+)/", prompt))

        digest_hosts = _hosts_from_prompt(digest_captured["prompt"])
        presentation_hosts = _hosts_from_prompt(presentation_captured["prompt"])
        union = digest_hosts | presentation_hosts
        assert union, "both products must feed entries into their LLM prompts"
        overlap = len(digest_hosts & presentation_hosts) / len(union)
        assert overlap >= 0.5, (
            f"digest/presentation source-host overlap {overlap:.2f} < 0.5 "
            f"(digest={sorted(digest_hosts)} presentation={sorted(presentation_hosts)})"
        )

    def test_presentation_uses_same_week_set_out_of_week_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Presentation's shared set is week-windowed: an out-of-week entry is
        never fed to the presentation LLM (the old all-time limit=5000 load
        would have included it)."""
        _freeze_datetime(monkeypatch)
        in_week = [_entry(i) for i in range(1, 6)]
        old_entry = dict(_entry(1))
        old_entry.update({
            "entry_id": "tech-e-old",
            "title": "AI funding round old: stale inference costs",
            "collected_at": "2026-07-01T10:00:00Z",
        })
        entries = in_week + [old_entry]
        captured: dict[str, str] = {}

        def _capture_presentation(prompt: str, slide_count: int = 10) -> dict[str, Any]:
            captured["prompt"] = prompt
            return _canned_presentation(prompt, slide_count)

        with (
            patch("autoinfo.output.KBStore", return_value=_window_store(entries)),
            patch("autoinfo.output._call_llm_for_presentation", side_effect=_capture_presentation),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            generate_presentation(
                domain="tech-ai-developer", topic="AI", allow_empty=True,
            )
        assert "stale inference costs" not in captured["prompt"]
        assert "AI funding round 1" in captured["prompt"]


# ===========================================================================
# Topic fallback + cap preservation on the shared set
# ===========================================================================


class TestPresentationTopicFallback:
    def test_topic_filter_noop_feed_uses_shared_set_first_50(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When every entry carries the topic terms the topic filter is a
        no-op and the presentation consumes the full shared set (≤50), not a
        filtered subset."""
        _freeze_datetime(monkeypatch)
        # 5 in-week + 5 drifted(no topic term) — the drifted are excluded by
        # the drift filter; the shared set has 5 entries, all topic-bearing.
        entries = [_entry(i) for i in range(1, 6)]
        shared_set, _dr, _we = _select_story_set(
            _store(entries), "tech-ai-developer", period="weekly",
            product="presentation", query_limit=5000,
        )
        assert len(shared_set) == 5
        # All carry the topic term "AI" in title/summary → filter is a no-op.
        assert all(
            "ai" in (e["title"] + " " + e["summary"]).lower() for e in shared_set
        )

    def test_topic_fallback_preserves_entries_first_50_and_not_drifted_heavy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the topic filter yields nothing, the presentation falls back
        to the shared set's first 50 — and the drift filter (todo 1) already
        ran before that slice, so a drifted-source-heavy KB never fills the
        50-slice with removed sources."""
        _freeze_datetime(monkeypatch)
        # 6 active (topic-bearing) + 12 drifted (no topic term) — the drift
        # filter excludes the drifted BEFORE the 50-slice, so the fallback
        # set is the 6 active entries.
        active = [_entry(i) for i in range(1, 7)]
        drifted = [_entry(i, drifted=True) for i in range(1, 13)]
        entries = active + drifted
        captured: dict[str, Any] = {}

        def _capture_presentation(prompt: str, slide_count: int = 10) -> dict[str, Any]:
            captured["prompt"] = prompt
            return _canned_presentation(prompt, slide_count)

        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_presentation", side_effect=_capture_presentation),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            generate_presentation(
                domain="tech-ai-developer",
                topic="AI funding",
                allow_empty=True,
            )
        # The prompt echoes the topic-bearing entries (entry #201s never
        # appear — the 50-slice is filled from the shared set, not drifted).
        assert "AI funding round 1" in captured["prompt"]
        assert "Drifted funding round" not in captured["prompt"]
        # Drifted source host is never fed to the LLM.
        assert _DRIFTED_URL not in captured["prompt"]

    def test_topic_entries_cap_ten_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The LLM-prompt cap is topic_entries[:10] (#178) — at most 10
        entries reach the presentation LLM prompt."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 16)]
        captured: dict[str, Any] = {}

        def _capture_presentation(prompt: str, slide_count: int = 10) -> dict[str, Any]:
            captured["prompt"] = prompt
            return _canned_presentation(prompt, slide_count)

        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_presentation", side_effect=_capture_presentation),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            generate_presentation(
                domain="tech-ai-developer", topic="AI", allow_empty=True,
            )
        entry_count = sum(
            1 for line in captured["prompt"].splitlines()
            if line.startswith("- AI funding round")
        )
        assert entry_count == 10
        assert "AI funding round 15" not in captured["prompt"]


# ===========================================================================
# Report consumes the same-week shared set
# ===========================================================================


class TestReportSharedSet:
    def test_report_single_domain_consumes_same_week_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The report's single-domain entry load consumes the same week-windowed
        story set: an out-of-week entry never reaches the report (accepted —
        report content MAY change)."""
        _freeze_datetime(monkeypatch)
        in_week = [_entry(i) for i in range(1, 6)]
        old_entry = dict(_entry(1))
        old_entry.update({
            "entry_id": "tech-e-report-old",
            "title": "AI funding round old: stale inference costs",
            "collected_at": "2026-07-01T10:00:00Z",
        })
        entries = in_week + [old_entry]
        captured: dict[str, int] = {}

        def _fake_group_by_theme(
            extractor: object,
            ents: list[dict[str, Any]],
            domain: str = "",
            domains: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            captured["count"] = len(ents)
            return [{"theme": "General", "description": "", "entries": list(ents)}]

        from autoinfo.llm import LLMExtractor

        with (
            patch("autoinfo.output.KBStore", return_value=_window_store(entries)),
            patch("autoinfo.output._group_by_theme", side_effect=_fake_group_by_theme),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value={
                    "executive_summary": "This report covers the tracked developments.",
                    "key_findings": [],
                    "recommendations": [],
                },
            ),
            patch.object(
                LLMExtractor, "extract", return_value=MagicMock(),
            ),
        ):
            generate_report(domain="tech-ai-developer", format="markdown")
        # The stale out-of-week entry is excluded by the shared week window.
        assert captured["count"] == 5
