"""Tests for issue #303: empty-shell products + internal-state leak.

- column with sections=[] renders fallback text (no silent empty headings)
- presentation with LLM synthesis returning no slides: no internal-state leak

TDD: these tests should fail (RED) before the fix, pass (GREEN) after.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# ① Column empty-shell: sections=[] must render fallback text
# ---------------------------------------------------------------------------


class TestColumnEmptyShell:
    """column.md.j2 must render fallback text when sections are empty."""

    def _render_column(self, sections: list[dict[str, Any]], **kwargs: Any) -> str:
        from pathlib import Path

        from jinja2 import Environment

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "column.md.j2"
        )
        content = tpl_path.read_text()

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v or "\u2014"
        # Issue #157: mirror the production env globals — column.md.j2 uses
        # domain_display_name (and user_source_label) which the bare env must
        # register or the template raises UndefinedError.
        from autoinfo.output import _domain_display_name, _user_source_label

        env.globals["domain_display_name"] = _domain_display_name
        env.globals["user_source_label"] = _user_source_label
        tmpl = env.from_string(content)

        defaults = {
            "title": "Test Column", "domain": "test", "generated_at": "2026-01-01",
            "executive_summary": "Summary.", "sections": sections,
            "references": [], "appendices": [],
        }
        defaults.update(kwargs)
        return tmpl.render(**defaults)

    def test_deep_dive_empty_shows_fallback(self) -> None:
        result = self._render_column(sections=[])
        # Must NOT have an empty "## Deep Dive" heading with nothing under it
        assert (
            "No deep-dive" in result
            or "no deep-dive" in result.lower()
            or "no sections" in result.lower()
        ), (
            f"Expected fallback text in Deep Dive section, got:\n{result}"
        )

    def test_implications_empty_omits_section(self) -> None:
        # Issue #133: with no implications the whole "## Implications &
        # Outlook" section (heading included) is omitted — never an empty
        # heading, never a hollow placeholder.  (#157 fixed the bare-env
        # globals so this renders at all.)
        result = self._render_column(sections=[])
        assert "## Implications & Outlook" not in result, (
            f"Expected the empty Implications section to be omitted, got:\n{result}"
        )

    def test_column_with_sections_renders_normally(self) -> None:
        sections = [
            {"title": "AI in IVF", "content": "Deep analysis.", "entries": []},
        ]
        result = self._render_column(sections=sections)
        assert "## Deep Dive" in result
        assert "AI in IVF" in result
        assert "Deep analysis." in result


# ---------------------------------------------------------------------------
# ② Presentation internal-state leak
# ---------------------------------------------------------------------------


class TestPresentationLeak:
    """Presentation must not expose internal fallback state in rendered output."""

    def test_kb_fallback_no_leak_string(self) -> None:
        """When LLM returns no slides, the KB-derived fallback must not
        expose 'KB-derived slide' or 'returned no slides' in the output."""
        from autoinfo.output import _fallback_slides_from_entries

        entries = [
            {"title": "IVF breakthrough", "summary": "Time-lapse imaging improves outcomes."},
            {"title": "Embryo selection", "summary": "AI models show promise."},
        ]
        slides = _fallback_slides_from_entries(entries, slide_count=3)
        for slide in slides:
            notes = slide.get("notes", "")
            assert "KB-derived slide" not in notes, (
                f"Internal-state leak in notes: {notes!r}"
            )
            assert "returned no slides" not in notes, (
                f"Internal-state leak in notes: {notes!r}"
            )

    def test_kb_fallback_notes_are_neutral(self) -> None:
        """KB-derived slide notes should be neutral or empty."""
        from autoinfo.output import _fallback_slides_from_entries

        entries = [
            {"title": "IVF breakthrough", "summary": "Time-lapse imaging improves outcomes."},
        ]
        slides = _fallback_slides_from_entries(entries, slide_count=1)
        assert len(slides) >= 1
        notes = slides[0].get("notes", "")
        # Should either be empty or a neutral message
        if notes:
            assert "KB-derived" not in notes
            assert "no slides" not in notes.lower()
