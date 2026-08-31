"""Tests for issue #42 — low-value References relegation.

Paid-user audit: References mixes in URL-valid, real-but-off-domain noise
(promos / ticket sales, obituaries, celebrity/entertainment) for commercial
domains.  The fix re-ranks/drops low-value entries inside
``_sorted_ref_entries`` (domain-aware) WITHOUT touching the KB / manifest:

- Non-language-learning domain with >= ``_REF_LOW_VALUE_MIN_REAL_ENTRIES``
  clean candidates: flagged entries are dropped from References entirely.
- Non-language-learning domain with few clean candidates: flagged entries
  survive ONLY at the tail (below every clean entry).
- Language-learning domains (english/french/spanish/...-learning): cultural /
  historical teaching material is kept at the tail, never dropped.
- Signals are PHRASE-SHAPED — a legit sentence ("pricing models to promote
  value", "discounts up to 10% in regions") never fires.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    _REF_LOW_VALUE_MIN_REAL_ENTRIES,
    _low_value_signal_penalty,
    _normalize_digest_product_context,
    _sorted_ref_entries,
    generate_digest,
)

PROMO_TITLE = (
    "Tonight marks your last chance to save up to $300 on a "
    "TechCrunch Disrupt pass"
)
EV_TITLE = "EV maker rolls out three-speed drivetrain for highway efficiency"
SKI_TITLE = "A 26-year-old ski mountaineer has died after a fall on Gran Paradiso"


def _entry(
    entry_id: str,
    title: str,
    summary: str,
    relevance: float,
    domain: str = "b2b",
) -> dict[str, Any]:
    """A config-shaped KB entry in the exact shape the reference paths use."""
    return {
        "entry_id": entry_id,
        "title": title,
        "summary": summary,
        "source_url": f"https://example.com/{entry_id}",
        "source_type": "rss",
        "source_platform": "source",
        "domain": domain,
        "relevance_score": relevance,
        "language": "en",
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-08-19T10:00:00Z",
    }


def _clean_entries(n: int, domain: str = "b2b") -> list[dict[str, Any]]:
    """``n`` clean summary-bearing entries, relevance ``n..1``."""
    return [
        _entry(
            f"clean-{i}",
            f"Real story {i}: quarterly growth across the sector",
            f"Analyst summary {i} covering fundamentals and outlook.",
            float(n - i + 1),
            domain=domain,
        )
        for i in range(1, n + 1)
    ]


def _fail_open_sources(domain: str) -> list[Any]:
    """FAIL-OPEN (drift filter #119): this fixture KB is synthetic (hosts on
    example.com, platform "source") — no real config source matches, so
    declare none active and keep everything (the tests exercise low-value
    pruning, not source drift)."""
    del domain
    return []


def _titles(entries: list[dict[str, Any]]) -> list[str]:
    return [str(e.get("title") or "") for e in entries]


def _flat_digest(entries: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    """Render the flat product-template context for the digest path."""
    return _normalize_digest_product_context({
        "title": f"Weekly Digest \u2014 {domain}",
        "domain": domain,
        "period": "weekly",
        "period_label": "Weekly",
        "date_from": "2026-08-03",
        "date_to": "2026-08-10",
        "generated_at": "2026-08-10T00:00:00+00:00",
        "entries": entries,
        "llm_synthesis": {
            "executive_summary": "Synthesis.",
            "key_findings": [],
            "recommendations": [],
        },
        "target_audience": "",
        "source_tier_badge": False,
    }, domain)


# ---------------------------------------------------------------------------
# (a) Signal scoring: phrase-shaped, deterministic, no false positives
# ---------------------------------------------------------------------------


class TestLowValueSignalPenalty:
    def test_promo_signal_on_disrupt_pass(self) -> None:
        assert _low_value_signal_penalty(
            _entry("p1", PROMO_TITLE, "Save up to $300.", 99)
        ) >= 1

    def test_obituary_signal_on_ski_mountaineer(self) -> None:
        assert _low_value_signal_penalty(
            _entry("s1", SKI_TITLE, "Rescue teams recovered the body.", 80,
                   domain="italian-learning")
        ) >= 1

    def test_celebrity_signal_on_dolly_parton(self) -> None:
        assert _low_value_signal_penalty(
            _entry("c1", "Dolly Parton has died at age 80, family confirms",
                   "Country legend passes.", 90)
        ) >= 1

    def test_low_value_is_deterministic(self) -> None:
        entry = _entry("p2", PROMO_TITLE, "Save up to $300.", 99)
        assert _low_value_signal_penalty(entry) == _low_value_signal_penalty(
            {**entry}
        )

    def test_do_not_overfilter_legit_sentences(self) -> None:
        """\"promote\" / \"discount\" as verbs inside legit business sentences
        must NOT fire (issue #42 Do-NOT)."""
        legit = _entry(
            "ok1",
            "Pricing models to promote value across enterprise tiers",
            "Discounts up to 10% in regions remain under review.",
            70,
        )
        assert _low_value_signal_penalty(legit) == 0


# ---------------------------------------------------------------------------
# (b) _sorted_ref_entries: relegation / drop behavior
# ---------------------------------------------------------------------------


class TestSortedRefEntriesRelegation:
    def test_b2b_drops_promo_when_enough_real_entries(self) -> None:
        """>= MIN_REAL clean entries -> promo dropped from References."""
        entries = _clean_entries(_REF_LOW_VALUE_MIN_REAL_ENTRIES)
        entries.append(_entry("promo", PROMO_TITLE, "Save up to $300.", 99))
        titles = _titles(_sorted_ref_entries(entries, domain="b2b"))
        assert PROMO_TITLE not in titles

    def test_b2b_keeps_promo_at_tail_when_few_real_entries(self) -> None:
        """< MIN_REAL clean entries -> promo survives ONLY as the last entry."""
        entries = _clean_entries(5)
        entries.append(_entry("promo", PROMO_TITLE, "Save up to $300.", 99))
        titles = _titles(_sorted_ref_entries(entries, domain="b2b"))
        assert len(titles) == 6
        assert titles[-1] == PROMO_TITLE
        assert all(t != PROMO_TITLE for t in titles[:-1])

    def test_strong_ev_story_stays_in_references(self) -> None:
        """A normal strong domain item stays in References, above any tail."""
        entries = _clean_entries(_REF_LOW_VALUE_MIN_REAL_ENTRIES)
        ev = _entry("ev", EV_TITLE, "Three-speed drivetrain hits the road.", 95)
        entries.append(ev)
        entries.append(_entry("promo", PROMO_TITLE, "Save up to $300.", 99))
        titles = _titles(_sorted_ref_entries(entries, domain="b2b"))
        assert EV_TITLE in titles
        assert EV_TITLE in titles[: _REF_LOW_VALUE_MIN_REAL_ENTRIES]

    def test_language_learning_keeps_cultural_item_at_tail(self) -> None:
        """italian-learning: obituary-framed cultural story is NOT dropped;
        it stays in the list at the tail (teaching material survives)."""
        # Many clean language items + a high-relevance cultural story.
        entries = _clean_entries(30, domain="italian-learning")
        ski = _entry("ski", SKI_TITLE,
                     "Rescue teams recovered the body after a fall.", 99,
                     domain="italian-learning")
        entries.append(ski)
        titles = _titles(_sorted_ref_entries(entries, domain="italian-learning"))
        assert SKI_TITLE in titles
        assert titles[-1] == SKI_TITLE
        # The tail is AFTER all clean items even though relevance is highest.
        assert titles.index(SKI_TITLE) >= 30

    def test_language_learning_still_relegates_rankings(self) -> None:
        """Even in a language-learning domain, flagged items rank below all
        clean items (reduced penalty = tail, not deleted)."""
        entries = [
            _entry("a", "Daily grammar drill: present tense", "Clean.", 10,
                   domain="english-learning"),
            _entry("b", "Verb conjugation practice", "Clean.", 9,
                   domain="english-learning"),
            _entry("c", f"{PROMO_TITLE}", "Ad copy.", 99, domain="english-learning"),
        ]
        titles = _titles(_sorted_ref_entries(entries, domain="english-learning"))
        assert titles[-1] == PROMO_TITLE


# ---------------------------------------------------------------------------
# (c) Digest-path integration (acceptance): the b2b *digest* context
# ---------------------------------------------------------------------------


class TestDigestPathLowValueRelegation:
    def test_b2b_digest_omits_promo_and_keeps_ev_story(self) -> None:
        entries = _clean_entries(_REF_LOW_VALUE_MIN_REAL_ENTRIES)
        entries.append(_entry("ev", EV_TITLE, "Three-speed drivetrain on road.", 95))
        entries.append(_entry("promo", PROMO_TITLE, "Save up to $300.", 99))
        flat = _flat_digest(entries, "b2b")
        ref_titles = [r["title"] for r in flat["references"]]
        assert PROMO_TITLE not in ref_titles
        assert EV_TITLE in ref_titles

    def test_b2b_digest_few_entries_promo_at_tail(self) -> None:
        entries = _clean_entries(5)
        entries.append(_entry("promo", PROMO_TITLE, "Save up to $300.", 99))
        flat = _flat_digest(entries, "b2b")
        ref_titles = [r["title"] for r in flat["references"]]
        assert ref_titles[-1] == PROMO_TITLE
        assert all(t != PROMO_TITLE for t in ref_titles[:-1])

    def test_language_digest_keeps_cultural_item_at_tail(self) -> None:
        entries = _clean_entries(10, domain="italian-learning")
        entries.append(_entry("ski", SKI_TITLE,
                              "Rescue teams recovered the body.", 99,
                              domain="italian-learning"))
        flat = _flat_digest(entries, "italian-learning")
        ref_titles = [r["title"] for r in flat["references"]]
        assert SKI_TITLE in ref_titles
        assert ref_titles[-1] == SKI_TITLE


# ---------------------------------------------------------------------------
# (d) Issue #46 — Executive Summary synthesis candidates are pruned
# ---------------------------------------------------------------------------
# #42 filters References, but the Executive Summary is LLM-synthesized from a
# candidate entry list that was NOT filtered — so a low-value obituary could
# still lead the summary's first line.  The synthesis-prompt candidate list
# now goes through the SAME ``_sorted_ref_entries`` relegation, while the full
# ``entries`` list still flows to References unchanged.

OBIT_TITLE = "Dolly Parton has died at age 80, family confirms"


def _obit_entry(domain: str = "b2b") -> dict[str, Any]:
    return _entry(
        "obit-46",
        OBIT_TITLE,
        "Country music legend passes away surrounded by family.",
        99.0,
        domain=domain,
    )


class TestSynthesisPromptLowValueFilter:
    """End-to-end through ``generate_digest``: the LLM synthesis prompt's
    entry list is pruned/demoted exactly like References (#42), while the
    full entries list still reaches the rendered References section."""

    def _capture(self, entries: list[dict[str, Any]], domain: str) -> tuple[str, str]:
        captured: dict[str, Any] = {}

        def _store(*_args: Any, **_kwargs: Any) -> MagicMock:
            store = MagicMock()
            store.list_entries.return_value = entries
            return store

        def _llm(prompt: str, config: Any = None) -> dict[str, Any]:
            captured["prompt"] = prompt
            return {
                "executive_summary": "Synthesis.",
                "key_findings": [],
                "recommendations": [],
            }

        with (
            patch("autoinfo.output.KBStore", side_effect=_store),
            patch("autoinfo.output._call_llm_for_digest", side_effect=_llm),
            patch(
                "autoinfo.output._get_domain_source_configs",
                side_effect=_fail_open_sources,
            ),
        ):
            result = generate_digest(domain=domain, period="weekly")
        assert isinstance(result, str)
        return cast(str, captured["prompt"]), result

    def test_synthesis_candidates_exclude_obituary(self) -> None:
        """>= MIN_REAL clean entries -> the obituary is dropped from the
        synthesis candidates (not in the prompt at all).  The full entries
        list still flows to the rendered body for traceability (issue #46:
        only the synthesis candidates — and References via #42 — are pruned;
        entries are never deleted).

        Uses ``tech-ai-developer``: the b2b demo domain's #56
        ``exclude_keywords`` (``has died``/``passed away``/``obituary``)
        removes the obituary BEFORE the low-value logic runs, which would
        make this test pass for the wrong reason."""
        entries = _clean_entries(
            _REF_LOW_VALUE_MIN_REAL_ENTRIES, domain="tech-ai-developer"
        )
        entries.append(_obit_entry("tech-ai-developer"))
        prompt, result = self._capture(entries, "tech-ai-developer")
        assert OBIT_TITLE not in prompt
        assert "Real story 20: quarterly growth across the sector" in prompt
        assert OBIT_TITLE in result

    def test_synthesis_keeps_obituary_at_tail_when_few_entries(self) -> None:
        """< MIN_REAL clean entries -> the obituary survives in the
        synthesis candidates ONLY at the tail (never in the leading
        enumeration)."""
        entries = _clean_entries(5, domain="tech-ai-developer")
        entries.append(_obit_entry("tech-ai-developer"))
        prompt, _ = self._capture(entries, "tech-ai-developer")
        assert OBIT_TITLE in prompt
        assert prompt.index(OBIT_TITLE) > prompt.rindex("Real story ")

    def test_lang_learning_synthesis_demotes_obituary_to_tail(self) -> None:
        """Language-learning keeps teaching material: the obituary stays in the
        synthesis candidates but demoted below every clean entry."""
        entries = _clean_entries(
            _REF_LOW_VALUE_MIN_REAL_ENTRIES, domain="english-learning"
        )
        entries.append(_obit_entry("english-learning"))
        prompt, result = self._capture(entries, "english-learning")
        assert OBIT_TITLE in prompt
        obit_idx = prompt.index(OBIT_TITLE)
        assert "Real story " not in prompt[obit_idx:]
        assert OBIT_TITLE in result
