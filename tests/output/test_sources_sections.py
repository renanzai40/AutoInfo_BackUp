"""Plan todo 8 (P0-2 provenance-by-default) — Sources/References sections
across the 8 product templates.

Every product family must ship a default source-provenance section rendered
purely from its existing render context (no LLM calls, no context-shape
restructure).  The per-family matrix (roadmap P0-2, corrected 2026-09-04):

- ``report`` / ``premium-briefing`` / ``enterprise-briefing`` / ``column``
  already carry a ``## References`` section — this test locks their presence
  and per-source_url rendering (regression guard: never regress to no-section).
- ``magazine-digest`` gains a ``## Sources`` section iterating the rendered
  entries (``entry.source_url`` + ``entry.source_label``), mirroring the
  digest.html.j2 entry-link style.
- ``tutorial`` upgrades its bare ``## Further Reading`` list to a structured
  ``## Sources`` section: a numbered KB ``references`` list (title +
  source_url, report-context shape) added to the tutorial render context,
  with the historical further-reading bullets retained under it.
- ``digest`` (md + html sibling formats) gains an aggregate ``## References``
  tail before the footer — inline per-entry citations stay, the tail lists
  every entry source_url in one deduplicated block.
- ``presentation`` keeps inline per-slide citations BY DESIGN (a slide deck
  aggregates no prose tail); the template carries a note documenting the
  decision, asserted here so the decision cannot silently regress.
- ``presentation.html`` intentionally has NO provenance section (plan
  decision: leave as-is).

Hermetic: renders flat/template contexts directly (no KBStore / LLM seams),
mirroring ``tests/output/test_column_references.py``.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    _get_jinja_env,
    _normalize_digest_product_context,
)

_ENTRY_URLS = [
    "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "https://www.nature.com/articles/s41586-026-09999-x",
    "https://time.com/climate-policy-week/",
]

_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": f"entry-{i:03d}",
        "title": f"Time-lapse imaging study {i}",
        "summary": f"A prospective cohort reports improved outcomes ({i}).",
        "source_url": url,
        "source_type": "api" if i % 2 else "rss",
        "source_platform": platform,
        "source_label": label,
        "relevance_score": 92.0 - i,
        "tags": '["IVF"]',
        "tier": "01-Raw",
        "collected_at": "2026-08-09T10:00:00Z",
        "domain": "medical-research",
    }
    for i, (url, platform, label) in enumerate(
        [
            (_ENTRY_URLS[0], "pubmed", "PubMed"),
            (_ENTRY_URLS[1], "nature", "Nature"),
            (_ENTRY_URLS[2], "time", "Time"),
        ],
        start=1,
    )
]

_REFS: list[dict[str, Any]] = [
    {
        "title": f"Time-lapse imaging study {i}",
        "source_url": url,
        "source_type": "api" if i % 2 else "rss",
        "source_platform": platform,
        "source_label": label,
        "domain": "medical-research",
        "description": f"A prospective cohort reports improved outcomes ({i}).",
    }
    for i, (url, platform, label) in enumerate(
        [
            (_ENTRY_URLS[0], "pubmed", "PubMed"),
            (_ENTRY_URLS[1], "nature", "Nature"),
            (_ENTRY_URLS[2], "time", "Time"),
        ],
        start=1,
    )
]


def _template(name: str) -> ProductTemplate:
    """Return the named ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return cast(ProductTemplate, row["template"])
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _render(family: str, variant: str, data: dict[str, Any]) -> str:
    rendered = _template(family).render(family, variant, data)
    assert isinstance(rendered, str)
    return rendered


def _digest_context() -> dict[str, Any]:
    """A digest-path context (nested llm_synthesis shape) for one domain."""
    return {
        "title": "Weekly Digest \u2014 medical-research",
        "domain": "medical-research",
        "period": "weekly",
        "period_label": "Weekly",
        "date_from": "2026-08-03",
        "date_to": "2026-08-10",
        "generated_at": "2026-08-10",
        "entries": _ENTRIES,
        "llm_synthesis": {
            "executive_summary": "IVF imaging and climate coverage led the week.",
            "key_findings": [],
            "recommendations": [],
        },
        "target_audience": "",
        "source_tier_badge": False,
    }


