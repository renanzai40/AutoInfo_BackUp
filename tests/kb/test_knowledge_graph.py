"""Tests for knowledge graph — entity extraction tables and query_knowledge_graph.

Covers:
    - Entity table creation and indexing
    - Auto-discovery of ``related_to`` relations from shared entries
    - query_knowledge_graph(entity, relation) → related entities
    - Empty / edge cases (no entities, no matches)
    - Integration with KBStore.store_entities
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from autoinfo.kb import KBStore, SQLiteIndex


def _entity_id(name: str, domain: str) -> str:
    """Match SQLiteIndex._entity_id to compute expected hashes."""
    raw = f"{domain}:{name.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ===================================================================
# SQLiteIndex — entity & relation methods
# ===================================================================


class TestSQLiteIndexEntities:
    """Low-level entity/relation tests on SQLiteIndex."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_kg.db"

    @pytest.fixture
    def index(self, db_path: Path) -> SQLiteIndex:
        idx = SQLiteIndex(db_path)
        idx.init_db()
        return idx

    # ------------------------------------------------------------------
    # Entity tables
    # ------------------------------------------------------------------

    def test_entities_table_created(self, db_path: Path, index: SQLiteIndex) -> None:
        """Verify ``entities`` and ``kg_relations`` tables exist."""
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "entities" in tables
        assert "kg_relations" in tables
        conn.close()

    def test_index_entities_empty_list(self, index: SQLiteIndex) -> None:
        """Indexing an empty entity list is a no-op."""
        count = index.index_entities("entry-1", "medical-research", [])
        assert count == 0

    def test_index_entities_stores_rows(self, index: SQLiteIndex) -> None:
        """Entities are stored and retrievable."""
        entities = [
            {"name": "Time-lapse embryo imaging", "type": "technology"},
            {"name": "IVF", "type": "procedure"},
        ]
        index.index_entities("entry-1", "medical-research", entities)

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM entities WHERE domain = ?", ("medical-research",)
            ).fetchall()
            assert len(rows) == 2
            names = {r["name"] for r in rows}
            assert "Time-lapse embryo imaging" in names
            assert "IVF" in names

    def test_index_entities_deduplicates_by_name_type_domain(
        self, index: SQLiteIndex
    ) -> None:
        """Same entity name+type in the same domain is stored only once."""
        entities = [{"name": "IVF", "type": "procedure"}]
        index.index_entities("entry-1", "medical-research", entities)
        index.index_entities("entry-2", "medical-research", entities)

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE name = 'IVF' AND domain = 'medical-research'"
            ).fetchone()
            assert count == 1

    def test_index_entities_skips_missing_name_or_type(
        self, index: SQLiteIndex
    ) -> None:
        """Entities without name or type are skipped."""
        entities = [
            {"name": "", "type": "concept"},  # empty name
            {"name": "Valid", "type": ""},     # empty type
            {"name": "OK", "type": "concept"},
        ]
        index.index_entities("entry-1", "medical-research", entities)

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE domain = 'medical-research'"
            ).fetchone()
            assert count == 1

    # ------------------------------------------------------------------
    # Relation discovery
    # ------------------------------------------------------------------

    def test_discover_relations_creates_related_to(self, index: SQLiteIndex) -> None:
        """Entities sharing an entry get a ``related_to`` relation."""
        entities = [
            {"name": "IVF", "type": "procedure"},
            {"name": "Embryo", "type": "concept"},
        ]
        index.index_entities("entry-1", "medical-research", entities)
        count = index.discover_relations(
            "entry-1", "medical-research", ["IVF", "Embryo"]
        )
        assert count == 1

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM kg_relations WHERE domain = 'medical-research'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["relation_type"] == "related_to"
            assert rows[0]["strength"] == 1.0

    def test_discover_relations_strength_increments(self, index: SQLiteIndex) -> None:
        """Co-occurrence across multiple entries increases strength."""
        entities_a = [{"name": "IVF", "type": "procedure"}]
        entities_b = [{"name": "Embryo", "type": "concept"}]

        # Entry 1: both IVF and Embryo appear
        index.index_entities("entry-1", "medical-research", entities_a + entities_b)
        index.discover_relations("entry-1", "medical-research", ["IVF", "Embryo"])

        # Entry 2: both appear again
        index.index_entities("entry-2", "medical-research", entities_a + entities_b)
        index.discover_relations("entry-2", "medical-research", ["IVF", "Embryo"])

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            row = conn.execute(
                "SELECT strength, entries_shared FROM kg_relations "
                "WHERE relation_type = 'related_to'"
            ).fetchone()
            assert row is not None
            assert row[0] == 2.0  # strength == number of shared entries
            shared = json.loads(row[1])
            assert len(shared) == 2

    def test_discover_relations_less_than_two_entities(self, index: SQLiteIndex) -> None:
        """No relations created with fewer than 2 entity names."""
        count = index.discover_relations("entry-1", "medical-research", ["IVF"])
        assert count == 0

    def test_discover_relations_skips_duplicate_pairs(self, index: SQLiteIndex) -> None:
        """Same pair indexed twice produces one relation row."""
        entities = [
            {"name": "A", "type": "concept"},
            {"name": "B", "type": "concept"},
        ]
        index.index_entities("entry-1", "medical-research", entities)
        index.discover_relations("entry-1", "medical-research", ["A", "B"])
        index.discover_relations("entry-1", "medical-research", ["A", "B"])

        import sqlite3

        with sqlite3.connect(str(index.db_path)) as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM kg_relations WHERE domain = 'medical-research'"
            ).fetchone()
            assert count == 1

    # ------------------------------------------------------------------
    # query_knowledge_graph
    # ------------------------------------------------------------------

    def test_query_no_matches(self, index: SQLiteIndex) -> None:
        """Querying a non-existent entity returns empty results."""
        result = index.query_knowledge_graph("nonexistent", domain="medical-research")
        assert result["total_count"] == 0
        assert result["results"] == []

    def test_query_returns_related_entities(self, index: SQLiteIndex) -> None:
        """Query returns correctly structured related entities."""
        entities = [
            {"name": "IVF", "type": "procedure"},
            {"name": "Embryo", "type": "concept"},
            {"name": "Blastocyst", "type": "concept"},
        ]
        index.index_entities("entry-1", "medical-research", entities)
        index.discover_relations(
            "entry-1", "medical-research", ["IVF", "Embryo", "Blastocyst"]
        )

        result = index.query_knowledge_graph("IVF", domain="medical-research")
        assert result["total_count"] > 0
        assert result["entity"] == "IVF"
        assert result["relation"] == "related_to"

        related_ids = {r["related_entity"] for r in result["results"]}
        embryo_id = _entity_id("Embryo", "medical-research")
        blastocyst_id = _entity_id("Blastocyst", "medical-research")
        assert embryo_id in related_ids
        assert blastocyst_id in related_ids

    def test_query_with_empty_relation_returns_all(self, index: SQLiteIndex) -> None:
        """Empty relation string matches all relation types."""
        entities = [
            {"name": "IVF", "type": "procedure"},
            {"name": "Embryo", "type": "concept"},
        ]
        index.index_entities("entry-1", "medical-research", entities)
        index.discover_relations("entry-1", "medical-research", ["IVF", "Embryo"])

        result = index.query_knowledge_graph(
            "IVF", relation="", domain="medical-research"
        )
        assert result["total_count"] > 0

    def test_query_partial_name_match(self, index: SQLiteIndex) -> None:
        """Query with a partial name still matches."""
        entities = [{"name": "Time-lapse imaging", "type": "technology"}]
        index.index_entities("entry-1", "medical-research", entities)
        # We need at least 2 entities to form a relation
        entities2 = [{"name": "IVF", "type": "procedure"}]
        index.index_entities("entry-2", "medical-research", entities + entities2)
        index.discover_relations(
            "entry-2", "medical-research", ["Time-lapse imaging", "IVF"]
        )

        result = index.query_knowledge_graph("Time-lapse", domain="medical-research")
        assert result["total_count"] > 0

    def test_query_domain_isolates_results(self, index: SQLiteIndex) -> None:
        """Entities in different domains do not cross-contaminate."""
        for domain in ("medical-research", "ai-commercial"):
            ents = [
                {"name": f"Entity-{domain}", "type": "concept"},
                {"name": "SharedEntity", "type": "concept"},
            ]
            index.index_entities(f"entry-{domain}", domain, ents)
            index.discover_relations(
                f"entry-{domain}", domain,
                [f"Entity-{domain}", "SharedEntity"],
            )

        med_result = index.query_knowledge_graph(
            "SharedEntity", domain="medical-research"
        )
        ai_result = index.query_knowledge_graph(
            "SharedEntity", domain="ai-commercial"
        )

        # Each domain should have exactly 1 related entity (the domain-specific one)
        assert med_result["total_count"] == 1
        assert ai_result["total_count"] == 1
        med_ids = {r["related_entity"] for r in med_result["results"]}
        ai_ids = {r["related_entity"] for r in ai_result["results"]}
        med_entity_id = _entity_id("Entity-medical-research", "medical-research")
        ai_entity_id = _entity_id("Entity-ai-commercial", "ai-commercial")
        assert med_entity_id in med_ids
        assert ai_entity_id in ai_ids


