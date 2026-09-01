"""Tests for per-product LLM synthesis sections (output-quality-mega, todo 7).

Covers spec §2.4 of ``.omo/evidence/phaseA-template-spec.md``: the digest and
report synthesis prompts must request the product-specific fields keyed by the
resolved product family (``premium-briefing`` / ``enterprise-briefing`` /
``magazine-digest``; ``key_metrics`` for ``enterprise-briefing`` only):

- ``implications`` (``list[str]``, index-aligned 1:1 with ``key_findings``)
- ``risks`` (``list[dict]`` ``{title, likelihood, impact, mitigation}``)
- ``action_required`` (``list[str]``, index-aligned)
- ``key_metrics`` (``list[dict]`` ``{metric, value, source}``, enterprise)

and that the fields flow into the flat render context on BOTH paths:

- digest path: ``llm_synthesis`` → ``_normalize_digest_product_context`` →
  top-level flat keys
- report path: synthesis dict → ``ReportData`` → ``_report_data_to_dict`` →
  ``pt_context``

Default standard/report synthesis stays unchanged (no product fields).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult
from autoinfo.output import (
    _REPORT_PRODUCT_BASE_SECTIONS,
    PRODUCT_TEMPLATES,
    ProductTemplate,
    ReportData,
    ReportSection,
    _build_digest_llm_prompt,
    _generate_executive_summary,
    _normalize_digest_product_context,
    _report_data_to_dict,
    generate_digest,
    generate_report,
)

# ===================================================================
# Sample data
# ===================================================================

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "title": "Improved IVF outcomes with time-lapse imaging",
        "language": "en",
        "summary": "Time-lapse imaging improves live birth rates in IVF.",
                    "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": 92.0,
        "tags": '["IVF", "embryo"]',
        "tier": "01-Raw",
        "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    },
    {
        "entry_id": "entry-002",
        "title": "AI-driven embryo selection: a systematic review",
        "language": "en",
        "summary": "AI models show promise but lack prospective validation.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": 85.0,
        "tags": '["AI", "IVF"]',
        "tier": "01-Raw",
        "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    },
]

# Product synthesis with 2 findings — implications / risks / action_required
# index-aligned 1:1 with key_findings (spec §2.4 / §5.2-5.4).
_SAMPLE_DIGEST_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's key developments focus on IVF technology advancements "
        "including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": "Significant improvement in live birth rates (48.2% vs 39.5%).",
        },
        {
            "topic": "AI embryo selection",
            "detail": "Promising but lacks prospective clinical validation.",
        },
    ],
    "recommendations": [
        "Consider time-lapse imaging as standard of care",
        "Support prospective AI validation trials",
    ],
    "implications": [
        "Clinics should evaluate time-lapse imaging adoption given the live "
        "birth rate improvement.",
        "Regulators and payers should watch for unvalidated AI embryo "
        "selection tools.",
    ],
    "risks": [
        {
            "title": "Validation lag",
            "likelihood": "high",
            "impact": "medium",
            "mitigation": "Run prospective trials before standardizing.",
        },
        {
            "title": "Adoption cost",
            "likelihood": "medium",
            "impact": "low",
            "mitigation": "Pilot programs to demonstrate ROI.",
        },
    ],
    "action_required": [
        "Run a pilot evaluation of time-lapse imaging across two clinics.",
        "Fund prospective AI validation trials.",
    ],
    "key_metrics": [
        {"metric": "Live birth rate", "value": "48.2% vs 39.5%", "source": "time-lapse RCT"},
        {
            "metric": "Validation status",
            "value": "Prospective trials pending",
            "source": "systematic review",
        },
    ],
}

# Report-path synthesis markdown WITHOUT product sections — what a default
# (non-product) report LLM emits.
_SAMPLE_REPORT_SYNTHESIS_BASE_MD = """## Executive Summary
This briefing covers two key themes. IVF treatment continues to advance with
time-lapse imaging improving outcomes.

## Key Findings
- Time-lapse imaging: Significant improvement in live birth rates (48.2% vs 39.5%).
- AI embryo selection: Promising but lacks prospective clinical validation.

