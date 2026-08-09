#!/usr/bin/env python3
"""Generate the remaining matrix cells: digest/report audio+audiobook, column html."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    generate_digest,
    generate_report,
)

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"


def persist(domain: str, product: str, fmt: str, content) -> Path:
    d = OUTPUTS / domain
    d.mkdir(parents=True, exist_ok=True)
    ext = {"markdown": ".md", "html": ".html", "json": ".json", "agent": ".json",
           "audio": ".mp3", "epub": ".epub", "audiobook": ".zip"}[fmt]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    p = d / f"{product}-{fmt}-{stamp}{ext}"
    import base64
    if fmt in ("audio", "epub", "audiobook"):
        p.write_bytes(base64.b64decode(content))
    else:
        p.write_text(str(content), encoding="utf-8")
    return p


def gen(domain: str, product: str, fmt: str) -> tuple[bool, str]:
    try:
        if product == "digest":
            out = generate_digest(domain=domain, period="weekly", format=fmt)
        elif product == "report":
            out = generate_report(domain=domain, period="weekly", format=fmt)
        elif product == "column":
            template = next(r["template"] for r in PRODUCT_TEMPLATES if r["name"] == "column")
            out = generate_report(domain=domain, period="weekly", format=fmt,
                                  report_type="column", product_template=template)
        else:
            return False, f"unknown {product}"
        if not out:
            return False, "empty"
        p = persist(domain, product, fmt, out)
        return p.stat().st_size > 0, f"{p.name} ({p.stat().st_size}b)"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:150]}"


def main() -> None:
    cells = [
        ("medical-research", "digest", "audio"),
        ("medical-research", "digest", "audiobook"),
        ("medical-research", "report", "audio"),
        ("medical-research", "report", "audiobook"),
        ("tech-ai-developer", "digest", "audio"),
        ("tech-ai-developer", "digest", "audiobook"),
        ("tech-ai-developer", "report", "audio"),
        ("tech-ai-developer", "report", "audiobook"),
    ]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(gen, *c): c for c in cells}
        for f in futs:
            c = futs[f]
            ok, note = f.result()
            print(f"[{'OK ' if ok else 'ERR'}] {c[0]}/{c[1]}-{c[2]} {note}")


if __name__ == "__main__":
    main()
