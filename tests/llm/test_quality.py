"""Tests for quality gates G1-G3 (and orchestrator G0).

Covers:
    - G1SourceAuthority: tier-based advisory warnings
    - G2Dedup: URL, PMID, DOI duplicate detection
    - G3RelevanceScoring: keyword overlap scoring + threshold hiding
    - run_quality_gates: orchestrator runs G0+G1+G2+G3
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from autoinfo.config import QualityGateConfig
from autoinfo.models import Item, KBEntry
from autoinfo.quality import (
    G1SourceAuthority,
    G2Dedup,
    G3RelevanceScoring,
    QualityResult,
    run_quality_gates,
)

# ===================================================================
# G1 — Source Authority
# ===================================================================


class TestG1SourceAuthority:
    """G1 is advisory — always passes, but flags low-tier sources."""

    def test_tier_1_passes_unflagged(self, sample_item: Item) -> None:
        g1 = G1SourceAuthority()
        result = g1.check(sample_item)

        assert result.passed is True
        assert result.flagged is False
        assert result.gate_name == "G1-SourceAuthority"
        assert "warning" not in result.details

    def test_tier_2_passes_unflagged(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 2})
        g1 = G1SourceAuthority()
        result = g1.check(item)

        assert result.passed is True
        assert result.flagged is False
        assert "warning" not in result.details

    def test_tier_3_flagged_advisory(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 3})
        g1 = G1SourceAuthority()
        result = g1.check(item)

        assert result.passed is True  # advisory only
        assert result.flagged is True
        assert result.details["warning"] == "low quality source"

    def test_tier_4_flagged_advisory(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 4})
        g1 = G1SourceAuthority()
        result = g1.check(item)

        assert result.passed is True
        assert result.flagged is True
        assert result.details["warning"] == "low quality source"

    def test_source_config_overrides_item_tier(self, sample_item: Item) -> None:
        """source_config quality_tier takes precedence over item.quality_tier."""
        item = Item(**{**sample_item.to_dict(), "quality_tier": 1})
        source_config = {"quality_tier": 3, "name": "community-forum"}
        g1 = G1SourceAuthority()
        result = g1.check(item, source_config)

        assert result.flagged is True
        assert result.details["warning"] == "low quality source"

    def test_negative_tier_handling(self, sample_item: Item) -> None:
        """Tier 0 or negative should be treated conservatively (not flagged)."""
        item = Item(**{**sample_item.to_dict(), "quality_tier": 0})
        g1 = G1SourceAuthority()
        result = g1.check(item)

        assert result.passed is True
        assert result.flagged is False  # tier 0 <= 2

    def test_score_reflects_tier(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 3})
        g1 = G1SourceAuthority()
        result = g1.check(item)

        assert result.score == 3.0  # score = tier number


class TestG1SourceScore:
    """Deterministic source credibility score (E9)."""

    def test_tier1_maps_to_90(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 1})
        g1 = G1SourceAuthority()
        result = g1.check(item)
        assert result.details["source_score"] == 90.0

    def test_tier2_maps_to_70(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 2})
        g1 = G1SourceAuthority()
        result = g1.check(item)
        assert result.details["source_score"] == 70.0

    def test_tier3_maps_to_50(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 3})
        g1 = G1SourceAuthority()
        result = g1.check(item)
        assert result.details["source_score"] == 50.0
        assert result.flagged is True

    def test_tier4_maps_to_30(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 4})
        g1 = G1SourceAuthority()
        result = g1.check(item)
        assert result.details["source_score"] == 30.0
        assert result.flagged is True

    def test_tier5_gets_fallback_score(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 5})
        g1 = G1SourceAuthority()
        result = g1.check(item)
        raw_score = result.details["source_score"]
        assert isinstance(raw_score, float)
        assert 0.0 < raw_score < 30.0  # fallback below tier4

    def test_gate_config_overrides_score_map(self, sample_item: Item) -> None:
        item = Item(**{**sample_item.to_dict(), "quality_tier": 1})
        custom_map = {1: 95.0, 2: 75.0, 3: 55.0, 4: 25.0}
        gate_config = QualityGateConfig(
            name="G1-SourceAuthority", source_score_map=custom_map
        )
        g1 = G1SourceAuthority()
        result = g1.check(item, gate_config=gate_config)
        assert result.details["source_score"] == 95.0

    def test_kb_entry_has_source_score_field(self, sample_kb_entry: KBEntry) -> None:
        assert hasattr(sample_kb_entry, "source_score")
        assert sample_kb_entry.source_score == 0.0  # default

    def test_store_entry_persists_source_score(
        self, sample_item: Item, tmp_path: Path
    ) -> None:
        from autoinfo.kb import KBStore

        store = KBStore(base_path=tmp_path / "kb")
        store.index.init_db()

        from autoinfo.models import ExtractionResult

        quality_results = {
            "G1-SourceAuthority": QualityResult(
                gate_name="G1-SourceAuthority",
                passed=True,
                score=1.0,
                details={"quality_tier": 1, "source_score": 90.0},
            ),
        }
        entry = store.store_entry(
            sample_item,
            extraction=ExtractionResult(item_id="t1", tl_dr="Test"),
            quality_results=quality_results,
        )
        assert entry.source_score == 90.0

        # Check frontmatter
        md_path = Path(entry.file_path)
        content = md_path.read_text(encoding="utf-8")
        assert "source_score: 90.0" in content

        # Check SQLite persistence
        db_entry = store.index.get_entry(entry.entry_id)
        assert db_entry is not None
        assert db_entry["source_score"] == 90.0

    def test_search_results_include_source_score(
        self, sample_item: Item, tmp_path: Path
    ) -> None:
        from autoinfo.kb import KBStore
        from autoinfo.models import ExtractionResult

        store = KBStore(base_path=tmp_path / "kb")
        store.index.init_db()

        quality_results = {
            "G1-SourceAuthority": QualityResult(
                gate_name="G1-SourceAuthority",
                passed=True,
                score=1.0,
                details={"quality_tier": 1, "source_score": 90.0},
            ),
        }
        entry = store.store_entry(
            sample_item,
            extraction=ExtractionResult(item_id="t1", tl_dr="IVF embryo study"),
            quality_results=quality_results,
        )

        results = store.search_knowledge_base(query="IVF embryo", limit=5)
        assert results["total_count"] >= 1
        found = False
        for e in results["entries"]:
            if e.get("entry_id") == entry.entry_id:
                assert e.get("source_score") == 90.0
                found = True
                break
        assert found, f"Entry {entry.entry_id} not found in search results"


# ===================================================================
# G2 — Dedup
# ===================================================================


class TestG2Dedup:
    """G2 detects duplicates by URL, PMID, or DOI."""

    def test_url_duplicate_detected(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        existing = [
            KBEntry(**{**sample_kb_entry.to_dict(), "source_url": sample_item.source_url})
        ]
        g2 = G2Dedup()
        result = g2.check(sample_item, existing)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["is_duplicate"] is True
        assert result.details["matched_by"] == "url"

    def test_url_unique_passes(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/other",
                    "title": "Unrelated study about diabetes management in elderly patients",
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(sample_item, existing)

        assert result.passed is True
        assert result.details["is_duplicate"] is False

    def test_naive_item_aware_entry_no_crash(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        """G2 freshness window must not crash on naive-vs-aware datetime (#145)."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "collected_at": "2026-07-15T10:30:00",  # naive (no tz suffix)
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/other",  # bypass URL match
                    "title": sample_item.title,  # force fuzzy-title path
                }
            )
        ]  # collected_at stays aware ("2026-07-15T10:30:00Z")
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.details["is_duplicate"] is True
        assert result.details["matched_by"] == "fuzzy_title"

    def test_pmid_duplicate_detected(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        """Use different URLs so URL match doesn't fire before PMID match."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/new-item",
                "raw_data": {"pmid": "12345678"},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/existing-entry",
                    "custom_fields": {"pmid": "12345678"},
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["is_duplicate"] is True
        assert result.details["matched_by"] == "pmid"

    def test_doi_duplicate_detected(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        """Use different URLs so URL match doesn't fire before DOI match."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/new-item",
                "raw_data": {"doi": "10.1000/j.jrm.2026.03.004"},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/existing-entry",
                    "extracted_fields": {"doi": "10.1000/j.jrm.2026.03.004"},
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["is_duplicate"] is True
        assert result.details["matched_by"] == "doi"

    def test_doi_case_insensitive(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        """DOI matching should be case-insensitive."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/new-item",
                "raw_data": {"doi": "10.1000/J.JRM.2026.03.004"},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/existing-entry",
                    "extracted_fields": {"doi": "10.1000/j.jrm.2026.03.004"},
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.details["matched_by"] == "doi"

    def test_empty_existing_entries(self, sample_item: Item) -> None:
        g2 = G2Dedup()
        result = g2.check(sample_item, [])

        assert result.passed is True
        assert result.details["is_duplicate"] is False

    def test_no_match_returns_correct_details(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/other",
                    "title": "Cardiovascular risk factors in middle-aged adults: a cohort study",
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(sample_item, existing)

        assert result.details["matched_by"] is None

    def test_url_match_precedes_pmid(self, sample_item: Item, sample_kb_entry: KBEntry) -> None:
        """URL match should be detected before checking PMID/DOI."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/dup",
                "raw_data": {"pmid": "12345678"},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/dup",
                    "custom_fields": {"pmid": "12345678"},
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.details["matched_by"] == "url"
        assert result.passed is False

    def test_different_urls_same_pmid_detected(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        """Different URLs with same PMID should be caught by PMID match."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/via-pubmed",
                "raw_data": {"pmid": "12345678"},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/other-url",
                    "custom_fields": {"pmid": "12345678"},
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.details["matched_by"] == "pmid"

    def test_fuzzy_title_duplicate_detected(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        """Similar titles (≥85% match) should be flagged as duplicates."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/new-item",
                "raw_data": {},  # no PMID/DOI to avoid those matches
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/existing-entry",
                    # Title is almost identical — only missing "a" article
                    "title": "Improved IVF outcomes with time-lapse embryo "
                    "imaging: randomized controlled trial",
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is False
        assert result.flagged is True
        assert result.details["is_duplicate"] is True
        assert result.details["matched_by"] == "fuzzy_title"
        assert result.details["similarity"] >= 0.85

    def test_fuzzy_title_below_threshold_passes(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        """Dissimilar titles (< 85% match) should not trigger fuzzy dedup."""
        item = Item(
            **{
                **sample_item.to_dict(),
                "source_url": "https://example.com/new-item",
                "raw_data": {},
            }
        )
        existing = [
            KBEntry(
                **{
                    **sample_kb_entry.to_dict(),
                    "source_url": "https://example.com/existing-entry",
                    "title": "Cardiovascular risk factors in middle-aged adults: a cohort study",
                }
            )
        ]
        g2 = G2Dedup()
        result = g2.check(item, existing)

        assert result.passed is True
        assert result.details["is_duplicate"] is False

# ===================================================================
# G3 — Relevance Scoring
# ===================================================================


class TestG3RelevanceScoring:
    """G3 scores keyword overlap and hides low-relevance items."""

    def test_all_keywords_match_gets_full_score(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        # The sample_item's title and content mention "IVF" and "embryo"
        result = g3.check(sample_item, topic_keywords=["IVF", "embryo"])

        assert result.passed is True
        assert result.score == 100.0  # both keywords found

    def test_partial_keyword_match(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        # Only "IVF" appears in the item (in title, weighted), "quantum" does not
        result = g3.check(sample_item, topic_keywords=["IVF", "quantum"])

        # Discriminative scoring (#182): title hit (weight 2.0) + 1/2
        # coverage → 70, not the old flat 1/2 = 50.
        assert result.score == 70.0

    def test_no_keywords_match_returns_zero(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        result = g3.check(sample_item, topic_keywords=["quantum", "computing"])

        assert result.score == 0.0
        assert result.flagged is True
        assert result.details["hidden"] is True

    def test_empty_keywords_degrades_to_zero(self, sample_item: Item) -> None:
        """Issue #16: no keywords means no relevance signal — the score must
        degrade to 0 (flagged), never a placeholder 100/always-pass.  The old
        ``score=100 (always pass)`` behavior stored ``100.0/100`` in the KB
        for every entry whose topic carried no keywords, which rendered every
        digest/magazine Relevance as ``100.0/100`` with no discriminative
        power."""
        g3 = G3RelevanceScoring()
        result = g3.check(sample_item, topic_keywords=[])

        assert result.score == 0.0
        assert result.passed is False
        assert result.flagged is True
        assert "no keywords" in result.details["reason"]

    def test_below_threshold_flagged_hidden(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        result = g3.check(sample_item, topic_keywords=["quantum"], threshold=30)

        assert result.score == 0.0
        assert result.flagged is True
        assert result.details["hidden"] is True
        assert result.details["reason"] == "below relevance threshold"

    def test_lexical_partial_hit_flags_not_archives(self, sample_item: Item) -> None:
        """Issue #79: a relevant item hitting only 1 of N union keywords
        (score 8-15 < threshold) must be FLAGGED, not archived — archiving it
        would exclude valid content from digests (empty-shell regression)."""
        from autoinfo.config import QualityGateConfig

        g3 = G3RelevanceScoring()
        # 13-keyword union (b2b-like broad set); the item hits only "IVF" in title.
        keywords = [
            "IVF", "embryo", "fertility", "startup", "funding", "SaaS",
            "enterprise", "cloud", "CRM", "marketing", "sales", "procurement",
            "vendor",
        ]
        config = QualityGateConfig(
            name="G3-RelevanceScoring", category="soft", retries=0,
            action="archive", threshold=30,
        )
        result = g3.check(sample_item, topic_keywords=keywords, threshold=30, gate_config=config)

        assert result.passed is False
        assert result.score < 30
        assert result.details["scoring_method"] == "lexical"
        assert result.details.get("archive") is False
        assert result.details.get("archived_as_flag") is True

    def test_lexical_zero_hit_still_archives(self, sample_item: Item) -> None:
        """Issue #79: zero lexical hits (score 0, no keyword evidence at all)
        still archives — the genuine negative signal keeps its safety net."""
        from autoinfo.config import QualityGateConfig

        g3 = G3RelevanceScoring()
        config = QualityGateConfig(
            name="G3-RelevanceScoring", category="soft", retries=0,
            action="archive", threshold=30,
        )
        result = g3.check(
            sample_item, topic_keywords=["quantum computing"], threshold=30,
            gate_config=config,
        )

        assert result.passed is False
        assert result.score == 0.0
        assert result.details["scoring_method"] == "lexical"
        assert result.details.get("archive") is True

    def test_llm_path_archive_unchanged(self, sample_item: Item) -> None:
        """Issue #79: the LLM scoring path keeps archive semantics — only the
        lexical degraded fallback distinguishes zero-hit (archive) from
        partial-hit (flag)."""
        from autoinfo.config import QualityGateConfig

        g3 = G3RelevanceScoring()
        g3.llm_call = lambda **kwargs: type(
            "R", (), {"choices": [type("C", (), {"message": type(
                "M", (), {"content": "10"})()})()]}  # noqa: E501
        )()
        config = QualityGateConfig(
            name="G3-RelevanceScoring", category="soft", retries=1,
            action="archive", threshold=30,
        )
        result = g3.check(
            sample_item, topic_keywords=["IVF", "embryo"], threshold=30,
            gate_config=config,
        )

        assert result.details["scoring_method"] == "llm"
        assert result.details.get("archive") is True

    def test_above_threshold_not_hidden(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        result = g3.check(sample_item, topic_keywords=["IVF"], threshold=30)

        assert result.score == 100.0
        assert result.flagged is False
        assert result.details["hidden"] is False

    def test_score_capped_at_100(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        # Even if more keywords match than total keywords (shouldn't happen, but guard)
        result = g3.check(sample_item, topic_keywords=["IVF"])

        assert result.score == 100.0  # 1/1 * 100 = 100, capped at 100

    def test_case_insensitive_matching(self, sample_item: Item) -> None:
        """Keyword matching is case-insensitive."""
        g3 = G3RelevanceScoring()
        # "ivf" lowercase should match "IVF" in the title
        result = g3.check(sample_item, topic_keywords=["ivf"])

        assert result.score == 100.0

    def test_content_keyword_match(self, sample_item: Item) -> None:
        """Keywords in the content body should also count."""
        g3 = G3RelevanceScoring()
        # "implantation" isn't in title but appears in content as "implantation" (wait let me check)
        # Actually looking at sample_item content, "implantation" is there in "implantation rate"
        # But the sample_item content uses "implantation" — let me use something I know is there
        # "live birth" appears in the content
        result = g3.check(sample_item, topic_keywords=["live birth"])

        assert result.score == 100.0

    def test_keyword_match_count_in_details(self, sample_item: Item) -> None:
        g3 = G3RelevanceScoring()
        result = g3.check(sample_item, topic_keywords=["IVF", "embryo", "quantum"])

        assert result.details["keyword_matches"] == 2
        assert result.details["total_keywords"] == 3

    def test_custom_threshold(self, sample_item: Item) -> None:
        """Custom threshold values are respected."""
        g3 = G3RelevanceScoring()
        # 1/3 match, IVF in title → discriminative score 47 (#182)
        # With threshold=30: 47 >= 30 → passes (not flagged)
        # With threshold=40: 47 < 40 → passes; with threshold=60: flagged
        result_low = g3.check(
            sample_item,
            topic_keywords=["IVF", "quantum", "computing"],
            threshold=30,
        )
        assert result_low.score == 47.0
        assert result_low.passed is True
        assert result_low.flagged is False  # 47 >= 30

        result_mid = g3.check(
            sample_item,
            topic_keywords=["IVF", "quantum", "computing"],
            threshold=40,
        )
        assert result_mid.score == 47.0
        assert result_mid.passed is True  # 47 >= 40

        result_high = g3.check(
            sample_item,
            topic_keywords=["IVF", "quantum", "computing"],
            threshold=60,
        )
        assert result_high.score == 47.0
        assert result_high.passed is False
        assert result_high.flagged is True  # 47 < 60
        assert result_high.details["hidden"] is True


# ===================================================================
# G3 — Relevance Scoring (LLM-based)
# ===================================================================


class TestG3RelevanceScoringLLM:
    """G3 LLM-based 0-100 scoring with retry loop following G4's pattern."""

    @staticmethod
    def _mock_llm_response(score_text: str) -> MagicMock:
        """Build a mock litellm response whose content is *score_text*."""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = score_text
        return mock_resp

    @staticmethod
    def _gate_config(retries: int = 2, action: str = "archive") -> QualityGateConfig:
        """Return a QualityGateConfig with retries > 0 to trigger LLM path."""
        return QualityGateConfig(
            name="G3-RelevanceScoring",
            retries=retries,
            action=action,
        )

    def test_llm_score_returned_directly(self, sample_item: Item) -> None:
        """LLM returns '85' → score is 85."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("85")
        )
        result = g3.check(
            sample_item,
            topic_keywords=["IVF", "embryo"],
            gate_config=self._gate_config(),
        )
        assert result.score == 85.0
        assert result.details["scoring_method"] == "llm"

    def test_llm_score_zero(self, sample_item: Item) -> None:
        """LLM returns '0' → score is 0, flagged hidden."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("0")
        )
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            threshold=30,
            gate_config=self._gate_config(),
        )
        assert result.score == 0.0
        assert result.flagged is True
        assert result.details["hidden"] is True

    def test_llm_score_100(self, sample_item: Item) -> None:
        """LLM returns '100' → score is 100, passes."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("100")
        )
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            gate_config=self._gate_config(),
        )
        assert result.score == 100.0
        assert result.passed is True
        assert result.flagged is False

    def test_llm_clamps_out_of_range(self, sample_item: Item) -> None:
        """LLM returns '150' → clamped to 100."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("150")
        )
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            gate_config=self._gate_config(),
        )
        assert result.score == 100.0

    def test_llm_parses_number_from_text(self, sample_item: Item) -> None:
        """LLM returns 'Score: 73' → parses to 73."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("Score: 73")
        )
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            gate_config=self._gate_config(),
        )
        assert result.score == 73.0

    def test_all_retries_exhausted_falls_back_to_lexical(self, sample_item: Item) -> None:
        """Issue #172: LLM raises on all retries → lexical fallback (NEVER the
        old silent neutral-pass 50, which flattened every item's relevance)."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(side_effect=RuntimeError("API down"))
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            threshold=30,
            gate_config=self._gate_config(retries=3),
        )
        # Discriminative lexical score, not a flat neutral 50.
        assert result.score != 50.0
        assert result.details["scoring_method"] == "lexical"
        assert result.details["llm_retries"] == 3

    def test_retry_escalating_context(self, sample_item: Item) -> None:
        """First call fails (unparseable), second succeeds → returns second score."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock()
        g3.llm_call.side_effect = [
            self._mock_llm_response("not a number"),
            self._mock_llm_response("42"),
        ]
        result = g3.check(
            sample_item,
            topic_keywords=["IVF"],
            gate_config=self._gate_config(retries=2),
        )
        assert result.score == 42.0
        assert result.details["llm_retries"] == 2

    def test_lexical_fallback_when_retries_zero(self, sample_item: Item) -> None:
        """gate_config.retries=0 → lexical fallback (no LLM call)."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(side_effect=AssertionError("should not be called"))
        result = g3.check(
            sample_item,
            topic_keywords=["IVF", "embryo"],
            gate_config=self._gate_config(retries=0),
        )
        assert result.score == 100.0  # lexical: both keywords match
        assert result.details["scoring_method"] == "lexical"
        g3.llm_call.assert_not_called()

    def test_content_truncation_for_large_input(self, sample_item: Item) -> None:
        """Content > 32K chars is truncated before LLM call."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("90")
        )
        # Build content exceeding _MAX_CONTENT_CHARS (32K)
        long_item = Item(**{
            **sample_item.to_dict(),
            "content": "A" * 50000,
        })
        result = g3.check(
            long_item,
            topic_keywords=["IVF"],
            gate_config=self._gate_config(),
        )
        assert result.score == 90.0
        # Verify the content passed to LLM was truncated
        call_args = g3.llm_call.call_args
        user_content = call_args[1]["messages"][1]["content"]
        content_start = user_content.find("CONTENT: ")
        passed_content = user_content[content_start + len("CONTENT: "):]
        # Should be ≤ 32K chars plus the prefix text before CONTENT:
        assert len(passed_content) <= g3._MAX_CONTENT_CHARS + 200

    def test_no_keywords_short_circuits_llm(self, sample_item: Item) -> None:
        """Empty keywords → degraded score 0, no LLM call made (issue #16)."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(side_effect=AssertionError("should not be called"))
        result = g3.check(
            sample_item,
            topic_keywords=[],
            gate_config=self._gate_config(),
        )
        assert result.score == 0.0
        assert result.passed is False
        assert result.flagged is True
        g3.llm_call.assert_not_called()

    def test_multi_language_keywords(self, sample_item: Item) -> None:
        """Multi-language keyword dict is flattened and scored by LLM."""
        g3 = G3RelevanceScoring(model="test/test")
        g3.llm_call = MagicMock(
            return_value=self._mock_llm_response("88")
        )
        result = g3.check(
            sample_item,
            topic_keywords={"en": ["IVF"], "zh": ["试管婴儿"]},
            gate_config=self._gate_config(),
        )
        assert result.score == 88.0
        assert result.details["scoring_method"] == "llm"


# ===================================================================
# Orchestrator — run_quality_gates
# ===================================================================


class TestRunQualityGates:
    """run_quality_gates() orchestrator runs all three gates."""

    def test_runs_all_three_gates(self, sample_item: Item) -> None:
        context = {
            "source_config": {"quality_tier": 1},
            "existing_entries": [],
            "topic_keywords": ["IVF", "embryo"],
            "threshold": 30,
        }
        results = run_quality_gates(sample_item, context)

        assert "G0-SchemaIntegrity" in results
        assert "G1-SourceAuthority" in results
        assert "G2-Dedup" in results
        assert "G3-RelevanceScoring" in results
        assert len(results) >= 4

    def test_all_quality_result_instances(self, sample_item: Item) -> None:
        results = run_quality_gates(sample_item, {"topic_keywords": ["IVF"]})

        for name, result in results.items():
            assert isinstance(result, QualityResult), f"{name} is not a QualityResult"

    def test_context_defaults_when_missing(self, sample_item: Item) -> None:
        """Orchestrator should not crash when context is empty."""
        results = run_quality_gates(sample_item, {})

        assert len(results) >= 4
        # G0 should pass for valid sample_item
        assert results["G0-SchemaIntegrity"].passed is True
        # G3 with empty keywords degrades to 0 (issue #16)
        g3 = results["G3-RelevanceScoring"]
        assert g3.score == 0.0
        assert g3.passed is False
        assert g3.flagged is True

    def test_context_none_defaults(self, sample_item: Item) -> None:
        """Orchestrator should not crash when context is None."""
        results = run_quality_gates(sample_item)

        assert len(results) >= 4

    def test_llm_model_forwarded_to_g3(self, sample_item: Item) -> None:
        """Issue #173: the serial run_quality_gates path forwards llm_model to
        the G3 scorer — the default CLI (no --check-factual) must score with
        the configured production LLM, never the dead hardcoded default."""
        context = {
            "topic_keywords": ["IVF"],
            "threshold": 30,
        }
        with patch(
            "autoinfo.quality.G3RelevanceScoring",
            wraps=G3RelevanceScoring,
        ) as mock_g3_cls:
            run_quality_gates(
                sample_item, context,
                llm_model="openai/mimo-v2.5",
            )
        # The G3 scorer was constructed with the forwarded production model.
        constructed = [c for c in mock_g3_cls.call_args_list]
        assert constructed, "G3RelevanceScoring was not constructed"
        kwargs = constructed[0].kwargs
        assert kwargs.get("model") == "openai/mimo-v2.5", (
            f"G3 constructed without the forwarded model: {kwargs}"
        )

    def test_g3_triggers_hidden_in_orchestrator(self, sample_item: Item) -> None:
        """Hidden flag propagates through orchestrated G3."""
        context = {
            "topic_keywords": ["quantum", "computing"],
            "threshold": 30,
        }
        results = run_quality_gates(sample_item, context)

        g3 = results["G3-RelevanceScoring"]
        assert g3.flagged is True
        assert g3.details["hidden"] is True

    def test_g1_flagged_in_orchestrator(self, sample_item: Item) -> None:
        context = {
            "source_config": {"quality_tier": 3},
            "topic_keywords": ["IVF"],
        }
        results = run_quality_gates(sample_item, context)

        g1 = results["G1-SourceAuthority"]
        assert g1.flagged is True
        assert g1.details["warning"] == "low quality source"

    def test_g1_uses_item_quality_tier_without_source_config(
        self, sample_item: Item
    ) -> None:
        """G1 falls back to item.quality_tier when source_config not in context (Fix A path)."""
        item = Item(**{**sample_item.to_dict(), "quality_tier": 3})
        context = {"topic_keywords": ["IVF"]}
        results = run_quality_gates(item, context)

        g1 = results["G1-SourceAuthority"]
        assert g1.flagged is True
        assert g1.details["warning"] == "low quality source"
        assert g1.details["quality_tier"] == 3

    def test_g1_source_config_overrides_item_tier_in_orchestrator(
        self, sample_item: Item
    ) -> None:
        """source_config in context overrides item.quality_tier (Fix B path)."""
        item = Item(**{**sample_item.to_dict(), "quality_tier": 1})
        context = {
            "source_config": {"quality_tier": 3},
            "topic_keywords": ["IVF"],
        }
        results = run_quality_gates(item, context)

        g1 = results["G1-SourceAuthority"]
        assert g1.flagged is True
        assert g1.details["quality_tier"] == 3

    def test_g2_detects_duplicate_in_orchestrator(
        self, sample_item: Item, sample_kb_entry: KBEntry
    ) -> None:
        existing = [
            KBEntry(**{**sample_kb_entry.to_dict(), "source_url": sample_item.source_url})
        ]
        context = {
            "existing_entries": existing,
            "topic_keywords": ["IVF"],
        }
        results = run_quality_gates(sample_item, context)

        g2 = results["G2-Dedup"]
        assert g2.passed is False
        assert g2.details["is_duplicate"] is True


# ===================================================================
# QualityResult dataclass
# ===================================================================


class TestQualityResult:
    """Verify QualityResult dataclass fields and defaults."""

    def test_default_values(self) -> None:
        r = QualityResult(gate_name="test", passed=True)

        assert r.score == 0.0
        assert r.details == {}
        assert r.flagged is False

    def test_custom_values(self) -> None:
        r = QualityResult(
            gate_name="G1",
            passed=True,
            score=95.0,
            details={"key": "val"},
            flagged=True,
        )

        assert r.gate_name == "G1"
        assert r.passed is True
        assert r.score == 95.0
        assert r.details == {"key": "val"}
        assert r.flagged is True
