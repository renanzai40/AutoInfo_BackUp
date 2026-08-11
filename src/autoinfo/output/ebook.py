"""B23: EPUB / MOBI / audiobook output generation.

Renders Markdown chapter content as an EPUB3 ebook (via ``ebooklib``),
converts EPUB to Kindle MOBI (via calibre's ``ebook-convert``), and builds
a chaptered MP3 audiobook (per-chapter TTS via :func:`autoinfo.output._render_audio`
plus ID3v2 CHAP/CTOC chapter markers via ``mutagen``).

All third-party imports are lazy so that importing this module has no side
effects; missing optional dependencies raise :class:`RuntimeError` with an
install hint.

MOBI note: the legacy MOBI6 format uses cp1252 and cannot encode CJK text.
``ebook-convert --mobi-file-type=both`` emits both MOBI6 and KF8 (AZW3);
Kindle readers use the KF8 stream, which does handle CJK.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from autoinfo.output import _render_audio

logger = logging.getLogger(__name__)


def _ebooklib_or_raise() -> None:
    """Import and return ebooklib, raising RuntimeError with an install hint if missing."""
    try:
        import ebooklib  # noqa: F401, PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "EPUB/MOBI output requires the 'ebooklib' package.\n"
            "Install it with: pip install 'autoinfo[ebook]'\n"
            f"Original error: {exc}"
        ) from exc


def _markdown_to_xhtml(body: str) -> str:
    """Convert a Markdown body to XML-well-formed XHTML.

    The default ``html5`` output leaves ``<img>`` / ``<br>`` unclosed, which
    fails strict EPUB readers; ``output_format="xhtml"`` emits self-closing
    tags that stay XML-valid for CJK and all other content.

    An empty (or whitespace-only) body yields a valid empty-paragraph
    fragment — ebooklib's EPUB writer crashes with ``lxml ParserError`` on
    an empty document, so a chapter must never render to zero bytes.
    """
    import markdown as md_lib  # noqa: PLC0415

    xhtml = str(
        md_lib.markdown(
            body or "",
            extensions=["fenced_code", "tables", "sane_lists"],
            output_format="xhtml",
        )
    )
    return xhtml if xhtml.strip() else "<p></p>"


def render_epub(
    title: str,
    author: str,
    lang: str,
    chapters: list[tuple[str, str]],
    cover_bytes: bytes | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Build an EPUB3 ebook from Markdown chapters.

    Parameters
    ----------
    title:
        Book title (also used as the EPUB ``DC:title`` metadata).
    author:
        Author name (EPUB ``DC:creator`` metadata).
    lang:
        RFC 5646 language code (e.g. ``"en"``, ``"zh"``).  Critical for
        CJK readers to pick a font.
    chapters:
        List of ``(heading, markdown_body)`` tuples; each becomes one
        EPUB chapter (``EpubHtml`` item) in spine and table of contents.
    cover_bytes:
        Optional PNG/JPEG cover image bytes.  When provided, a cover page
        is created and registered as the book cover.
    summary:
        Optional description stored as EPUB ``DC:description`` metadata.

    Returns
    -------
    dict
        ``{"format": "epub", "data_b64": ..., "chapters": n, "title": title}``
        where ``data_b64`` is base64-encoded EPUB3 bytes.

    Raises
    ------
    RuntimeError
        If ``ebooklib`` is not installed.
    ValueError
        If *chapters* is empty.
    """
    _ebooklib_or_raise()
    from ebooklib import epub  # noqa: PLC0415

    if not chapters:
        raise ValueError("Cannot build an EPUB with zero chapters")

    book = epub.EpubBook()
    book.set_identifier(f"autoinfo-{uuid.uuid4().hex}")
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)
    book.add_metadata("DC", "date", date.today().isoformat())
    if summary:
        book.add_metadata("DC", "description", summary)

    chapter_items: list[epub.EpubHtml] = []
    for idx, (heading, body) in enumerate(chapters):
        item = epub.EpubHtml(
            title=heading,
            file_name=f"chapter_{idx:03d}.xhtml",
            lang=lang,
        )
        item.content = _markdown_to_xhtml(body)
        book.add_item(item)
        chapter_items.append(item)

    if cover_bytes is not None:
        book.set_cover("cover.png", cover_bytes, create_page=True)

    # TOC = chapters; spine = nav + chapters; NCX + Nav for EPUB3 navigation.
    book.toc = chapter_items
    book.spine = ["nav", *chapter_items]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    tmp_dir = Path(tempfile.gettempdir()) / "autoinfo"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".epub", dir=str(tmp_dir))
    os.close(fd)
    try:
        epub.write_epub(tmp_path, book)
        data = Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "format": "epub",
        "data_b64": base64.b64encode(data).decode("ascii"),
        "chapters": len(chapters),
        "title": title,
    }


