"""Tests for issue #302: render-layer defects.

Covers:
- ② magazine plural bug (1 publication vs 1 publications)
- ③ source-name internal identifiers → display names (platform_name filter)
- ④ reference jamming (newline eaten by trim_blocks)
- ① LLM raw JSON / prompt leakage detection

TDD: these tests should fail (RED) before the fix, pass (GREEN) after.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# ② Magazine plural bug
# ---------------------------------------------------------------------------


class TestMagazinePluralBug:
    """magazine-digest template must pluralize 'publication' correctly."""

    def test_single_publication_uses_singular(self) -> None:
        """1 publication → '1 publication', not '1 publications'."""
        from jinja2 import Environment

        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
        )
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v

        # Simulate the magazine-digest line 10
        tmpl = env.from_string(
            '{{ entries|length }} articles '
            'from {{ (entries|groupby("source_platform", default="General"))|length }} '
            'publication{{ "s" if '
            '(entries|groupby("source_platform", default="General"))|length != 1 else "" }}'
        )
        entries = [{"source_platform": "pubmed", "title": "A"}]
        result = tmpl.render(entries=entries)
        assert "1 publication" in result
        assert "1 publications" not in result

    def test_multiple_publications_uses_plural(self) -> None:
        """2 publications → '2 publications'."""
        from jinja2 import Environment

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v

        tmpl = env.from_string(
            '{{ entries|length }} articles '
            'from {{ (entries|groupby("source_platform", default="General"))|length }} '
            'publication{{ "s" if '
            '(entries|groupby("source_platform", default="General"))|length != 1 else "" }}'
        )
        entries = [
            {"source_platform": "pubmed", "title": "A"},
            {"source_platform": "rss", "title": "B"},
        ]
        result = tmpl.render(entries=entries)
        assert "2 publications" in result


# ---------------------------------------------------------------------------
# ③ Source-name platform_name filter
# ---------------------------------------------------------------------------


class TestPlatformNameFilter:
    """platform_name Jinja2 filter maps internal ids to display names."""

    def test_known_ids_mapped(self) -> None:
        from autoinfo.output import _platform_name

        assert _platform_name("pubmed") == "PubMed"
        assert _platform_name("sec_edgar") == "SEC EDGAR"
        assert _platform_name("rss") == "RSS"
        assert _platform_name("web") == "Web"
        assert _platform_name("api") == "API"
        assert _platform_name("openalex") == "OpenAlex"

    def test_unknown_id_falls_back(self) -> None:
        from autoinfo.output import _platform_name

        assert _platform_name("some_new_platform") == "some_new_platform"

    def test_empty_id_returns_dash(self) -> None:
        from autoinfo.output import _platform_name

        assert _platform_name("") == "\u2014"
        assert _platform_name(None) == "\u2014"

    def test_filter_registered_in_jinja_env(self) -> None:
        from autoinfo.output import _get_jinja_env

        env = _get_jinja_env()
        assert "platform_name" in env.filters

    def test_digest_template_uses_filter(self) -> None:
        """digest.md.j2 line 49 should use platform_name filter."""
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "digest.md.j2"
        )
        content = tpl_path.read_text()
        assert "platform_name" in content

    def test_column_template_uses_filter(self) -> None:
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "column.md.j2"
        )
        content = tpl_path.read_text()
        assert "user_source_label" in content

    def test_report_template_uses_filter(self) -> None:
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "report.md.j2"
        )
        content = tpl_path.read_text()
        assert "user_source_label" in content

    def test_premium_briefing_uses_filter(self) -> None:
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "premium-briefing.md.j2"
        )
        content = tpl_path.read_text()
        assert "user_source_label" in content

    def test_enterprise_briefing_uses_filter(self) -> None:
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "enterprise-briefing.md.j2"
        )
        content = tpl_path.read_text()
        assert "user_source_label" in content

    def test_magazine_digest_uses_filter(self) -> None:
        from pathlib import Path

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "magazine-digest.md.j2"
        )
        content = tpl_path.read_text()
        assert "platform_name" in content


# ---------------------------------------------------------------------------
# ④ Reference newline integrity
# ---------------------------------------------------------------------------


class TestReferenceNewlineIntegrity:
    """Reference loops must not jam entries on one line (trim_blocks issue)."""

    def _render_ref_loop(self, refs: list[dict[str, Any]], template_str: str) -> str:
        from jinja2 import Environment

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v or "\u2014"
        tmpl = env.from_string(template_str)
        return tmpl.render(references=refs)

    def test_column_refs_separate_lines(self) -> None:
        refs = [
            {"title": "A", "source_url": "http://a.com", "source_platform": "pubmed"},
            {"title": "B", "source_url": "http://b.com", "source_platform": "rss"},
        ]
        tpl = (
            "{% for ref in references %}"
            "- **{{ ref.title }}**"
            "{{ (' — ' ~ ref.source_url) if ref.source_url else '' }}"
            "{{ (' (' ~ ref.source_platform ~ ')') if ref.source_platform else '' }}"
            "\n"
            "{% endfor %}"
        )
        result = self._render_ref_loop(refs, tpl)
        lines = [line for line in result.strip().splitlines() if line.strip()]
        assert len(lines) == 2, f"Expected 2 separate lines, got {len(lines)}: {lines!r}"

    def test_report_refs_separate_lines(self) -> None:
        refs = [
            {"title": "X", "source_url": "", "source_platform": "web"},
            {"title": "Y", "source_url": "http://y.com", "source_platform": ""},
            {"title": "Z", "source_url": "", "source_platform": ""},
        ]
        tpl = (
            "{% for ref in references %}"
            "- **{{ ref.title }}**"
            "{{ (' — ' ~ ref.source_url) if ref.source_url else '' }}"
            "{{ (' (' ~ ref.source_platform ~ ')') if ref.source_platform else '' }}"
            "\n"
            "{% endfor %}"
        )
        result = self._render_ref_loop(refs, tpl)
        lines = [line for line in result.strip().splitlines() if line.strip()]
        assert len(lines) == 3, f"Expected 3 separate lines, got {len(lines)}: {lines!r}"

    def test_column_template_no_jamming(self) -> None:
        """column.md.j2 reference loop must not jam entries."""
        from pathlib import Path

        from jinja2 import Environment

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "column.md.j2"
        )
        content = tpl_path.read_text()

        from autoinfo.output import _user_source_label

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v or "\u2014"
        env.globals["user_source_label"] = _user_source_label
        tmpl = env.from_string(content)
        result = tmpl.render(
            title="Test", domain="test", generated_at="2026-01-01",
            executive_summary="Summary.", sections=[],
            references=[
                {"title": "Ref A", "source_url": "http://a.com", "source_platform": "pubmed"},
                {"title": "Ref B", "source_url": "http://b.com", "source_platform": "rss"},
            ],
            appendices=[],
        )
        # Find the "What Changed This Week" section
        in_section = False
        ref_lines = []
        for line in result.splitlines():
            if "What Changed This Week" in line:
                in_section = True
                continue
            if in_section and line.startswith("---"):
                break
            if in_section and line.startswith("- **"):
                ref_lines.append(line)
        assert len(ref_lines) == 2, (
            f"Expected 2 separate ref lines, got {len(ref_lines)}: {ref_lines!r}"
        )

    def test_report_template_no_jamming(self) -> None:
        """report.md.j2 reference loop must not jam entries."""
        from pathlib import Path

        from jinja2 import Environment

        tpl_path = (
            Path(__file__).parent.parent.parent
            / "src" / "autoinfo" / "data" / "templates" / "report.md.j2"
        )
        content = tpl_path.read_text()

        from autoinfo.output import _user_source_label

        env = Environment(trim_blocks=True, lstrip_blocks=True)
        env.filters["product_summary"] = lambda v: v
        env.filters["platform_name"] = lambda v: v or "\u2014"
        env.globals["user_source_label"] = _user_source_label
        tmpl = env.from_string(content)
        result = tmpl.render(
            title="Test", domain="test", generated_at="2026-01-01",
            executive_summary="Summary.", key_findings=[], recommendations=[],
            sections=[], source_tier_badge=False,
            references=[
                {"title": "Ref A", "source_url": "http://a.com", "source_platform": "pubmed"},
                {"title": "Ref B", "source_url": "http://b.com", "source_platform": "rss"},
            ],
            appendices=[],
        )
        in_refs = False
        ref_lines = []
        for line in result.splitlines():
            if line.strip() == "## References":
                in_refs = True
                continue
            if in_refs and line.startswith("---"):
                break
            if in_refs and (line.lstrip()[:2].rstrip(".").isdigit() or line.startswith("- **")):
                ref_lines.append(line)
        # Should be on separate lines
        assert len(ref_lines) == 2, (
            f"Expected 2 separate ref lines, got {len(ref_lines)}: {ref_lines!r}"
        )


# ---------------------------------------------------------------------------
# ① LLM raw JSON / prompt leakage detection
# ---------------------------------------------------------------------------


class TestLLMLeakDetection:
    """_contains_raw_llm_leak must flag synthetic leak content."""

    def test_clean_product_no_flag(self) -> None:
        from autoinfo.output import _contains_raw_llm_leak

        clean = (
            "# Medical Research Digest\n\n"
            "## Executive Summary\n\n"
            "IVF outcomes improve with time-lapse imaging.\n\n"
            "## Key Findings\n\n"
            "- Time-lapse improves birth rates.\n"
        )
        assert _contains_raw_llm_leak(clean) is False

    def test_fenced_json_block_flagged(self) -> None:
        from autoinfo.output import _contains_raw_llm_leak

        leaky = 'Here is the result:\n```json\n{"title": "Test", "entries": []}\n```\n'
        assert _contains_raw_llm_leak(leaky) is True

    def test_json_prefix_flagged(self) -> None:
        from autoinfo.output import _contains_raw_llm_leak

        leaky = '{"title": "Digest", "entries": [{"id": 1}]}'
        assert _contains_raw_llm_leak(leaky) is True

    def test_prompt_echo_flagged(self) -> None:
        from autoinfo.output import _contains_raw_llm_leak

        leaky = "You are a medical research analyst. Please summarize the following entries."
        assert _contains_raw_llm_leak(leaky) is True

    def test_ai_self_reference_flagged(self) -> None:
        from autoinfo.output import _contains_raw_llm_leak

        leaky = "As an AI language model, I cannot provide medical advice."
        assert _contains_raw_llm_leak(leaky) is True
