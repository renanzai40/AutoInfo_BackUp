"""Video output pipeline — HyperFrames (HTML + GSAP -> MP4) renderer.

Generates video content from structured report data using the HyperFrames
pipeline (ported from AutoMedia, 2026-08-13):

1. TTS audio narration (via existing ``_render_audio`` from output.py)
2. HyperFrames project scaffold (theme + scene planning + layout diversity)
3. ``bun x hyperframes render`` — headless Chrome + GSAP animation -> MP4

The old PIL+FFmpeg slideshow path is superseded; the pipeline now generates
a real HyperFrames project directory (package.json / meta.json /
hyperframes.json / index.html / compositions/*.html / assets/audio/).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Directory containing the ported AutoMedia assets (themes + templates).
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_assets")


@dataclass
class VideoConfig:
    """Configuration for HyperFrames video generation."""

    fps: int = 30
    resolution: tuple[int, int] = (1920, 1080)
    theme: str = "terminal-green"
    quality: str = "draft"  # draft | standard | high
    tts_speed: float = 1.0
    transition: str = "fade"  # kept for backward compat
    bg_color: str = ""  # kept for backward compat; theme overrides
    font_color: str = ""  # kept for backward compat; theme overrides
    font_size: int = 30  # kept for backward compat; scene templates own sizes
    scene_mode: str = "auto"  # auto | A | B | C | D (AutoMedia scene patterns)
    theme_mood: str = ""  # filter themes by mood (light/dark/tech/editorial/...)


# ---------------------------------------------------------------------------
# Theme library (ported from AutoMedia theme-palettes.json / od-themes.json)
# ---------------------------------------------------------------------------


def _load_themes() -> dict[str, Any]:
    """Load the merged theme library (36 palettes + 8 brand themes)."""
    themes: dict[str, Any] = {}
    for filename in ("theme_palettes.json", "od_themes.json"):
        path = os.path.join(_ASSETS_DIR, "themes", filename)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        themes.update(data.get("themes", {}))
    return themes


def _flatten_theme(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten a theme entry's ``variables`` dict into dotted keys.

    Themes in the ported library are heterogeneous — not every palette
    declares every CSS variable (e.g. 14/36 lack ``--font-display``).  Missing
    variables get safe defaults so any theme renders without template errors.
    """
    flat = {"dark": raw.get("dark", False), "mood": raw.get("mood", [])}
    for var_name, value in raw.get("variables", {}).items():
        key = var_name.lstrip("-").replace("-", "_")
        flat[key] = value
    # Defaults for variables that only some themes declare.
    flat.setdefault("font_display", "system-ui, sans-serif")
    flat.setdefault("surface_2", flat.get("surface", "#1a1a2e"))
    flat.setdefault("border", "rgba(128,128,128,0.2)")
    flat.setdefault("border_strong", "rgba(128,128,128,0.35)")
    flat.setdefault("radius", "12px")
    flat.setdefault("radius_lg", "16px")
    flat.setdefault("shadow", "0 4px 12px rgba(0,0,0,0.3)")
    flat.setdefault("grad", f"linear-gradient(135deg, {flat.get('accent', '#00ff88')}, {flat.get('bg', '#0a0a0a')})")
    flat.setdefault("good", flat.get("accent", "#00ff88"))
    flat.setdefault("warn", "#ffaa00")
    flat.setdefault("bad", "#ff6464")
    return flat


def select_theme(config: VideoConfig | None = None) -> dict[str, Any]:
    """Select a flattened theme dict from the ported library.

    Picks ``config.theme`` if it exists; otherwise filters by
    ``config.theme_mood`` (first match) and falls back to the default
    ``terminal-green`` (brand-safe dark tech theme).
    """
    themes = _load_themes()
    cfg = config or VideoConfig()

    if cfg.theme in themes:
        return _flatten_theme(themes[cfg.theme])

    if cfg.theme_mood:
        for name, t in themes.items():
            if cfg.theme_mood in t.get("mood", []):
                logger.info("theme %r chosen by mood %r", name, cfg.theme_mood)
                return _flatten_theme(t)

    if "terminal-green" in themes:
        logger.warning("theme %r not found — falling back to terminal-green", cfg.theme)
        return _flatten_theme(themes["terminal-green"])

    # Last resort: first theme in the library.
    name, t = next(iter(themes.items()))
    logger.warning("no themes loaded — using first theme %r", name)
    return _flatten_theme(t)


# ---------------------------------------------------------------------------
# Scene planning — AutoMedia scene patterns (A/B/C/D) + layout diversity
# ---------------------------------------------------------------------------

