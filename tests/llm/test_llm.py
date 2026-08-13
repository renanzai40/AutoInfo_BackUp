"""Snapshot regression tests for LLM extraction pipeline.

All LLM calls are mocked — no real API calls are made.
Tests cover:

- Basic extraction returns :class:`ExtractionResult` with expected fields
- *dry_run* shows prompt without calling the API
- *extract_with_retry* succeeds on valid response
- *extract_with_retry* retries and raises after max failures
- Malformed JSON response handled gracefully
- Relevance score clamped to [0, 100]
- LLM error returns empty default result
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import Config, LLMConfig
from autoinfo.llm import LLMExtractor, call_with_fallback
from autoinfo.models import ExtractionResult, Item

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def mock_litellm() -> MagicMock:
    """Create a mock ``litellm`` module to replace ``_get_litellm()``.

    The returned mock has a ``.completion`` attribute that returns a response
    with valid extraction JSON.
    """
    m = MagicMock()
    m.completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "tl_dr": (
                "Time-lapse embryo imaging significantly improves live birth "
                "rates (48.2% vs 39.5%) compared to standard morphological "
                "assessment in a large RCT of 1,200 IVF patients."
            ),
            "key_points": [
                "Multicenter RCT with 1,200 IVF patients",
                "Live birth rate: 48.2% vs 39.5%, RR 1.22, p=0.006",
                "Non-invasive method improves embryo selection",
            ],
            "entities": [
                {"name": "Time-lapse embryo imaging", "type": "technology"},
                {"name": "IVF", "type": "procedure"},
            ],
            "relevance_score": 92,
        })))]
    )
    return m


@pytest.fixture
def extractor() -> LLMExtractor:
    """Return a default :class:`LLMExtractor` (no config file needed)."""
    return LLMExtractor()


# ===================================================================
# Tests
# ===================================================================


class TestExtract:
    """``LLMExtractor.extract()`` — happy path and error handling."""

    def test_returns_extraction_result(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm: MagicMock,
    ) -> None:
        """extract() returns ExtractionResult with all expected fields."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = extractor.extract(sample_item)

        assert isinstance(result, ExtractionResult)
        assert result.item_id == sample_item.id
        assert result.title == sample_item.title
        assert result.tl_dr != ""
        assert len(result.key_points) >= 3
        assert len(result.entities) >= 1
        assert 0 <= result.relevance_score <= 100

    def test_llm_error_returns_empty_default(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """extract() returns empty ExtractionResult when LLM raises."""
        mock_lm = MagicMock()
        mock_lm.completion.side_effect = Exception("Network error")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            result = extractor.extract(sample_item)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr == ""
        assert result.key_points == []
        assert result.relevance_score == 0.0

    def test_litellm_not_available(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """extract() handles missing litellm gracefully."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=None):
            result = extractor.extract(sample_item)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr == ""
        assert result.relevance_score == 0.0

    def test_relevance_score_clamped(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """relevance_score is clamped to [0, 100]."""
        for raw_score in [-10, 50, 150]:
            mock_lm = MagicMock()
            mock_lm.completion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps({
                    "tl_dr": "test",
                    "key_points": ["point"],
                    "entities": [],
                    "relevance_score": raw_score,
                })))]
            )

            with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
                result = extractor.extract(sample_item)

            assert 0 <= result.relevance_score <= 100, (
                f"raw_score={raw_score} -> relevance_score={result.relevance_score}"
            )


class TestDryRun:
    """``LLMExtractor.dry_run()`` — prompt inspection without API call."""

    def test_dry_run_returns_prompt_string(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """dry_run() shows the prompt text without calling any API."""
        prompt = extractor.dry_run(sample_item)

        assert isinstance(prompt, str)
        assert "System:" in prompt
        assert "User:" in prompt
        assert "AutoInfo" in prompt
        assert sample_item.title in prompt

    def test_dry_run_no_llm_call(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Verify no ``litellm.completion`` is called during dry_run."""
        with patch.object(LLMExtractor, "_get_litellm") as mock_get:
            extractor.dry_run(sample_item)
            mock_get.assert_not_called()

    def test_dry_run_custom_schema(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Custom schema fields appear in the dry-run prompt."""
        prompt = extractor.dry_run(sample_item, schema=["tl_dr", "custom_field"])
        assert "tl_dr" in prompt
        assert "custom_field" in prompt


class TestExtractWithRetry:
    """``LLMExtractor.extract_with_retry()`` — retry logic."""

    def test_retry_succeeds_on_valid_response(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm: MagicMock,
    ) -> None:
        """extract_with_retry() returns result on first success."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = extractor.extract_with_retry(sample_item, max_retries=2)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr != ""

    def test_retry_raises_after_max_attempts(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """extract_with_retry() raises RuntimeError after exhausting retries."""
        mock_lm = MagicMock()
        mock_lm.completion.side_effect = Exception("API error")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            with pytest.raises(RuntimeError, match="LLM extraction failed"):
                extractor.extract_with_retry(sample_item, max_retries=2)

    def test_retry_attempts_logged(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Each failed attempt is logged as a warning."""
        mock_lm = MagicMock()
        mock_lm.completion.side_effect = Exception("timeout")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            with pytest.raises(RuntimeError):
                extractor.extract_with_retry(sample_item, max_retries=2)

        # Should have logged 3 attempts (max_retries + 1)
        warning_count = sum(
            1
            for rec in caplog.records
            if "LLM extraction attempt" in rec.getMessage()
        )
        assert warning_count == 3

    def test_retry_recovers_after_transient_failure(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm: MagicMock,
    ) -> None:
        """extract_with_retry() recovers when a later attempt succeeds."""
        call_count = 0

        def _side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            return mock_litellm.completion(*args, **kwargs)

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = _side_effect

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            result = extractor.extract_with_retry(sample_item, max_retries=3)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr != ""
        assert call_count == 3  # 2 failures + 1 success

    # ------------------------------------------------------------------
    # Fallback chain tests
    # ------------------------------------------------------------------

    def test_fallback_used_when_primary_exhausted(
        self,
        sample_item: Item,
    ) -> None:
        """Fallback model is tried after primary retries are exhausted."""
        from autoinfo.config import Config, LLMConfig

        fallback_cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="")
        cfg = Config(
            llm=LLMConfig(
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_key="",
                fallback=[fallback_cfg],
            )
        )
        extractor = LLMExtractor(config=cfg)

        # Primary always fails; fallback succeeds
        mock_lm = MagicMock()

        def _side_effect(**kwargs: object) -> MagicMock:
            model = str(kwargs.get("model", ""))
            if "deepseek" in model:
                raise Exception("Primary model error")
            return MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps({
                    "tl_dr": "fallback model result",
                    "key_points": ["recovered via fallback"],
                    "entities": [],
                    "relevance_score": 85,
                })))]
            )

        mock_lm.completion.side_effect = _side_effect

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            result = extractor.extract_with_retry(sample_item, max_retries=2)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr == "fallback model result"
        assert len(result.key_points) == 1

    def test_fallback_all_fail(
        self,
        sample_item: Item,
    ) -> None:
        """RuntimeError is raised when both primary and all fallbacks fail."""
        from autoinfo.config import Config, LLMConfig

        fallback_cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="")
        cfg = Config(
            llm=LLMConfig(
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_key="",
                fallback=[fallback_cfg],
            )
        )
        extractor = LLMExtractor(config=cfg)

        mock_lm = MagicMock()
        mock_lm.completion.side_effect = Exception("Always fails")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            with pytest.raises(RuntimeError, match="fallback"):
                extractor.extract_with_retry(sample_item, max_retries=2)

    def test_fallback_logged(
        self,
        sample_item: Item,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Fallback attempts are logged with model name and duration."""
        import logging

        caplog.set_level(logging.INFO)

        from autoinfo.config import Config, LLMConfig

        fallback_cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="")
        cfg = Config(
            llm=LLMConfig(
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_key="",
                fallback=[fallback_cfg],
            )
        )
        extractor = LLMExtractor(config=cfg)

        mock_lm = MagicMock()

        def _side_effect(**kwargs: object) -> MagicMock:
            model = str(kwargs.get("model", ""))
            if "deepseek" in model:
                raise Exception("Primary error")
            return MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps({
                    "tl_dr": "ok",
                    "key_points": [],
                    "entities": [],
                    "relevance_score": 50,
                })))]
            )

        mock_lm.completion.side_effect = _side_effect

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            extractor.extract_with_retry(sample_item, max_retries=2)

        # Should see a fallback warning with model name
        fallback_logs = [
            rec.getMessage()
            for rec in caplog.records
            if "Fallback" in rec.getMessage()
        ]
        assert any("openai/gpt-4o" in msg for msg in fallback_logs)
        assert any("succeeded" in msg for msg in fallback_logs)

    def test_no_fallback_raises_immediately(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
    ) -> None:
        """When no fallback is configured, error message says so."""
        from autoinfo.config import Config, LLMConfig

        # Explicit no-fallback config: the real .autoinfo/config.yaml now
        # carries the mimo-v2.5 fallback chain (todo 2), so the shared
        # extractor fixture would exercise the fallback path instead of the
        # "no fallback" message this test guards.
        cfg = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                api_key="",
                base_url="https://opencode.ai/zen/go/v1",
                fallback=[],
            )
        )
        extractor = LLMExtractor(config=cfg)
        mock_lm = MagicMock()
        mock_lm.completion.side_effect = Exception("API error")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            with pytest.raises(RuntimeError, match="no fallback"):
                extractor.extract_with_retry(sample_item, max_retries=2)


