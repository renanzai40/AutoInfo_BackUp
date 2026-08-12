"""Tests for the KB export functionality (autoinfo.output.export_kb).

Covers:
    - Markdown export creates a valid tar.gz with .md files
    - JSON export produces a valid JSON array with entry content
    - SQLite export copies the database
    - Domain filter scopes export correctly
    - Empty KB exports gracefully (zero entries)
    - Invalid format raises ValueError
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from jsonschema import Draft7Validator

from autoinfo.kb import KBStore, SQLiteIndex
from autoinfo.models import Item, KBEntry
from autoinfo.output import export_kb

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
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
            "sources": [],
            "topics": [{"name": "IVF breakthroughs", "keywords": ["IVF"]}],
        },
        {
            "name": "ai-commercial",
            "active": True,
            "sources": [],
            "topics": [{"name": "LLM", "keywords": ["LLM"]}],
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with config and some KB entries."""
    # --- Config ---
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_SAMPLE_CONFIG, fh, default_flow_style=False)

    # --- KBStore (creates knowledge/ + autoinfo.db) ---
    store = KBStore(base_path=tmp_path / "knowledge")

    # Add entries for medical-research
    store.store_entry(
        Item(
            id="med-1",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/med1",
            title="IVF breakthrough study",
            content="Medical content about IVF breakthroughs.",
            collected_at="2026-07-15T10:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
        )
    )
    store.store_entry(
        Item(
            id="med-2",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/med2",
            title="Embryo selection advances",
            content="New embryo selection techniques.",
            collected_at="2026-07-16T10:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
        )
    )

    # Add entries for ai-commercial
    store.store_entry(
        Item(
            id="ai-1",
            source_name="arxiv",
            source_type="api",
            source_url="https://example.com/ai1",
            title="GPT-5 architecture paper",
            content="AI content about GPT-5.",
            collected_at="2026-07-15T11:00:00Z",
            domain="ai-commercial",
            topic_tags=["LLM"],
        )
    )

    return tmp_path


@pytest.fixture
def empty_project_dir(tmp_path: Path) -> Path:
    """Create a project with config but no KB entries."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_SAMPLE_CONFIG, fh, default_flow_style=False)

    # Initialize KB with empty SQLite DB (no entries stored)
    KBStore(base_path=tmp_path / "knowledge")

    return tmp_path


# ---------------------------------------------------------------------------
# Tests: markdown export
# ---------------------------------------------------------------------------


class TestMarkdownExport:
    def test_creates_tar_gz(self, project_dir: Path) -> None:
        """Markdown export produces a .tar.gz file."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="markdown")

        assert result["format"] == "markdown"
        assert result["success"] is True
        path = Path(result["path"])
        assert path.exists()
        assert path.name.endswith(".tar.gz")

    def test_tar_gz_contains_md_files(self, project_dir: Path) -> None:
        """The tar.gz archive contains .md files with correct content."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="markdown")

        archive_path = Path(result["path"])
        with tarfile.open(str(archive_path), "r:gz") as tar:
            members = tar.getnames()
            # Should contain all .md files
            md_members = [m for m in members if m.endswith(".md")]
            assert len(md_members) == 3  # med-1, med-2, ai-1

            # Verify paths are relative to knowledge/
            for md in md_members:
                assert md.startswith("medical-research/") or md.startswith("ai-commercial/")
                assert "01-Raw" in md

    def test_domain_filter(self, project_dir: Path) -> None:
        """Domain filter only includes entries from that domain."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(domain="medical-research", format="markdown")

        archive_path = Path(result["path"])
        with tarfile.open(str(archive_path), "r:gz") as tar:
            md_members = [m for m in tar.getnames() if m.endswith(".md")]
            assert len(md_members) == 2
            assert all(m.startswith("medical-research/") for m in md_members)


# ---------------------------------------------------------------------------
# Tests: JSON export
# ---------------------------------------------------------------------------


