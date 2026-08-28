"""Tests for issue #10 — premium/enterprise ``Actions`` depth.

Two levers close the #10 gap:

1. **Prompt-side granularity** — ``_REPORT_PRODUCT_SYNTHESIS_PROMPTS`` (the
   premium-briefing / enterprise-briefing family prompts, shared via
   ``_REPORT_PRODUCT_BASE_SECTIONS``) must instruct the model that every
   ``Action Required`` bullet MUST name a concrete object (WHAT — which
   entity/product/model) and a timeframe or trigger (WHEN).  The WHO-actor
   requirement already exists; the gap #10 names is object + timeframe
   granularity — bare verbs like "Track AI model releases" / "Monitor Y"
   must be forbidden.

2. **Deterministic weak-action guard (premium-only)** — ``_fill_premium_
   takeaway_fields`` gains an opt-in ``weak`` predicate (default keeps the
   existing ``_usable`` behavior).  When the trigger fires and a takeaway's
   ``Actions`` line is weak (``_is_weak_analysis``: <40 chars / formulaic
   "Track "/"Monitor developments around" prefixes), the action is replaced
   per-index from ``_deterministic_takeaway_fields`` so the rendered premium
   takeaway ships a concrete KB-derived action.  Scope narrowing (Oracle
   SF2): the guard is PREMIUM-ONLY — enterprise renders a flat ``- [ ]``
   checkbox list that ``_so_what_substantive`` requires to stay checkbox-
   shaped, so enterprise is NOT wired into the guard (prompt constraint
   only).
"""

from __future__ import annotations

from typing import Any

from autoinfo.output import (
    _REPORT_PRODUCT_SYNTHESIS_PROMPTS,
    _deterministic_takeaway_fields,
    _fill_premium_takeaway_fields,
)

# ===================================================================
# (a) Prompt-side WHAT/WHEN granularity constraint
# ===================================================================


class TestPromptActionGranularity:
    """The premium/enterprise synthesis prompt must demand object+timeframe."""

    def test_premium_prompt_requires_what_and_when(self) -> None:
        """premium-briefing's prompt constant carries the WHAT/WHEN clause."""
        prompt = _REPORT_PRODUCT_SYNTHESIS_PROMPTS["premium-briefing"]
        assert "Action Required" in prompt
        # The WHAT lever: the action must name a concrete object (entity/
        # product/model) — never a bare verb.
        assert "concrete object" in prompt.lower() or "name the" in prompt.lower()
        assert "which" in prompt.lower()  # "WHICH ... " WHAT wording
        # The WHEN lever: a timeframe or trigger is mandatory.
        assert "timeframe" in prompt.lower() or "when" in prompt.lower()
        assert "trigger" in prompt.lower()
        # The anti-example: bare verbs without object/timeframe are forbidden.
        assert "Track" in prompt  # explicit anti-example wording

    def test_enterprise_prompt_requires_what_and_when(self) -> None:
        """enterprise-briefing inherits the same WHAT/WHEN clause (prompt-side
        only — no guard wiring on the enterprise render path)."""
        prompt = _REPORT_PRODUCT_SYNTHESIS_PROMPTS["enterprise-briefing"]
        assert "Action Required" in prompt
        assert "concrete object" in prompt.lower() or "name the" in prompt.lower()
        assert "timeframe" in prompt.lower() or "when" in prompt.lower()
        assert "trigger" in prompt.lower()
        assert "Track" in prompt  # anti-example wording


# ===================================================================
# (b) Weak-action fallback (premium) — KB-derived specific action
# ===================================================================

_PREMIUM_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "e1",
        "title": "OpenAI GPT-5",
        "summary": "OpenAI shipped GPT-5 with benchmark results published.",
        "source_url": "https://openai.com/gpt-5",
        "relevance_score": 95.0,
    },
    {
        "entry_id": "e2",
        "title": "Google Gemini Ultra",
        "summary": "Gemini Ultra benchmarks landed in the AI evaluation hub.",
        "source_url": "https://blog.google/gemini-ultra",
        "relevance_score": 88.0,
    },
]


