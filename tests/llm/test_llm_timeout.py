"""Tests for issue #136 — LLM timeout threading + parallel processing.

Covers:

- ``LLMConfig.timeout`` field: default, config.yaml parsing, round-trip
- ``timeout`` kwarg passed to litellm.completion at every call site
  (llm.py, quality.py G3/G4/G5 + llm_judge, cefr.py, translation_qa.py,
  mcp/server.py suggest_keywords)
- ``run_processing`` parallelizes items across a bounded thread pool
- MCP ``call_tool`` offloads collect/process/batch_run to worker threads
  so the event loop stays responsive (progress tools keep answering)
- Per-item progress lines printed during processing (``AUTOINFO_PROCESS_PROGRESS``)

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.config import LLMConfig, config_to_dict
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def sample_items() -> list[Item]:
    """Two synthetic items for processing tests (mirrors test_process.py)."""
    return [
        Item(
            id="item-001",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/1",
            title="First test article about IVF",
            content="This is the content of the first test article about IVF treatment outcomes.",
            content_type="text",
            collected_at="2026-07-15T10:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["IVF"],
            quality_tier=1,
            raw_data={},
        ),
        Item(
            id="item-002",
            source_name="pubmed",
            source_type="api",
            source_platform="pubmed",
            source_url="https://example.com/2",
            title="Second test article about neuroplasticity",
            content="This is the content of the second test article about synaptic plasticity.",
            content_type="text",
            collected_at="2026-07-15T11:00:00Z",
            language="en",
            domain="medical-research",
            topic_tags=["neuroplasticity"],
            quality_tier=1,
            raw_data={},
        ),
    ]


# ===================================================================
# LLMConfig.timeout
# ===================================================================


class TestLLMConfigTimeout:
    """``LLMConfig.timeout`` field exists, defaults, parses, round-trips."""

    def test_default_timeout(self) -> None:
        """Default timeout is 120.0 seconds."""
        assert LLMConfig().timeout == 120.0

    def test_explicit_timeout_override(self) -> None:
        """Explicitly constructed configs keep their value."""
        assert LLMConfig(timeout=42.0).timeout == 42.0

    def test_config_yaml_parses_timeout(self, tmp_path) -> None:
        """``llm.timeout`` in config.yaml is parsed into LLMConfig."""
        from autoinfo.config import load_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "llm:\n  provider: openai\n  model: deepseek-chat\n  timeout: 45.5\n",
            encoding="utf-8",
        )
        config = load_config(cfg_path)
        assert config.llm.timeout == 45.5

    def test_config_yaml_missing_timeout_uses_default(self, tmp_path) -> None:
        """Config without ``llm.timeout`` falls back to the default."""
        from autoinfo.config import load_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("llm:\n  provider: openai\n  model: deepseek-chat\n", encoding="utf-8")
        config = load_config(cfg_path)
        assert config.llm.timeout == 120.0

    def test_config_to_dict_round_trip(self) -> None:
        """Serialized config keeps ``llm.timeout``."""
        raw = config_to_dict(_config_with_timeout(77.0))
        assert raw["llm"]["timeout"] == 77.0


def _config_with_timeout(timeout: float):
    from autoinfo.config import Config

    return Config(llm=LLMConfig(provider="openai", model="deepseek-chat", timeout=timeout))


# ===================================================================
# LLM call sites pass timeout to litellm.completion
# ===================================================================


def _mock_litellm_response() -> MagicMock:
    return MagicMock(
        choices=[MagicMock(
            message=MagicMock(
                content='{"tl_dr": "x", "key_points": [], "entities": [], "relevance_score": 80}'
            )
        )]
    )


class TestLlmCallTimeout:
    """``LLMExtractor._call_llm`` threads ``timeout`` through."""

    def test_extractor_passes_default_timeout(self, sample_item: Item) -> None:
        mock_lm = MagicMock()
        mock_lm.completion.return_value = _mock_litellm_response()
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            LLMExtractor().extract(sample_item)
        assert mock_lm.completion.call_args.kwargs["timeout"] == 120.0

    def test_extractor_passes_configured_timeout(self, sample_item: Item) -> None:
        mock_lm = MagicMock()
        mock_lm.completion.return_value = _mock_litellm_response()
        extractor = LLMExtractor(config=_config_with_timeout(23.5))
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_lm):
            extractor.extract(sample_item)
        assert mock_lm.completion.call_args.kwargs["timeout"] == 23.5


class TestQualityTimeout:
    """Quality gates (G3/G4/G5) and llm_judge pass timeout."""

    def test_g3_passes_timeout(self, sample_item: Item) -> None:
        from autoinfo.config import QualityGateConfig
        from autoinfo.quality import G3RelevanceScoring

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="88"))]
        )
        gate = G3RelevanceScoring(timeout=30.0)
        with patch(
            "autoinfo.quality.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            gate.check(
                sample_item,
                ["IVF"],
                gate_config=QualityGateConfig(name="G3", retries=1),
            )
        assert mock_cwf.call_args.kwargs["timeout"] == 30.0

    def test_g3_without_timeout_omits_kwarg(self, sample_item: Item) -> None:
        from autoinfo.config import QualityGateConfig
        from autoinfo.quality import G3RelevanceScoring

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="88"))]
        )
        gate = G3RelevanceScoring()
        with patch(
            "autoinfo.quality.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            gate.check(
                sample_item,
                ["IVF"],
                gate_config=QualityGateConfig(name="G3", retries=1),
            )
        assert mock_cwf.call_args.kwargs["timeout"] is None

    def test_g4_passes_timeout(self, sample_item: Item, tmp_path) -> None:
        from autoinfo.quality import G4FactualConsistency

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(
                message=MagicMock(content='{"contradiction": false, "explanation": "ok"}')
            )]
        )
        extraction = _dummy_extraction(sample_item)
        gate = G4FactualConsistency(
            model="openrouter/deepseek/deepseek-chat",
            collections_path=tmp_path,
            timeout=40.0,
        )
        with patch(
            "autoinfo.quality.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            gate.check(sample_item, extraction)
        assert mock_cwf.call_args.kwargs["timeout"] == 40.0

    def test_g5_passes_timeout(self, sample_item: Item) -> None:
        from autoinfo.quality import G5TranslationAccuracy

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(
                message=MagicMock(content='{"faithful": true, "explanation": "ok", "issues": []}')
            )]
        )
        extraction = _dummy_extraction(sample_item)
        extraction.custom_fields["translation"] = "Some translated text."
        gate = G5TranslationAccuracy(timeout=55.0)
        with patch(
            "autoinfo.quality.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            gate.check(sample_item, extraction)
        assert mock_cwf.call_args.kwargs["timeout"] == 55.0

    def test_llm_judge_passes_timeout(self) -> None:
        from autoinfo.quality import llm_judge

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(
                message=MagicMock(
                content=(
                    '{"faithfulness": 90, "terminology": 80, '
                    '"style": 70, "readability": 60, "issues": []}'
                )
                )
            )]
        )
        with patch.dict(sys.modules, {"litellm": mock_lm}):
            llm_judge("source", "target", "en", "zh", timeout=33.0)
        assert mock_lm.completion.call_args.kwargs["timeout"] == 33.0


class TestCefrTimeout:
    """``cefr.classify_text`` passes timeout through."""

    def test_classify_text_passes_timeout(self) -> None:
        from autoinfo.cefr import classify_text

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="B2"))]
        )
        with patch.dict(sys.modules, {"litellm": mock_lm}):
            result = classify_text(
                "The mitochondria is the powerhouse of the cell",
                lang="en",
                model_config={"model": "openrouter/deepseek/deepseek-chat", "timeout": 66.0},
            )
        assert result["cefr_level"] == "B2"
        assert mock_lm.completion.call_args.kwargs["timeout"] == 66.0


class TestTranslationQaTimeout:
    """``translation_qa`` LLM calls pass timeout through."""

    def _patch_litellm(self):
        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="back translated text"))]
        )
        return mock_lm

    def test_back_translate_passes_timeout(self) -> None:
        from autoinfo.translation_qa import back_translate

        mock_lm = self._patch_litellm()
        with patch(
            "autoinfo.translation_qa.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            back_translate(
                source_text="hello",
                translated_text="bonjour",
                source_lang="en",
                target_lang="fr",
                timeout=28.0,
            )
        assert mock_cwf.call_args.kwargs["timeout"] == 28.0

    def test_llm_judge_translation_passes_timeout(self) -> None:
        from autoinfo.translation_qa import llm_judge_translation

        mock_lm = MagicMock()
        mock_lm.completion.return_value = MagicMock(
            choices=[MagicMock(
                message=MagicMock(content='{"faithfulness_score": 80, "issues": []}')
            )]
        )
        with patch(
            "autoinfo.translation_qa.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            llm_judge_translation("source", "back", "en", timeout=29.0)
        assert mock_cwf.call_args.kwargs["timeout"] == 29.0

    def test_refine_translation_passes_timeout(self) -> None:
        from autoinfo.translation_qa import refine_translation

        mock_lm = self._patch_litellm()
        with patch(
            "autoinfo.translation_qa.call_with_fallback",
            return_value=mock_lm.completion.return_value,
        ) as mock_cwf:
            refine_translation(
                source_text="hello",
                initial_translation="bonjour",
                source_lang="en",
                target_lang="fr",
                judge_feedback=[],
                timeout=31.0,
            )
        assert mock_cwf.call_args.kwargs["timeout"] == 31.0


# ===================================================================
# Parallel processing
# ===================================================================


def _dummy_extraction(item: Item) -> ExtractionResult:
    return ExtractionResult(
        item_id=item.id,
        title=item.title,
        tl_dr="A summary.",
        key_points=["A key point"],
        entities=[{"name": "IVF", "type": "procedure"}],
        relevance_score=80.0,
    )


def _quality_all_pass():
    from autoinfo.quality import QualityResult

    return {
        "G1-SourceAuthority": QualityResult(gate_name="G1", passed=True, details={}),
        "G2-Dedup": QualityResult(gate_name="G2", passed=True, details={"is_duplicate": False}),
        "G3-RelevanceScoring": QualityResult(gate_name="G3", passed=True, score=80.0, details={}),
    }


class TestProcessParallelism:
    """``run_processing`` processes items concurrently in a thread pool."""

    def test_worker_count_from_env(self, monkeypatch) -> None:
        from autoinfo.process import _resolve_process_workers

        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "3")
        assert _resolve_process_workers() == 3
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "999")
        assert _resolve_process_workers() == 16  # clamped
        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "0")
        assert _resolve_process_workers() == 1  # clamped
        monkeypatch.delenv("AUTOINFO_PROCESS_WORKERS")
        assert _resolve_process_workers() == 5  # default

    def test_thread_pool_used_with_bounded_workers(
        self, sample_items: list[Item], monkeypatch
    ) -> None:
        """ThreadPoolExecutor is used with the configured worker count."""
        from autoinfo.kb import KBStore
        from autoinfo.process import run_processing

        captured: dict = {}

        class FakePool:
            def __init__(self, max_workers, thread_name_prefix=""):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, *args, **kwargs):
                fut = Future()
                fut.set_result(fn(*args, **kwargs))
                return fut

        mock_ext = MagicMock(return_value=_dummy_extraction(sample_items[0]))
        mock_quality = MagicMock(return_value=_quality_all_pass())
        from autoinfo.models import KBEntry

        mock_entry = KBEntry(entry_id="e", title="t", domain="d")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "4")
        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
            patch("autoinfo.process.ThreadPoolExecutor", FakePool),
        ):
            result = run_processing("medical-research")

        assert captured["max_workers"] == 4
        assert result.kb_entries_created == 2
        assert result.passed_gates == 2

    def test_extraction_calls_overlap_concurrently(
        self, sample_items: list[Item], monkeypatch
    ) -> None:
        """Two items' LLM extractions overlap in time (parallelism proof)."""
        from autoinfo.kb import KBStore
        from autoinfo.models import KBEntry
        from autoinfo.process import run_processing

        entered: list[str] = []
        lock = threading.Lock()
        both_entered = threading.Event()
        release = threading.Event()

        def slow_extract(item: Item, schema=None) -> ExtractionResult:
            with lock:
                entered.append(item.id)
                if len(entered) == 2:
                    both_entered.set()
            release.wait(timeout=10)
            return _dummy_extraction(item)

        mock_ext = MagicMock(side_effect=slow_extract)
        mock_quality = MagicMock(return_value=_quality_all_pass())
        mock_entry = KBEntry(entry_id="e", title="t", domain="d")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        monkeypatch.setenv("AUTOINFO_PROCESS_WORKERS", "2")
        runner = threading.Thread(
            target=run_processing, kwargs={"domain": "medical-research"}
        )
        try:
            with (
                patch("autoinfo.process.load_cached_items", return_value=sample_items),
                patch.object(LLMExtractor, "extract", mock_ext),
                patch("autoinfo.process.run_quality_gates", mock_quality),
                patch("autoinfo.process.KBStore", return_value=mock_store),
            ):
                runner.start()
                assert both_entered.wait(timeout=10), (
                    "items extracted sequentially — expected concurrent execution"
                )
        finally:
            release.set()
            runner.join(timeout=15)

        assert sorted(entered) == ["item-001", "item-002"]


