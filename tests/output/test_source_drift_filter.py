"""Selection-time source-drift filter (cross-product-coherence #119, todo 1).

C2 contract: product entry-load (digest + presentation) must exclude entries
whose source identity is absent from the domain's CURRENT config source list.
The source identity of an entry is derived as:

- HOST match: the entry's ``source_url`` host against each configured
  ``SourceConfig.url`` host via ``_host_matches_source`` (subdomain-aware —
  ``arxiv.org`` ⊂ ``rss.arxiv.org``), OR
- PLATFORM match: ``source_platform`` against ``SourceConfig.name``/``type``
  ONLY when the platform is non-generic.  Pre-#323 entries carry generic
  ``source_platform='rss'/'web'/'api'`` (``_GENERIC_PLATFORMS``) — they must
  NEVER be dropped via a "both host AND platform" test, and a generic platform
  alone must never exclude an entry whose host matches.

FAIL-OPEN contract: ``_get_domain_source_configs`` returns ``[]`` when the
config is missing/unreadable — the helper MUST return True (keep everything),
never drop everything.

RED→GREEN: these tests fail on pre-#119 code (no ``_is_source_active_in_config``
helper, no drift filter applied at the digest/presentation entry-load sites) and
pass after the fix.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import SourceConfig
from autoinfo.output import _is_source_active_in_config, generate_digest, generate_presentation

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

# A drifted source that is NOT in the ``tech-ai-developer`` config: infoq-cn
# (a real source for OTHER domains) — its host www.infoq.cn matches no
# configured source host, and its platform "infoq-cn" matches no configured
# source name/type.
_DRIFTED_URL = "https://www.infoq.cn/article/ai-funding-9"
_DRIFTED_PLATFORM = "infoq-cn"

# A generic-platform (pre-#323) entry whose host DOES match a configured source.
_GENERIC_URL = "https://arstechnica.com/ai/2026/08/generic-platform-entry"


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
    return {
        "entry_id": f"tech-e{i}",
        "title": f"AI funding round {i}: model inference costs fall",
        "summary": f"Startup {i} cut inference cost by 40% this week.",
        "domain": "tech-ai-developer",
        "tier": "01-Raw",
        "language": "en",
        "source_url": _URLS[i - 1],
        "source_type": "rss",
        "source_platform": _SOURCES[i - 1],
        "collected_at": f"2026-08-2{i}:10:00:00Z",
        "relevance_score": 90.0 - (i % 10),
        "tags": '["AI", "funding"]',
        "quality_tier": 1,
        "dedup_status": "unique",
        "file_path": "",
        "custom_fields": "{}",
    }


def _generic_platform_entry(i: int) -> dict[str, Any]:
    """A pre-#323 style entry: generic ``source_platform='rss'`` but its host
    (arstechnica.com) matches a configured source."""
    return {
        "entry_id": f"tech-e-generic-{i}",
        "title": f"AI funding generic platform entry {i}",
        "summary": f"Generic platform entry {i} about AI funding.",
        "domain": "tech-ai-developer",
        "tier": "01-Raw",
        "language": "en",
        "source_url": _GENERIC_URL,
        "source_type": "rss",
        "source_platform": "rss",
        "collected_at": f"2026-08-2{i}:10:00:00Z",
        "relevance_score": 80.0,
        "tags": '["AI"]',
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
# Helper: _is_source_active_in_config
# ===========================================================================


class TestIsSourceActiveInConfig:
    def test_host_match_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Host match (exact + subdomain-aware) → True."""
        monkeypatch.setattr(
            "autoinfo.output._get_domain_source_configs",
            lambda domain: _active_source_configs(),
        )
        assert _is_source_active_in_config(_entry(1), "tech-ai-developer") is True
        # arstechnica.com article vs feeds.arstechnica.com feed — subdomain match
        assert _is_source_active_in_config(_entry(4), "tech-ai-developer") is True

    def test_host_mismatch_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drifted host + non-generic platform absent from config → False."""
        monkeypatch.setattr(
            "autoinfo.output._get_domain_source_configs",
            lambda domain: _active_source_configs(),
        )
        assert _is_source_active_in_config(_entry(9, drifted=True), "tech-ai-developer") is False

    def test_non_generic_platform_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-generic platform matches a configured source name → True even
        when the host does not match (feed-host mismatch)."""
        configs = [
            SourceConfig(
                name="infoq-cn",
                type="rss",
                url="https://www.infoq.cn/feed",
            )
        ]
        monkeypatch.setattr(
            "autoinfo.output._get_domain_source_configs", lambda domain: configs
        )
        assert _is_source_active_in_config(_entry(9, drifted=True), "tech-ai-developer") is True

    def test_generic_platform_not_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generic ``source_platform='rss'`` with a matching host → True
        (pre-#323 entries are never dropped by a generic platform)."""
        monkeypatch.setattr(
            "autoinfo.output._get_domain_source_configs",
            lambda domain: _active_source_configs(),
        )
        assert _is_source_active_in_config(_generic_platform_entry(1), "tech-ai-developer") is True

    def test_fail_open_empty_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FAIL-OPEN: unreadable/missing config returns ``[]`` → helper keeps
        EVERYTHING (never drops all entries)."""
        monkeypatch.setattr(
            "autoinfo.output._get_domain_source_configs", lambda domain: []
        )
        assert _is_source_active_in_config(_entry(9, drifted=True), "tech-ai-developer") is True
        assert _is_source_active_in_config(_entry(1), "tech-ai-developer") is True


# ===========================================================================
# Digest drift filter
# ===========================================================================


class TestDigestDriftFilter:
    def test_digest_excludes_drifted_entries(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A drifted source (infoq-cn — host + platform absent from the
        tech-ai-developer config) is excluded from the rendered digest, and the
        exclusion is logged with the source name + count."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 6)] + [_entry(9, drifted=True)]
        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_canned_llm),
            patch(
                "autoinfo.output._get_domain_source_configs",
                lambda domain: _active_source_configs(),
            ),
        ):
            with caplog.at_level("INFO", logger="autoinfo.output"):
                result = generate_digest(domain="tech-ai-developer", period="weekly")
        assert isinstance(result, str)
        assert "Drifted funding round" not in result
        assert _DRIFTED_URL not in result
        # Active entries survive.
        assert "AI funding round 1" in result
        assert "AI funding round 5" in result
        # Drift exclusion is logged with the source name + count.
        assert any(
            "Excluded 1 drifted entry" in msg and "infoq-cn" in msg
            for msg in caplog.messages
        ), "drift exclusion must be logged with source name + count"

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

    def test_digest_generic_platform_entry_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pre-#323 entry with generic ``source_platform='rss'`` whose host
        matches a configured source is NOT dropped."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 5)] + [_generic_platform_entry(1)]
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
        assert "AI funding generic platform entry" in result

    def test_digest_fail_open_unreadable_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAIL-OPEN: an unreadable config (→ ``[]`` from
        ``_get_domain_source_configs``) excludes NOTHING — even a drifted
        entry survives."""
        _freeze_datetime(monkeypatch)
        entries = [_entry(i) for i in range(1, 6)] + [_entry(9, drifted=True)]
        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_canned_llm),
            patch(
                "autoinfo.output._get_domain_source_configs", lambda domain: []
            ),
        ):
            result = generate_digest(domain="tech-ai-developer", period="weekly")
        assert isinstance(result, str)
        assert "Drifted funding round" in result


