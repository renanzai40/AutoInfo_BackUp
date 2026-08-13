"""Todo 10 — enforce shared per-provider rate limiting across every parallel
fan-out path (llm-concurrency-remediation).

Covers the acceptance cases for the final enforcement pass:

(a) two simulated chain entries (primary model + fallback model on the
    *same* gateway) sharing ONE per-provider semaphore: 16 concurrent
    calls, semaphore width 4 -> the COMBINED in-flight count (primary
    attempts + fallback attempts together) never exceeds 4.  A bypass —
    e.g. the fallback entry resolving a different ``(provider, base_url)``
    key and thereby acquiring a second width-4 semaphore — would let up to
    8 calls run concurrently, so this test genuinely proves the shared
    bound across both models, not just a per-key bound.
(b) audit: every parallel fan-out call site is enumerated and asserted to
    resolve through the shared limiter (import-time registry + source
    checks):

      1. multi-item process workers (process.py ThreadPoolExecutor dispatch)
      2. multi-text cefr_batch (mcp/server.py _handle_cefr_batch)
      3. multi-domain cross-domain reports (generate_report(domains=...))
      4. multi-batch _group_by_theme (output/__init__.py)

    plus the global invariant: the ONLY ``.completion()`` call in
    ``src/autoinfo`` lives inside ``call_with_fallback``, under the shared
    semaphore — no uncoordinated bypass path can exist.
(c) HTTP 429 storm on both models: per-attempt jittered backoff applies
    (bounded at ``MAX_LLM_ATTEMPTS`` attempts per chain entry) and the
    shared in-flight bound still holds under load.

All LLM calls are stubbed — no real API calls, no real sleeps.
"""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import autoinfo.cefr as cefr
import autoinfo.llm as llm
import autoinfo.process as process_mod
from autoinfo.config import Config, LLMConfig
from autoinfo.llm import LLMExtractor, call_with_fallback, get_provider_semaphore

# ---------------------------------------------------------------------------
# Shared stub plumbing
# ---------------------------------------------------------------------------

PRIMARY_MODEL = "deepseek-v4-flash"
FALLBACK_MODEL = "mimo-v2.5"
GATEWAY = "https://shared-gw.invalid/v1"


class StubHTTPError(RuntimeError):
    """Mirrors a LiteLLM HTTPException — carries ``status_code``."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


def _ok_response() -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])


def _chain_config() -> Config:
    """Primary + fallback models on the SAME (provider, base_url).

    Mirrors the production setup (deepseek-v4-flash + mimo-v2.5 on one
    gateway): both chain entries resolve the semaphore key
    ``("openai", GATEWAY)``.
    """
    return Config(
        llm=LLMConfig(
            provider="openai",
            model=PRIMARY_MODEL,
            base_url=GATEWAY,
            fallback=[LLMConfig(model=FALLBACK_MODEL, base_url=GATEWAY)],
        )
    )


@pytest.fixture(autouse=True)
def _isolate_semaphore_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Width-4 env + a fresh semaphore registry per test (restored after)."""
    monkeypatch.setenv("AUTOINFO_LLM_MAX_CONCURRENCY", "4")
    saved = dict(llm._PROVIDER_SEMAPHORES)
    llm._PROVIDER_SEMAPHORES.clear()
    yield
    llm._PROVIDER_SEMAPHORES.clear()
    llm._PROVIDER_SEMAPHORES.update(saved)


