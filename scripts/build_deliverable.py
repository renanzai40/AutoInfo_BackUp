#!/usr/bin/env python3
"""Build the AutoInfo deliverable zip: 13 domains x processed outputs + real raw.

Excludes (issue #182 audit-feedback):
- _failed/ dirs (test fixtures, e.g. test-item-g4-retry.json)
- _runs.json run metadata (not real content)
- any file whose name hints test/example/mock
- zero-byte or placeholder-only raw entries (no title AND no content)
- stale raw entries older than the freshness window (default 45 days)

Usage: HOME=/home/renanzai python3 scripts/build_deliverable.py [--out PATH]
"""
import json
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"
COLLECTIONS = ROOT / "collections"

DOMAINS = [
    "medical-research", "ai-commercial", "financial-intelligence",
    "tech-ai-developer", "language-learning", "online-video",
    "financial-news", "online-education", "legal-compliance",
    "general-news", "gaming", "b2b", "retail",
]

FRESHNESS_DAYS = 45
_NON_RAW = re.compile(r"(_runs\.json$|test|fixture|example|mock|\.bak$|~$)", re.I)
_PLACEHOLDER = re.compile(r"(no content was provided|_No entries found|draft|placeholder)", re.I)


def _is_real_raw_file(path: Path) -> tuple[bool, str]:
    """Return (keep, reason) for a raw collection file."""
    name = path.name
    if _NON_RAW.search(name):
        return False, "non-raw artifact"
    if path.parent.name == "_failed":
        return False, "_failed fixture"
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False, "unparseable"
    if not isinstance(data, dict):
        return False, "not object"
    title = str(data.get("title") or "")
    content = str(data.get("content") or data.get("summary") or "")
    if not title.strip() and not content.strip():
        return False, "empty entry"
    if _PLACEHOLDER.search(title + " " + content[:200]):
        return False, "placeholder content"
    # Freshness: keep only entries collected/created within the window
    for key in ("collected_at", "created_at", "date"):
        raw = str(data.get(key) or "")
        if raw and re.search(r"\d{4}-\d{2}-\d{2}", raw):
            try:
                when = datetime.fromisoformat(raw[:10])
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when < datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS):
                    return False, f"stale ({raw[:10]})"
            except ValueError:
                pass
    return True, ""


def main() -> None:
    out_path = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else ROOT / "autoinfo-deliverable-13domains.zip"

    stats: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # README
        readme = ROOT / "validation-deliveries" / "2026-08-10" / "paygrade-issues.md"
        if readme.exists():
            zf.write(readme, "README.md")

        for dom in DOMAINS:
            stats[dom] = {"processed": 0, "raw": 0}
            # Processed outputs (only non-empty markdown)
            dom_out = OUTPUTS / dom
            if dom_out.is_dir():
                for p in sorted(dom_out.glob("*.md")):
                    text = p.read_text(encoding="utf-8", errors="replace")
                    if len(text.strip()) < 500:
                        continue  # empty shell, never ship
                    stats[dom]["processed"] += 1
                    zf.write(p, f"{dom}/processed/{p.name}")
            # Raw (real entries only)
            dom_raw = COLLECTIONS / dom
            if dom_raw.is_dir():
                for p in sorted(dom_raw.rglob("*.json")):
                    keep, reason = _is_real_raw_file(p)
                    if not keep:
                        continue
                    stats[dom]["raw"] += 1
                    zf.write(p, f"{dom}/raw/{dom}/{p.relative_to(dom_raw)}")

    print(f"zip: {out_path}")
    total_p, total_r = 0, 0
    for dom, s in stats.items():
        print(f"  {dom:25s} processed={s['processed']} raw={s['raw']}")
        total_p += s["processed"]
        total_r += s["raw"]
    print(f"TOTAL processed={total_p} raw={total_r}")


if __name__ == "__main__":
    main()
