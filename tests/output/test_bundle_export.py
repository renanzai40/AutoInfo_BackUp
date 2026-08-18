"""Tests for multi-format bundle export (format=bundle).

Covers:
    - Bundle ZIP contains correct files (data.json, summary.md, metadata.yaml)
    - Each format inside the bundle is independently valid
    - Empty domain produces a valid (low-count) bundle
    - Result metadata includes 'formats' key
    - Format validation: 'bundle' is accepted, invalid formats raise ValueError
    - Single-entry bundle works correctly
    - Graceful PDF skip when weasyprint is unavailable
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from autoinfo.kb import KBStore
from autoinfo.models import Item
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
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with config and some KB entries."""
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(_SAMPLE_CONFIG, fh, default_flow_style=False)

    store = KBStore(base_path=tmp_path / "knowledge")

    store.store_entry(
        Item(
            id="med-1",
            source_name="pubmed",
            source_type="api",
            source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
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
            source_url="https://pubmed.ncbi.nlm.nih.gov/87654321/",
            title="Embryo selection advances",
            content="New embryo selection techniques.",
            collected_at="2026-07-16T10:00:00Z",
            domain="medical-research",
            topic_tags=["IVF"],
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

    KBStore(base_path=tmp_path / "knowledge")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: bundle generation
# ---------------------------------------------------------------------------


class TestBundleGeneration:
    def test_bundle_contains_correct_files(self, project_dir: Path) -> None:
        """Bundle ZIP should contain data.json, summary.md, and metadata.yaml."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        assert result["format"] == "bundle"
        assert result["success"] is True
        path = Path(result["path"])
        assert path.exists()
        assert path.name.endswith(".zip")

        # Verify ZIP contents
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            assert "data.json" in names
            assert "summary.md" in names
            assert "metadata.yaml" in names

    def test_json_format_is_valid(self, project_dir: Path) -> None:
        """The data.json inside the bundle should be valid JSON."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        with zipfile.ZipFile(result["path"], "r") as zf:
            json_bytes = zf.read("data.json")
            data = json.loads(json_bytes)
            assert isinstance(data, list)
            assert len(data) == result["entries_count"]
            for entry in data:
                assert "title" in entry
                assert "entry_id" in entry
                assert "source_url" in entry

    def test_markdown_format_is_valid(self, project_dir: Path) -> None:
        """The summary.md inside the bundle should contain entry titles."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        with zipfile.ZipFile(result["path"], "r") as zf:
            md_content = zf.read("summary.md").decode("utf-8")
            assert "IVF breakthrough study" in md_content
            assert "Embryo selection advances" in md_content
            assert md_content.startswith("#")  # starts with heading

    def test_metadata_yaml_is_valid(self, project_dir: Path) -> None:
        """The metadata.yaml should contain expected fields."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        with zipfile.ZipFile(result["path"], "r") as zf:
            yaml_bytes = zf.read("metadata.yaml")
            meta = yaml.safe_load(yaml_bytes)
            assert meta["domain"] == "*"
            assert meta["entry_count"] == result["entries_count"]
            assert "formats_included" in meta
            assert "generated_at" in meta
            assert meta["export_version"] == "1.0"
            assert meta["generator"] == "AutoInfo"

    def test_empty_domain(self, empty_project_dir: Path) -> None:
        """Empty domain should produce a valid bundle with 0 entries."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = empty_project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        assert result["entries_count"] == 0
        assert result["success"] is True

        with zipfile.ZipFile(result["path"], "r") as zf:
            names = zf.namelist()
            assert "data.json" in names
            # data.json should be an empty array
            json_bytes = zf.read("data.json")
            data = json.loads(json_bytes)
            assert data == []
            # metadata.yaml should have entry_count 0
            yaml_bytes = zf.read("metadata.yaml")
            meta = yaml.safe_load(yaml_bytes)
            assert meta["entry_count"] == 0

    def test_single_entry(self, empty_project_dir: Path) -> None:
        """A single-entry KB should export correctly."""
        # Add just one entry
        store = KBStore(base_path=empty_project_dir / "knowledge")
        store.store_entry(
            Item(
                id="single-1",
                source_name="pubmed",
                source_type="api",
                source_url="https://pubmed.ncbi.nlm.nih.gov/87654322/",
                title="Single entry test",
                content="This is a single entry.",
                collected_at="2026-07-20T10:00:00Z",
                domain="medical-research",
                topic_tags=["test"],
            )
        )

        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = empty_project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        assert result["entries_count"] == 1

        with zipfile.ZipFile(result["path"], "r") as zf:
            md_content = zf.read("summary.md").decode("utf-8")
            assert "Single entry test" in md_content

    def test_result_contains_formats_key(self, project_dir: Path) -> None:
        """Result dict should include 'formats' key listing included formats."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")

        assert "formats" in result
        assert isinstance(result["formats"], list)
        # At minimum: json, md, yaml
        assert "json" in result["formats"]
        assert "md" in result["formats"]
        assert "yaml" in result["formats"]

    def test_domain_filter(self, project_dir: Path) -> None:
        """Domain filter should scope the bundle correctly."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(domain="medical-research", format="bundle")

        assert result["domain"] == "medical-research"
        assert result["entries_count"] == 2


class TestBundleFormatValidation:
    def test_bundle_is_accepted(self, project_dir: Path) -> None:
        """'bundle' format should be accepted without error."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            result = export_kb(format="bundle")
        assert result["format"] == "bundle"

    def test_invalid_format_raises(self, project_dir: Path) -> None:
        """Invalid format should raise ValueError."""
        with patch("autoinfo.output.get_config_path") as mock_cfg:
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            with pytest.raises(ValueError, match="Unsupported export format"):
                export_kb(format="docx")


class TestBundlePdfGracefulSkip:
    def test_pdf_skipped_when_weasyprint_unavailable(
        self, project_dir: Path
    ) -> None:
        """When weasyprint is not importable, PDF is skipped gracefully."""
        with (
            patch("autoinfo.output.get_config_path") as mock_cfg,
            patch("autoinfo.output._build_bundle_pdf") as mock_pdf,
        ):
            mock_cfg.return_value = project_dir / ".autoinfo" / "config.yaml"
            mock_pdf.side_effect = ValueError("weasyprint not available")
            result = export_kb(format="bundle")

        assert result["success"] is True
        assert "pdf" not in result["formats"]
        assert "warning" in result  # warning message about PDF skip
