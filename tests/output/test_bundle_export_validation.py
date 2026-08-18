"""Tests for issue #301: bundle export self-validation.

- Bundle with real entries → zip contains all required members, non-trivial size
- Bundle with zero entries → explicit empty-state warning in result
- Bundle with all entries filtered → same empty-state handling

TDD: these tests should fail (RED) before the fix, pass (GREEN) after.
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

_SAMPLE_CONFIG = {
    "project": {"name": "Test", "created_at": "2026-07-01"},
    "llm": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "api_key": "k"},
    "domains": [{"name": "medical-research", "active": True, "sources": [], "topics": []}],
}

_REQUIRED_BUNDLE_MEMBERS = {"data.json", "summary.md", "metadata.yaml"}


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / ".autoinfo"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text(yaml.dump(_SAMPLE_CONFIG))
    store = KBStore(base_path=tmp_path / "knowledge")
    store.store_entry(Item(
        id="m1", source_name="pubmed", source_type="api",
        source_url="https://pubmed.ncbi.nlm.nih.gov/111/",
        title="IVF breakthrough", content="Real medical content.",
        collected_at="2026-07-15T10:00:00Z", domain="medical-research", topic_tags=["IVF"],
    ))
    store.store_entry(Item(
        id="m2", source_name="pubmed", source_type="api",
        source_url="https://pubmed.ncbi.nlm.nih.gov/222/",
        title="Embryo selection", content="New techniques.",
        collected_at="2026-07-16T10:00:00Z", domain="medical-research", topic_tags=["IVF"],
    ))
    return tmp_path


@pytest.fixture
def empty_project_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / ".autoinfo"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text(yaml.dump(_SAMPLE_CONFIG))
    KBStore(base_path=tmp_path / "knowledge")
    return tmp_path


class TestBundleMembersValidation:
    """Bundle zip must contain all required member files."""

    def test_bundle_contains_required_members(self, project_dir: Path) -> None:
        with patch(
            "autoinfo.output.get_config_path",
            return_value=project_dir / ".autoinfo" / "config.yaml",
        ):
            result = export_kb(format="bundle")

        path = Path(result["path"])
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            for member in _REQUIRED_BUNDLE_MEMBERS:
                assert member in names, f"Required member '{member}' missing from bundle"

    def test_bundle_zip_nontrivial_size(self, project_dir: Path) -> None:
        """Bundle zip with entries should be >100 bytes."""
        with patch(
            "autoinfo.output.get_config_path",
            return_value=project_dir / ".autoinfo" / "config.yaml",
        ):
            result = export_kb(format="bundle")

        path = Path(result["path"])
        size = path.stat().st_size
        assert size > 100, (
            f"Bundle zip too small ({size} bytes) for {result['entries_count']} entries"
        )

    def test_bundle_no_empty_warning_when_entries_exist(self, project_dir: Path) -> None:
        """Bundle with real entries should not contain empty-state warning."""
        with patch(
            "autoinfo.output.get_config_path",
            return_value=project_dir / ".autoinfo" / "config.yaml",
        ):
            result = export_kb(format="bundle")

        assert result["entries_count"] >= 1
        warnings = result.get("warnings", [])
        assert not any("empty" in w.lower() for w in warnings), (
            f"Unexpected empty-state warning: {warnings}"
        )


class TestBundleEmptyState:
    """Bundle with zero entries should signal empty state explicitly."""

    def test_empty_entries_has_warning(self, empty_project_dir: Path) -> None:
        """Zero-entry bundle should include an empty-state warning."""
        with patch(
            "autoinfo.output.get_config_path",
            return_value=empty_project_dir / ".autoinfo" / "config.yaml",
        ):
            result = export_kb(format="bundle")

        assert result["entries_count"] == 0
        warnings = result.get("warnings", [])
        assert len(warnings) >= 1, "Expected at least one empty-state warning for zero entries"
        assert any("empty" in w.lower() or "no entries" in w.lower() for w in warnings), (
            f"Expected empty-state warning text, got: {warnings}"
        )

    def test_empty_entries_bundle_still_valid(self, empty_project_dir: Path) -> None:
        """Zero-entry bundle should still be a valid zip with required members."""
        with patch(
            "autoinfo.output.get_config_path",
            return_value=empty_project_dir / ".autoinfo" / "config.yaml",
        ):
            result = export_kb(format="bundle")

        path = Path(result["path"])
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            for member in _REQUIRED_BUNDLE_MEMBERS:
                assert member in names
            # data.json should be an empty array
            data = json.loads(zf.read("data.json"))
            assert data == []
