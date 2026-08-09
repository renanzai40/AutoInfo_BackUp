#!/usr/bin/env python3
"""Correct end-user-matrix.yaml required_cells to match ACTUAL product/format
capability (verified against source code 2026-08-09). The previous spec demanded
all 8 products x 7 formats for both domains, but several products only implement
a subset of formats (tutorial: md+agent; presentation: md+html+agent;
template products: md+html). Those unsupported cells are false gaps — the honest
"100% coverage" target is: every cell the code CAN produce HAS evidence.

Usage: HOME=/home/renanzai python3 scripts/fix_matrix_spec.py [--dry-run]
"""
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs/dev/specs/end-user-matrix.yaml"

# Verified capability matrix (source: src/autoinfo/output/__init__.py + templates)
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

DOMAINS = ["medical-research", "tech-ai-developer"]


def main() -> None:
    dry = "--dry-run" in sys.argv
    text = SPEC.read_text(encoding="utf-8")

    # Build new required_cells block, preserving the existing header comment.
    cells = []
    for d in DOMAINS:
        for product in ["digest", "report", "tutorial", "presentation",
                        "premium-briefing", "column", "magazine-digest",
                        "enterprise-briefing"]:
            for fmt in CAPABILITY[product]:
                cells.append(f"  - {{domain: {d}, product: {product}, format: {fmt}}}")

    # Replace the required_cells section between the marker comments.
    start_marker = "# Required cells"
    end_marker = "# Products whose generation requires an LLM key"
    start = text.index(start_marker)
    end = text.index(end_marker)
    new_block = (
        "# Required cells — every product x format the codebase ACTUALLY supports\n"
        "# (capability-verified 2026-08-09; tutorial=md+agent, presentation=md+html+agent,\n"
        "# template products=md+html, digest/report=all 7). Cells outside this set are\n"
        "# not implementable and are NOT gaps.\n"
        "required_cells:\n" + "\n".join(cells) + "\n"
    )
    new_text = text[:start] + new_block + text[end:]

    old_cells = text[start:text.index(end_marker)]
    old_count = sum(1 for line in old_cells.splitlines() if line.strip().startswith("- {domain:"))
    print(f"old required_cells: {old_count} -> new: {len(cells)}")
    if not dry:
        SPEC.write_text(new_text, encoding="utf-8")
        print(f"written {SPEC}")


if __name__ == "__main__":
    main()
