"""Per-provider shared rate limiting + jittered 429/5xx backoff (todo 1).

Covers the acceptance cases for the llm-concurrency-remediation plan:

(a) stub 429, 429, 200 -> success after exactly 3 attempts, with
    ``time.sleep`` recorded (mocked backoff delays).
(b) stub 5xx x3 -> aggregate ``RuntimeError`` after exactly 3 attempts,
    no infinite loop.
(c) stub 400 -> NO retry (1 attempt only).
(d) semaphore = 4, 16 concurrent calls to the same provider -> max
    observed in-flight == 4 (deterministic barrier, no flaky sleeps).
(e) fallback chain still walks ``[primary] + [fallback]`` in order, each
    chain entry receiving the same retry/backoff treatment.

Plus regression guards:

- always-429 stub: the *last* error surfaces after 3 attempts and the
  call completes in well under 30 s (backoff is mocked, never hangs).
- semaphores are keyed per ``(provider, base_url)`` — two providers
  never share a global lock.
- retryable detection also honors stubs that expose only ``.status``
  (some providers) as well as ``.status_code`` (LiteLLM HTTPExceptions).

All LLM calls are stubbed — no real API calls, no real sleeps.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import Config, LLMConfig
from autoinfo.llm import LLMExtractor, call_with_fallback

# ---------------------------------------------------------------------------
# Stub provider errors
# ---------------------------------------------------------------------------


class StubHTTPError(RuntimeError):
    """Mirrors a LiteLLM HTTPException — carries ``status_code``."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


