#!/usr/bin/env python3
"""Measure LLM concurrency: how fast do N parallel calls complete, do we hit rate limits?

Usage:
    python scripts/test_llm_concurrency.py                    # default: serial baseline + (1,3,5)
    python scripts/test_llm_concurrency.py --workers 16 --total 12
"""
import argparse
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.config import load_config
from autoinfo.llm import LLMExtractor
from autoinfo.models import Item

# Matches provider rate-limit error messages (HTTP 429 / "Rate Limit").
_RATE_LIMIT_RE = re.compile(r"429|Rate Limit", re.IGNORECASE)


def _resolve_api_key() -> str:
    """Resolve the API key from the env var or the inline config key."""
    env_key = os.environ.get("AUTOINFO_LLM_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        cfg = load_config(".autoinfo/config.yaml")
        return (getattr(cfg.llm, "api_key", "") or "").strip()
    except Exception:
        return ""


def one_call(model: str, i: int) -> tuple[int, float, str]:
    cfg = load_config(".autoinfo/config.yaml")
    # override model for this worker
    cfg.llm.model = model
    ext = LLMExtractor(cfg)
    item = Item(
        id=f"conc-test-{i}", source_name="test", source_type="internal",
        source_url="", title="Summary",
        content=(
            f"Summarize item {i}: The knowledge base covers IVF treatment outcomes, "
            "donor selection criteria, and clinic marketing strategies in "
            "reproductive medicine."
        ),
    )
    t0 = time.time()
    try:
        ext.extract(item, schema=["summary"])
        dt = time.time() - t0
        return i, dt, "OK"
    except Exception as e:
        dt = time.time() - t0
        return i, dt, f"{type(e).__name__}: {str(e)[:80]}"


def _p95(durations: list[float]) -> float:
    """Nearest-rank 95th percentile of per-call durations (0.0 when empty)."""
    if not durations:
        return 0.0
    s = sorted(durations)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def run_concurrency(n: int, model: str = "deepseek-v4-flash", total: int = 12) -> dict:
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = [ex.submit(one_call, model, i) for i in range(total)]
        for f in futs:
            results.append(f.result())
    wall = time.time() - t0
    oks = [r for r in results if r[2] == "OK"]
    errs = [r for r in results if r[2] != "OK"]
    avg = sum(r[1] for r in oks) / len(oks) if oks else 0
    return {
        "concurrency": n, "total": total, "wall": round(wall, 1),
        "ok": len(oks), "err": len(errs), "avg_per_call": round(avg, 1),
        "p95": round(_p95([r[1] for r in results]), 1),
        "rate_limit_count": sum(1 for r in results if _RATE_LIMIT_RE.search(r[2])),
        "err_samples": [e[2][:60] for e in errs[:3]],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=None,
        help="concurrency level; omit for the default serial-baseline + (1,3,5) run",
    )
    parser.add_argument(
        "--total", type=int, default=12, help="number of LLM calls per row (default 12)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _resolve_api_key():
        print(
            "SKIPPED: no LLM API key available "
            "(AUTOINFO_LLM_API_KEY unset and .autoinfo/config.yaml has no llm.api_key)"
        )
        return 0
    if args.workers is None:
        print("=== 串行基线 (concurrency=1) ===")
        print(run_concurrency(1, total=6))
        for n in (3, 5):
            print(f"=== 并发 {n} ===")
            print(run_concurrency(n, total=10))
        return 0
    print(run_concurrency(args.workers, total=args.total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