def render_mobi(epub_data_b64: str) -> dict[str, Any]:
    """Convert base64-encoded EPUB3 bytes to Kindle MOBI via calibre.

    Uses calibre's ``ebook-convert`` with ``--mobi-file-type=both`` so the
    output carries both legacy MOBI6 and KF8 (AZW3) streams; the KF8 stream
    is what Kindle readers use, and it supports CJK text (plain MOBI6 is
    cp1252-only and cannot).

    Parameters
    ----------
    epub_data_b64:
        Base64-encoded EPUB3 bytes, as returned by :func:`render_epub`.

    Returns
    -------
    dict
        ``{"format": "mobi", "data_b64": ..., "chapters": n}``.

    Raises
    ------
    RuntimeError
        If calibre's ``ebook-convert`` is not installed, or conversion fails.
    """
    _ebooklib_or_raise()
    converter = shutil.which("ebook-convert")
    if converter is None:
        raise RuntimeError(
            "Calibre's 'ebook-convert' is required for MOBI output but was "
            "not found on PATH.\n"
            "Install calibre (https://calibre-ebook.com/download) and ensure "
            "'ebook-convert' is available, then retry."
        )

    tmp_dir = Path(tempfile.gettempdir()) / "autoinfo"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    in_path = tmp_dir / f"input-{uuid.uuid4().hex}.epub"
    out_path = tmp_dir / f"output-{uuid.uuid4().hex}.mobi"
    try:
        in_path.write_bytes(base64.b64decode(epub_data_b64))
        subprocess.run(  # noqa: S603
            [
                converter,
                str(in_path),
                str(out_path),
                "--mobi-file-type=both",
            ],
            timeout=300,
            check=True,
            capture_output=True,
        )
        data = out_path.read_bytes()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("MOBI conversion timed out after 300 seconds") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Calibre ebook-convert failed (exit {exc.returncode}): {stderr[:2000]}"
        ) from exc
    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    # Re-read the EPUB to report the chapter count in the result dict.
    from ebooklib.epub import read_epub  # noqa: PLC0415

    chapter_count = 0
    try:
        book = read_epub(io.BytesIO(base64.b64decode(epub_data_b64)))
        chapter_count = len(book.spine) - 1  # spine = ["nav", *chapters]
    except Exception:
        logger.debug("Could not re-read EPUB for chapter count", exc_info=True)

    return {
        "format": "mobi",
        "data_b64": base64.b64encode(data).decode("ascii"),
        "chapters": chapter_count,
    }


def _build_chaptered_mp3(mp3_paths: list[Path]) -> bytes:
    """Concatenate chapter MP3s and tag them with ID3v2.3 CHAP/CTOC frames.

    Chapter start times are computed cumulatively from each file's actual
    duration (no artificial silence inserted).  The resulting single MP3 is
    the self-hosted chaptered-audiobook standard (Audiobookshelf/Overcast
    compatible).

    If mutagen is unavailable or tagging fails for any reason, falls back
    to a plain concatenation of the chapter MP3 bytes (still valid output,
    just without chapter markers).
    """
    audio_bytes = b"".join(p.read_bytes() for p in mp3_paths)
    try:
        from mutagen.id3 import CHAP, CTOC, ID3, TIT2  # noqa: PLC0415
        from mutagen.mp3 import MP3  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "mutagen is not installed — returning plain concatenated MP3. "
            "Install with: pip install 'autoinfo[ebook]'"
        )
        return audio_bytes

    try:
        # mutagen ships py.typed with incomplete annotations; route its API
        # through Any-typed aliases so strict mypy accepts the calls.
        mp3_loader: Any = MP3
        id3_ctor: Any = ID3
        chap_ctor: Any = CHAP
        ctoc_ctor: Any = CTOC
        tit2_ctor: Any = TIT2

        durations: list[float] = []
        for path in mp3_paths:
            audio = mp3_loader(str(path))
            info = audio.info
            durations.append(float(info.length) if info is not None else 0.0)
        # Start times accumulate from actual durations; chapters stay ordered
        # by start time because we build them cumulatively in list order.
        starts_ms: list[int] = []
        acc_ms = 0
        for duration in durations:
            starts_ms.append(acc_ms)
            acc_ms += int(round(duration * 1000))
        ends_ms = [
            start + int(round(duration * 1000))
            for start, duration in zip(starts_ms, durations)
        ]

        tag = id3_ctor()
        child_ids: list[str] = []
        for idx, (start, end) in enumerate(zip(starts_ms, ends_ms)):
            element_id = f"chp{idx:04d}"
            child_ids.append(element_id)
            tag.add(
                chap_ctor(
                    element_id=element_id,
                    start_time=start,
                    end_time=end,
                    start_offset=0,
                    end_offset=0,
                    sub_frames=[
                        tit2_ctor(encoding=3, text=f"Chapter {idx + 1}")
                    ],
                )
            )
        tag.add(
            ctoc_ctor(
                element_id="toc",
                flags=0,
                child_element_ids=child_ids,
                sub_frames=[tit2_ctor(encoding=3, text="Table of Contents")],
            )
        )
        buf = io.BytesIO()
        tag.save(buf, v2_version=3)
        return buf.getvalue() + audio_bytes
    except Exception:
        logger.warning(
            "Failed to tag chaptered MP3 — returning plain concatenated MP3.",
            exc_info=True,
        )
        return audio_bytes