# ===========================================================================
# Presentation drift filter
# ===========================================================================


class TestPresentationDriftFilter:
    def _render_with_capture(
        self,
        monkeypatch: pytest.MonkeyPatch,
        entries: list[dict[str, Any]],
        source_configs_fn: Any,
    ) -> tuple[str, str]:
        """Render a presentation, capturing the LLM prompt so we can assert
        which entries reached the synthesis input (the rendered slides are
        canned and do not echo entry titles)."""
        _freeze_datetime(monkeypatch)
        captured: dict[str, str] = {}

        def _capturing_llm(prompt: str, slide_count: int = 10) -> dict[str, Any]:
            captured["prompt"] = prompt
            return _canned_presentation(prompt, slide_count)

        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch(
                "autoinfo.output._call_llm_for_presentation",
                side_effect=_capturing_llm,
            ),
            patch(
                "autoinfo.output._get_domain_source_configs",
                source_configs_fn,
            ),
        ):
            result = generate_presentation(
                domain="tech-ai-developer",
                topic="AI funding",
                allow_empty=True,
            )
        assert isinstance(result, str)
        return result, captured["prompt"]

    def test_presentation_excludes_drifted_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A drifted source is excluded from the presentation's topic-entries
        input, so it never reaches the LLM prompt nor the KB-derived slides."""
        entries = [_entry(i) for i in range(1, 5)] + [_entry(9, drifted=True)]
        result, prompt = self._render_with_capture(
            monkeypatch, entries, lambda domain: _active_source_configs()
        )
        assert "Drifted funding round" not in prompt
        assert _DRIFTED_URL not in prompt
        assert "Slide 1" in result

    def test_presentation_generic_platform_entry_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Generic-platform entry with a matching host survives in the
        presentation topic-entries input."""
        entries = [_entry(i) for i in range(1, 4)] + [_generic_platform_entry(1)]
        _, prompt = self._render_with_capture(
            monkeypatch, entries, lambda domain: _active_source_configs()
        )
        assert "AI funding generic platform entry" in prompt

    def test_presentation_fail_open_unreadable_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAIL-OPEN: unreadable config excludes nothing — the drifted entry
        is still available as topic-entries input."""
        entries = [_entry(i) for i in range(1, 4)] + [_entry(9, drifted=True)]
        _, prompt = self._render_with_capture(
            monkeypatch, entries, lambda domain: []
        )
        assert "Drifted funding round 9" in prompt
        assert _DRIFTED_URL in prompt
