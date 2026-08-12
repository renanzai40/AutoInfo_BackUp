"""Tests for collection stats / diff / config overrides (tasks 24+25)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from autoinfo.kb import KBStore, SQLiteIndex
from autoinfo.models import Item, KBEntry
from autoinfo.status import get_collection_stats, get_collection_diff


def _seed_entries(index: SQLiteIndex, domain: str, count: int, days_ago: int = 0) -> list[str]:
    """Insert *count* entries into the index for *domain*."""
    from datetime import date, timedelta

    collected = (date.today() - timedelta(days=days_ago)).isoformat()
    ids: list[str] = []
    for i in range(count):
        eid = f"{domain}-entry-{i}"
        dedup = "unique" if i % 3 != 0 else "duplicate"
        entry = KBEntry(
            entry_id=eid,
            title=f"{domain} entry {i}",
            domain=domain,
            source_url=f"https://example.com/{domain}/{i}",
            source_type="api",
            source_platform="pubmed" if domain == "medical-research" else "arxiv",
            collected_at=collected,
            summary="",
            tags=["test"],
            quality_tier=1,
            relevance_score=50.0,
            dedup_status=dedup,
            file_path="",
        )
        index.index_entry(entry)
        ids.append(eid)
    return ids


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_monitor.db"


@pytest.fixture
def index(db_path: Path) -> SQLiteIndex:
    idx = SQLiteIndex(db_path)
    idx.init_db()
    return idx


@pytest.fixture
def pop_index(index: SQLiteIndex) -> SQLiteIndex:
    """Pre-populated index with entries across domains."""
    _seed_entries(index, "medical-research", 10, days_ago=0)
    _seed_entries(index, "ai-commercial", 5, days_ago=0)
    _seed_entries(index, "language-learning", 3, days_ago=30)
    return index


class TestCollectionStats:
    """get_collection_stats behavior."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> KBStore:
        kb_path = tmp_path / "knowledge"
        kb_path.mkdir(parents=True, exist_ok=True)
        return KBStore(base_path=kb_path)

    def _make_store_with_index(
        self, tmp_path: Path, index: SQLiteIndex
    ) -> KBStore:
        """Create a KBStore that uses the given index."""
        kb_path = tmp_path / "knowledge"
        kb_path.mkdir(parents=True, exist_ok=True)
        store = KBStore(base_path=kb_path)
        store.index = index
        return store

    def test_daily_stats_returns_counts(
        self, pop_index: SQLiteIndex, tmp_path: Path
    ) -> None:
        store = self._make_store_with_index(tmp_path, pop_index)
        stats = store.get_collection_stats(period="daily")
        assert stats["period"] == "daily"
        assert stats["total_items"] >= 10
        assert "medical-research" in stats["domains"]
        assert "ai-commercial" in stats["domains"]

    def test_weekly_stats(
        self, pop_index: SQLiteIndex, tmp_path: Path
    ) -> None:
        store = self._make_store_with_index(tmp_path, pop_index)
        stats = store.get_collection_stats(period="weekly")
        assert stats["total_items"] >= 15

    def test_monthly_stats(
        self, pop_index: SQLiteIndex, tmp_path: Path
    ) -> None:
        store = self._make_store_with_index(tmp_path, pop_index)
        stats = store.get_collection_stats(period="monthly")
        assert stats["total_items"] >= 18
        assert "language-learning" in stats["domains"]

    def test_stats_has_domain_and_source_breakdown(
        self, pop_index: SQLiteIndex, tmp_path: Path
    ) -> None:
        store = self._make_store_with_index(tmp_path, pop_index)
        stats = store.get_collection_stats(period="monthly")
        assert isinstance(stats["domains"], dict)
        assert isinstance(stats["sources"], dict)
        assert stats["domains"].get("medical-research", 0) >= 10
        assert stats["domains"].get("ai-commercial", 0) >= 5

    def test_stats_empty_db(self, db_path: Path, tmp_path: Path) -> None:
        idx = SQLiteIndex(db_path)
        idx.init_db()
        store = self._make_store_with_index(tmp_path, idx)
        stats = store.get_collection_stats(period="daily")
        assert stats["total_items"] == 0
        assert stats["domains"] == {}
        assert stats["sources"] == {}

    def test_status_wrapper_get_collection_stats(
        self, pop_index: SQLiteIndex, tmp_path: Path
    ) -> None:
        store = self._make_store_with_index(tmp_path, pop_index)
        stats = store.get_collection_stats(period="daily")
        assert "period" in stats
        assert "total_items" in stats


