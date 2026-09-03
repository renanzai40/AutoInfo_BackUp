"""Tests for the all-dimension product quality gate (scripts/quality_gate.py).

Issue #188: the R2-review battery (formerly /tmp/m1_review_battery_r2.py) is
versioned as scripts/quality_gate.py — the standard delivery quality gate.
These tests lock the per-file rules (F1-F4 format, C1-C5 content), the CJK
bilingual exemption, the cross-product identity-conflict detector (X1), and
the CLI exit codes (0 pass / 1 defects / 2 usage).

The check functions are pure and operate on strings/paths, so no filesystem
beyond tmp_path fixtures, no network, no LLM.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# scripts/ is not a package — load it via sys.path like the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import quality_gate as qg  # noqa: E402  (sys.path insert above)

# ---------------------------------------------------------------------------
# F1 empty shell
# ---------------------------------------------------------------------------


def test_f1_clean_text_passes() -> None:
    assert qg.find_empty_shell("x" * 600) == []


def test_f1_tiny_text_fails() -> None:
    defects = qg.find_empty_shell("short")
    assert len(defects) == 1
    assert defects[0].startswith("F1 empty shell")


def test_f1_boundary_just_under() -> None:
    # 499 non-space bytes < 500 floor.
    assert len(qg.find_empty_shell("x" * 499)) == 1


def test_f1_boundary_just_over() -> None:
    assert qg.find_empty_shell("x" * 500) == []


# ---------------------------------------------------------------------------
# F2 placeholders
# ---------------------------------------------------------------------------


def test_f2_no_placeholders() -> None:
    assert qg.find_placeholders("A fully written product with no markers.") == []


def test_f2_placeholder_detected() -> None:
    for marker in ("TODO", "PLACEHOLDER", "TBD", "{{", "[[待", "待补", "占位"):
        assert len(qg.find_placeholders(f"see {marker} here")) == 1, marker


# ---------------------------------------------------------------------------
# F3 doubled citations
# ---------------------------------------------------------------------------


def test_f3_same_source_doubled_fails() -> None:
    text = (
        "The trial studied equine subjects (Source: https://doi.org/abc) "
        "(Source: https://doi.org/abc)."
    )
    defects = qg.find_doubled_citations(text)
    assert len(defects) == 1
    assert "doi.org/abc" in defects[0]


def test_f3_different_sources_not_doubled() -> None:
    # Back-to-back DIFFERENT sources are not a doubled citation.
    text = (
        "A (Source: https://a.com/1) (Source: https://b.com/2) "
        "(Source: https://a.com/1)."
    )
    assert qg.find_doubled_citations(text) == []


def test_f3_multi_source_citation_legal() -> None:
    # "(Sources: A and B)" is a legal one-item-multi-source citation.
    text = "Both matter (Sources: https://a.com/1 and https://b.com/2)."
    assert qg.find_doubled_citations(text) == []


# ---------------------------------------------------------------------------
# F4 forbidden words
# ---------------------------------------------------------------------------


def test_f4_forbidden_word_detected_case_insensitive() -> None:
    defects = qg.find_forbidden_words("HORSE trials are common", ["horse"])
    assert len(defects) == 1
    assert "horse" in defects[0]


def test_f4_no_forbidden_words() -> None:
    assert qg.find_forbidden_words("Clean text", ["horse"]) == []


def test_f4_empty_wordlist_noop() -> None:
    assert qg.find_forbidden_words("Clean text", []) == []


# ---------------------------------------------------------------------------
# C1 synthesized fake entries
# ---------------------------------------------------------------------------


def test_c1_fake_entry_markers_detected() -> None:
    for marker in (
        "AI 商业周报 3",
        "金融市场情报 7",
        "医学研究前沿 2",
        "英语学习素材 4",
        "\nweekly:\n",
    ):
        assert len(qg.find_fake_entries(f"Summary: {marker} covered")) == 1, marker


def test_c1_zh_summary_line_start_marker() -> None:
    # A synthesized placeholder summary STARTS a line with "本期...要点"
    # (mirrors output._SUMMARY_PLACEHOLDER_RE).
    assert len(qg.find_fake_entries("\n本期内容要点总结如下\n")) == 1


def test_c1_weekly_in_editorial_title_not_fake() -> None:
    # "SaaS Weekly: Strategic Insights" is a real editorial title, not a
    # synthesized entry placeholder — must NOT be flagged.
    assert (
        qg.find_fake_entries(
            "# B2B & Enterprise SaaS Weekly: Strategic Insights and Trends"
        )
        == []
    )


def test_c1_clean_text_passes() -> None:
    assert (
        qg.find_fake_entries(
            "This week AI startups raised significant rounds across the sector."
        )
        == []
    )


# ---------------------------------------------------------------------------
# C2 log / stack / LLM leaks
# ---------------------------------------------------------------------------


def test_c2_llm_error_text_detected() -> None:
    # Each fragment is detected at least once (some fragments contain two
    # markers — "Give Feedback" also carries BerriAI, "```json" also carries
    # the raw JSON prefix).
    for fragment in (
        "LiteLLM.Info: If you need to debug",
        "Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues",
        "use `litellm._turn_on_debug()`",
        "```json\n{\"title\": \"raw\"}",
        "Traceback (most recent call last):",
    ):
        assert qg.find_llm_leaks(fragment), fragment


def test_c2_clean_text_passes() -> None:
    assert qg.find_llm_leaks("A clean product with real analysis.") == []


# ---------------------------------------------------------------------------
# C3 CJK residue + bilingual exemption
# ---------------------------------------------------------------------------


def test_c3_english_domain_cjk_fails() -> None:
    text = "English product with 中文残留内容混入." * 4  # > 5 CJK chars
    defects = qg.find_cjk_residue(text, "medical-research")
    assert len(defects) == 1
    assert "CJK residue" in defects[0]


def test_c3_learning_domain_exempt() -> None:
    text = "English product with 中文残留内容混入." * 4
    assert qg.find_cjk_residue(text, "english-learning") == []


def test_c3_low_cjk_count_under_threshold_passes() -> None:
    # A single stray ideograph (e.g. in a code sample) is not a leak.
    assert qg.find_cjk_residue("One 字 in a code sample", "medical-research") == []


def test_c3_threshold_respected() -> None:
    text = "字字字字字字"  # 6 CJK chars
    assert qg.find_cjk_residue(text, "medical-research", threshold=10) == []
    assert len(qg.find_cjk_residue(text, "medical-research", threshold=5)) == 1


def test_c3_learning_domains_all_exempt() -> None:
    text = "字" * 20
    for domain in ("english-learning", "french-learning", "korean-learning",
                   "language-learning"):
        assert qg.find_cjk_residue(text, domain) == [], domain


def test_c3_ai_commercial_bilingual_exempt() -> None:
    # Issue #190/#193: ai-commercial is a bilingual domain (36kr Chinese
    # source, seed default_language "") — CJK residue is by-design, not a
    # leak, and the standard gate command must not false-flag it.
    text = "中文字符残留" * 4  # well above threshold
    assert qg.find_cjk_residue(text, "ai-commercial") == []
    assert qg.find_cjk_residue(text, "cross-domain") == []


# ---------------------------------------------------------------------------
# C4 truncated lines
# ---------------------------------------------------------------------------


def test_c4_truncated_line_detected() -> None:
    line = (
        "This is a deliberately truncated sentence that never finishes with "
        "any punctuation and keeps going past eighty characters into grey zone"
    )
    defects = qg.find_truncated_lines(line)
    assert len(defects) == 1
    assert "C4 truncated line" in defects[0]


def test_c4_complete_long_sentence_passes() -> None:
    line = (
        "This is a completely finished sentence that ends with proper "
        "terminal punctuation and is more than eighty characters long."
    )
    assert qg.find_truncated_lines(line) == []


def test_c4_markdown_constructs_skipped() -> None:
    constructs = [
        "# "
        + "Heading without punctuation that is quite long indeed and exceeds "
        "eighty characters comfortably",
        "- "
        + "list item without terminal punctuation but still very long indeed "
        "exceeding eighty characters",
        "[a very long link label that exceeds eighty characters easily without"
        " any punctuation at all](https://example.com/very/long/path)",
        "| " + "table" + " | "
        + "cell content without punctuation but quite long indeed exceeding "
        "eighty characters total" + " |",
    ]
    assert qg.find_truncated_lines("\n".join(constructs)) == []


def test_c4_line_ending_in_citation_paren_passes() -> None:
    # Real products end key-finding bullets with (Source: <url>).
    line = (
        "OpenAI raised a significant funding round this period with "
        "participation from leading investors (Source: https://techcrunch.com/x)"
    )
    assert qg.find_truncated_lines(line) == []


# ---------------------------------------------------------------------------
# C5 source integrity
# ---------------------------------------------------------------------------


def test_c5_all_body_citations_in_references(tmp_path: Path) -> None:
    text = (
        "Claim one (Source: https://a.com/1). Claim two (Source: https://b.com/2).\n"
        "## References\n"
        "1. https://a.com/1\n"
        "2. https://b.com/2\n"
    )
    # A report-family file carries the References section.
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    assert qg.find_source_integrity(text, path=f) == []


def test_c5_dangling_body_citation_not_in_references(tmp_path: Path) -> None:
    text = (
        "Claim (Source: https://a.com/1). Fabricated (Source: https://fake.com/x).\n"
        "## References\n"
        "1. https://a.com/1\n"
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    defects = qg.find_source_integrity(text, path=f)
    assert len(defects) == 1
    assert "fake.com/x" in defects[0]


def test_c5_reference_prefix_of_body_url_aligns(tmp_path: Path) -> None:
    # The References renderer may truncate a long URL while the body cites the
    # full form — a path-boundary prefix aligns to the same article.
    text = (
        "Claim (Source: https://www.france24.com/fr/afrique/20260825-ceuta-ils-"
        "mangent-les-chats-fausses-images-rumeur-persistante-20260825).\n"
        "## References\n"
        "1. https://www.france24.com/fr/afrique/20260825-ceuta-ils-mangent-les-"
        "chats-fausses-images-rumeur-persistante\n"
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    assert qg.find_source_integrity(text, path=f) == []


def test_c5_markdown_link_citation_checked(tmp_path: Path) -> None:
    text = (
        "See [the story](https://a.com/1) for detail.\n"
        "## References\n"
        "1. https://b.com/2\n"
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    defects = qg.find_source_integrity(text, path=f)
    assert len(defects) == 1
    assert "a.com/1" in defects[0]


def test_c5_no_references_section_with_many_citations(tmp_path: Path) -> None:
    text = (
        "A (Source: https://a.com/1). B (Source: https://b.com/2). "
        "C (Source: https://c.com/3)."
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    defects = qg.find_source_integrity(text, path=f)
    assert len(defects) == 1
    assert "no References section" in defects[0]


def test_c5_no_body_citations_skips(tmp_path: Path) -> None:
    f = tmp_path / "report.md"
    f.write_text("Plain prose with no citations at all.\n", encoding="utf-8")
    assert qg.find_source_integrity("Plain prose with no citations at all.\n", path=f) == []


def test_c5_family_scoped_to_reference_bearers(tmp_path: Path) -> None:
    # Digest/column/tutorial/presentation list sources inline by design — no
    # References section is expected, so C5 must NOT fire for them.
    text = "A (Source: https://a.com/1). B (Source: https://b.com/2). C (Source: https://c.com/3)."
    for fam in ("digest", "column", "magazine-digest", "tutorial", "presentation"):
        f = tmp_path / f"{fam}.md"
        f.write_text(text, encoding="utf-8")
        assert qg.find_source_integrity(text, path=f) == [], fam
    # report + briefings DO carry References and are checked.
    for fam in ("report", "premium-briefing", "enterprise-briefing"):
        f = tmp_path / f"{fam}.md"
        f.write_text(text, encoding="utf-8")
        assert len(qg.find_source_integrity(text, path=f)) == 1, fam


# ---------------------------------------------------------------------------
# X1 cross-product identity conflicts
# ---------------------------------------------------------------------------


def test_x1_no_conflict_when_identities_agree(tmp_path: Path) -> None:
    a = tmp_path / "digest.md"
    b = tmp_path / "report.md"
    a.write_text(
        "OpenAI is an AI research and deployment company. "
        "Stripe is a financial infrastructure platform.\n",
        encoding="utf-8",
    )
    b.write_text(
        "OpenAI is an AI research and deployment company. "
        "Stripe is a financial infrastructure platform.\n",
        encoding="utf-8",
    )
    assert qg.find_cross_product_conflicts([a, b]) == []


def test_x1_conflicting_identity_detected(tmp_path: Path) -> None:
    a = tmp_path / "digest.md"
    b = tmp_path / "report.md"
    a.write_text(
        "OpenAI is a legal-industry AI-native operating system company.\n",
        encoding="utf-8",
    )
    b.write_text(
        "OpenAI is a model-evaluation platform for enterprise LLM benchmarks.\n",
        encoding="utf-8",
    )
    defects = qg.find_cross_product_conflicts([a, b])
    assert len(defects) == 1
    assert "OpenAI" in defects[0]
    assert "legal industry ai native operating system" in defects[0]
    assert "model evaluation platform" in defects[0]


def test_x1_event_paraphrase_not_conflict(tmp_path: Path) -> None:
    # Different lengths describing the SAME event must NOT be flagged.
    a = tmp_path / "digest.md"
    b = tmp_path / "report.md"
    a.write_text(
        "Stripe acquired OpenRouter for seven billion dollars this period.\n",
        encoding="utf-8",
    )
    b.write_text(
        "Stripe acquired OpenRouter.\n",
        encoding="utf-8",
    )
    assert qg.find_cross_product_conflicts([a, b]) == []


def test_x1_single_file_no_conflict(tmp_path: Path) -> None:
    f = tmp_path / "digest.md"
    f.write_text("OpenAI is an AI research company.\n", encoding="utf-8")
    assert qg.find_cross_product_conflicts([f]) == []


# ---------------------------------------------------------------------------
# extract_identity_claims
# ---------------------------------------------------------------------------


def test_extract_identity_claims_finds_copular() -> None:
    claims = qg.extract_identity_claims(
        "OpenAI is a model-evaluation platform. Stripe acquired OpenRouter."
    )
    assert "OpenAI" in claims
    assert "Stripe" not in claims  # event sentence, no identity claim


def test_extract_identity_claims_ignores_event_sentences() -> None:
    claims = qg.extract_identity_claims(
        "OpenAI raised a funding round. Stripe bought OpenRouter."
    )
    assert claims == {}


# ---------------------------------------------------------------------------
# Domain / language helpers
# ---------------------------------------------------------------------------


def test_normalize_domain_from_dir_name() -> None:
    assert qg._normalize_domain("outputs/ai-commercial") == "ai-commercial"
    assert qg._normalize_domain("ai-commercial") == "ai-commercial"
    assert qg._normalize_domain("  AI-Commercial  ") == "ai-commercial"


def test_normalize_domain_outputs_stripped() -> None:
    assert qg._normalize_domain("outputs/b2b/digest.md") == "b2b"


# ---------------------------------------------------------------------------
# parse_domain_blocklist
# ---------------------------------------------------------------------------


def test_parse_domain_blocklist_empty() -> None:
    assert qg.parse_domain_blocklist("") == {}


def test_parse_domain_blocklist_parses() -> None:
    parsed = qg.parse_domain_blocklist(
        "medical-research:cervical cancer,NICE;ai-commercial:horse"
    )
    assert parsed == {
        "medical-research": ["cervical cancer", "NICE"],
        "ai-commercial": ["horse"],
    }


# ---------------------------------------------------------------------------
# Orchestration: gate_file / gate_directory / main exit codes
# ---------------------------------------------------------------------------


def test_gate_file_clean(tmp_path: Path) -> None:
    f = tmp_path / "digest.md"
    f.write_text(
        "A fully written product line that carries a real sentence. "
        + "x" * 800,
        encoding="utf-8",
    )
    assert qg.gate_file(f, domain="ai-commercial") == []


def test_gate_file_polluted_catches_multiple(tmp_path: Path) -> None:
    f = tmp_path / "digest.md"
    f.write_text(
        "LiteLLM.Info leaked. TODO finish. 中文残留混入文本." * 6,
        encoding="utf-8",
    )
    # medical-research is NOT a bilingual domain — CJK there is a real leak.
    defects = qg.gate_file(f, domain="medical-research")
    assert any("C2" in d for d in defects)
    assert any("F2" in d for d in defects)
    assert any("C3" in d for d in defects)


def test_gate_directory_bilingual_ai_commercial_no_flag_passes(
    tmp_path: Path,
) -> None:
    """#193 acceptance: the STANDARD gate command on an ai-commercial dir
    (bilingual, 36kr Chinese content) must PASS with no --cjk-exempt-domains
    flag — the exemption is a code default, not a magic flag.
    """
    domain_dir = tmp_path / "ai-commercial"
    domain_dir.mkdir()
    (domain_dir / "digest.md").write_text(
        "OpenAI 融资 85 分新闻 中文内容混排 English content. " * 10,
        encoding="utf-8",
    )
    assert qg.gate_directory(domain_dir) == []


def test_gate_directory_clean_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "digest.md").write_text(
        "OpenAI is an AI research company. " + "y" * 500, encoding="utf-8"
    )
    (tmp_path / "report.md").write_text(
        "OpenAI is an AI research company. " + "z" * 500, encoding="utf-8"
    )
    assert qg.gate_directory(tmp_path) == []


def test_main_clean_returns_zero(tmp_path: Path) -> None:
    (tmp_path / "digest.md").write_text(
        "OpenAI is an AI research company. " + "y" * 500, encoding="utf-8"
    )
    assert qg.main([str(tmp_path)]) == 0


def test_main_polluted_returns_one(tmp_path: Path) -> None:
    (tmp_path / "digest.md").write_text(
        "TODO: unfinished " + "中文残留" * 10 + " LiteLLM.Info leak "
        + "x" * 200,
        encoding="utf-8",
    )
    assert qg.main([str(tmp_path)]) == 1


def test_main_missing_dir_returns_two(tmp_path: Path) -> None:
    assert qg.main([str(tmp_path / "does-not-exist")]) == 2


def test_main_json_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "digest.md").write_text(
        "TODO unfinished " + "x" * 200, encoding="utf-8"
    )
    rc = qg.main([str(tmp_path), "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    assert '"exit_code": 1' in out
    assert "TODO" in out


# ---------------------------------------------------------------------------
# C6 long-form narrative grounding (issue #192)
# ---------------------------------------------------------------------------

_FEATURE_DRIFT = (
    "Zorpzilla's journey from a three-person idea to a market leader has "
    "been remarkable. The company has built a strong customer base across "
    "multiple regions. Its products serve a broad audience of enterprises "
    "and consumers alike. Analysts point to the founding team's persistence "
    "as the key differentiator in a crowded market."
)
_FEATURE_GROUNDED = (
    "Zorpzilla's journey from a three-year-old startup shows steady and "
    "disciplined growth. The company raised funding for hardware products "
    "and built a strong customer base. Its products serve a broad audience "
    "of enterprises and consumers alike. Analysts point to the founding "
    "team's persistence as the key differentiator in a crowded market."
)
_FEATURE_HEDGE = (
    "Zorpzilla's financial details are not disclosed in the available "
    "sources. The startup's customer composition is unknown, though its "
    "hardware products reach a broad audience. Analysts note the founding "
    "team's persistence as the key differentiator in a crowded market. "
    "Specific revenue figures are not in the sources at all."
)


def _magazine_with_feature(feature: str) -> str:
    return f"""# Weekly Magazine Digest

