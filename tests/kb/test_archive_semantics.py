"""Archive semantics tests (T3.1 / T3.2).

Verifies the approved archive decision: a soft-gate ``archive`` action
(e.g. G3 relevance below threshold) stores the item with
``status="archived"`` — still stored, never deleted, but excluded from
search results and digest generation, while direct retrieval by
``entry_id`` keeps working.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.process import run_processing
from autoinfo.quality import QualityResult

# ===================================================================
# Shared fixtures / helpers
# ===================================================================

DOMAIN = "archive-test-domain"


def _make_item(item_id: str, title: str, topic: str = "research") -> Item:
    """Return a well-formed Item with content long enough for KB storage."""
    return Item(
        id=item_id,
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url=f"https://example.com/{item_id}",
        title=title,
        content=(
            f"This is the full body content of the article {title}. "
            "It contains enough words to satisfy the minimum content "
            "length required for knowledge base storage."
        ),
        content_type="text",
        collected_at="2026-07-15T10:00:00Z",
        language="en",
        domain=DOMAIN,
        topic_tags=[topic],
        quality_tier=1,
        raw_data={},
    )


def _make_extraction(item_id: str, title: str, score: float) -> ExtractionResult:
    """Return a deterministic ExtractionResult for a mocked LLM call."""
    return ExtractionResult(
        item_id=item_id,
        title=title,
        tl_dr=f"Summary of {title}.",
        key_points=["Point one", "Point two"],
        entities=[{"name": "Entity", "type": "concept", "relevance": 0.5}],
        relevance_score=score,
    )


def _g3_archived() -> dict[str, QualityResult]:
    """G3 below threshold with action 'archive' (the default)."""
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
            gate_name="G3-RelevanceScoring", passed=False, score=5.0,
            flagged=True,
            details={
                "hidden": True,
                "action": "archive",
                "archive": True,
                "reason": "below relevance threshold",
            },
        ),
    }


def _g3_active() -> dict[str, QualityResult]:
    """G3 above threshold — normal active entry."""
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
            gate_name="G3-RelevanceScoring", passed=True, score=90.0,
            details={"hidden": False, "action": "archive"},
        ),
    }


def _entry_status(entry: dict[str, Any]) -> str:
    """Read the ``status`` value from an entry dict's custom_fields JSON."""
    cf = entry.get("custom_fields") or "{}"
    try:
        cf_dict = json.loads(cf) if isinstance(cf, str) else dict(cf)
    except (json.JSONDecodeError, TypeError):
        return ""
    return str(cf_dict.get("status", ""))


# ===================================================================
# T3.1 — G3 archive action stores the item with status="archived"
# ===================================================================


class TestArchiveOnProcessing:
    """``run_processing`` stores G3-archived items with status='archived'."""

    def _run(self, tmp_path: Path, item: Item, quality: dict[str, QualityResult]):
        store = KBStore(base_path=tmp_path / "knowledge", min_content_chars=50)
        mock_ext = MagicMock(
            side_effect=lambda it, schema=None: _make_extraction(
                it.id, it.title, 5.0
            )
        )
        mock_quality = MagicMock(return_value=quality)
        fake_lang_en = type("Lang", (), {"lang": "en", "prob": 0.95})()

        with (
            patch("autoinfo.process.load_cached_items", return_value=[item]),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=store),
            patch("langdetect.detect_langs", return_value=[fake_lang_en]),
        ):
            result = run_processing(DOMAIN)

        assert result.kb_entries_created == 1
        assert result.errors == []
        stored = store.list_entries(DOMAIN, limit=10)
        assert len(stored) == 1
        return store, stored[0]

    def test_low_relevance_item_stored_as_archived(self, tmp_path: Path) -> None:
        """G3 archive item: stored on disk, status='archived', not failed."""
        item = _make_item("item-archived", "Zorpzilla archived research article")
        store, stored = self._run(tmp_path, item, _g3_archived())

        assert _entry_status(stored) == "archived"
        file_path = stored.get("file_path", "")
        assert file_path
        assert Path(file_path).is_file()

        entry = store.get_entry(stored["entry_id"])
        assert entry is not None
        assert _entry_status(entry) == "archived"
        assert "content" in entry and entry["content"]

    def test_high_relevance_item_stays_active(self, tmp_path: Path) -> None:
        """G3 pass item: stored normally with status='active'."""
        item = _make_item("item-active", "Zorpzilla active research article")
        store, stored = self._run(tmp_path, item, _g3_active())

        assert _entry_status(stored) == "active"
        entry = store.get_entry(stored["entry_id"])
        assert entry is not None
        assert _entry_status(entry) == "active"


