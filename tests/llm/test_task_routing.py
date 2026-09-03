"""Per-task LLM model routing — todo 9 of llm-concurrency-remediation.

Routing table (config-driven, never a vendor/model code constant — #195):

    extraction / classification  -> ``llm.tasks["extraction"]`` when present,
                                    else the base ``llm`` config
                                    (deepseek-v4-flash this release)
    judgment (G4/G5/llm_judge)   -> ``llm.judgment_model`` when set, else
                                    ``llm.model`` (the deployment's own
                                    working model), else a loud
                                    JudgmentModelNotConfiguredError; a judgment
                                    task's task-config model is NEVER honored
                                    (drift guardrail)

The mock-capture asserts the model argument at the provider-call boundary
(``_litellm.completion(model=...)``) — the actual LLM call seam — not
config-layer defaults.  All LLM calls are mocked; no real API calls.

Coverage (plan todo 9):
(a) extraction call -> deepseek-v4-flash; G4/G5 judgment call -> the
    configured deployment model;
(b) judgment task with an invalid task-config model -> still never honored;
(c) no task config -> current defaults preserved (incl. explicit-model wins,
    which keeps the G4 retry-chain model escalation contract intact);
(d) no judgment_model AND no llm.model -> JudgmentModelNotConfiguredError (#195).
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import (
    Config,
    JudgmentModelNotConfiguredError,
    LLMConfig,
    LLMTaskConfig,
    _resolve_task_llm_config,
)
from autoinfo.llm import LLMExtractor, call_with_fallback
from autoinfo.models import ExtractionResult, Item
from autoinfo.quality import (
    G4FactualConsistency,
    G5TranslationAccuracy,
    llm_judge,
)

# ===================================================================
# Helpers
# ===================================================================


def _mock_litellm(raw_text: str) -> MagicMock:
    """Build a mock ``litellm`` module whose ``completion()`` returns raw text.

    The returned mock records the ``model`` kwarg at the provider boundary.
    """
    mock_litellm = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = raw_text
    mock_litellm.completion.return_value = mock_response
    return mock_litellm


def _captured_model(mock_litellm: MagicMock) -> str:
    """Return the ``model`` kwarg captured at the completion boundary."""
    assert mock_litellm.completion.called, "completion was never called"
    return mock_litellm.completion.call_args.kwargs["model"]


def _make_item() -> Item:
    """Return a synthetic item for routing tests."""
    return Item(
        id="routing-item-001",
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url="https://example.com/article",
        title="Test article about IVF outcomes",
        content=(
            "A recent study found that IVF success rates improve with "
            "time-lapse imaging. The live birth rate was 48.2% in the "
            "treatment group compared to 39.5% in the control group."
        ),
        content_type="text",
        collected_at="2026-07-20T10:00:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=1,
    )


def _make_extraction(*, translation: str | None = None) -> ExtractionResult:
    """Return an extraction result; optionally carrying a translation."""
    return ExtractionResult(
        item_id="routing-item-001",
        title="Test article about IVF outcomes",
        tl_dr="IVF success rates improve with time-lapse imaging.",
        key_points=["Time-lapse imaging improves IVF outcomes"],
        entities=[],
        relevance_score=85.0,
        custom_fields={"translation": translation} if translation else {},
    )


# ===================================================================
# (a) Routing table — extraction vs judgment
# ===================================================================


class TestExtractionRouting:
    """Extraction calls resolve through the ``extraction`` task config."""

    def test_extraction_task_routes_to_task_config_model(self) -> None:
        """Task-configured extraction model reaches the completion boundary."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                tasks={"extraction": LLMTaskConfig(model="deepseek-v4-flash")},
            )
        )
        mock_litellm = _mock_litellm(
            json.dumps(
                {
                    "tl_dr": "IVF success rates improve with time-lapse imaging.",
                    "key_points": ["IVF improves with imaging"],
                    "entities": [],
                    "relevance_score": 85,
                }
            )
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = LLMExtractor(config=config).extract(_make_item())

        assert result.tl_dr
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"

    def test_extraction_resolution_uses_task_max_tokens(self) -> None:
        """Task max_tokens rides along with the routed model.

        Driven through the ``task=`` seam (the extractor passes an explicit
        ``max_tokens=2000`` by contract; the seam proves the routing threads
        the task's max_tokens to the payload).
        """
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                tasks={"extraction": LLMTaskConfig(model="deepseek-v4-flash", max_tokens=777)},
            )
        )
        mock_litellm = _mock_litellm(json.dumps({"ok": True}))
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                task="extraction",
                config=config,
            )

        assert mock_litellm.completion.call_args.kwargs["max_tokens"] == 777
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"


