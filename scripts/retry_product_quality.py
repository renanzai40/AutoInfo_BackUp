#!/usr/bin/env python3
"""Retry-generate products until content quality passes (end-user view).

Handles LLM flakiness: generates the product, audits its summary, retries up to
N times. Skips products already OK.
"""
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import PRODUCT_TEMPLATES, generate_report, generate_tutorial  # noqa: E402

OUT = ROOT / "outputs"

VAGUE = [
    "this report covers", "the article titled", "the provided content is empty",
    "appears to discuss", "the instructions emphasize", "no content was provided",
    "were submitted without substantive content", "all .* entries included in this report",
]
PLACEHOLDER = ["_No objectives defined._", "_No exercises provided._", "_No entries found"]


def _quality(text: str) -> tuple[bool, str]:
    for m in PLACEHOLDER:
        if m.lower() in text.lower():
            return False, f"placeholder {m[:30]}"
    m = re.search(r"## (?:Executive Summary|The Big Idea)\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    summary = m.group(1) if m else text[:1200]
    for v in VAGUE:
        if re.search(v, summary, re.I):
            return False, f"vague {v[:30]}"
    return True, "ok"


def _gen(domain: str, product: str) -> str:
    if product == "tutorial":
        return generate_tutorial(domain=domain, format="markdown")
    tmpl = next(r["template"] for r in PRODUCT_TEMPLATES if r["name"] == product)
    if product == "column":
        return generate_report(domain=domain, period="weekly", format="markdown",
                               report_type="column", product_template=tmpl)
    return generate_report(domain=domain, period="weekly", format="markdown",
                           product_template=tmpl)


def main() -> None:
    targets = [
        ("medical-research", "enterprise-briefing"),
        ("medical-research", "magazine-digest"),
        ("medical-research", "tutorial"),
        ("tech-ai-developer", "column"),
    ]
    for domain, product in targets:
        ok = False
        for attempt in range(1, 6):
            try:
                out = _gen(domain, product)
                good, reason = _quality(str(out))
                if good and len(str(out)) > 1500:
                    d = OUT / domain
                    d.mkdir(parents=True, exist_ok=True)
                    p = d / f"{product}-markdown-{time.strftime('%Y%m%d-%H%M%S')}.md"
                    p.write_text(str(out), encoding="utf-8")
                    print(
                        f"[OK ] {domain}/{product} attempt={attempt} {p.name} "
                        f"({p.stat().st_size}b)"
                    )
                    ok = True
                    break
                print(f"[retry] {domain}/{product} attempt={attempt}: {reason}")
            except Exception as e:
                print(
                    f"[err ] {domain}/{product} attempt={attempt}: "
                    f"{type(e).__name__} {str(e)[:60]}"
                )
            time.sleep(1)
        if not ok:
            print(f"[FAIL] {domain}/{product} after 5 attempts")


if __name__ == "__main__":
    main()