## Recommendations
- Consider time-lapse imaging as standard of care.
- Support prospective AI validation trials.
"""

# Report-path synthesis markdown (mocked LLM output) carrying the §2.4
# product sections; risks use the ``title | likelihood | impact | mitigation``
# line format and key_metrics the ``metric | value | source`` format.
_SAMPLE_REPORT_SYNTHESIS_MD = """## Executive Summary
This briefing covers two key themes. IVF treatment continues to advance with
time-lapse imaging improving outcomes. Neuroplasticity research highlights
critical developmental periods.

## Key Findings
- Time-lapse imaging: Significant improvement in live birth rates (48.2% vs 39.5%).
- AI embryo selection: Promising but lacks prospective clinical validation.

## Implications
- Clinics should evaluate time-lapse imaging adoption given the live birth rate improvement.
- Regulators and payers should watch for unvalidated AI embryo selection tools.

## Risks & Opportunities
- Validation lag | high | medium | Run prospective trials before standardizing.
- Adoption cost | medium | low | Pilot programs to demonstrate ROI.

## Action Required
- Run a pilot evaluation of time-lapse imaging across two clinics.
- Fund prospective AI validation trials.

## Key Metrics
- Live birth rate | 48.2% vs 39.5% | time-lapse RCT
- Validation status | Prospective trials pending | systematic review

## Recommendations
- Consider time-lapse imaging as standard of care.
- Support prospective AI validation trials.
"""

# Dedicated-prompt response (round-2 F3 fix): ONLY the §2.4 product sections,
# no executive summary — what the second small prompt is asked to emit.
_SAMPLE_PRODUCT_SECTIONS_ONLY_MD = """## Implications
- Clinics should evaluate time-lapse imaging adoption given the live birth rate improvement.
- Regulators and payers should watch for unvalidated AI embryo selection tools.

## Risks & Opportunities
- Validation lag | high | medium | Run prospective trials before standardizing.
- Adoption cost | medium | low | Pilot programs to demonstrate ROI.

## Action Required
- Run a pilot evaluation of time-lapse imaging across two clinics.
- Fund prospective AI validation trials.

## Key Metrics
- Live birth rate | 48.2% vs 39.5% | time-lapse RCT
- Validation status | Prospective trials pending | systematic review
"""

_GROUPINGS: list[dict[str, Any]] = [
    {
        "theme": "IVF & Reproductive Medicine",
        "description": "Advancements in IVF treatment.",
        "entries": [_SAMPLE_ENTRIES[0]],
    },
    {
        "theme": "AI in Embryo Selection",
        "description": "AI-driven selection tools.",
        "entries": [_SAMPLE_ENTRIES[1]],
    },
]


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return cast(ProductTemplate, row["template"])
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _make_grouping_result() -> ExtractionResult:
    """Return an ExtractionResult with thematic grouping custom fields."""
    return ExtractionResult(
        item_id="_report_llm_call",
        title="Groups",
        custom_fields={
            "groups": [
                {
                    "theme": "IVF & Reproductive Medicine",
                    "description": "Advancements in IVF treatment.",
                    "entry_ids": ["entry-001"],
                },
                {
                    "theme": "AI in Embryo Selection",
                    "description": "AI-driven selection tools.",
                    "entry_ids": ["entry-002"],
                },
            ],
        },
    )


def _get_llm_extractor_class() -> type[LLMExtractor]:
    """Return the ``LLMExtractor`` class from ``autoinfo.llm``."""
    from autoinfo.llm import LLMExtractor

    return LLMExtractor


# ===================================================================
# Digest path: prompt keying by product family
# ===================================================================


class TestDigestPromptProductKeying:
    """``_build_digest_llm_prompt`` requests product fields per family."""

    def test_default_family_unchanged_no_product_fields(self) -> None:
        """The default ``digest`` family never requests product fields."""
        prompt = _build_digest_llm_prompt(_SAMPLE_ENTRIES)
        for field in ("implications", "risks", "action_required", "key_metrics"):
            assert field not in prompt

    def test_premium_briefing_requests_three_product_fields(self) -> None:
        """premium-briefing asks for implications/risks/action_required."""
        prompt = _build_digest_llm_prompt(
            _SAMPLE_ENTRIES, product_family="premium-briefing"
        )
        for field in ("implications", "risks", "action_required"):
            assert f'"{field}"' in prompt
        # Index-alignment contract (spec §2.4) is explicit in the prompt.
        assert "index-aligned" in prompt
        # key_metrics is enterprise-only — absent here.
        assert '"key_metrics"' not in prompt

    def test_premium_briefing_risks_require_concrete_numbers(self) -> None:
        """#307: every Risk must embed a concrete number/case/entity and every
        Action a who/what/when — no template-filler prose."""
        sections = _REPORT_PRODUCT_BASE_SECTIONS
        assert "concrete number, case, or named entity" in sections
        assert "who does it" in sections
        assert "timeline" in sections
        assert "Valuation Bubble" in sections  # explicit anti-example

    def test_premium_briefing_actions_require_who_what_when(self) -> None:
        """#307: Actions must name WHO/WHAT/WHEN, never bare imperatives."""
        sections = _REPORT_PRODUCT_BASE_SECTIONS
        assert "WHO does it" in sections
        assert "WHAT specifically" in sections
        assert "WHEN timeline" in sections
        assert "conduct market analysis" in sections  # explicit anti-example

    def test_magazine_digest_requests_three_product_fields(self) -> None:
        """magazine-digest asks for implications/risks/action_required."""
        prompt = _build_digest_llm_prompt(
            _SAMPLE_ENTRIES, product_family="magazine-digest"
        )
        for field in ("implications", "risks", "action_required"):
            assert f'"{field}"' in prompt
        assert '"key_metrics"' not in prompt

    def test_enterprise_briefing_requests_key_metrics_too(self) -> None:
        """enterprise-briefing additionally asks for key_metrics."""
        prompt = _build_digest_llm_prompt(
            _SAMPLE_ENTRIES, product_family="enterprise-briefing"
        )
        for field in ("implications", "risks", "action_required", "key_metrics"):
            assert f'"{field}"' in prompt

    def test_unknown_family_falls_back_to_default(self) -> None:
        """An unknown family behaves exactly like the default digest."""
        prompt = _build_digest_llm_prompt(_SAMPLE_ENTRIES, product_family="column")
        assert "implications" not in prompt


