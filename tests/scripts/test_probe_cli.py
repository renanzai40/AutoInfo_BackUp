"""Tests for the LLM-concurrency probe CLI (scripts/test_llm_concurrency.py).

Covers:

- ``run_concurrency`` returns ``p95`` and ``rate_limit_count`` in its dict
- ``main(["--workers", "3", "--total", "6"])`` parses the args and prints a
  row containing p95 + rate_limit_count
- No-args invocation keeps the serial-baseline + (1,3,5) default behavior
- Empty API key -> ``SKIPPED`` + reason, no network, exit 0

``one_call`` is always mocked — no real LLM calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package — load it via sys.path like the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import test_llm_concurrency as probe  # noqa: E402


def _ok_call(model: str, i: int) -> tuple[int, float, str]:
    """Instant OK call with a fixed 1.0s duration."""
    return i, 1.0, "OK"


def _rate_limited_call(model: str, i: int) -> tuple[int, float, str]:
    """Instant 429 rate-limited call."""
    return i, 0.2, "HTTPError: 429 Rate Limit exceeded for provider openai"


def test_run_concurrency_returns_p95_and_rate_limit_count() -> None:
    """The result dict carries p95 (95th pct of durations) + rate_limit_count."""
    # 12 calls: 11 OK @ 1.0s, 1 rate-limited @ 0.2s
    calls = [_ok_call("m", i) for i in range(11)] + [_rate_limited_call("m", 11)]
    with patch.object(probe, "one_call", side_effect=calls):
        row = probe.run_concurrency(4, total=12)

    assert row["concurrency"] == 4
    assert row["total"] == 12
    assert row["ok"] == 11
    assert row["err"] == 1
    assert row["rate_limit_count"] == 1
    # nearest-rank p95 of [0.2, 1.0 x11] is the max duration 1.0
    assert row["p95"] == 1.0


def test_main_parses_workers_and_total_and_prints_row(capsys: pytest.CaptureFixture[str]) -> None:
    """``main(["--workers", "3", "--total", "6"])`` emits a single row dict
    containing p95 + rate_limit_count."""
    with (
        patch.object(probe, "one_call", side_effect=[_ok_call("m", i) for i in range(6)]),
        patch.object(probe, "_resolve_api_key", return_value="fake-key"),
    ):
        code = probe.main(["--workers", "3", "--total", "6"])

    out = capsys.readouterr().out
    assert code == 0
    assert "'concurrency': 3" in out
    assert "'total': 6" in out
    assert "'p95'" in out
    assert "'rate_limit_count'" in out


def test_main_no_args_keeps_serial_baseline_and_135_sequence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No-args fallback: serial baseline (1, total=6) then (3, total=10), (5, total=10)."""
    # 6 + 10 + 10 = 26 calls
    side = [_ok_call("m", i) for i in range(26)]
    with (
        patch.object(probe, "one_call", side_effect=side),
        patch.object(probe, "_resolve_api_key", return_value="fake-key"),
    ):
        code = probe.main([])

    out = capsys.readouterr().out
    assert code == 0
    # three rows printed: concurrency 1 (baseline), then 3 and 5
    assert "'concurrency': 1" in out
    assert "'total': 6" in out
    assert "'concurrency': 3" in out
    assert "'concurrency': 5" in out
    assert "'total': 10" in out


def test_main_skips_without_key(capsys: pytest.CaptureFixture[str]) -> None:
    """No API key available -> SKIPPED + reason, no LLM calls, exit 0."""
    with (
        patch.object(probe, "_resolve_api_key", return_value=""),
        patch.object(probe, "one_call", side_effect=AssertionError("must not run")),
    ):
        code = probe.main(["--workers", "3", "--total", "6"])

    out = capsys.readouterr().out
    assert code == 0
    assert "SKIPPED" in out
    assert "no LLM API key" in out.lower() or "api key" in out.lower()