class TestParseResponseFallback:
    """``LLMExtractor._parse_response()`` — JSON parsing fallback strategies."""

    def test_direct_json(self, extractor: LLMExtractor) -> None:
        """Valid JSON is parsed directly."""
        result = extractor._parse_response('{"tl_dr": "test", "key_points": ["a"]}')
        assert result["tl_dr"] == "test"
        assert result["key_points"] == ["a"]

    def test_json_in_markdown_code_block(self, extractor: LLMExtractor) -> None:
        """JSON inside a ```json ... ``` block is extracted."""
        content = """Here's my analysis:

```json
{"tl_dr": "markdown wrapped", "key_points": ["p1"]}
```"""
        result = extractor._parse_response(content)
        assert result["tl_dr"] == "markdown wrapped"

    def test_json_in_fenced_block_no_lang(self, extractor: LLMExtractor) -> None:
        """JSON inside a plain ``` ... ``` block is extracted."""
        content = """```{"tl_dr": "fenced", "key_points": ["p1"]}```"""
        result = extractor._parse_response(content)
        assert result["tl_dr"] == "fenced"

    def test_brace_extraction(self, extractor: LLMExtractor) -> None:
        """Bare JSON object embedded in text is extracted."""
        content = 'Here is the result: {"tl_dr": "bare", "key_points": []} end.'
        result = extractor._parse_response(content)
        assert result["tl_dr"] == "bare"

    def test_malformed_returns_empty(self, extractor: LLMExtractor) -> None:
        """Completely unparseable content returns empty dict."""
        result = extractor._parse_response("Not even close to JSON")
        assert result == {}

    def test_empty_string_returns_empty(self, extractor: LLMExtractor) -> None:
        result = extractor._parse_response("")
        assert result == {}