## The Feature

{feature}

## Entries

### 1. Zorpzilla

**Summary**: Zorpzilla is a three-year-old startup from Berlin.

## References

1. **Zorpzilla** — https://example.com/zorpzilla — Zorpzilla is a three-year-old startup.
"""


def test_c6_three_person_drift_flagged() -> None:
    """#192 acceptance: 'three-person idea' when sources say 'three-year-old
    startup' is an orphan narrative claim — the deterministic grounding
    check must FAIL the product."""
    defects = qg.find_orphan_narrative_claims(_magazine_with_feature(_FEATURE_DRIFT))
    assert len(defects) == 1
    assert "C6 orphan narrative claim" in defects[0]
    # Normalized claim is "3person" (whitespace/punct stripped for compare).
    assert "3person" in defects[0] or "3 person" in defects[0]


def test_c6_grounded_feature_passes() -> None:
    """A feature that restates the sources' facts (three-year-old, funding,
    hardware) is fully grounded — no orphans."""
    assert qg.find_orphan_narrative_claims(
        _magazine_with_feature(_FEATURE_GROUNDED)
    ) == []


def test_c6_honest_hedge_never_flagged() -> None:
    """#179/#191 correct behavior: 'not disclosed in the available sources'
    is an honest hedge, NOT an orphan claim — must PASS."""
    assert qg.find_orphan_narrative_claims(
        _magazine_with_feature(_FEATURE_HEDGE)
    ) == []


def test_c6_gate_file_runs_grounding_check(tmp_path: Path) -> None:
    """C6 is wired into gate_file — a drifted magazine-digest fails the
    standard gate command."""
    f = tmp_path / "magazine-digest.md"
    f.write_text(_magazine_with_feature(_FEATURE_DRIFT), encoding="utf-8")
    defects = qg.gate_file(f, domain="ai-commercial")
    assert any("C6" in d for d in defects)


# ---------------------------------------------------------------------------
# known-defects fixture corpus acceptance (#194 spec C)
# ---------------------------------------------------------------------------


def test_quality_gate_known_good_passes() -> None:
    """The known-good fixture product must pass the L0 gate clean."""
    known_good = (
        Path(__file__).resolve().parent.parent.parent
        / "tests" / "fixtures" / "known-defects" / "known-good"
    )
    assert qg.gate_directory(known_good) == []


def test_quality_gate_flags_three_person_fixture() -> None:
    """The three-person-drift fixture is caught deterministically (C6)."""
    drift_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "tests" / "fixtures" / "known-defects" / "three-person-drift"
    )
    defects = qg.gate_directory(drift_dir)
    assert any("C6" in d for d in defects)


# ---------------------------------------------------------------------------
# H1/H2/H3 grade-review assertion classes (issues #200/#203/#204)
# ---------------------------------------------------------------------------


def _report_with_signal_and_refs(signal_lines: str, refs: str) -> str:
    """A report-family body (narrative) + References ground truth."""
    return (
        "# Report\n\n## Executive Summary\n"
        + signal_lines
        + "\n\n## References\n"
        + refs
    )


def test_h1_flags_narrative_only_signal(tmp_path: Path) -> None:
    """#200 acceptance: 'low market breadth' appears in the narrative but
    NOT in References (which carry the honest source signals) — H1 flags it."""
    text = _report_with_signal_and_refs(
        signal_lines=(
            "Joe Tigay points to signals such as low market breadth as reasons "
            "to expect a pullback this month."
        ),
        refs=(
            "1. **Stocks predict** — https://example.com/tigay — Joe Tigay "
            "points to low VIX, inflation shocks, and excessive AI spending."
        ),
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    defects = qg.find_narrative_signal_integrity(text, path=f)
    assert any("market breadth" in d for d in defects), defects
    # The honest source signals are grounded and never flagged.
    for grounded in ("VIX", "inflation shocks", "AI spending"):
        assert not any(grounded in d for d in defects), defects


def test_h1_grounded_signal_passes(tmp_path: Path) -> None:
    """A narrative signal that IS in References passes H1 (no orphan)."""
    text = _report_with_signal_and_refs(
        signal_lines=(
            "The source notes excessive AI spending across the sector."
        ),
        refs=(
            "1. **A spending call** — https://example.com/s — excessive AI "
            "spending is a key concern."
        ),
    )
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    assert qg.find_narrative_signal_integrity(text, path=f) == []


def test_h1_only_applies_to_reference_bearing_families(tmp_path: Path) -> None:
    """H1 is scoped to report/briefing/digest — not magazine-digest."""
    text = _report_with_signal_and_refs(
        signal_lines="Signals such as low market breadth dominate the period.",
        refs="1. **X** — https://example.com/x — low VIX and inflation.",
    )
    f = tmp_path / "magazine-digest.md"
    f.write_text(text, encoding="utf-8")
    assert qg.find_narrative_signal_integrity(text, path=f) == []


def test_h2_flags_mid_word_line_end() -> None:
    """H2 acceptance: 'police offi' is a bare prefix of 'officers' elsewhere —
    the line ends mid-word and is flagged."""
    text = (
        "Officers arrested the suspect. The statement lists police offi" + "\n"
        "several roles including investigating officers across the precinct."
    )
    defects = qg.find_word_boundary_truncation(text)
    assert any("offi" in d for d in defects), defects


def test_h2_complete_line_passes() -> None:
    """A line ending in a real terminal word is not an H2 truncation."""
    text = (
        "Officers conducted the investigation thoroughly and completed the "
        "full product system review before publishing."
    )
    assert qg.find_word_boundary_truncation(text) == []


def test_h3_flags_glued_bullet() -> None:
    """H3 acceptance: a '- ' bullet that does not start a line (previous char
    is not a newline) — ').- **next' — is flagged."""
    text = (
        "## Key Findings\n"
        "- First finding with a citation (Source: https://a.com/1).- **Second "
        "finding glued onto the first line** but this is a real paragraph."
    )
    defects = qg.find_bullet_serialization_glue(text)
    assert len(defects) == 1
    assert "H3 bullet serialization glue" in defects[0]


def test_h3_clean_lines_pass() -> None:
    """Bullets that each start a new line are not glue."""
    text = (
        "## Key Findings\n"
        "- First finding on its own line.\n"
        "- Second finding on its own line.\n"
    )
    assert qg.find_bullet_serialization_glue(text) == []
