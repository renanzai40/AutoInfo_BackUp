"""Tests for the collection orchestrator and deduplication system.

Covers:
- DedupChecker URL exact match
- DedupChecker PMID/DOI match
- DedupChecker passes unique items
- run_collection dispatches to correct handlers
- run_collection dry-run returns estimates without storing
- run_collection error in one source continues others
- CLI collect command wires correctly
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import ANY, patch

import pytest
import yaml

from autoinfo.collect import _cache_items
from autoinfo.dedup import DedupChecker
from autoinfo.models import Item, KBEntry


# ======================================================================
# DedupChecker tests
# ======================================================================


class TestDedupChecker:
    """Verify dedup detection logic for URL, PMID, and DOI matching."""

    def make_entry(
        self,
        entry_id: str,
        source_url: str = "",
        pmid: str = "",
        doi: str = "",
    ) -> KBEntry:
        return KBEntry(
            entry_id=entry_id,
            title="Test Entry",
            domain="medical-research",
            source_url=source_url,
            custom_fields={"pmid": pmid, "doi": doi},
        )

    def make_item(
        self,
        item_id: str,
        source_url: str = "",
        pmid: str = "",
        doi: str = "",
    ) -> Item:
        return Item(
            id=item_id,
            source_name="pubmed",
            source_type="api",
            source_url=source_url,
            title="Test Item",
            content="Test content",
            collected_at="2026-07-20T00:00:00Z",
            raw_data={"pmid": pmid, "doi": doi},
        )

    # -- URL exact match ----------------------------------------------------

    def test_url_exact_match_detects_duplicate(self):
        """Items with identical source_url are flagged as duplicates."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="new-item",
            source_url="https://example.com/article/123",
        )
        existing = [
            self.make_entry(
                entry_id="existing-001",
                source_url="https://example.com/article/123",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is True
        assert result["matched_by"] == "url"
        assert result["existing_id"] == "existing-001"

    def test_url_exact_match_no_duplicate_when_different(self):
        """Items with different source_url are not flagged."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="new-item",
            source_url="https://example.com/article/456",
        )
        existing = [
            self.make_entry(
                entry_id="existing-001",
                source_url="https://example.com/article/123",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is False

    def test_url_empty_source_url_skips_url_check(self):
        """When item has no source_url, URL check is skipped gracefully."""
        checker = DedupChecker()
        item = self.make_item(item_id="new-item", source_url="")
        existing = [
            self.make_entry(
                entry_id="existing-001",
                source_url="https://example.com/article/123",
            ),
        ]

        result = checker.check(item, existing)
        # No URL match because item has no URL, but also no DOI/PMID match
        assert result["is_duplicate"] is False

    # -- PMID match ---------------------------------------------------------

    def test_pmid_match_detects_duplicate(self):
        """Items sharing the same PMID are flagged."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="new-item",
            source_url="https://example.com/different",
            pmid="98765432",
        )
        existing = [
            self.make_entry(
                entry_id="existing-pmid",
                source_url="https://example.com/other",
                pmid="98765432",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is True
        assert result["matched_by"] == "pmid"
        assert result["existing_id"] == "existing-pmid"

    def test_pmid_match_no_duplicate_when_different(self):
        """Items with different PMIDs are not flagged."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="new-item", source_url="", pmid="11111111"
        )
        existing = [
            self.make_entry(
                entry_id="existing-pmid",
                source_url="",
                pmid="22222222",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is False

    # -- DOI match ----------------------------------------------------------

    def test_doi_match_detects_duplicate(self):
        """Items sharing the same DOI are flagged."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="new-item",
            source_url="https://example.com/different",
            doi="10.1000/j.test.2026.01.001",
        )
        existing = [
            self.make_entry(
                entry_id="existing-doi",
                source_url="https://example.com/other",
                doi="10.1000/j.test.2026.01.001",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is True
        assert result["matched_by"] == "doi"
        assert result["existing_id"] == "existing-doi"

    # -- Unique items -------------------------------------------------------

    def test_unique_item_passes_through(self):
        """A genuinely unique item is not flagged as duplicate."""
        checker = DedupChecker()
        item = self.make_item(
            item_id="brand-new",
            source_url="https://example.com/unique-article",
            pmid="99999999",
            doi="10.1000/j.unique.2026.01.001",
        )
        existing = [
            self.make_entry(
                entry_id="existing-001",
                source_url="https://example.com/other",
                pmid="11111111",
                doi="10.1000/j.other.2026.01.001",
            ),
        ]

        result = checker.check(item, existing)
        assert result["is_duplicate"] is False
        assert result["matched_by"] == ""
        assert result["existing_id"] == ""

    def test_empty_existing_list_returns_unique(self):
        """When no existing entries are provided, the item is unique."""
        checker = DedupChecker()
        item = self.make_item(item_id="only-item", source_url="https://example.com/a")
        result = checker.check(item, [])
        assert result["is_duplicate"] is False

    # -- load_existing ------------------------------------------------------

    def test_load_existing_returns_empty_for_missing_dir(self, tmp_path):
        """load_existing returns [] when the domain directory doesn't exist."""
        checker = DedupChecker(knowledge_dir=str(tmp_path))
        entries = checker.load_existing("nonexistent-domain")
        assert entries == []

    def test_load_existing_parses_valid_kb_file(self, tmp_path):
        """load_existing correctly parses a Markdown file with YAML frontmatter."""
        kb_dir = tmp_path / "test-domain" / "01-Raw"
        kb_dir.mkdir(parents=True)

        entry_data = {
            "entry_id": "kb-from-file",
            "title": "Parsed Entry",
            "domain": "test-domain",
            "tier": "01-Raw",
            "source_url": "https://example.com/parsed",
            "source_type": "api",
            "source_platform": "pubmed",
            "collected_at": "2026-07-20T00:00:00Z",
            "custom_fields": {"pmid": "12345678"},
        }

        md_content = "---\n" + yaml.dump(entry_data) + "---\n\nBody content here.\n"
        (kb_dir / "test-entry.md").write_text(md_content, encoding="utf-8")

        checker = DedupChecker(knowledge_dir=str(tmp_path))
        entries = checker.load_existing("test-domain")

        assert len(entries) == 1
        assert entries[0].entry_id == "kb-from-file"
        assert entries[0].custom_fields["pmid"] == "12345678"

    def test_load_existing_skips_malformed_files(self, tmp_path):
        """load_existing skips files without valid YAML frontmatter."""
        kb_dir = tmp_path / "test-domain" / "01-Raw"
        kb_dir.mkdir(parents=True)

        # No frontmatter at all
        (kb_dir / "no-frontmatter.md").write_text("Just some text.\n", encoding="utf-8")

        checker = DedupChecker(knowledge_dir=str(tmp_path))
        entries = checker.load_existing("test-domain")
        assert len(entries) == 0


# ======================================================================
# run_collection orchestrator tests
# ======================================================================


class TestRunCollection:
    """Verify the orchestrator dispatches correctly and handles errors."""

    SAMPLE_CONFIG = {
        "project": {"name": "Test Project", "created_at": "2026-07-01"},
        "llm": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat",
            "api_key": "test-key",
        },
        "domains": [
            {
                "name": "medical-research",
                "active": True,
                "sources": [
                    {
                        "name": "pubmed",
                        "type": "api",
                        "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                        "quality_tier": 1,
                    },
                    {
                        "name": "nature-rss",
                        "type": "rss",
                        "url": "https://feeds.nature.com/nature/rss/current",
                        "quality_tier": 2,
                    },
                ],
                "topics": [{"name": "IVF breakthroughs", "keywords": ["IVF", "embryo"]}],
            },
        ],
    }

    @pytest.fixture
    def with_config(self, tmp_path: Path) -> Path:
        """Create a temporary project with a valid config."""
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as fh:
            yaml.dump(self.SAMPLE_CONFIG, fh, default_flow_style=False)
        return tmp_path

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_dispatches_to_correct_handlers(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """Orchestrator calls _build_handler which creates correct types."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        # Build a proper Config object matching SAMPLE_CONFIG
        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                        SourceConfig(name="nature-rss", type="rss", url="https://feeds.nature.com/nature/rss/current"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        # Patch _fetch_items to return empty lists (avoids real network calls)
        with patch("autoinfo.collect._fetch_items", return_value=[]) as mock_fetch:
            result = run_collection(
                domain="medical-research",
                topic="IVF",
                limit=5,
                dry_run=True,
            )

            # Should have fetched from both sources
            assert mock_fetch.call_count == 2
            # Should report 0 items since we mocked empty returns
            assert result["total_found"] == 0
            assert result["total_new"] == 0
            assert len(result["per_source"]) == 2

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_progress_cb_called_per_source(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """``progress_cb`` fires once per source, in order, with its result."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                        SourceConfig(name="nature-rss", type="rss", url="https://feeds.nature.com/nature/rss/current"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        seen: list[str] = []
        with patch("autoinfo.collect._fetch_items", return_value=[]):
            run_collection(
                domain="medical-research",
                dry_run=True,
                progress_cb=lambda r: seen.append(r.source),
            )

        assert seen == ["pubmed", "nature-rss"]

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_progress_cb_optional_when_none(self, mock_load_config, mock_get_config_path, with_config):
        """``progress_cb`` defaults to ``None`` — collection works unchanged."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items", return_value=[]):
            result = run_collection(domain="medical-research", dry_run=True)

        assert result["total_found"] == 0
        assert len(result["per_source"]) == 1

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_dry_run_returns_estimates_without_storage(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """dry_run=True returns estimates and does not cache anything."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        pubmed_item = Item(
            id="pmid-123",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/pmid123",
            title="PubMed Article",
            content="Abstract content...",
            collected_at="2026-07-20T00:00:00Z",
        )

        rss_item = Item(
            id="rss-001",
            source_name="nature-rss",
            source_type="rss",
            source_url="https://example.com/rss-item",
            title="RSS Item",
            content="RSS content...",
            collected_at="2026-07-20T00:00:00Z",
        )

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                        SourceConfig(name="nature-rss", type="rss", url="https://feeds.nature.com/nature/rss/current"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items") as mock_fetch:
            # Return 1 item for first source, 2 for second
            mock_fetch.side_effect = [[pubmed_item], [rss_item, rss_item]]

            # Also patch _cache_items to track whether it gets called
            with patch("autoinfo.collect._cache_items") as mock_cache:
                result = run_collection(
                    domain="medical-research",
                    topic="IVF",
                    limit=5,
                    dry_run=True,
                )

                # Should report correct counts
                assert result["total_found"] == 3
                assert result["total_new"] == 3
                assert result["dry_run"] is True

                # Should NOT have cached anything
                mock_cache.assert_not_called()

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_error_in_one_source_continues_others(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """When one source fails, other sources still get collected."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        rss_item = Item(
            id="rss-001",
            source_name="nature-rss",
            source_type="rss",
            source_url="https://example.com/rss-item",
            title="RSS Item",
            content="Content",
            collected_at="2026-07-20T00:00:00Z",
        )

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                        SourceConfig(name="nature-rss", type="rss", url="https://feeds.nature.com/nature/rss/current"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items") as mock_fetch:
            # First call raises, second call succeeds
            mock_fetch.side_effect = [Exception("PubMed down!"), [rss_item]]

            result = run_collection(
                domain="medical-research",
                topic="IVF",
                limit=5,
                dry_run=True,
            )

            # Should have 2 per_source results
            assert len(result["per_source"]) == 2

            # First source should be in error
            pubmed_result = result["per_source"][0]
            assert pubmed_result["status"] == "error"
            assert len(pubmed_result["errors"]) > 0
            assert "PubMed down" in pubmed_result["errors"][0]["message"]

            # Second source should have succeeded
            rss_result = result["per_source"][1]
            assert rss_result["status"] == "success"
            assert rss_result["items_found"] == 1

            # Total should reflect only successful source
            assert result["total_found"] == 1

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_caches_items_when_not_dry_run(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """Items are written to collections/ when dry_run=False."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        pubmed_item = Item(
            id="pmid-123",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/pmid123",
            title="PubMed Article",
            content="Abstract content...",
            collected_at="2026-07-20T00:00:00Z",
        )

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items", return_value=[pubmed_item]):
            with patch("autoinfo.collect._cache_items") as mock_cache:
                run_collection(
                    domain="medical-research",
                    topic="IVF",
                    limit=5,
                    dry_run=False,
                )

                # Should have called _cache_items with the new item
                mock_cache.assert_called_once()
                args, _ = mock_cache.call_args
                cached_items = args[0]
                assert len(cached_items) == 1
                assert cached_items[0].id == "pmid-123"

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_api_source_is_handled(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """Non-pubmed API sources are now handled by HttpApiHandler (previously skipped)."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(name="arxiv", type="api", url="https://export.arxiv.org/api/"),
                        SourceConfig(name="pubmed", type="api", url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items") as mock_fetch:
            mock_fetch.return_value = []

            result = run_collection(
                domain="medical-research",
                topic="IVF",
                limit=5,
                dry_run=True,
            )

            # Both sources should appear in per_source
            assert len(result["per_source"]) == 2

            # Both sources should be attempted (not skipped)
            # arxiv is now handled by HttpApiHandler
            arxiv_result = result["per_source"][0]
            assert arxiv_result["status"] == "success"

            # pubmed should also be attempted
            pubmed_result = result["per_source"][1]
            assert pubmed_result["status"] == "success"

    @patch("autoinfo.collect.get_config_path")
    @patch("autoinfo.collect.load_config")
    def test_propagates_source_quality_tier_to_items(
        self,
        mock_load_config,
        mock_get_config_path,
        with_config,
    ):
        """Items fetched from tier-3 sources get quality_tier=3 (Fix A — E9)."""
        from autoinfo.collect import run_collection
        from autoinfo.config import Config, DomainConfig, SourceConfig, ProjectConfig, LLMConfig

        pubmed_item = Item(
            id="pmid-456",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/pmid456",
            title="PubMed Tier3 Article",
            content="Abstract content...",
            collected_at="2026-07-20T00:00:00Z",
            quality_tier=1,  # default — _fetch_and_cache_source should override
        )

        config = Config(
            project=ProjectConfig(name="Test Project", created_at="2026-07-01"),
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat", api_key="test-key"),
            domains=[
                DomainConfig(
                    name="medical-research",
                    active=True,
                    sources=[
                        SourceConfig(
                            name="pubmed",
                            type="api",
                            url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                            quality_tier=3,
                        ),
                    ],
                    topics=[],
                ),
            ],
        )
        mock_get_config_path.return_value = with_config / ".autoinfo" / "config.yaml"
        mock_load_config.return_value = config

        with patch("autoinfo.collect._fetch_items") as mock_fetch:
            mock_fetch.return_value = [pubmed_item]

            run_collection(domain="medical-research", topic="IVF", limit=5, dry_run=True)

            # _fetch_and_cache_source should have set item.quality_tier
            # from source_config.quality_tier = 3
            assert pubmed_item.quality_tier == 3, (
                f"Expected quality_tier=3 from source_config, got {pubmed_item.quality_tier}"
            )
            assert pubmed_item.domain == "medical-research"


# ======================================================================
# CLI integration tests
# ======================================================================


class TestCollectCli:
    """Verify the CLI collect command wires to the orchestrator correctly."""

    @patch("autoinfo.collect.run_collection")
    def test_cli_calls_run_collection(self, mock_run_collection, cli_runner):
        """``autoinfo collect --domain X`` calls ``run_collection`` with correct args."""
        from autoinfo.cli.collect import app

        mock_run_collection.return_value = {
            "collection_id": "col-test",
            "domain": "medical-research",
            "total_found": 5,
            "total_new": 3,
            "duration_s": 1.23,
            "per_source": [],
            "dry_run": False,
        }

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--topic", "IVF", "--limit", "10"],
        )

        assert result.exit_code == 0
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="IVF",
            sources=None,
            limit=10,
            dry_run=False,
            progress_cb=ANY,
        )

    @patch("autoinfo.collect.run_collection")
    def test_cli_dry_run_flag(self, mock_run_collection, cli_runner):
        """``--dry-run`` is passed through to ``run_collection``."""
        from autoinfo.cli.collect import app

        mock_run_collection.return_value = {
            "collection_id": "col-dry",
            "domain": "medical-research",
            "total_found": 3,
            "total_new": 3,
            "duration_s": 0.5,
            "per_source": [],
            "dry_run": True,
        }

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--dry-run"],
        )

        assert result.exit_code == 0
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="",
            sources=None,
            limit=20,
            dry_run=True,
            progress_cb=ANY,
        )

    @patch("autoinfo.collect.run_collection")
    def test_cli_json_output(self, mock_run_collection, cli_runner):
        """``--json`` produces valid JSON output."""
        from autoinfo.cli.collect import app

        mock_run_collection.return_value = {
            "collection_id": "col-json",
            "domain": "medical-research",
            "total_found": 2,
            "total_new": 1,
            "duration_s": 0.3,
            "per_source": [
                {
                    "source": "pubmed",
                    "status": "success",
                    "items_found": 2,
                    "items_new": 1,
                    "errors": [],
                    "duration_s": 0.3,
                },
            ],
            "dry_run": False,
        }

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--json"],
        )

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["collection_id"] == "col-json"
        assert parsed["total_found"] == 2

    @patch("autoinfo.collect.run_collection")
    def test_cli_source_filter(self, mock_run_collection, cli_runner):
        """``--source`` filter is passed as a list to ``run_collection``."""
        from autoinfo.cli.collect import app

        mock_run_collection.return_value = {
            "collection_id": "col-src",
            "domain": "medical-research",
            "total_found": 0,
            "total_new": 0,
            "duration_s": 0.1,
            "per_source": [],
            "dry_run": False,
        }

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--source", "pubmed"],
        )

        assert result.exit_code == 0
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="",
            sources=["pubmed"],
            limit=20,
            dry_run=False,
            progress_cb=ANY,
        )

    def test_cli_no_config_error(self, cli_runner):
        """When no config exists, a friendly error is shown."""
        from autoinfo.cli.collect import app

        # Patch run_collection to raise FileNotFoundError (as it would without config)
        with patch(
            "autoinfo.collect.run_collection",
            side_effect=FileNotFoundError("No configuration found. Run 'autoinfo init' first."),
        ):
            result = cli_runner.invoke(
                app,
                ["--domain", "medical-research"],
            )

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "No configuration found" in result.output

    def test_cli_all_and_domain_conflict(self, cli_runner):
        """``--all`` and ``--domain`` together produce an error."""
        from autoinfo.cli.collect import app

        result = cli_runner.invoke(
            app,
            ["--all", "--domain", "medical-research"],
        )

        assert result.exit_code == 1
        assert "Cannot use --all with --domain" in result.output

    @patch.object(Path, "cwd")
    @patch("autoinfo.collect.run_collection")
    def test_cli_all_multi_domain_dispatch(
        self, mock_run_collection, mock_cwd, cli_runner, tmp_path,
    ):
        """``--all`` collects for all active domains in config."""
        import yaml
        from autoinfo.cli.collect import app
        from autoinfo.config import _dict_to_config

        # Point cwd to a temp dir so get_config_path finds the test config
        tmp = Path(tmp_path)
        mock_cwd.return_value = tmp
        config_dir = tmp / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"

        config_data = {
            "project": {"name": "test", "created_at": ""},
            "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
            "domains": [
                {"name": "domain-a", "active": True, "sources": [{"name": "src-a", "type": "rss", "url": "https://a.example.com/rss"}]},
                {"name": "domain-b", "active": True, "sources": [{"name": "src-b", "type": "rss", "url": "https://b.example.com/rss"}]},
            ],
        }
        config_path.write_text(yaml.dump(config_data))

        mock_result = {
            "collection_id": "col-test",
            "domain": "",
            "total_found": 5,
            "total_new": 3,
            "duration_s": 1.0,
            "per_source": [],
            "dry_run": False,
        }

        def side_effect(**kwargs):
            r = dict(mock_result)
            r["domain"] = kwargs["domain"]
            return r

        mock_run_collection.side_effect = side_effect

        result = cli_runner.invoke(
            app,
            ["--all", "--limit", "10", "--dry-run"],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert mock_run_collection.call_count == 2
        calls = [c[1] for c in mock_run_collection.call_args_list]
        domains_collected = [c["domain"] for c in calls]
        assert "domain-a" in domains_collected
        assert "domain-b" in domains_collected
        for c in calls:
            assert c["limit"] == 10
            assert c["dry_run"] is True


# ======================================================================
# _cache_items id handling (GitHub issue #104)
# ======================================================================


def _make_item(item_id) -> Item:
    return Item(
        id=item_id,
        source_name="gh-trending",
        source_type="api",
        source_url=f"https://example.com/{item_id}",
        title="Test Item",
        content="Test content",
    )


class TestCacheItemsIdHandling:
    def test_cache_items_accepts_int_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        item = _make_item(123456)
        _cache_items([item], "tech", "gh-trending")
        expected = (
            tmp_path
            / "collections"
            / "tech"
            / "gh-trending"
            / date.today().isoformat()
            / "123456.json"
        )
        assert expected.is_file()

    def test_cache_items_accepts_slash_in_str_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        item = _make_item("10.4103/2348-2907.142333")
        _cache_items([item], "tech", "gh-trending")
        expected = (
            tmp_path
            / "collections"
            / "tech"
            / "gh-trending"
            / date.today().isoformat()
            / "10.4103_2348-2907.142333.json"
        )
        assert expected.is_file()