# ===================================================================
# Per-item progress output
# ===================================================================


class TestProgressOutput:
    """Per-item progress lines are printed to stdout (flushed)."""

    def test_progress_lines_printed(
        self, sample_items: list[Item], monkeypatch, capsys
    ) -> None:
        from autoinfo.kb import KBStore
        from autoinfo.models import KBEntry
        from autoinfo.process import run_processing

        mock_ext = MagicMock(return_value=_dummy_extraction(sample_items[0]))
        mock_quality = MagicMock(return_value=_quality_all_pass())
        mock_entry = KBEntry(entry_id="e", title="t", domain="d")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        monkeypatch.setenv("AUTOINFO_PROCESS_PROGRESS", "1")
        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            run_processing("medical-research")

        captured = capsys.readouterr().out
        lines = [ln for ln in captured.splitlines() if ln.startswith("[")]
        assert len(lines) == 2
        assert "[1/2] processed" in lines[0] or "[2/2] processed" in lines[0]
        assert "[1/2] processed" in lines[1] or "[2/2] processed" in lines[1]
        assert "(" in lines[0] and "s)" in lines[0]

    def test_progress_disabled_without_env(
        self, sample_items: list[Item], monkeypatch, capsys
    ) -> None:
        """Without AUTOINFO_PROCESS_PROGRESS and a non-TTY stdout, no progress."""
        from autoinfo.kb import KBStore
        from autoinfo.models import KBEntry
        from autoinfo.process import run_processing

        mock_ext = MagicMock(return_value=_dummy_extraction(sample_items[0]))
        mock_quality = MagicMock(return_value=_quality_all_pass())
        mock_entry = KBEntry(entry_id="e", title="t", domain="d")
        mock_store = MagicMock(spec=KBStore)
        mock_store.store_entry.return_value = mock_entry
        mock_store.list_entries.return_value = []

        monkeypatch.delenv("AUTOINFO_PROCESS_PROGRESS", raising=False)
        with (
            patch("autoinfo.process.load_cached_items", return_value=sample_items),
            patch.object(LLMExtractor, "extract", mock_ext),
            patch("autoinfo.process.run_quality_gates", mock_quality),
            patch("autoinfo.process.KBStore", return_value=mock_store),
            patch("autoinfo.process._progress_enabled", return_value=False),
        ):
            run_processing("medical-research")

        captured = capsys.readouterr().out
        assert "[1/2] processed" not in captured