def _report_style_context() -> dict[str, Any]:
    """A flat report-path context (_report_data_to_dict shape)."""
    return {
        "title": "Weekly Report \u2014 medical-research",
        "domain": "medical-research",
        "generated_at": "2026-08-10",
        "collection_id": "",
        "executive_summary": "IVF imaging and climate coverage led the week.",
        "key_findings": [{"text": "Imaging improves outcomes.", "source_url": _ENTRY_URLS[0]}],
        "recommendations": ["Adopt time-lapse imaging."],
        "implications": [],
        "risks": [],
        "action_required": [],
        "key_metrics": [],
        "source_tier_badge": False,
        "entries": [
            {
                "title": ref["title"],
                "summary": "",
                "source_url": ref["source_url"],
                "source_type": ref["source_type"],
                "source_platform": ref["source_platform"],
                "source_label": ref["source_label"],
                "relevance_score": None,
                "collected_at": "",
            }
            for ref in _REFS
        ],
        "sections": [
            {
                "title": "Fertility research",
                "content": "Theme body text.",
                "entries": [
                    {
                        "title": ref["title"],
                        "summary": ref["description"],
                        "source_url": ref["source_url"],
                        "source_type": ref["source_type"],
                        "source_platform": ref["source_platform"],
                        "source_label": ref["source_label"],
                    }
                    for ref in _REFS
                ],
            }
        ],
        "references": _REFS,
        "appendices": [],
        "grouping_degradation_marker": "",
    }


def _assert_urls_in_section(markdown: str, heading: str, urls: list[str]) -> None:
    """Assert every URL renders inside the ``## <heading>`` section body."""
    lines = markdown.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == f"## {heading}"]
    assert starts, f"## {heading} section not found in rendered markdown"
    start = starts[-1]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    block = "\n".join(lines[start + 1 : end])
    for url in urls:
        assert url in block, f"source_url missing from ## {heading}: {url!r}"


# ===================================================================
# 1. Families that already carry References — regression guard
# ===================================================================


class TestReferencesBearingFamiliesUnchanged:
    """report / premium-briefing / enterprise-briefing / column keep their
    existing ``## References`` section — locked, never re-added, never lost."""

    @pytest.mark.parametrize(
        "family",
        ["report", "premium-briefing", "enterprise-briefing", "column"],
    )
    def test_references_section_present_with_every_source_url(
        self, family: str
    ) -> None:
        flat = _report_style_context()
        if family == "column":
            flat["references"] = _REFS
        out = _render(family, "md", flat)
        assert "## References" in out
        _assert_urls_in_section(out, "References", _ENTRY_URLS)


# ===================================================================
# 2. magazine-digest — new Sources section
# ===================================================================


class TestMagazineDigestSourcesSection:
    """magazine-digest.md.j2 renders ``## Sources`` iterating its entries."""

    def test_sources_section_lists_every_entry_url(self) -> None:
        flat = _normalize_digest_product_context(
            _digest_context(), "medical-research", product_family="magazine-digest"
        )
        out = _render("magazine-digest", "md", flat)

        assert "## Sources" in out
        for entry in flat["entries"]:
            assert str(entry["source_url"]) in out
        _assert_urls_in_section(out, "Sources", _ENTRY_URLS)

    def test_sources_section_before_footer(self) -> None:
        flat = _normalize_digest_product_context(
            _digest_context(), "medical-research", product_family="magazine-digest"
        )
        out = _render("magazine-digest", "md", flat)
        assert out.index("## Sources") < out.index("*Magazine Digest ·")

    def test_sources_entries_render_label_and_url_together(self) -> None:
        """Each source line pairs the user-facing label with its URL
        (digest.html.j2:254-265 link style — the label links the URL)."""
        flat = _normalize_digest_product_context(
            _digest_context(), "medical-research", product_family="magazine-digest"
        )
        out = _render("magazine-digest", "md", flat)
        # Every entry renders as a markdown link whose target is its URL.
        for entry in flat["entries"]:
            url = str(entry["source_url"])
            assert re.search(r"\[[^\]]+\]\(" + re.escape(url) + r"\)", out), (
                f"entry source not rendered as [label]({url})"
            )

    def test_empty_entries_renders_graceful_sources_section(self) -> None:
        flat = _normalize_digest_product_context(
            _digest_context() | {"entries": []},
            "medical-research",
            product_family="magazine-digest",
        )
        out = _render("magazine-digest", "md", flat)
        assert "## Sources" in out
        assert "No sources for this edition." in out


# ===================================================================
# 3. tutorial — Further Reading upgraded to structured Sources
# ===================================================================


def _tutorial_context() -> dict[str, Any]:
    """The tutorial render context as generate_tutorial builds it, plus the
    new KB-derived ``references`` list the upgraded section consumes."""
    return {
        "title": "Medical Research \u2014 Tutorial",
        "domain": "medical-research",
        "target_audience": "student",
        "collection_id": "",
        "duration": "3 minutes",
        "prerequisites": "None",
        "objectives": ["Understand time-lapse imaging."],
        "content": [
            {
                "heading": "Time-lapse imaging",
                "body": (
                    "Time-lapse imaging improves live birth rates. "
                    f"(Source: {_ENTRY_URLS[0]})"
                ),
                "code_example": None,
                "code_language": None,
                "key_takeaway": "Better outcomes with time-lapse.",
            }
        ],
        "exercises": [
            {"title": "Key finding", "description": "Summarize the main finding."}
        ],
        "summary": "Time-lapse imaging improves IVF outcomes.",
        "further_reading": _ENTRY_URLS[:2],
        "references": _REFS,
        "generated_at": "2026-08-10",
        "vocabulary": [],
        "grammar": [],
    }


