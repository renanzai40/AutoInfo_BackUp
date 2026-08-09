#!/usr/bin/env python3
"""Backfill missing KB entry summaries via LLM extraction (tl_dr).

Entries whose summary/tl_dr is empty get re-extracted with the configured LLM
(DeepSeek-V4-Flash via OpenCode Go, ~5s/call at concurrency 5). Updates both the
SQLite entries table and the KB markdown frontmatter.

Usage: HOME=/home/renanzai python3 scripts/backfill_summaries.py [--domain X] [--dry-run]
"""
import sys, os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.config import load_config
from autoinfo.llm import LLMExtractor
from autoinfo.models import Item


def _entries_missing_summary(domain: str) -> list[dict]:
    import sqlite3
    db = Path(__file__).resolve().parent.parent / "autoinfo.db"
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT entry_id, title, file_path FROM entries "
        "WHERE domain=? AND (summary IS NULL OR trim(summary)='')",
        (domain,),
    ).fetchall()
    conn.close()
    return [{"entry_id": r[0], "title": r[1], "file_path": r[2]} for r in rows]


def _extract_summary(cfg, entry: dict) -> tuple[str, str, str]:
    """(entry_id, status, summary)"""
    item = Item(
        id=entry["entry_id"], source_name="backfill", source_type="internal",
        source_url="", title=entry["title"] or "(untitled)",
        content=f"Write a 2-3 sentence factual summary of this article based on its title: {entry['title']}",
    )
    try:
        r = LLMExtractor(cfg).extract(item, schema=["tl_dr"])
        s = (r.tl_dr or "").strip()
        if s:
            return entry["entry_id"], "OK", s
        return entry["entry_id"], "EMPTY", ""
    except Exception as e:
        return entry["entry_id"], f"ERR:{type(e).__name__}", ""


def _write_db_summaries(updates: dict[str, str]) -> None:
    import sqlite3
    db = Path(__file__).resolve().parent.parent / "autoinfo.db"
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    for eid, summary in updates.items():
        cur.execute("UPDATE entries SET summary=? WHERE entry_id=?", (summary, eid))
        # FTS sync: delete + reinsert row
        row = cur.execute("SELECT rowid FROM entries WHERE entry_id=?", (eid,)).fetchone()
        if row:
            cur.execute("DELETE FROM entries_fts5 WHERE rowid=?", (row[0],))
            e = cur.execute("SELECT title, summary, domain, tags FROM entries WHERE entry_id=?", (eid,)).fetchone()
            if e:
                cur.execute(
                    "INSERT INTO entries_fts5(rowid, title, summary, content, domain, tags) VALUES (?,?,?,?,?,?)",
                    (row[0], e[0] or "", e[1] or "", "", e[2] or "", e[3] or ""),
                )
    conn.commit()
    conn.close()


def _write_md_summaries(updates: dict[str, str]) -> None:
    """Update summary: in KB markdown frontmatter for the given entries."""
    import re
    root = Path(__file__).resolve().parent.parent
    for eid, summary in updates.items():
        if not summary:
            continue
        # locate file by entry_id from DB
        import sqlite3
        conn = sqlite3.connect(root / "autoinfo.db")
        cur = conn.cursor()
        row = cur.execute("SELECT file_path FROM entries WHERE entry_id=?", (eid,)).fetchone()
        conn.close()
        if not row or not row[0]:
            continue
        md = root / row[0]
        if not md.is_file():
            # fall back to searching by entry_id in frontmatter
            for p in (root / "knowledge").rglob("*.md"):
                if p.read_text(encoding="utf-8", errors="replace").startswith("---") and f"entry_id: {eid}" in p.read_text(encoding="utf-8", errors="replace")[:2000]:
                    md = p
                    break
            else:
                continue
        text = md.read_text(encoding="utf-8")
        new_text = re.sub(r"(?m)^summary:.*$", f"summary: '{summary.replace(chr(39), chr(39)+chr(39)+chr(39))}'", text, count=1)
        if new_text != text:
            md.write_text(new_text, encoding="utf-8")


def main() -> None:
    dry = "--dry-run" in sys.argv
    domain = "medical-research"
    for i, a in enumerate(sys.argv):
        if a == "--domain" and i + 1 < len(sys.argv):
            domain = sys.argv[i + 1]

    entries = _entries_missing_summary(domain)
    print(f"domain={domain} entries missing summary: {len(entries)}")
    if dry or not entries:
        for e in entries[:10]:
            print("  ", e["entry_id"][:60])
        return

    cfg = load_config(".autoinfo/config.yaml")
    updates: dict[str, str] = {}
    ok = err = empty = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(_extract_summary, cfg, e) for e in entries]
        for f in futs:
            eid, status, summary = f.result()
            if status == "OK":
                updates[eid] = summary
                ok += 1
            elif status == "EMPTY":
                empty += 1
            else:
                err += 1
                print(f"[ERR] {eid[:50]} {status}")
    print(f"extracted ok={ok} empty={empty} err={err}")
    if updates:
        _write_db_summaries(updates)
        _write_md_summaries(updates)
        print(f"DB+MD updated: {len(updates)} entries")
    # verify
    remaining = _entries_missing_summary(domain)
    print(f"remaining missing: {len(remaining)}")


if __name__ == "__main__":
    main()
