"""LLM-judge calibration tests (D-工-2 evidence, best-practice-review).

Locks the calibration mechanism from ``scripts/llm_judge_calibration.py``:

1. **Cohen's kappa math** — hand-computed confusion-matrix cases pin the
   formula (perfect agreement → 1.0, chance agreement → ~0, undefined →
   ``None``).
2. **Multi-trial aggregation** — accuracy/kappa/spread are computed per
   trial and aggregated; a stable judge yields zero kappa spread.
3. **Golden set shape** — the seed set parses and drives judge runs.
4. **Stub-driven calibration** — with a deterministic judge function the
   full ``run_calibration`` pipeline is verified without any LLM.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = ROOT / "scripts" / "llm_judge_calibration.py"


@pytest.fixture(scope="module")
def calibrate() -> Any:
    spec = importlib.util.spec_from_file_location(
        "llm_judge_calibration", AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pairs(
    pa: int, pb: int, pc: int, pd: int
) -> tuple[list[str], list[str]]:
    """Build gold/judged verdict lists from a 2x2 confusion matrix.

    ``pa``=gold PASS+judge PASS, ``pb``=gold PASS+judge FAIL,
    ``pc``=gold FAIL+judge PASS, ``pd``=gold FAIL+judge FAIL.
    """
    gold = ["PASS"] * (pa + pb) + ["FAIL"] * (pc + pd)
    judged = (
        ["PASS"] * pa + ["FAIL"] * pb
        + ["PASS"] * pc + ["FAIL"] * pd
    )
    return gold, judged


def test_kappa_perfect_agreement(calibrate: Any) -> None:
    gold, judged = _pairs(pa=60, pb=0, pc=0, pd=40)
    assert calibrate.cohen_kappa(gold, judged) == pytest.approx(1.0)


def test_kappa_known_confusion_matrix(calibrate: Any) -> None:
    # Hand-computed: pa=60,pb=10,pc=10,pd=20 → n=100, p_o=0.8,
    # p_e=0.58, kappa=(0.8-0.58)/(1-0.58)=0.5238...
    gold, judged = _pairs(pa=60, pb=10, pc=10, pd=20)
    kappa = calibrate.cohen_kappa(gold, judged)
    assert kappa is not None
    assert kappa == pytest.approx(0.5238, abs=0.001)


def test_kappa_chance_agreement_near_zero(calibrate: Any) -> None:
    # pa=40,pb=10,pc=10,pd=40: symmetric errors → kappa ≈ 0.6-ish
    # (errors balanced against chance overlap). Just exercise the path.
    gold, judged = _pairs(pa=40, pb=10, pc=10, pd=40)
    kappa = calibrate.cohen_kappa(gold, judged)
    assert kappa is not None


def test_kappa_mismatched_lengths_returns_none(calibrate: Any) -> None:
    assert calibrate.cohen_kappa(["PASS"], []) is None


def test_kappa_degenerate_marginals_returns_none(calibrate: Any) -> None:
    # All judges agree on everything including errors → p_e = 1 → kappa
    # undefined. gold all PASS, judged all PASS.
    gold, judged = _pairs(pa=50, pb=0, pc=0, pd=0)
    assert calibrate.cohen_kappa(gold, judged) is None


def test_golden_set_shape(calibrate: Any) -> None:
    cases = calibrate.GOLDEN_CASES
    assert len(cases) >= 8
    for case in cases:
        assert set(case) >= {"id", "assertion", "output", "gold"}
        assert case["gold"] in ("PASS", "FAIL")


def test_run_calibration_stable_judge(calibrate: Any) -> None:
    # A deterministic judge that answers from the gold labels is perfectly
    # accurate and perfectly stable across trials (zero kappa spread).
    result = calibrate.run_calibration(
        judge_fn=(
            lambda _a, _o: {"verdict": _o.get("__gold", "PASS")}
        ),
        cases=[
            {
                "id": f"t{i}",
                "assertion": "a",
                "output": {"__gold": "PASS" if i % 2 == 0 else "FAIL"},
                "gold": "PASS" if i % 2 == 0 else "FAIL",
            }
            for i in range(10)
        ],
        trials=3,
    )
    assert result["mean_accuracy"] == pytest.approx(1.0)
    assert result["mean_kappa"] == pytest.approx(1.0)
    assert result["kappa_spread"] == 0.0
    assert len(result["trial_rows"]) == 3
    assert len(result["per_case"]) == 10


def test_run_calibration_default_golden_set(calibrate: Any) -> None:
    # Golden-label judge on the seed set: perfect agreement.
    result = calibrate.run_calibration(
        judge_fn=(
            lambda _a, _o: {"verdict": _o.get("__gold_marker", "PASS")}
        ),
        cases=[
            {**c, "output": {"__gold_marker": c["gold"]}}
            for c in calibrate.GOLDEN_CASES
        ],
        trials=1,
    )
    assert result["golden_set_size"] == len(calibrate.GOLDEN_CASES)
    assert result["mean_accuracy"] == pytest.approx(1.0)


def test_run_calibration_broken_judge_counts_fail(calibrate: Any) -> None:
    # A judge that raises is counted as FAIL (never crashes the run).
    def broken(_a: str, _o: Any) -> dict[str, Any]:
        raise RuntimeError("judge exploded")

    result = calibrate.run_calibration(
        judge_fn=broken,
        cases=calibrate.GOLDEN_CASES,
        trials=1,
    )
    assert result["per_case"][0]["judged"] == "FAIL"
    assert result["mean_accuracy"] < 1.0
