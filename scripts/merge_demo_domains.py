#!/usr/bin/env python3
"""Merge demo-domain sources into .autoinfo/config.yaml for all 13 domains.

Reads each src/autoinfo/data/domains/<d>/sources.yaml and appends the domain
block (with its sources + topics) to the project config if the domain is not
already configured. For domains that already exist in the config, merges any
sources/topics from the demo sources.yaml that are missing from the existing
block (sources matched by name, falling back to url; topics matched by name).
Preserves existing config blocks.

Usage: HOME=/home/renanzai python3 scripts/merge_demo_domains.py [--dry-run]
       python3 scripts/merge_demo_domains.py --config PATH --domains-dir PATH [--dry-run]
"""
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".autoinfo" / "config.yaml"
DOMAINS_DIR = ROOT / "src" / "autoinfo" / "data" / "domains"


def _flag_value(args: list[str], flag: str, default: Path) -> Path:
    """Value of ``--flag <path>`` if present, else ``default``."""
    if flag in args:
        return Path(args[args.index(flag) + 1])
    return default


def _merge_domain(existing_block: dict[str, Any], demo: dict[str, Any]) -> tuple[int, int]:
    """Merge demo sources/topics into an existing domain block.

    Only sources/topics missing from the existing block are appended; all
    existing config is preserved. Sources are matched by name, falling back
    to url; topics are matched by name. Returns (added_sources, added_topics).
    """
    existing_sources = existing_block.setdefault("sources", [])
    existing_names = {str(s.get("name") or "").strip() for s in existing_sources}
    existing_urls = {str(s.get("url") or "").strip() for s in existing_sources}

    added_sources = 0
    for src in demo.get("sources") or []:
        name = str(src.get("name") or "").strip()
        url = str(src.get("url") or "").strip()
        if name in existing_names or (url and url in existing_urls):
            continue
        existing_sources.append(src)
        existing_names.add(name)
        if url:
            existing_urls.add(url)
        added_sources += 1

    added_topics = 0
    demo_topics = demo.get("topics")
    if demo_topics:
        existing_topics = existing_block.setdefault("topics", [])
        existing_topic_names = {
            str(t.get("name") or "").strip() for t in existing_topics
        }
        for topic in demo_topics:
            tname = str(topic.get("name") or "").strip()
            if tname in existing_topic_names:
                continue
            existing_topics.append(topic)
            existing_topic_names.add(tname)
            added_topics += 1

    # Cross-domain noise filter (#319): carry the demo domain's
    # exclude_keywords into the existing block when it declares any.
    demo_exclusions = demo.get("exclude_keywords")
    if demo_exclusions:
        existing_block.setdefault("exclude_keywords", demo_exclusions)

    return added_sources, added_topics


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in args
    config_path = _flag_value(args, "--config", CONFIG)
    domains_dir = _flag_value(args, "--domains-dir", DOMAINS_DIR)

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    existing = {d.get("name") for d in cfg.get("domains", [])}
    print(f"已配置域: {sorted(existing)}")

    added = []
    merged = []
    for ddir in sorted(domains_dir.iterdir()):
        if not ddir.is_dir():
            continue
        dname = ddir.name
        sf = ddir / "sources.yaml"
        if not sf.is_file():
            continue
        demo = yaml.safe_load(sf.read_text(encoding="utf-8"))
        if not isinstance(demo, dict) or not demo.get("sources"):
            continue
        if dname in existing:
            block = next(d for d in cfg["domains"] if d.get("name") == dname)
            added_sources, added_topics = _merge_domain(block, demo)
            if added_sources or added_topics:
                merged.append((dname, added_sources, added_topics))
                print(
                    f"  ~ {dname}: +{added_sources} sources, +{added_topics} topics"
                )
            continue
        block = {
            "name": dname,
            "active": True,
            "sources": demo["sources"],
        }
        if demo.get("topics"):
            block["topics"] = demo["topics"]
        if demo.get("exclude_keywords"):
            block["exclude_keywords"] = demo["exclude_keywords"]
        cfg["domains"].append(block)
        added.append(dname)
        print(f"  + {dname}: {len(demo['sources'])} sources")

    print(f"\n新增域: {len(added)} -> 总域数: {len(cfg['domains'])}")
    if merged:
        print(f"合并到已有域: {len(merged)}")
    if (added or merged) and not dry:
        config_path.write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        print(f"written {config_path}")
    else:
        print(
            "(dry-run — pass --write to apply)"
            if not (added or merged)
            else "(dry-run)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