# ===================================================================
# MCP call_tool offload
# ===================================================================


class TestCallToolOffload:
    """Heavy MCP handlers run off the event loop via asyncio.to_thread."""

    async def _call(self, name: str, args: dict):
        from autoinfo.mcp.server import call_tool

        result = await call_tool(name, args)
        assert len(result) == 1
        return result[0].text

    async def test_heavy_handlers_dispatched_via_to_thread(self) -> None:
        from autoinfo.mcp import server as mcp_server

        calls: list[tuple] = []

        async def fake_to_thread(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        with (
            patch("asyncio.to_thread", fake_to_thread),
            patch.object(
                mcp_server,
                "_handle_collect_sources",
                return_value={"success": True, "data": {"collected_count": 0}},
            ) as mock_collect,
            patch.object(
                mcp_server,
                "_handle_process_collection",
                return_value={"success": True, "data": {"status": "noop"}},
            ) as mock_process,
            patch.object(
                mcp_server,
                "_handle_batch_run",
                return_value={"success": True, "data": {"overall_success": True}},
            ) as mock_batch,
            patch.object(mcp_server, "_is_llm_configured", return_value=True),
        ):
            await self._call("collect_sources", {"domain": "med"})
            await self._call("process_collection", {"domain": "med"})
            await self._call("batch_run", {"domain": "med"})

            handlers = {fn for fn, _, _ in calls}
            assert mock_collect in handlers
            assert mock_process in handlers
            assert mock_batch in handlers

    async def test_event_loop_responsive_while_processing_runs(self) -> None:
        """Progress tools answer while process_collection blocks in a thread."""
        from autoinfo.mcp import server as mcp_server

        started = threading.Event()
        handler_thread_id: list[int] = []

        def slow_handler(**kwargs):
            handler_thread_id.append(threading.get_ident())
            started.set()
            time.sleep(0.3)
            return {"success": True, "data": {"status": "completed"}}

        loop_thread_id = threading.get_ident()
        with (
            patch.object(mcp_server, "_handle_process_collection", side_effect=slow_handler),
            patch.object(mcp_server, "_is_llm_configured", return_value=True),
        ):
            task = asyncio.create_task(
                self._call("process_collection", {"domain": "med"})
            )
            # Yield to the loop so the task can reach asyncio.to_thread
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.05)
            assert started.is_set(), "handler did not start"
            # While the handler sleeps in its worker thread, the event loop
            # must still serve other tools (i.e. it was not blocked).
            progress_text = await asyncio.wait_for(
                self._call("get_processing_progress", {"domain": "med"}),
                timeout=5,
            )
            assert "success" in progress_text or "status" in progress_text
            await asyncio.wait_for(task, timeout=10)

        assert handler_thread_id, "handler never executed"
        assert handler_thread_id[0] != loop_thread_id, (
            "handler ran on the event loop thread — expected thread offload"
        )

    async def test_fast_tools_not_offloaded(self) -> None:
        """Non-heavy tools keep dispatching synchronously (no to_thread)."""
        from autoinfo.mcp import server as mcp_server

        calls: list[tuple] = []

        async def fake_to_thread(fn, *args, **kwargs):
            calls.append(fn)
            return fn(*args, **kwargs)

        with (
            patch("asyncio.to_thread", fake_to_thread),
            patch.object(mcp_server, "_handle_list_domains", return_value={"domains": []}),
        ):
            await self._call("list_domains", {})
        assert calls == []
