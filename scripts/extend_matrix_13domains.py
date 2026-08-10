#!/usr/bin/env python3
"""Extend end-user-matrix.yaml from 2 demo domains to all 13 configured
domains, preserving the main-branch capability annotations.

Main's spec (capability revision) lists 131 cells for medical-research +
tech-ai-developer with per-cell capability: implemented|not-implemented.
This script duplicates the same capability pattern for the remaining 11
domains so the matrix honestly reflects the 13-domain target (#182).

Usage: HOME=/home/renanzai python3 scripts/extend_matrix_13domains.py [--dry-run]
"""
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs/dev/specs/end-user-matrix.yaml"

DOMAINS = [
    "medical-research", "ai-commercial", "financial-intelligence",
    "tech-ai-developer", "language-learning", "online-video",
    "financial-news", "online-education", "legal-compliance",
    "general-news", "gaming", "b2b", "retail",
]

# Capability per product (source: fix_matrix_spec.py, verified against code)
CAPABILITY = {
    "digest": ["markdown", "html", "json", "agent", "audio", "epub", "audiobook"],
    "report": ["markdown", "html", "json", "agent", "audio", "epub", "audiobook"],
    "tutorial": ["markdown", "agent"],
    "presentation": ["markdown", "html", "agent"],
    "premium-briefing": ["markdown", "html"],
    "column": ["markdown", "html"],
    "magazine-digest": ["markdown", "html"],
    "enterprise-briefing": ["markdown", "html"],
}
ALL_FORMATS = ["markdown", "html", "json", "agent", "audio", "epub", "audiobook"]
PRODUCTS = ["digest", "report", "tutorial", "presentation",
            "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]


def main() -> None:
    dry = "--dry-run" in sys.argv
    text = SPEC.read_text(encoding="utf-8")

    # Find the required_cells block boundaries
    start_marker = "required_cells:"
    end_marker = "# Products whose generation requires an LLM key"
    start = text.index(start_marker)
    end = text.index(end_marker)

    # Build cells for ALL 13 domains with capability annotations
    lines: list[str] = []
    for d in DOMAINS:
        for product in PRODUCTS:
            for fmt in ALL_FORMATS:
                cap = "implemented" if fmt in CAPABILITY[product] else "not-implemented"
                cell = f"  - {{domain: {d}, product: {product}, format: {fmt}, "
                cell += f"capability: {cap}}}"
                lines.append(cell)

    new_block = (
        "# Required cells — FULL end-user capability surface (8 products x 7 formats).\n"
        "# Each cell carries a capability annotation so the matrix can distinguish\n"
        "# 'real gap' (implemented but no evidence) from 'capability boundary'\n"
        "# (not implemented by design — annotated, not silently dropped).\n"
        "# Extended to ALL 13 configured domains (issue #182).\n"
        "required_cells:\n" + "\n".join(lines) + "\n"
    )
    new_text = text[:start] + new_block + text[end:]

    old_count = text[start:text.index(end_marker)].count("- {domain:")
    new_count = len(lines)
    print(f"old required_cells: {old_count} -> new: {new_count}")
    if not dry:
        SPEC.write_text(new_text, encoding="utf-8")
        print(f"written {SPEC}")


if __name__ == "__main__":
    main()
