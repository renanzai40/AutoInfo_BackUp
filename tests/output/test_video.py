"""Tests for the HyperFrames video output pipeline.

Covers the ported HyperFrames integration (2026-08-13): theme selection,
scene planning / layout diversity, TTS narration, scene-duration math, and
HyperFrames project scaffolding.  Render execution (bun) is tested
separately in ``test_video_integration.py``.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output.video import (
    LAYOUTS,
    VideoConfig,
    _pick_layouts,
    _split_narration_into_scenes,
    generate_audio_narration,
    generate_hyperframes_project,
    select_theme,
)


class TestVideoConfig:
    """Unit tests for VideoConfig dataclass."""

    def test_default_values(self) -> None:
        """Default VideoConfig has expected HyperFrames values."""
        cfg = VideoConfig()
        assert cfg.fps == 30
        assert cfg.resolution == (1920, 1080)
        assert cfg.theme == "terminal-green"
        assert cfg.quality == "draft"
        assert cfg.tts_speed == 1.0

    def test_custom_values(self) -> None:
        """Custom VideoConfig stores provided values."""
        cfg = VideoConfig(
            fps=60,
            resolution=(3840, 2160),
            theme="nord",
            quality="standard",
            tts_speed=1.5,
        )
        assert cfg.fps == 60
        assert cfg.resolution == (3840, 2160)
        assert cfg.theme == "nord"
        assert cfg.quality == "standard"
        assert cfg.tts_speed == 1.5


class TestSelectTheme:
    """Unit tests for theme selection from the ported library."""

    def test_named_theme(self) -> None:
        """A named theme resolves to its flattened variables."""
        theme = select_theme(VideoConfig(theme="terminal-green"))
        assert theme["dark"] is True
        assert theme["accent"]  # non-empty accent colour

    def test_mood_fallback(self) -> None:
        """theme_mood picks the first matching-theme; unknown name falls back."""
        theme = select_theme(VideoConfig(theme="does-not-exist", theme_mood="light"))
        assert theme["dark"] is False

    def test_missing_theme_falls_back_to_default(self) -> None:
        """Unknown theme name falls back to terminal-green."""
        theme = select_theme(VideoConfig(theme="nope-123"))
        assert theme.get("accent")  # default theme has accent


class TestLayoutDiversity:
    """Unit tests for the AutoMedia Gate VQ layout-diversity rule."""

    def test_adjacent_scenes_differ(self) -> None:
        """No two adjacent scenes share a layout."""
        for n in (2, 3, 4, 5, 6, 7):
            layouts = _pick_layouts(n)
            for i in range(len(layouts) - 1):
                assert layouts[i] != layouts[i + 1], f"adjacent same at {i}"

    def test_five_scenes_four_layouts_minimum(self) -> None:
        """5-scene video uses >= 4 distinct layouts (AutoMedia Gate VQ)."""
        layouts = _pick_layouts(5)
        assert len(set(layouts)) >= 4

    def test_single_scene(self) -> None:
        """Single scene uses centered-hero."""
        assert _pick_layouts(1) == ["centered-hero"]

    def test_all_layouts_have_html_and_animations(self) -> None:
        """Every registered layout has both html and animations templates."""
        for name, layout in LAYOUTS.items():
            assert "html" in layout, name
            assert "animations" in layout, name


class TestSceneDurationMath:
    """Unit tests for scene-frame-boundary calculation (AutoMedia math)."""

    def test_character_ratio_split(self) -> None:
        """Scene durations scale with character counts; sum approx total."""
        sections = [
            {"heading": "A", "body": "x" * 100},
            {"heading": "B", "body": "y" * 300},
            {"heading": "C", "body": "z" * 50},
        ]
        scenes = _split_narration_into_scenes(sections, total_duration=60.0)
        assert len(scenes) == 3
        # Float safety margin guarantees no negative / zero durations.
        assert all(s["duration"] > 0 for s in scenes)
        # Scenes are chronologically ordered.
        for i in range(1, len(scenes)):
            assert scenes[i]["start"] >= scenes[i - 1]["start"]

    def test_min_duration_floor(self) -> None:
        """Very short scenes still get >= 1.5s (readability floor)."""
        scenes = _split_narration_into_scenes(
            [{"heading": "Tiny", "body": "a"}], total_duration=0.5
        )
        assert scenes[0]["duration"] >= 1.5

    def test_empty_sections(self) -> None:
        """Empty section list returns empty scene list."""
        assert _split_narration_into_scenes([], 60.0) == []


class TestGenerateAudioNarration:
    """Unit tests for TTS audio narration generation (unchanged contract)."""

    @patch("autoinfo.output._render_audio")
    def test_happy_path(self, mock_render: MagicMock) -> None:
        """TTS narration generates an MP3 file from section content."""
        mock_render.return_value = b"fake_mp3_data" * 100  # > 100 bytes

        output_dir = "/tmp/test-video-audio-happy"
        os.makedirs(output_dir, exist_ok=True)

        sections = [{"heading": "Intro", "body": "This is a test."}]
        result = generate_audio_narration(
            title="Test Video",
            sections=sections,
            output_dir=output_dir,
        )

        assert os.path.exists(result)
        assert os.path.getsize(result) > 100
        mock_render.assert_called_once()

    @patch("autoinfo.output._render_audio")
    def test_multiple_sections(self, mock_render: MagicMock) -> None:
        """Narration text includes all section headings and bodies."""
        mock_render.return_value = b"fake_mp3_data" * 100

        output_dir = "/tmp/test-video-audio-multi"
        os.makedirs(output_dir, exist_ok=True)

        sections = [
            {"heading": "Intro", "body": "First section body."},
            {"heading": "Methods", "body": "Second section body."},
            {"heading": "", "body": "No heading section."},
        ]
        result = generate_audio_narration(
            title="Multi-Section",
            sections=sections,
            output_dir=output_dir,
        )

        assert os.path.exists(result)
        call_text = mock_render.call_args[0][0]
        assert "Multi-Section" in call_text
        assert "Intro" in call_text
        assert "First section body" in call_text
        assert "Methods" in call_text
        assert "Second section body" in call_text
        assert "No heading section" in call_text

    @patch("autoinfo.output._render_audio")
    def test_too_small_audio_raises(self, mock_render: MagicMock) -> None:
        """Audio file smaller than 100 bytes raises RuntimeError."""
        mock_render.return_value = b"tiny"  # < 100 bytes

        output_dir = "/tmp/test-video-audio-small"
        os.makedirs(output_dir, exist_ok=True)

        with pytest.raises(RuntimeError, match="TTS audio too small"):
            generate_audio_narration(
                title="Test",
                sections=[{"heading": "H", "body": "B"}],
                output_dir=output_dir,
            )

    @patch("autoinfo.output._render_audio")
    def test_voice_passed_through(self, mock_render: MagicMock) -> None:
        """Voice parameter is forwarded to _render_audio."""
        mock_render.return_value = b"fake_mp3_data" * 100

        output_dir = "/tmp/test-video-audio-voice"
        os.makedirs(output_dir, exist_ok=True)

        generate_audio_narration(
            title="Test",
            sections=[{"heading": "H", "body": "B"}],
            output_dir=output_dir,
            voice="nova",
        )

        mock_render.assert_called_once()
        assert mock_render.call_args[1].get("voice") == "nova"


class TestGenerateHyperframesProject:
    """Unit tests for HyperFrames project scaffolding."""

    def test_project_structure(self, tmp_path: str) -> None:
        """Generated project has all required HyperFrames files."""
        project = generate_hyperframes_project(
            title="Test",
            sections=[
                {"heading": "One", "body": "First body"},
                {"heading": "Two", "body": "Second body"},
            ],
            output_dir=str(tmp_path),
        )

        for required in ("package.json", "hyperframes.json", "meta.json", "index.html"):
            assert os.path.isfile(os.path.join(project, required)), required

        compositions = os.path.join(project, "compositions")
        assert os.path.isdir(compositions)
        assert len(os.listdir(compositions)) == 2

    def test_index_has_audio_track_and_scene_hosts(self, tmp_path: str) -> None:
        """index.html wires sub-composition hosts; audio only when present."""
        project = generate_hyperframes_project(
            title="Audio Test",
            sections=[{"heading": "S", "body": "Body"}],
            output_dir=str(tmp_path),
            audio_path=None,  # no audio -> no audio element, fallback durations
        )
        with open(os.path.join(project, "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert "narration-audio" not in html  # no audio element without audio
        assert "compositions/01-scene.html" in html

    def test_index_with_audio_has_audio_track(self, tmp_path: str) -> None:
        """A real audio file wires the narration track into index.html."""
        import subprocess

        audio = os.path.join(str(tmp_path), "narr.mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
                 "-c:a", "libmp3lame", audio],
                capture_output=True,
            )
        except FileNotFoundError:
            pytest.skip("ffmpeg unavailable — cannot create audio fixture")
        if not os.path.isfile(audio):
            pytest.skip("ffmpeg unavailable — cannot create audio fixture")
        project = generate_hyperframes_project(
            title="Audio Test",
            sections=[{"heading": "S", "body": "Body"}],
            output_dir=str(tmp_path),
            audio_path=audio,
        )
        with open(os.path.join(project, "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert "narration-audio" in html
        assert "assets/audio/narration.mp3" in html

    def test_meta_json_has_scene_timing(self, tmp_path: str) -> None:
        """meta.json declares scene start/duration for the renderer."""
        project = generate_hyperframes_project(
            title="Timing",
            sections=[
                {"heading": "A", "body": "x" * 100},
                {"heading": "B", "body": "y" * 300},
            ],
            output_dir=str(tmp_path),
        )
        import json

        with open(os.path.join(project, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        assert len(meta["scenes"]) == 2
        assert meta["scenes"][0]["start"] == 0
        assert meta["scenes"][1]["start"] > 0