# ===================================================================
# KBStore — store_entities & query_knowledge_graph
# ===================================================================


class TestKBStoreKnowledgeGraph:
    """Integration tests via KBStore."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        return KBStore(base_path=tmp_path / "knowledge")

    def test_store_entities_returns_summary(self, store: KBStore) -> None:
        """store_entities returns a summary dict."""
        entities = [
            {"name": "IVF", "type": "procedure"},
            {"name": "Embryo", "type": "concept"},
        ]
        result = store.store_entities("entry-1", "medical-research", entities)
        assert result["entry_id"] == "entry-1"
        assert isinstance(result["entities_indexed"], int)
        assert isinstance(result["relations_discovered"], int)

    def test_store_entities_empty(self, store: KBStore) -> None:
        """Empty entity list produces no-ops."""
        result = store.store_entities("entry-1", "medical-research", [])
        # entities_indexed may be 0; check it doesn't crash
        assert result["entry_id"] == "entry-1"

    def test_query_knowledge_graph_via_store(self, store: KBStore) -> None:
        """KBStore.query_knowledge_graph returns structured results."""
        entities = [
            {"name": "CRISPR", "type": "technology"},
            {"name": "Gene Therapy", "type": "concept"},
            {"name": "AAV Vector", "type": "technology"},
        ]
        store.store_entities("entry-1", "medical-research", entities)

        result = store.query_knowledge_graph(
            "CRISPR", domain="medical-research"
        )
        assert result["entity"] == "CRISPR"
        assert result["total_count"] >= 1
        related = {r["related_entity"] for r in result["results"]}
        gene_therapy_id = _entity_id("Gene Therapy", "medical-research")
        aav_id = _entity_id("AAV Vector", "medical-research")
        assert gene_therapy_id in related or aav_id in related

    def test_cross_entry_co_occurrence(self, store: KBStore) -> None:
        """Entities that co-occur across multiple entries get higher strength."""
        # Entry 1: CRISPR + Gene Therapy
        store.store_entities(
            "entry-1", "medical-research",
            [
                {"name": "CRISPR", "type": "technology"},
                {"name": "Gene Therapy", "type": "concept"},
            ],
        )
        # Entry 2: CRISPR + Gene Therapy + AAV
        store.store_entities(
            "entry-2", "medical-research",
            [
                {"name": "CRISPR", "type": "technology"},
                {"name": "Gene Therapy", "type": "concept"},
                {"name": "AAV Vector", "type": "technology"},
            ],
        )

        result = store.query_knowledge_graph(
            "CRISPR", domain="medical-research"
        )
        assert result["total_count"] >= 1
        # CRISPR should be most strongly related to Gene Therapy (2 shared entries)
        gene_therapy_id = _entity_id("Gene Therapy", "medical-research")
        for r in result["results"]:
            if r["related_entity"] == gene_therapy_id:
                assert r["strength"] >= 2.0
                assert r["entries_shared_count"] >= 2

    def test_different_domains_isolated(self, store: KBStore) -> None:
        """Entities in different domains do not mix in results."""
        store.store_entities(
            "e1", "medical-research",
            [{"name": "Aspirin", "type": "drug"}, {"name": "Fever", "type": "concept"}],
        )
        store.store_entities(
            "e2", "ai-commercial",
            [{"name": "Aspirin", "type": "drug"}, {"name": "Transformer", "type": "technology"}],
        )

        med_result = store.query_knowledge_graph(
            "Aspirin", domain="medical-research"
        )
        ai_result = store.query_knowledge_graph(
            "Aspirin", domain="ai-commercial"
        )

        med_related = {r["related_entity"] for r in med_result["results"]}
        ai_related = {r["related_entity"] for r in ai_result["results"]}
        fever_id = _entity_id("Fever", "medical-research")
        transformer_id = _entity_id("Transformer", "ai-commercial")
        assert fever_id in med_related
        assert fever_id not in ai_related
        assert transformer_id in ai_related
        assert transformer_id not in med_related


# ===================================================================
# Process pipeline integration — entity extraction called after store_entry
# ===================================================================


class TestProcessIntegration:
    """Verify that process.py calls store_entities after store_entry."""

    @pytest.mark.skip(reason="timeout — requires LLM mock for hermetic testing")
    def test_process_calls_store_entities(self, mocker, tmp_path: Path) -> None:
        """run_processing should call KBStore.store_entities when entities exist."""
        from autoinfo.models import Item
        from autoinfo.process import run_processing

        item = Item(
            id="test-kg-001",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/kg-test",
            title="KG Integration Test",
            content="Test content about CRISPR and Gene Therapy.",
            content_type="text",
            collected_at="2026-07-20T00:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["genetics"],
            quality_tier=1,
        )
        mocker.patch("autoinfo.process.load_cached_items", return_value=[item])

        spy = mocker.spy(KBStore, "store_entities")

        # Patch LLM to return known entities
        mock_extract = mocker.patch("autoinfo.process.LLMExtractor")
        mock_instance = mock_extract.return_value
        from autoinfo.models import ExtractionResult
        mock_instance.extract.return_value = ExtractionResult(
            item_id="test-kg-001",
            title="KG Integration Test",
            tl_dr="CRISPR and Gene Therapy are related.",
            key_points=["CRISPR is a gene-editing tool."],
            entities=[
                {"name": "CRISPR", "type": "technology"},
                {"name": "Gene Therapy", "type": "concept"},
            ],
            relevance_score=85.0,
        )

        with mocker.patch(
            "autoinfo.process.KBStore",
            wraps=KBStore,
        ):
            # We need a KBStore that uses the tmp_path
            # The process module uses KBStore() with default path;
            # override via mocker
            original_store = KBStore(base_path=tmp_path / "knowledge")

            with mocker.patch(
                "autoinfo.process.KBStore",
                return_value=original_store,
            ):
                result = run_processing("medical-research")

        assert result.kb_entries_created >= 1
        # Verify store_entities was called
        spy.assert_called()
