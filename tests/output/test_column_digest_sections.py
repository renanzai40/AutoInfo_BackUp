"""Tests for issue #316 — column digest Deep Dive sections + Sections metadata.

The ``column`` product template (``column.md.j2``) renders a Deep Dive from
``sections`` (list of ``{title, content, entries}``) and prints
``**Sections**: {{ sections|length }}``.  Before #316 the digest path never
materialized ``sections`` — ``_normalize_digest_product_context`` flattened
executive_summary / key_findings / recommendations / references but NOT
``sections`` — so a column digest rendered ``_No deep-dive sections available
for this column._`` with ``**Sections**: 0`` even when entries existed.

Covers:

- ``generate_digest(product_template=column)`` with a synthesis carrying a
  ``sections`` array renders ``## Deep Dive`` with >= 8 ``### `` subsections,
  each with substantive content, and ``**Sections**: N`` matching the actual
  count (never the empty placeholder).
- The deterministic fallback: when the synthesis carries no usable
  ``sections`` but entries exist, sections are derived from the entries so
  the template never renders the empty placeholder.
- ``_build_digest_llm_prompt(product_family="column")`` requests the
  ``sections`` array (8-10 subsections).
- ``_normalize_digest_product_context`` flattens ``sections`` and defaults
  to ``[]`` when absent (non-column families unchanged).
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    _build_digest_llm_prompt,
    _normalize_digest_product_context,
    generate_digest,
)

# ===================================================================
# Sample data
# ===================================================================

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": f"entry-{i:03d}",
        "title": f"Research finding {i} on IVF time-lapse imaging",
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
        "collected_at": "2026-07-15T10:00:00Z",
    }
    for i in range(1, 11)
]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's column covers ten studies on IVF time-lapse imaging."
    ),
    "key_findings": [
        {"topic": "Time-lapse imaging", "detail": "Live birth rates improved."},
    ],
    "trends": ["Time-lapse imaging adoption"],
    "recommendations": ["Consider time-lapse imaging as standard of care."],
}

_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS: dict[str, Any] = {
    **_SAMPLE_LLM_SYNTHESIS,
    "sections": [
        {
            "title": f"Deep dive subsection {i}",
            "content": (
                f"Analysis of study {i}: time-lapse imaging improved live "
                "birth rates by 8.7 percentage points (48.2% vs 39.5%) in "
                "the 2026 cohort, a statistically significant gain."
            ),
        }
        for i in range(1, 9)
    ],
}


def _column_template() -> Any:
    """Return the ``column`` ProductTemplate row from the registry."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "column":
            return row["template"]
    raise AssertionError("column ProductTemplate row missing from PRODUCT_TEMPLATES")


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Return sample entries for any domain (mirrors test_digest helper)."""
    return _SAMPLE_ENTRIES


def _render_column_digest(synthesis: dict[str, Any]) -> str:
    """Render a column digest through generate_digest with the shared mocks."""
    with (
        patch("autoinfo.output.KBStore") as mock_kb_cls,
        patch("autoinfo.output._call_llm_for_digest") as mock_llm,
    ):
        mock_llm.return_value = synthesis
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb_cls.return_value = mock_store
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format="markdown",
            product_template=_column_template(),
        )
    assert isinstance(result, str)
    return result


def _deep_dive_subsections(markdown: str) -> list[str]:
    """Return the ``### `` subsection headings in the Deep Dive."""
    return [ln for ln in markdown.splitlines() if ln.startswith("### ")]


def _render_column_template(flat: dict[str, Any]) -> str:
    """Render the flat column context through the column template directly.

    Hermetic — no KBStore / LLM seams (the context is already normalized).
    Mirrors ``generate_digest(product_template=column)``'s render site:
    ``product_template.render("column", "md", pt_context)``.
    """
    rendered = _column_template().render("column", "md", flat)
    assert isinstance(rendered, str)
    return rendered


