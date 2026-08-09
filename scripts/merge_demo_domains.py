#!/usr/bin/env python3
"""Merge demo-domain sources into .autoinfo/config.yaml for all 13 domains.

Reads each src/autoinfo/data/domains/<d>/sources.yaml and appends the domain
block (with its sources + topics) to the project config if the domain is not
already configured. Preserves existing config blocks.

Usage: HOME=/home/renanzai python3 scripts/merge_demo_domains.py [--dry-run]
"""
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".autoinfo" / "config.yaml"
DOMAINS_DIR = ROOT / "src" / "autoinfo" / "data" / "domains"


def main() -> None:
    dry = "--dry-run" in sys.argv
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    existing = {d.get("name") for d in cfg.get("domains", [])}
    print(f"已配置域: {sorted(existing)}")

    added = []
    for ddir in sorted(DOMAINS_DIR.iterdir()):
        if not ddir.is_dir():
            continue
        dname = ddir.name
        sf = ddir / "sources.yaml"
        if not sf.is_file():
            continue
        if dname in existing:
            continue
        demo = yaml.safe_load(sf.read_text(encoding="utf-8"))
        if not isinstance(demo, dict) or not demo.get("sources"):
            continue
        block = {
            "name": dname,
            "active": True,
            "sources": demo["sources"],
        }
        if demo.get("topics"):
            block["topics"] = demo["topics"]
        cfg["domains"].append(block)
        added.append(dname)
        print(f"  + {dname}: {len(demo['sources'])} sources")

    print(f"\n新增域: {len(added)} -> 总域数: {len(cfg['domains'])}")
    if added and not dry:
        CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"written {CONFIG}")
    else:
        print("(dry-run — pass --write to apply)" if not added else "(dry-run)")


if __name__ == "__main__":
    main()
