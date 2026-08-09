#!/usr/bin/env python3
"""Batch-generate products for all matrix required cells (E8).

For each (domain, product, format) required cell, generate the product via the
real generation functions and persist to outputs/<domain>/. Skips cells that
already have evidence. Result-driven: verifies the generated artifact exists.

Usage: HOME=/home/renanzai python3 scripts/fill_matrix_products.py [--dry-run]
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    generate_digest,
    generate_presentation,
    generate_report,
    generate_tutorial,
)

DOMAINS = ["medical-research", "tech-ai-developer"]
PRODUCTS = ["digest", "report", "tutorial", "presentation",
            "premium-briefing", "column", "magazine-digest", "enterprise-briefing"]
FORMATS = ["markdown", "html", "json", "agent", "audio", "epub", "audiobook"]

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"


def cell_evidence(domain: str, product: str, fmt: str) -> bool:
    """True if an artifact already exists for this cell."""
    d = OUTPUTS / domain
    if not d.is_dir():
        return False
    for f in d.iterdir():
        if f.name.startswith(f"{product}-{fmt}-"):
            return True
    return False


def persist(domain: str, product: str, fmt: str, content) -> Path:
    """Persist content under outputs/<domain>/ with the matrix-recognized name."""
    d = OUTPUTS / domain
    d.mkdir(parents=True, exist_ok=True)
    ext = {"markdown": ".md", "html": ".html", "json": ".json", "agent": ".json",
           "audio": ".mp3", "epub": ".epub", "audiobook": ".zip"}[fmt]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    p = d / f"{product}-{fmt}-{stamp}{ext}"
    if fmt in ("audio", "epub", "audiobook"):
        import base64
        p.write_bytes(base64.b64decode(content))
    elif fmt in ("json", "agent"):
        import json as _json
        if isinstance(content, str):
            try:
                content = _json.loads(content)
            except Exception:
                pass
        p.write_text(_json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        p.write_text(str(content), encoding="utf-8")
    return p


def gen_one(domain: str, product: str, fmt: str) -> tuple[bool, str]:
    """Generate one product cell. Returns (ok, note)."""
    try:
        if product == "digest":
            out = generate_digest(domain=domain, period="weekly", format=fmt)
        elif product == "report":
            out = generate_report(domain=domain, period="weekly", format=fmt)
        elif product == "tutorial":
            out = generate_tutorial(domain=domain, format=fmt)
        elif product == "presentation":
            out = generate_presentation(domain=domain, topic="", format=fmt)
        elif product in ("premium-briefing", "column", "magazine-digest", "enterprise-briefing"):
            # These flow through generate_report with a product template.
            template = next(
                (row["template"] for row in PRODUCT_TEMPLATES if row["name"] == product),
                None,
            )
            if template is None:
                return False, f"no template for {product}"
            if product == "column":
                out = generate_report(domain=domain, period="weekly", format=fmt,
                                      report_type="column", product_template=template)
            else:
                out = generate_report(domain=domain, period="weekly", format=fmt,
                                      product_template=template)
        else:
            return False, f"unknown product {product}"
        if not out:
            return False, "empty output"
        p = persist(domain, product, fmt, out)
        return p.stat().st_size > 0, f"persisted {p.name} ({p.stat().st_size}b)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"


async def main() -> None:
    dry = "--dry-run" in sys.argv
    cells = [(d, p, f) for d in DOMAINS for p in PRODUCTS for f in FORMATS]
    # Only required cells
    import yaml
    spec = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "docs/dev/specs/end-user-matrix.yaml").read_text()
    )
    required = {(c["domain"], c["product"], c["format"]) for c in spec["required_cells"]}
    todo = [c for c in cells if c in required and not cell_evidence(*c)]
    print(f"required={len(required)} todo={len(todo)} (already produced={len(required)-len(todo)})")
    if dry:
        for c in todo:
            print("  ", c)
        return

    # Result-driven: run cells concurrently (measured: concurrency=5 is ~3.5x
    # faster than serial with zero rate-limit errors on OpenCode Go).
    from concurrent.futures import ThreadPoolExecutor

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(gen_one, *c): c for c in todo}
        for fut in futs:
            c = futs[fut]
            t0 = time.time()
            try:
                success, note = fut.result()
            except Exception as exc:
                success, note = False, f"{type(exc).__name__}: {str(exc)[:120]}"
            dt = time.time() - t0
            tag = "OK " if success else "ERR"
            print(f"[{tag}] {c[0]}/{c[1]}-{c[2]} ({dt:.0f}s) {note}")
            if success:
                ok += 1
            else:
                fail += 1
    print(f"\nDONE: ok={ok} fail={fail}")


if __name__ == "__main__":
    asyncio.run(main())