class TestConfigHandling:
    """``LLMExtractor`` configuration — default and custom config."""

    def test_default_config_no_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Extractor can be created without a config file."""
        # TRIAGE #16 (env-dep): the repo-root gitignored runtime .autoinfo/config.yaml
        # (created 2026-08-03) is picked up by get_config_path() →
        # LLMExtractor()._model != documented default (root cause src/autoinfo/llm.py:88-102).
        # Real fix: stub the path lookup so the default-config path is taken
        # regardless of cwd/env state.
        monkeypatch.setattr("autoinfo.llm.get_config_path", lambda: None)
        extractor = LLMExtractor()
        assert extractor._model == "openrouter/deepseek/deepseek-chat"

    def test_custom_config_model(self) -> None:
        """Custom config provider/model are reflected in the model string."""
        from autoinfo.config import Config, LLMConfig

        cfg = Config(llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key=""))
        extractor = LLMExtractor(config=cfg)
        assert extractor._model == "openai/gpt-4o-mini"

    def test_custom_schema_appears_in_prompt(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Custom schema fields are included alongside defaults in the prompt."""
        prompt = extractor.dry_run(sample_item, schema=["tl_dr", "key_points"])
        assert "tl_dr" in prompt
        assert "key_points" in prompt
        # Default fields are always included even when not in the schema
        assert "entities" in prompt


