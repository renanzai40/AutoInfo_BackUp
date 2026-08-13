"""Tests for the processing pipeline — ``autoinfo.process``.

Covers:

- ``load_cached_items`` — directory walking and deserialisation
- ``run_processing`` — end-to-end pipeline orchestration
- ``ProcessResult`` — correct aggregation of per-item stats
- Error resilience — single-item failures don't stop the pipeline
- CLI wiring — ``autoinfo process`` invokes ``run_processing``

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import ProcessResult, load_cached_items, run_processing
from autoinfo.quality import QualityResult


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def sample_items() -> list[Item]:
    """Return two synthetic items for processing tests."""
    return [
        Item(
            id="item-001",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/1",
            title="First test article about IVF",
            content="This is the content of the first test article about IVF treatment outcomes.",
            content_type="text",
            collected_at="2026-07-15T10:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["IVF"],
            quality_tier=1,
            raw_data={},
        ),
        Item(
            id="item-002",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/2",
            title="Second test article about neuroplasticity",
            content="This is the content of the second test article about synaptic plasticity.",
            content_type="text",
            collected_at="2026-07-15T11:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["neuroplasticity"],
            quality_tier=1,
            raw_data={},
        ),
    ]


@pytest.fixture
def mock_extraction() -> ExtractionResult:
    """Return a predictable :class:`ExtractionResult` for mock LLM calls."""
    return ExtractionResult(
        item_id="item-001",
        title="First test article about IVF",
        tl_dr="A test article about IVF treatment outcomes.",
        key_points=["IVF is a key treatment", "Outcomes depend on many factors"],
        entities=[{"name": "IVF", "type": "procedure", "relevance": 0.9}],
        relevance_score=85.0,
    )


@pytest.fixture
def mock_extraction_second() -> ExtractionResult:
    """Extraction result for the second test item."""
    return ExtractionResult(
        item_id="item-002",
        title="Second test article about neuroplasticity",
        tl_dr="A test article about neuroplasticity and synaptic plasticity.",
        key_points=["Neuroplasticity is key", "Synaptic plasticity matters"],
        entities=[{"name": "Neuroplasticity", "type": "concept", "relevance": 0.85}],
        relevance_score=72.0,
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


def _make_quality_results_duplicate() -> dict[str, QualityResult]:
    """Return quality results where G2 detects a duplicate."""
    return {
        "G1-SourceAuthority": QualityResult(
            gate_name="G1-SourceAuthority", passed=True, score=1.0,
            details={"quality_tier": 1, "source_name": "pubmed"},
        ),
        "G2-Dedup": QualityResult(
            gate_name="G2-Dedup", passed=False, score=0.0,
            flagged=True,
            details={
                "is_duplicate": True, "matched_by": "url",
                "existing_id": "existing-entry",
            },
        ),
        "G3-RelevanceScoring": QualityResult(
            gate_name="G3-RelevanceScoring", passed=True, score=85.0,
            details={"hidden": False},
        ),
    }


# ===================================================================
# Test: Item.from_dict resilience (partial/malformed dicts)
# ===================================================================


class TestItemFromDict:
    """``Item.from_dict()`` resilience to missing/extra keys."""

    def test_from_dict_empty(self) -> None:
        """Empty dict returns an Item with all default values."""
        item = Item.from_dict({})
        assert item.id == ""
        assert item.title == ""
        assert item.content == ""
        assert item.source_url == ""
        assert item.source_type == ""
        assert item.source_name == ""
        assert item.content_type == "text"
        assert item.topic_tags == []
        assert item.quality_tier == 1
        assert item.raw_data == {}

    def test_from_dict_missing_source_url(self) -> None:
        """Missing ``source_url`` fills with empty string."""
        item = Item.from_dict({
            "id": "x",
            "source_name": "pubmed",
            "source_type": "api",
            "title": "Test",
            "content": "Body",
        })
        assert item.source_url == ""
        assert item.id == "x"
        assert item.title == "Test"

    def test_from_dict_extra_keys(self) -> None:
        """Extra keys in the dict are silently ignored."""
        item = Item.from_dict({
            "id": "x",
            "source_name": "pubmed",
            "source_type": "api",
            "source_url": "https://example.com",
            "title": "Test",
            "content": "Body",
            "bogus_field": "should be ignored",
            "_unused": 42,
        })
        assert item.id == "x"
        assert item.title == "Test"
        assert not hasattr(item, "bogus_field")

    def test_from_dict_wrong_types(self) -> None:
        """Non-string values for str fields are accepted as-is (no crash)."""
        item = Item.from_dict({
            "id": "x",
            "source_name": "pubmed",
            "source_type": "api",
            "source_url": "https://example.com",
            "title": "Test",
            "content": "Body",
            "quality_tier": "3",  # str instead of int
        })
        assert item.id == "x"
        # quality_tier will be the raw value passed through
        assert item.quality_tier == "3"


# ===================================================================
# Test: load_cached_items
# ===================================================================


class TestLoadCachedItems:
    """``load_cached_items()`` — cache directory walking."""

    def test_empty_when_dir_missing(self) -> None:
        """Return empty list when ``collections/<domain>/`` does not exist."""
        items = load_cached_items("nonexistent-domain")
        assert items == []

    def test_empty_when_dir_empty(self, tmp_path: Path) -> None:
        """Return empty list when the cache directory has no files."""
        cache_dir = tmp_path / "collections" / "test-domain"
        cache_dir.mkdir(parents=True)

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")
        assert items == []

    def test_loads_valid_items(self, tmp_path: Path) -> None:
        """Valid JSON cache files are loaded as :class:`Item` objects."""
        cache_file = (
            tmp_path / "collections" / "test-domain" / "pubmed" / "2026-07-15" / "item-001.json"
        )
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({
                "id": "item-001",
                "source_name": "pubmed",
                "source_type": "api",
                "source_url": "https://example.com/1",
                "title": "Test",
                "content": "content",
                "collected_at": "2026-07-15T10:00:00Z",
            }),
            encoding="utf-8",
        )

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")

        assert len(items) == 1
        assert items[0].id == "item-001"
        assert items[0].title == "Test"

    def test_skips_malformed_files(self, tmp_path: Path, caplog) -> None:
        """Malformed JSON files are skipped with a warning."""
        cache_file = (
            tmp_path / "collections" / "test-domain" / "pubmed" / "2026-07-15" / "bad.json"
        )
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("this is not json", encoding="utf-8")

        caplog.set_level(logging.WARNING)

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")

        assert items == []
        assert "Skipping malformed cache file" in caplog.text

    def test_skips_non_dict_json(self, tmp_path: Path, caplog) -> None:
        """Valid JSON that is not a dict (e.g. list) is skipped."""
        cache_file = (
            tmp_path / "collections" / "test-domain" / "pubmed" / "2026-07-15" / "array.json"
        )
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text('["not", "a", "dict"]', encoding="utf-8")

        caplog.set_level(logging.WARNING)

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")

        assert items == []
        assert "expected a JSON object, got list" in caplog.text

    def test_skips_underscore_directories(self, tmp_path: Path) -> None:
        """Directories starting with ``_`` are skipped (e.g. ``_runs``)."""
        valid_dir = tmp_path / "collections" / "test-domain" / "pubmed" / "2026-07-15"
        valid_dir.mkdir(parents=True)
        valid_file = valid_dir / "item-001.json"
        valid_file.write_text(
            json.dumps({
                "id": "item-001",
                "source_name": "pubmed",
                "source_type": "api",
                "source_url": "https://example.com/1",
                "title": "Test",
                "content": "content",
                "collected_at": "2026-07-15T10:00:00Z",
            }),
            encoding="utf-8",
        )

        # Create a _runs directory that should be skipped
        skip_dir = tmp_path / "collections" / "test-domain" / "pubmed" / "_runs"
        skip_dir.mkdir(parents=True)
        (skip_dir / "run.json").write_text("{}", encoding="utf-8")

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")

        assert len(items) == 1  # _runs file was not loaded

    def test_loads_multiple_sources(self, tmp_path: Path) -> None:
        """Items from multiple source directories are all loaded."""
        src1 = tmp_path / "collections" / "test-domain" / "pubmed" / "2026-07-15"
        src2 = tmp_path / "collections" / "test-domain" / "rss-feed" / "2026-07-15"
        src1.mkdir(parents=True)
        src2.mkdir(parents=True)

        (src1 / "a.json").write_text(
            json.dumps({"id": "a", "source_name": "pubmed", "source_type": "api",
                        "source_url": "", "title": "A", "content": "a",
                        "collected_at": "now"}),
            encoding="utf-8",
        )
        (src2 / "b.json").write_text(
            json.dumps({"id": "b", "source_name": "rss", "source_type": "rss",
                        "source_url": "", "title": "B", "content": "b",
                        "collected_at": "now"}),
            encoding="utf-8",
        )

        items = load_cached_items("test-domain", base_path=tmp_path / "collections")

        assert len(items) == 2
        assert {i.id for i in items} == {"a", "b"}


# ===================================================================
# Test: run_processing
# ===================================================================


class TestRunProcessing:
    """``run_processing()`` — pipeline orchestration."""

    def test_empty_cache_returns_zero_counts(self) -> None:
        """No cached items yields a ProcessResult with zero counts."""
        with patch("autoinfo.process.load_cached_items", return_value=[]):
            result = run_processing("medical-research")

        assert isinstance(result, ProcessResult)
        assert result.total_items == 0
        assert result.passed_gates == 0
        assert result.kb_entries_created == 0
        assert result.errors == []

    def test_happy_path(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
        mock_extraction_second: ExtractionResult,
    ) -> None:
        """Full pipeline processes all items and creates KB entries."""
        # Mock extraction — return different results for each call
        mock_ext = MagicMock(side_effect=[mock_extraction, mock_extraction_second])

        # Mock quality gates — always pass
        mock_quality = MagicMock(return_value=_make_quality_results_all_pass())

        # Mock KB store — return a KBEntry
        mock_entry = KBEntry(entry_id="test", title="test", domain="test")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            result = run_processing("medical-research")

        assert result.total_items == 2
        assert result.passed_gates == 2
        assert result.kb_entries_created == 2
        assert result.errors == []
        assert len(result.per_item_logs) == 2
        assert result.duration_s > 0

        # Verify store_entry was called twice
        assert mock_store.store_entry.call_count == 2

    def test_item_failure_does_not_stop_pipeline(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
    ) -> None:
        """When one item fails, the pipeline continues with the next."""
        # Item-002 fails extraction (deterministic under parallel processing)
        def fail_item_two(item: Item, schema=None) -> ExtractionResult:
            if item.id == "item-002":
                raise Exception("LLM failed for item 2")
            return mock_extraction

        mock_ext = MagicMock(side_effect=fail_item_two)

        mock_quality = MagicMock(return_value=_make_quality_results_all_pass())
        mock_entry = KBEntry(entry_id="test", title="test", domain="test")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            result = run_processing("medical-research")

        assert result.total_items == 2
        assert result.passed_gates == 1  # Only first item passed
        assert result.kb_entries_created == 1  # Only first item stored
        assert len(result.errors) == 1
        assert result.errors[0]["item_id"] == "item-002"

        # First item: ok, second: error
        assert result.per_item_logs[0]["status"] == "ok"
        assert result.per_item_logs[1]["status"] == "error"

    def test_duplicate_items_are_logged(
        self,
        sample_items: list[Item],
        mock_extraction: ExtractionResult,
    ) -> None:
        """Duplicate items (G2 fails) are still stored but logged."""
        mock_ext = MagicMock(side_effect=lambda item, schema=None: mock_extraction)

        # Item-002 is a duplicate (deterministic under parallel processing)
        def quality_for_item(item: Item, context=None, gate_config=None, **kwargs):
            if item.id == "item-002":
                return _make_quality_results_duplicate()
            return _make_quality_results_all_pass()

        mock_quality = MagicMock(side_effect=quality_for_item)

        mock_entry = KBEntry(entry_id="test", title="test", domain="test")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            result = run_processing("medical-research")

        assert result.total_items == 2
        assert result.passed_gates == 1  # Only first has all gates passing
        assert result.kb_entries_created == 2  # Both stored
        assert result.per_item_logs[0]["status"] == "ok"
        assert result.per_item_logs[1]["status"] == "duplicate"

    def test_model_override_creates_correct_config(self) -> None:
        """Model override with provider split creates correct config."""
        from autoinfo.config import Config

        cfg = Config()
        from autoinfo.process import _build_config_with_model

        # Full override with provider/model
        result = _build_config_with_model(cfg, "openai/gpt-4o-mini")
        assert result is not None
        assert result.llm.provider == "openai"
        assert result.llm.model == "gpt-4o-mini"

        # Model-only override
        result = _build_config_with_model(cfg, "gpt-4o")
        assert result is not None
        assert result.llm.model == "gpt-4o"
        # Provider should be unchanged
        assert result.llm.provider == ""

        # None override returns original config
        result = _build_config_with_model(cfg, None)
        assert result is cfg

    def test_model_override_no_config(self) -> None:
        """_build_config_with_model creates minimal config when None passed."""
        from autoinfo.process import _build_config_with_model

        result = _build_config_with_model(None, "test-model")
        assert result is not None
        assert result.llm.model == "test-model"

    def test_process_result_dataclass(self) -> None:
        """ProcessResult dataclass fields work correctly."""
        result = ProcessResult(
            domain="medical-research",
            total_items=5,
            passed_gates=3,
            kb_entries_created=3,
            errors=[{"item_id": "bad", "error": "fail"}],
            duration_s=12.5,
            per_item_logs=[{"item_id": "item1", "status": "ok"}],
        )

        assert result.domain == "medical-research"
        assert result.total_items == 5
        assert result.passed_gates == 3
        assert result.kb_entries_created == 3
        assert len(result.errors) == 1
        assert result.duration_s == 12.5
        assert len(result.per_item_logs) == 1


# ===================================================================
# Test: Language detection
# ===================================================================


class TestLanguageDetection:
    """``detect_language()`` — auto-detect text language."""

    def test_detect_english(self) -> None:
        """English text is detected as ``"en"``."""
        from autoinfo.process import detect_language

        fake_lang_en = type("Lang", (), {"lang": "en", "prob": 0.95})()

        with patch("langdetect.detect_langs", return_value=[fake_lang_en]):
            result = detect_language("This is a sample English text to detect language.")
        assert result == "en"

    def test_detect_chinese(self) -> None:
        """Chinese text is detected as ``"zh-cn"`` or ``"zh"``."""
        from autoinfo.process import detect_language

        fake_lang_zh = type("Lang", (), {"lang": "zh-cn", "prob": 0.97})()

        long_zh = "这是一段比较长的中文文本，用来测试语言检测功能是否能够正确识别中文语言。"
        with patch("langdetect.detect_langs", return_value=[fake_lang_zh]):
            result = detect_language(long_zh)
        assert result in ("zh-cn", "zh")

    def test_detect_short_text(self) -> None:
        """Very short text (< 20 chars) returns ``"unknown"``."""
        from autoinfo.process import detect_language

        result = detect_language("Hi")
        assert result == "unknown"


# ===================================================================
# Test: CLI wiring
# ===================================================================


class TestProcessCli:
    """``autoinfo process`` CLI command."""

    def test_process_help(self, cli_runner) -> None:
        """``--help`` shows expected parameters."""
        from autoinfo.cli import app

        result = cli_runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.stdout
        assert "--model" in result.stdout
        assert "--batch-size" in result.stdout
        assert "--json" in result.stdout

    def test_process_missing_domain(self, cli_runner) -> None:
        """Missing ``--domain`` shows error."""
        from autoinfo.cli import app

        result = cli_runner.invoke(app, ["process"])
        assert result.exit_code != 0
        # Typer outputs option errors to stderr
        assert "Missing option" in result.stdout or "Missing option" in result.stderr

    def test_process_with_mocked_run(
        self, cli_runner, sample_items: list[Item]
    ) -> None:
        """``autoinfo process --domain X`` calls ``run_processing``."""
        from autoinfo.cli import app

        mock_proc = MagicMock(return_value=ProcessResult(
            domain="test-domain",
            total_items=3,
            processed_count=3,
            remaining_count=0,
            is_complete=True,
            passed_gates=2,
            kb_entries_created=2,
            duration_s=5.0,
            per_item_logs=[
                {"item_id": "a", "title": "A", "status": "ok", "g3_score": 85.0, "duration_s": 0.5},
                {"item_id": "b", "title": "B", "status": "ok", "g3_score": 72.0, "duration_s": 0.6},
            ],
        ))

        with patch("autoinfo.cli.process.run_processing", mock_proc):
            result = cli_runner.invoke(app, ["process", "--domain", "test-domain"])

        assert result.exit_code == 0
        assert "Processing domain: test-domain" in result.stdout
        assert "Summary: 3 items" in result.stdout
        assert "2 passed G1-G3" in result.stdout
        assert "2 KB entries created" in result.stdout
        # No batch message because is_complete=True
        assert "Batch progress" not in result.stdout

    def test_process_json_output(self, cli_runner) -> None:
        """``--json`` flag produces parseable JSON."""
        from autoinfo.cli import app

        mock_proc = MagicMock(return_value=ProcessResult(
            domain="test-domain",
            total_items=1,
            processed_count=1,
            remaining_count=0,
            is_complete=True,
            passed_gates=1,
            kb_entries_created=1,
            duration_s=2.0,
            per_item_logs=[{"item_id": "a", "title": "A", "status": "ok", "g3_score": 90.0, "duration_s": 0.3}],
        ))

        with patch("autoinfo.cli.process.run_processing", mock_proc):
            result = cli_runner.invoke(app, [
                "process", "--domain", "test-domain", "--json",
            ])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["domain"] == "test-domain"
        assert data["total_items"] == 1
        assert data["processed_count"] == 1
        assert data["remaining_count"] == 0
        assert data["is_complete"] is True
        assert data["kb_entries_created"] == 1

    def test_process_help_shows_check_translation(self, cli_runner) -> None:
        """``--help`` shows ``--check-translation`` parameter."""
        from autoinfo.cli import app

        result = cli_runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0
        assert "--check-translation" in result.stdout

    def test_process_check_translation_passed_to_run(
        self, cli_runner
    ) -> None:
        """``--check-translation`` flag is forwarded to ``run_processing``."""
        from autoinfo.cli import app

        with patch("autoinfo.cli.process.run_processing") as mock_proc:
            mock_proc.return_value = ProcessResult(
                domain="test-domain", total_items=0,
                processed_count=0, remaining_count=0, is_complete=True,
                passed_gates=0, kb_entries_created=0, duration_s=0.0,
            )
            result = cli_runner.invoke(app, [
                "process", "--domain", "test-domain", "--check-translation",
            ])

        assert result.exit_code == 0
        mock_proc.assert_called_once()
        _, kwargs = mock_proc.call_args
        assert kwargs.get("check_translation") is True

    def test_process_exit_code_on_errors(self, cli_runner) -> None:
        """Exit code 1 when processing has errors."""
        from autoinfo.cli import app

        mock_proc = MagicMock(return_value=ProcessResult(
            domain="test-domain",
            total_items=2,
            processed_count=2,
            remaining_count=0,
            is_complete=True,
            passed_gates=1,
            kb_entries_created=1,
            errors=[{"item_id": "b", "error": "LLM failure"}],
            duration_s=3.0,
            per_item_logs=[
                {"item_id": "a", "title": "A", "status": "ok", "g3_score": 85.0, "duration_s": 0.5},
                {"item_id": "b", "title": "B", "status": "error", "error": "LLM failure", "duration_s": 1.2},
            ],
        ))

        with patch("autoinfo.cli.process.run_processing", mock_proc):
            result = cli_runner.invoke(app, ["process", "--domain", "test-domain"])

        assert result.exit_code == 1
        # Error count is written to stderr with err=True
        assert "1 item(s) failed processing" in result.stderr


# ===================================================================
# Test: auto-process CLI flag (via collect)
# ===================================================================


class TestAutoProcessFlag:
    """``autoinfo collect --auto-process`` chains collect → process."""

    def test_auto_process_calls_run_processing(self, cli_runner) -> None:
        """``--auto-process`` invokes ``run_processing`` after collection."""
        from autoinfo.cli import app

        # Mock collection to return items
        with (
            patch(
                "autoinfo.collect.run_collection",
                return_value={
                    "collection_id": "col-test",
                    "domain": "medical-research",
                    "total_found": 3,
                    "total_new": 2,
                    "duration_s": 1.5,
                    "per_source": [
                        {"source": "pubmed", "status": "success",
                         "items_found": 3, "items_new": 2, "duration_s": 1.2,
                         "errors": []},
                    ],
                    "dry_run": False,
                },
            ),
            patch(
                "autoinfo.process.run_processing",
                return_value=ProcessResult(
                    domain="medical-research",
                    total_items=2,
                    processed_count=2,
                    remaining_count=0,
                    is_complete=True,
                    passed_gates=2,
                    kb_entries_created=2,
                    duration_s=5.0,
                ),
            ),
        ):
            result = cli_runner.invoke(app, [
                "collect",
                "--domain", "medical-research",
                "--topic", "IVF",
                "--limit", "3",
                "--auto-process",
            ])

        assert result.exit_code == 0
        assert "── Running auto-process ──" in result.stdout
        assert "Processing: 2 items → 2 passed G1-G3 → 2 KB entries created" in result.stdout

    def test_auto_process_no_new_items(self, cli_runner) -> None:
        """``--auto-process`` is skipped when no new items were collected."""
        from autoinfo.cli import app

        with patch(
            "autoinfo.collect.run_collection",
            return_value={
                "collection_id": "col-test",
                "domain": "medical-research",
                "total_found": 0,
                "total_new": 0,
                "duration_s": 0.5,
                "per_source": [],
                "dry_run": False,
            },
        ):
            result = cli_runner.invoke(app, [
                "collect",
                "--domain", "medical-research",
                "--auto-process",
            ])

        assert result.exit_code == 0
        assert "No new items — skipping auto-process." in result.stdout

    def test_auto_process_dry_run_skips(self, cli_runner) -> None:
        """``--auto-process`` with ``--dry-run`` does not run processing."""
        from autoinfo.cli import app

        with patch(
            "autoinfo.collect.run_collection",
            return_value={
                "collection_id": "col-test",
                "domain": "medical-research",
                "total_found": 5,
                "total_new": 5,
                "duration_s": 1.0,
                "per_source": [],
                "dry_run": True,
            },
        ):
            result = cli_runner.invoke(app, [
                "collect",
                "--domain", "medical-research",
                "--dry-run",
                "--auto-process",
            ])

        assert result.exit_code == 0
        assert "Running auto-process" not in result.stdout
        assert "Dry-run" in result.stdout
