#!/usr/bin/env python3
"""Content-quality audit of processed products (end-user view).

For every persisted product under outputs/<domain>/, classify content quality:
- OK: has substantive content (non-placeholder, non-empty, real substance)
- EMPTY: placeholder/empty-state markers (_No objectives defined._ etc.)
- VAGUE: content exists but is generic boilerplate (no domain-specific substance)
- NONPRODUCT: not a product file (matrix-report.md etc.)

Usage: python3 scripts/audit_product_quality.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

# Placeholder markers that indicate an empty-state product
PLACEHOLDER_MARKERS = [
    "_No objectives defined._",
    "_No exercises provided._",
    "_No entries found",
    "_No content",
    "No content provided",
    "no content was provided",
    "has no accessible content",
    "lacks accessible content",
    "but no content was provided",
    "is empty, so no detailed summary",
    "were submitted without substantive content",
    "no findings or analyses were available",
]

# Vague boilerplate phrases (LLM wrote meta-instructions instead of analysis)
VAGUE_MARKERS = [
    "the instructions emphasize",
    "this article is a directive",
    "this document provides instructions",
    "the article titled",
    "this report covers",
    "distills .* entries into a coherent picture",
    "all .* entries included in this report",
    "the report's content and implications remain unspecified",
    "appears to discuss",
    "no content was provided for analysis",
    "the provided content is empty",
]


def _classify(path: Path, text: str) -> tuple[str, str]:
    """Return (status, note)."""
    name = path.name
    if name.startswith("matrix-report") or name == "report.md":
        return "NONPRODUCT", "matrix/test artifact, not a product"
    if not text.strip():
        return "EMPTY", "zero-length file"
    # EMPTY: placeholder markers
    for m in PLACEHOLDER_MARKERS:
        if m.lower() in text.lower():
            return "EMPTY", f"placeholder: {m[:40]}"
    # VAGUE: boilerplate
    for m in VAGUE_MARKERS:
        if re.search(m, text, re.IGNORECASE):
            return "VAGUE", f"boilerplate: {m[:40]}"
    return "OK", ""


def main() -> None:
    by_status: dict[str, list[tuple[Path, str]]] = {}
    for p in OUTPUTS.rglob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        status, note = _classify(p, text)
        by_status.setdefault(status, []).append((p, note))

    for status in ("OK", "EMPTY", "VAGUE", "NONPRODUCT"):
        items = by_status.get(status, [])
        print(f"\n=== {status}: {len(items)} ===")
        for p, note in sorted(items):
            print(f"  {p.relative_to(OUTPUTS)} | {note}")


if __name__ == "__main__":
    main()
