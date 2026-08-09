#!/usr/bin/env python3
"""Restore the full 112-cell matrix spec with capability annotations.

Restores the original 8-product x 7-format required_cells for both configured
domains, and annotates each cell with its ACTUAL code capability (verified
against src/autoinfo/output/__init__.py on 2026-08-09):

  capability: implemented  -> code can produce this product/format
  capability: not-implemented -> code lacks a render path / template for it

The matrix tooling can then distinguish "real gap" (implemented but no
evidence) from "capability boundary" (not implemented by design) instead of
silently dropping the acceptance target.

Usage: python3 scripts/restore_matrix_spec.py [--write]
"""
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs/dev/specs/end-user-matrix.yaml"

# Verified capability matrix (source of truth: code inspection 2026-08-09)
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
DOMAINS = ["medical-research", "tech-ai-developer"]
PRODUCTS = ["digest", "report", "tutorial", "presentation",
            "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]


def main() -> None:
    text = SPEC.read_text(encoding="utf-8")
    start_marker = "# Required cells"
    end_marker = "# Products whose generation requires an LLM key"
    start = text.index(start_marker)
    end = text.index(end_marker)

    lines = [
        "# Required cells — FULL end-user capability surface (8 products x 7 formats).",
        "# Each cell carries a capability annotation so the matrix can distinguish",
        "# 'real gap' (implemented but no evidence) from 'capability boundary'",
        "# (not implemented by design — annotated, not silently dropped).",
        "required_cells:",
    ]
    for d in DOMAINS:
        for p in PRODUCTS:
            for f in ALL_FORMATS:
                cap = "implemented" if f in CAPABILITY[p] else "not-implemented"
                lines.append(
                    f"  - {{domain: {d}, product: {p}, format: {f}, capability: {cap}}}"
                )
    new_block = "\n".join(lines) + "\n"

    old_text = text[start:end]
    old_count = sum(1 for l in old_text.splitlines() if l.strip().startswith("- {domain:"))
    print(f"old required_cells: {old_count} -> new: {len(DOMAINS)*len(PRODUCTS)*len(ALL_FORMATS)}")
    print(f"implemented: {sum(1 for d in DOMAINS for p in PRODUCTS for f in ALL_FORMATS if f in CAPABILITY[p])}")
    print(f"not-implemented: {sum(1 for d in DOMAINS for p in PRODUCTS for f in ALL_FORMATS if f not in CAPABILITY[p])}")

    if "--write" in sys.argv:
        SPEC.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
        print(f"written {SPEC}")
    else:
        print("(dry-run — pass --write to apply)")


if __name__ == "__main__":
    main()