# ===================================================================
# call_with_fallback — shared chain-walk helper (issue #147)
# ===================================================================


class TestCallWithFallback:
    """``llm.call_with_fallback`` walks primary + fallback model chain.

    The same helper is used by every standalone litellm call site so the
    configured fallback chain protects all LLM paths, not just extraction.
    """

    def _config_with_fallback(self) -> Config:
        return Config(
            llm=LLMConfig(
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_key="",
                fallback=[LLMConfig(provider="openai", model="gpt-4o", api_key="")],
            )
        )

    def _mock_litellm(self) -> MagicMock:
        return MagicMock()

    def test_primary_failure_falls_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Primary fails → fallback model is tried and its response returned."""
        import logging

        mock_lm = self._mock_litellm()
        fallback_resp = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

        def _side_effect(**kwargs: object) -> MagicMock:
            if "deepseek" in str(kwargs.get("model", "")):
                raise Exception("Primary model error")
            return fallback_resp

        mock_lm.completion.side_effect = _side_effect

        caplog.set_level(logging.INFO)
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            resp = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=self._config_with_fallback(),
            )

        assert resp is fallback_resp
        assert mock_lm.completion.call_count == 2
        models_called = [
            str(c.kwargs["model"]) for c in mock_lm.completion.call_args_list
        ]
        assert "deepseek/deepseek-chat" in models_called
        assert "openai/gpt-4o" in models_called
        assert "Fallback to openai/gpt-4o succeeded" in caplog.text

    def test_all_models_fail_raises(self) -> None:
        """Every model in the chain failing raises RuntimeError."""
        mock_lm = self._mock_litellm()
        mock_lm.completion.side_effect = Exception("Always fails")

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            with pytest.raises(RuntimeError, match="All LLM models"):
                call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    config=self._config_with_fallback(),
                )
        assert mock_lm.completion.call_count == 2

    def test_no_fallback_single_attempt(self) -> None:
        """Without a configured fallback the primary is attempted once."""
        cfg = Config(
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="")
        )
        mock_lm = self._mock_litellm()
        resp = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
        mock_lm.completion.return_value = resp

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            result = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=cfg,
                max_tokens=512,
                temperature=0.2,
            )

        assert result is resp
        assert mock_lm.completion.call_count == 1
        call_kwargs = mock_lm.completion.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o-mini"
        assert call_kwargs["max_tokens"] == 512
        assert call_kwargs["temperature"] == 0.2

    def test_json_mode_passes_response_format(self) -> None:
        """json_mode=True adds response_format json_object to the call."""
        cfg = Config(
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="")
        )
        mock_lm = self._mock_litellm()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="{}"))]
        )

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=cfg,
                json_mode=True,
            )

        call_kwargs = mock_lm.completion.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_primary_succeeds_no_fallback_attempt(self) -> None:
        """Successful primary call never touches the fallback model."""
        mock_lm = self._mock_litellm()
        resp = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
        mock_lm.completion.return_value = resp

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            result = call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                config=self._config_with_fallback(),
            )

        assert result is resp
        assert mock_lm.completion.call_count == 1
