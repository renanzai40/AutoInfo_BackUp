#!/usr/bin/env python3
"""Scan and optionally remove legacy empty KB entries (issue #279).

Entries written before the 50-char minimum-content guard existed can be
empty shells.  This script scans ``knowledge/**/{01-Raw,02-Draft}/*.md``
for files whose body content is shorter than ``MIN_KB_CONTENT_CHARS`` and
reports (``--dry-run``, default) or removes (``--apply``) them.

03-Wiki is append-only and is NEVER scanned or removed — the script
hard-refuses any path containing ``03-Wiki``.

Usage::

    python scripts/cleanup_empty_kb_entries.py [--dry-run] [KNOWLEDGE_ROOT]
    python scripts/cleanup_empty_kb_entries.py --apply [KNOWLEDGE_ROOT]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autoinfo.kb import MIN_KB_CONTENT_CHARS  # noqa: E402

_EMPTY_TIERS = ("01-Raw", "02-Draft")
_WIKI_MARKER = "03-Wiki"


def _iter_entries(knowledge_root: Path) -> Iterator[Path]:
    """Yield every markdown file under ``<root>/<domain>/{01-Raw,02-Draft}/``.

    Never descends into 03-Wiki: only the two writable tiers are globbed,
    and any path that nevertheless contains the 03-Wiki marker is refused.
    """
    root = Path(knowledge_root)
    for domain_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for tier in _EMPTY_TIERS:
            tier_dir = domain_dir / tier
            if not tier_dir.is_dir():
                continue
            for md_file in tier_dir.rglob("*.md"):
                if _WIKI_MARKER in md_file.parts:
                    raise RuntimeError(
                        f"refusing to touch 03-Wiki path: {md_file}"
                    )
                yield md_file


def _body_length(md_file: Path) -> int:
    """Length of the markdown body, i.e. the file content minus YAML
    frontmatter — the same notion the KB pipeline's 50-char guard uses."""
    raw = md_file.read_text(encoding="utf-8")
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            raw = raw[end + 3 :]
    return len(raw.strip())


def scan_empty_entries(knowledge_root: Path) -> list[Path]:
    """Return entries in 01-Raw/02-Draft whose content is shorter than
    ``MIN_KB_CONTENT_CHARS``.  03-Wiki is never scanned."""
    empty: list[Path] = []
    for md_file in _iter_entries(knowledge_root):
        try:
            if _body_length(md_file) < MIN_KB_CONTENT_CHARS:
                empty.append(md_file)
        except OSError:
            continue
    return sorted(empty)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan KB entries shorter than MIN_KB_CONTENT_CHARS "
            f"({MIN_KB_CONTENT_CHARS} chars). Never touches 03-Wiki."
        )
    )
    parser.add_argument(
        "knowledge_root",
        nargs="?",
        default="knowledge",
        type=Path,
        help="KB root containing <domain>/{01-Raw,02-Draft,03-Wiki} (default: knowledge)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="report flagged entries without deleting (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="delete flagged entries",
    )
    args = parser.parse_args(argv)

    root = Path(args.knowledge_root)
    scanned = sum(1 for _ in _iter_entries(root))
    empty = scan_empty_entries(root)

    if args.apply:
        for entry in empty:
            entry.unlink()
        verb = "removed"
    else:
        verb = "flagged"
        for entry in empty:
            print(entry)

    print(
        f"{len(empty)} empty {verb} / {scanned} scanned "
        f"(min content: {MIN_KB_CONTENT_CHARS} chars)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
