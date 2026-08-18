"""Tests for scripts/merge_demo_domains.py.

Regression #291: when a target domain ALREADY exists in the config, the script
used to skip it entirely (``if dname in existing: continue``), so new
sources/topics from the demo domain's sources.yaml were never merged into the
existing block. These tests lock the fix: existing-domain merges add missing
sources/topics, skip already-present ones, preserve existing config, and
report merges under --dry-run — while the add-new-domain path stays unchanged.

All tests are hermetic: they point the script at a temp config + temp domains
dir via --config / --domains-dir, so no real .autoinfo/config.yaml is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# scripts/ is not a package — load it via sys.path like the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import merge_demo_domains as merger  # noqa: E402


def _dump(path: Path, data: object) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Temp config with an existing ``demo-domain`` block plus a demo
    sources.yaml carrying one already-present source and one new source/topic.

    Returns (config_path, domains_dir).
    """
    config_path = tmp_path / ".autoinfo" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    _dump(
        config_path,
        {
            "project": {"name": "test"},
            "domains": [
                {
                    "name": "demo-domain",
                    "active": True,
                    "sources": [
                        {
                            "name": "existing-src",
                            "type": "rss",
                            "url": "https://existing.example/rss",
                        }
                    ],
                    "topics": [{"name": "Existing Topic", "keywords": ["existing"]}],
                }
            ],
        },
    )

    domains_dir = tmp_path / "domains"
    ddir = domains_dir / "demo-domain"
    ddir.mkdir(parents=True)
    _dump(
        ddir / "sources.yaml",
        {
            "name": "demo-domain",
            "sources": [
                {
                    "name": "existing-src",
                    "type": "rss",
                    "url": "https://existing.example/rss",
                },
                {"name": "new-src", "type": "api", "url": "https://new.example/api"},
            ],
            "topics": [
                {"name": "Existing Topic", "keywords": ["existing"]},
                {"name": "New Topic", "keywords": ["new"]},
            ],
        },
    )
    return config_path, domains_dir


def _run(config_path: Path, domains_dir: Path, *extra: str) -> int:
    return merger.main(
        ["--config", str(config_path), "--domains-dir", str(domains_dir), *extra]
    )


def _demo_block(cfg: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in cfg["domains"] if d["name"] == "demo-domain")


def test_existing_domain_merges_missing_source(tmp_path: Path) -> None:
    """#291: a source present in sources.yaml but missing from the existing
    block IS merged in (this failed before the fix — the domain was skipped)."""
    config_path, domains_dir = _make_fixture(tmp_path)

    _run(config_path, domains_dir)

    block = _demo_block(_load(config_path))
    names = {s["name"] for s in block["sources"]}
    assert "new-src" in names


def test_existing_domain_skips_already_present_source(tmp_path: Path) -> None:
    """Already-present sources are not duplicated (matched by name)."""
    config_path, domains_dir = _make_fixture(tmp_path)

    _run(config_path, domains_dir)

    block = _demo_block(_load(config_path))
    assert [s["name"] for s in block["sources"]] == ["existing-src", "new-src"]


def test_existing_domain_skips_source_with_same_url_different_name(
    tmp_path: Path,
) -> None:
    """A source whose url already exists is treated as present even if its
    name differs (url is the fallback identity key)."""
    config_path, domains_dir = _make_fixture(tmp_path)
    # demo sources.yaml: same url as existing-src but a different name
    ddir = domains_dir / "demo-domain"
    _dump(
        ddir / "sources.yaml",
        {
            "name": "demo-domain",
            "sources": [
                {
                    "name": "renamed-src",
                    "type": "rss",
                    "url": "https://existing.example/rss",
                },
                {"name": "new-src", "type": "api", "url": "https://new.example/api"},
            ],
        },
    )

    _run(config_path, domains_dir)

    block = _demo_block(_load(config_path))
    assert [s["name"] for s in block["sources"]] == ["existing-src", "new-src"]


def test_existing_domain_preserves_existing_config(tmp_path: Path) -> None:
    """Existing fields (active, sources, topics) are preserved, not overwritten."""
    config_path, domains_dir = _make_fixture(tmp_path)

    _run(config_path, domains_dir)

    block = _demo_block(_load(config_path))
    assert block["active"] is True
    assert block["sources"][0] == {
        "name": "existing-src",
        "type": "rss",
        "url": "https://existing.example/rss",
    }
    assert block["topics"][0] == {"name": "Existing Topic", "keywords": ["existing"]}


def test_existing_domain_merges_missing_topic(tmp_path: Path) -> None:
    """Missing topics from sources.yaml are appended to the existing block."""
    config_path, domains_dir = _make_fixture(tmp_path)

    _run(config_path, domains_dir)

    block = _demo_block(_load(config_path))
    topic_names = {t["name"] for t in block["topics"]}
    assert "New Topic" in topic_names
    assert len(block["topics"]) == 2


def test_dry_run_reports_merge_and_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--dry-run reports the would-be merge and leaves the config untouched."""
    config_path, domains_dir = _make_fixture(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    _run(config_path, domains_dir, "--dry-run")

    out = capsys.readouterr().out
    assert "demo-domain" in out
    assert "+1 sources" in out
    assert config_path.read_text(encoding="utf-8") == before


def test_new_domain_still_added(tmp_path: Path) -> None:
    """The add-new-domain path is unchanged: a domain absent from the config
    is still appended as a fresh block."""
    config_path, domains_dir = _make_fixture(tmp_path)
    ddir = domains_dir / "brand-new"
    ddir.mkdir()
    _dump(
        ddir / "sources.yaml",
        {
            "name": "brand-new",
            "sources": [
                {"name": "s1", "type": "rss", "url": "https://brand-new.example/rss"}
            ],
        },
    )

    _run(config_path, domains_dir)

    cfg = _load(config_path)
    names = {d["name"] for d in cfg["domains"]}
    assert "brand-new" in names
    assert "demo-domain" in names
    new_block = next(d for d in cfg["domains"] if d["name"] == "brand-new")
    assert new_block["active"] is True
    assert new_block["sources"][0]["name"] == "s1"