class TestPremiumWeakActionFallback:
    """``weak=True`` fires the deterministic KB-derived action fallback."""

    def test_weak_action_replaced_with_kb_derived_specific_action(self) -> None:
        """A weak ("Track AI model releases") LLM action is replaced per-index
        with the KB-derived specific action ("Track OpenAI GPT-5 ... by the
        next period"), index-aligned with the entries."""
        _, _, actions = _fill_premium_takeaway_fields(
            ["_No implication captured for this takeaway._", "_No implication."],
            None,
            ["Track AI model releases", "Monitor AI funding"],
            _PREMIUM_ENTRIES,
            "ai-commercial",
            weak=True,
        )
        assert len(actions) == 2
        # Weak actions replaced with the KB-derived specific fallback.
        assert "OpenAI GPT-5" in actions[0], actions
        assert "https://openai.com/gpt-5" in actions[0], actions
        assert "Gemini Ultra" in actions[1], actions
        # The generic verb-only phrasing is gone.
        assert "Track AI model releases" not in actions
        assert "Monitor AI funding" not in actions

    def test_substantive_llm_actions_preserved_under_weak(self) -> None:
        """A substantive (WHAT/WHEN-shaped) LLM action survives ``weak=True``
        — the guard only replaces what ``_is_weak_analysis`` flags."""
        substantive = "CMO: ship the Q3 pricing experiment to 10% of customers by 2026-09-15"
        _, _, actions = _fill_premium_takeaway_fields(
            None,
            None,
            ["Track AI model releases", substantive],
            _PREMIUM_ENTRIES,
            "ai-commercial",
            weak=True,
        )
        assert len(actions) == 2
        assert "OpenAI GPT-5" in actions[0], actions  # weak one replaced
        assert actions[1] == substantive, actions  # substantive one kept

    def test_weak_guard_is_index_aligned(self) -> None:
        """Per-index replacement never mis-pairs: action i maps to entry i.
        With one weak action in slot 0, the fallback for slot 0 (entry 0)
        must pair with OpenAI GPT-5, not Gemini Ultra."""
        _, _, actions = _fill_premium_takeaway_fields(
            None,
            None,
            ["Track AI model releases", "Fund prospective validation trials"],
            _PREMIUM_ENTRIES,
            "ai-commercial",
            weak=True,
        )
        assert "OpenAI GPT-5" in actions[0]
        assert "Gemini Ultra" not in actions[0]
        # The LLM-produced list length is preserved (no padding/truncation).
        assert len(actions) == 2

    def test_weak_fallback_matches_deterministic_shape(self) -> None:
        """The weak-replaced action equals the deterministic per-entry action
        (``_deterministic_takeaway_fields`` at the same index)."""
        _, _, deterministic = _deterministic_takeaway_fields(_PREMIUM_ENTRIES, "ai-commercial")
        _, _, actions = _fill_premium_takeaway_fields(
            None,
            None,
            ["Track AI model releases", "Monitor AI funding"],
            _PREMIUM_ENTRIES,
            "ai-commercial",
            weak=True,
        )
        assert actions[0] == deterministic[0]
        assert actions[1] == deterministic[1]

    def test_weak_guard_is_opt_in(self) -> None:
        """Default (``weak=False``) preserves the ``_usable`` behavior: a
        non-empty action is kept even when weak-shaped (existing premium
        callers/tests unchanged)."""
        _, _, actions = _fill_premium_takeaway_fields(
            None,
            None,
            ["Track AI model releases", ""],
            _PREMIUM_ENTRIES,
            "ai-commercial",
        )
        assert actions[0] == "Track AI model releases", actions  # kept as-is
        # Empty slot still backfilled (existing behavior) — the fallback for
        # the second-ranked entry (Gemini Ultra, relevance 88 < GPT-5 95).
        assert "Gemini Ultra" in actions[1], actions


# ===================================================================
# (c) Regression: default path (test_digest_context_normalization parity)
# ===================================================================


class TestDefaultUsablePathUnchanged:
    """The default (no ``weak``) path keeps #357 behavior byte-for-byte."""

    def test_placeholder_backfill_still_fires(self) -> None:
        """``_No ..._`` placeholders are backfilled per-index exactly like the
        pre-#10 default (mirrors
        ``test_digest_context_normalization.py::
        test_premium_action_slot_placeholder_backfilled``)."""
        entries = [
            {
                "title": "Startup A raises $50M",
                "source_url": "https://x.com/1",
                "summary": "Series B led by fund X",
                "relevance_score": 90.0,
            },
            {
                "title": "Startup B partners with Enterprise Co",
                "source_url": "https://x.com/2",
                "summary": "distribution deal",
                "relevance_score": 80.0,
            },
        ]
        impl, risks, actions = _fill_premium_takeaway_fields(
            ["_No implication captured for this takeaway._", "Real implication"],
            None,
            ["_No follow-up actions suggested._", ""],
            entries,
            "ai-commercial",
        )
        assert len(impl) == len(risks) == len(actions) == 2
        for slot in impl + actions:
            assert "_No " not in slot
            assert slot.strip()
        # Issue #54: the fallback is honest — it never fabricates a fake
        # "medium/medium" risk or an "Uncertain trajectory" pseudo-analysis.
        assert "Revisit Startup A" in actions[0]
        assert impl[1] == "Real implication"
        assert "No differentiated risk signal" in risks[0]["title"]
        assert risks[0]["likelihood"] == "n/a" and risks[0]["impact"] == "n/a"
        assert "medium" not in str(risks[0]).lower()


