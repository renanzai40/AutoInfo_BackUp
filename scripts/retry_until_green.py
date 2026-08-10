#!/usr/bin/env python3
"""Retry paygrade-failing products until audit shows all OK.

Runs audit_product_quality; for every VAGUE/EMPTY/too-short product, calls
the appropriate generator again (fresh LLM call — DeepSeek empty-content is
transient, #178), writing to the paygrade stamp. Loops until no failures
remain or max_rounds reached.

Usage: HOME=/home/renanzai python3 scripts/retry_until_green.py [--max-rounds N]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUTPUTS = ROOT / "outputs"
STAMP = "20260810-paygrade"

import os  # noqa: E402, I001
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import (  # noqa: E402, I001
    generate_digest, generate_report, generate_tutorial, generate_presentation,
    PRODUCT_TEMPLATES,
)

MIN_CHARS = {
    "digest": 1500, "report": 2000, "tutorial": 2000, "presentation": 3000,
    "premium-briefing": 2000, "column": 2000,
    "magazine-digest": 2000, "enterprise-briefing": 2000,
}
PLACEHOLDER = [
    "_No objectives defined._", "_No exercises provided._", "_No entries found",
    "no content was provided", "no content provided",
]
VAGUE_RE = [
    r"this report covers", r"the article titled", r"the provided content is empty",
    r"this document provides instructions", r"this article is a directive",
    r"this article provides guidelines", r"this article provides instructions",
    r"appears to discuss",
]


def _first_summary(text: str) -> str:
    m = re.search(r"## (?:Executive Summary|The Big Idea)\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    return m.group(1) if m else text[:1500]


def _is_bad(path: Path, text: str) -> tuple[bool, str]:
    if not text.strip():
        return True, "empty"
    summary = _first_summary(text)
    if not summary.strip():
        return True, "no-summary"
    for p in PLACEHOLDER:
        if p.lower() in summary.lower():
            return True, f"placeholder:{p[:30]}"
    for r in VAGUE_RE:
        if re.search(r, summary, re.I):
            return True, f"vague:{r}"
    return False, ""


def _gen(domain: str, product: str) -> str:
    if product == "digest":
        return generate_digest(domain=domain, period="weekly", format="markdown")
    if product == "report":
        return generate_report(domain=domain, period="weekly", format="markdown")
    if product == "tutorial":
        return generate_tutorial(domain=domain, format="markdown")
    if product == "presentation":
        return generate_presentation(domain=domain, topic="", format="markdown")
    template_obj = None
    for pt in PRODUCT_TEMPLATES:
        if isinstance(pt, dict) and pt.get("name") == product:
            template_obj = pt.get("template")
            break
    return generate_report(domain=domain, period="weekly", format="markdown",
                           product_template=template_obj, product_type="PROCESSED")


def _scan_bad() -> list[tuple[str, str, str]]:
    """Return [(domain, product, reason)] for failing products."""
    bad: list[tuple[str, str, str]] = []
    for p in OUTPUTS.glob(f"*/{STAMP}.md"):
        pass
    for dom_dir in OUTPUTS.iterdir():
        if not dom_dir.is_dir():
            continue
        domain = dom_dir.name
        # Skip non-domain dirs (coverage-matrix, validation-processed, etc.)
        if domain in ("coverage-matrix", "validation-processed", "test-domain"):
            continue
        for prod in ["digest", "report", "tutorial", "presentation",
                     "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]:
            path = dom_dir / f"{prod}-markdown-{STAMP}.md"
            if not path.is_file():
                bad.append((domain, prod, "missing"))
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            bad_flag, why = _is_bad(path, text)
            if bad_flag or len(text) < MIN_CHARS[prod]:
                bad.append((domain, prod, why or f"short:{len(text)}"))
    return bad


def main() -> None:
    max_rounds = 3
    for a in sys.argv[1:]:
        if a.startswith("--max-rounds="):
            max_rounds = int(a.split("=", 1)[1])

    for rnd in range(1, max_rounds + 1):
        bad = _scan_bad()
        print(f"=== Round {rnd}: {len(bad)} failing ===")
        if not bad:
            print("ALL GREEN")
            return
        for domain, prod, why in bad:
            print(f"[RETRY] {domain}/{prod} ({why})")
            try:
                result = _gen(domain, prod)
                text = result if isinstance(result, str) else str(result)
                out_path = OUTPUTS / domain / f"{prod}-markdown-{STAMP}.md"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text, encoding="utf-8")
                still, why2 = _is_bad(out_path, text)
                status = "OK" if not still and len(text) >= MIN_CHARS[prod] else "BAD"
                msg = f"  -> {status} ({len(text)} chars)"
                if status == "BAD":
                    msg += f" {why2}"
                print(msg)
            except Exception as exc:  # noqa: BLE001
                print(f"  -> ERR {exc}")
    remaining = _scan_bad()
    print(f"\n=== Final: {len(remaining)} still failing ===")
    for d, p, w in remaining:
        print(f"  {d}/{p}: {w}")


if __name__ == "__main__":
    main()
