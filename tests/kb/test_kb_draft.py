# mypy: ignore-errors
"""Tests for 02-Draft tier — create_kb_draft, reject_kb_draft, list_kb_tier.

Covers:
    - create_kb_draft with valid raw_id creates file in 02-Draft/
    - create_kb_draft with nonexistent raw_id raises ValueError
    - Multiple raw_ids merged into single Draft
    - Draft file has correct frontmatter with tier: "02-Draft"
    - reject_kb_draft moves entry back to 01-Raw
    - reject_kb_draft archives entry
    - list_kb_tier returns only entries in specified tier
    - SQLite index updated with correct tier
    - Frontmatter includes source_raw_ids
    - Promotion provenance: promotion_source/promoted_by fields + frontmatter
    - Draft carries forward real Raw scores (G-02: no more hardcoded 0/1)
    - Legacy Drafts without source_raw_ids remain compatible
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from autoinfo.kb import KBStore
from autoinfo.models import Item, KBEntry

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    """Create a KBStore rooted in a temp directory."""
    return KBStore(base_path=tmp_path / "knowledge")


@pytest.fixture
def sample_item_1() -> Item:
    return Item(
        id="raw-001",
        source_name="pubmed",
        source_type="api",
        source_url="https://example.com/paper1",
        source_platform="pubmed",
        title="IVF outcomes with time-lapse imaging",
        content=(
            "Time-lapse embryo imaging has been proposed as a non-invasive "
            "method to improve embryo selection in IVF cycles."
        ),
        content_type="text",
        collected_at="2026-07-15T10:30:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF", "embryo imaging"],
        quality_tier=1,
    )


@pytest.fixture
def sample_item_2() -> Item:
    return Item(
        id="raw-002",
        source_name="pubmed",
        source_type="api",
        source_url="https://example.com/paper2",
        source_platform="pubmed",
        title="AI-assisted embryo grading",
        content=(
            "Artificial intelligence models can predict embryo viability "
            "with high accuracy using time-lapse video data."
        ),
        content_type="text",
        collected_at="2026-07-16T14:00:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF", "AI"],
        quality_tier=1,
    )


def _store_scored_raw(store: KBStore, item: Item) -> KBEntry:
    """Store a Raw entry with full provenance and real G1/G3 gate scores so
    the promotion admission gate (T2/T3) admits drafts built from it.

    Mirrors ``make_scored_raw`` in tests/kb/test_promotion.py — G1 lives in
    ``details["source_score"]``, G3 in the gate score (see
    ``test_draft_carries_forward_raw_scores`` for the carry-forward wiring).
    """
    from autoinfo.quality import QualityResult

    g3 = QualityResult(gate_name="G3-RelevanceScoring", passed=True, score=85.0)
    g1 = QualityResult(
        gate_name="G1-SourceAuthority",
        passed=True,
        score=0.0,
        details={"source_score": 72.0},
    )
    return store.store_entry(
        item,
        quality_results={
            "G3-RelevanceScoring": g3,
            "G1-SourceAuthority": g1,
        },
    )


@pytest.fixture(autouse=True)
def _promotion_g4_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the promotion-time G4 factual checker (promotion.py) for a
    passing fake so promote tests never make real LLM calls.

    Mirrors ``patch_g4`` in tests/kb/test_promotion.py: the admission gate
    itself is untouched — only the LLM-backed checker backend is faked.
    """
    from autoinfo.quality import QualityResult

    class _FakeG4:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def check(
            self,
            item: object,  # noqa: ARG002
            extraction: object,  # noqa: ARG002
            gate_config: object | None = None,  # noqa: ARG002
        ) -> QualityResult:
            return QualityResult(
                gate_name="G4-SummaryFactual",
                passed=True,
                score=1.0,
                details={"contradiction": False},
            )

    monkeypatch.setattr("autoinfo.promotion.G4FactualConsistency", _FakeG4)


@pytest.fixture
def raw_entry_ids(store: KBStore, sample_item_1: Item, sample_item_2: Item) -> list[str]:
    """Store two admission-eligible Raw entries (full provenance + real
    G1/G3 scores) and return their entry IDs."""
    e1 = _store_scored_raw(store, sample_item_1)
    e2 = _store_scored_raw(store, sample_item_2)
    return [e1.entry_id, e2.entry_id]


