"""LLM-judge calibration mechanism: D-工-2 evidence for the best-practice review.

Implements the D-工-2 calibration protocol (Airbnb EDD; arXiv 2025-2026
judge-bias research): a golden set of curated cases with known verdicts,
run through the judge multiple times, scored by agreement (accuracy) and
Cohen's kappa.

Design (matches the review's "grade the judge, not the prompt" principle):

- ``GOLDEN_CASES`` — a seed golden set (skeleton for the target 50-100).
  Each case: ``{"id", "assertion", "output", "gold"}`` where ``gold`` is the
  human-verified verdict ("PASS"/"FAIL"). Seed cases are representative of
  the G4 factual-consistency / llm_assert judging tasks.
- ``cohen_kappa`` — Cohen's kappa for two raters over two verdict classes,
  computed from the confusion matrix. Returns ``None`` when kappa is
  undefined (perfect agreement denominator or degenerate marginals).
- ``run_calibration(judge_fn, cases, trials)`` — runs the judge on every
  case per trial, aggregates per-trial accuracy + kappa, and reports
  trial-to-trial consistency (the multi-trial signal that detects judge
  instability).
- ``main`` — with an LLM key configured, wires the real
  ``autoinfo.mcp.validation._llm_judge``; without one it prints the
  ``unconfigured`` status (never a silent pass). Tests inject a stub judge.

Run from the project root: ``python3 scripts/llm_judge_calibration.py``
(calls the real judge when ``AUTOINFO_LLM_API_KEY`` is set).

Writes a timestamped report to
``validation-runs/coverage/llm-judge-calibration-<date>.json`` and prints a
summary to stdout. The kappa math is pure — testable without any LLM.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from statistics import mean
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "validation-runs" / "coverage"

JudgeFn = Callable[[str, Any], dict[str, Any]]

# Seed golden set — skeleton for the D-工-2 target of 50-100 cases. Each case
# mirrors the G4 / llm_assert judging contract (assertion + tool output →
# PASS/FAIL), with a human-verified gold verdict.
GOLDEN_CASES: list[dict[str, Any]] = [
    {
        "id": "g4-001",
        "assertion": (
            "The tool output contains a processed_count greater than 0, "
            "proving at least one item was processed successfully."
        ),
        "output": {"processed_count": 3, "status": "ok", "failed": 0},
        "gold": "PASS",
    },
    {
        "id": "g4-002",
        "assertion": (
            "The tool output contains a processed_count greater than 0, "
            "proving at least one item was processed successfully."
        ),
        "output": {"processed_count": 0, "status": "ok", "failed": 3},
        "gold": "FAIL",
    },
    {
        "id": "g4-003",
        "assertion": "The result contains custom_fields with key 'methodology'.",
        "output": {
            "custom_fields": {
                "main_findings": "CRISPR efficacy confirmed",
                "methodology": "randomized controlled trial",
            }
        },
        "gold": "PASS",
    },
    {
        "id": "g4-004",
        "assertion": "The result contains custom_fields with key 'methodology'.",
        "output": {"custom_fields": {"main_findings": "no methodology extracted"}},
        "gold": "FAIL",
    },
    {
        "id": "g4-005",
        "assertion": (
            "The response answers the query about CRISPR gene editing — it "
            "must mention gene editing or genetic engineering."
        ),
        "output": {
            "answer": (
                "CRISPR-Cas9 enables targeted gene editing by cutting DNA at "
                "a programmed site."
            )
        },
        "gold": "PASS",
    },
    {
        "id": "g4-006",
        "assertion": (
            "The response answers the query about CRISPR gene editing — it "
            "must mention gene editing or genetic engineering."
        ),
        "output": {"answer": "The weather in Shanghai is sunny today."},
        "gold": "FAIL",
    },
    {
        "id": "g4-007",
        "assertion": "The error envelope carries code 'DomainNotFound'.",
        "output": {
            "success": False,
            "error": {
                "code": "DomainNotFound",
                "message": "Domain 'xyz' not found. Use add_domain().",
                "actionable": True,
            },
        },
        "gold": "PASS",
    },
    {
        "id": "g4-008",
        "assertion": "The error envelope carries code 'DomainNotFound'.",
        "output": {
            "success": False,
            "error": {
                "code": "LLM_NOT_CONFIGURED",
                "message": "No LLM key configured. Set AUTOINFO_LLM_API_KEY.",
                "actionable": True,
            },
        },
        "gold": "FAIL",
    },
]


def cohen_kappa(
    gold: list[str], judged: list[str]
) -> float | None:
    """Cohen's kappa for two raters over PASS/FAIL verdict classes.

    Parameters
    ----------
    gold:
        Human-verified gold verdicts.
    judged:
        Judge verdicts, same length as *gold*.

    Returns
    -------
    float | None
        ``(p_o - p_e) / (1 - p_e)``; ``None`` when kappa is undefined
        (zero denominator: perfect agreement or degenerate marginals).
    """
    if len(gold) != len(judged) or not gold:
        return None
    n = len(gold)
    classes = ("PASS", "FAIL")
    # confusion matrix: rows = gold, cols = judged
    c: dict[tuple[str, str], int] = {}
    for g, j in zip(gold, judged):
        key = (g if g in classes else "FAIL", j if j in classes else "FAIL")
        c[key] = c.get(key, 0) + 1
    a = c.get(("PASS", "PASS"), 0)
    d = c.get(("FAIL", "FAIL"), 0)
    b = c.get(("PASS", "FAIL"), 0)  # gold PASS, judge FAIL
    c_ = c.get(("FAIL", "PASS"), 0)  # gold FAIL, judge PASS
    p_o = (a + d) / n
    p_e = ((a + b) * (a + c_) + (b + d) * (c_ + d)) / (n * n)
    denom = 1.0 - p_e
    if denom == 0.0:
        return None
    return (p_o - p_e) / denom


def _accuracy(gold: list[str], judged: list[str]) -> float:
    if not gold:
        return 0.0
    return sum(1 for g, j in zip(gold, judged) if g == j) / len(gold)


def run_calibration(
    judge_fn: JudgeFn,
    cases: list[dict[str, Any]] | None = None,
    trials: int = 1,
) -> dict[str, Any]:
    """Run the judge over the golden set for *trials* independent passes.

    Parameters
    ----------
    judge_fn:
        ``judge_fn(assertion, output) -> {"verdict": "PASS"|"FAIL", ...}``
        (the real ``_llm_judge`` in production; a stub in tests).
    cases:
        Golden cases; defaults to :data:`GOLDEN_CASES`.
    trials:
        Number of independent judge passes (detects judge instability).

    Returns
    -------
    dict
        Per-trial rows (``trial``, ``accuracy``, ``kappa``) plus aggregated
        ``mean_accuracy``, ``mean_kappa``, ``kappa_spread`` (max-min across
        trials — a large spread flags unstable judging), and per-case rows
        for the first trial.
    """
    if cases is None:
        cases = GOLDEN_CASES
    gold = [c["gold"] for c in cases]
    trial_rows: list[dict[str, Any]] = []
    per_case: list[dict[str, Any]] = []
    for trial in range(1, trials + 1):
        judged: list[str] = []
        for case in cases:
            try:
                result = judge_fn(case["assertion"], case["output"])
                verdict = str(result.get("verdict", "")).strip().upper()
            except Exception:
                verdict = "FAIL"
            judged.append(verdict)
            if trial == 1:
                per_case.append({
                    "id": case["id"],
                    "gold": case["gold"],
                    "judged": verdict,
                    "correct": verdict == case["gold"],
                })
        kappa = cohen_kappa(gold, judged)
        trial_rows.append({
            "trial": trial,
            "accuracy": round(_accuracy(gold, judged), 3),
            "kappa": round(kappa, 3) if kappa is not None else None,
        })

    kappas = [t["kappa"] for t in trial_rows if t["kappa"] is not None]
    return {
        "golden_set_size": len(cases),
        "trials": trials,
        "mean_accuracy": round(
            mean(t["accuracy"] for t in trial_rows), 3
        ),
        "mean_kappa": round(mean(kappas), 3) if kappas else None,
        "kappa_spread": round(max(kappas) - min(kappas), 3) if len(kappas) > 1 else 0.0,
        "trial_rows": trial_rows,
        "per_case": per_case,
    }


def main() -> int:
    # Real judge requires the autoinfo package + an LLM key. When either is
    # missing the run reports unconfigured — never a silent pass.
    try:
        from autoinfo.mcp.validation import _llm_judge
    except ImportError:
        _llm_judge = None

    has_key = bool(
        __import__("os").environ.get("AUTOINFO_LLM_API_KEY")
        or __import__("os").environ.get("OPENAI_API_KEY")
    )
    if _llm_judge is None or not has_key:
        print(
            "LLM-judge calibration (D-工-2) — unconfigured: no LLM key / "
            "autoinfo package. Set AUTOINFO_LLM_API_KEY to run a live "
            "calibration. Kappa math validated by tests/validation/"
            "test_llm_judge_calibration.py."
        )
        out = {
            "status": "unconfigured",
            "golden_set_size": len(GOLDEN_CASES),
            "note": (
                "Run with AUTOINFO_LLM_API_KEY set to execute a live "
                "calibration (trials via --trials)."
            ),
        }
    else:
        trials = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 1
        result = run_calibration(_llm_judge, trials=trials)
        print(
            f"LLM-judge calibration (D-工-2) — "
            f"{datetime.date.today().isoformat()}"
        )
        print(f"Golden set: {result['golden_set_size']} cases, "
              f"{result['trials']} trial(s)")
        print(f"Mean accuracy: {result['mean_accuracy']}, "
              f"mean kappa: {result['mean_kappa']}, "
              f"kappa spread: {result['kappa_spread']}")
        out = {"status": "calibrated", **result}

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (
        f"llm-judge-calibration-{datetime.date.today().isoformat()}.json"
    )
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
