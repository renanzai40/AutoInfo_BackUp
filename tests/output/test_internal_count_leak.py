"""Internal count / entry-ID leak tests (backup issue #77).

End products must not expose KB internals: the digest header count, the
enterprise Scope coverage counts (reworded to user-facing language), and
LLM-echoed "Source: Entry N" placeholders.  Acceptance scan pattern:
``Total entries|Entry [0-9]+|selected [0-9]+ of [0-9]+|N key findings.*references``.
"""

from __future__ import annotations

import re

from autoinfo.output import (
    _DIGEST_ENTERPRISE_METRICS_FIELDS,
    _strip_entry_placeholders,
)


def _render_template(name: str, context: dict[str, object]) -> str:
    from autoinfo.output import _get_jinja_env

    return _get_jinja_env().get_template(name).render(**context)


_DIGEST_CONTEXT: dict[str, object] = {
    "title": "Weekly Digest",
    "domain": "b2b",
    "period_label": "Weekly",
    "date_from": "2026-08-21",
    "date_to": "2026-08-28",
    "generated_at": "2026-08-28T00:00:00+00:00",
    "entries": [
        {
            "title": "Startup funding round",
            "summary": "Series A for an AI firm",
            "source_url": "https://example.com/1",
            "source_label": "example",
            "collected_at": "2026-08-25T00:00:00+00:00",
            "relevance_score": 50.0,
        }
        for _ in range(3)
    ],
}


class TestDigestTemplateNoInternalCount:
    def test_no_total_entries_line(self) -> None:
        out = _render_template("digest.md.j2", _DIGEST_CONTEXT)
        assert "Total entries" not in out

    def test_no_entry_number_leak(self) -> None:
        out = _render_template("digest.md.j2", _DIGEST_CONTEXT)
        assert not re.search(r"Entry \d+", out)

    def test_acceptance_scan_clean(self) -> None:
        out = _render_template("digest.md.j2", _DIGEST_CONTEXT)
        assert not re.search(
            r"Total entries|Entry [0-9]+|selected [0-9]+ of [0-9]+|"
            r"\d+ key findings.*references",
            out,
        )


_ENTERPRISE_CONTEXT: dict[str, object] = {
    "title": "Enterprise Briefing",
    "domain": "medical-research",
    "period_label": "Weekly",
    "date_from": "2026-08-21",
    "date_to": "2026-08-28",
    "generated_at": "2026-08-28T00:00:00+00:00",
    "executive_summary": "Summary.",
    "key_findings": [{"topic": f"Finding {i}", "detail": "Detail"} for i in range(9)],
    "key_metrics": [{"metric": "m", "value": "v", "source": "example"}],
    "action_required": ["Action"],
    "recommendations": ["Rec"],
    "risks": [],
    "references": [
        {
            "title": f"Ref {i}",
            "source_url": f"https://example.com/r{i}",
            "source_platform": "example",
        }
        for i in range(20)
    ],
}


class TestEnterpriseScopeUserWording:
    def test_scope_uses_user_language_not_internal_counts(self) -> None:
        out = _render_template("enterprise-briefing.md.j2", _ENTERPRISE_CONTEXT)
        assert "In this briefing" in out
        assert "key findings selected" not in out
        assert "source references" not in out
        assert "9 key points · drawn from 20 sources" in out

    def test_acceptance_scan_clean(self) -> None:
        out = _render_template("enterprise-briefing.md.j2", _ENTERPRISE_CONTEXT)
        assert not re.search(
            r"Total entries|Entry [0-9]+|selected [0-9]+ of [0-9]+|"
            r"\d+ key findings.*references",
            out,
        )


class TestStripEntryPlaceholders:
    def test_strips_entry_n_source(self) -> None:
        assert _strip_entry_placeholders(
            "| Metric | Value | Source |\n| x | 1 | Source: Entry 1/16/29 |"
        ) == "| Metric | Value | Source |\n| x | 1 | Source: (source) |"

    def test_leaves_real_sources_untouched(self) -> None:
        out = _strip_entry_placeholders("(Source: https://pubmed.ncbi.nlm.nih.gov/123/)")
        assert "https://pubmed.ncbi.nlm.nih.gov/123/" in out

    def test_prompt_no_longer_uses_entry_placeholder(self) -> None:
        joined = " ".join(_DIGEST_ENTERPRISE_METRICS_FIELDS)
        assert "Entry/study/dataset" not in joined
        assert "never placeholder text like Entry N" in joined


class TestNoInternalFieldTable:
    """Issue #91 (R2-wide): the digest/magazine/report products must not
    render the internal KB metadata table (Field|Value / Type / Collected /
    Relevance N/100 / Tags) or raw internal platform ids in References."""

    _LEAK_RE = re.compile(
        r"Field \| Value|Type rss|Collected|Relevance [0-9.]+/100|Tags\["
    )

    def _entry(self, platform: str = "npr-news") -> dict[str, object]:
        return {
            "title": "Test entry",
            "summary": "Summary.",
            "source_label": "NPR",
            "source_platform": platform,
            "source_type": "rss",
            "collected_at": "2026-08-25T00:00:00+00:00",
            "relevance_score": 50.0,
            "tags": '["ai"]',
            "source_url": "https://www.npr.org/article/1",
        }

    def test_digest_no_field_table(self) -> None:
        out = _render_template("digest.md.j2", {
            **_DIGEST_CONTEXT,
            "entries": [self._entry()],
        })
        assert self._LEAK_RE.search(out) is None, f"leak in digest:\n{out}"

    def test_magazine_no_relevance_byline(self) -> None:
        out = _render_template("magazine-digest.md.j2", {
            **_DIGEST_CONTEXT,
            "entries": [self._entry()],
        })
        assert self._LEAK_RE.search(out) is None, f"leak in magazine:\n{out}"
        assert "npr-news" not in out

    def test_report_references_no_internal_platform(self) -> None:
        ref = {
            "title": "Ref",
            "source_url": "https://www.npr.org/article/1",
            "source_label": "NPR",
            "source_platform": "npr-news",
        }
        out = _render_template("report.md.j2", {
            "title": "R", "domain": "d", "generated_at": "g",
            "sections": [], "references": [ref],
        })
        assert "npr-news" not in out
        assert "NPR" in out