class TestJsonExport:
    def test_creates_json_file(self, project_dir: Path) -> None:
        """JSON export produces a .json file."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        assert result["format"] == "json"
        assert result["success"] is True
        path = Path(result["path"])
        assert path.exists()
        assert path.suffix == ".json"

    def test_valid_json_array(self, project_dir: Path) -> None:
        """File content parses as a JSON array of entry objects."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 3

        # Check required keys in each entry
        for entry in data:
            assert "entry_id" in entry
            assert "title" in entry
            assert "domain" in entry
            assert "source_url" in entry
            assert "content" in entry
            assert "tags" in entry

    def test_content_included(self, project_dir: Path) -> None:
        """Entry content (file body) is included in JSON."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        # The medical entry should have its content
        med_entries = [e for e in data if e["domain"] == "medical-research"]
        assert len(med_entries) == 2
        assert any("IVF breakthrough" in e["title"] for e in med_entries)

        # Content should include the body text
        for e in med_entries:
            assert len(e["content"]) > 0

    def test_domain_filter(self, project_dir: Path) -> None:
        """Domain filter only exports entries from that domain."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(domain="ai-commercial", format="json")

        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["domain"] == "ai-commercial"
        assert data[0]["title"] == "GPT-5 architecture paper"


# ---------------------------------------------------------------------------
# Tests: SQLite export
# ---------------------------------------------------------------------------


class TestSQLiteExport:
    def test_creates_db_file(self, project_dir: Path) -> None:
        """SQLite export produces a .db file."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="sqlite")

        assert result["format"] == "sqlite"
        assert result["success"] is True
        path = Path(result["path"])
        assert path.exists()
        assert path.suffix == ".db"

    def test_full_db_copy_contains_all_entries(self, project_dir: Path) -> None:
        """Full (no domain) SQLite export copies all entries."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="sqlite")

        db_path = Path(result["path"])
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        assert count == 3

    def test_domain_filter(self, project_dir: Path) -> None:
        """Domain filter only exports matching entries in SQLite copy."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(domain="medical-research", format="sqlite")

        db_path = Path(result["path"])
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        domains = conn.execute("SELECT DISTINCT domain FROM entries").fetchall()
        conn.close()
        assert count == 2
        assert all(d[0] == "medical-research" for d in domains)


# ---------------------------------------------------------------------------
# Tests: empty KB
# ---------------------------------------------------------------------------


class TestEmptyKB:
    def test_markdown(self, empty_project_dir: Path) -> None:
        """Empty KB markdown export produces tar.gz with zero entries."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = empty_project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="markdown")

        assert result["success"] is True
        assert result["entries_count"] == 0
        path = Path(result["path"])
        assert path.exists()
        with tarfile.open(str(path), "r:gz") as tar:
            assert len(tar.getnames()) == 0

    def test_json(self, empty_project_dir: Path) -> None:
        """Empty KB JSON export produces an empty JSON array."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = empty_project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert result["entries_count"] == 0
        assert data == []

    def test_sqlite(self, empty_project_dir: Path) -> None:
        """Empty KB SQLite export creates a DB with zero entries."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = empty_project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="sqlite")

        db_path = Path(result["path"])
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        assert result["entries_count"] == 0
        assert count == 0


# ---------------------------------------------------------------------------
# Tests: invalid format / missing config
# ---------------------------------------------------------------------------