# ===================================================================
# Digest path: fields flow llm_synthesis -> flat context -> render
# ===================================================================


class TestDigestProductFieldsFlow:
    """``generate_digest(product_template=...)`` surfaces the fields."""

    def _render(
        self, *, product_template: ProductTemplate | None, format: str = "markdown"
    ) -> tuple[str, str]:
        """Render a digest; returns (rendered, prompt_sent_to_llm)."""
        captured_prompt: list[str] = []

        def _fake_llm(prompt: str, config: Any = None) -> dict[str, Any]:
            captured_prompt.append(prompt)
            return _SAMPLE_DIGEST_SYNTHESIS

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest", side_effect=_fake_llm),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _SAMPLE_ENTRIES
            mock_kb_cls.return_value = mock_store
            result = generate_digest(
                domain="medical-research",
                period="weekly",
                format=format,
                product_template=product_template,
            )
        assert isinstance(result, str)
        return result, captured_prompt[0] if captured_prompt else ""

    def test_digest_premium_briefing_surfaces_aligned_fields(self) -> None:
        """Per-takeaway implication/risk/action render non-empty (index-aligned)."""
        rendered, prompt = self._render(
            product_template=_registry_template("premium-briefing")
        )
        # The prompt requested the product fields (keyed by family).
        assert '"implications"' in prompt
        assert "index-aligned" in prompt
        # Takeaway 1 and 2 each carry their aligned implication.
        assert "> **So what**: Clinics should evaluate time-lapse imaging" in rendered
        assert "> **So what**: Regulators and payers should watch" in rendered
        # Aligned risk dict renders its fields.
        assert "**Risk / Opportunity:** Validation lag — likelihood high / impact" in rendered
        # Aligned action renders.
        assert "**Actions:** Run a pilot evaluation of time-lapse imaging" in rendered

    def test_digest_enterprise_briefing_surfaces_key_metrics(self) -> None:
        """Enterprise render includes the Key Metrics table with real rows."""
        rendered, prompt = self._render(
            product_template=_registry_template("enterprise-briefing")
        )
        assert '"key_metrics"' in prompt
        assert "| Metric | Value | Source |" in rendered
        assert "| Live birth rate | 48.2% vs 39.5% | time-lapse RCT |" in rendered
        # Risk matrix row rendered from the aligned risk dicts.
        assert "| Validation lag | high | medium |" in rendered

    def test_digest_default_family_does_not_request_product_fields(self) -> None:
        """No product_template -> default digest prompt, no product fields."""
        rendered, prompt = self._render(product_template=None)
        assert "## Entries" in rendered
        assert "implications" not in prompt
        assert "Premium Briefing \u00b7 " not in rendered

    def test_normalize_flat_context_carries_product_fields(self) -> None:
        """The flat context keys come straight from llm_synthesis (todo 5 seam)."""
        context = {
            "title": "Weekly Digest \u2014 medical-research",
            "domain": "medical-research",
            "entries": _SAMPLE_ENTRIES,
            "llm_synthesis": _SAMPLE_DIGEST_SYNTHESIS,
        }
        flat = _normalize_digest_product_context(context, "medical-research")
        assert flat["implications"] == _SAMPLE_DIGEST_SYNTHESIS["implications"]
        assert flat["risks"] == _SAMPLE_DIGEST_SYNTHESIS["risks"]
        assert flat["action_required"] == _SAMPLE_DIGEST_SYNTHESIS["action_required"]
        assert flat["key_metrics"] == _SAMPLE_DIGEST_SYNTHESIS["key_metrics"]
        # Index-alignment: same order/count as the normalized key_findings.
        assert len(flat["implications"]) == len(flat["key_findings"]) == 2


