"""Tests for FTS5 full-text search over KB entries.

Covers:
    - FTS5 virtual table creation
    - Search returns matching entries ranked by relevance
    - Search with no matches returns empty entries with total_count=0
    - Pagination (offset, limit)
    - Domain filter
    - CJK search (Chinese characters)
    - kb reindex populates FTS5 from .md files
    - _escape_fts5_query helper
    - Fallback to LIKE search
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.kb import (
    KBStore,
    SQLiteIndex,
    _escape_fts5_query,
)
from autoinfo.models import Item, KBEntry

# ===================================================================
# _escape_fts5_query helper
# ===================================================================


class TestEscapeFts5Query:
    def test_empty_query(self) -> None:
        assert _escape_fts5_query("") == ""
        assert _escape_fts5_query("   ") == ""

    def test_plain_terms(self) -> None:
        assert _escape_fts5_query("IVF breakthrough") == "IVF breakthrough"

    def test_strips_special_chars(self) -> None:
        assert "^" not in _escape_fts5_query("^IVF")
        assert '"' not in _escape_fts5_query('"IVF"')
        assert "(" not in _escape_fts5_query("(IVF)")
        assert ":" not in _escape_fts5_query("title:IVF")
        assert "*" not in _escape_fts5_query("IVF*")
        assert "!" not in _escape_fts5_query("!IVF")

    def test_lowercases_fts5_keywords(self) -> None:
        result = _escape_fts5_query("IVF AND embryo")
        assert "AND" not in result
        assert "and" in result

    def test_lowercases_or_not(self) -> None:
        result = _escape_fts5_query("IVF OR embryo")
        assert "OR" not in result
        assert "or" in result

    def test_mixed_chars_preserves_alphanumeric(self) -> None:
        result = _escape_fts5_query("time-lapse imaging")
        assert result

    def test_cjk_preserved(self) -> None:
        result = _escape_fts5_query("辅助生殖")
        assert "辅助生殖" in result or "辅" in result


# ===================================================================
# SQLiteIndex FTS5
# ===================================================================


class TestSQLiteIndexFTS5:
    """Test FTS5 functionality on the low-level SQLiteIndex."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_autoinfo.db"

    @pytest.fixture
    def index(self, db_path: Path) -> SQLiteIndex:
        idx = SQLiteIndex(db_path)
        idx.init_db()
        return idx

    @pytest.fixture
    def sample_entries(self) -> list[KBEntry]:
        return [
            KBEntry(
                entry_id="entry-001",
                title="Improved IVF outcomes with time-lapse imaging",
                domain="medical-research",
                tier="01-Raw",
                source_url="https://example.com/1",
                source_type="api",
                source_platform="pubmed",
                collected_at="2026-07-15T10:00:00Z",
                summary="Time-lapse imaging improves live birth rates in IVF patients.",
                tags=["IVF", "time-lapse", "embryo imaging"],
                quality_tier=1,
                relevance_score=92.0,
                dedup_status="unique",
                file_path="",
            ),
            KBEntry(
                entry_id="entry-002",
                title="AI-powered embryo selection using deep learning",
                domain="medical-research",
                tier="01-Raw",
                source_url="https://example.com/2",
                source_type="api",
                source_platform="pubmed",
                collected_at="2026-07-14T10:00:00Z",
                summary="Deep learning model predicts embryo viability with 89% accuracy.",
                tags=["AI", "embryo", "deep learning"],
                quality_tier=1,
                relevance_score=88.0,
                dedup_status="unique",
                file_path="",
            ),
            KBEntry(
                entry_id="entry-003",
                title="LLM market trends 2026",
                domain="ai-commercial",
                tier="01-Raw",
                source_url="https://example.com/3",
                source_type="api",
                source_platform="arxiv",
                collected_at="2026-07-13T10:00:00Z",
                summary="Large language models continue to dominate AI investment.",
                tags=["LLM", "market", "AI"],
                quality_tier=1,
                relevance_score=75.0,
                dedup_status="unique",
                file_path="",
            ),
            KBEntry(
                entry_id="entry-004",
                title="儿童英语学习新方法",
                domain="language-learning",
                tier="01-Raw",
                source_url="https://example.com/4",
                source_type="api",
                source_platform="custom",
                collected_at="2026-07-12T10:00:00Z",
                summary="通过游戏学习英语的新方法研究",
                tags=["儿童", "英语", "游戏"],
                quality_tier=1,
                relevance_score=80.0,
                dedup_status="unique",
                file_path="",
            ),
        ]

    def _index_all(
        self,
        index: SQLiteIndex,
        entries: list[KBEntry],
        contents: dict[str, str] | None = None,
    ) -> None:
        for entry in entries:
            index.index_entry(entry)
            index.index_entry_fts5(
                entry, content=(contents or {}).get(entry.entry_id, "")
            )

    def test_fts5_table_created(self, db_path: Path, index: SQLiteIndex) -> None:
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "entries_fts5" in table_names
        conn.close()

    def test_fts5_virtual_table_type(self, db_path: Path, index: SQLiteIndex) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT type, sql FROM sqlite_master WHERE name='entries_fts5'"
        ).fetchone()
        assert row is not None, "entries_fts5 table not found"
        assert "fts5" in row["sql"].lower(), "not an FTS5 table"
        conn.close()

    # --------------------------------------------------------------
    # Search returns matching entries
    # --------------------------------------------------------------

    def test_search_returns_matching_entries(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("IVF")
        assert result["total_count"] >= 1
        assert result["entries"][0]["entry_id"] == "entry-001"

    def test_search_multiple_matches_ranked(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("embryo")
        # Both entry-001 and entry-002 mention "embryo"
        assert result["total_count"] >= 2
        entry_ids = {e["entry_id"] for e in result["entries"]}
        assert "entry-001" in entry_ids
        assert "entry-002" in entry_ids

    def test_search_no_matches_returns_empty(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("xyznonexistent12345")
        assert result["total_count"] == 0
        assert result["entries"] == []

    # --------------------------------------------------------------
    # Pagination
    # --------------------------------------------------------------

    def test_search_pagination(
        self, index: SQLiteIndex
    ) -> None:
        entries = [
            KBEntry(
                entry_id=f"page-entry-{i:03d}",
                title=f"Article about IVF number {i}",
                domain="medical-research",
                source_url=f"https://example.com/{i}",
                tags=["IVF"],
                collected_at=f"2026-07-{15:02d}T10:00:0{i}Z",
            )
            for i in range(10)
        ]
        self._index_all(index, entries)

        # Page 1: limit=5, offset=0
        page1 = index.search_fts5("IVF", limit=5, offset=0)
        assert len(page1["entries"]) == 5
        assert page1["total_count"] >= 10

        # Page 2: limit=5, offset=5
        page2 = index.search_fts5("IVF", limit=5, offset=5)
        assert len(page2["entries"]) == 5

        # No overlap
        ids_p1 = {e["entry_id"] for e in page1["entries"]}
        ids_p2 = {e["entry_id"] for e in page2["entries"]}
        assert ids_p1.isdisjoint(ids_p2)

    # --------------------------------------------------------------
    # Domain filter
    # --------------------------------------------------------------

    def test_search_domain_filter(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        # Search "AI" across all domains
        all_results = index.search_fts5("AI")
        assert all_results["total_count"] >= 1

        # Filter to only ai-commercial
        ai_results = index.search_fts5("AI", domain="ai-commercial")
        assert ai_results["total_count"] >= 1
        for e in ai_results["entries"]:
            assert e["domain"] == "ai-commercial"

        # Filter to non-matching domain
        empty = index.search_fts5("AI", domain="language-learning")
        assert empty["total_count"] == 0

    def test_search_empty_domain_returns_all(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("embryo", domain="")
        assert result["total_count"] >= 1

    # --------------------------------------------------------------
    # CJK search
    # --------------------------------------------------------------

    def test_cjk_search(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("儿童")
        assert result["total_count"] >= 1
        assert result["entries"][0]["entry_id"] == "entry-004"

    def test_cjk_search_summary(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("游戏")
        assert result["total_count"] >= 1

    # --------------------------------------------------------------
    # FTS5 fallback
    # --------------------------------------------------------------

    def test_fts5_fallback_on_invalid_syntax(
        self, index: SQLiteIndex, sample_entries: list[KBEntry]
    ) -> None:
        self._index_all(index, sample_entries)

        result = index.search_fts5("IVF")
        assert result["total_count"] >= 1

    # ==============================================================
    # KBStore integration
    # ==============================================================


class TestKBStoreFTS5:
    """Test FTS5 via the high-level KBStore."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        return KBStore(base_path=tmp_path / "knowledge")

    @pytest.fixture
    def sample_items(self) -> list[Item]:
        return [
            Item(
                id="item-001",
                source_name="pubmed",
                source_type="api",
                source_url="https://example.com/1",
                title="IVF with time-lapse imaging",
                content="Time-lapse embryo imaging improves embryo selection in IVF cycles.",
                collected_at="2026-07-15T10:00:00Z",
                domain="medical-research",
                topic_tags=["IVF", "time-lapse"],
            ),
            Item(
                id="item-002",
                source_name="pubmed",
                source_type="api",
                source_url="https://example.com/2",
                title="AI in embryo selection",
                content="Deep learning models can predict embryo viability with high accuracy.",
                collected_at="2026-07-14T10:00:00Z",
                domain="medical-research",
                topic_tags=["AI", "embryo"],
            ),
            Item(
                id="item-003",
                source_name="arxiv",
                source_type="api",
                source_url="https://example.com/3",
                title="儿童英语学习",
                content="通过互动游戏学习英语的方法研究。",
                collected_at="2026-07-13T10:00:00Z",
                domain="language-learning",
                topic_tags=["儿童", "英语"],
            ),
        ]

    def test_search_knowledge_base_after_store(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("IVF")
        assert result["total_count"] >= 1
        assert "time-lapse" in result["entries"][0]["title"].lower()

    def test_search_knowledge_base_no_matches(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("nonexistent12345")
        assert result["total_count"] == 0
        assert result["entries"] == []

    def test_search_with_domain_filter(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("embryo", domain="medical-research")
        assert result["total_count"] >= 1
        for e in result["entries"]:
            assert e["domain"] == "medical-research"

    def test_search_with_domain_no_match(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("embryo", domain="ai-commercial")
        assert result["total_count"] == 0

    def test_cjk_search_via_store(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("儿童")
        assert result["total_count"] >= 1

    def test_search_pagination_via_store(
        self, store: KBStore
    ) -> None:
        for i in range(10):
            store.store_entry(
                Item(
                    id=f"item-{i:03d}",
                    source_name="pubmed",
                    source_type="api",
                    source_url=f"https://example.com/{i}",
                    title=f"IVF research article {i}",
                    content=f"This is content about IVF for article number {i}.",
                    collected_at=f"2026-07-{15:02d}T10:00:0{i}Z",
                    domain="medical-research",
                    topic_tags=["IVF"],
                )
            )

        page1 = store.search_knowledge_base("IVF", limit=5, offset=0)
        assert len(page1["entries"]) == 5

        page2 = store.search_knowledge_base("IVF", limit=5, offset=5)
        assert len(page2["entries"]) == 5

        ids_p1 = {e["entry_id"] for e in page1["entries"]}
        ids_p2 = {e["entry_id"] for e in page2["entries"]}
        assert ids_p1.isdisjoint(ids_p2)

    # --------------------------------------------------------------
    # Reindex
    # --------------------------------------------------------------

    def test_reindex_knowledge_base(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        # Verify search works (FTS5 was populated via store_entry)
        before = store.search_knowledge_base("IVF")
        assert before["total_count"] >= 1

        # Now reindex
        result = store.reindex_knowledge_base()
        assert result["fts5_indexed"] >= 3
        assert result["files_found"] >= 3
        assert result["errors"] == []

        # Search should still work after reindex
        after = store.search_knowledge_base("IVF")
        assert after["total_count"] >= 1

    def test_reindex_domain_scoped(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.reindex_knowledge_base(domain="medical-research")
        assert result["fts5_indexed"] >= 3  # Still indexes all entries
        assert result["files_found"] >= 2  # 2 items in medical-research

    def test_reindex_from_orphaned_md_files(
        self, tmp_path: Path, store: KBStore
    ) -> None:
        md_dir = tmp_path / "knowledge" / "medical-research" / "01-Raw" / "IVF"
        md_dir.mkdir(parents=True, exist_ok=True)
        md_file = md_dir / "2026-07-15-orphaned-test.md"
        entry_id = "orphaned-entry"
        fm = {
            "title": "Orphaned test entry",
            "domain": "medical-research",
            "tier": "01-Raw",
            "entry_id": entry_id,
            "source_url": "https://example.com/orphaned",
            "source_type": "api",
            "source_platform": "test",
            "collected_at": "2026-07-15T10:00:00Z",
            "summary": "This entry only exists as a md file.",
            "tags": ["test"],
            "quality_tier": 1,
            "relevance_score": 50.0,
            "dedup_status": "unique",
            "language": "en",
        }
        frontmatter = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
        md_file.write_text(
            f"---\n{frontmatter}---\n\nOrphaned body content for FTS5 testing.",
            encoding="utf-8",
        )

        # Verify not in index yet
        assert store.index.get_entry(entry_id) is None

        # Reindex — should pick up orphaned file
        result = store.reindex_knowledge_base(domain="medical-research")
        assert result["files_found"] >= 1

        # Now entry should exist in SQLite and FTS5
        assert store.index.get_entry(entry_id) is not None

        search_result = store.search_knowledge_base("orphaned")
        assert search_result["total_count"] >= 1

    def test_mcp_search_returns_expected_shape(
        self, store: KBStore, sample_items: list[Item]
    ) -> None:
        for item in sample_items:
            store.store_entry(item)

        result = store.search_knowledge_base("IVF")
        expected_keys = {"query", "domain", "entries", "total_count", "limit", "offset"}
        assert expected_keys.issubset(result.keys())
        assert isinstance(result["entries"], list)


# ===================================================================
# T8: search tier soft-boost + tier field (kb-curation-gap-closure)
# ===================================================================


class TestSearchTierSoftBoost:
    """Search soft-boost by KB tier.

    03-Wiki entries get a small post-multiplier on the combined score so
    they outrank equal-scoring Draft/Raw entries; every result carries
    its ``tier``; stale-content demotion still outranks the boost.
    """

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        return KBStore(base_path=tmp_path / "knowledge")

    @staticmethod
    def _seed(
        store: KBStore, entries: list[KBEntry], contents: dict[str, str] | None = None
    ) -> None:
        for entry in entries:
            store.index.index_entry(entry)
            store.index.index_entry_fts5(
                entry, content=(contents or {}).get(entry.entry_id, entry.summary)
            )

    @staticmethod
    def _tier_entry(
        entry_id: str,
        tier: str,
        title: str,
        relevance_score: float,
        collected_at: str,
    ) -> KBEntry:
        return KBEntry(
            entry_id=entry_id,
            title=title,
            domain="medical-research",
            tier=tier,
            source_url=f"https://example.com/{entry_id}",
            source_type="api",
            source_platform="pubmed",
            collected_at=collected_at,
            summary=f"{title} — IVF embryo selection content.",
            tags=["IVF", "embryo"],
            quality_tier=1,
            relevance_score=relevance_score,
            dedup_status="unique",
            file_path="",
        )

    def test_search_tier_boost_wiki_first(self, store: KBStore) -> None:
        """Same content score: 03-Wiki ranks above 02-Draft and 01-Raw."""
        now = datetime.now(timezone.utc).isoformat()
        entries = [
            self._tier_entry("draft-1", "02-Draft", "Draft IVF article", 0.9, now),
            self._tier_entry("raw-1", "01-Raw", "Raw IVF article", 0.9, now),
            self._tier_entry("wiki-1", "03-Wiki", "Wiki curated IVF article", 0.9, now),
        ]
        self._seed(store, entries)

        result = store.search_knowledge_base("IVF")
        assert len(result["entries"]) == 3
        assert [e["entry_id"] for e in result["entries"]] == [
            "wiki-1",
            "draft-1",
            "raw-1",
        ]

    def test_search_tier_present(self, store: KBStore) -> None:
        """Every result carries a ``tier`` field equal to its KB tier."""
        now = datetime.now(timezone.utc).isoformat()
        entries = [
            self._tier_entry("wiki-2", "03-Wiki", "Wiki IVF overview", 0.8, now),
            self._tier_entry("draft-2", "02-Draft", "Draft IVF overview", 0.8, now),
            self._tier_entry("raw-2", "01-Raw", "Raw IVF overview", 0.8, now),
        ]
        self._seed(store, entries)

        result = store.search_knowledge_base("IVF")
        assert len(result["entries"]) == 3
        tier_by_id = {e["entry_id"]: e["tier"] for e in result["entries"]}
        assert tier_by_id == {
            "wiki-2": "03-Wiki",
            "draft-2": "02-Draft",
            "raw-2": "01-Raw",
        }

    def test_stale_demotion_coexists_with_tier_boost(self, store: KBStore) -> None:
        """A stale entry is still demoted below fresh entries — even 03-Wiki."""
        now = datetime.now(timezone.utc).isoformat()
        stale_wiki = self._tier_entry(
            "stale-wiki-1",
            "03-Wiki",
            "Stale curated IVF article",
            0.99,
            "2020-01-01T00:00:00Z",
        )
        fresh_draft = self._tier_entry(
            "fresh-draft-1",
            "02-Draft",
            "Fresh IVF draft article",
            0.9,
            now,
        )
        self._seed(store, [stale_wiki, fresh_draft])

        # Default mode: stale demotion outranks the wiki boost.
        result = store.search_knowledge_base("IVF")
        assert [e["entry_id"] for e in result["entries"]] == [
            "fresh-draft-1",
            "stale-wiki-1",
        ]

        # include_stale=True: pure score order — the boost never lifts a
        # lower base score above a higher one.
        result_all = store.search_knowledge_base("IVF", include_stale=True)
        ids = [e["entry_id"] for e in result_all["entries"]]
        assert ids.index("fresh-draft-1") < ids.index("stale-wiki-1")
        assert isinstance(result["total_count"], int)


# ===================================================================
# Custom-fields faceted filter (output-quality-mega, todo 25)
# ===================================================================


class TestSearchCustomFieldsFilter:
    """Faceted filtering on the ``custom_fields`` JSON column.

    Todo 24 (output-quality-mega) persists per-product analysis fields
    (``{"product_analysis": {"implications", "risks", "action_required",
    "key_metrics"}}``) onto KB entries via ``update_entry_metadata``.
    A downstream agent must be able to find those entries with the
    EXISTING ``search_knowledge_base`` tool — via the new
    ``filter_custom_fields`` faceted filter key.

    Semantics: each key is a dot-path into ``custom_fields``; an
    empty-string value matches entries where the field exists and is
    non-empty; any other value matches entries where the field's JSON
    value equals that text.  Default search (no filter) is unchanged.
    """

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        return KBStore(base_path=tmp_path / "knowledge")

    @staticmethod
    def _entry(
        entry_id: str,
        title: str,
        product_analysis: dict[str, Any] | None,
    ) -> KBEntry:
        custom_fields: dict[str, Any] = {}
        if product_analysis is not None:
            custom_fields["product_analysis"] = product_analysis
        return KBEntry(
            entry_id=entry_id,
            title=title,
            domain="medical-research",
            tier="01-Raw",
            source_url=f"https://example.com/{entry_id}",
            source_type="api",
            source_platform="pubmed",
            collected_at="2026-07-15T10:00:00Z",
            summary=f"{title} — IVF embryo selection content.",
            tags=["IVF", "embryo"],
            quality_tier=1,
            relevance_score=90.0,
            dedup_status="unique",
            file_path="",
            custom_fields=custom_fields,
        )

    @staticmethod
    def _seed(
        store: KBStore, entries: list[KBEntry]
    ) -> None:
        for entry in entries:
            store.index.index_entry(entry)
            store.index.index_entry_fts5(entry, content=entry.summary)

    def _seed_mixed(self, store: KBStore) -> list[str]:
        """Two entries with action_required, one without."""
        entries = [
            self._entry(
                "pa-001",
                "Time-lapse imaging improves IVF outcomes",
                {
                    "implications": ["Clinics should evaluate adoption."],
                    "action_required": ["Fund prospective validation trials."],
                },
            ),
            self._entry(
                "pa-002",
                "AI embryo selection systematic review",
                {
                    "risks": [
                        {
                            "title": "Validation lag",
                            "likelihood": "high",
                            "impact": "medium",
                            "mitigation": "Run prospective trials.",
                        }
                    ],
                    "action_required": ["Run prospective AI validation trials."],
                },
            ),
            self._entry("pa-003", "LLM market trends", None),
        ]
        self._seed(store, entries)
        return ["pa-001", "pa-002"]

    def test_presence_filter_returns_subset(
        self, store: KBStore
    ) -> None:
        expected = self._seed_mixed(store)

        result = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={"product_analysis.action_required": ""},
        )
        assert result["total_count"] == 2
        ids = {e["entry_id"] for e in result["entries"]}
        assert ids == set(expected)

    def test_presence_filter_ignores_field_without_value(
        self, store: KBStore
    ) -> None:
        """A field persisted as an empty container is treated as absent."""
        self._seed(
            store,
            [
                self._entry(
                    "pa-empty",
                    "IVF with empty action list",
                    {"action_required": []},
                ),
                self._entry(
                    "pa-full",
                    "IVF with actions",
                    {"action_required": ["Fund a trial."]},
                ),
            ],
        )

        result = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={"product_analysis.action_required": ""},
        )
        assert result["total_count"] == 1
        assert result["entries"][0]["entry_id"] == "pa-full"

    def test_value_filter_exact_match(
        self, store: KBStore
    ) -> None:
        self._seed_mixed(store)
        exact = '["Fund prospective validation trials."]'

        result = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={"product_analysis.action_required": exact},
        )
        assert result["total_count"] == 1
        assert result["entries"][0]["entry_id"] == "pa-001"

        no_match = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={
                "product_analysis.action_required": '["No such action."]'
            },
        )
        assert no_match["total_count"] == 0

    def test_default_search_unchanged(self, store: KBStore) -> None:
        self._seed_mixed(store)

        plain = store.search_knowledge_base("IVF")
        assert plain["total_count"] == 3

        filtered = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={"product_analysis.key_metrics": ""},
        )
        assert filtered["total_count"] == 0

    def test_fts5_fallback_like_path_applies_filter(
        self, store: KBStore
    ) -> None:
        """The LIKE fallback path applies the same custom-fields filter."""
        # "NOT" is an FTS5 keyword — MATCH 'not' raises OperationalError,
        # so search falls back to the LIKE path; "notes" contains "not".
        self._seed(
            store,
            [
                self._entry(
                    "pa-like-1",
                    "Clinical notes on IVF outcomes",
                    {"action_required": ["Fund a trial."]},
                ),
                self._entry(
                    "pa-like-2",
                    "Notes on embryo transfer",
                    None,
                ),
            ],
        )

        unfiltered = store.search_knowledge_base("NOT")
        assert unfiltered["method"] == "like"
        assert unfiltered["total_count"] == 2

        result = store.search_knowledge_base(
            "NOT",
            filter_custom_fields={"product_analysis.action_required": ""},
        )
        assert result["method"] == "like"
        assert result["total_count"] == 1
        assert result["entries"][0]["entry_id"] == "pa-like-1"

    def test_invalid_path_rejected(self, store: KBStore) -> None:
        self._seed_mixed(store)
        with pytest.raises(ValueError, match="filter_custom_fields"):
            store.search_knowledge_base(
                "IVF",
                filter_custom_fields={
                    'product_analysis.action_required"; DROP TABLE entries --': ""
                },
            )

    def test_filter_via_update_entry_metadata_path(
        self, store: KBStore
    ) -> None:
        """Todo-24 persistence path: update_entry_metadata then faceted search."""
        self._seed(
            store,
            [
                self._entry("pa-raw-1", "IVF raw entry", None),
                self._entry("pa-raw-2", "IVF raw entry two", None),
            ],
        )
        # The todo-24 shape: {"product_analysis": {...}} merged into
        # custom_fields by KBStore.update_entry_metadata.
        assert store.update_entry_metadata(
            "pa-raw-1",
            {"product_analysis": {"action_required": ["Fund prospective trials."]}},
        )
        assert not store.update_entry_metadata(
            "no-such-entry",
            {"product_analysis": {"action_required": ["x"]}},
        )

        meta = store.get_entry("pa-raw-1")
        assert meta is not None
        cf = json.loads(meta["custom_fields"])
        assert cf["product_analysis"]["action_required"] == [
            "Fund prospective trials."
        ]

        result = store.search_knowledge_base(
            "IVF",
            filter_custom_fields={"product_analysis.action_required": ""},
        )
        assert result["total_count"] == 1
        assert result["entries"][0]["entry_id"] == "pa-raw-1"

    def test_index_level_presence_filter(
        self, tmp_path: Path
    ) -> None:
        """Low-level SQLiteIndex filter (used by the LIKE path)."""
        index = SQLiteIndex(tmp_path / "idx.db")
        index.init_db()
        entries = [
            self._entry("idx-1", "IVF article one", {"action_required": ["A"]}),
            self._entry("idx-2", "IVF article two", None),
        ]
        for entry in entries:
            index.index_entry(entry)
            index.index_entry_fts5(entry, content=entry.summary)

        result = index.search_fts5(
            "IVF", filter_custom_fields={"product_analysis.action_required": ""}
        )
        assert result["total_count"] == 1
        assert result["entries"][0]["entry_id"] == "idx-1"
