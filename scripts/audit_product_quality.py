#!/usr/bin/env python3
"""Refined content-quality audit: focus on EXECUTIVE SUMMARY quality (the
end-user reads first), not stray section titles.

For each md product, judge:
- OK: executive summary (first content section after metadata) has substantive
      domain-specific content (not boilerplate/placeholder/self-referential)
- EMPTY: no content / placeholder markers anywhere
- VAGUE: executive summary is boilerplate (this report covers / article titled / no content)
- NONPRODUCT: matrix/test artifacts

Usage: python3 scripts/audit_product_quality.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

PLACEHOLDER = [
    "_No objectives defined._", "_No exercises provided._", "_No entries found",
    "No content provided", "no content was provided", "has no accessible content",
    "were submitted without substantive content", "no findings or analyses were available",
    "is empty, so no detailed summary",
]
VAGUE = [
    "this report covers", "the article titled", "the provided content is empty",
    "appears to discuss", "the instructions emphasize", "this article is a directive",
    "this document provides instructions", "all .* entries included in this report",
    "the report's content and implications remain unspecified",
]


def _first_summary(text: str) -> str:
    """Return text up to the first '## Executive Summary' section content."""
    m = re.search(r"## (?:Executive Summary|The Big Idea)\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    if m:
        return m.group(1)
    return text[:1500]


def _classify(path: Path, text: str) -> tuple[str, str]:
    name = path.name
    if name.startswith("matrix-report") or name == "report.md":
        return "NONPRODUCT", "matrix/test artifact"
    if not text.strip():
        return "EMPTY", "zero-length"
    summary = _first_summary(text)
    if not summary.strip():
        return "EMPTY", "no summary section"
    # Placeholder check applies to the SUMMARY only — a missing entry body
    # inside a product with a real summary is a RAW-data gap, not a product
    # defect (issue #182: raw quality cascades into processed quality).
    for m in PLACEHOLDER:
        if m.lower() in summary.lower():
            return "EMPTY", f"placeholder in summary: {m[:36]}"
    for m in VAGUE:
        if re.search(m, summary, re.I):
            return "VAGUE", f"boilerplate in summary: {m[:36]}"
    return "OK", ""


def main() -> None:
    by: dict[str, list[tuple[Path, str]]] = {}
    for p in OUTPUTS.rglob("*.md"):
        status, note = _classify(p, p.read_text(encoding="utf-8", errors="replace"))
        by.setdefault(status, []).append((p, note))
    for st in ("OK", "VAGUE", "EMPTY", "NONPRODUCT"):
        items = by.get(st, [])
        print(f"\n=== {st}: {len(items)} ===")
        for p, n in sorted(items):
            print(f"  {p.relative_to(OUTPUTS)} | {n}")


if __name__ == "__main__":
    main()
