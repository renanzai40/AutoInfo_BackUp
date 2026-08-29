"""Tests for issue #314: enterprise-briefing coverage claim consistency.

The enterprise-briefing Executive Summary is written by the LLM, and
previously nothing bound its opening "coverage" claim to the actual number
of Key Findings bullets rendered below — the summary could claim "20
items" while only 9 findings were detailed (or vice versa), which breaks
the paid-product credibility contract.

Fix has two parts (both asserted here):

1. Prompt-level guard: the report synthesis prompt (shared by
   premium-briefing / magazine-digest / enterprise-briefing via
   ``_REPORT_PRODUCT_BASE_SECTIONS``) MUST instruct the model to name
   exactly the number of Key Findings it writes, never a larger count.
2. Render-level determinism: the enterprise-briefing template labels the
   selection scope deterministically — ``N key findings selected · M source
   references`` (single-language, no CJK template leak, #8 residual; and no
   awkward ``of M key findings`` counting syntax, #49) — so even a stale
   summary claim is visibly scoped, on BOTH flat-context paths (report
   ``_report_data_to_dict`` and digest ``_normalize_digest_product_context``).
"""

from __future__ import annotations

import re
from typing import Any, cast

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    ReportData,
    _build_report_synthesis_prompt,
    _normalize_digest_product_context,
    _report_data_to_dict,
)


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return cast(ProductTemplate, row["template"])
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _make_report_data(n_findings: int, n_references: int) -> ReportData:
    """A ReportData with ``n_findings`` key findings and ``n_references`` refs."""
    return ReportData(
        title="medical-research \u2014 Enterprise Briefing",
        generated_at="2026-08-19 00:00 UTC",
        domain="medical-research",
        executive_summary="This briefing details 20 selected items from the period.",
        key_findings=cast(
            list[dict[str, Any]],
            [{"text": f"Finding number {i}"} for i in range(1, n_findings + 1)],
        ),
        references=[
            {
                "title": f"Reference {i}",
                "source_url": f"https://example.com/ref-{i}",
                "source_type": "api",
                "source_platform": "pubmed",
                "domain": "medical-research",
            }
            for i in range(1, n_references + 1)
        ],
    )


def _make_digest_context(n_findings: int, n_entries: int) -> dict[str, Any]:
    """A raw digest context whose synthesis has ``n_findings`` key findings."""
    return {
        "title": "Weekly Digest \u2014 medical-research",
        "domain": "medical-research",
        "entries": [
            {
                "entry_id": f"entry-{i:03d}",
                "title": f"Entry number {i}",
                "summary": f"Summary of entry {i}.",
                "source_url": f"https://example.com/entry-{i}",
                "source_type": "rss",
                "source_platform": "pubmed",
                "domain": "medical-research",
            }
            for i in range(1, n_entries + 1)
        ],
        "llm_synthesis": {
            "executive_summary": "This briefing details 20 selected items.",
            "key_findings": [
                {"topic": f"Topic {i}", "detail": f"Detail {i}."}
                for i in range(1, n_findings + 1)
            ],
            "recommendations": ["Watch the trial results."],
        },
    }


# ===================================================================
# Prompt-level guard
# ===================================================================


class TestSynthesisPromptCoverageConsistency:
    """The synthesis prompt must bind the coverage claim to the findings count."""

    def test_synthesis_prompt_requires_coverage_consistency(self) -> None:
        """enterprise-briefing prompt names the exact Key Findings count rule.

        The Executive Summary's opening sentence MUST state the number of
        Key Findings actually written below — never a larger coverage
        count. This guard lives in ``_REPORT_PRODUCT_BASE_SECTIONS`` so it
        applies to enterprise-briefing (and the sibling product families).
        """
        prompt = _build_report_synthesis_prompt(
            "Themes and entries:\n<entries>",
            product_family="enterprise-briefing",
        )
        assert "coverage" in prompt
        assert "number of Key Findings" in prompt

    def test_coverage_guard_shared_by_all_product_families(self) -> None:
        """premium-briefing and magazine-digest inherit the same guard."""
        for family in ("premium-briefing", "magazine-digest"):
            prompt = _build_report_synthesis_prompt(
                "Themes and entries:\n<entries>",
                product_family=family,
            )
            assert "number of Key Findings" in prompt


