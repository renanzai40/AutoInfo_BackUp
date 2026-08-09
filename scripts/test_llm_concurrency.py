#!/usr/bin/env python3
"""Measure LLM concurrency: how fast do N parallel calls complete, do we hit rate limits?"""
import sys, os, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("AUTOINFO_LLM_API_KEY", os.environ.get("OPENCODE_GO_KEY", ""))

from autoinfo.config import load_config
from autoinfo.llm import LLMExtractor
from autoinfo.models import Item


def one_call(model: str, i: int) -> tuple[int, float, str]:
    cfg = load_config(".autoinfo/config.yaml")
    # override model for this worker
    cfg.llm.model = model
    ext = LLMExtractor(cfg)
    item = Item(
        id=f"conc-test-{i}", source_name="test", source_type="internal",
        source_url="", title="Summary",
        content=f"Summarize item {i}: The knowledge base covers IVF treatment outcomes, donor selection criteria, and clinic marketing strategies in reproductive medicine.",
    )
    t0 = time.time()
    try:
        r = ext.extract(item, schema=["summary"])
        dt = time.time() - t0
        return i, dt, "OK"
    except Exception as e:
        dt = time.time() - t0
        return i, dt, f"{type(e).__name__}: {str(e)[:80]}"


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
        "err_samples": [e[2][:60] for e in errs[:3]],
    }


if __name__ == "__main__":
    print("=== 串行基线 (concurrency=1) ===")
    print(run_concurrency(1, total=6))
    for n in (3, 5):
        print(f"=== 并发 {n} ===")
        print(run_concurrency(n, total=10))
