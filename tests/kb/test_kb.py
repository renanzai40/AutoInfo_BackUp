"""Tests for the KB storage system (KBStore + SQLiteIndex).

Covers:
    - Markdown file creation with correct YAML frontmatter
    - All required frontmatter fields present
    - SQLite index store & retrieve
    - list_entries pagination and ordering
    - get_entry full content reading from file
    - 100+ entries listed in <100ms (performance gate)
    - Quality results integration (relevance_score, dedup_status)
    - Extraction integration (TL;DR, key points in body)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from autoinfo.kb import KBStore, SQLiteIndex, _slugify
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.quality import QualityResult

# ===================================================================
# _slugify helper
# ===================================================================


class TestSlugify:
    def test_basic_slug(self) -> None:
        assert _slugify("Improved IVF outcomes: a RCT") == "improved-ivf-outcomes-a-rct"

    def test_multiple_spaces_and_punctuation(self) -> None:
        assert _slugify("Hello   World!!!") == "hello-world"

    def test_trailing_hyphens_removed(self) -> None:
        assert _slugify("hello-") == "hello"

    def test_leading_hyphens_removed(self) -> None:
        assert _slugify("-hello") == "hello"

    def test_max_len(self) -> None:
        long = "a-" * 100
        result = _slugify(long, max_len=80)
        assert len(result) <= 80
        assert not result.endswith("-")

    def test_unicode_preserved(self) -> None:
        slug = _slugify("IVF 辅助生殖技术")
        assert "ivf" in slug
        # Non-ASCII chars get replaced by hyphens
        assert all(c in "-abcdefghijklmnopqrstuvwxyz0123456789" for c in slug)


# ===================================================================
# SQLiteIndex
# ===================================================================


class TestSQLiteIndex:
    """Test the low-level SQLite index independently."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_autoinfo.db"

    @pytest.fixture
    def index(self, db_path: Path) -> SQLiteIndex:
        idx = SQLiteIndex(db_path)
        idx.init_db()
        return idx

    @pytest.fixture
    def sample_entry(self) -> KBEntry:
        return KBEntry(
            entry_id="medical-research-ivf-improved-ivf-outcomes",
            title="Improved IVF outcomes with time-lapse imaging",
            domain="medical-research",
            tier="01-Raw",
            source_url="https://example.com/article1",
            source_type="api",
            source_platform="pubmed",
            collected_at="2026-07-15T10:30:00Z",
            summary="Time-lapse improves live birth rates.",
            tags=["IVF", "time-lapse"],
            quality_tier=1,
            relevance_score=92.0,
            dedup_status="unique",
            file_path="knowledge/medical-research/01-Raw/IVF/2026-07-15-improved-ivf-outcomes.md",
        )

    def test_init_db_creates_tables(self, db_path: Path, index: SQLiteIndex) -> None:
        """Verify tables and indexes are created on init."""
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert ("entries",) in tables

        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {r[0] for r in indexes}
        assert "idx_domain" in index_names
        assert "idx_collected_at" in index_names
        conn.close()

    def test_index_and_retrieve_entry(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        index.index_entry(sample_entry)
        retrieved = index.get_entry(sample_entry.entry_id)
        assert retrieved is not None
        assert retrieved["entry_id"] == sample_entry.entry_id
        assert retrieved["title"] == sample_entry.title
        assert retrieved["domain"] == sample_entry.domain
        assert retrieved["source_url"] == sample_entry.source_url

    def test_index_entry_tags_stored_as_json(
        self, index: SQLiteIndex, sample_entry: KBEntry
    ) -> None:
        index.index_entry(sample_entry)
        retrieved = index.get_entry(sample_entry.entry_id)
        assert retrieved is not None
        tags = json.loads(retrieved["tags"])
        assert tags == ["IVF", "time-lapse"]

    def test_list_entries_empty(self, index: SQLiteIndex) -> None:
        entries = index.list_entries("medical-research")
        assert entries == []

    def test_list_entries_with_data(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        index.index_entry(sample_entry)
        entries = index.list_entries("medical-research")
        assert len(entries) == 1
        assert entries[0]["entry_id"] == sample_entry.entry_id

    def test_list_entries_domain_filter(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        index.index_entry(sample_entry)
        # Wrong domain
        entries = index.list_entries("ai-commercial")
        assert entries == []
        # Correct domain
        entries = index.list_entries("medical-research")
        assert len(entries) == 1

    def test_list_entries_ordered_by_collected_at_desc(self, index: SQLiteIndex) -> None:
        entries_data = [
            KBEntry(
                entry_id=f"entry-{i:03d}",
                title=f"Entry {i}",
                domain="medical-research",
                collected_at=f"2026-07-{15 - i:02d}T10:00:00Z",
                source_url=f"https://example.com/{i}",
                tags=[],
            )
            for i in range(5)
        ]
        # Insert in ascending order
        for e in entries_data:
            index.index_entry(e)

        entries = index.list_entries("medical-research", limit=10)
        # Should come back newest first
        dates = [e["collected_at"] for e in entries]
        assert dates == sorted(dates, reverse=True)

    def test_list_entries_pagination(self, index: SQLiteIndex) -> None:
        for i in range(10):
            index.index_entry(
                KBEntry(
                    entry_id=f"entry-{i:03d}",
                    title=f"Entry {i}",
                    domain="medical-research",
                    collected_at=f"2026-07-{15:02d}T10:00:0{i}Z",
                    source_url=f"https://example.com/{i}",
                    tags=[],
                )
            )

        # Page 1 (limit=3)
        page1 = index.list_entries("medical-research", limit=3, offset=0)
        assert len(page1) == 3
        # Page 2 (limit=3, offset=3)
        page2 = index.list_entries("medical-research", limit=3, offset=3)
        assert len(page2) == 3
        # Page 4 (offset=9) — should have 1 entry
        page4 = index.list_entries("medical-research", limit=3, offset=9)
        assert len(page4) == 1
        # No overlap
        ids_p1 = {e["entry_id"] for e in page1}
        ids_p2 = {e["entry_id"] for e in page2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_list_entries_date_filter(self, index: SQLiteIndex) -> None:
        index.index_entry(
            KBEntry(
                entry_id="old",
                title="Old entry",
                domain="medical-research",
                collected_at="2026-06-01T00:00:00Z",
                source_url="https://example.com/old",
                tags=[],
            )
        )
        index.index_entry(
            KBEntry(
                entry_id="new",
                title="New entry",
                domain="medical-research",
                collected_at="2026-07-15T00:00:00Z",
                source_url="https://example.com/new",
                tags=[],
            )
        )

        # date_from = 2026-07-01 — strict collected_at would keep only "new",
        # but the #182 created_at fallback keeps both (both indexed just now
        # with fresh created_at). Digest generation never sees empty.
        entries = index.list_entries("medical-research", date_from="2026-07-01")
        assert len(entries) == 2
        assert entries[0]["entry_id"] == "new"

        # date_from = 2026-01-01 — should include both
        entries = index.list_entries("medical-research", date_from="2026-01-01")
        assert len(entries) == 2

    def test_get_entry_nonexistent(self, index: SQLiteIndex) -> None:
        assert index.get_entry("does-not-exist") is None

    def test_get_entry_with_tags(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        index.index_entry(sample_entry)
        retrieved = index.get_entry(sample_entry.entry_id)
        assert retrieved is not None
        # Tags stored as JSON string
        assert json.loads(retrieved["tags"]) == ["IVF", "time-lapse"]

    def test_search_by_field(self, index: SQLiteIndex) -> None:
        index.index_entry(
            KBEntry(
                entry_id="e1",
                title="IVF breakthroughs 2026",
                domain="medical-research",
                source_url="https://example.com/ivf",
                source_type="api",
                source_platform="pubmed",
                collected_at="2026-07-15T00:00:00Z",
                tags=[],
            )
        )
        index.index_entry(
            KBEntry(
                entry_id="e2",
                title="AI in healthcare",
                domain="medical-research",
                source_url="https://example.com/ai",
                source_type="api",
                source_platform="arxiv",
                collected_at="2026-07-16T00:00:00Z",
                tags=[],
            )
        )

        results = index.search_by_field("title", "IVF")
        assert len(results) == 1
        assert results[0]["entry_id"] == "e1"

        results = index.search_by_field("source_platform", "arxiv")
        assert len(results) == 1
        assert results[0]["entry_id"] == "e2"

    def test_search_by_field_invalid(self, index: SQLiteIndex) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            index.search_by_field("relevance_score", "high")

    def test_count_entries(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        assert index.count_entries() == 0
        assert index.count_entries("medical-research") == 0
        index.index_entry(sample_entry)
        assert index.count_entries() == 1
        assert index.count_entries("medical-research") == 1
        assert index.count_entries("ai-commercial") == 0

    def test_index_entry_update_replaces(self, index: SQLiteIndex, sample_entry: KBEntry) -> None:
        index.index_entry(sample_entry)
        updated = KBEntry(**{**sample_entry.to_dict(), "title": "Updated title"})
        index.index_entry(updated)
        assert index.count_entries() == 1
        retrieved = index.get_entry(sample_entry.entry_id)
        assert retrieved is not None
        assert retrieved["title"] == "Updated title"


# ===================================================================
# KBStore
# ===================================================================


class TestKBStore:
    """Tests for the high-level KBStore."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        """Create a KBStore rooted in a temp directory."""
        return KBStore(base_path=tmp_path / "knowledge")

    @pytest.fixture
    def sample_item(self) -> Item:
        return Item(
            id="test-item-001",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=12345678",
            title="Improved IVF outcomes with time-lapse embryo imaging",
            content=(
                "Time-lapse embryo imaging has been proposed as a non-invasive method "
                "to improve embryo selection in IVF cycles."
            ),
            content_type="text",
            collected_at="2026-07-15T10:30:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["IVF", "embryo imaging"],
            quality_tier=1,
        )

    @pytest.fixture
    def sample_extraction(self) -> ExtractionResult:
        return ExtractionResult(
            item_id="test-item-001",
            title="Improved IVF outcomes with time-lapse embryo imaging",
            tl_dr="Time-lapse embryo imaging significantly improves live birth rates.",
            key_points=[
                "Multicenter RCT with 1,200 IVF patients",
                "Live birth rate: 48.2% vs 39.5%",
            ],
            entities=[
                {"name": "Time-lapse embryo imaging", "type": "technology", "relevance": 0.95},
                {"name": "IVF", "type": "procedure", "relevance": 0.90},
            ],
            relevance_score=92.0,
        )

    @pytest.fixture
    def sample_quality_results(self) -> dict[str, QualityResult]:
        return {
            "G1-SourceAuthority": QualityResult(
                gate_name="G1-SourceAuthority",
                passed=True,
                score=1.0,
                flagged=False,
            ),
            "G2-Dedup": QualityResult(
                gate_name="G2-Dedup",
                passed=True,
                score=1.0,
                flagged=False,
                details={"is_duplicate": False, "matched_by": None},
            ),
            "G3-RelevanceScoring": QualityResult(
                gate_name="G3-RelevanceScoring",
                passed=True,
                score=92.0,
                flagged=False,
                details={"hidden": False, "keyword_matches": 2, "total_keywords": 3},
            ),
        }

    # ------------------------------------------------------------------
    # File creation
    # ------------------------------------------------------------------

    def test_store_entry_creates_markdown_file(self, store: KBStore, sample_item: Item) -> None:
        entry = store.store_entry(sample_item)
        # File should exist
        fp = Path(entry.file_path)
        assert fp.exists(), f"Markdown file not created at {fp}"
        assert fp.is_file()

    def test_file_path_follows_convention(self, store: KBStore, sample_item: Item) -> None:
        entry = store.store_entry(sample_item)
        # Expected: knowledge/medical-research/01-Raw/IVF/<date>-<slug>.md
        fp = Path(entry.file_path)
        assert "medical-research" in fp.parts
        assert "01-Raw" in fp.parts
        assert "IVF" in fp.parts
        assert fp.name.endswith(".md")

    def test_frontmatter_contains_all_required_fields(
        self, store: KBStore, sample_item: Item
    ) -> None:
        entry = store.store_entry(sample_item)
        # Read the file and parse frontmatter
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        assert raw.startswith("---")
        end = raw.find("---", 3)
        assert end != -1
        fm = yaml.safe_load(raw[3:end])

        required = [
            "title", "domain", "tier", "entry_id",
            "source_url", "source_type", "source_platform",
            "collected_at", "summary", "tags",
            "quality_tier", "relevance_score", "dedup_status",
            "language",
        ]
        for field in required:
            assert field in fm, f"Missing frontmatter field: {field}"

        # Verify values
        assert fm["title"] == sample_item.title
        assert fm["domain"] == "medical-research"
        assert fm["tier"] == "01-Raw"
        assert fm["source_url"] == sample_item.source_url
        assert fm["source_type"] == "api"
        assert fm["source_platform"] == "pubmed"
        assert fm["collected_at"] == "2026-07-15T10:30:00Z"
        assert fm["quality_tier"] == 1
        assert fm["language"] == "en"

    def test_frontmatter_includes_quality_flags(
        self, store: KBStore, sample_item: Item, sample_quality_results
    ) -> None:
        entry = store.store_entry(sample_item, quality_results=sample_quality_results)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])

        assert "quality_flags" in fm
        flags = fm["quality_flags"]
        assert flags["G1-SourceAuthority"] is False
        assert flags["G3-RelevanceScoring"] is False

    def test_frontmatter_relevance_score_from_quality(
        self, store: KBStore, sample_item: Item, sample_quality_results
    ) -> None:
        entry = store.store_entry(sample_item, quality_results=sample_quality_results)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["relevance_score"] == 92.0

    def test_frontmatter_dedup_status_unique(
        self, store: KBStore, sample_item: Item, sample_quality_results
    ) -> None:
        entry = store.store_entry(sample_item, quality_results=sample_quality_results)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["dedup_status"] == "unique"

    def test_frontmatter_dedup_status_duplicate(self, store: KBStore, sample_item: Item) -> None:
        quality = {
            "G2-Dedup": QualityResult(
                gate_name="G2-Dedup",
                passed=False,
                flagged=True,
                details={"is_duplicate": True, "matched_by": "url", "existing_id": "existing-001"},
            ),
        }
        entry = store.store_entry(sample_item, quality_results=quality)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["dedup_status"] == "duplicate"

    def test_body_contains_original_content(self, store: KBStore, sample_item: Item) -> None:
        entry = store.store_entry(sample_item)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        # Body is after the frontmatter block
        assert sample_item.content in raw

    def test_body_includes_extraction_data(
        self, store: KBStore, sample_item: Item, sample_extraction: ExtractionResult
    ) -> None:
        entry = store.store_entry(sample_item, extraction=sample_extraction)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        assert sample_extraction.tl_dr in raw
        for kp in sample_extraction.key_points:
            assert kp in raw

    # ------------------------------------------------------------------
    # list_entries
    # ------------------------------------------------------------------

    def test_list_entries_empty(self, store: KBStore) -> None:
        entries = store.list_entries("medical-research")
        assert entries == []

    def test_list_entries_after_store(self, store: KBStore, sample_item: Item) -> None:
        store.store_entry(sample_item)
        entries = store.list_entries("medical-research")
        assert len(entries) == 1
        assert entries[0]["title"] == sample_item.title

    def test_list_entries_domain_filter(self, store: KBStore, sample_item: Item) -> None:
        store.store_entry(sample_item)
        entries = store.list_entries("ai-commercial")
        assert entries == []

    def test_list_entries_pagination(self, store: KBStore) -> None:
        for i in range(10):
            item = Item(
                id=f"item-{i:03d}",
                source_name="pubmed",
                source_type="api",
                source_url=f"https://example.com/{i}",
                title=f"Article {i}",
                content=f"Content {i}",
                collected_at=f"2026-07-{15:02d}T10:00:0{i}Z",
                domain="medical-research",
                topic_tags=["IVF"],
            )
            store.store_entry(item)

        page1 = store.list_entries("medical-research", limit=3, offset=0)
        assert len(page1) == 3
        page2 = store.list_entries("medical-research", limit=3, offset=3)
        assert len(page2) == 3
        # Ensure no overlap
        ids_p1 = {e["entry_id"] for e in page1}
        ids_p2 = {e["entry_id"] for e in page2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_list_entries_ordered_by_collected_at_desc(self, store: KBStore) -> None:
        for i in range(5):
            item = Item(
                id=f"item-{i:03d}",
                source_name="pubmed",
                source_type="api",
                source_url=f"https://example.com/{i}",
                title=f"Article {i}",
                content=f"Content {i}",
                # Older items have higher i so they are collected later
                collected_at=f"2026-07-{10 + i:02d}T10:00:00Z",
                domain="medical-research",
                topic_tags=["IVF"],
            )
            store.store_entry(item)

        entries = store.list_entries("medical-research", limit=10)
        # Should be newest first (largest day first)
        dates = [e["collected_at"] for e in entries]
        assert dates == sorted(dates, reverse=True)

    def test_list_entries_date_filter(self, store: KBStore) -> None:
        old_item = Item(
            id="old-item",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/old",
            title="Old article",
            content="Old content",
            collected_at="2026-06-01T00:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
        )
        new_item = Item(
            id="new-item",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/new",
            title="New article",
            content="New content",
            collected_at="2026-07-15T00:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
        )
        store.store_entry(old_item)
        store.store_entry(new_item)

        entries = store.list_entries("medical-research", date_from="2026-07-01")
        # Issue #182: created_at fallback — both items were stored just now
        # (fresh created_at), so even the old-collected_at item passes the
        # weekly window via its ingest time. Digest generation thus never
        # sees an empty domain when sources publish old-dated articles.
        assert len(entries) == 2
        # newest first (both collected_at DESC)
        assert "new-article" in entries[0]["entry_id"]

    # ------------------------------------------------------------------
    # get_entry
    # ------------------------------------------------------------------

    def test_get_entry_returns_content(self, store: KBStore, sample_item: Item) -> None:
        entry = store.store_entry(sample_item)
        full = store.get_entry(entry.entry_id)
        assert full is not None
        assert full["entry_id"] == entry.entry_id
        assert full["title"] == sample_item.title
        assert "content" in full
        assert sample_item.content in full["content"]

    def test_get_entry_nonexistent(self, store: KBStore) -> None:
        full = store.get_entry("does-not-exist")
        assert full is None

    def test_get_entry_parses_body_only(self, store: KBStore, sample_item: Item) -> None:
        """The content field should not include the YAML frontmatter."""
        entry = store.store_entry(sample_item)
        full = store.get_entry(entry.entry_id)
        assert full is not None
        # Content should not contain frontmatter markers
        assert "---" not in full["content"]
        # But should contain the original content
        assert sample_item.content in full["content"]

    # ------------------------------------------------------------------
    # Performance — 100+ entries in <100ms
    # ------------------------------------------------------------------

    def test_list_entries_100_entries_under_100ms(self, store: KBStore) -> None:
        """Performance gate: listing 100+ entries must complete in <100ms."""
        for i in range(110):
            item = Item(
                id=f"perf-item-{i:03d}",
                source_name="pubmed",
                source_type="api",
                source_url=f"https://example.com/perf/{i}",
                title=f"Performance Test Article {i}",
                content=f"Content for article {i} with some filler keywords.",
                collected_at=f"2026-07-{15:02d}T10:00:0{i % 10}Z",
                domain="medical-research",
                topic_tags=["IVF"],
            )
            store.store_entry(item)

        # Warm up — ensure SQLite cache is hot
        store.list_entries("medical-research", limit=50)
        store.list_entries("medical-research", limit=50, offset=50)

        start = time.perf_counter()
        entries = store.list_entries("medical-research", limit=100)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(entries) >= 100
        assert elapsed_ms < 100, f"list_entries took {elapsed_ms:.1f}ms (expected <100ms)"

    # ------------------------------------------------------------------
    # Integration with quality + extraction
    # ------------------------------------------------------------------

    def test_store_with_quality_and_extraction(
        self,
        store: KBStore,
        sample_item: Item,
        sample_extraction: ExtractionResult,
        sample_quality_results,
    ) -> None:
        entry = store.store_entry(
            sample_item, extraction=sample_extraction, quality_results=sample_quality_results
        )
        assert entry.relevance_score == 92.0
        assert entry.dedup_status == "unique"
        assert entry.summary == sample_extraction.tl_dr

        # Verify via get_entry
        full = store.get_entry(entry.entry_id)
        assert full is not None
        assert full["relevance_score"] == 92.0
        assert full["dedup_status"] == "unique"
        assert sample_extraction.tl_dr in full.get("content", "")

    def test_store_without_quality_or_extraction(self, store: KBStore, sample_item: Item) -> None:
        """Should work with minimal inputs."""
        entry = store.store_entry(sample_item)
        assert entry.relevance_score == 0.0  # default
        assert entry.dedup_status == "unique"
        assert entry.summary == ""

        full = store.get_entry(entry.entry_id)
        assert full is not None
        assert full["relevance_score"] == 0.0
        assert full["dedup_status"] == "unique"

    # ------------------------------------------------------------------
    # Multiple topics / domains
    # ------------------------------------------------------------------

    def test_multiple_domains_separate_files(self, store: KBStore) -> None:
        med_item = Item(
            id="med-1",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/med",
            title="Medical article",
            content="Medical content",
            collected_at="2026-07-15T00:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
        )
        ai_item = Item(
            id="ai-1",
            source_name="arxiv",
            source_type="api",
            source_url="https://example.com/ai",
            title="AI article",
            content="AI content",
            collected_at="2026-07-15T00:00:00Z",
            domain="ai-commercial",
            topic_tags=["LLM"],
        )

        med_entry = store.store_entry(med_item)
        ai_entry = store.store_entry(ai_item)

        # Files in separate directories
        assert "medical-research" in med_entry.file_path
        assert "ai-commercial" in ai_entry.file_path

        # Listing scoped per-domain
        assert len(store.list_entries("medical-research")) == 1
        assert len(store.list_entries("ai-commercial")) == 1


# ===================================================================
# import-kb — frontmatter `domain:` collision (Final QA F3 regression)
# ===================================================================


def test_import_kb_markdown_frontmatter_domain_does_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import a Markdown file whose frontmatter includes ``domain:``.

    Regression for the F3 rejection: frontmatter ``domain:`` collided with the
    explicit ``domain`` parameter of ``_build_entry()`` → TypeError. The
    explicit ``--domain`` value must win and the entry must land in 01-Raw.
    """
    from autoinfo.importer import import_kb

    md = (
        "---\n"
        "title: Domain frontmatter import test\n"
        "source_url: https://example.com/domain-frontmatter\n"
        "source_type: web\n"
        "source_platform: example\n"
        "domain: medical-research\n"
        "tags: [import, test]\n"
        "---\n"
        "\n"
        "Body of the imported article.\n"
    )

    monkeypatch.chdir(tmp_path)  # KBStore() writes to ./knowledge

    result = import_kb(domain="medical-research", format="markdown", data=md)

    assert result["entries_imported"] == 1, f"import failed: {result}"
    assert result["errors"] == []

    # Entry landed in 01-Raw under the explicit domain
    raw_dir = tmp_path / "knowledge" / "medical-research" / "01-Raw"
    assert raw_dir.is_dir()
    assert list(raw_dir.rglob("*.md")), "no 01-Raw markdown entry written"
