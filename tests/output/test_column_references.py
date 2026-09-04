"""Plan task 6 — the column template's missing ``## References`` section.

``column.md.j2`` line ~45 promises "full source list in References" but the
template never rendered a ``## References`` section — a dangling pointer to a
section that does not exist.  This locks the fix:

- A trailing ``## References`` section (after Reader Takeaways / Appendices,
  before the footer) renders the template-context ``references`` list using
  ``ref.title`` / ``ref.source_url`` / ``user_source_label(ref)`` — the same
  ref-dict shape the column render contexts already carry (report path:
  ``labeled_refs``; digest path: ``_normalize_digest_product_context``), and
  the same rendering idiom as ``report.md.j2``.
- With an empty ``references`` list the section renders the honest
  "No sources for this edition." empty-state (no KeyError, no crash).

Hermetic — renders the already-normalized flat context directly through the
``column`` ProductTemplate (mirrors ``test_column_digest_sections``); no
KBStore / LLM seams.
"""

from __future__ import annotations

from typing import Any

from autoinfo.output import PRODUCT_TEMPLATES, _normalize_digest_product_context


def _column_template() -> Any:
    """Return the ``column`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "column":
            return row["template"]
    raise AssertionError("column ProductTemplate row missing from PRODUCT_TEMPLATES")


def _render_column(flat: dict[str, Any]) -> str:
    """Render the flat column context through the column template directly."""
    rendered = _column_template().render("column", "md", flat)
    assert isinstance(rendered, str)
    return rendered


def _context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a digest-path context dict (mirrors test_column_digest_sections)."""
    return {
        "title": "Weekly Digest \u2014 medical-research",
        "domain": "medical-research",
        "period": "weekly",
        "period_label": "Weekly",
        "date_from": "2026-08-03",
        "date_to": "2026-08-10",
        "generated_at": "2026-08-10T00:00:00+00:00",
        "entries": entries,
        "llm_synthesis": {
            "executive_summary": (
                "This week's column covers IVF imaging and neuroplasticity "
                "studies."
            ),
            "key_findings": [],
            "recommendations": [],
        },
        "target_audience": "",
        "source_tier_badge": False,
    }


_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "title": "Time-lapse imaging improves IVF outcomes",
        "summary": "A prospective cohort reports improved live birth rates.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "source_type": "api",
        "source_platform": "pubmed",
        "relevance_score": 92.0,
        "tags": '["IVF"]',
        "tier": "01-Raw",
        "collected_at": "2026-08-09T10:00:00Z",
    },
    {
        "entry_id": "entry-002",
        "title": "Neuroplasticity peaks in early childhood",
        "summary": "Early experiences shape cortical plasticity windows.",
        "source_url": "https://www.nature.com/articles/s41586-026-09999-x",
        "source_type": "rss",
        "source_platform": "nature",
        "relevance_score": 78.0,
        "tags": '["neuroplasticity"]',
        "tier": "01-Raw",
        "collected_at": "2026-08-09T11:00:00Z",
    },
]


def _references_block(markdown: str) -> str:
    """Return the body of the ``## References`` section (to the next ``## ``
    heading or end of document)."""
    lines = markdown.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "## References"),
        -1,
    )
    assert start >= 0, "## References section not found in rendered markdown"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


class TestColumnReferencesSection:
    """The in-body "full source list in References" promise is backed by a
    real trailing ``## References`` section."""

    def test_references_section_renders_every_source_url(self) -> None:
        """A column context with references renders ``## References`` with
        each reference's source_url present."""
        flat = _normalize_digest_product_context(
            _context(_ENTRIES), "medical-research", product_family="column"
        )
        assert flat["references"], "hermetic setup: refs must exist"
        out = _render_column(flat)

        block = _references_block(out)
        for ref in flat["references"]:
            assert str(ref["source_url"]) in block, (
                f"source_url missing from References: {ref['source_url']!r}"
            )
            assert str(ref["title"]) in block, (
                f"ref title missing from References: {ref['title']!r}"
            )

    def test_references_section_positioned_before_footer(self) -> None:
        """The section trails Reader Takeaways/Appendices and precedes the
        footer, closing the line-45 dangling pointer."""
        flat = _normalize_digest_product_context(
            _context(_ENTRIES), "medical-research", product_family="column"
        )
        out = _render_column(flat)

        assert out.index("## Reader Takeaways") < out.index("## References")
        assert out.index("## References") < out.index("*Column ·")
        # The in-body promise still points at the (now real) section.
        assert "full source list in References" in out

    def test_empty_references_renders_graceful_no_sources(self) -> None:
        """Empty references → the "No sources for this edition." empty-state,
        no KeyError / crash."""
        flat = _normalize_digest_product_context(
            _context([]), "medical-research", product_family="column"
        )
        assert flat["references"] == []
        out = _render_column(flat)

        assert "No sources for this edition." in _references_block(out)