# Visual layout patterns (AutoMedia visual-layouts.md, 6 types).  Each scene
# picks a layout; adjacent scenes must differ (5-scene video uses >= 4 layouts).
LAYOUTS: dict[str, dict[str, Any]] = {
    "centered-hero": {
        "label": "Centered Hero",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 380px; left: 10%; width: 80%; text-align: center; color: var(--accent); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="1.2" data-duration="{{ duration }}" data-track-index="1"
         style="top: 520px; left: 16%; width: 68%; text-align: center; color: var(--text-2);">
      {{ body | e }}
    </div>
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -40, duration: 0.9, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body", { opacity: 0, y: 24, duration: 0.7, ease: "power3.out" }, 0.9);
""",
    },
    "split-screen": {
        "label": "Split Screen",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 300px; left: 10%; width: 80%; color: var(--text-1); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="0.8" data-duration="{{ duration }}" data-track-index="1"
         style="top: 400px; left: 10%; width: 36%; padding: 40px; background: var(--surface); border-radius: var(--radius-lg); border: 2px solid var(--accent); color: var(--text-1);">
      {{ body_left | default(body, true) | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="1.2" data-duration="{{ duration }}" data-track-index="2"
         style="top: 400px; right: 10%; width: 36%; padding: 40px; background: var(--surface-2); border-radius: var(--radius-lg); border: 2px solid var(--border); color: var(--text-2);">
      {{ body_right | default(body, true) | e }}
    </div>
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -30, duration: 0.8, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body", { opacity: 0, x: -50, duration: 0.8, ease: "power3.out" }, 0.7);
    tl.from("#scene .scene-body:nth-of-type(3)", { opacity: 0, x: 50, duration: 0.8, ease: "power3.out" }, 1.0);
""",
    },
    "card-grid": {
        "label": "Card Grid",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 300px; left: 10%; width: 80%; color: var(--text-1); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="0.8" data-duration="{{ duration }}" data-track-index="1"
         style="top: 400px; left: 10%; width: 80%; color: var(--text-2);">
      {{ body | e }}
    </div>
    {% for card in cards %}<div class="clip scene-body" id="scene-body" data-start="{{ 1.0 + loop.index0 * 0.4 }}" data-duration="{{ duration }}" data-track-index="{{ 2 + loop.index }}"
         style="top: {{ 500 + (loop.index0 % 2) * 160 }}px; left: {{ 10 + (loop.index0 % 3) * 28 }}%; width: 24%; padding: 24px; background: var(--surface); border-radius: var(--radius-lg); color: var(--text-1);">
      {{ card | e }}
    </div>
    {% endfor %}
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -30, duration: 0.8, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body", { opacity: 0, y: 20, duration: 0.6, ease: "power3.out" }, 0.7);
    tl.from("#scene .clip[data-track-index] .scene-body", {}, 0);
    tl.from("#scene div.clip[data-track-index]:not([data-track-index='0']):not([data-track-index='1'])", { opacity: 0, scale: 0.9, stagger: 0.25, duration: 0.6, ease: "power2.out" }, 1.0);
""",
    },
    "data-dashboard": {
        "label": "Data Dashboard",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 300px; left: 10%; width: 80%; color: var(--accent); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="0.6" data-duration="{{ duration }}" data-track-index="1"
         style="top: 400px; left: 10%; width: 80%; color: var(--text-2); font-size: 44px; font-weight: 600;">
      {{ body | e }}
    </div>
    {% for stat in stats %}<div class="clip scene-body" id="scene-body" data-start="{{ 0.8 + loop.index0 * 0.5 }}" data-duration="{{ duration }}" data-track-index="{{ 2 + loop.index }}"
         style="top: {{ 560 + (loop.index0 // 4) * 140 }}px; left: {{ 10 + (loop.index0 % 4) * 20 }}%; width: 16%; text-align: center;">
      <div style="font-size: 48px; font-weight: 700; color: var(--accent);">{{ stat.value | e }}</div>
      <div style="font-size: 24px; color: var(--text-3); margin-top: 8px;">{{ stat.label | e }}</div>
    </div>
    {% endfor %}
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -30, duration: 0.8, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body:nth-of-type(2)", { opacity: 0, y: 20, duration: 0.6, ease: "power3.out" }, 0.6);
    tl.from("#scene div.clip[data-track-index]:not([data-track-index='0']):not([data-track-index='1'])", { opacity: 0, scale: 0.8, stagger: 0.2, duration: 0.6, ease: "back.out(1.4)" }, 0.9);
""",
    },
    "timeline-flow": {
        "label": "Timeline / Flow",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 300px; left: 10%; width: 80%; color: var(--text-1); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="0.6" data-duration="{{ duration }}" data-track-index="1"
         style="top: 400px; left: 10%; width: 80%; color: var(--text-2);">
      {{ body | e }}
    </div>
    {% for step in steps %}<div class="clip scene-body" id="scene-body" data-start="{{ 0.8 + loop.index0 * 0.6 }}" data-duration="{{ duration }}" data-track-index="{{ 2 + loop.index }}"
         style="top: {{ 500 + loop.index0 * 90 }}px; left: 16%; width: 68%; padding-left: 60px; position: absolute; color: var(--text-1);">
      <span style="position: absolute; left: 0; width: 40px; height: 40px; border-radius: 50%; background: var(--accent); color: var(--bg); text-align: center; line-height: 40px; font-weight: 700;">{{ loop.index }}</span>
      {{ step | e }}
    </div>
    {% endfor %}
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -30, duration: 0.8, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body:nth-of-type(2)", { opacity: 0, y: 20, duration: 0.6, ease: "power3.out" }, 0.6);
    tl.from("#scene div.clip[data-track-index]:not([data-track-index='0']):not([data-track-index='1'])", { opacity: 0, x: -60, stagger: 0.35, duration: 0.7, ease: "power3.out" }, 0.9);
""",
    },
    "fullscreen-narrative": {
        "label": "Full-screen Narrative",
        "html": """
    <div class="clip scene-title" id="scene-title" data-start="0" data-duration="{{ duration }}" data-track-index="0"
         style="top: 380px; left: 10%; width: 80%; font-size: 64px; color: var(--accent); font-family: var(--font-display);">
      {{ heading | e }}
    </div>
    <div class="clip scene-body" id="scene-body" data-start="1.0" data-duration="{{ duration }}" data-track-index="1"
         style="top: 520px; left: 14%; width: 72%; color: var(--text-1); font-size: 36px;">
      {{ body | e }}
    </div>
""",
        "animations": """
    tl.from("#scene .scene-title", { opacity: 0, y: -50, duration: 1.0, ease: "power3.out" }, 0);
    tl.from("#scene .scene-body", { opacity: 0, y: 30, duration: 0.8, ease: "power3.out" }, 0.8);
""",
    },
}

# Ordered layout rotation — guarantees adjacent-scene diversity (>=4 of 6
# layouts for a 5-scene video, matching AutoMedia Gate VQ).
_LAYOUT_ORDER = [
    "centered-hero",
    "split-screen",
    "card-grid",
    "data-dashboard",
    "timeline-flow",
    "fullscreen-narrative",
]


def _pick_layouts(n_scenes: int) -> list[str]:
    """Assign a layout per scene with mandatory adjacent diversity."""
    if n_scenes <= 0:
        return []
    if n_scenes == 1:
        return ["centered-hero"]
    if n_scenes == 2:
        return ["centered-hero", "split-screen"]
    # Rotate through the full library; >= 4 distinct layouts for n >= 5.
    layouts = [_LAYOUT_ORDER[i % len(_LAYOUT_ORDER)] for i in range(n_scenes)]
    return layouts


# ---------------------------------------------------------------------------
# TTS narration (reuses the existing engine from output.py)
# ---------------------------------------------------------------------------


def generate_audio_narration(
    title: str,
    sections: list[dict[str, str]],
    output_dir: str,
    voice: str = "default",
) -> str:
    """Generate TTS audio narration for content.

    Args:
        title: Report title
        sections: List of dicts with 'heading' and 'body' keys
        output_dir: Directory to write audio file
        voice: TTS voice name

    Returns:
        Path to audio file

    Raises:
        RuntimeError: If TTS generation fails entirely
    """
    # Build narration text from sections
    text_parts = [f"Title: {title}"]
    for section in sections:
        heading = section.get("heading", "")
        body = section.get("body", "")
        if heading:
            text_parts.append(heading)
        if body:
            text_parts.append(body)

    narration_text = ". ".join(text_parts)

    # Use existing TTS engine from output.py
    from autoinfo.output import _render_audio

    audio_bytes = _render_audio(narration_text, voice=voice)

    os.makedirs(output_dir, exist_ok=True)
    audio_path = os.path.join(output_dir, "narration.mp3")
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    if not os.path.getsize(audio_path) > 100:
        raise RuntimeError(f"TTS audio too small: {audio_path}")

    logger.info(
        "TTS audio generated: %s (%d bytes)",
        audio_path,
        os.path.getsize(audio_path),
    )
    return audio_path


# ---------------------------------------------------------------------------
# HyperFrames project scaffold
# ---------------------------------------------------------------------------


def _probe_audio_duration(audio_path: str) -> float:
    """Probe audio duration in seconds via ffprobe (0.0 on failure)."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        info = json.loads(out.stdout or "{}")
        return float(info.get("format", {}).get("duration", 0.0))
    except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _split_narration_into_scenes(
    sections: list[dict[str, str]],
    total_duration: float,
) -> list[dict[str, Any]]:
    """Assign per-scene start/duration from TTS length by character ratio.

    Mirrors AutoMedia's scene-frame-boundary math, including the float
    precision safety margin (-0.01s per scene) that prevents HyperFrames
    ``overlapping_clips_same_track`` lint failures.
    """
    if not sections:
        return []
    char_lens = [max(len(s.get("heading", "")) + len(s.get("body", "")), 1) for s in sections]
    total_chars = sum(char_lens)
    scenes: list[dict[str, Any]] = []
    cumsum = 0.0
    for i, (section, clen) in enumerate(zip(sections, char_lens)):
        start = cumsum / total_chars * total_duration
        end = (cumsum + clen) / total_chars * total_duration
        duration = max(1.5, end - start - 0.01)  # float-safety margin
        scenes.append(
            {
                "name": section.get("heading", f"Section {i + 1}")[:40],
                "start": round(start, 3),
                "duration": round(duration, 3),
                "heading": section.get("heading", ""),
                "body": section.get("body", ""),
            }
        )
        cumsum += clen
    return scenes


def _render_jinja(template_name: str, **ctx: Any) -> str:
    """Render a template from the ported assets dir."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(os.path.join(_ASSETS_DIR, "templates")),
        undefined=StrictUndefined,
        autoescape=False,
    )
    return env.get_template(template_name).render(**ctx)


def _write_scene_composition(
    compositions_dir: str,
    index: int,
    scene: dict[str, Any],
    layout_name: str,
    theme: dict[str, Any],
) -> None:
    """Write one scene composition HTML (layout + GSAP timeline)."""
    layout = LAYOUTS[layout_name]
    html = _render_jinja(
        "scene.html.j2",
        theme=theme,
        loop={"index": index},
        duration=scene["duration"],
        layout={
            "name": layout["label"],
            "html": layout["html"],
            "animations": layout["animations"],
        },
        heading=scene["heading"],
        body=scene["body"],
        body_left=scene.get("heading"),
        body_right=scene.get("body"),
        cards=scene.get("cards", []),
        stats=scene.get("stats", []),
        steps=scene.get("steps", []),
    )
    path = os.path.join(compositions_dir, f"{index:02d}-scene.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def generate_hyperframes_project(
    title: str,
    sections: list[dict[str, str]],
    output_dir: str,
    audio_path: str | None = None,
    config: VideoConfig | None = None,
) -> str:
    """Generate a complete HyperFrames project directory.

    Returns the project directory path.  The caller then runs
    :func:`render_hyperframes` to produce the MP4.
    """
    cfg = config or VideoConfig()
    theme = select_theme(cfg)

    os.makedirs(output_dir, exist_ok=True)

    # --- Copy project skeleton files ---
    for name in ("package.json", "hyperframes.json"):
        src = os.path.join(_ASSETS_DIR, "templates", name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(output_dir, name))

    # --- Audio ---
    has_audio = bool(audio_path and os.path.isfile(audio_path))
    if has_audio:
        audio_dir = os.path.join(output_dir, "assets", "audio")
        os.makedirs(audio_dir, exist_ok=True)
        assert audio_path is not None, "audio_path required when narration audio exists"
        shutil.copy(audio_path, os.path.join(audio_dir, "narration.mp3"))
        total_duration = _probe_audio_duration(audio_path)
    else:
        total_duration = float(len(sections) * 8)  # fallback 8s per scene

    if total_duration <= 0:
        total_duration = float(len(sections) * 8)

    # --- Scene planning ---
    scenes = _split_narration_into_scenes(sections, total_duration)
    layout_names = _pick_layouts(len(scenes))

    # --- meta.json (scene start/duration) ---
    meta = _render_jinja(
        "meta.json.j2",
        title=title,
        target_duration=int(total_duration),
        scenes=[{"name": s["name"], "start": s["start"], "duration": s["duration"]} for s in scenes],
    )
    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        f.write(meta)

    # --- compositions/ ---
    compositions_dir = os.path.join(output_dir, "compositions")
    os.makedirs(compositions_dir, exist_ok=True)
    for i, scene in enumerate(scenes, start=1):
        _write_scene_composition(compositions_dir, i, scene, layout_names[i - 1], theme)

    # --- index.html (root composition + audio track + scene hosts) ---
    index_html = _render_jinja(
        "index.html.j2",
        theme=theme,
        title=title,
        total_duration=total_duration,
        has_audio=has_audio,
        scenes=[{"start": s["start"], "duration": s["duration"]} for s in scenes],
    )
    with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    logger.info(
        "HyperFrames project generated: %s (%d scenes, %.1fs audio, theme=%s)",
        output_dir,
        len(scenes),
        total_duration,
        cfg.theme,
    )
    return output_dir


# ---------------------------------------------------------------------------
# HyperFrames render (bun x hyperframes)
# ---------------------------------------------------------------------------


def _find_binary(name: str) -> str:
    """Locate an executable on PATH (bun, ffmpeg, ffprobe)."""
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(
            f"'{name}' not found on PATH. "
            f"HyperFrames rendering requires: bun (https://bun.sh), "
            f"and ffmpeg/ffprobe for audio probing."
        )
    return path


def render_hyperframes(
    project_dir: str,
    output_path: str,
    quality: str = "draft",
    timeout: float = 600,
) -> str:
    """Render a HyperFrames project to MP4 via ``bun x hyperframes render``.

    Runs ``lint`` first (fail fast on composition errors), then the render
    at the requested quality.  Raises RuntimeError on lint/render failure
    or missing output.
    """
    bun = _find_binary("bun")

    # --- lint gate (G3 equivalent) ---
    lint = subprocess.run(
        [bun, "x", "hyperframes", "lint"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if lint.returncode != 0:
        raise RuntimeError(
            f"HyperFrames lint failed:\n{lint.stdout}\n{lint.stderr}"
        )
    logger.info("HyperFrames lint passed: %s", project_dir)

    # --- render ---
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    render = subprocess.run(
        [
            bun, "x", "hyperframes", "render",
            "--output", output_path,
            "--quality", quality,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if render.returncode != 0:
        raise RuntimeError(
            f"HyperFrames render failed (quality={quality}):\n"
            f"{render.stdout}\n{render.stderr}"
        )

    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 100:
        raise RuntimeError(
            f"Video output is missing or too small: {output_path}"
        )

    logger.info(
        "Video rendered via HyperFrames: %s (%d bytes, quality=%s)",
        output_path,
        os.path.getsize(output_path),
        quality,
    )
    return output_path


# ---------------------------------------------------------------------------
# Public entry — full pipeline
# ---------------------------------------------------------------------------


def generate_report_video(
    title: str,
    sections: list[dict[str, str]],
    output_path: str | None = None,
    config: VideoConfig | None = None,
    voice: str = "default",
) -> str:
    """Generate a video report: TTS -> HyperFrames project -> MP4.

    Args:
        title: Report title
        sections: List of dicts with 'heading' and 'body' keys
        output_path: Optional output MP4 path (default: temp dir)
        config: Optional VideoConfig
        voice: TTS voice name

    Returns:
        Absolute path to the rendered MP4.

    Raises:
        FileNotFoundError: bun / ffmpeg missing
        RuntimeError: TTS / lint / render failure
    """
    cfg = config or VideoConfig()

    work_dir = tempfile.mkdtemp(prefix="autoinfo_video_")
    audio_path: str | None = None
    try:
        # 1. TTS narration
        audio_dir = os.path.join(work_dir, "audio")
        audio_path = generate_audio_narration(title, sections, audio_dir, voice=voice)

        # 2. HyperFrames project
        project_dir = os.path.join(work_dir, "project")
        generate_hyperframes_project(
            title=title,
            sections=sections,
            output_dir=project_dir,
            audio_path=audio_path,
            config=cfg,
        )

        # 3. Render
        if output_path is None:
            output_path = os.path.join(
                work_dir, f"autoinfo_video_{int(time.time())}.mp4"
            )
        render_hyperframes(project_dir, output_path, quality=cfg.quality)

        return os.path.abspath(output_path)
    except Exception:
        # Preserve work_dir on failure for post-mortem inspection.
        logger.error("Video generation failed; work dir kept at %s", work_dir, exc_info=True)
        raise
    else:
        # Clean up the temp project on success — only the MP4 matters.
        shutil.rmtree(work_dir, ignore_errors=True)
