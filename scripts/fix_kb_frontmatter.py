#!/usr/bin/env python3
"""Fix KB frontmatter summary fields with broken single-quote escaping.

backfill_summaries.py wrote `summary: '...'''...'` (over-escaped quotes) which
breaks YAML parsing for files whose summary contains apostrophes. This rewrites
those summary lines as double-quoted YAML scalars (proper escaping) and verifies
each file parses cleanly afterward.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _frontmatter_parts(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_block, rest) if the file starts with ---."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def _fix_summary_line(frontmatter: str) -> str:
    """Rewrite the summary: line as a double-quoted YAML scalar."""
    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        # Collapse the over-escaped quotes from the backfill writer.
        fixed = raw.replace("''''", "'").replace("'''", "'").replace("''", "'")
        escaped = fixed.replace("\\", "\\\\").replace('"', '\\"')
        return f'summary: "{escaped}"'
    return re.sub(r"(?ms)^summary: '(.*)'$", _repl, frontmatter, count=1)


def main() -> None:
    bad: list[Path] = []
    for p in ROOT.joinpath("knowledge").rglob("*.md"):
        if ".bak" in p.name:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            parts = _frontmatter_parts(text)
            if parts is None:
                continue
            yaml.safe_load(parts[0])
        except Exception:
            bad.append(p)

    print(f"待修复: {len(bad)}")
    fixed = 0
    for p in bad:
        text = p.read_text(encoding="utf-8", errors="replace")
        parts = _frontmatter_parts(text)
        if parts is None:
            print(f"  SKIP (no frontmatter): {p}")
            continue
        new_fm = _fix_summary_line(parts[0])
        try:
            yaml.safe_load(new_fm)
        except Exception as e:
            print(f"  STILL BROKEN: {p} | {str(e)[:70]}")
            continue
        p.write_text(f"---{new_fm}---{parts[1]}", encoding="utf-8")
        fixed += 1
        print(f"  修复 OK: {p.name}")

    # Final sweep
    remaining = []
    for p in ROOT.joinpath("knowledge").rglob("*.md"):
        if ".bak" in p.name:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            parts = _frontmatter_parts(text)
            if parts is None:
                continue
            yaml.safe_load(parts[0])
        except Exception:
            remaining.append(p)
    print(f"修复 {fixed} 个; 剩余失败: {len(remaining)}")
    for p in remaining[:5]:
        print("  ", p.name)


if __name__ == "__main__":
    main()
