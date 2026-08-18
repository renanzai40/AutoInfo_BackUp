"""Provider-inheritance tests for ``LLMConfig.resolve_model`` (todo 6).

``resolve_model`` hardcodes ``'openrouter'`` as the fallback provider when
``self.provider`` is empty.  For empty-provider fallback entries (the
configured ``mimo-v2.5`` fallback inherits the primary provider) that
misjudges the effective provider prefix.  This wave adds an optional
``default_provider`` parameter so callers can pass the inherited provider
explicitly:

- ``LLMConfig(provider="", model="mimo-v2.5").resolve_model(default_provider="openai")``
  must resolve to ``"openai/mimo-v2.5"`` (NOT ``"openrouter/mimo-v2.5"``).
- The no-argument call keeps the historical ``"openrouter/..."`` default —
  backward compatibility is a hard requirement (15 callers in src/).
- ``call_with_fallback`` already inherits the primary provider for
  empty-provider fallback entries (``fb.provider or provider`` at
  llm.py:715); the chain test locks that existing correct behavior so a
  future refactor cannot regress it to ``openrouter/...``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autoinfo.config import Config, LLMConfig
from autoinfo.llm import LLMExtractor, call_with_fallback


class TestResolveModelDefaultProvider:
    """``default_provider`` overrides the hardcoded ``openrouter`` fallback."""

    def test_empty_provider_inherits_default_provider(self) -> None:
        """Empty provider + explicit default_provider -> default_provider prefix."""
        cfg = LLMConfig(provider="", model="mimo-v2.5")
        assert cfg.resolve_model(default_provider="openai") == "openai/mimo-v2.5"

    def test_no_default_provider_keeps_openrouter(self) -> None:
        """No-arg call keeps the historical ``openrouter`` fallback."""
        cfg = LLMConfig(provider="", model="mimo-v2.5")
        assert cfg.resolve_model() == "openrouter/mimo-v2.5"

    def test_explicit_provider_wins_over_default_provider(self) -> None:
        """A non-empty ``self.provider`` always beats ``default_provider``."""
        cfg = LLMConfig(provider="azure", model="gpt-4")
        assert cfg.resolve_model(default_provider="openai") == "azure/gpt-4"

    def test_prefixed_model_untouched(self) -> None:
        """A model that already carries a provider prefix is returned as-is."""
        cfg = LLMConfig(provider="", model="openai/mimo-v2.5")
        assert cfg.resolve_model(default_provider="openai") == "openai/mimo-v2.5"

    def test_empty_model_returns_empty(self) -> None:
        """Empty model still returns an empty string (historical contract)."""
        cfg = LLMConfig(provider="", model="")
        assert cfg.resolve_model(default_provider="openai") == ""


class TestCallWithFallbackProviderInheritance:
    """The chain build inherits the primary provider for empty-provider
    fallback entries — locked so it cannot regress to ``openrouter/...``."""

    def test_fallback_entry_inherits_primary_provider(self) -> None:
        """Chain second entry model is ``openai/mimo-v2.5``, NOT
        ``openrouter/mimo-v2.5``."""
        cfg = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                base_url="https://opencode.ai/zen/go/v1",
                fallback=[
                    LLMConfig(
                        provider="",
                        model="mimo-v2.5",
                        base_url="https://opencode.ai/zen/go/v1",
                    )
                ],
            )
        )

        called: list[dict[str, object]] = []

        class StubRateLimitError(RuntimeError):
            """Minimal LiteLLM 429 stand-in — retryable via ``status_code``."""

            def __init__(self, message: str = "Rate limit hit") -> None:
                self.status_code = 429
                super().__init__(message)

        def stub_completion(**kwargs: object) -> MagicMock:
            called.append(kwargs)
            model = str(kwargs["model"])
            if model == "openai/deepseek-v4-flash":
                raise StubRateLimitError("primary rate limited (429)")
            if model == "openai/mimo-v2.5":
                return MagicMock(
                    choices=[MagicMock(message=MagicMock(content="ok"))]
                )
            raise AssertionError(f"unexpected model in chain: {model}")

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

        models_called = [str(kw["model"]) for kw in called]
        # Primary exhausted its MAX_LLM_ATTEMPTS retries (3 tries), then the
        # fallback was attempted once and won.
        assert models_called.count("openai/deepseek-v4-flash") == 3
        assert models_called[-1] == "openai/mimo-v2.5"
        assert "openrouter/mimo-v2.5" not in models_called
        assert resp.choices[0].message.content == "ok"