class TestTutorialSourcesSection:
    """tutorial.md.j2 renders a structured ``## Sources`` section: the KB
    references list (numbered, title + source_url) plus the historical
    further-reading bullets retained under the same section."""

    def test_sources_section_lists_every_kb_source_url(self) -> None:
        out = _render("tutorial", "md", _tutorial_context())
        assert "## Sources" in out
        _assert_urls_in_section(out, "Sources", _ENTRY_URLS)

    def test_sources_section_keeps_further_reading_bullets(self) -> None:
        out = _render("tutorial", "md", _tutorial_context())
        fr_block = out.split("## Further Reading", 1)[1].split("## Sources", 1)[0]
        for url in _ENTRY_URLS[:2]:
            assert f"- {url}" in fr_block

    def test_sources_section_before_footer(self) -> None:
        out = _render("tutorial", "md", _tutorial_context())
        assert out.index("## Sources") < out.index("*Tutorial ·")

    def test_missing_references_key_renders_graceful(self) -> None:
        """A context without ``references`` (older callers) must not raise
        KeyError — the section renders its empty-state."""
        ctx = _tutorial_context()
        ctx.pop("references")
        out = _render("tutorial", "md", ctx)
        assert "## Sources" in out
        assert "No sources for this edition." in out


# ===================================================================
# 4. digest md + html — aggregate References tail
# ===================================================================


class TestDigestReferencesTail:
    """digest.md.j2 renders an aggregate ``## References`` tail before the
    footer (inline per-entry citations stay); digest.html.j2 mirrors it."""

    def test_digest_markdown_references_tail_before_footer(self) -> None:
        flat = _normalize_digest_product_context(
            _digest_context(), "medical-research", product_family="digest"
        )
        out = _render("digest", "md", flat)
        assert "## References" in out
        _assert_urls_in_section(out, "References", _ENTRY_URLS)
        assert out.index("## References") < out.rindex("*Digest ·")

    def test_digest_markdown_inline_citations_remain(self) -> None:
        """The per-entry ``[View Source](url)`` inline links are untouched."""
        flat = _normalize_digest_product_context(
            _digest_context(), "medical-research", product_family="digest"
        )
        out = _render("digest", "md", flat)
        assert "[View Source]" in out

    def test_digest_html_references_tail(self) -> None:
        """The html sibling carries the same aggregate References section,
        rendered in the digest.html.j2 entry-link style."""
        from autoinfo.output import _render_digest_html

        out = _render_digest_html(_digest_context())
        assert ">References</h2>" in out
        for url in _ENTRY_URLS:
            assert url in out
        # Tail sits before the footer marker.
        assert out.index("References</h2>") < out.index("footer class=\"digest-footer\"")

    def test_digest_markdown_empty_entries_renders_graceful(self) -> None:
        flat = _normalize_digest_product_context(
            _digest_context() | {"entries": []},
            "medical-research",
            product_family="digest",
        )
        out = _render("digest", "md", flat)
        assert "## References" in out
        assert "No sources for this edition." in out


# ===================================================================
# 5. presentation — inline by design, note locked
# ===================================================================


_PRESENTATION_CONTEXT: dict[str, Any] = {
    "title": "IVF Technology \u2014 Presentation",
    "topic": "IVF technology",
    "domain": "medical-research",
    "target_audience": "executive",
    "description": "Overview of IVF technology advancements.",
    "slides": [
        {
            "title": "Time-Lapse Imaging",
            "content": "Continuous embryo monitoring improves live birth rates.",
            "bullets": ["48.2% vs 39.5% live birth"],
            "source_url": _ENTRY_URLS[0],
            "notes": "Prepared from knowledge base sources.",
        },
        {
            "title": "AI Embryo Selection",
            "content": "AI models show promise but lack prospective validation.",
            "bullets": ["Systematic review"],
            "source_url": _ENTRY_URLS[1],
            "notes": "",
        },
    ],
    "generated_at": "2026-08-10",
}


class TestPresentationInlineByDesign:
    """Plan decision: the presentation keeps per-slide inline citations and
    does NOT gain an aggregated section; the template documents that decision."""

    def test_template_note_documents_inline_decision(self) -> None:
        from pathlib import Path

        tpl = (
            Path(__file__).resolve().parents[2]
            / "src" / "autoinfo" / "data" / "templates" / "presentation.md.j2"
        )
        content = tpl.read_text(encoding="utf-8")
        assert "Sources/References" in content
        assert "inline" in content

    def test_presentation_renders_inline_slide_sources(self) -> None:
        env = _get_jinja_env()
        rendered = env.get_template("presentation.md.j2").render(
            **_PRESENTATION_CONTEXT
        )
        assert "(Source: " in rendered
        for url in _ENTRY_URLS[:2]:
            assert url in rendered
        # No aggregated section leaked in.
        assert "## Sources" not in rendered
        assert "## References" not in rendered