# ===================================================================
# Render-level scope label
# ===================================================================


class TestEnterpriseTemplateScopeLabel:
    """The template deterministically labels the selection scope."""

    def test_enterprise_template_annotates_selected_count(self) -> None:
        """Report path: 9 findings + 20 references render the scope label."""
        flat = _report_data_to_dict(_make_report_data(9, 20))
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert "9 key points · drawn from 20 sources" in out
        assert "of 20 key findings" not in out
        # The deterministic label sits between the summary and the findings.
        assert out.index("> **In this briefing**:") < out.index("## Key Findings")

    def test_enterprise_digest_path_annotates_too(self) -> None:
        """Digest path: same label through ``_normalize_digest_product_context``."""
        flat = _normalize_digest_product_context(
            _make_digest_context(9, 20), "medical-research"
        )
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert "9 key points · drawn from 20 sources" in out
        assert "of 20 key findings" not in out

    def test_scope_label_absent_when_no_findings(self) -> None:
        """No key findings -> no scope label (empty-state unchanged)."""
        flat = _report_data_to_dict(_make_report_data(0, 3))
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert "精选" not in out
        assert "**Scope**" not in out

    def test_scope_label_degrades_when_no_references(self) -> None:
        """Findings without references never expose an "N of 0" counting
        syntax — the references clause degrades to "no source references"."""
        flat = _report_data_to_dict(_make_report_data(3, 0))
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert "3 key points · no source links" in out
        assert "of 0" not in out
        assert "key points · 0 sources" not in out


class TestScopeLabelSingleLanguageNoCjk:
    """Issue #8 residual: the enterprise scope label must be single-language
    (no CJK template leak) and must not over-claim a per-finding expansion
    (the References section is a flat list, not a per-finding detail block)."""

    def test_scope_label_single_language_no_cjk(self) -> None:
        """A hermetic enterprise-briefing render (3 findings + 60 references)
        contains NO CJK characters anywhere in the body."""
        flat = _report_data_to_dict(_make_report_data(3, 60))
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert not re.search(r"[\u4e00-\u9fff]", out), (
            f"CJK characters leaked into the enterprise-briefing body:\n{out}"
        )

    def test_scope_label_counts_match_references(self) -> None:
        """The scope label's ``N key findings selected · M source references``
        equals the rendered Key Findings bullets and the rendered References —
        no "items detailed below" claim the flat References list cannot support,
        and never an "of M key findings" counting syntax (issue #49)."""
        flat = _report_data_to_dict(_make_report_data(3, 60))
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        scope_m = re.search(r"> \*\*In this briefing\*\*: (.+)$", out, re.MULTILINE)
        assert scope_m, f"scope line missing from render:\n{out}"
        scope_line = scope_m.group(1)
        count_m = re.search(r"(\d+) key points · drawn from (\d+) sources", scope_line)
        assert count_m, (
            f"N key points · M sources counts missing "
            f"from scope line:\n{scope_line}"
        )
        n, m = int(count_m.group(1)), int(count_m.group(2))
        assert "of key findings" not in scope_line
        findings_m = re.search(
            r"## Key Findings\n(.*?)(?:\n## |\Z)", out, re.DOTALL
        )
        assert findings_m, f"Key Findings section missing:\n{out}"
        rendered_findings = len(re.findall(r"-\s+\S", findings_m.group(1)))
        assert n == rendered_findings, (
            f"scope N={n} but Key Findings renders {rendered_findings} bullets"
        )
        refs_m = re.search(r"## References\n(.*?)(?:\n---|\Z)", out, re.DOTALL)
        assert refs_m, f"References section missing:\n{out}"
        rendered_refs = len(re.findall(r"^\d+\. ", refs_m.group(1), re.MULTILINE))
        assert m == rendered_refs, (
            f"scope M={m} but References renders {rendered_refs} entries"
        )
