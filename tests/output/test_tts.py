"""Tests for TTS functionality: _render_audio with OpenAI and edge-tts engines."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import (
    _get_tts_engine_from_config,
    _render_audio,
    _render_audio_edge_tts,
    _render_audio_openai,
)

# ---------------------------------------------------------------------------
# Helpers for mocking edge_tts
# ---------------------------------------------------------------------------


def _register_fake_edge_tts() -> MagicMock:
    """Create a fake ``edge_tts`` module and register it in ``sys.modules``.

    Returns the mock ``Communicate`` class so tests can further configure it.
    """
    fake_module = MagicMock()
    fake_comm = MagicMock()
    fake_module.Communicate = fake_comm
    sys.modules["edge_tts"] = fake_module
    return fake_comm


def _cleanup_fake_edge_tts() -> None:
    """Remove the fake ``edge_tts`` module from ``sys.modules``."""
    sys.modules.pop("edge_tts", None)


# ---------------------------------------------------------------------------
# OpenAI TTS engine tests
# ---------------------------------------------------------------------------


class TestRenderAudioOpenAI:
    """Tests for _render_audio with engine="openai"."""

    @pytest.fixture(autouse=True)
    def mock_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test-key")

    def test_openai_returns_mp3_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test-key")

        mock_response = MagicMock()
        mock_response.content = b"fake-mp3-bytes"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response):
            result = _render_audio("Hello world", engine="openai")

        assert isinstance(result, bytes)
        assert result == b"fake-mp3-bytes"

    def test_openai_via_main_function(self) -> None:
        mock_response = MagicMock()
        mock_response.content = b"mp3-data"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response):
            result = _render_audio("Test text", engine="openai")

        assert result == b"mp3-data"

    def test_openai_missing_text_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Cannot render empty text"):
            _render_audio("", engine="openai")

    def test_openai_text_exceeds_char_limit_truncated(self) -> None:
        long_text = "x" * 5000
        mock_response = MagicMock()
        mock_response.content = b"truncated-mp3"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post") as mock_post:
            mock_post.return_value = mock_response
            result = _render_audio(long_text, engine="openai")

        # Verify truncated text was sent (4000 chars + truncation note)
        call_args = mock_post.call_args
        sent_input = call_args[1]["json"]["input"]
        assert len(sent_input) < 4100
        assert "[truncated]" in sent_input
        assert result == b"truncated-mp3"

    def test_openai_custom_voice(self) -> None:
        mock_response = MagicMock()
        mock_response.content = b"nova-mp3"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post") as mock_post:
            mock_post.return_value = mock_response
            result = _render_audio("Hello", engine="openai", voice="nova")

        call_args = mock_post.call_args
        assert call_args[1]["json"]["voice"] == "nova"
        assert result == b"nova-mp3"

    def test_openai_http_error_raises_runtimeerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test-key")

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.json.return_value = {"error": "Unauthorized"}
        mock_request = MagicMock()

        http_error = httpx.HTTPStatusError(
            "Unauthorized", request=mock_request, response=mock_response
        )

        with patch(
            "httpx.post", side_effect=http_error
        ), pytest.raises(RuntimeError, match="OpenAI TTS API error"):
            _render_audio("test", engine="openai")

    def test_openai_no_api_key_raises_runtimeerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with patch(
            "autoinfo.output.get_config_path", return_value=None
        ), pytest.raises(RuntimeError, match="AUTOINFO_LLM_API_KEY"):
            _render_audio_openai("test")

    def test_openai_empty_response_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.content = b""
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response), pytest.raises(
            RuntimeError, match="empty audio data"
        ):
            _render_audio_openai("test")


# ---------------------------------------------------------------------------
# Local edge-tts engine tests
# ---------------------------------------------------------------------------


class TestRenderAudioEdgeTTS:
    """Tests for _render_audio with engine="local" (edge-tts)."""

    def test_local_returns_mp3_bytes(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"chunk1"}
                yield {"type": "audio", "data": b"chunk2"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            result = _render_audio("Hello world", engine="local")
        finally:
            _cleanup_fake_edge_tts()

        assert isinstance(result, bytes)
        assert result == b"chunk1chunk2"

    def test_local_custom_voice(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"voice-data"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            result = _render_audio(
                "Hello", engine="local", local_voice="en-GB-SoniaNeural"
            )
        finally:
            _cleanup_fake_edge_tts()

        fake_comm.assert_called_once_with("Hello", "en-GB-SoniaNeural")
        assert result == b"voice-data"

    def test_local_empty_audio_raises(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "WordBoundary", "data": b""}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            with pytest.raises(RuntimeError, match="empty audio data"):
                _render_audio_edge_tts("test")
        finally:
            _cleanup_fake_edge_tts()


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------


class TestFallback:
    """Tests for graceful fallback when edge-tts is not installed."""

    def test_local_falls_back_to_openai_when_edge_tts_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-fallback")

        # Remove edge_tts from sys.modules to simulate not installed
        with patch.dict(sys.modules, {"edge_tts": None}):
            mock_response = MagicMock()
            mock_response.content = b"fallback-mp3"
            mock_response.raise_for_status = MagicMock()

            with patch(
                "httpx.post", return_value=mock_response
            ) as mock_post:
                result = _render_audio("Hello", engine="local")

            assert mock_post.called
            assert result == b"fallback-mp3"

    def test_local_runtime_error_reraises_without_openai_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # engine="local" re-raises synthesis failures (never falls back to
        # OpenAI — the user chose local explicitly); ImportError still
        # falls back, covered by the not-installed sibling test above.
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-fallback")

        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                raise RuntimeError("TTS service unavailable")
                yield  # unreachable; makes this an async generator (edge-tts stream() yields)

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            with patch("httpx.post") as mock_post:
                with pytest.raises(RuntimeError, match="TTS service unavailable"):
                    _render_audio("Hello", engine="local")
        finally:
            _cleanup_fake_edge_tts()

        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Engine resolution tests
# ---------------------------------------------------------------------------


class TestEngineResolution:
    """Tests for engine parameter resolution."""

    def test_defaults_to_openai_when_engine_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-default")

        mock_response = MagicMock()
        mock_response.content = b"default-openai"
        mock_response.raise_for_status = MagicMock()

        with patch("autoinfo.output.get_config_path", return_value=None):
            with patch("httpx.post", return_value=mock_response):
                result = _render_audio("test", engine=None)

        assert result == b"default-openai"

    def test_unknown_engine_falls_back_to_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-unknown")

        mock_response = MagicMock()
        mock_response.content = b"unknown-fallback"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response):
            result = _render_audio("test", engine="invalid-engine")

        assert result == b"unknown-fallback"


# ---------------------------------------------------------------------------
# Config TTS section tests
# ---------------------------------------------------------------------------


class TestTTSConfig:
    """Tests for TTSConfig parsing from YAML config."""

    def test_config_parses_tts_section(self) -> None:
        from autoinfo.config import Config, TTSConfig

        config = Config()
        assert isinstance(config.tts, TTSConfig)
        assert config.tts.engine == "local"
        assert config.tts.local_voice == "en-US-JennyNeural"

    def test_config_tts_defaults(self) -> None:
        from autoinfo.config import TTSConfig

        tts = TTSConfig()
        assert tts.engine == "local"
        assert tts.local_voice == "en-US-JennyNeural"

    def test_config_tts_custom_engine(self) -> None:
        from autoinfo.config import TTSConfig

        tts = TTSConfig(engine="local", local_voice="en-GB-SoniaNeural")
        assert tts.engine == "local"
        assert tts.local_voice == "en-GB-SoniaNeural"

    def test_get_tts_engine_from_config_returns_default(self) -> None:
        with patch(
            "autoinfo.output.get_config_path", return_value=None
        ):
            result = _get_tts_engine_from_config()
        assert result == "local"

    def test_get_tts_engine_from_config_reads_tts_section(
        self, tmp_path: Path
    ) -> None:
        import yaml

        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"tts": {"engine": "local", "local_voice": "en-GB"}}),
            encoding="utf-8",
        )

        with patch(
            "autoinfo.output.get_config_path", return_value=config_file
        ):
            result = _get_tts_engine_from_config()
        assert result == "local"


class TestRenderAudioEdgeTTSDirect:
    """Tests for _render_audio_edge_tts helper directly."""

    def test_edge_tts_helper_returns_bytes(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"edge-data"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            result = _render_audio_edge_tts("test")
        finally:
            _cleanup_fake_edge_tts()

        assert result == b"edge-data"
        assert isinstance(result, bytes)

    def test_edge_tts_helper_respects_voice(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"x"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            _render_audio_edge_tts("test", voice="en-AU-NatashaNeural")
        finally:
            _cleanup_fake_edge_tts()

        fake_comm.assert_called_once_with("test", "en-AU-NatashaNeural")

    def test_edge_tts_import_error_propagates(self) -> None:
        """When edge_tts is truly not importable, ImportError is raised."""
        with patch.dict(sys.modules, {"edge_tts": None}):
            with pytest.raises(ImportError):
                _render_audio_edge_tts("test")

    def test_edge_tts_timeout_raises_runtimeerror(self) -> None:
        import asyncio

        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                await asyncio.sleep(99)
                yield {"type": "audio", "data": b"x"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            with pytest.raises(RuntimeError, match="timed out"):
                _render_audio_edge_tts("test", timeout=0.01)
        finally:
            _cleanup_fake_edge_tts()


# ---------------------------------------------------------------------------
# Top-level _render_audio engine=local test
# ---------------------------------------------------------------------------


class TestRenderAudioWithEngineLocal:
    """Integration-style tests for _render_audio(engine='local')."""

    def test_render_audio_engine_local_works(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"local-mp3"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            result = _render_audio("Hello world", engine="local")
        finally:
            _cleanup_fake_edge_tts()

        assert result == b"local-mp3"

    def test_render_audio_engine_local_empty_text_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot render empty text"):
            _render_audio("", engine="local")

    def test_render_audio_engine_local_strips_markdown(self) -> None:
        fake_comm = _register_fake_edge_tts()
        try:
            async def mock_stream():
                yield {"type": "audio", "data": b"stripped"}

            instance = MagicMock()
            instance.stream = MagicMock(return_value=mock_stream())
            fake_comm.return_value = instance

            _render_audio("**bold** and *italic* text", engine="local")
        finally:
            _cleanup_fake_edge_tts()

        # edge_tts.Communicate should receive stripped text (no markdown)
        call_args = fake_comm.call_args[0]
        assert "**" not in call_args[0]
        assert "*" not in call_args[0]
