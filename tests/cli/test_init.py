"""Tests for ``autoinfo init`` multi-domain behavior (issue #100).

Regression coverage: when ``init --demo A --demo B`` is run with multiple
domains, *all* domains must be embedded in ``config.yaml`` (the single
source of truth) and no misleading standalone ``sources.yaml`` may be
written (it previously only reflected the first domain).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.cli.init import _run_init


@pytest.fixture
def autoinfo_dir(tmp_path: Path) -> Path:
    return tmp_path / ".autoinfo"


def _read_config(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"config.yaml not created at {path}"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"config.yaml parsed to {type(data).__name__}"
    return data


class TestMultiDomainInit:
    """``_run_init`` with multiple domains (issue #100)."""

    def test_config_embeds_all_domains(
        self, autoinfo_dir: Path
    ) -> None:
        """config.yaml must contain sources/topics for EVERY requested domain."""
        _run_init(["medical-research", "ai-commercial"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        domain_names = [d["name"] for d in data["domains"]]
        assert domain_names == ["medical-research", "ai-commercial"]

        # Both domains must carry their sources inline in config.yaml
        for d in data["domains"]:
            assert d["sources"], f"domain {d['name']!r} has no sources in config"

    def test_no_misleading_standalone_sources_yaml(
        self, autoinfo_dir: Path
    ) -> None:
        """No standalone sources.yaml — config.yaml is the single source of truth."""
        _run_init(["medical-research", "ai-commercial"], autoinfo_dir)

        assert not (autoinfo_dir / "sources.yaml").exists(), (
            "standalone sources.yaml must not be created: with multiple domains "
            "it only reflected the first domain (issue #100)"
        )

    def test_config_embeds_all_domains_sources(
        self, autoinfo_dir: Path
    ) -> None:
        """Sources for the 2nd domain must not be lost."""
        _run_init(["medical-research", "ai-commercial"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        ai_commercial = next(
            d for d in data["domains"] if d["name"] == "ai-commercial"
        )
        source_names = [s["name"].lower() for s in ai_commercial["sources"]]
        assert any("techcrunch" in n for n in source_names), (
            f"ai-commercial sources missing from config: {source_names}"
        )


class TestInitDirLayout:
    """Regression: runtime dirs must be at project root, NOT under .autoinfo/ (issue #106)."""

    def test_runtime_dirs_at_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fresh init creates knowledge/, collections/, outputs/ at project root.

        Only config.yaml stays in .autoinfo/.
        """
        monkeypatch.chdir(tmp_path)
        autoinfo_dir = tmp_path / ".autoinfo"
        _run_init(["medical-research"], autoinfo_dir)

        # Runtime dirs MUST be at project root
        assert (tmp_path / "collections").is_dir(), "collections/ must be at project root"
        assert (tmp_path / "knowledge" / "01-Raw").is_dir(), (
            "knowledge/01-Raw must be at project root"
        )
        assert (tmp_path / "knowledge" / "02-Draft").is_dir(), (
            "knowledge/02-Draft must be at project root"
        )
        assert (tmp_path / "knowledge" / "03-Wiki").is_dir(), (
            "knowledge/03-Wiki must be at project root"
        )
        assert (tmp_path / "outputs").is_dir(), "outputs/ must be at project root"

        # Runtime dirs must NOT be under .autoinfo/
        assert not (autoinfo_dir / "collections").exists(), (
            "collections/ must NOT be under .autoinfo/"
        )
        assert not (autoinfo_dir / "knowledge").exists(), (
            "knowledge/ must NOT be under .autoinfo/"
        )
        assert not (autoinfo_dir / "outputs").exists(), (
            "outputs/ must NOT be under .autoinfo/"
        )

    def test_autoinfo_dir_only_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """.autoinfo/ should only contain config.yaml (no runtime data)."""
        monkeypatch.chdir(tmp_path)
        autoinfo_dir = tmp_path / ".autoinfo"
        _run_init(["medical-research"], autoinfo_dir)

        assert autoinfo_dir.is_dir(), ".autoinfo/ must exist"
        assert (autoinfo_dir / "config.yaml").is_file(), (
            "config.yaml must exist in .autoinfo/"
        )
        # No runtime directories under .autoinfo/
        for sub in ["knowledge", "collections", "outputs"]:
            assert not (autoinfo_dir / sub).exists(), (
                f".autoinfo/{sub}/ must NOT exist (runtime dir goes to root)"
            )


class TestSingleDomainInit:
    """Single-domain init must keep working (no regression)."""

    def test_config_created(self, autoinfo_dir: Path) -> None:
        _run_init(["medical-research"], autoinfo_dir)
        data = _read_config(autoinfo_dir / "config.yaml")
        assert [d["name"] for d in data["domains"]] == ["medical-research"]

    def test_no_standalone_sources_yaml_single_domain(
        self, autoinfo_dir: Path
    ) -> None:
        """sources.yaml removed even for single-domain init (consistency)."""
        _run_init(["medical-research"], autoinfo_dir)
        assert not (autoinfo_dir / "sources.yaml").exists()


class TestInitMergeBackfill:
    """Issue #319: init --demo backfills exclude_keywords for existing domains."""

    def test_init_merge_backfills_exclude_keywords(
        self, autoinfo_dir: Path
    ) -> None:
        """An existing ai-commercial domain lacking exclude_keywords gets the
        demo-seed value backfilled (additive only)."""
        autoinfo_dir.mkdir(parents=True)
        cfg = {
            "project": {"name": "test"},
            "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
            "domains": [
                {
                    "name": "ai-commercial",
                    "active": True,
                    "sources": [
                        {
                            "name": "techcrunch",
                            "type": "rss",
                            "url": "https://techcrunch.com/feed/",
                        }
                    ],
                    "topics": [],
                }
            ],
        }
        (autoinfo_dir / "config.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        _run_init(["ai-commercial"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        ai = next(d for d in data["domains"] if d["name"] == "ai-commercial")
        # #319: the ai-commercial seed now carries the full noise set.
        got = ai["exclude_keywords"]
        for term in ("贝达药业", "DURAVYU", "华能", "株冶", "平安好医生",
                     "SEC 8-K", "10-Q", "财报", "年报"):
            assert term in got, f"init backfill missing {term!r}: {got}"

    def test_init_merge_never_overwrites_present_exclude_keywords(
        self, autoinfo_dir: Path
    ) -> None:
        """A present exclude_keywords value is never overwritten by the seed."""
        autoinfo_dir.mkdir(parents=True)
        cfg = {
            "project": {"name": "test"},
            "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
            "domains": [
                {
                    "name": "ai-commercial",
                    "active": True,
                    "sources": [
                        {
                            "name": "techcrunch",
                            "type": "rss",
                            "url": "https://techcrunch.com/feed/",
                        }
                    ],
                    "topics": [],
                    "exclude_keywords": ["custom-term"],
                }
            ],
        }
        (autoinfo_dir / "config.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        _run_init(["ai-commercial"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        ai = next(d for d in data["domains"] if d["name"] == "ai-commercial")
        assert ai["exclude_keywords"] == ["custom-term"]


def _demo_extract_fields(domain: str) -> list[str]:
    """Read ``extract_fields`` from the bundled demo domain sources.yaml."""
    demo_yaml = (
        Path(__file__).resolve().parents[2]
        / "src" / "autoinfo" / "data" / "domains" / domain / "sources.yaml"
    )
    assert demo_yaml.is_file(), f"demo sources.yaml missing: {demo_yaml}"
    data = yaml.safe_load(demo_yaml.read_text()) or {}
    fields = data.get("extract_fields", [])
    assert fields, f"demo domain {domain!r} carries no extract_fields seed"
    return list(fields)


class TestInitExtractFields:
    """init --demo must persist extract_fields (parity with domain import --from-demo).

    ``domain import --from-demo`` and ``domain init --seed`` both write the demo
    domain's ``extract_fields`` into the project config; ``init --demo`` skipped
    the key, so a user onboarded via init --demo got the domain WITHOUT its
    extraction schema. Both fresh-create and merge branches must propagate it.
    """

    def test_fresh_init_persists_extract_fields_medical_research(
        self, autoinfo_dir: Path
    ) -> None:
        _run_init(["medical-research"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        med = next(d for d in data["domains"] if d["name"] == "medical-research")
        assert med["extract_fields"] == _demo_extract_fields("medical-research")
        assert len(med["extract_fields"]) == 7

    def test_fresh_init_persists_extract_fields_financial_intelligence(
        self, autoinfo_dir: Path
    ) -> None:
        _run_init(["financial-intelligence"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        fin = next(
            d for d in data["domains"] if d["name"] == "financial-intelligence"
        )
        assert fin["extract_fields"] == _demo_extract_fields(
            "financial-intelligence"
        )

    def test_merge_branch_persists_extract_fields_for_new_domain(
        self, autoinfo_dir: Path
    ) -> None:
        """Second init on an existing project adds the domain with extract_fields."""
        _run_init(["medical-research"], autoinfo_dir)
        _run_init(["financial-intelligence"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        names = [d["name"] for d in data["domains"]]
        assert names == ["medical-research", "financial-intelligence"]
        fin = next(d for d in data["domains"] if d["name"] == "financial-intelligence")
        assert fin["extract_fields"] == _demo_extract_fields("financial-intelligence")

    def test_merge_branch_backfills_missing_extract_fields(
        self, autoinfo_dir: Path
    ) -> None:
        """An existing domain created by older init (no extract_fields) is
        backfilled additively — present values are never overwritten."""
        autoinfo_dir.mkdir(parents=True)
        cfg = {
            "project": {"name": "test"},
            "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
            "domains": [
                {
                    "name": "medical-research",
                    "active": True,
                    "sources": [
                        {
                            "name": "pubmed",
                            "type": "api",
                            "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                        }
                    ],
                    "topics": [],
                }
            ],
        }
        (autoinfo_dir / "config.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        _run_init(["medical-research"], autoinfo_dir)

        data = _read_config(autoinfo_dir / "config.yaml")
        med = next(d for d in data["domains"] if d["name"] == "medical-research")
        assert med["extract_fields"] == _demo_extract_fields("medical-research")
        # untouched pre-existing keys survive the backfill
        assert med["topics"] == []
        assert med["sources"][0]["name"] == "pubmed"