class TestErrors:
    def test_invalid_format(self, project_dir: Path) -> None:
        """Invalid format raises ValueError."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            with pytest.raises(ValueError, match="Unsupported export format"):
                export_kb(format="docx")

    def test_invalid_format_pdf(self, project_dir: Path) -> None:
        """Invalid format raises ValueError."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            with pytest.raises(ValueError, match="Unsupported export format"):
                export_kb(format="xml")

    def test_missing_config_raises(self) -> None:
        """Without config, export raises FileNotFoundError."""
        with patch("autoinfo.output.get_config_path", return_value=None):
            with pytest.raises(FileNotFoundError, match="No configuration"):
                export_kb(format="json")

    def test_no_config_file_on_disk(self, tmp_path: Path) -> None:
        """No config file at all raises FileNotFoundError."""
        # Point to a non-existent config
        fake_config = tmp_path / ".autoinfo" / "config.yaml"
        with patch("autoinfo.output.get_config_path", return_value=fake_config):
            with pytest.raises(FileNotFoundError, match="No configuration"):
                export_kb(format="json")


# ---------------------------------------------------------------------------
# Tests: returns correct metadata
# ---------------------------------------------------------------------------


class TestResultMetadata:
    def test_result_contains_expected_keys(self, project_dir: Path) -> None:
        """Result dict has all expected metadata fields."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="markdown")

        assert "format" in result
        assert "path" in result
        assert "entries_count" in result
        assert "domain" in result
        assert "success" in result
        assert "collection_id" in result

    def test_domain_label_all(self, project_dir: Path) -> None:
        """Without domain filter, domain label is '*'."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        assert result["domain"] == "*"

    def test_domain_label_filtered(self, project_dir: Path) -> None:
        """With domain filter, domain label matches input."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(domain="medical-research", format="json")

        assert result["domain"] == "medical-research"


# ---------------------------------------------------------------------------
# Tests: agent-native JSON-LD export (B-004: tags as real JSON arrays)
# ---------------------------------------------------------------------------


class TestAgentExport:
    def test_tags_are_real_arrays(self, project_dir: Path) -> None:
        """Agent export emits tags as JSON arrays, not JSON-encoded strings."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="agent")

        assert result["success"] is True
        assert len(result["entries"]) == 3
        for entry in result["entries"]:
            assert isinstance(entry["tags"], list), (
                f"tags must be a JSON array, got {type(entry['tags']).__name__}: {entry['tags']!r}"
            )
            assert all(isinstance(t, str) for t in entry["tags"])
            assert entry["tags"] in (["IVF"], ["LLM"])

    def test_json_export_tags_are_real_arrays(self, project_dir: Path) -> None:
        """JSON export also emits tags as real arrays (not strings)."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="json")

        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert len(data) == 3
        for entry in data:
            assert isinstance(entry["tags"], list), (
                f"tags must be a JSON array, got {type(entry['tags']).__name__}: {entry['tags']!r}"
            )
            assert all(isinstance(t, str) for t in entry["tags"])

    def test_validates_against_kb_export_schema(self, project_dir: Path) -> None:
        """Agent export validates against docs/schemas/knowledge-base-export-v1.json."""
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "schemas"
            / "knowledge-base-export-v1.json"
        )
        assert schema_path.is_file(), f"schema file missing: {schema_path}"

        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="agent")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)
        errors = sorted(
            (f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(result)),
        )
        assert errors == [], "agent export failed schema validation:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Tests: sitemap export requires explicit base_url (B-002)
# ---------------------------------------------------------------------------


class TestSitemapBaseUrl:
    def test_sitemap_requires_explicit_base_url(self, project_dir: Path) -> None:
        """export_kb(format='sitemap') without base_url raises an actionable error."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            with pytest.raises(ValueError, match="requires an explicit base_url"):
                export_kb(domain="medical-research", format="sitemap")

    def test_sitemap_index_loc_uses_explicit_base_url(self, project_dir: Path) -> None:
        """Sitemap index page uses the provided base_url, not a placeholder."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(
                domain="medical-research",
                format="sitemap",
                base_url="https://kb.your-site.example",
            )

        assert result["success"] is True
        tree = ET.parse(result["path"])
        root = tree.getroot()
        ns = {"sm": "https://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = root.findall("sm:url", ns)
        index_loc = urls[-1].find("sm:loc", ns).text
        assert index_loc == "https://kb.your-site.example"