class TestJudgmentRouting:
    """G4/G5/llm_judge resolve the deployment judgment model (issue #195)."""

    def test_g4_judgment_uses_configured_model(self) -> None:
        """G4 default model is the configured model at the boundary."""
        mock_litellm = _mock_litellm(
            json.dumps({"contradiction": False, "explanation": "consistent"})
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            # No deployment config in this test — pass the model explicitly
            # (a config-less default construction raises, issue #195).
            result = G4FactualConsistency(
                model="openai/deepseek-v4-flash"
            ).check(_make_item(), _make_extraction())

        assert result.passed is True
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"

    def test_g4_configless_construction_raises(self) -> None:
        """Issue #195 acceptance #1: no config → a config-less G4 default
        construction raises JudgmentModelNotConfiguredError (never a code-constant
        guess)."""
        with patch.object(LLMExtractor, "_get_litellm"), \
             patch("autoinfo.config.get_config_path", return_value=None):
            with pytest.raises(JudgmentModelNotConfiguredError):
                G4FactualConsistency()  # noqa: B018

    def test_g5_judgment_uses_configured_model(self) -> None:
        """G5 default model is the configured model at the boundary."""
        mock_litellm = _mock_litellm(
            json.dumps({"faithful": True, "explanation": "faithful", "issues": []})
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = G5TranslationAccuracy(
                model="openai/deepseek-v4-flash"
            ).check(
                _make_item(), _make_extraction(translation="IVF 成功率有所提升。")
            )

        assert result.passed is True
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"

    def test_llm_judge_uses_configured_model(self) -> None:
        """llm_judge (translation QA gate 5) default is the configured model."""
        mock_litellm = _mock_litellm(
            json.dumps(
                {
                    "faithfulness": 95,
                    "terminology": 90,
                    "style": 88,
                    "readability": 92,
                    "issues": [],
                }
            )
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            scores = llm_judge(
                "IVF success rates improve with time-lapse imaging.",
                "IVF 成功率随时间推移成像而提升。",
                "en",
                "zh",
                model="openai/deepseek-v4-flash",
            )

        assert scores["faithfulness"] == 95
        assert scores["judged"] is True
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"


# ===================================================================
# (b) Drift guardrail — judgment task config is never honored
# ===================================================================


class TestJudgmentDriftGuardrail:
    """A judgment task configured with an invalid model stays un-drifted."""

    def test_resolve_task_llm_config_ignores_task_model(self) -> None:
        """``_resolve_task_llm_config`` ignores task-config model for judgment:
        resolution is llm.judgment_model → llm.model (issue #195)."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="some-base-model",
                tasks={"g4_factual": LLMTaskConfig(model="invalid-drifted-model")},
            )
        )
        resolved = _resolve_task_llm_config(config, "g4_factual")
        # The written llm.tasks override is never honored — judgment falls
        # through to the deployment's llm.model.
        assert resolved.model == "openai/some-base-model"

    def test_call_with_fallback_judgment_task_at_boundary(self) -> None:
        """Task-routed judgment call reaches the boundary with the resolved
        deployment model (never the drifted task model)."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="some-base-model",
                tasks={"llm_judge": LLMTaskConfig(model="invalid-drifted-model")},
            )
        )
        mock_litellm = _mock_litellm(json.dumps({"ok": True}))
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            call_with_fallback(
                messages=[{"role": "user", "content": "judge this"}],
                task="llm_judge",
                config=config,
            )

        # The resolved model is provider-qualified at the boundary.
        assert _captured_model(mock_litellm) == "openai/some-base-model"


class TestJudgmentModelOverride:
    """llm.judgment_model (#45/#195): deployment override of the judgment model."""

    def test_resolve_returns_override_when_set(self) -> None:
        """`llm.judgment_model` set -> g4_factual resolves to the override."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                judgment_model="deepseek-v4-flash",
                tasks={"g4_factual": LLMTaskConfig(model="drifted-model")},
            )
        )
        resolved = _resolve_task_llm_config(config, "g4_factual")
        assert resolved.model == "deepseek-v4-flash"

    def test_resolve_falls_through_to_llm_model_when_unset(self) -> None:
        """No llm.judgment_model -> g4_factual resolves to llm.model (issue
        #195; previously a code-constant release pin)."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                tasks={"g4_factual": LLMTaskConfig(model="drifted-model")},
            )
        )
        resolved = _resolve_task_llm_config(config, "g4_factual")
        assert resolved.model == "openai/deepseek-v4-flash"

    def test_resolve_raises_when_nothing_configured(self) -> None:
        """Issue #195 acceptance #1: neither judgment_model nor llm.model →
        resolution raises loudly (never guesses a model)."""
        config = Config(llm=LLMConfig(provider="", model=""))
        with pytest.raises(JudgmentModelNotConfiguredError):
            _resolve_task_llm_config(config, "g4_factual")

    def test_call_with_fallback_judgment_override_at_boundary(self) -> None:
        """The override reaches the completion boundary (not silent)."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                judgment_model="deepseek-v4-flash",
            )
        )
        mock_litellm = _mock_litellm(json.dumps({"ok": True}))
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            call_with_fallback(
                messages=[{"role": "user", "content": "judge this"}],
                task="g4_factual",
                config=config,
            )

        # `deepseek-v4-flash` is bare; resolve_model() prepends the provider.
        assert _captured_model(mock_litellm) == "openai/deepseek-v4-flash"


class TestJudgmentFailureNotSilent:
    """Judgment LLM exhaustion must surface (ERROR / propagate), never trample
    entries through a broken G4/G5 gate (#45)."""

    def test_judgment_exhaustion_propagates_runtime_error(
        self, caplog
    ) -> None:
        """All chain models fail -> RuntimeError propagates + ERROR logged."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                judgment_model="deepseek-v4-flash",
            )
        )
        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = RuntimeError(
            "Model openai/deepseek-v4-flash is not supported"
        )

        with caplog.at_level("ERROR", logger="autoinfo.llm"):
            with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
                with pytest.raises(RuntimeError) as exc_info:
                    call_with_fallback(
                        messages=[{"role": "user", "content": "judge this"}],
                        task="g4_factual",
                        config=config,
                    )

        assert "not supported" in str(exc_info.value)
        assert "Judgment task" in caplog.text
        assert "g4_factual" in caplog.text
        assert any("Judgment task" in record.message for record in caplog.records)

    def test_non_judgment_exhaustion_is_not_judgment_error(self, caplog) -> None:
        """Non-judgment task failure keeps WARNING-level signals, no
        judgment ERROR banner (no false alarm on ordinary pipeline calls)."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
            )
        )
        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = RuntimeError("boom")

        with caplog.at_level("ERROR", logger="autoinfo.llm"):
            with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
                with pytest.raises(RuntimeError):
                    call_with_fallback(
                        messages=[{"role": "user", "content": "extract this"}],
                        task="extraction",
                        config=config,
                    )

        assert "Judgment task" not in caplog.text
        assert not any(
            record.levelno >= logging.ERROR
            for record in caplog.records
            if "extraction" in record.message
        )