# ===================================================================
# (e) Issue #54: honest deterministic fallback (no fabricated analysis)
# ===================================================================


class TestIssue54HonestFallback:
    """#54 paid review: the premium deterministic fallback must never
    impersonate real analysis.  It states plainly that no differentiated
    signal was captured this period and rates risk likelihood/impact as
    ``n/a`` — never a fake ``Uncertain trajectory for …`` + medium/medium."""

    def test_deterministic_fields_are_honest(self) -> None:
        impl, risks, actions = _deterministic_takeaway_fields(
            _PREMIUM_ENTRIES, "ai-commercial"
        )
        assert len(impl) == len(risks) == len(actions) == 2
        for text in impl:
            assert "No differentiated signal captured for" in text, text
            assert "revisit next period" in text.lower(), text
        for text in actions:
            assert text.startswith("Revisit "), text
            assert "differentiated" in text, text
        for r in risks:
            assert "No differentiated risk signal" in r["title"]
            assert r["likelihood"] == "n/a", r
            assert r["impact"] == "n/a", r
            assert "medium" not in str(r).lower(), r
            assert "Uncertain trajectory" not in str(r), r
        # No pre-#54 formulaic boilerplate anywhere in the fallback.
        rendered = "\n".join(
            [*impl, *map(str, actions), *map(str, risks)]
        )
        assert "Monitor developments around" not in rendered
        assert "Uncertain trajectory for" not in rendered
        assert "for validation in the next period" not in rendered


# ===================================================================
# (d) Enterprise NOT wired into the weak guard
# ===================================================================


class TestEnterpriseNotWired:
    """Enterprise keeps its flat checkbox contract — no weak-action guard on
    the enterprise render path (scope narrowing, Oracle SF2)."""

    def test_enterprise_prompt_is_only_what_when_constraint(self) -> None:
        """The enterprise lever is the prompt-side WHAT/WHEN clause only; the
        deterministic guard lives in ``_fill_premium_takeaway_fields``, which
        the enterprise render path does not invoke with ``weak=True``."""
        # The prompt constant carries the constraint…
        assert "Action Required" in _REPORT_PRODUCT_SYNTHESIS_PROMPTS["enterprise-briefing"]
        # …and the guard is documented as premium-only: the function signature
        # exposes ``weak`` (opt-in) — enterprise callers do not pass it.
        import inspect

        sig = inspect.signature(_fill_premium_takeaway_fields)
        assert "weak" in sig.parameters

    def test_enterprise_checkbox_shape_is_so_what_compatible(self) -> None:
        """Enterprise ``action_required`` items render as ``- [ ]`` checkboxes
        (``enterprise-briefing.md.j2`` line 53) that ``_so_what_substantive``
        requires — so the deterministic fallback (a non-checkbox sentence) is
        NOT applied on the enterprise path.  This pins the render contract so
        the scope narrowing cannot silently regress."""
        from autoinfo.output import PRODUCT_TEMPLATES
        from autoinfo.validation_matrix import _so_what_substantive

        enterprise = next(
            row["template"] for row in PRODUCT_TEMPLATES if row["name"] == "enterprise-briefing"
        )
        # Flat context with checkbox-shaped actions — what the LLM synthesis
        # produces for enterprise (never the deterministic fallback).
        flat = {
            "title": "t",
            "domain": "ai-commercial",
            "executive_summary": "Summary.",
            "key_findings": [{"text": "F1"}],
            "references": [{"title": "R1", "source_url": "https://e/1"}],
            "action_required": ["Track AI model releases by 2026-09-30."],
            "risks": [],
            "key_metrics": [],
            "recommendations": ["Recommend."],
        }
        rendered = enterprise.render("enterprise-briefing", "md", flat)
        # The deterministic fallback phrasing is absent (guard not applied).
        assert "for validation in the next period" not in rendered
        # The checkbox contract that _so_what_substantive requires is intact.
        assert "- [ ] Track AI model releases by 2026-09-30." in rendered
        result = _so_what_substantive(rendered, "ai-commercial", "enterprise-briefing")
        assert result.passed, result.details