# ===================================================================
# Report path: synthesis prompt + parse
# ===================================================================


class TestReportSynthesisProductFields:
    """``_generate_executive_summary`` requests and parses product sections."""

    def _synthesize(
        self, product_family: str = "report", md: str = _SAMPLE_REPORT_SYNTHESIS_MD
    ) -> tuple[dict[str, Any], str]:
        """Run the synthesis with a captured prompt; returns (result, prompt)."""
        captured: list[str] = []
        extractor = MagicMock()

        def _fake_synthesis(prompt: str) -> str:
            captured.append(prompt)
            return md

        with patch(
            "autoinfo.output._call_llm_for_report_synthesis", side_effect=_fake_synthesis
        ):
            result = _generate_executive_summary(
                extractor,
                _SAMPLE_ENTRIES,
                _GROUPINGS,
                product_family=product_family,
            )
        assert isinstance(result, dict)
        return result, captured[0] if captured else ""

    def test_default_family_prompt_has_no_product_sections(self) -> None:
        """Default ``report`` family: prompt requests no product sections."""
        result, prompt = self._synthesize(md=_SAMPLE_REPORT_SYNTHESIS_BASE_MD)
        assert "## Implications" not in prompt
        assert "## Risks & Opportunities" not in prompt
        assert "## Action Required" not in prompt
        assert "## Key Metrics" not in prompt
        # Parsed product keys default to empty lists (flat §2.1 contract).
        assert result.get("implications") == []
        assert result.get("risks") == []
        assert result.get("action_required") == []
        assert result.get("key_metrics") == []

    def test_premium_family_requests_and_parses_aligned_fields(self) -> None:
        """premium-briefing: prompt asks; parse yields aligned lists/dicts."""
        result, prompt = self._synthesize("premium-briefing")
        assert "## Implications" in prompt
        assert "index-aligned" in prompt
        assert "## Key Metrics" not in prompt
        assert result["implications"] == [
            "Clinics should evaluate time-lapse imaging adoption given the "
            "live birth rate improvement.",
            "Regulators and payers should watch for unvalidated AI embryo "
            "selection tools.",
        ]
        assert result["risks"][0] == {
            "title": "Validation lag",
            "likelihood": "high",
            "impact": "medium",
            "mitigation": "Run prospective trials before standardizing.",
        }
        assert result["action_required"] == [
            "Run a pilot evaluation of time-lapse imaging across two clinics.",
            "Fund prospective AI validation trials.",
        ]
        # Index-alignment contract (spec §2.4): same order/count as findings.
        assert len(result["implications"]) == len(result["key_findings"]) == 2

    def test_enterprise_family_parses_key_metrics(self) -> None:
        """enterprise-briefing: key_metrics parsed to {metric, value, source}."""
        result, prompt = self._synthesize("enterprise-briefing")
        assert "## Key Metrics" in prompt
        assert result["key_metrics"] == [
            {"metric": "Live birth rate", "value": "48.2% vs 39.5%", "source": "time-lapse RCT"},
            {
                "metric": "Validation status",
                "value": "Prospective trials pending",
                "source": "systematic review",
            },
        ]


