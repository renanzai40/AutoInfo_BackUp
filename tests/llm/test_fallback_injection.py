"""Failure-injection tests for the mimo-v2.5 fallback chain (todo 2).

Unit (mandatory): monkeypatches the provider-call seam inside
``call_with_fallback`` — the per-provider ``_litellm.completion`` call
resolved via ``LLMExtractor._get_litellm`` (the same seam todo 1's
test_rate_limit_429.py uses).  The PRIMARY model raises a retryable HTTP
429 every attempt; the chain must exhaust the primary and walk through to
the configured fallback, and the fallback completion call must carry
model ``openai/mimo-v2.5`` on the opencode gateway with no key of its own
(the gateway inherits the primary key).  Zero real sleeps (``time.sleep``
patched), zero network — fully deterministic.

Integration (optional): with a real key the configured chain
([primary deepseek-v4-flash] + [fallback mimo-v2.5]) is exercised
end-to-end against the opencode gateway.  Skipped cleanly (exit 0) when
``AUTOINFO_LLM_API_KEY`` is not set.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import load_config
from autoinfo.llm import LLMExtractor, call_with_fallback

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".autoinfo" / "config.yaml"

# The chain is asserted against the repository's real (gitignored) config —
# absent on CI (fresh checkout has no .autoinfo/), so skip cleanly instead of
# failing FileNotFoundError.
pytestmark = pytest.mark.skipif(
    not CONFIG_PATH.is_file(),
    reason=".autoinfo/config.yaml absent (gitignored) — deployment-config test",
)

OPENGATE_BASE_URL = "https://opencode.ai/zen/go/v1"
FALLBACK_MODEL = "mimo-v2.5"


class StubRateLimitError(RuntimeError):
    """Minimal LiteLLM 429 stand-in — retryable via ``status_code``."""

    def __init__(self, message: str = "Rate limit hit") -> None:
        self.status_code = 429
        super().__init__(message)


def _ok_response() -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])


class TestFallbackInjection:
    """Primary 429 -> chain falls through to mimo-v2.5 fallback."""

    def test_primary_429_falls_through_to_mimo_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = load_config(CONFIG_PATH)
        assert len(cfg.llm.fallback) == 1  # guard: config edit is in place

        primary_model = cfg.llm.resolve_model()
        fallback_model = (
            f"{cfg.llm.fallback[0].provider or cfg.llm.provider}/{FALLBACK_MODEL}"
        )

        called: list[dict[str, object]] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            called.append(kwargs)
            model = str(kwargs["model"])
            if model == primary_model:
                raise StubRateLimitError("primary rate limited (429)")
            if model == fallback_model:
                return _ok_response()
            raise AssertionError(f"unexpected model in chain: {model}")

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", return_value=None),  # deterministic, no sleeps
        ):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "short test"}],
                config=cfg,
                max_tokens=64,
            )

        models_called = [str(kw["model"]) for kw in called]
        # Primary exhausted its MAX_LLM_ATTEMPTS retries (3 tries), then the
        # fallback was attempted once and won.
        assert models_called.count(primary_model) == 3
        assert models_called[-1] == fallback_model
        assert resp.choices[0].message.content == "ok"

        # The fallback call carries the opencode gateway and no key of its
        # own — the gateway inherits the primary key.
        fallback_kwargs = called[-1]
        assert fallback_kwargs["api_base"] == OPENGATE_BASE_URL
        assert fallback_kwargs["api_key"] is None
        # Reasoned primary still suppresses response_format (issue #178)
        # and sends the disable-thinking body — the fallback is a reasoning
        # model on the same gateway, so the same controls apply.
        assert "response_format" not in fallback_kwargs

    def test_primary_ok_never_calls_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the primary succeeds no fallback is invoked."""
        cfg = load_config(CONFIG_PATH)
        primary_model = cfg.llm.resolve_model()

        called: list[dict[str, object]] = []

        def stub_completion(**kwargs: object) -> MagicMock:
            called.append(kwargs)
            return _ok_response()

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = stub_completion

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm),
            patch("time.sleep", return_value=None),
        ):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "short test"}],
                config=cfg,
                max_tokens=64,
            )

        assert [str(kw["model"]) for kw in called] == [primary_model]
        assert resp.choices[0].message.content == "ok"


@pytest.mark.skipif(
    not os.environ.get("AUTOINFO_LLM_API_KEY"),
    reason=(
        "AUTOINFO_LLM_API_KEY not set — integration variant skipped "
        "(clean skip, exit 0)"
    ),
)
def test_integration_real_chain_with_key() -> None:
    """End-to-end smoke of the configured chain against the real gateway.

    Exercises the parsed fallback config through the real provider call —
    the primary (deepseek-v4-flash) and, on primary failure, the
    mimo-v2.5 fallback on the same opencode gateway.
    """
    cfg = load_config(CONFIG_PATH)
    resp = call_with_fallback(
        messages=[
            {"role": "system", "content": "Reply with the single word: ok"},
            {"role": "user", "content": "ping"},
        ],
        config=cfg,
        max_tokens=16,
    )
    assert resp.choices[0].message.content