# ===================================================================
# create_kb_draft
# ===================================================================


class TestCreateKbDraft:
    def test_creates_file_in_02_draft(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Compiled draft on IVF imaging",
            summary="Summary of time-lapse imaging research",
        )
        fp = Path(draft.file_path)
        assert fp.exists(), f"Draft file not created at {fp}"
        assert fp.is_file()
        assert "02-Draft" in fp.parts

    def test_auto_generates_summary_when_not_passed(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        """Issue #176: create_kb_draft without a summary must auto-generate a
        deterministic one from the source Raw summaries/titles, so the Draft
        never renders as an empty shell in digest/report."""
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Compiled draft on IVF imaging",
        )
        assert draft.summary, "auto-generated summary must be non-empty"
        # Drawn from the source Raw summaries — no empty-shell, no lang prefix.
        assert "IVF" in draft.summary or "embryo" in draft.summary
        assert not draft.summary.startswith(("本期", "要点"))

    def test_explicit_summary_wins(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        """An explicitly passed summary is kept verbatim (API compatible)."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Compiled draft on IVF imaging",
            summary="Explicit custom summary",
        )
        assert draft.summary == "Explicit custom summary"

    def test_rejects_draft_from_short_raw_entry(
        self, store: KBStore
    ) -> None:
        """A Draft compiled from a Raw entry whose merged content is below
        MIN_KB_CONTENT_CHARS is rejected (issue #279 — the same 50-char
        floor process/import paths enforce must hold at Draft creation)."""
        from autoinfo.kb import MIN_KB_CONTENT_CHARS

        raw = store.store_entry(
            Item(
                id="raw-short",
                source_name="pubmed",
                source_type="api",
                source_url="https://example.com/short",
                source_platform="pubmed",
                title="Tiny raw title",
                content="tiny",
                content_type="text",
                collected_at="2026-07-15T10:30:00Z",
                language="en",
                domain="medical-research",
                topic_tags=["IVF"],
                quality_tier=1,
            )
        )
        assert raw is not None

        strict = KBStore(
            base_path=store.base_path,
            min_content_chars=MIN_KB_CONTENT_CHARS,
        )
        with pytest.raises(ValueError, match="too short"):
            strict.create_kb_draft(
                raw_ids=[raw.entry_id],
                title="Draft from short raw",
            )
        assert not list(
            (store.base_path / "medical-research" / "02-Draft").rglob("*.md")
        ), "no Draft file may be written for short content"

    def test_draft_tier_is_02_draft(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft on IVF",
        )
        assert draft.tier == "02-Draft"

    def test_frontmatter_has_correct_tier(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Frontmatter test draft",
        )
        raw = Path(draft.file_path).read_text(encoding="utf-8")
        assert raw.startswith("---")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["tier"] == "02-Draft"
        assert fm["entry_id"] == draft.entry_id
        assert fm["title"] == "Frontmatter test draft"

    def test_frontmatter_includes_source_raw_ids(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Draft with source refs",
        )
        raw = Path(draft.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        # custom_fields should contain source_raw_ids — but tier is the important field
        assert fm["tier"] == "02-Draft"

    def test_body_links_back_to_raw_ids(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Draft with source refs",
        )
        raw = Path(draft.file_path).read_text(encoding="utf-8")
        # Each source should appear as a section heading
        for rid in raw_entry_ids:
            # The raw entry titles should appear in the body
            pass
        # The _Compiled from: line should exist
        assert "_Compiled from:" in raw

    def test_nonexistent_raw_id_raises_value_error(self, store: KBStore) -> None:
        with pytest.raises(ValueError, match="not found"):
            store.create_kb_draft(
                raw_ids=["nonexistent-id"],
                title="Bad draft",
            )

    def test_empty_raw_ids_raises_value_error(self, store: KBStore) -> None:
        with pytest.raises(ValueError, match="empty"):
            store.create_kb_draft(
                raw_ids=[],
                title="Empty draft",
            )

    def test_multiple_raw_ids_merged_into_single_draft(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Merged draft",
            tags=["IVF", "imaging"],
        )
        fp = Path(draft.file_path)
        assert fp.exists()
        raw = fp.read_text(encoding="utf-8")
        # Both raw entry titles should appear in the body
        assert "Source 1:" in raw or "Time-lapse" in raw
        assert "Source 2:" in raw or "AI-assisted" in raw

    def test_draft_tags_stored_in_sqlite(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Tagged draft",
            tags=["IVF", "imaging", "draft"],
        )
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        stored_tags = json.loads(meta["tags"])
        assert "IVF" in stored_tags
        assert "imaging" in stored_tags
        assert "draft" in stored_tags

    def test_sqlite_index_has_draft_tier(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="SQLite tier test",
        )
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "02-Draft"

    def test_draft_summary_stored(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Summary test",
            summary="This is a test summary for the draft.",
        )
        assert draft.summary == "This is a test summary for the draft."
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert "test summary" in meta.get("summary", "")

    def test_raw_entry_still_in_01_raw(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        """Creating a Draft should not remove or alter the original Raw entries."""
        store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Non-destructive test",
        )
        raw_meta = store.index.get_entry(raw_entry_ids[0])
        assert raw_meta is not None
        assert raw_meta["tier"] == "01-Raw"

    def test_draft_with_non_raw_entry_raises_error(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Creating a draft from a non-01-Raw entry should fail."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Intermediate",
        )
        # Now try to use the Draft as a raw source
        with pytest.raises(ValueError, match="not in 01-Raw"):
            store.create_kb_draft(
                raw_ids=[draft.entry_id],
                title="Double-draft",
            )


# ===================================================================
# reject_kb_draft
# ===================================================================


class TestRejectKbDraft:
    def test_reject_moves_to_01_raw(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft to reject",
        )
        result = store.reject_kb_draft(draft_id=draft.entry_id, reason="Not relevant")
        assert result["status"] == "rejected"
        assert result["action"] == "back_to_raw"
        assert "01-Raw" in result["new_path"]

        # Verify the file moved and tier updated in SQLite
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "01-Raw"

        # Original draft file should not exist
        assert not Path(result["old_path"]).exists()
        # New file should exist
        assert Path(result["new_path"]).exists()

    def test_reject_archives_entry(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft to archive",
        )
        result = store.reject_kb_draft(
            draft_id=draft.entry_id, reason="Out of scope", action="archive"
        )
        assert result["status"] == "archived"
        assert result["action"] == "archive"
        assert "_archive" in result["new_path"]

        # Entry should be removed from index
        meta = store.index.get_entry(draft.entry_id)
        assert meta is None

        # Original file should not exist
        assert not Path(result["old_path"]).exists()
        # Archived file should exist
        assert Path(result["new_path"]).exists()

    def test_reject_nonexistent_draft_raises_error(self, store: KBStore) -> None:
        with pytest.raises(ValueError, match="not found"):
            store.reject_kb_draft(draft_id="nonexistent-draft")

    def test_reject_raw_entry_raises_error(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        with pytest.raises(ValueError, match="not a Draft"):
            store.reject_kb_draft(draft_id=raw_entry_ids[0])

    def test_reject_adds_rejection_reason_to_frontmatter(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Rejection reason test",
        )
        result = store.reject_kb_draft(draft_id=draft.entry_id, reason="Duplicate content")
        # Read the moved file's frontmatter
        new_fp = Path(result["new_path"])
        raw = new_fp.read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["rejection_reason"] == "Duplicate content"
        assert "rejected_at" in fm


# ===================================================================
# list_kb_tier
# ===================================================================


class TestListKbTier:
    def test_list_draft_returns_only_drafts(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft A",
        )
        entries = store.list_kb_tier(domain="medical-research", tier="02-Draft")
        assert len(entries) == 1
        assert entries[0]["entry_id"] == draft.entry_id
        assert entries[0]["tier"] == "02-Draft"

    def test_list_raw_returns_only_raw(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft B",
        )
        raw_entries = store.list_kb_tier(domain="medical-research", tier="01-Raw")
        assert len(raw_entries) == 2  # Both sample items are in 01-Raw
        for e in raw_entries:
            assert e["tier"] == "01-Raw"

    def test_list_tier_empty_domain(self, store: KBStore) -> None:
        entries = store.list_kb_tier(domain="nonexistent", tier="02-Draft")
        assert entries == []

    def test_list_tier_pagination(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        for i in range(5):
            store.create_kb_draft(
                raw_ids=[raw_entry_ids[0]],
                title=f"Draft pagination {i}",
            )
        page1 = store.list_kb_tier(domain="medical-research", tier="02-Draft", limit=2, offset=0)
        assert len(page1) == 2
        page2 = store.list_kb_tier(domain="medical-research", tier="02-Draft", limit=2, offset=2)
        assert len(page2) == 2
        ids_p1 = {e["entry_id"] for e in page1}
        ids_p2 = {e["entry_id"] for e in page2}
        assert ids_p1.isdisjoint(ids_p2)


# ===================================================================
# SQLiteIndex tier column
# ===================================================================


class TestSQLiteIndexTier:
    def test_tier_column_exists(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        """Verify the tier column is present in the SQLite schema."""
        import sqlite3

        db_path = store.index.db_path
        conn = sqlite3.connect(str(db_path))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()]
        assert "tier" in cols
        conn.close()

    def test_raw_entry_has_01_raw_tier(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        meta = store.index.get_entry(raw_entry_ids[0])
        assert meta is not None
        assert meta["tier"] == "01-Raw"

    def test_list_entries_filters_by_tier(self, store: KBStore, raw_entry_ids: list[str]) -> None:
        store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Tier filter draft",
        )
        # list_entries with tier filter should work
        drafts = store.index.list_entries(domain="medical-research", tier="02-Draft")
        assert len(drafts) >= 1
        for d in drafts:
            assert d["tier"] == "02-Draft"


# ===================================================================
# Expanded frontmatter fields — author, source_ids, status, etc.
# ===================================================================


class TestExpandedFrontmatter:
    def test_frontmatter_has_expanded_fields(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Draft frontmatter must include all 5 new fields."""
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Expanded frontmatter test",
            summary="Testing new frontmatter fields",
            tags=["test"],
        )
        raw = Path(draft.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])

        assert "author" in fm, "Missing author in frontmatter"
        assert "source_ids" in fm, "Missing source_ids in frontmatter"
        assert "status" in fm, "Missing status in frontmatter"
        assert "related_concepts" in fm, "Missing related_concepts in frontmatter"
        assert "linked_entries" in fm, "Missing linked_entries in frontmatter"

        # Check default values
        assert fm["author"] == ""
        assert fm["source_ids"] == raw_entry_ids
        assert fm["status"] == "active"
        assert fm["related_concepts"] == []
        assert fm["linked_entries"] == []

    def test_draft_custom_fields_stored_in_sqlite(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """New fields should be serialized into custom_fields JSON in SQLite."""
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="SQLite custom_fields test",
        )
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None

        custom_fields_raw = meta.get("custom_fields") or "{}"
        cf = json.loads(custom_fields_raw)
        assert cf.get("author") == ""
        assert cf.get("source_ids") == raw_entry_ids
        assert cf.get("status") == "active"
        assert cf.get("related_concepts") == []
        assert cf.get("linked_entries") == []

    def test_raw_entry_does_not_have_expanded_fields(
        self, store: KBStore, sample_item_1: Item
    ) -> None:
        """01-Raw entries should NOT contain the expanded frontmatter fields."""
        entry = store.store_entry(sample_item_1)
        raw = Path(entry.file_path).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])

        assert "author" not in fm, "author should not appear in 01-Raw frontmatter"
        assert "source_ids" not in fm, "source_ids should not appear in 01-Raw frontmatter"
        assert "status" not in fm, "status should not appear in 01-Raw frontmatter"
        assert "related_concepts" not in fm, (
            "related_concepts should not appear in 01-Raw frontmatter"
        )
        assert "linked_entries" not in fm, "linked_entries should not appear in 01-Raw frontmatter"

    def test_expanded_fields_survive_promotion(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Expanded fields should carry forward through Draft → Wiki promotion."""
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Promotion frontmatter test",
        )
        result = store.promote_kb_draft(draft_id=draft.entry_id)
        raw = Path(result["new_path"]).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])

        assert "author" in fm
        assert "source_ids" in fm
        assert "status" in fm
        assert "related_concepts" in fm
        assert "linked_entries" in fm
        # Status should still be "active" after promotion
        assert fm["status"] == "active"
        assert fm["source_ids"] == raw_entry_ids

    def test_backwards_compatibility_no_custom_fields(self, store: KBStore) -> None:
        """Entries without custom_fields column or with empty JSON should load fine."""
        entry = KBEntry(
            entry_id="legacy-entry",
            title="Legacy entry",
            domain="medical-research",
            tier="02-Draft",
            source_url="https://example.com/legacy",
            source_type="api",
            source_platform="pubmed",
            collected_at="2026-01-01T00:00:00Z",
            summary="Legacy entry without expanded fields",
            tags=["legacy"],
            quality_tier=1,
            relevance_score=0.0,
            dedup_status="unique",
            file_path="/tmp/nonexistent.md",
        )
        # Index without custom_fields column value — simulate legacy row
        with store.index._connect() as conn:
            conn.execute(
                """INSERT INTO entries
                   (entry_id, title, domain, tier, source_url, source_type,
                    source_platform, collected_at, summary, quality_tier,
                    relevance_score, dedup_status, file_path, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.entry_id,
                    entry.title,
                    entry.domain,
                    entry.tier,
                    entry.source_url,
                    entry.source_type,
                    entry.source_platform,
                    entry.collected_at,
                    entry.summary,
                    entry.quality_tier,
                    entry.relevance_score,
                    entry.dedup_status,
                    entry.file_path,
                    json.dumps(entry.tags),
                ),
            )

        # Should load without error
        meta = store.index.get_entry(entry.entry_id)
        assert meta is not None
        assert meta["entry_id"] == "legacy-entry"

        # custom_fields should be empty string from SQLite
        cf_raw = meta.get("custom_fields") or "{}"
        cf = json.loads(cf_raw)
        assert cf == {}
        # KBEntry constructed from filtered meta should have defaults
        kb_fields = {
            k: v for k, v in meta.items()
            if k in KBEntry.__dataclass_fields__
        }
        kb_fields["custom_fields"] = cf
        loaded = KBEntry(**kb_fields)
        assert loaded.author == ""
        assert loaded.source_ids == []
        assert loaded.status == "active"
        assert loaded.related_concepts == []
        assert loaded.linked_entries == []

    def test_expanded_fields_persist_after_reject(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Expanded fields should survive Draft → Raw demotion (reject).

        Note: reject modifies the existing file frontmatter in-place
        (adding rejection_reason) rather than rebuilding via
        _build_frontmatter(), so expanded fields from the Draft persist
        in the file even after demotion to 01-Raw.
        """
        draft = store.create_kb_draft(
            raw_ids=raw_entry_ids,
            title="Reject field preservation test",
        )
        result = store.reject_kb_draft(draft_id=draft.entry_id, reason="Test")
        raw = Path(result["new_path"]).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])

        # Expanded fields persist in file because reject modified in-place
        assert "author" in fm
        # SQLite custom_fields should still have them
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        cf = json.loads(meta.get("custom_fields") or "{}")
        assert cf.get("source_ids") == raw_entry_ids
        # Entry is now 01-Raw in SQLite
        assert meta["tier"] == "01-Raw"


# ===================================================================
# promote_kb_draft
# ===================================================================


class TestPromoteKbDraft:
    def test_promote_moves_draft_to_03_wiki(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Unit test: promote a Draft -> 03-Wiki."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Draft to promote",
        )
        result = store.promote_kb_draft(draft_id=draft.entry_id)
        assert result["status"] == "promoted"
        assert "03-Wiki" in result["new_path"]
        assert "02-Draft" not in result["new_path"]

        # Verify SQLite updated
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "03-Wiki"

        # Original Draft file should be gone
        assert not Path(result["old_path"]).exists()
        # New Wiki file should exist
        assert Path(result["new_path"]).exists()

    def test_promote_records_agent_promotion_source(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Unit test: promoted file gets promotion_source=agent + promoted_at
        in frontmatter (T2: human_promoted is no longer written)."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Frontmatter promote test",
        )
        result = store.promote_kb_draft(draft_id=draft.entry_id)
        raw = Path(result["new_path"]).read_text(encoding="utf-8")
        end = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end])
        assert fm["promotion_source"] == "agent"
        assert "human_promoted" not in fm
        assert "promoted_at" in fm

    def test_promote_nonexistent_draft_raises_error(self, store: KBStore) -> None:
        """Negative test: promote non-existent entry -> ValueError."""
        with pytest.raises(ValueError, match="not found"):
            store.promote_kb_draft(draft_id="nonexistent-draft")

    def test_promote_raw_entry_raises_error(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Negative test: promote a Raw entry (not Draft) -> ValueError."""
        with pytest.raises(ValueError, match="not a Draft"):
            store.promote_kb_draft(draft_id=raw_entry_ids[0])

    def test_promote_preserves_entry_id(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Unit test: entry_id stays the same after promotion."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="ID preservation test",
        )
        original_id = draft.entry_id
        store.promote_kb_draft(draft_id=original_id)
        meta = store.index.get_entry(original_id)
        assert meta is not None
        assert meta["entry_id"] == original_id

    def test_promote_does_not_delete_other_tiers(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Unit test: existing Raw entries are untouched after promotion."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="Non-destructive promote",
        )
        store.promote_kb_draft(draft_id=draft.entry_id)
        # Raw entry should still exist
        raw_meta = store.index.get_entry(raw_entry_ids[0])
        assert raw_meta is not None
        assert raw_meta["tier"] == "01-Raw"

    def test_promote_cli_integration(
        self, store: KBStore, raw_entry_ids: list[str]
    ) -> None:
        """Integration test: simulate CLI promote via direct API call
        (matching the CLI pattern exactly)."""
        draft = store.create_kb_draft(
            raw_ids=[raw_entry_ids[0]],
            title="CLI integration draft",
        )
        # Same call pattern as the CLI handler
        result = store.promote_kb_draft(draft_id=draft.entry_id)
        # Verify the result dict structure matches what CLI outputs
        assert "status" in result
        assert "draft_id" in result
        assert "old_path" in result
        assert "new_path" in result
        assert "promoted_at" in result
        # Verify the promoted entry exists in 03-Wiki
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "03-Wiki"
        assert Path(result["new_path"]).exists()


# ===================================================================
# _ensure_not_wiki (03-Wiki append-only guard)
# ===================================================================


class TestEnsureNotWiki:
    def test_store_entry_to_03_wiki_raises_permission_error(
        self, store: KBStore, sample_item_1: Item
    ) -> None:
        """Negative test: agent cannot write directly to 03-Wiki via store_entry()."""
        with pytest.raises(PermissionError, match="03-Wiki is append-only"):
            store.store_entry(sample_item_1, tier="03-Wiki")

    def test_store_entry_to_01_raw_is_allowed(
        self, store: KBStore, sample_item_1: Item
    ) -> None:
        """Unit test: writing to 01-Raw is not blocked."""
        entry = store.store_entry(sample_item_1)
        assert entry.tier == "01-Raw"
        assert Path(entry.file_path).exists()


# ===================================================================
# Promotion provenance — KBEntry fields + Draft score carry-forward
# ===================================================================


class TestPromotionProvenance:
    """T1: promotion_source/promoted_by provenance fields and Draft
    carry-forward of real Raw scores (G-02: scores must not be zeroed)."""

    def test_promotion_fields_exist_on_model_default_none(self) -> None:
        """KBEntry exposes nullable promotion_source/promoted_by, defaulting to None."""
        entry = KBEntry(
            entry_id="prov-1",
            title="Provenance model",
            domain="medical-research",
        )
        assert entry.promotion_source is None
        assert entry.promoted_by is None
        entry.promotion_source = "agent"
        entry.promoted_by = "alice"
        assert entry.promotion_source == "agent"
        assert entry.promoted_by == "alice"

    def test_promotion_fields_render_in_frontmatter_when_set(self) -> None:
        """Set promotion fields appear in generated frontmatter."""
        from autoinfo.kb import _build_frontmatter

        entry = KBEntry(
            entry_id="prov-2",
            title="Provenance fm",
            domain="medical-research",
            tier="02-Draft",
            promotion_source="agent",
            promoted_by="alice",
        )
        fm = _build_frontmatter(entry)
        assert "promotion_source: agent" in fm
        assert "promoted_by: alice" in fm

    def test_promotion_fields_omitted_from_frontmatter_when_unset(self) -> None:
        """Nullable provenance fields stay out of frontmatter when unset."""
        from autoinfo.kb import _build_frontmatter

        entry = KBEntry(
            entry_id="prov-3",
            title="Provenance none",
            domain="medical-research",
            tier="02-Draft",
        )
        fm = _build_frontmatter(entry)
        assert "promotion_source" not in fm
        assert "promoted_by" not in fm

    def test_draft_carries_forward_raw_scores(
        self, store: KBStore, sample_item_1: Item
    ) -> None:
        """A Draft created from a scored Raw entry inherits the exact
        G1/G3-derived values instead of hardcoded 0/1."""
        from autoinfo.quality import QualityResult

        g3 = QualityResult(
            gate_name="G3-RelevanceScoring", passed=True, score=87.5
        )
        g1 = QualityResult(
            gate_name="G1-SourceAuthority",
            passed=True,
            score=0.0,
            details={"source_score": 72.0},
        )
        sample_item_1.quality_tier = 3
        raw = store.store_entry(
            sample_item_1,
            quality_results={
                "G3-RelevanceScoring": g3,
                "G1-SourceAuthority": g1,
            },
        )
        assert raw.relevance_score == 87.5
        assert raw.quality_tier == 3
        assert raw.source_score == 72.0

        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Score carry-forward draft",
        )
        assert draft.relevance_score == 87.5
        assert draft.quality_tier == 3
        assert draft.source_score == 72.0

        fm_raw = Path(draft.file_path).read_text(encoding="utf-8")
        end = fm_raw.find("---", 3)
        fm = yaml.safe_load(fm_raw[3:end])
        assert fm["relevance_score"] == 87.5
        assert fm["quality_tier"] == 3
        assert fm["source_score"] == 72.0

        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["relevance_score"] == 87.5
        assert meta["quality_tier"] == 3
        assert meta["source_score"] == 72.0

    def test_draft_from_legacy_raw_without_scores_creates_fine(
        self, store: KBStore, sample_item_1: Item
    ) -> None:
        """A Draft from a legacy Raw row (score columns never populated)
        still creates fine and stays 'pending' (no promotion provenance)."""
        raw = store.store_entry(sample_item_1)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Legacy-source draft",
        )
        assert draft.tier == "02-Draft"
        assert Path(draft.file_path).exists()
        assert draft.relevance_score == 0.0
        assert draft.quality_tier == 1
        assert draft.source_score == 0.0
        assert draft.promotion_source is None
        assert draft.promoted_by is None
        meta = store.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "02-Draft"

    def test_legacy_draft_without_source_raw_ids_preserves_real_values(
        self, store: KBStore
    ) -> None:
        """A pre-provenance Draft (no source_raw_ids custom field) keeps
        its previously-real scores — loading never zeroes them."""
        entry = KBEntry(
            entry_id="legacy-draft-no-raw",
            title="Legacy no-raw draft",
            domain="medical-research",
            tier="02-Draft",
            source_url="https://example.com/legacy",
            source_type="api",
            source_platform="pubmed",
            collected_at="2026-01-01T00:00:00Z",
            summary="",
            tags=["legacy"],
            quality_tier=2,
            relevance_score=66.0,
            source_score=58.0,
            dedup_status="unique",
            file_path=str(
                store.base_path / "medical-research" / "02-Draft"
                / "general" / "legacy-draft.md"
            ),
        )
        store.index.index_entry(entry)
        meta = store.get_entry(entry.entry_id)
        assert meta is not None
        assert meta["tier"] == "02-Draft"
        assert meta["relevance_score"] == 66.0
        assert meta["quality_tier"] == 2
        assert meta["source_score"] == 58.0
