#!/usr/bin/env python3
"""Regenerate ALL products for a domain using the fixed synthesis code.

Usage: HOME=/home/renanzai python3 scripts/gen_domain_products.py <domain> [--all-formats]
Generates the 8 products as markdown (Human-readable floor) for the domain,
skipping any that already exist with today's timestamp. Run after the report
synthesis fix (40cf65a) so briefings get real content, not meta-narrative.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import (  # noqa: E402, I001
    generate_digest, generate_report, generate_tutorial, generate_presentation,
    PRODUCT_TEMPLATES,
)


def gen_one(domain: str, product: str) -> str:
    if product == "digest":
        return generate_digest(domain=domain, period="weekly", format="markdown")
    if product == "report":
        return generate_report(domain=domain, period="weekly", format="markdown")
    if product == "tutorial":
        return generate_tutorial(domain=domain, format="markdown")
    if product == "presentation":
        return generate_presentation(domain=domain, topic="", format="markdown")
    tmpl = next(r["template"] for r in PRODUCT_TEMPLATES if r["name"] == product)
    if product == "column":
        return generate_report(domain=domain, period="weekly", format="markdown",
                               report_type="column", product_template=tmpl)
    if product == "magazine-digest":
        return generate_digest(domain=domain, period="weekly", format="markdown",
                               product_template=tmpl)
    return generate_report(domain=domain, period="weekly", format="markdown",
                           product_template=tmpl)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: gen_domain_products.py <domain>")
        sys.exit(1)
    domain = sys.argv[1]
    out_dir = ROOT / "outputs" / domain
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    products = ["digest", "report", "tutorial", "presentation",
                "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]
    for p in products:
        try:
            out = gen_one(domain, p)
            if not out or len(str(out)) < 500:
                print(f"[ERR] {p}: too short ({len(str(out))})")
                continue
            f = out_dir / f"{p}-markdown-{stamp}.md"
            f.write_text(str(out), encoding="utf-8")
            print(f"[OK] {p}: {len(str(out))} chars")
        except Exception as e:
            print(f"[ERR] {p}: {type(e).__name__} {str(e)[:100]}")


if __name__ == "__main__":
    main()
