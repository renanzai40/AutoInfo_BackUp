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
        """``**Sections**: N`` equals the number of rendered subsections."""
        out = _render_column_digest(_SAMPLE_LLM_SYNTHESIS_WITH_SECTIONS)

        subsections = _deep_dive_subsections(out)
        assert f"**Sections**: {len(subsections)}" in out
        assert "**Sections**: 0" not in out

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
        assert f"**Sections**: {len(subsections)}" in out

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
        return {
            "title": "Weekly Digest \u2014 medical-research",
            "domain": "medical-research",
            "period": "weekly",
            "period_label": "Weekly",
            "date_from": "2026-08-03",
            "date_to": "2026-08-10",
            "generated_at": "2026-08-10T00:00:00+00:00",
            "entries": _SAMPLE_ENTRIES,
            "llm_synthesis": synthesis,
            "target_audience": "",
            "source_tier_badge": False,
        }

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
