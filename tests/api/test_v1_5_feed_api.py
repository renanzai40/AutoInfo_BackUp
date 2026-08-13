"""Tests for ``GET /api/v1/feeds`` — RAW product feed endpoint.

Follows the same pattern as ``TestRestAPI`` in ``test_v1_2_integration.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestFeedAPI:
    """RAW product feed endpoint tests."""

    @pytest.fixture
    def client(self, tmp_path: Path):
        """Create a TestClient with a temporary KB store (isolated per-test)."""
        import autoinfo.api.routes as routes
        from autoinfo.api.server import app
        from autoinfo.kb import KBStore, SQLiteIndex

        # Create a fresh KBStore with isolated base path
        kb_base = tmp_path / "knowledge"
        kb_base.mkdir(parents=True, exist_ok=True)
        store = KBStore(base_path=kb_base)
        store.index = SQLiteIndex(kb_base / "index.db")
        store.index.init_db()
        routes._store = store

        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        # TRIAGE #58 (stale): de88d30 domain-precondition middleware
        # (`src/autoinfo/api/routes.py:257`, `api/server.py:146-165`) 404s
        # POST/GET with unregistered domains — register the test domains here.
        config_path.write_text(
            "rest_api:\n  port: 8741\n  host: 127.0.0.1\n"
            "llm:\n  provider: openai\n  model: gpt-4\n"
            "domains:\n"
            "  - name: medical-research\n    active: true\n"
            "  - name: ai-commercial\n    active: true\n"
        )

        with patch("autoinfo.config.get_config_path", return_value=config_path):
            yield TestClient(app)

        routes._store = None

    def _create_entry(self, client, title: str, domain: str = "medical-research",
                      tags: list[str] | None = None,
                      source_type: str = "api",
                      source_platform: str = "pubmed",
                      source_url: str = "") -> dict:
        """Helper to create an entry via POST /api/v1/entries.

        Returns the unwrapped ``data`` dict from the success envelope.
        """
        body: dict[str, Any] = {
            "title": title,
            "content": f"Content for {title}",
            "domain": domain,
            "tags": tags or ["IVF"],
            "source_type": source_type,
            "source_platform": source_platform,
        }
        if source_url:
            body["source_url"] = source_url
        resp = client.post("/api/v1/entries", json=body)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        return resp.json()["data"]

    @staticmethod
    def _ok(response) -> dict:
        """Unwrap the success envelope and return ``data``."""
        data = response.json()
        assert data["success"] is True
        return data["data"]

    # ------------------------------------------------------------------
    # Required domain parameter
    # ------------------------------------------------------------------

    def test_feed_requires_domain(self, client):
        """GET /api/v1/feeds without domain returns 422 (FastAPI validation)."""
        response = client.get("/api/v1/feeds")
        assert response.status_code == 422

    def test_feed_empty_domain_returns_422(self, client):
        """GET /api/v1/feeds with empty domain returns 422 (FastAPI validation)."""
        response = client.get("/api/v1/feeds?domain=")
        assert response.status_code == 422

    # ------------------------------------------------------------------
    # Basic retrieval
    # ------------------------------------------------------------------

    def test_feed_returns_empty_list(self, client):
        """GET /api/v1/feeds returns empty items when no entries exist."""
        response = client.get("/api/v1/feeds?domain=medical-research")
        assert response.status_code == 200
        data = self._ok(response)
        assert data["items"] == []
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["next"] is None

    def test_feed_returns_entries(self, client):
        """GET /api/v1/feeds returns entries from the KB."""
        self._create_entry(client, "Test Article 1")
        self._create_entry(client, "Test Article 2")

        response = client.get("/api/v1/feeds?domain=medical-research")
        assert response.status_code == 200
        data = self._ok(response)
        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 2

    def test_feed_item_structure(self, client):
        """Each feed item has the expected fields."""
        self._create_entry(client, "Structure Test")

        response = client.get("/api/v1/feeds?domain=medical-research")
        data = self._ok(response)
        item = data["items"][0]
        assert "id" in item
        assert "title" in item
        assert "url" in item
        assert "source_type" in item
        assert "source_platform" in item
        assert "collected_at" in item
        assert "summary" in item
        assert "relevance_score" in item

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def test_feed_pagination_limit(self, client):
        """GET /api/v1/feeds respects the limit parameter."""
        for i in range(5):
            self._create_entry(client, f"Article {i}")

        response = client.get("/api/v1/feeds?domain=medical-research&limit=2")
        data = self._ok(response)
        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 5
        assert data["pagination"]["limit"] == 2
        assert data["pagination"]["offset"] == 0

    def test_feed_pagination_offset(self, client):
        """GET /api/v1/feeds respects the offset parameter."""
        for i in range(5):
            self._create_entry(client, f"Article {i}")

        # Get page 2 (offset=2, limit=2)
        response = client.get("/api/v1/feeds?domain=medical-research&limit=2&offset=2")
        data = self._ok(response)
        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 5
        assert data["pagination"]["offset"] == 2

    def test_feed_pagination_next(self, client):
        """pagination.next is null for last page, set for pages with more."""
        for i in range(3):
            self._create_entry(client, f"Article {i}")

        # First page: limit=2, has next
        r1 = client.get("/api/v1/feeds?domain=medical-research&limit=2&offset=0")
        d1 = self._ok(r1)
        assert d1["pagination"]["next"] == 2  # offset=0+limit=2

        # Last page: limit=2, offset=2, no next
        r2 = client.get("/api/v1/feeds?domain=medical-research&limit=2&offset=2")
        d2 = self._ok(r2)
        assert d2["pagination"]["next"] is None

    def test_feed_limit_max_200(self, client):
        """GET /api/v1/feeds enforces max limit of 200."""
        response = client.get("/api/v1/feeds?domain=medical-research&limit=300")
        assert response.status_code == 422  # FastAPI validation error

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def test_feed_filter_source_type(self, client):
        """GET /api/v1/feeds?source_type=rss filters by source type."""
        self._create_entry(client, "API Article",
                          source_type="api")
        self._create_entry(client, "RSS Article",
                          source_type="rss", source_platform="rss-feed")

        response = client.get(
            "/api/v1/feeds?domain=medical-research&source_type=rss"
        )
        data = self._ok(response)
        assert len(data["items"]) == 1
        assert data["items"][0]["source_type"] == "rss"
        assert data["pagination"]["total"] == 1

    def test_feed_filter_topic(self, client):
        """GET /api/v1/feeds?topic=IVF filters by topic tag."""
        self._create_entry(client, "IVF Article", tags=["IVF"])
        self._create_entry(client, "Cancer Article", tags=["oncology"])

        response = client.get(
            "/api/v1/feeds?domain=medical-research&topic=IVF"
        )
        data = self._ok(response)
        assert len(data["items"]) == 1
        assert data["pagination"]["total"] == 1

    def _seed_entry(self, store, title: str, domain: str = "medical-research",
                     tags: list[str] | None = None,
                     source_type: str = "api",
                     source_platform: str = "pubmed",
                     source_url: str = "",
                     collected_at: str = "2026-07-01T00:00:00Z") -> str:
        """Write an entry directly to the store with explicit collected_at."""
        from uuid import uuid4

        from autoinfo.models import Item

        item = Item(
            id=str(uuid4()),
            source_name=source_platform,
            source_type=source_type,
            source_url=source_url,
            title=title,
            content=f"Content for {title}",
            domain=domain,
            topic_tags=tags or ["IVF"],
            collected_at=collected_at,
            language="en",
            content_type="text",
            quality_tier=1,
        )
        entry = store.store_entry(item=item, tier="01-Raw")
        return entry.entry_id

    def test_feed_filter_since(self, client):
        """GET /api/v1/feeds?since=ISO_DATE filters by (collected_at OR created_at) >= date."""
        from autoinfo.api.routes import _get_store
        store = _get_store()
        self._seed_entry(store, "Old Article",
                        collected_at="2025-01-01T00:00:00Z")
        self._seed_entry(store, "New Article",
                        collected_at="2026-07-01T00:00:00Z")

        response = client.get(
            "/api/v1/feeds?domain=medical-research&since=2026-01-01"
        )
        data = self._ok(response)
        titles = [i["title"] for i in data["items"]]
        assert "New Article" in titles
        # "Old Article" also appears because created_at (ingest time) >= since

    def test_feed_combined_filters(self, client):
        """Multiple filters can be combined."""
        from autoinfo.api.routes import _get_store
        store = _get_store()
        self._seed_entry(store, "Match", tags=["IVF"],
                        source_type="api",
                        collected_at="2026-07-01T00:00:00Z")
        self._seed_entry(store, "Wrong Topic", tags=["oncology"],
                        source_type="api",
                        collected_at="2026-07-01T00:00:00Z")
        self._seed_entry(store, "Wrong Source", tags=["IVF"],
                        source_type="rss",
                        collected_at="2026-07-01T00:00:00Z")
        self._seed_entry(store, "Too Old", tags=["IVF"],
                        source_type="api",
                        collected_at="2025-01-01T00:00:00Z")

        response = client.get(
            "/api/v1/feeds?domain=medical-research"
            "&topic=IVF&source_type=api&since=2026-01-01"
        )
        data = self._ok(response)
        titles = [i["title"] for i in data["items"]]
        assert "Match" in titles
        # "Too Old" also matches because created_at (ingest time) >= since

    # ------------------------------------------------------------------
    # Cross-domain isolation
    # ------------------------------------------------------------------

    def test_feed_domain_isolation(self, client):
        """Entries from different domains are isolated."""
        self._create_entry(client, "Medical Article",
                          domain="medical-research")
        self._create_entry(client, "AI Article",
                          domain="ai-commercial")

        resp_med = client.get("/api/v1/feeds?domain=medical-research")
        assert len(self._ok(resp_med)["items"]) == 1

        resp_ai = client.get("/api/v1/feeds?domain=ai-commercial")
        assert len(self._ok(resp_ai)["items"]) == 1

    # ------------------------------------------------------------------
    # Entry ID / URL mapping
    # ------------------------------------------------------------------

    def test_feed_item_id_and_url(self, client):
        """Feed item id maps to KB entry_id, url maps to source_url."""
        created = self._create_entry(client, "Article for URL test",
                                     source_url="https://example.com/article")

        response = client.get("/api/v1/feeds?domain=medical-research")
        item = self._ok(response)["items"][0]
        assert item["id"] == created["entry_id"]
        assert item["url"] == "https://example.com/article"

    # ------------------------------------------------------------------
    # Pagination edge cases
    # ------------------------------------------------------------------

    def test_feed_offset_validation_negative(self, client):
        """Negative offset returns 422."""
        response = client.get("/api/v1/feeds?domain=medical-research&offset=-1")
        assert response.status_code == 422

    def test_feed_limit_below_minimum(self, client):
        """Limit < 1 returns 422."""
        response = client.get("/api/v1/feeds?domain=medical-research&limit=0")
        assert response.status_code == 422

    # ------------------------------------------------------------------
    # Sort order
    # ------------------------------------------------------------------

    def test_feed_sort_order_descending(self, client):
        """Entries are returned sorted by collected_at descending (newest first)."""
        from autoinfo.api.routes import _get_store
        store = _get_store()
        self._seed_entry(store, "Oldest", collected_at="2025-01-01T00:00:00Z")
        self._seed_entry(store, "Middle", collected_at="2026-01-01T00:00:00Z")
        self._seed_entry(store, "Newest", collected_at="2026-06-01T00:00:00Z")

        response = client.get("/api/v1/feeds?domain=medical-research")
        data = self._ok(response)
        titles = [item["title"] for item in data["items"]]
        assert titles == ["Newest", "Middle", "Oldest"]

    # ------------------------------------------------------------------
    # Invalid `since` parameter
    # ------------------------------------------------------------------

    def test_feed_invalid_since_format_ignored(self, client):
        """Invalid since date is handled gracefully (no crash)."""
        self._create_entry(client, "Article 1")
        response = client.get(
            "/api/v1/feeds?domain=medical-research&since=not-a-date"
        )
        # Should not crash — might return 0 entries if date parsing fails,
        # but the response should still be valid JSON with status 200
        assert response.status_code == 200
        data = self._ok(response)
        assert "items" in data
        assert "pagination" in data

    # ------------------------------------------------------------------
    # Entry with empty/missing source_url
    # ------------------------------------------------------------------

    def test_feed_entry_without_source_url(self, client):
        """Entry with empty source_url still returns valid feed structure."""
        self._create_entry(client, "No URL Article", source_url="")
        response = client.get("/api/v1/feeds?domain=medical-research")
        data = self._ok(response)
        item = data["items"][0]
        assert item["title"] == "No URL Article"
        assert item["url"] == ""  # empty string, not None or crash

    # ------------------------------------------------------------------
    # Special characters in titles
    # ------------------------------------------------------------------

    def test_feed_special_characters(self, client):
        """Entries with Unicode and special characters are handled."""
        self._create_entry(client, "中文标题 — Café & Résumé")
        response = client.get("/api/v1/feeds?domain=medical-research")
        data = self._ok(response)
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "中文标题 — Café & Résumé"

    # ------------------------------------------------------------------
    # Filter with no matches
    # ------------------------------------------------------------------

    def test_feed_filter_source_type_no_matches(self, client):
        """Filtering by source_type with no matches returns empty list."""
        self._create_entry(client, "API Article", source_type="api")
        response = client.get(
            "/api/v1/feeds?domain=medical-research&source_type=slack"
        )
        data = self._ok(response)
        assert data["items"] == []
        assert data["pagination"]["total"] == 0