def _column_context(
    synthesis: dict[str, Any], entries: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build a digest-path context dict (mirrors ``TestColumnNormalizeSections``)."""
    return {
        "title": "Weekly Digest \u2014 medical-research",
        "domain": "medical-research",
        "period": "weekly",
        "period_label": "Weekly",
        "date_from": "2026-08-03",
        "date_to": "2026-08-10",
        "generated_at": "2026-08-10T00:00:00+00:00",
        "entries": _SAMPLE_ENTRIES if entries is None else entries,
        "llm_synthesis": synthesis,
        "target_audience": "",
        "source_tier_badge": False,
    }


def _section_block(markdown: str, heading: str) -> tuple[str, str]:
    """Split *markdown* into ``(block_after_heading, block_before_heading)``.

    The block after *heading* runs to the next ``## `` heading or the end of
    the document; the block before is the remainder of the document (used to
    compare What Changed against the References listing).
    """
    lines = markdown.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip() == heading),
        -1,
    )
    assert start >= 0, f"section {heading!r} not found in rendered markdown"
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith("## ") and lines[i].strip() != heading
        ),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end]), "\n".join(lines[:start])


# ===================================================================
# Test: LLM synthesis sections render the Deep Dive
# ===================================================================


class TestColumnDigestSections:
    """#316: column digest renders the Deep Dive from synthesis sections."""

    def test_deep_dive_renders_eight_plus_subsections(self) -> None:
        """A synthesis with 8 sections renders 8+ ``### `` subsections."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS)

        assert "## Deep Dive" in out
        assert len(_deep_dive_subsections(out)) >= 8
        assert "_No deep-dive sections available" not in out

    def test_sections_metadata_matches_actual_count(self) -> None:
        """The Deep Dive renders N subsections and NO internal count header
        (R2: ``**Sections**: N`` must not leak to end users — #85)."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS)

        subsections = _deep_dive_subsections(out)
        assert "**Sections**" not in out
        assert "**References**: " not in out
        assert len(subsections) > 0

    def test_each_subsection_has_substantive_content(self) -> None:
        """Every ``### `` heading is followed by a substantive paragraph."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS)

        lines = out.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("### "):
                continue
            body = next(
                (candidate for candidate in lines[i + 1 :] if candidate.strip()),
                "",
            )
            assert len(body.strip()) > 20, f"empty subsection under {line!r}"


# ===================================================================
# Test: deterministic fallback (no synthesis sections)
# ===================================================================


class TestColumnDigestDeterministicFallback:
    """#316: no synthesis sections → sections derived from the entries."""

    def test_no_sections_in_synthesis_still_renders_deep_dive(self) -> None:
        """Entries exist → the Deep Dive is never the empty placeholder."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS)

        assert "## Deep Dive" in out
        assert "_No deep-dive sections available" not in out
        subsections = _deep_dive_subsections(out)
        assert len(subsections) >= 8
        assert "**Sections**" not in out

    def test_deterministic_sections_carry_substantive_content(self) -> None:
        """Derived sections carry real entry titles + summaries."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS)

        lines = out.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("### "):
                continue
            body = next(
                (candidate for candidate in lines[i + 1 :] if candidate.strip()),
                "",
            )
            assert len(body.strip()) > 20, f"empty subsection under {line!r}"


# ===================================================================
# Test: synthesis prompt requests sections for the column family
# ===================================================================


class TestColumnDigestPrompt:
    """#316: the column digest synthesis prompt requests a sections array."""

    def test_column_prompt_requests_sections_array(self) -> None:
        """product_family="column" asks for 8-10 deep-dive subsections."""
        prompt = _build_digest_llm_prompt(_SAMPLE_ENTRIES, product_family="column")

        assert isinstance(prompt, str)
        assert '"sections"' in prompt
        assert "8-10" in prompt

    def test_default_digest_prompt_does_not_request_sections(self) -> None:
        """The default digest family stays unchanged (no sections field)."""
        prompt = _build_digest_llm_prompt(_SAMPLE_ENTRIES)

        assert '"sections"' not in prompt


# ===================================================================
# Test: context normalization flattens sections
# ===================================================================


class TestColumnNormalizeSections:
    """#316: _normalize_digest_product_context flattens sections."""

    def _context(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        return _column_context(synthesis)

    def test_flattens_synthesis_sections(self) -> None:
        """Synthesis ``sections`` flow into ``flat["sections"]`` as dicts."""
        flat = _normalize_digest_product_context(
            self._context(_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS),
            "medical-research",
            product_family="column",
        )

        assert len(flat["sections"]) == 8
        for section in flat["sections"]:
            assert section["title"]
            assert section["content"]

    def test_deterministic_fallback_when_sections_missing(self) -> None:
        """Column family + no synthesis sections → derived from entries."""
        flat = _normalize_digest_product_context(
            self._context(_SAMPLE_LLM_SYNTHESIS),
            "medical-research",
            product_family="column",
        )

        assert len(flat["sections"]) >= 8
        for section in flat["sections"]:
            assert section["title"]
            assert section["content"]

    def test_defaults_to_empty_list_when_sections_absent(self) -> None:
        """Non-column families keep ``sections == []`` (backward compatible)."""
        flat = _normalize_digest_product_context(
            self._context(_SAMPLE_LLM_SYNTHESIS),
            "medical-research",
        )

        assert flat["sections"] == []


# ===================================================================
# Test: value-drain guardrails (issue #17)
# ===================================================================


class TestColumnValueDrain:
    """#17: the column product must never copy its inputs verbatim.

    Three value-drain defects shipped in ``column.md.j2``: the What Changed
    section rendered the ENTIRE ``references`` list (60+ title lines,
    byte-identical to the References listing), the Implications & Outlook
    section copied each Deep Dive ``section.content`` verbatim, and Reader
    Takeaways was hardcoded meta boilerplate (no substantive takeaways).
    """

    def _context(
        self,
        synthesis: dict[str, Any],
        entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return _column_context(synthesis, entries=entries)

    # --- What Changed (issue #17.1) ------------------------------------

    def test_what_changed_is_capped_delta_not_reference_dump(self) -> None:
        """With 60 references the What Changed list is capped, not a dump.

        The flat column context carries up to 60 references (``ref_limit``
        default).  Pre-#17 the template looped over every reference, so the
        What Changed section listed all 60 title lines — byte-identical to
        the References listing below it.
        """
        sections = [
            {
                "title": f"Deep dive subsection {i}",
                "content": (
                    f"Analysis of study {i}: time-lapse imaging improved "
                    "live birth rates in the 2026 cohort."
                ),
            }
            for i in range(1, 9)
        ]
        entries = [
            {
                **_e,
                "title": f"Research finding {i} on IVF time-lapse imaging",
            }
            for i, _e in enumerate(_SAMPLE_ENTRIES, start=1)
        ]
        entries += [
            {
                "entry_id": f"extra-{i:03d}",
                "title": f"Additional IVF finding {i}",
                "summary": f"Additional study {i} reports IVF outcomes.",
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{20000000 + i}/",
                "source_type": "api",
                "source_platform": "pubmed",
                "relevance_score": 89.0 - i,
                "tags": '["IVF", "embryo"]',
                "tier": "01-Raw",
                "collected_at": "2026-07-15T10:00:00Z",
            }
            for i in range(1, 51)
        ]
        synthesis = {
            **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
            "sections": sections,
        }
        flat = _normalize_digest_product_context(
            self._context(synthesis, entries=entries),
            "medical-research",
            product_family="column",
        )
        assert len(flat["references"]) == 60, "hermetic setup: 60 references"
        out = _render_column_template(flat)

        changed, _ = _section_block(out, "## What Changed This Week")
        bullets = [
            ln for ln in changed.splitlines() if ln.startswith("- **")
        ]
        # Capped delta: at most 8 titles in What Changed.
        assert len(bullets) <= 8, (
            f"What Changed lists {len(bullets)} titles (must be capped <= 8): "
            f"{bullets[:3]}..."
        )
        # Never the full reference dump: at most 8 of the 60 titles appear.
        titles = [str(r.get("title") or "") for r in flat["references"]]
        appearing = [t for t in titles if t in changed]
        assert len(appearing) <= 8, (
            f"What Changed shows {len(appearing)}/60 reference titles (full "
            f"dump): {appearing[:3]}..."
        )

    def test_what_changed_dedupes_deep_dive_entry_titles(self) -> None:
        """Titles already shown in Deep Dive section tables are skipped."""
        sections = [
            {
                "title": f"Deep dive subsection {i}",
                "content": f"Analysis block {i}.",
                "entries": [
                    {
                        "title": f"Research finding {i} on IVF time-lapse imaging",
                        "summary": f"Study {i} summary.",
                    }
                ],
            }
            for i in range(1, 9)
        ]
        entries = [
            {
                **_e,
                "title": f"Research finding {i} on IVF time-lapse imaging",
            }
            for i, _e in enumerate(_SAMPLE_ENTRIES, start=1)
        ]
        entries += [
            {
                "entry_id": f"extra-{i:03d}",
                "title": f"Additional IVF finding {i}",
                "summary": f"Additional study {i} reports IVF outcomes.",
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{20000000 + i}/",
                "source_type": "api",
                "source_platform": "pubmed",
                "relevance_score": 89.0 - i,
                "tags": '["IVF", "embryo"]',
                "tier": "01-Raw",
                "collected_at": "2026-07-15T10:00:00Z",
            }
            for i in range(1, 51)
        ]
        flat = _normalize_digest_product_context(
            self._context({**_SAMPLE_LLM_SYNTHESIS, "sections": sections}, entries=entries),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        changed, _ = _section_block(out, "## What Changed This Week")
        # Deep Dive table titles must not be duplicated in What Changed.
        for section in flat["sections"]:
            for entry in section.get("entries") or []:
                assert str(entry.get("title") or "") not in changed, (
                    f"What Changed duplicates Deep Dive entry "
                    f"{entry.get('title')!r}"
                )
                assert str(entry.get("title") or "") in out, (
                    f"Deep Dive entry missing from full document "
                    f"{entry.get('title')!r}"
                )

    # --- Implications & Outlook (issue #17.2) --------------------------

    def test_implications_not_verbatim_section_content(self) -> None:
        """Implications bullets never copy ``section.content`` verbatim."""
        sections = [
            {
                "title": f"Deep dive subsection {i}",
                "content": (
                    f"Section {i} unique analysis: time-lapse imaging "
                    f"improved IVF live birth rates by {8 + i} percentage "
                    "points in the 2026 prospective cohort."
                ),
            }
            for i in range(1, 9)
        ]
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "sections": sections,
                }
            ),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        implications, _ = _section_block(out, "## Implications & Outlook")
        bullets = [ln for ln in implications.splitlines() if ln.startswith("- **")]
        assert len(bullets) == len(sections), (
            f"Implications has {len(bullets)} bullets for "
            f"{len(sections)} sections"
        )
        for i, section in enumerate(sections):
            content = str(section["content"]).strip()
            assert content not in implications, (
                f"Implications copies section {i} content verbatim: {content!r}"
            )
            assert str(section["title"]) in implications, (
                f"Implications misses section {i} title {section['title']!r}"
            )

    def test_implications_fallback_never_leaks_internal_count(self) -> None:
        """#49: the no-implication fallback never exposes ``(N item(s))``.

        Pre-#49 the template fell back to ``Covered in the Deep Dive (N
        item(s)); watch for follow-up developments next period.`` when the
        synthesis gave no implication for a section — an internal render
        count in reader-facing text.  The fallback must carry no count.
        """
        sections = [
            {
                "title": f"Deep dive subsection {i}",
                "content": f"Analysis block {i}.",
                "entries": [
                    {
                        "title": f"Entry {i}-{j}",
                        "summary": f"Summary {i}-{j}.",
                    }
                    for j in range(1, 4)
                ],
            }
            for i in range(1, 9)
        ]
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "sections": sections,
                }
            ),
            "medical-research",
            product_family="column",
        )
        assert flat["implications"] == [], (
            "hermetic setup: synthesis carries no implications"
        )
        out = _render_column_template(flat)

        implications, _ = _section_block(out, "## Implications & Outlook")
        assert "Covered in the Deep Dive; watch for follow-up developments next period." in implications, (
            f"natural fallback missing from Implications:\n{implications}"
        )
        assert not re.search(r"\(\d+ item\(s\)\)", out), (
            f"internal item count leaked into reader text:\n{out}"
        )

    def test_implications_uses_synthesis_implications_when_present(self) -> None:
        """Synthesis ``implications`` (so-what phrasing) is preferred."""
        implications = [
            f"So-what implication for section {i}: watch for follow-up "
            f"replications and extended cohorts."
            for i in range(1, 9)
        ]
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "implications": implications,
                }
            ),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        implications_block, _ = _section_block(out, "## Implications & Outlook")
        for i, implication in enumerate(implications):
            assert implication in implications_block, (
                f"Synthesis implication {i} missing from Implications"
            )
        # So-what phrasing, not section content.
        for section in flat["sections"]:
            assert str(section["content"]).strip() not in implications_block, (
                f"Implications copies section content verbatim: "
                f"{str(section['content']).strip()!r}"
            )

    # --- Reader Takeaways (issue #17.3) ---------------------------------

    def test_reader_takeaways_not_hardcoded_meta(self) -> None:
        """Takeaways derive from ``action_required``, never the meta lines."""
        action_required = [
            "Replicate the time-lapse cohort at a second center.",
            "Update the lab's embryo-grading protocol.",
            "Schedule a follow-up review after the extended cohort data lands.",
        ]
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "action_required": action_required,
                }
            ),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        takeaways, _ = _section_block(out, "## Reader Takeaways")
        assert "Revisit the Deep Dive sections" not in takeaways
        assert "Track the What Changed This Week list" not in takeaways
        assert "Follow the referenced sources" not in takeaways
        for action in action_required:
            assert action in takeaways, (
                f"action_required item missing from Takeaways: {action!r}"
            )

    def test_reader_takeaways_fallback_to_recommendations(self) -> None:
        """No ``action_required`` → numbered recommendations render."""
        recommendations = [
            "Consider time-lapse imaging as standard of care.",
            "Budget for a multicenter trial.",
        ]
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "action_required": [],
                    "recommendations": recommendations,
                }
            ),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        takeaways, _ = _section_block(out, "## Reader Takeaways")
        assert "Revisit the Deep Dive sections" not in takeaways
        assert "Track the What Changed This Week list" not in takeaways
        assert "Follow the referenced sources" not in takeaways
        for rec in recommendations:
            assert rec in takeaways, (
                f"recommendation missing from Takeaways: {rec!r}"
            )

    def test_reader_takeaways_section_derived_fallback(self) -> None:
        """Neither field present → takeaways derive from section titles."""
        flat = _normalize_digest_product_context(
            self._context(
                {
                    **_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS,
                    "action_required": [],
                    "recommendations": [],
                }
            ),
            "medical-research",
            product_family="column",
        )
        out = _render_column_template(flat)

        takeaways, _ = _section_block(out, "## Reader Takeaways")
        assert "Revisit the Deep Dive sections" not in takeaways
        assert "Track the What Changed This Week list" not in takeaways
        assert "Follow the referenced sources" not in takeaways
        for section in flat["sections"]:
            assert str(section["title"]) in takeaways, (
                f"section-derived takeaway missing {section['title']!r}"
            )
