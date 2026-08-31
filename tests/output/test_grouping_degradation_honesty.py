"""Todo 4 — honest degradation annotation + structured log (#120, C4).

When the grouping degrades on a silent-hop path — (a) LLM fail/timeout →
``_deterministic_grouping`` fallback, (b) the #106 chaos guard → deterministic
fallback, (c) the 0/1-group "General" catch-all, (d) entry-level column
sections — the rendered product must carry the pinned honesty marker
``> *Grouped by source \u2014 not semantic topics*`` at the top of the section
list, AND a structured ``event="grouping_degraded"`` warning with the correct
``reason`` / ``grouping``.  On semantic-success the marker must be ABSENT.

Products covered: report, digest (column product template), column
(``report_type="column"``-equivalent via the column digest — the entry-level
path is reachable only there, note the deviation from the literal plan
wording: ``generate_report(report_type="column")`` renders through
``_render_report_template`` and never reaches ``_deterministic_column_sections``,
which is a digest-path-only seam).

RED→GREEN: these tests fail on pre-todo-4 code (no marker helper, no
``event="grouping_degraded"`` log, no marker injection in report/digest/column).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    _group_by_theme,
)

# The pinned marker string — asserted byte-for-byte.
MARKER = "> *Grouped by source \u2014 not semantic topics*"

_SOURCE_TYPES = ("rss", "api", "web")


def _entry(i: int) -> dict[str, Any]:
    return {
        "entry_id": f"e{i}",
        "title": f"AI funding round {i}",
        "summary": f"Startup {i} raised $20M.",
        "source_url": f"https://techcrunch.com/{i}",
        "source_type": _SOURCE_TYPES[i % len(_SOURCE_TYPES)],
        "source_platform": "techcrunch",
        "domain": "ai-commercial",
        "relevance_score": 90.0 - (i % 10),
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    }


def _store(entries: list[dict[str, Any]]) -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = list(entries)
    store.list_kb_tier.return_value = []
    store.promote_kb_draft.return_value = {}
    store.flag_for_knowledge_base.return_value = {}
    return store


def _stub_summary() -> dict[str, Any]:
    return {
        "executive_summary": "This report covers the tracked developments.",
        "key_findings": [],
        "recommendations": [],
    }


def _column_template() -> Any:
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "column":
            return row["template"]
    raise AssertionError("column ProductTemplate row missing from PRODUCT_TEMPLATES")


def _column_entries(n: int) -> list[dict[str, Any]]:
    """Column-digest fixture: enough entries that entry-level sections render
    (the deterministic theme grouping yields < 8 sections on this shape, so
    the entry-level fallback fires)."""
    return [
        {
            "entry_id": f"entry-{i:03d}",
            "title": f"Research finding {i} on IVF time-lapse imaging",
            "language": "en",
            "summary": (
                f"Study {i} reports improved live birth rates with time-lapse "
                "imaging in a prospective cohort."
            ),
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{10000000 + i}/",
            "source_type": "api",
            "source_platform": "pubmed",
            "relevance_score": 90.0 - i,
            "tags": '["IVF", "embryo"]',
            "tier": "01-Raw",
            "collected_at": (date.today() - timedelta(days=1)).isoformat(),
        }
        for i in range(1, n + 1)
    ]


def _column_synthesis() -> dict[str, Any]:
    return {
        "executive_summary": "This week's column covers ten studies on IVF.",
        "key_findings": [
            {"topic": "Time-lapse imaging", "detail": "Live birth rates improved."},
        ],
        "trends": ["Time-lapse imaging adoption"],
        "recommendations": ["Consider time-lapse imaging as standard of care."],
    }


def _column_synthesis_with_sections() -> dict[str, Any]:
    return {
        **_column_synthesis(),
        "sections": [
            {
                "title": f"Deep dive subsection {i}",
                "content": (
                    f"Analysis of study {i}: time-lapse imaging improved live "
                    "birth rates by 8.7 percentage points in the 2026 cohort."
                ),
            }
            for i in range(1, 9)
        ],
    }


def _render_column_digest(
    entries: list[dict[str, Any]], synthesis: dict[str, Any]
) -> str:
    """Render a column digest through generate_digest with the column product
    template (the digest-path entry-level column seam)."""
    from autoinfo.output import generate_digest

    with (
        patch("autoinfo.output.KBStore", return_value=_store(entries)),
        patch("autoinfo.output._call_llm_for_digest", return_value=synthesis),
    ):
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            product_template=_column_template(),
        )
    assert isinstance(result, str)
    return result


def _render_report_faulted(entries: list[dict[str, Any]]) -> str:
    """Render a report with ``group:fail`` fault injection, forcing the
    deterministic fallback and its degradation marker."""
    from autoinfo.output import generate_report

    old = os.environ.get("AUTOINFO_FAULT_INJECT")
    os.environ["AUTOINFO_FAULT_INJECT"] = "group:fail"
    try:
        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch(
                "autoinfo.output._generate_executive_summary",
                return_value=_stub_summary(),
            ),
        ):
            result = generate_report(domain="ai-commercial")
    finally:
        if old is None:
            os.environ.pop("AUTOINFO_FAULT_INJECT", None)
        else:
            os.environ["AUTOINFO_FAULT_INJECT"] = old
    assert isinstance(result, str)
    return result


# ---------------------------------------------------------------------------
# marker-on-fail
# ---------------------------------------------------------------------------


class TestReportMarkerOnFail:
    def test_marker_on_fail_report(self, caplog: Any) -> None:
        """``group:fail`` → deterministic fallback → the report renders the
        pinned marker at the top of the section list."""
        entries = [_entry(i) for i in range(1, 4)]
        with caplog.at_level("WARNING", logger="autoinfo.output"):
            report = _render_report_faulted(entries)

        assert MARKER in report
        # Marker sits at the TOP of the section list (right after "## Sections",
        # before any "### " section heading).
        sections_idx = report.index("## Sections")
        marker_idx = report.index(MARKER)
        first_section = report.index("### ", sections_idx)
        assert sections_idx < marker_idx < first_section, (
            "marker must lead the section list"
        )

    def test_marker_reason_log_report(self, caplog: Any) -> None:
        """The degraded report emits ``event="grouping_degraded"`` with a
        degradation reason (llm_failure for the fault-inject path)."""
        entries = [_entry(i) for i in range(1, 4)]
        with caplog.at_level("WARNING", logger="autoinfo.output"):
            _render_report_faulted(entries)

        events = [
            r for r in caplog.records
            if getattr(r, "message", "").startswith("grouping_degraded")
        ]
        assert events, "no grouping_degraded log record"
        assert any(
            'reason=\'llm_failure\'' in r.message for r in events
        ), "expected llm_failure reason on the fault-inject report path"


class TestDigestMarkerOnFail:
    def test_marker_on_fail_digest(self, caplog: Any) -> None:
        """Column digest with no synthesis sections → deterministic entry-level
        column sections → the rendered Deep Dive carries the pinned marker."""
        entries = _column_entries(10)
        with caplog.at_level("WARNING", logger="autoinfo.output"):
            out = _render_column_digest(entries, _column_synthesis())

        assert MARKER in out
        deep_dive_idx = out.index("## Deep Dive")
        marker_idx = out.index(MARKER)
        assert deep_dive_idx < marker_idx, (
            "marker must appear inside the Deep Dive"
        )

    def test_marker_reason_log_digest(self, caplog: Any) -> None:
        """The column-digest entry-level path logs ``event="grouping_degraded"``
        with reason ``entry_level``."""
        entries = _column_entries(10)
        with caplog.at_level("WARNING", logger="autoinfo.output"):
            _render_column_digest(entries, _column_synthesis())

        assert any(
            getattr(r, "message", "").startswith("grouping_degraded")
            and "reason='entry_level'" in r.message
            and "grouping='entry_level'" in r.message
            for r in caplog.records
        ), "column digest entry_level degradation not logged with reason entry_level"


class TestColumnMarkerOnFail:
    def test_marker_on_fail_column_via_fault_inject(self, caplog: Any) -> None:
        """`report_type='column'`-equivalent: the column product template
        renders the pinned marker + the ``entry_level`` degradation log.

        The entry-level path (`_deterministic_column_sections`) is reachable
        only through the digest path with the column template — a
        `generate_report(report_type='column')` renders through
        `_render_report_template` and never calls it.  So this test drives the
        column product template through `generate_digest`, which is exactly
        the seam the plan's `_deterministic_column_sections` (:4790) note names.
        """
        entries = _column_entries(10)
        with caplog.at_level("WARNING", logger="autoinfo.output"):
            out = _render_column_digest(entries, _column_synthesis())

        assert MARKER in out
        assert any(
            getattr(r, "message", "").startswith("grouping_degraded")
            and "reason='entry_level'" in r.message
            for r in caplog.records
        ), "column entry_level degradation not logged"


# ---------------------------------------------------------------------------
# marker-on-chaos / marker-on-no-groups (grouping-level)
# ---------------------------------------------------------------------------


class TestGroupingLevelMarkers:
    def test_marker_on_chaos(self, caplog: Any) -> None:
        """>20-theme burst → chaos guard → deterministic fallback → degraded
        flag set + `reason='chaos'` logged."""
        entries = [_entry(i) for i in range(1, 26)]
        chaos = [
            {"theme": f"Chaos-Theme-{i}", "description": "", "entries": [entries[i - 1]]}
            for i in range(1, 26)
        ]
        with (
            patch("autoinfo.output._run_grouping_batches", return_value=chaos),
            patch("autoinfo.output.fault_inject.maybe_fault"),
            caplog.at_level("WARNING", logger="autoinfo.output"),
        ):
            result = _group_by_theme(MagicMock(), entries, domain="ai-commercial")

        assert not any(g["theme"].startswith("Chaos-Theme-") for g in result)
        assert any(
            getattr(r, "message", "").startswith("grouping_degraded")
            and "reason='chaos'" in r.message
            for r in caplog.records
        ), "chaos degradation not logged with reason chaos"
        from autoinfo.output import _grouping_degraded as flag

        assert flag, "chaos path must set the degradation flag"

    def test_marker_on_no_groups_general(self, caplog: Any) -> None:
        """0-group LLM result → single 'General' catch-all → degraded flag set
        + `reason='no_groups'`, `grouping='general'` logged."""
        entries = [
            {
                "entry_id": f"e{i}",
                "title": f"Title {i}",
                "summary": f"Summary {i}",
                "source_url": f"https://x.com/{i}",
                "source_type": "rss",
                "source_platform": "x",
                "domain": "d",
            }
            for i in range(1, 4)
        ]
        with (
            patch("autoinfo.output._llm_group_batch", return_value=None),
            patch("autoinfo.output.fault_inject.maybe_fault"),
            caplog.at_level("WARNING", logger="autoinfo.output"),
        ):
            result = _group_by_theme(MagicMock(), entries, domain="d")

        assert [g["theme"] for g in result] == ["General"]
        assert any(
            getattr(r, "message", "").startswith("grouping_degraded")
            and "reason='no_groups'" in r.message
            and "grouping='general'" in r.message
            for r in caplog.records
        ), "no-groups General collapse not logged with reason no_groups"

    def test_marker_reason_llm_failure_source_type(self, caplog: Any) -> None:
        """LLM returns no groups on a multi-source batch → deterministic
        source_type fallback → `reason='llm_failure'`, `grouping='source_type'`."""
        entries = [
            {
                "entry_id": f"e{i}",
                "title": f"Title {i}",
                "summary": f"Summary {i}",
                "source_url": f"https://x.com/{i}",
                "source_type": st,
                "source_platform": "x",
                "domain": "d",
            }
            for i, st in enumerate(["rss", "api"])
        ]
        with (
            patch("autoinfo.output._llm_group_batch", return_value=None),
            patch("autoinfo.output.fault_inject.maybe_fault"),
            caplog.at_level("WARNING", logger="autoinfo.output"),
        ):
            _group_by_theme(MagicMock(), entries, domain="d")

        assert any(
            getattr(r, "message", "").startswith("grouping_degraded")
            and "reason='llm_failure'" in r.message
            and "grouping='source_type'" in r.message
            for r in caplog.records
        ), "llm_failure source_type degradation not logged"


# ---------------------------------------------------------------------------
# marker-ABSENT on success
# ---------------------------------------------------------------------------


class TestMarkerAbsentOnSuccess:
    def test_report_success_no_marker(self) -> None:
        """LLM grouping succeeds (2 semantic themes) → no marker in the report."""
        from tests.output.test_report import _make_grouping_result, _make_summary_result

        entries = [
            {
                "entry_id": "entry-001",
                "title": "Improved IVF outcomes with time-lapse imaging",
                "summary": "Time-lapse imaging improves live birth rates in IVF.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "source_type": "api",
                "source_platform": "pubmed",
                "relevance_score": 92.0,
                "tags": '["IVF", "embryo"]',
                "tier": "01-Raw",
                "collected_at": "2026-07-15T10:00:00Z",
            },
            {
                "entry_id": "entry-002",
                "title": "Neuroplasticity in early childhood development",
                "summary": "Early childhood experiences shape brain plasticity.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
                "source_type": "rss",
                "source_platform": "feed",
                "relevance_score": 78.0,
                "tags": '["neuroplasticity", "development"]',
                "tier": "01-Raw",
                "collected_at": "2026-07-16T10:00:00Z",
            },
            {
                "entry_id": "entry-003",
                "title": "Synaptic pruning mechanisms in adolescents",
                "summary": "Adolescent brain undergoes significant synaptic pruning.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654322/",
                "source_type": "api",
                "source_platform": "pubmed",
                "relevance_score": 85.0,
                "tags": '["neuroplasticity", "adolescent"]',
                "tier": "01-Raw",
                "collected_at": "2026-07-17T10:00:00Z",
            },
        ]
        from autoinfo.llm import LLMExtractor

        mock_extract = MagicMock(
            side_effect=[_make_grouping_result(), _make_summary_result()]
        )
        from autoinfo.output import generate_report

        with (
            patch("autoinfo.output.KBStore", return_value=_store(entries)),
            patch.object(LLMExtractor, "extract", mock_extract),
            patch("autoinfo.output._call_llm_for_report_synthesis", return_value=""),
            patch("autoinfo.output.fault_inject.maybe_fault"),
        ):
            report = generate_report(domain="medical-research")
        assert isinstance(report, str)
        assert MARKER not in report
        assert "Grouped by source" not in report

    def test_digest_success_no_marker(self) -> None:
        """Column digest with synthesis sections → no deterministic fallback →
        no marker."""
        out = _render_column_digest(
            _column_entries(10), _column_synthesis_with_sections()
        )
        assert MARKER not in out
        assert "Grouped by source" not in out

    def test_column_success_no_marker(self) -> None:
        """Column digest with synthesis sections (semantic Deep Dive) → no
        marker anywhere in the rendered column."""
        out = _render_column_digest(
            _column_entries(10), _column_synthesis_with_sections()
        )
        assert "Grouped by source" not in out
        assert MARKER not in out
