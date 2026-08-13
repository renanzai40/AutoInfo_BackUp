"""Tests for the ``cefr_batch`` MCP handler concurrency contract.

Todo-5 of the llm-concurrency-remediation plan: ``_handle_cefr_batch`` must
fan out per-text classification across a bounded ``ThreadPoolExecutor``
(default <= 8 workers, ``AUTOINFO_CEFR_BATCH_WORKERS`` env override) while:

- preserving result order (futures are keyed by original index and
  collected in insertion order),
- isolating per-item failures (one raising text yields a per-item error
  entry and never breaks the other texts),
- routing every per-text LLM call through the shared semaphore-guarded
  ``call_with_fallback`` path (llm.py) so the fan-out stays rate-limited
  per provider rather than uncoordinated.
"""

from __future__ import annotations

import random
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from autoinfo.llm import get_provider_semaphore
from autoinfo.mcp.server import _handle_cefr_batch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sleeping_classifier(
    monitor: dict[str, object], *, delay: float = 0.02
):
    """Build a ``classify_text`` stand-in that measures in-flight concurrency.

    ``monitor`` is a shared dict with ``lock``, ``in_flight`` and ``max_seen``
    (both length-1 lists mutated in place).  The classifier sleeps *inside*
    the in-flight window so concurrent execution is genuinely observable.
    """

    def _classify(text: str, lang: str = "en", model_config: dict | None = None):
        lock = monitor["lock"]
        in_flight = monitor["in_flight"]
        max_seen = monitor["max_seen"]
        with lock:  # type: ignore[arg-type]
            in_flight[0] += 1  # type: ignore[index]
            max_seen[0] = max(max_seen[0], in_flight[0])  # type: ignore[index]
        try:
            time.sleep(delay)
            return {"cefr_level": "B1", "confidence": 0.85}
        finally:
            with lock:  # type: ignore[arg-type]
                in_flight[0] -= 1  # type: ignore[index]

    return _classify


def _make_monitor() -> dict[str, object]:
    return {
        "lock": threading.Lock(),
        "in_flight": [0],
        "max_seen": [0],
    }


# ---------------------------------------------------------------------------
# (a) Parallel fan-out, bounded by the worker cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("workers_env", "cap"),
    [
        (None, 8),  # default bound
        ("3", 3),  # env override bound
    ],
)
def test_parallel_fanout_respects_bound(
    monkeypatch: pytest.MonkeyPatch, workers_env: str | None, cap: int
) -> None:
    """32 texts: in-flight must exceed 1 (parallel) but stay <= the cap."""
    texts = [f"text-{i:02d}" for i in range(32)]
    monitor = _make_monitor()
    classifier = _make_sleeping_classifier(monitor, delay=0.02)

    if workers_env is None:
        monkeypatch.delenv("AUTOINFO_CEFR_BATCH_WORKERS", raising=False)
    else:
        monkeypatch.setenv("AUTOINFO_CEFR_BATCH_WORKERS", workers_env)

    with mock.patch("autoinfo.cefr.classify_text", new=classifier):
        out = _handle_cefr_batch(texts, lang="en")

    assert out["total"] == 32
    assert out["errors"] == 0
    # Parallel: more than one classification ran concurrently...
    assert monitor["max_seen"][0] > 1
    # ...but the fan-out never exceeded the worker bound.
    assert monitor["max_seen"][0] <= cap
    # Order preserved even under concurrent execution.
    assert [r["text"] for r in out["results"]] == texts


# ---------------------------------------------------------------------------
# (b) Result order == input order
# ---------------------------------------------------------------------------


def test_result_order_matches_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """32 texts classified with jittered timing: results stay index-ordered."""
    texts = [f"para-{i:03d}-" + "x" * (i % 7) for i in range(32)]
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    expected = [levels[i % len(levels)] for i in range(32)]

    def _classify(text: str, lang: str = "en", model_config: dict | None = None):
        # Random jitter makes completion order differ from submission order,
        # so a reorder bug would surface deterministically in the asserts.
        time.sleep(random.uniform(0.0, 0.02))
        idx = int(text.split("-")[1])
        return {"cefr_level": expected[idx], "confidence": 0.9}

    monkeypatch.delenv("AUTOINFO_CEFR_BATCH_WORKERS", raising=False)
    with mock.patch("autoinfo.cefr.classify_text", new=_classify):
        out = _handle_cefr_batch(texts, lang="en")

    assert out["errors"] == 0
    assert [r["text"] for r in out["results"]] == texts
    assert [r["cefr_level"] for r in out["results"]] == expected
    assert [r["confidence"] for r in out["results"]] == [0.9] * 32


# ---------------------------------------------------------------------------
# (c) Per-item error isolation
# ---------------------------------------------------------------------------


def test_per_item_error_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """One raising text -> per-item error entry; the rest succeed in order."""
    texts = [f"text-{i:02d}" for i in range(12)]
    boom = {2, 7}

    def _classify(text: str, lang: str = "en", model_config: dict | None = None):
        time.sleep(0.01)
        if int(text.rsplit("-", 1)[1]) in boom:
            raise RuntimeError(f"boom {text}")
        return {"cefr_level": "B2", "confidence": 0.8}

    monkeypatch.delenv("AUTOINFO_CEFR_BATCH_WORKERS", raising=False)
    with mock.patch("autoinfo.cefr.classify_text", new=_classify):
        out = _handle_cefr_batch(texts, lang="en")

    assert out["total"] == 12
    assert out["errors"] == len(boom) == 2
    results = out["results"]
    # Order is preserved even when some items fail.
    assert [r["text"] for r in results] == texts
    for i, entry in enumerate(results):
        if i in boom:
            assert "error" in entry and "boom" in entry["error"]
            assert "cefr_level" not in entry
        else:
            assert entry["cefr_level"] == "B2"
            assert "error" not in entry


# ---------------------------------------------------------------------------
# Semaphore-guarded LLM path (todo-1 integration)
# ---------------------------------------------------------------------------


def test_batch_routes_through_call_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The un-mocked real path must resolve via call_with_fallback (llm.py),
    which is where the shared per-provider semaphore is acquired."""
    texts = ["one", "two", "three", "four"]
    calls: list[dict] = []

    def _fake_call_with_fallback(messages: list, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="B2"))]
        )

    monkeypatch.delenv("AUTOINFO_CEFR_BATCH_WORKERS", raising=False)
    with mock.patch("autoinfo.cefr.call_with_fallback", new=_fake_call_with_fallback):
        out = _handle_cefr_batch(texts, lang="en")

    assert out["errors"] == 0
    assert len(calls) == len(texts)
    assert all(r["cefr_level"] == "B2" for r in out["results"])


def test_shared_provider_semaphore_identity() -> None:
    """Todo-1 shared limiter: same (provider, base_url) -> same semaphore
    object, so fan-out across callers is rate-limited by one limiter."""
    s1 = get_provider_semaphore("openai", "https://example.test/v1")
    s2 = get_provider_semaphore("openai", "https://example.test/v1")
    s3 = get_provider_semaphore("openai", "https://example.test/other")
    assert s1 is s2
    assert s1 is not s3