class StubStatusError(RuntimeError):
    """Some providers expose only ``status`` — retryable detection must
    honor this attribute as well as ``status_code``."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_config(
    provider: str = "stub-provider",
    model: str = "stub-model",
    base_url: str = "https://stub.invalid",
    fallback: list[LLMConfig] | None = None,
) -> Config:
    return Config(
        llm=LLMConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            fallback=fallback or [],
        )
    )


def _ok_response() -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])


def _recorded_sleep() -> tuple[list[float], MagicMock]:
    """Return (sleep_log, sleep_mock) capturing every ``time.sleep`` delay."""
    sleep_log: list[float] = []

    def recording_sleep(delay: float) -> None:
        sleep_log.append(delay)

    return sleep_log, MagicMock(side_effect=recording_sleep)


# ---------------------------------------------------------------------------
# (a) 429, 429, 200 -> success after exactly 3 attempts
# ---------------------------------------------------------------------------


class TestRetry429:
    """Jittered exponential backoff on HTTP 429."""

    def test_retries_429_then_succeeds(self) -> None:
        attempts: list[int] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            attempts.append(1)
            if len(attempts) < 3:
                raise StubHTTPError(429)
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=_stub_config(),
            )

        assert len(attempts) == 3, "expected exactly 3 attempts (2 retries)"
        assert mock_lm.completion.call_count == 3
        assert len(sleep_log) == 2, "expected one backoff sleep between retries"
        assert 0.75 <= sleep_log[0] <= 1.25, "attempt 1 backoff: base 1.0s +-25%"
        assert 1.5 <= sleep_log[1] <= 2.5, "attempt 2 backoff: base 2.0s +-25%"
        assert resp.choices[0].message.content == "ok"

    def test_always_429_surfaces_last_error_fast(self) -> None:
        """Failure variant: last error surfaces after 3 attempts, < 30 s."""
        attempts: list[int] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            attempts.append(1)
            raise StubHTTPError(429, "Rate limit hit: try later")

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        start = time.monotonic()
        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_stub_config(),
                )
        elapsed = time.monotonic() - start

        assert len(attempts) == 3, "expected exactly 3 attempts, then give up"
        assert len(sleep_log) == 2, "backoff bounded — no infinite loop"
        assert "Rate limit hit: try later" in str(excinfo.value), (
            "last error must surface in the aggregate error"
        )
        assert elapsed < 30.0, "test must complete fast (backoff mocked, no hang)"


# ---------------------------------------------------------------------------
# (b) 5xx x3 -> aggregate error after exactly 3 attempts
# ---------------------------------------------------------------------------


class TestRetry5xx:
    """HTTP 5xx triggers the same bounded retry path."""

    def test_5xx_exhausts_after_three_attempts(self) -> None:
        attempts: list[int] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            attempts.append(1)
            raise StubHTTPError(503)

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            with pytest.raises(RuntimeError, match="All LLM models"):
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_stub_config(),
                )

        assert len(attempts) == 3, "expected exactly 3 attempts, no infinite loop"
        assert mock_lm.completion.call_count == 3
        assert len(sleep_log) == 2


# ---------------------------------------------------------------------------
# (c) 400 -> NO retry (1 attempt only)
# ---------------------------------------------------------------------------


class TestNoRetry4xx:
    """Non-retryable 4xx statuses must not trigger backoff."""

    def test_400_no_retry_single_attempt(self) -> None:
        attempts: list[int] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            attempts.append(1)
            raise StubHTTPError(400, "Bad request")

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            with pytest.raises(RuntimeError, match="All LLM models"):
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_stub_config(),
                )

        assert len(attempts) == 1, "400 must not be retried"
        assert mock_lm.completion.call_count == 1
        assert sleep_log == [], "no backoff sleep for non-retryable errors"

    def test_status_only_error_is_retried(self) -> None:
        """Errors exposing only ``.status`` (no ``status_code``) retried too."""
        attempts: list[int] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            attempts.append(1)
            if len(attempts) == 1:
                raise StubStatusError(429)
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=_stub_config(),
            )

        assert len(attempts) == 2
        assert len(sleep_log) == 1
        assert resp.choices[0].message.content == "ok"


# ---------------------------------------------------------------------------
# (d) semaphore = 4, 16 concurrent calls -> max in-flight == 4
# ---------------------------------------------------------------------------


class TestSemaphoreConcurrency:
    """Per-provider shared semaphore bounds concurrent in-flight calls."""

    def test_sixteen_concurrent_calls_bounded_to_four(self, monkeypatch) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_MAX_CONCURRENCY", "4")
        # Unique base_url -> fresh semaphore created while the env var is set.
        base_url = "https://stub-concurrency.invalid"

        state = {"in_flight": 0, "max_in_flight": 0, "entered": 0}
        lock = threading.Lock()
        slots_filled = threading.Event()
        release = threading.Event()

        def stub_completion(**kwargs: object) -> MagicMock:
            with lock:
                state["in_flight"] += 1
                state["entered"] += 1
                state["max_in_flight"] = max(
                    state["max_in_flight"], state["in_flight"]
                )
                if state["entered"] >= 4:
                    slots_filled.set()
            try:
                release.wait(timeout=15)
            finally:
                with lock:
                    state["in_flight"] -= 1
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        results: list[Exception | None] = [None] * 16

        def worker(index: int) -> None:
            try:
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=_stub_config(base_url=base_url),
                )
            except Exception as exc:  # noqa: BLE001 — captured for assertions
                results[index] = exc

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", return_value=None),
        ):
            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(16)
            ]
            for thread in threads:
                thread.start()

            # The first 4 calls fill the semaphore slots and block inside the
            # stub; the other 12 must queue on the semaphore (never enter).
            assert slots_filled.wait(timeout=15), "semaphore slots never filled"
            # Give queued threads a bounded window to (incorrectly) enter.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with lock:
                    if state["entered"] > 4:
                        break
                time.sleep(0.01)
            with lock:
                assert state["entered"] == 4, (
                    "expected exactly 4 calls in flight — "
                    "semaphore not shared across callers"
                )
                assert state["max_in_flight"] == 4
            release.set()
            for thread in threads:
                thread.join(timeout=15)

        assert all(result is None for result in results), f"{results}"
        assert mock_lm.completion.call_count == 16
        assert state["entered"] == 16
        assert state["max_in_flight"] == 4, (
            "max observed in-flight must equal the semaphore width (4)"
        )

    def test_semaphores_are_per_provider(self, monkeypatch) -> None:
        """Two providers get independent semaphores — never one global lock."""
        monkeypatch.setenv("AUTOINFO_LLM_MAX_CONCURRENCY", "1")
        entered: list[str] = []
        lock = threading.Lock()
        both_entered = threading.Event()
        release = threading.Event()

        def stub_completion(**kwargs: object) -> MagicMock:
            with lock:
                entered.append(str(kwargs["model"]))
                if len(entered) == 2:
                    both_entered.set()
            try:
                release.wait(timeout=15)
            finally:
                pass
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion

        def worker(provider: str, model: str, base_url: str) -> None:
            call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=_stub_config(
                    provider=provider, model=model, base_url=base_url
                ),
            )

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            threads = [
                threading.Thread(
                    target=worker,
                    args=("stub-a", "stub-a", "https://stub-a.invalid"),
                ),
                threading.Thread(
                    target=worker,
                    args=("stub-b", "stub-b", "https://stub-b.invalid"),
                ),
            ]
            for thread in threads:
                thread.start()
            # With per-provider semaphores (width 1 each) both providers enter
            # concurrently; a single global lock would serialize them.
            assert both_entered.wait(timeout=15), (
                "providers serialized — semaphore is global, not per-provider"
            )
            release.set()
            for thread in threads:
                thread.join(timeout=15)

        assert sorted(entered) == ["stub-a/stub-a", "stub-b/stub-b"]


# ---------------------------------------------------------------------------
# (e) fallback chain order preserved
# ---------------------------------------------------------------------------


class TestFallbackChainOrder:
    """Each chain entry gets the retry treatment; ordering is unchanged."""

    def test_primary_exhausts_retries_then_fallback_wins(self) -> None:
        fallback_cfg = LLMConfig(provider="stub-fb", model="fb-model")
        cfg = _stub_config(fallback=[fallback_cfg])
        called_models: list[str] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            model = str(kwargs["model"])
            called_models.append(model)
            if model == "stub-provider/stub-model":
                raise StubHTTPError(500)
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion
        sleep_log, sleep_mock = _recorded_sleep()

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", sleep_mock),
        ):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=cfg,
            )

        assert resp.choices[0].message.content == "ok"
        assert called_models == [
            "stub-provider/stub-model",  # primary attempt 1
            "stub-provider/stub-model",  # primary attempt 2
            "stub-provider/stub-model",  # primary attempt 3
            "stub-fb/fb-model",  # fallback — succeeds on first call
        ], "chain must walk [primary] + [fallback] in order"
        assert len(sleep_log) == 2, "primary retries backed off before fallback"