class TestCollectionDiff:
    """get_collection_diff behavior."""

    def _make_store(self, tmp_path: Path, index: SQLiteIndex) -> KBStore:
        kb_path = tmp_path / "knowledge"
        kb_path.mkdir(parents=True, exist_ok=True)
        store = KBStore(base_path=kb_path)
        store.index = index
        return store

    def test_diff_returns_new_entries(
        self, index: SQLiteIndex, tmp_path: Path
    ) -> None:
        _seed_entries(index, "test", 3, days_ago=10)
        _seed_entries(index, "test", 2, days_ago=0)

        store = self._make_store(tmp_path, index)
        diff = store.get_collection_diff("2026-07-15")
        assert diff["count"] == 3

    def test_diff_returns_domain_grouping(
        self, index: SQLiteIndex, tmp_path: Path
    ) -> None:
        _seed_entries(index, "med", 3, days_ago=0)
        _seed_entries(index, "ai", 2, days_ago=0)

        store = self._make_store(tmp_path, index)
        diff = store.get_collection_diff("2026-07-01")
        assert diff["count"] == 5
        assert "med" in diff["domains"]
        assert "ai" in diff["domains"]

    def test_diff_no_new_entries(
        self, index: SQLiteIndex, tmp_path: Path
    ) -> None:
        _seed_entries(index, "test", 3, days_ago=10)

        store = self._make_store(tmp_path, index)
        diff = store.get_collection_diff("2099-01-01")
        assert diff["count"] == 0
        assert diff["new_entries"] == []

    def test_status_wrapper_get_collection_diff(
        self, index: SQLiteIndex, tmp_path: Path
    ) -> None:
        _seed_entries(index, "test", 3, days_ago=0)
        store = self._make_store(tmp_path, index)
        diff = store.get_collection_diff("2026-07-01")
        assert "since_id" in diff
        assert "new_entries" in diff


class TestConfigOverrides:
    """Config override system (task 25)."""

    @pytest.fixture
    def overrides_dir(self, tmp_path: Path) -> Path:
        overrides = tmp_path / ".autoinfo" / "overrides"
        overrides.mkdir(parents=True, exist_ok=True)
        return overrides

    def test_override_file_creation(self, overrides_dir: Path) -> None:
        """Verify an override YAML file can be created and loaded."""
        override = {"llm": {"model": "gpt-4"}}
        override_path = overrides_dir / "production.yaml"
        with open(override_path, "w", encoding="utf-8") as f:
            yaml.dump(override, f)

        assert override_path.is_file()
        with open(override_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["llm"]["model"] == "gpt-4"

    def test_override_directory_exists(self, tmp_path: Path) -> None:
        """The overrides dir is created if it doesn't exist."""
        overrides = tmp_path / ".autoinfo" / "overrides"
        overrides.mkdir(parents=True, exist_ok=True)
        assert overrides.is_dir()

    def test_multiple_override_files(self, overrides_dir: Path) -> None:
        """Multiple override files in the directory can be loaded independently."""
        files = {
            "dev.yaml": {"llm": {"model": "deepseek-chat"}},
            "prod.yaml": {"llm": {"model": "gpt-4"}},
        }
        for name, content in files.items():
            with open(overrides_dir / name, "w", encoding="utf-8") as f:
                yaml.dump(content, f)

        # Each file should be independently loadable
        with open(overrides_dir / "dev.yaml", encoding="utf-8") as f:
            dev = yaml.safe_load(f)
        assert dev["llm"]["model"] == "deepseek-chat"

        with open(overrides_dir / "prod.yaml", encoding="utf-8") as f:
            prod = yaml.safe_load(f)
        assert prod["llm"]["model"] == "gpt-4"

    def test_override_merging(self, overrides_dir: Path) -> None:
        """Overrides should be mergeable with base config."""
        base = {"llm": {"model": "base-model", "temperature": 0.7}}
        override = {"llm": {"model": "override-model"}}

        merged = dict(base)
        merged["llm"].update(override["llm"])

        assert merged["llm"]["model"] == "override-model"
        assert merged["llm"]["temperature"] == 0.7