class TestDefaultsPreserved:
    """No task config -> current defaults preserved end-to-end."""

    def test_empty_config_extraction_keeps_historical_default(self) -> None:
        """Empty config -> openrouter/deepseek/deepseek-chat (unchanged)."""
        mock_litellm = _mock_litellm(
            json.dumps(
                {
                    "tl_dr": "IVF success rates improve with time-lapse imaging.",
                    "key_points": ["IVF improves with imaging"],
                    "entities": [],
                    "relevance_score": 85,
                }
            )
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            LLMExtractor(config=Config()).extract(_make_item())

        assert _captured_model(mock_litellm) == "openrouter/deepseek/deepseek-chat"

    def test_custom_base_model_without_tasks_unchanged(self) -> None:
        """Base config model (no tasks) flows through untouched."""
        config = Config(
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="")
        )
        mock_litellm = _mock_litellm(
            json.dumps(
                {
                    "tl_dr": "IVF success rates improve with time-lapse imaging.",
                    "key_points": ["IVF improves with imaging"],
                    "entities": [],
                    "relevance_score": 85,
                }
            )
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            LLMExtractor(config=config).extract(_make_item())

        assert _captured_model(mock_litellm) == "openai/gpt-4o-mini"

    def test_explicit_model_param_wins_over_task_routing(self) -> None:
        """An explicit model param beats task routing (retry-chain contract).

        The G4 retry chain passes ``model=`` explicitly per attempt; that
        escalation contract must keep winning over any routing.
        """
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                tasks={"extraction": LLMTaskConfig(model="deepseek-v4-flash")},
            )
        )
        mock_litellm = _mock_litellm(json.dumps({"ok": True}))
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                model="test/model-two",
                task="extraction",
                config=config,
            )

        assert _captured_model(mock_litellm) == "test/model-two"
