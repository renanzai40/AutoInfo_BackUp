"""Tests for keyword auto-discovery hygiene (issue #179).

Covers the auto-discovery step of the processing pipeline:

- Junk candidates (stopwords, single characters, digits, punctuation,
  stopword-only phrases) are never written to the domain keyword store
- Valid candidates are still discovered and written (AUTO_ADDED)
- ``DomainConfig.auto_keyword_discovery = False`` disables the writes
- ``DomainConfig.max_auto_keywords`` caps the number of AUTO_ADDED
  keywords per domain (skip, never an error)
- Defaults preserve pre-#179 behavior for existing configs

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import Config, DomainConfig, config_to_dict, load_config
from autoinfo.kb import KBStore
from autoinfo.keywords import KeywordsFile, KeywordState
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import run_processing
from autoinfo.quality import QualityResult

# ===================================================================
# Fixtures / helpers
# ===================================================================

DOMAIN = "kw-test"


def _item(item_id: str) -> Item:
    """Return a minimal synthetic item for keyword discovery tests."""
    return Item(
        id=item_id,
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url=f"https://example.com/{item_id}",
        title="Test article",
        content="Test content.",
        content_type="text",
        collected_at="2026-07-15T10:00:00Z",
        language="en",
        domain=DOMAIN,
        topic_tags=[],
        quality_tier=1,
        raw_data={},
    )


def _make_quality_results_all_pass() -> dict[str, QualityResult]:
    """Return quality gate results where all three gates pass."""
    return {
        "G1-SourceAuthority": QualityResult(
            gate_name="G1-SourceAuthority", passed=True, score=1.0,
            details={"quality_tier": 1, "source_name": "pubmed"},
        ),
        "G2-Dedup": QualityResult(
            gate_name="G2-Dedup", passed=True, score=1.0,
            details={"is_duplicate": False, "matched_by": None},
        ),
        "G3-RelevanceScoring": QualityResult(
            gate_name="G3-RelevanceScoring", passed=True, score=85.0,
            details={"hidden": False},
        ),
    }


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    items: list[Item],
    extraction: ExtractionResult,
    config: Config | None = None,
):
    """Run the processing pipeline with a mocked LLM and isolated cwd.

    ``chdir`` to *tmp_path* so the real ``KeywordsFile`` (default base dir
    is the cwd) writes to ``tmp_path/knowledge/<domain>/_keywords.yaml``.
    When *config* is provided, ``get_config_path``/``load_config`` are
    patched so the pipeline picks it up; otherwise no config exists and
    the pre-#179 defaults apply.
    """
    monkeypatch.chdir(tmp_path)
    mock_store = MagicMock(spec=KBStore)
    mock_store.store_entry.return_value = KBEntry(
        entry_id="test", title="test", domain=DOMAIN
    )
    mock_store.list_entries.return_value = []
    with ExitStack() as stack:
        stack.enter_context(
            patch("autoinfo.process.load_cached_items", return_value=items)
        )
        stack.enter_context(
            patch.object(
                LLMExtractor,
                "extract",
                MagicMock(return_value=extraction),
            )
        )
        stack.enter_context(
            patch(
                "autoinfo.process.run_quality_gates",
                MagicMock(return_value=_make_quality_results_all_pass()),
            )
        )
        stack.enter_context(
            patch("autoinfo.process.KBStore", return_value=mock_store)
        )
        if config is not None:
            stack.enter_context(
                patch(
                    "autoinfo.process.get_config_path",
                    return_value=tmp_path / ".autoinfo" / "config.yaml",
                )
            )
            stack.enter_context(
                patch("autoinfo.process.load_config", return_value=config)
            )
        return run_processing(DOMAIN)


def _extraction(
    item_id: str = "item-001",
    key_points: list[str] | None = None,
    entities: list[dict] | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        item_id=item_id,
        title="Test article",
        tl_dr="A test article.",
        key_points=key_points or [],
        entities=entities or [],
        relevance_score=85.0,
    )


def _keywords(tmp_path: Path) -> list[str]:
    """Return the keyword strings stored for the test domain."""
    return [e.keyword for e in KeywordsFile(base_dir=tmp_path).load(DOMAIN)]


# ===================================================================
# (a) Junk candidates are never added by auto-discovery
# ===================================================================


class TestJunkCandidatesRejected:
    """Stopwords, digits, punctuation and single chars are filtered out."""

    def test_junk_not_added_and_valid_kept(self, monkeypatch, tmp_path: Path) -> None:
        extraction = _extraction(
            key_points=[
                "the study",      # every word is a stopword
                "results 2024",   # contains a digit-only token
            ],
            entities=[
                {"name": "the", "type": "concept"},      # stopword
                {"name": "2024", "type": "concept"},     # digits only
                {"name": "!!", "type": "concept"},       # punctuation only
                {"name": "a", "type": "concept"},        # single character
                {"name": "CRISPR", "type": "technique"},  # valid
            ],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction)

        keywords = _keywords(tmp_path)
        assert "crispr" in keywords
        for junk in ("the", "2024", "!!", "a", "the study", "results 2024"):
            assert junk not in keywords

    def test_all_written_entries_are_auto_added(self, monkeypatch, tmp_path: Path) -> None:
        extraction = _extraction(
            entities=[{"name": "CRISPR", "type": "technique"}],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction)

        entries = KeywordsFile(base_dir=tmp_path).load(DOMAIN)
        assert len(entries) == 1
        assert entries[0].keyword == "crispr"
        assert entries[0].state == KeywordState.AUTO_ADDED
        assert entries[0].source.startswith("auto-discovery:")


class TestHygieneHelper:
    """Unit tests for the shared ``_is_valid_discovery_keyword`` helper."""

    @staticmethod
    def _helper():
        from autoinfo.process import _is_valid_discovery_keyword
        return _is_valid_discovery_keyword

    def test_rejects_junk_candidates(self) -> None:
        helper = self._helper()
        for junk in (
            "the", "this", "with",           # stopwords
            "the study", "results shown",    # stopword-only phrases
            "2024", "42",                    # digits
            "!!", "...", "???",              # punctuation
            "a", "x",                        # too short (min_length=2)
            "   ", "",                       # whitespace / empty
            "results 2024",                  # digit-only token inside phrase
        ):
            assert not helper(junk), junk

    def test_accepts_valid_candidates(self) -> None:
        helper = self._helper()
        for valid in (
            "crispr", "gene editing", "climate change",
            "machine learning", "ai", "ml", "dna",
        ):
            assert helper(valid), valid

    def test_case_insensitive_stopwords(self) -> None:
        helper = self._helper()
        assert not helper("The")
        assert not helper("  THE  ")

    def test_min_length_knob(self) -> None:
        helper = self._helper()
        assert helper("ab", min_length=2)
        assert not helper("ab", min_length=3)
        assert helper("abc", min_length=3)


# ===================================================================
# (b) Valid candidate keywords ARE added (existing behavior preserved)
# ===================================================================


class TestValidCandidatesAdded:
    """Real keywords from entity names and key points still get added."""

    def test_valid_keywords_added(self, monkeypatch, tmp_path: Path) -> None:
        extraction = _extraction(
            key_points=[
                "Machine learning improves outcomes",
                "climate change research",
            ],
            entities=[
                {"name": "CRISPR", "type": "technique"},
                {"name": "gene editing", "type": "technique"},
            ],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction)

        keywords = _keywords(tmp_path)
        for expected in (
            "crispr", "gene editing",
            "machine", "learning",
            "climate change", "machine learning",
        ):
            assert expected in keywords


# ===================================================================
# (c) Toggle: auto_keyword_discovery=False writes nothing
# ===================================================================


class TestDiscoveryToggle:
    """``auto_keyword_discovery: false`` disables auto-discovery writes."""

    def test_disabled_writes_no_keywords(self, monkeypatch, tmp_path: Path) -> None:
        config = Config(
            domains=[DomainConfig(name=DOMAIN, auto_keyword_discovery=False)]
        )
        extraction = _extraction(
            entities=[
                {"name": "CRISPR", "type": "technique"},
                {"name": "gene editing", "type": "technique"},
            ],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction, config=config)

        # Nothing written — the keywords file does not even exist.
        assert KeywordsFile(base_dir=tmp_path).load(DOMAIN) == []


# ===================================================================
# (d) Cap: max_auto_keywords bounds AUTO_ADDED growth
# ===================================================================


class TestAutoKeywordCap:
    """``max_auto_keywords`` caps AUTO_ADDED keyword growth (skip, no error)."""

    def test_cap_limits_new_auto_keywords(self, monkeypatch, tmp_path: Path) -> None:
        # Pre-seed 2 AUTO_ADDED keywords; cap is 3 → only 1 new keyword may
        # be added, and later candidates must be skipped without error.
        kf = KeywordsFile(base_dir=tmp_path)
        kf.add_keyword(DOMAIN, "seed-0")
        kf.add_keyword(DOMAIN, "seed-1")

        config = Config(domains=[DomainConfig(name=DOMAIN, max_auto_keywords=3)])
        extraction = _extraction(
            entities=[
                {"name": "k1", "type": "concept"},
                {"name": "k2", "type": "concept"},
                {"name": "k3", "type": "concept"},
                {"name": "k4", "type": "concept"},
                {"name": "k5", "type": "concept"},
                {"name": "k6", "type": "concept"},
            ],
        )
        result = _run(monkeypatch, tmp_path, [_item("item-001")], extraction, config=config)

        entries = KeywordsFile(base_dir=tmp_path).load(DOMAIN)
        auto = [e for e in entries if e.state == KeywordState.AUTO_ADDED]
        assert len(auto) == 3  # 2 seeds + exactly 1 new
        new_ones = {e.keyword for e in auto} - {"seed-0", "seed-1"}
        assert new_ones == {"k1"}
        # Skipped candidates are not an error — the run completes cleanly.
        assert result.errors == []

    def test_cap_reached_preexisting_adds_nothing(self, monkeypatch, tmp_path: Path) -> None:
        kf = KeywordsFile(base_dir=tmp_path)
        for i in range(3):
            kf.add_keyword(DOMAIN, f"seed-{i}")

        config = Config(domains=[DomainConfig(name=DOMAIN, max_auto_keywords=3)])
        extraction = _extraction(
            entities=[{"name": "k1", "type": "concept"}],
        )
        result = _run(monkeypatch, tmp_path, [_item("item-001")], extraction, config=config)

        auto = [
            e for e in KeywordsFile(base_dir=tmp_path).load(DOMAIN)
            if e.state == KeywordState.AUTO_ADDED
        ]
        assert {e.keyword for e in auto} == {"seed-0", "seed-1", "seed-2"}
        assert result.errors == []


# ===================================================================
# (e) Defaults: existing configs/domains behave as before
# ===================================================================


class TestDefaults:
    """Configs without the new fields keep the pre-#179 behavior."""

    def test_dataclass_defaults(self) -> None:
        d = DomainConfig(name=DOMAIN)
        assert d.auto_keyword_discovery is True
        assert d.max_auto_keywords == 100
        assert d.auto_keyword_min_length == 2

    def test_yaml_without_new_fields_gets_defaults(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "domains:\n  - name: kw-test\n    active: true\n",
            encoding="utf-8",
        )
        d = load_config(cfg_path).domains[0]
        assert d.auto_keyword_discovery is True
        assert d.max_auto_keywords == 100
        assert d.auto_keyword_min_length == 2

    def test_yaml_with_new_fields_is_parsed(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "domains:\n"
            "  - name: kw-test\n"
            "    auto_keyword_discovery: false\n"
            "    max_auto_keywords: 5\n"
            "    auto_keyword_min_length: 3\n",
            encoding="utf-8",
        )
        d = load_config(cfg_path).domains[0]
        assert d.auto_keyword_discovery is False
        assert d.max_auto_keywords == 5
        assert d.auto_keyword_min_length == 3
        # Serialization round-trip keeps non-default values.
        out = config_to_dict(Config(domains=[d]))
        assert out["domains"][0]["auto_keyword_discovery"] is False
        assert out["domains"][0]["max_auto_keywords"] == 5
        assert out["domains"][0]["auto_keyword_min_length"] == 3

    def test_no_config_still_discovers(self, monkeypatch, tmp_path: Path) -> None:
        """No config file at all (config=None) → discovery runs with defaults."""
        extraction = _extraction(
            entities=[{"name": "CRISPR", "type": "technique"}],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction)

        assert "crispr" in _keywords(tmp_path)

    def test_explicitly_enabled_matches_default(self, monkeypatch, tmp_path: Path) -> None:
        config = Config(
            domains=[DomainConfig(name=DOMAIN, auto_keyword_discovery=True)]
        )
        extraction = _extraction(
            entities=[{"name": "CRISPR", "type": "technique"}],
        )
        _run(monkeypatch, tmp_path, [_item("item-001")], extraction, config=config)

        assert "crispr" in _keywords(tmp_path)
