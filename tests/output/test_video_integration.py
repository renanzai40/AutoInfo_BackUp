"""Integration tests for the HyperFrames video rendering pipeline.

Tests cover:
- ``render_hyperframes()`` — bun lint + render orchestration (mocked bun)
- ``generate_report_video()`` — full pipeline (TTS + project + render)
- Error handling: missing bun, lint failure, render failure
- ``_render_video_scaffold`` integration with ``generate_report`` (video format)
- Real-render smoke tests, skipped when bun/ffmpeg unavailable
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output.video import (
    VideoConfig,
    generate_report_video,
    render_hyperframes,
)

# HyperFrames render requires bun + ffmpeg/ffprobe + headless Chrome libs.
# The unit tests below mock bun; the real-render tests skip when missing.
BUN = shutil.which("bun")
FFMPEG = shutil.which("ffmpeg")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir() -> str:
    d = tempfile.mkdtemp(prefix="test_video_")
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


def _fake_project(temp_dir: str) -> str:
    """Create a minimal valid HyperFrames project directory."""
    project = os.path.join(temp_dir, "project")
    os.makedirs(os.path.join(project, "compositions"), exist_ok=True)
    with open(os.path.join(project, "package.json"), "w") as f:
        f.write('{"name":"t","dependencies":{"hyperframes":"^0.6.95"}}')
    with open(os.path.join(project, "hyperframes.json"), "w") as f:
        f.write('{"project":{"entry":"index.html","width":1920,"height":1080,"fps":30}}')
    with open(os.path.join(project, "meta.json"), "w") as f:
        f.write('{"scenes":[{"id":"s1","start":0,"duration":5}]}')
    with open(os.path.join(project, "index.html"), "w") as f:
        f.write("<html><body>t</body></html>")
    return project


# ---------------------------------------------------------------------------
# render_hyperframes — mocked bun orchestration
# ---------------------------------------------------------------------------


class TestRenderHyperframes:
    def test_missing_bun_raises(self, temp_dir: str) -> None:
        """Missing bun binary raises FileNotFoundError."""
        project = _fake_project(temp_dir)
        with patch("autoinfo.output.video._find_binary", side_effect=FileNotFoundError("bun")):
            with pytest.raises(FileNotFoundError):
                render_hyperframes(project, os.path.join(temp_dir, "v.mp4"))

    def test_lint_failure_raises(self, temp_dir: str) -> None:
        """Lint non-zero exit raises RuntimeError with output."""
        project = _fake_project(temp_dir)
        proc = MagicMock(returncode=1, stdout="lint error", stderr="")
        with patch("autoinfo.output.video._find_binary", return_value="/usr/bin/bun"), \
             patch("subprocess.run", return_value=proc):
            with pytest.raises(RuntimeError, match="lint failed"):
                render_hyperframes(project, os.path.join(temp_dir, "v.mp4"))

    def test_render_failure_raises(self, temp_dir: str) -> None:
        """Render non-zero exit raises RuntimeError."""
        project = _fake_project(temp_dir)
        lint_ok = MagicMock(returncode=0, stdout="ok", stderr="")
        render_fail = MagicMock(returncode=2, stdout="", stderr="render boom")
        with patch("autoinfo.output.video._find_binary", return_value="/usr/bin/bun"), \
             patch("subprocess.run", side_effect=[lint_ok, render_fail]):
            with pytest.raises(RuntimeError, match="render failed"):
                render_hyperframes(project, os.path.join(temp_dir, "v.mp4"))

    def test_render_success_returns_path(self, temp_dir: str) -> None:
        """Successful render returns the output path and validates size."""
        project = _fake_project(temp_dir)
        output = os.path.join(temp_dir, "v.mp4")
        # Pre-create a real file so the size guard passes.
        with open(output, "wb") as f:
            f.write(b"x" * 200)

        lint_ok = MagicMock(returncode=0, stdout="ok", stderr="")
        render_ok = MagicMock(returncode=0, stdout="", stderr="")
        with patch("autoinfo.output.video._find_binary", return_value="/usr/bin/bun"), \
             patch("subprocess.run", side_effect=[lint_ok, render_ok]) as mock_run:
            result = render_hyperframes(project, output, quality="draft")
        assert result == output
        # Verify the render command includes the quality flag.
        render_call = mock_run.call_args_list[1]
        assert "--quality" in render_call.args[0]
        assert "draft" in render_call.args[0]


# ---------------------------------------------------------------------------
# generate_report_video — full pipeline (mocked render)
# ---------------------------------------------------------------------------


class TestGenerateReportVideo:
    def test_full_pipeline_returns_path(self, temp_dir: str) -> None:
        """TTS + project + render produces a video path."""
        with patch("autoinfo.output.video.generate_audio_narration") as mock_audio, \
             patch("autoinfo.output.video.render_hyperframes") as mock_render:
            mock_audio.return_value = os.path.join(temp_dir, "narration.mp3")
            mock_render.return_value = os.path.join(temp_dir, "video.mp4")

            result = generate_report_video(
                title="Test",
                sections=[{"heading": "H", "body": "B"}],
                output_path=os.path.join(temp_dir, "video.mp4"),
                config=VideoConfig(theme="nord"),
            )
        assert result == os.path.join(temp_dir, "video.mp4")
        mock_render.assert_called_once()
        # theme must reach the render config
        assert mock_render.call_args.kwargs.get("quality") == "draft"

    def test_failure_preserves_work_dir(self, temp_dir: str) -> None:
        """Render failure keeps the work dir for post-mortem, then raises."""
        with patch("autoinfo.output.video.generate_audio_narration") as mock_audio, \
             patch("autoinfo.output.video.render_hyperframes",
                   side_effect=RuntimeError("render boom")):
            mock_audio.return_value = os.path.join(temp_dir, "narration.mp3")
            with pytest.raises(RuntimeError, match="render boom"):
                generate_report_video(
                    title="Test",
                    sections=[{"heading": "H", "body": "B"}],
                )


# ---------------------------------------------------------------------------
# _render_video_scaffold integration with generate_report (video format)
# ---------------------------------------------------------------------------


class TestRenderVideoScaffoldIntegration:
    def test_scaffold_returns_json_contract(self, temp_dir: str) -> None:
        """_render_video_scaffold returns the JSON status blob contract."""
        from autoinfo.output import _render_video_scaffold

        fake_mp4 = os.path.join(temp_dir, "video.mp4")
        with open(fake_mp4, "wb") as f:
            f.write(b"x" * 200)

        with patch(
            "autoinfo.output.video.generate_report_video",
            return_value=fake_mp4,
        ):
            result = _render_video_scaffold(
                {"theme": "nord"},
                "Test Video",
                sections=[{"heading": "H", "body": "B"}],
            )
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["output_type"] == "video"
        assert parsed["format"] == "mp4"
        assert parsed["video_path"]  # absolute mp4 path


# ---------------------------------------------------------------------------
# Real-render smoke tests (skipped when env unavailable)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    BUN is None or FFMPEG is None,
    reason="bun or ffmpeg not on PATH — real HyperFrames render skipped",
)


class TestRealRender:
    def test_real_render_smoke(self, temp_dir: str) -> None:
        """End-to-end render of a generated project produces an MP4."""
        from autoinfo.output.video import generate_hyperframes_project

        project = generate_hyperframes_project(
            title="Smoke",
            sections=[{"heading": "A", "body": "x" * 200}],
            output_dir=os.path.join(temp_dir, "proj"),
            audio_path=None,  # no audio — fallback durations
            config=VideoConfig(quality="draft"),
        )
        output = os.path.join(temp_dir, "smoke.mp4")
        render_hyperframes(project, output, quality="draft")
        assert os.path.isfile(output)
        assert os.path.getsize(output) > 100