# ===================================================================
# Report path: fields flow synthesis -> ReportData -> pt_context -> render
# ===================================================================


class TestReportProductFieldsFlow:
    """``generate_report(product_template=...)`` surfaces the fields."""

    def _render(
        self, *, product_template: ProductTemplate | None
    ) -> tuple[str, str]:
        """Render a report; returns (rendered, prompt_sent_to_llm)."""
        captured: list[str] = []
        mock_extract = MagicMock(side_effect=[_make_grouping_result()])

        def _fake_synthesis(prompt: str) -> str:
            captured.append(prompt)
            return _SAMPLE_REPORT_SYNTHESIS_MD

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch.object(_get_llm_extractor_class(), "extract", mock_extract),
            patch(
                "autoinfo.output._call_llm_for_report_synthesis",
                side_effect=_fake_synthesis,
            ),
        ):
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _SAMPLE_ENTRIES
            mock_kb_cls.return_value = mock_store
            result = generate_report(
                domain="medical-research",
                format="markdown",
                report_type="standard",
                product_template=product_template,
            )
        assert isinstance(result, str)
        return result, captured[0] if captured else ""

    def test_report_premium_briefing_surfaces_product_fields(self) -> None:
        """pt_context carries the fields; template renders them non-empty."""
        rendered, prompt = self._render(
            product_template=_registry_template("premium-briefing")
        )
        assert "## Implications" in prompt
        assert "> **So what**: Clinics should evaluate time-lapse imaging" in rendered
        assert "**Risk / Opportunity:** Validation lag — likelihood high / impact" in rendered
        assert "**Actions:** Run a pilot evaluation of time-lapse imaging" in rendered
        assert "Premium Briefing \u00b7 " in rendered

    def test_report_enterprise_briefing_surfaces_key_metrics(self) -> None:
        """Enterprise report renders the Key Metrics + Risk Matrix tables."""
        rendered, prompt = self._render(
            product_template=_registry_template("enterprise-briefing")
        )
        assert "## Key Metrics" in prompt
        assert "| Live birth rate | 48.2% vs 39.5% | time-lapse RCT |" in rendered
        assert "| Validation lag | high | medium |" in rendered
        assert "- [ ] Fund prospective AI validation trials." in rendered
        assert "Enterprise Briefing \u00b7 " in rendered

    def test_report_default_unchanged(self) -> None:
        """No product_template -> standard report, no product sections requested."""
        rendered, prompt = self._render(product_template=None)
        assert "## Implications" not in prompt
        assert "## Key Takeaways" not in rendered
        assert "Report \u00b7 " in rendered


# ===================================================================
# ReportData flat context (unit level)
# ===================================================================


