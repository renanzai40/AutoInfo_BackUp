"""Per-task LLM model routing — todo 9 of llm-concurrency-remediation.

Routing table (release-pinned, static — never a runtime classifier):

    extraction / classification  -> ``llm.tasks["extraction"]`` when present,
                                    else the base ``llm`` config
                                    (deepseek-v4-flash this release)
    judgment (G4/G5/llm_judge)   -> ``JUDGMENT_MODEL`` — the release-pinned
                                    constant in ``autoinfo.config``; a
                                    judgment task's task-config model is
                                    NEVER honored (drift guardrail)

The mock-capture asserts the model argument at the provider-call boundary
(``_litellm.completion(model=...)``) — the actual LLM call seam — not
config-layer defaults.  All LLM calls are mocked; no real API calls.

Coverage (plan todo 9):
(a) extraction call -> deepseek-v4-flash; G4/G5 judgment call -> JUDGMENT_MODEL;
(b) judgment task with an invalid task-config model -> still pinned;
(c) no task config -> current defaults preserved (incl. explicit-model wins,
    which keeps the G4 retry-chain model escalation contract intact).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from autoinfo.config import (
    JUDGMENT_MODEL,
    Config,
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
    """G4/G5/llm_judge resolve through the release-pinned JUDGMENT_MODEL."""

    def test_g4_judgment_uses_pinned_model(self) -> None:
        """G4 default model is the pinned judgment model at the boundary."""
        mock_litellm = _mock_litellm(
            json.dumps({"contradiction": False, "explanation": "consistent"})
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = G4FactualConsistency().check(_make_item(), _make_extraction())

        assert result.passed is True
        assert _captured_model(mock_litellm) == JUDGMENT_MODEL

    def test_g5_judgment_uses_pinned_model(self) -> None:
        """G5 default model is the pinned judgment model at the boundary."""
        mock_litellm = _mock_litellm(
            json.dumps({"faithful": True, "explanation": "faithful", "issues": []})
        )
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm):
            result = G5TranslationAccuracy().check(
                _make_item(), _make_extraction(translation="IVF 成功率有所提升。")
            )

        assert result.passed is True
        assert _captured_model(mock_litellm) == JUDGMENT_MODEL

    def test_llm_judge_uses_pinned_model(self) -> None:
        """llm_judge (translation QA gate 5) default is the pinned model."""
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
            )

        assert scores["faithfulness"] == 95
        assert _captured_model(mock_litellm) == JUDGMENT_MODEL


# ===================================================================
# (b) Drift guardrail — judgment task config is never honored
# ===================================================================


class TestJudgmentDriftGuardrail:
    """A judgment task configured with an invalid model stays pinned."""

    def test_resolve_task_llm_config_pins_judgment_model(self) -> None:
        """``_resolve_task_llm_config`` ignores task-config model for judgment."""
        config = Config(
            llm=LLMConfig(
                provider="openai",
                model="some-base-model",
                tasks={"g4_factual": LLMTaskConfig(model="invalid-drifted-model")},
            )
        )
        resolved = _resolve_task_llm_config(config, "g4_factual")
        assert resolved.model == JUDGMENT_MODEL

    def test_call_with_fallback_judgment_task_pinned_at_boundary(self) -> None:
        """Task-routed judgment call reaches the boundary with the pin."""
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

        # JUDGMENT_MODEL is litellm-qualified (e.g. openai/stealth/ox-alpha),
        # so the boundary captures it verbatim — no double prefix.
        assert _captured_model(mock_litellm) == JUDGMENT_MODEL


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
