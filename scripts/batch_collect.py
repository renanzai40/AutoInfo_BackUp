#!/usr/bin/env python3
"""Batch collect+process a list of domains, then report data counts.

Usage: HOME=/home/renanzai python3 scripts/batch_collect.py gaming retail ...
"""
import subprocess
import sys
import time

DOMAINS = sys.argv[1:] if len(sys.argv) > 1 else [
    "gaming", "general-news", "language-learning", "legal-compliance",
    "online-education", "online-video", "retail",
]


def main() -> None:
    for d in DOMAINS:
        print(f"\n===== {d} =====")
        t0 = time.time()
        r = subprocess.run(
            ["python3", "-m", "autoinfo.cli", "collect",
             "--domain", d, "--limit", "5", "--auto-process"],
            capture_output=True, text=True, timeout=400,
            env={**__import__("os").environ, "HOME": "/home/renanzai"},
        )
        out = r.stdout + r.stderr
        # Summarize: sources found + processing result
        for line in out.splitlines():
            if line.startswith(("  ✓", "  ✗", "Total:", "Processing:", "KB entries")):
                print(line[:120])
        print(f"  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