# ===================================================================
# T3.2 — archived entries excluded from search, still retrievable
# ===================================================================


class TestSearchExcludesArchived:
    """``search_knowledge_base`` hides archived/deprecated entries."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> KBStore:
        store = KBStore(base_path=tmp_path / "knowledge", min_content_chars=0)

        active_item = _make_item("item-active", "Zorpzilla active research article")
        store.store_entry(
            active_item,
            _make_extraction(
                "item-active", "Zorpzilla active research article", 90.0
            ),
            _g3_active(),
        )

        archived_item = _make_item(
            "item-archived", "Zorpzilla archived research article"
        )
        store.store_entry(
            archived_item,
            _make_extraction(
                "item-archived", "Zorpzilla archived research article", 5.0
            ),
            _g3_archived(),
        )

        dep = KBEntry(
            entry_id="dep-001",
            title="Zorpzilla deprecated research article",
            domain=DOMAIN,
            tier="01-Raw",
            source_url="https://example.com/dep-001",
            source_type="api",
            source_platform="pubmed",
            collected_at="2026-07-15T10:00:00Z",
            tags=["research"],
            status="deprecated",
        )
        store.index.index_entry(dep)
        store.index.index_entry_fts5(dep, content=dep.title)

        return store

    def test_archived_absent_from_search(self, store: KBStore) -> None:
        """Search hits only the active entry, never archived/deprecated."""
        stored = store.list_entries(DOMAIN, limit=10)
        ids_by_title = {e["title"]: e["entry_id"] for e in stored}
        active_id = ids_by_title["Zorpzilla active research article"]
        archived_id = ids_by_title["Zorpzilla archived research article"]

        result = store.search_knowledge_base("zorpzilla", domain=DOMAIN)
        ids = [e["entry_id"] for e in result["entries"]]

        assert active_id in ids
        assert archived_id not in ids
        assert "dep-001" not in ids

    def test_archived_still_retrievable_by_id(self, store: KBStore) -> None:
        """Direct retrieval by entry_id works for archived entries."""
        stored = store.list_entries(DOMAIN, limit=10)
        archived_id = next(
            e["entry_id"]
            for e in stored
            if e["title"] == "Zorpzilla archived research article"
        )
        entry = store.get_entry(archived_id)
        assert entry is not None
        assert entry["entry_id"] == archived_id
        assert _entry_status(entry) == "archived"


# ===================================================================
# T3.2 — archived entries excluded from digest generation
# ===================================================================


class TestDigestExcludesArchived:
    """``generate_digest`` never surfaces archived/deprecated entries."""

    def _entry_dict(
        self, entry_id: str, title: str, status: str
    ) -> dict[str, Any]:
        return {
            "entry_id": entry_id,
            "title": title,
            "domain": "test-domain",
            "tier": "01-Raw",
            "source_url": f"https://example.com/{entry_id}",
            "source_type": "rss",
            "source_platform": "demo",
            "collected_at": (date.today() - timedelta(days=1)).isoformat(),
            "summary": f"Summary of {title}.",
            "tags": "[]",
            "quality_tier": 1,
            "relevance_score": 80.0,
            "dedup_status": "unique",
            "file_path": "",
            "custom_fields": json.dumps({"status": status}),
        }

    def _digest(
        self,
        entries: list[dict[str, Any]],
    ) -> str:
        from autoinfo.output import generate_digest

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_digest") as mock_llm,
        ):
            mock_llm.return_value = {"executive_summary": "Synthesis."}
            mock_store = MagicMock()
            mock_store.list_entries.return_value = entries
            mock_store.list_kb_tier.return_value = []
            mock_kb_cls.return_value = mock_store
            return generate_digest(
                domain="test-domain", period="weekly", format="markdown"
            )

    def test_archived_entry_not_in_digest(self) -> None:
        """Only the active entry is rendered into the digest."""
        active = self._entry_dict(
            "active-001", "Zorpzilla active digest article", "active"
        )
        archived = self._entry_dict(
            "archived-001", "Zorpzilla archived digest article", "archived"
        )
        deprecated = self._entry_dict(
            "deprecated-001", "Zorpzilla deprecated digest article", "deprecated"
        )

        rendered = self._digest([active, archived, deprecated])

        assert "Zorpzilla active digest article" in rendered
        assert "Zorpzilla archived digest article" not in rendered
        assert "Zorpzilla deprecated digest article" not in rendered

    def test_entries_without_status_unchanged(self) -> None:
        """Backward compatibility: entries lacking custom_fields status stay."""
        legacy = {
            "entry_id": "legacy-001",
            "title": "Zorpzilla legacy digest article",
            "domain": "test-domain",
            "tier": "01-Raw",
            "source_url": "https://example.com/legacy-001",
            "source_type": "rss",
            "source_platform": "demo",
            "collected_at": (date.today() - timedelta(days=1)).isoformat(),
            "summary": "Summary of legacy.",
            "tags": "[]",
            "quality_tier": 1,
            "relevance_score": 80.0,
            "dedup_status": "unique",
            "file_path": "",
        }

        rendered = self._digest([legacy])

        assert "Zorpzilla legacy digest article" in rendered


# ===================================================================
# T3.4 — re-ingest preserves lifecycle status (backup issue #79)
# ===================================================================


class TestReprocessPreservesDeliverableStatus:
    """Re-processing re-runs the quality gates over cached items.  A gate
    deciding 'archive' on a re-run must NOT downgrade an already-delivered
    entry (active -> archived) — that removes valid content from digests
    (empty-shell regression).  entry_id is content-derived, so a re-ingest
    of the same item resolves to the same id: the existing status wins;
    gates only apply to NEW entries."""

    def _store(self, tmp_path: Path) -> KBStore:
        return KBStore(base_path=tmp_path / "knowledge", min_content_chars=50)

    def test_active_stays_active_on_reingest_with_archive_gate(
        self, tmp_path: Path
    ) -> None:
        """A delivered (active) entry re-ingested with a gate that says
        archive stays active — the deliverable is not downgraded."""
        store = self._store(tmp_path)
        item = _make_item("reproc-1", "Zorpzilla reingest active article")
        ext = _make_extraction("reproc-1", item.title, 70.0)
        first = store.store_entry(item, ext, _g3_active())
        assert _entry_status(store.get_entry(first.entry_id)) == "active"

        second = store.store_entry(item, ext, _g3_archived())
        assert _entry_status(store.get_entry(second.entry_id)) == "active"

    def test_archived_stays_archived_on_reingest(self, tmp_path: Path) -> None:
        """An archived entry stays archived when re-ingested with a passing
        gate — a reprocess never silently resurrects rejected content."""
        store = self._store(tmp_path)
        item = _make_item("reproc-2", "Zorpzilla reingest archived article")
        ext = _make_extraction("reproc-2", item.title, 5.0)
        first = store.store_entry(item, ext, _g3_archived())
        assert _entry_status(store.get_entry(first.entry_id)) == "archived"

        second = store.store_entry(item, ext, _g3_active())
        assert _entry_status(store.get_entry(second.entry_id)) == "archived"

    def test_new_entry_goes_through_gate(self, tmp_path: Path) -> None:
        """A brand-new entry (no existing id) still follows the gates —
        archive applies to first-time ingestion."""
        store = self._store(tmp_path)
        item = _make_item("reproc-3", "Zorpzilla brand new article")
        ext = _make_extraction("reproc-3", item.title, 5.0)
        entry = store.store_entry(item, ext, _g3_archived())
        assert _entry_status(store.get_entry(entry.entry_id)) == "archived"

    def test_deprecated_stays_deprecated(self, tmp_path: Path) -> None:
        """An explicitly-deprecated entry is never resurrected by a
        reprocess gate decision."""
        store = self._store(tmp_path)
        item = _make_item("reproc-4", "Zorpzilla deprecated article")
        ext = _make_extraction("reproc-4", item.title, 70.0)
        first = store.store_entry(item, ext, _g3_active())
        # Explicitly deprecate at the SQLite layer (director deprecation).
        entry = store.get_entry(first.entry_id)
        cf = json.loads(entry.get("custom_fields") or "{}")
        cf["status"] = "deprecated"
        with store.index._connect() as conn:
            conn.execute(
                "UPDATE entries SET custom_fields = ? WHERE entry_id = ?",
                (json.dumps(cf, ensure_ascii=False), first.entry_id),
            )

        second = store.store_entry(item, ext, _g3_active())
        assert _entry_status(store.get_entry(second.entry_id)) == "deprecated"