class TestReportDataToDictProductFields:
    """``_report_data_to_dict`` carries the product fields in pt_context."""

    def test_product_fields_in_flat_dict(self) -> None:
        """The four fields are present in the flat render context."""
        data = ReportData(
            title="medical-research \u2014 Report",
            generated_at="2026-08-10 00:00 UTC",
            domain="medical-research",
            executive_summary="Summary.",
            key_findings=cast(
                list[dict[str, Any]],
                [
                    "Time-lapse imaging: Significant improvement in live birth rates.",
                    "AI embryo selection: Promising but lacks prospective validation.",
                ],
            ),
            sections=[
                ReportSection(title="IVF", content="c", items=[_SAMPLE_ENTRIES[0]])
            ],
            references=[
                {
                    "title": "Improved IVF outcomes",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                    "source_type": "api",
                    "source_platform": "pubmed",
                    "domain": "medical-research",
                }
            ],
            implications=["Implication one", "Implication two"],
            risks=[
                {
                    "title": "Validation lag",
                    "likelihood": "high",
                    "impact": "medium",
                    "mitigation": "Run prospective trials.",
                }
            ],
            action_required=["Fund prospective validation."],
            key_metrics=[{"metric": "Live birth rate", "value": "48.2%", "source": "RCT"}],
        )
        flat = _report_data_to_dict(data)
        assert flat["implications"] == ["Implication one", "Implication two"]
        assert flat["risks"][0]["title"] == "Validation lag"
        assert flat["action_required"] == ["Fund prospective validation."]
        assert flat["key_metrics"] == [
            {"metric": "Live birth rate", "value": "48.2%", "source": "RCT"}
        ]

    def test_defaults_empty_for_plain_reports(self) -> None:
        """Reports without product fields carry empty lists (backward compat)."""
        data = ReportData(
            title="t",
            generated_at="2026-08-10 00:00 UTC",
            domain="medical-research",
        )
        flat = _report_data_to_dict(data)
        assert flat["implications"] == []
        assert flat["risks"] == []
        assert flat["action_required"] == []
        assert flat["key_metrics"] == []


# ===================================================================
# Report path: prompt-size robustness (F3 blocker — bounded retry)
# ===================================================================


