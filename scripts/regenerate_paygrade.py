#!/usr/bin/env python3
"""Regenerate paygrade-failing products (VAGUE/EMPTY/too-short) with the fixed
synthesis code.

Usage: HOME=/home/renanzai python3 scripts/regenerate_paygrade.py [--domain X] [--product Y]
Without args, regenerates every product that audit flags VAGUE/EMPTY or that
currently has no output file (from the earlier failed runs).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUTPUTS = ROOT / "outputs"

import os  # noqa: E402, I001
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import (  # noqa: E402, I001
    generate_digest, generate_report, generate_tutorial, generate_presentation,
    PRODUCT_TEMPLATES,
)

PRODUCTS = ["digest", "report", "tutorial", "presentation",
            "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]

DOMAINS = ["medical-research", "ai-commercial", "financial-intelligence",
           "tech-ai-developer", "language-learning", "online-video",
           "financial-news", "online-education", "legal-compliance",
           "general-news", "gaming", "b2b", "retail"]

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
]

# Per-domain synthesis instructions — keeps the LLM in-domain so
# products reflect the domain's actual value (issue #182 paygrade).
_DOMAIN_INSTRUCTIONS = {
    "language-learning": (
        "This is a LANGUAGE LEARNING domain (English teaching materials, "
        "graded readers, literacy and multilingual resources). Organize "
        "content around language-learning value: vocabulary themes, "
        "reading-comprehension topics, teaching strategies, CEFR/level "
        "progression, and what each resource offers learners and teachers. "
        "Do NOT write a generic news summary."
    ),
    "financial-intelligence": (
        "This is a FINANCIAL INTELLIGENCE domain. Extract the market "
        "intelligence value: macro indicators, company filings that signal "
        "strategy/risk, market data points. Synthesize what these filings "
        "and data mean for investors/analysts rather than just listing "
        "filings. Do NOT write a regulatory-checklist summary."
    ),
}


def _first_summary(text: str) -> str:
    m = re.search(r"## (?:Executive Summary|The Big Idea)\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    return m.group(1) if m else text[:1500]


def _is_bad(path: Path, text: str) -> tuple[bool, str]:
    if not text.strip():
        return True, "empty"
    summary = _first_summary(text)
    for p in PLACEHOLDER:
        if p.lower() in summary.lower():
            return True, f"placeholder:{p[:30]}"
    for r in VAGUE_RE:
        if re.search(r, summary, re.I):
            return True, f"vague:{r}"
    return False, ""


def _gen(domain: str, product: str) -> str:
    instructions = _DOMAIN_INSTRUCTIONS.get(domain, "")

    if product == "digest":
        return generate_digest(domain=domain, period="weekly", format="markdown",
                               custom_instructions=instructions)
    if product == "report":
        return generate_report(domain=domain, period="weekly", format="markdown",
                               custom_instructions=instructions)
    if product == "tutorial":
        return generate_tutorial(domain=domain, format="markdown",
                                 custom_instructions=instructions)
    if product == "presentation":
        return generate_presentation(domain=domain, topic="", format="markdown",
                                     custom_instructions=instructions)
    # PRODUCT_TEMPLATES is a list[dict] with name/template keys
    template_obj = None
    for pt in PRODUCT_TEMPLATES:
        if isinstance(pt, dict) and pt.get("name") == product:
            template_obj = pt.get("template")
            break
    return generate_report(domain=domain, period="weekly", format="markdown",
                           product_template=template_obj, product_type="PROCESSED",
                           custom_instructions=instructions)


def main() -> None:
    only_domain = None
    only_product = None
    for a in sys.argv[1:]:
        if a.startswith("--domain="):
            only_domain = a.split("=", 1)[1]
        elif a.startswith("--product="):
            only_product = a.split("=", 1)[1]

    domains = [only_domain] if only_domain else DOMAINS
    for dom in domains:
        dom_dir = OUTPUTS / dom
        if not dom_dir.is_dir():
            dom_dir.mkdir(parents=True, exist_ok=True)
        for prod in PRODUCTS:
            if only_product and prod != only_product:
                continue
            stamp = "20260810-paygrade"
            out_path = dom_dir / f"{prod}-markdown-{stamp}.md"
            # Skip if a recent good copy already exists
            existing = sorted(dom_dir.glob(f"{prod}-markdown-*.md"))
            if existing:
                latest = max(existing, key=lambda p: p.stat().st_mtime)
                if latest.name != out_path.name:
                    text = latest.read_text(encoding="utf-8", errors="replace")
                    bad, why = _is_bad(latest, text)
                    if not bad and len(text) >= MIN_CHARS[prod]:
                        continue  # already good
            try:
                result = _gen(dom, prod)
                text = result if isinstance(result, str) else str(result)
                bad, why = _is_bad(out_path, text)
                ok = not bad and len(text) >= MIN_CHARS[prod]
                if ok:
                    out_path.write_text(text, encoding="utf-8")
                    print(f"[OK] {dom}/{prod}: {len(text)} chars")
                else:
                    # Issue #182 audit-feedback: never persist an empty/draft
                    # shell — delete any stale BAD copy so it can't ship.
                    if out_path.exists():
                        out_path.unlink()
                    print(f"[BAD] {dom}/{prod}: {len(text)} chars ({why or f'short:{len(text)}'})")
            except Exception as exc:  # noqa: BLE001
                # Generator raised (e.g. presentation empty-shell guard) — no
                # artifact written, nothing stale left behind.
                if out_path.exists() and out_path.stat().st_size < MIN_CHARS[prod]:
                    out_path.unlink()
                print(f"[ERR] {dom}/{prod}: {exc}")


if __name__ == "__main__":
    main()
