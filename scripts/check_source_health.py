#!/usr/bin/env python3
"""Check all configured sources across domains for health (dry-run collect).

Usage: HOME=/home/renanzai python3 scripts/check_source_health.py [domain...]
Exits 0. Prints a table: source name | status | items_found | error.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from autoinfo.collect import run_collection  # noqa: E402


def find_sources(d, out=None):
    if out is None:
        out = []
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "source" in v[0]:
                out.extend(v)
            else:
                find_sources(v, out)
    elif isinstance(d, list):
        for x in d:
            find_sources(x, out)
    return out


def main() -> None:
    domains = sys.argv[1:] or [
        "tech-ai-developer", "medical-research", "ai-commercial", "b2b",
        "financial-intelligence", "financial-news", "gaming", "general-news",
        "language-learning", "legal-compliance", "online-education",
        "online-video", "retail",
    ]
    for dom in domains:
        print(f"\n=== {dom} ===")
        try:
            data = run_collection(domain=dom, dry_run=True, limit=3)
            results = find_sources(data)
            for s in sorted(results, key=lambda x: x.get("source_failed", False)):
                status = "OK  " if not s.get("source_failed") else "DEAD"
                err = (s.get("errors") or [{}])[0].get("reason", "")[:60]
                print(
                    f"{status} {s.get('source','')[:32]:32s} "
                    f"found={s.get('items_found',0):3d} {err}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")


if __name__ == "__main__":
    main()