class _InFlightTracker:
    """Thread-safe in-flight counter shared by every stub completion call."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.entered = 0

    def enter(self) -> None:
        with self.lock:
            self.in_flight += 1
            self.entered += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self) -> None:
        with self.lock:
            self.in_flight -= 1

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {
                "in_flight": self.in_flight,
                "max_in_flight": self.max_in_flight,
                "entered": self.entered,
            }


# ---------------------------------------------------------------------------
# (a) Two-provider (primary + fallback) shared semaphore bound
# ---------------------------------------------------------------------------


class TestTwoProviderSharedSemaphore:
    """16 concurrent calls across BOTH chain models never exceed width 4."""

    def test_combined_inflight_bounded_across_primary_and_fallback(self) -> None:
        tracker = _InFlightTracker()
        primary_slots = threading.Event()
        fallback_slots = threading.Event()
        primary_release = threading.Event()
        fallback_release = threading.Event()
        state = {"primary_entered": 0, "fallback_entered": 0}
        state_lock = threading.Lock()

        def stub_completion(**kwargs: object) -> MagicMock:
            model = str(kwargs["model"])
            is_primary = model == f"openai/{PRIMARY_MODEL}"
            tracker.enter()
            with state_lock:
                if is_primary:
                    state["primary_entered"] += 1
                    if state["primary_entered"] == 4:
                        primary_slots.set()
                else:
                    state["fallback_entered"] += 1
                    if state["fallback_entered"] == 4:
                        fallback_slots.set()
            try:
                if is_primary:
                    primary_release.wait(timeout=15)
                    raise StubHTTPError(400)
                fallback_release.wait(timeout=15)
                return _ok_response()
            finally:
                tracker.leave()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        results: list[Exception | None] = [None] * 16

        def worker(index: int) -> None:
            try:
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_chain_config(),
                )
            except Exception as exc:  # noqa: BLE001 — captured for assertions
                results[index] = exc

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(16)
            ]
            for thread in threads:
                thread.start()

            # Phase 1: exactly 4 PRIMARY calls may be inside at once.
            assert primary_slots.wait(timeout=15), "primary semaphore never filled"
            self._assert_window(tracker, expected=4)

            # Release the primaries: each retries on the FALLBACK model while
            # still holding the SAME shared semaphore slot.
            primary_release.set()
            assert fallback_slots.wait(timeout=15), "fallback semaphore never filled"
            # Combined in-flight (primary + fallback) must still be 4 — a
            # per-provider bypass (second width-4 semaphore) would allow 8.
            self._assert_window(tracker, expected=4)

            fallback_release.set()
            for thread in threads:
                thread.join(timeout=15)

        assert all(result is None for result in results), f"{results}"
        assert mock_lm.completion.call_count == 32, (
            "16 calls x 2 chain entries (primary + fallback) expected"
        )
        snap = tracker.snapshot()
        assert snap["entered"] == 32
        assert snap["max_in_flight"] == 4, (
            "COMBINED in-flight across primary+fallback exceeded the shared "
            "width-4 bound — the fallback entry must resolve the SAME "
            "(provider, base_url) semaphore key"
        )

    @staticmethod
    def _assert_window(tracker: _InFlightTracker, expected: int) -> None:
        """While the slot event is held, no more than *expected* are in."""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if tracker.snapshot()["in_flight"] > expected:
                break
            time.sleep(0.01)
        snap = tracker.snapshot()
        assert snap["in_flight"] == expected, (
            f"expected exactly {expected} calls in flight, saw {snap['in_flight']}"
        )
        assert snap["max_in_flight"] == expected

    def test_same_gateway_resolves_identical_semaphore_object(self) -> None:
        """(provider, base_url) matching yields one shared semaphore object."""
        sem_a = get_provider_semaphore("openai", GATEWAY)
        sem_b = get_provider_semaphore("openai", GATEWAY)
        assert sem_a is sem_b
        # The fallback entry's effective provider defaults to the primary's
        # (config.llm.fallback[].provider or config.llm.provider), so with an
        # explicit fallback base_url both entries share this key.
        assert _chain_config().llm.fallback[0].base_url == GATEWAY


# ---------------------------------------------------------------------------
# (b) Import-time audit: every parallel fan-out resolves via the shared limiter
# ---------------------------------------------------------------------------


class TestFanOutAudit:
    """Enumerate the 4 fan-out sites; each must funnel into the shared limiter.

    All checks are import-time/source-level so a future change that routes a
    fan-out around the semaphore fails here, not in production.
    """

    def test_only_completion_call_site_is_call_with_fallback(self) -> None:
        """Global invariant: no ``.completion()`` call outside llm.py."""
        src_root = Path(__file__).resolve().parents[2] / "src" / "autoinfo"
        violators: list[str] = []
        for py in sorted(src_root.rglob("*.py")):
            text = py.read_text(encoding="utf-8")
            if py.name == "llm.py":
                assert text.count("_litellm.completion(") == 1, (
                    "llm.py must contain exactly one completion call site "
                    "(inside call_with_fallback)"
                )
            elif ".completion(" in text:
                violators.append(str(py.relative_to(src_root)))
        assert violators == [], (
            "found completion call(s) outside call_with_fallback: "
            f"{violators} — every LLM call must route through the shared "
            "per-provider semaphore"
        )

    def test_call_with_fallback_acquires_shared_semaphore_with_jitter(
        self,
    ) -> None:
        """The funnel itself: shared semaphore + jittered backoff, bounded."""
        src = inspect.getsource(llm.call_with_fallback)
        assert "get_provider_semaphore(" in src
        assert "with semaphore:" in src
        assert "_backoff_delay(" in src
        assert "MAX_LLM_ATTEMPTS" in src

    def test_llm_extractor_routes_through_call_with_fallback(self) -> None:
        src = inspect.getsource(LLMExtractor._call_llm)
        assert "call_with_fallback(" in src

    # -- Site 1: multi-item process workers ---------------------------------

    def test_site1_process_workers_resolve_through_shared_limiter(self) -> None:
        src = inspect.getsource(process_mod.run_processing)
        # Bounded dispatch: worker pool sized by _resolve_process_workers and
        # per-item gate pool sized by _resolve_subtask_cap.
        assert "ThreadPoolExecutor(max_workers=worker_count" in src
        assert "_resolve_process_workers()" in src
        assert "concurrent.futures.ThreadPoolExecutor(" in src
        assert "_resolve_subtask_cap()" in src
        # Every item's LLM calls (extraction + gates + CEFR) resolve through
        # call_with_fallback: extraction via LLMExtractor.extract, gates via
        # quality.py, CEFR via autoinfo.cefr.classify_text.
        assert "def _process_item" in src
        assert "extractor.extract(" in src
        assert "_classify_entry_cefr(" in src
        # Bounded caps (no unbounded parallelism).
        assert process_mod._PROCESS_WORKER_CAP == 16
        assert process_mod._DEFAULT_SUBTASK_CAP == 4
        assert "min(raw, _PROCESS_WORKER_CAP)" in inspect.getsource(
            process_mod._resolve_process_workers
        )

    def test_site1_quality_gates_use_call_with_fallback(self) -> None:
        import autoinfo.quality as quality

        # run_quality_gates dispatches to the gate classes; the LLM-bearing
        # gates call call_with_fallback from their scoring methods (G3 via
        # _llm_score, G4/G5 from check; G2 dedup is pure fuzzy-title
        # matching — no LLM).
        for gate_cls, method in (
            (quality.G3RelevanceScoring, "_llm_score"),
            (quality.G4FactualConsistency, "check"),
            (quality.G5TranslationAccuracy, "check"),
        ):
            assert "call_with_fallback(" in inspect.getsource(
                getattr(gate_cls, method)
            ), f"{gate_cls.__name__}.{method} must route through call_with_fallback"

    # -- Site 2: multi-text cefr_batch --------------------------------------

    def test_site2_cefr_batch_resolves_through_shared_limiter(self) -> None:
        from autoinfo.mcp import server as mcp_server

        src = inspect.getsource(mcp_server._handle_cefr_batch)
        # Bounded fan-out: cap 8, never more than the number of texts.
        assert "ThreadPoolExecutor(" in src
        assert "min(len(texts), 8)" in src
        # Each per-text task resolves through classify_text -> call_with_fallback.
        assert "pool.submit(classify_text" in src
        assert "call_with_fallback(" in inspect.getsource(cefr.classify_text)

    # -- Site 3: multi-domain cross-domain reports --------------------------

    def test_site3_cross_domain_reports_resolve_through_shared_limiter(
        self,
    ) -> None:
        from autoinfo.mcp import server as mcp_server
        from autoinfo.output import generate_report

        # Cross-domain entry point delegates to generate_report(domains=...).
        mcp_src = inspect.getsource(mcp_server._handle_generate_cross_domain_report)
        assert "generate_report" in mcp_src
        assert "domains" in mcp_src
        # Per-domain synthesis funnels through the shared limiter: the
        # report-synthesis helper uses call_with_fallback directly, and the
        # thematic grouping (site 4) resolves via extractor.extract.
        from autoinfo.output import _call_llm_for_report_synthesis

        report_src = inspect.getsource(generate_report)
        assert "_group_by_theme(" in report_src
        assert "domains=report_domains if is_cross_domain else None" in report_src
        assert "call_with_fallback(" in inspect.getsource(
            _call_llm_for_report_synthesis
        )

    # -- Site 4: multi-batch _group_by_theme --------------------------------

    def test_site4_group_by_theme_resolves_through_shared_limiter(self) -> None:
        from autoinfo.output import (
            _GROUPING_MAX_WORKERS,
            _group_by_theme,
            _llm_json_extract,
            _run_grouping_batches,
        )

        # Bounded pool: never wider than _GROUPING_MAX_WORKERS.
        assert _GROUPING_MAX_WORKERS == 4
        batch_src = inspect.getsource(_run_grouping_batches)
        assert "ThreadPoolExecutor(" in batch_src
        assert "_GROUPING_MAX_WORKERS" in batch_src
        # Per-batch LLM call resolves through extractor.extract (which routes
        # via LLMExtractor._call_llm -> call_with_fallback).
        assert "extractor.extract(" in inspect.getsource(_llm_json_extract)
        assert "_run_grouping_batches(" in inspect.getsource(_group_by_theme)

    def test_audit_table_enumeration_is_complete(self) -> None:
        """The four documented fan-out sites all exist at their documented caps."""
        from autoinfo.mcp import server as mcp_server
        from autoinfo.output import _GROUPING_MAX_WORKERS

        sites = {
            "1. multi-item process workers": (
                process_mod._PROCESS_WORKER_CAP,
                process_mod._DEFAULT_SUBTASK_CAP,
            ),
            "2. multi-text cefr_batch": (
                # cap 8 is inlined as min(len(texts), 8) — assert its presence
                8,
                8,
            ),
            "3. multi-domain cross-domain reports": (
                _GROUPING_MAX_WORKERS,
                _GROUPING_MAX_WORKERS,
            ),
            "4. multi-batch _group_by_theme": (
                _GROUPING_MAX_WORKERS,
                _GROUPING_MAX_WORKERS,
            ),
        }
        assert sites["1. multi-item process workers"] == (16, 4)
        assert sites["2. multi-text cefr_batch"] == (8, 8)
        assert "min(len(texts), 8)" in inspect.getsource(
            mcp_server._handle_cefr_batch
        )
        assert sites["3. multi-domain cross-domain reports"] == (4, 4)
        assert sites["4. multi-batch _group_by_theme"] == (4, 4)


# ---------------------------------------------------------------------------
# (c) 429 storm on both models: bounded backoff + shared bound holds
# ---------------------------------------------------------------------------


class Test429StormSharedBound:
    """16 concurrent calls, both models always 429."""

    def test_storm_applies_bounded_backoff_and_shared_bound(self) -> None:
        tracker = _InFlightTracker()
        slots_filled = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        backoff_calls: list[float] = []
        attempts: dict[tuple[int, str], int] = {}

        def recording_backoff(attempt: int) -> float:
            backoff_calls.append(attempt)
            return 0.0

        def stub_completion(**kwargs: object) -> MagicMock:
            model = str(kwargs["model"])
            tracker.enter()
            with lock:
                key = (threading.get_ident(), model)
                attempts[key] = attempts.get(key, 0) + 1
                if tracker.snapshot()["entered"] == 4:
                    slots_filled.set()
            try:
                release.wait(timeout=15)
                raise StubHTTPError(429, "Rate limit hit: try later")
            finally:
                tracker.leave()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        results: list[Exception | None] = [None] * 16

        def worker(index: int) -> None:
            try:
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_chain_config(),
                )
            except Exception as exc:  # noqa: BLE001 — captured for assertions
                results[index] = exc

        start = time.monotonic()
        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch.object(llm, "_backoff_delay", side_effect=recording_backoff),
        ):
            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(16)
            ]
            for thread in threads:
                thread.start()

            assert slots_filled.wait(timeout=15), "semaphore slots never filled"
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if tracker.snapshot()["entered"] > 4:
                    break
                time.sleep(0.01)
            assert tracker.snapshot()["entered"] == 4
            assert tracker.snapshot()["max_in_flight"] == 4, (
                "shared bound broken during the 429 storm"
            )
            release.set()
            for thread in threads:
                thread.join(timeout=30)

        elapsed = time.monotonic() - start
        assert all(
            isinstance(result, RuntimeError) for result in results
        ), f"expected every call to fail with RuntimeError: {results}"

        # Bounded attempts per call: 16 calls x 2 chain entries x 3 attempts.
        assert mock_lm.completion.call_count == (
            16 * 2 * llm.MAX_LLM_ATTEMPTS
        ), "attempts per chain entry must be bounded by MAX_LLM_ATTEMPTS"
        # Per-attempt backoff applies: 2 retries per chain entry per call.
        assert len(backoff_calls) == 16 * 2 * (llm.MAX_LLM_ATTEMPTS - 1), (
            "every retry must go through the jittered backoff"
        )
        per_chain_attempts = sorted(attempts.values())
        assert per_chain_attempts and per_chain_attempts[-1] == llm.MAX_LLM_ATTEMPTS
        assert per_chain_attempts[0] == llm.MAX_LLM_ATTEMPTS, (
            "every (call, model) pair must exhaust exactly MAX_LLM_ATTEMPTS"
        )
        assert tracker.snapshot()["max_in_flight"] == 4
        assert elapsed < 30.0, "storm must complete fast (backoff mocked, no hang)"