def _build_large_entry(i: int) -> dict[str, Any]:
    """An entry with a long title and a full 120-char summary.

    40 of these push the synthesis prompt past the ~12K-char size at which
    the configured LLM endpoint returns empty completions (F3 size sweep:
    11,908–12,827 chars → empty; ≤10,734 chars → non-empty).
    """
    return {
        "entry_id": f"entry-{i:03d}",
        "title": (
            "Long-form medical research study number %d on assisted "
            "reproductive technology outcomes and clinical practice" % i
        ),
        "summary": "S" * 120,
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{i:08d}/",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": float(100 - i),
        "tags": '["IVF"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    }


def _large_entries_and_grouping(
    n: int = 40,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return *n* long-title/long-summary entries in a single theme group."""
    entries = [_build_large_entry(i) for i in range(n)]
    groupings = [
        {"theme": "Reproductive Medicine Group", "description": "d", "entries": entries}
    ]
    return entries, groupings


class TestExecutiveSummaryPromptSizeRetry:
    """F3 robustness: an empty LLM response to an oversized synthesis prompt
    must trigger a bounded smaller-prompt retry instead of the theme-list
    fallback, so the differentiated product sections stay non-empty.

    The configured LLM endpoint returns EMPTY completions for report
    synthesis prompts ≳ ~11.9K chars (proven by the F3 size sweep), while the
    same dataset succeeds at ~6.8K–10.7K.  When the first call comes back
    empty (or without a usable executive summary), ``_generate_executive_summary``
    must re-call with a condensed entries-detail section — and the retry
    result must still carry the §2.4 product fields (implications / risks /
    action_required / key_metrics) parsed from the synthesis markdown.

    Round-2 (F3 re-verification): the endpoint's empty-completion behavior is
    no longer size-gated (bad windows return empty at ALL prompt sizes) and
    the model often omits the trailing §2.4 sections even when the synthesis
    succeeds.  So (1) the retry became a bounded multi-attempt loop with an
    injectable backoff sleep between attempts, and (2) when the synthesis
    succeeds but the parsed result lacks the product sections, a dedicated
    small prompt is issued (max 1) that asks for ONLY the §2.4 sections, and
    the parsed sections are merged back into the result.
    """

    def _synthesize_with(
        self,
        side_effect: Any,
        product_family: str = "enterprise-briefing",
        max_attempts: int | None = None,
        backoff_seconds: float | None = None,
        sleep_fn: Any = None,
    ) -> tuple[dict[str, Any], list[str], list[float]]:
        """Run the synthesis over 40 oversized entries; returns (result,
        captured_prompts, sleeps).  *side_effect* receives ``(prompt,
        call_no)``.  Sleeps are captured (never executed for real): the
        default sleeper records the backoff value each attempt boundary."""
        captured: list[str] = []
        sleeps: list[float] = []
        extractor = MagicMock()
        entries, groupings = _large_entries_and_grouping()

        def _fake(prompt: str) -> str:
            captured.append(prompt)
            return cast(str, side_effect(prompt, len(captured)))

        def _noop_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        with patch(
            "autoinfo.output._call_llm_for_report_synthesis", side_effect=_fake
        ):
            result = _generate_executive_summary(
                extractor,
                entries,
                groupings,
                product_family=product_family,
                max_synthesis_attempts=(
                    max_attempts if max_attempts is not None else 4
                ),
                retry_backoff_seconds=(
                    backoff_seconds if backoff_seconds is not None else 60.0
                ),
                sleep_fn=sleep_fn or _noop_sleep,
            )
        assert isinstance(result, dict)
        return result, captured, sleeps

    def test_large_prompt_empty_triggers_smaller_prompt_retry(self) -> None:
        """F3 scenario: oversized first prompt -> empty -> truncated-prompt
        retry -> non-empty executive summary AND differentiated sections."""
        # The 40-entry prompt lands in the F3 failing zone (≥ ~11.9K chars).
        def _side(prompt: str, call_no: int) -> str:
            return "" if call_no == 1 else _SAMPLE_REPORT_SYNTHESIS_MD

        result, captured, _ = self._synthesize_with(
            _side, product_family="enterprise-briefing"
        )
        # Reproduces the F3 prompt size that returns empty (12,429-char
        # enterprise prompt in the sweep).
        assert len(captured) == 2
        assert len(captured[0]) >= 11000
        # The retry fired with a condensed prompt, comfortably inside the
        # proven-safe zone (≤10.7K; ~6.8K for margin).
        assert len(captured[1]) < len(captured[0])
        assert len(captured[1]) <= 8000
        # The retry prompt still requests the product sections.
        assert "## Key Metrics" in captured[1]
        assert "## Action Required" in captured[1]
        # No theme-list fallback: real synthesis + non-empty product fields.
        assert result["executive_summary"]
        assert "This report covers" not in result["executive_summary"]
        assert result["implications"]
        assert result["risks"]
        assert result["action_required"]
        assert result["key_metrics"]
        assert result["key_metrics"][0] == {
            "metric": "Live birth rate",
            "value": "48.2% vs 39.5%",
            "source": "time-lapse RCT",
        }

    def test_first_call_without_executive_summary_triggers_retry(self) -> None:
        """A non-empty first response lacking an executive summary also
        triggers the smaller-prompt retry (not just the empty case)."""
        def _side(prompt: str, call_no: int) -> str:
            if call_no == 1:
                return "## Key Findings\n- something\n"
            return _SAMPLE_REPORT_SYNTHESIS_MD

        result, captured, _ = self._synthesize_with(
            _side, product_family="premium-briefing"
        )
        assert len(captured) == 2
        assert len(captured[1]) < len(captured[0])
        assert result["executive_summary"]
        assert result["implications"]
        assert result["risks"]
        assert result["action_required"]

    def test_all_attempts_empty_bounded_loop_then_theme_fallback(self) -> None:
        """If every attempt returns empty, fall back after exactly
        ``max_synthesis_attempts`` calls (bounded — no unbounded retry
        loop) with the theme-list fallback."""
        def _side(prompt: str, call_no: int) -> str:
            return ""

        result, captured, sleeps = self._synthesize_with(
            _side, product_family="enterprise-briefing"
        )
        assert len(captured) == 4
        # One backoff sleep between each of the 4 attempts (3 total).
        assert sleeps == [60.0, 60.0, 60.0]
        # Issue #217: the deterministic fallback must still carry non-empty
        # D1-required sections derived from the real entries — never empty
        # (an empty key_findings/recommendations would block delivery).
        assert result["executive_summary"]
        assert "This report covers" in result["executive_summary"]
        assert result["key_findings"]
        assert result["recommendations"]
        assert set(result) == {"executive_summary", "key_findings", "recommendations"}

    def test_retry_succeeds_but_omits_sections_fires_dedicated_prompt(
        self,
    ) -> None:
        """Round-2 defect 2: the retry succeeds (exec summary present) but
        omits the trailing §2.4 product sections -> a SECOND small dedicated
        prompt fires (max 1) asking for ONLY the product sections, and the
        parsed sections are merged so the result carries non-empty
        differentiated fields."""
        def _side(prompt: str, call_no: int) -> str:
            if call_no == 1:
                return ""
            if call_no == 2:
                return _SAMPLE_REPORT_SYNTHESIS_BASE_MD
            return _SAMPLE_PRODUCT_SECTIONS_ONLY_MD

        result, captured, _ = self._synthesize_with(
            _side, product_family="enterprise-briefing"
        )
        # primary (empty) + condensed retry (no sections) + dedicated prompt.
        assert len(captured) == 3
        # The dedicated prompt is small (well under the size concern) and
        # requests ONLY the product sections.
        assert len(captured[2]) < len(captured[1])
        assert len(captured[2]) <= 4000
        assert "## Implications" in captured[2]
        assert "## Key Metrics" in captured[2]
        # Base synthesis kept; product sections merged from the dedicated call.
        assert result["executive_summary"]
        assert "This report covers" not in result["executive_summary"]
        assert result["key_findings"]
        assert result["implications"]
        assert result["risks"][0] == {
            "title": "Validation lag",
            "likelihood": "high",
            "impact": "medium",
            "mitigation": "Run prospective trials before standardizing.",
        }
        assert result["action_required"]
        assert result["key_metrics"][0] == {
            "metric": "Live birth rate",
            "value": "48.2% vs 39.5%",
            "source": "time-lapse RCT",
        }

    def test_bad_window_survived_by_later_attempt_no_dedicated_prompt(
        self,
    ) -> None:
        """Round-2 defect 1: the endpoint returns empty for several minutes
        (bad window) then recovers; the bounded loop with backoff survives —
        attempt 4 succeeds with the FULL synthesis including sections, so no
        dedicated prompt is needed."""
        def _side(prompt: str, call_no: int) -> str:
            return "" if call_no <= 3 else _SAMPLE_REPORT_SYNTHESIS_MD

        result, captured, sleeps = self._synthesize_with(
            _side, product_family="enterprise-briefing"
        )
        assert len(captured) == 4
        assert sleeps == [60.0, 60.0, 60.0]
        assert result["executive_summary"]
        assert result["implications"]
        assert result["risks"]
        assert result["action_required"]
        assert result["key_metrics"]

    def test_max_attempts_and_backoff_are_injectable(self) -> None:
        """The loop bound and the backoff are parameters, so callers (and
        tests) can bound the loop tighter without changing behavior."""
        def _side(prompt: str, call_no: int) -> str:
            return ""

        sleeps: list[float] = []

        def _recording_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        result, captured, _ = self._synthesize_with(
            _side,
            product_family="enterprise-briefing",
            max_attempts=3,
            backoff_seconds=30.0,
            sleep_fn=_recording_sleep,
        )
        assert len(captured) == 3
        assert sleeps == [30.0, 30.0]
        assert result["executive_summary"]
        assert "This report covers" in result["executive_summary"]

    def test_small_prompt_first_call_succeeds_no_retry(self) -> None:
        """Fast path: when the first call succeeds, exactly one call is made
        and the result is unchanged (no retries, no backoff sleep, no
        dedicated prompt)."""
        def _side(prompt: str, call_no: int) -> str:
            return _SAMPLE_REPORT_SYNTHESIS_MD

        result, captured, sleeps = self._synthesize_with(
            _side, product_family="premium-briefing"
        )
        assert len(captured) == 1
        assert sleeps == []
        assert result["executive_summary"]
        assert result["implications"]
        assert result["risks"]
        assert result["action_required"]

    def test_default_report_family_unchanged_on_success(self) -> None:
        """Backward compat: the default ``report`` family makes a single
        call, requests no product sections, and behaves as before."""
        def _side(prompt: str, call_no: int) -> str:
            return _SAMPLE_REPORT_SYNTHESIS_BASE_MD

        result, captured, _ = self._synthesize_with(_side, product_family="report")
        assert len(captured) == 1
        assert "## Implications" not in captured[0]
        assert "## Key Metrics" not in captured[0]
        assert result["executive_summary"]
        assert result["key_findings"]
        assert result["implications"] == []
        assert result["risks"] == []
        assert result["action_required"] == []
        assert result["key_metrics"] == []