def render_audiobook(
    chapters: list[tuple[str, str]],
    voice: str = "alloy",
    engine: str | None = None,
) -> dict[str, Any]:
    """Render a chaptered MP3 audiobook from Markdown chapters.

    Each ``(heading, body)`` chapter is converted to speech via
    :func:`autoinfo.output._render_audio` (which enforces a 4096-char
    cap per request — chapters are naturally bounded so this is fine) and
    saved as ``chapter_XXX.mp3``.  The result carries both:

    - ``data_b64`` — a single chaptered MP3 with ID3v2.3 CHAP/CTOC frames
      (start times computed from actual per-chapter durations)
    - ``zip_b64`` — a ZIP bundle of the individual chapter MP3s

    Parameters
    ----------
    chapters:
        List of ``(heading, markdown_body)`` tuples; one audio chapter each.
    voice:
        TTS voice passed through to :func:`autoinfo.output._render_audio`.
    engine:
        TTS engine passed through to :func:`autoinfo.output._render_audio`
        (``None`` resolves from config, default ``"openai"``).

    Returns
    -------
    dict
        ``{"format": "audiobook", "data_b64": ..., "zip_b64": ...,
        "chapter_count": n}``.

    Raises
    ------
    ValueError
        If *chapters* is empty.
    RuntimeError
        If TTS rendering fails for any chapter (propagated from
        :func:`autoinfo.output._render_audio`).
    """
    if not chapters:
        raise ValueError("Cannot build an audiobook with zero chapters")

    # Skip chapters whose body is empty / whitespace-only / markdown-only
    # (e.g. a digest section with no content).  Rendering empty text raises
    # ValueError("Cannot render empty text as audio") from _render_audio and
    # would abort the whole audiobook (2026-08-11 batch regression: 4/4
    # digest-audiobook cells failed this way).  A silent chapter skip keeps
    # the audiobook buildable; chapters with no body after stripping
    # markdown are dropped from the chapter list.
    from autoinfo.output import _strip_markdown  # noqa: PLC0415

    usable: list[tuple[str, str]] = []
    for heading, body in chapters:
        plain = _strip_markdown(body or "")
        if plain and plain.strip():
            usable.append((heading, body))
    if not usable:
        raise ValueError("Cannot build an audiobook with zero non-empty chapters")
    chapters = usable

    tmp_dir = (
        Path(tempfile.gettempdir())
        / "autoinfo"
        / f"audiobook-{uuid.uuid4().hex[:8]}"
    )
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        mp3_paths: list[Path] = []
        for idx, (heading, body) in enumerate(chapters):
            audio_bytes = _render_audio(body, voice=voice, engine=engine)
            chapter_path = tmp_dir / f"chapter_{idx:03d}.mp3"
            chapter_path.write_bytes(audio_bytes)
            mp3_paths.append(chapter_path)

        # ZIP bundle of the individual chapter MP3s.
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, path in enumerate(mp3_paths):
                zf.write(path, arcname=f"chapter_{idx:03d}.mp3")
        zip_b64 = base64.b64encode(zip_buf.getvalue()).decode("ascii")

        # Single chaptered MP3 (CHAP/CTOC tagged, concatenated fallback).
        tagged_bytes = _build_chaptered_mp3(mp3_paths)

        return {
            "format": "audiobook",
            "data_b64": base64.b64encode(tagged_bytes).decode("ascii"),
            "zip_b64": zip_b64,
            "chapter_count": len(chapters),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
