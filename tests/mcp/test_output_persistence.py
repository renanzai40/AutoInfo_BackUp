"""E2 (issues #131-134): MCP ``generate_*`` handlers optionally persist
PROCESSED artifacts (digest/report/tutorial/presentation) to disk under
``outputs/``.

The optional ``persist`` parameter (default ``False``) added to the five
``generate_*`` MCP handlers:

- ``generate_digest``
- ``generate_report``
- ``generate_cross_domain_report``
- ``generate_tutorial``
- ``generate_presentation``

When ``persist=True`` the handler writes the returned artifact to
``outputs/<domain>/<product>-<format>-<timestamp>.<ext>`` and adds a
``persisted_path`` key to the success envelope.  When ``persist=False``
(and when omitted) the behavior is byte-identical to the pre-change
handlers: no file writes, no extra envelope keys.

The outputs root is the module-level ``autoinfo.mcp.server.OUTPUTS_DIR``
constant (default ``Path("outputs")``); tests redirect it to ``tmp_path``
via monkeypatch so nothing is ever written into the repo's real
``outputs/`` directory.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp.server import (
    _handle_generate_cross_domain_report,
    _handle_generate_digest,
    _handle_generate_presentation,
    _handle_generate_report,
    _handle_generate_tutorial,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def outputs_dir(tmp_path, monkeypatch):
    """Redirect the module-level outputs root to tmp_path."""
    monkeypatch.setattr(mcp_server, "OUTPUTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def kb_store_with_entries():
    """Stub KBStore so the digest/report handlers reach generate_*.

    Same seam as tests/test_digest.py::TestMcpHandler — the handlers
    resolve KBStore via a function-local import, so patch
    ``autoinfo.kb.KBStore`` to return a non-empty preview.
    """
    mock_store = MagicMock()
    mock_store.list_entries.return_value = [
        {
            "id": "e1",
            "title": "Entry 1",
            "domain": "medical-research",
            "content": "Body",
        }
    ]
    with patch("autoinfo.kb.KBStore", return_value=mock_store):
        yield


def _unique_output_file(outputs_root: Path, domain: str, pattern: str) -> Path:
    """Assert exactly one matching file exists under outputs_root/domain."""
    files = sorted((outputs_root / domain).glob(pattern))
    assert len(files) == 1, f"expected exactly one {pattern!r} file, got {files}"
    return files[0]


# ---------------------------------------------------------------------------
# Test 1 — digest + format json + persist=True
# ---------------------------------------------------------------------------


class TestDigestPersist:
    @patch("autoinfo.mcp.server.logger")
    def test_digest_json_persist_writes_file(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """persist=True on generate_digest (json) writes a parseable JSON file."""
        payload = {"digest_type": "digest", "domain": "test", "entry_count": 0}
        with patch(
            "autoinfo.output.generate_digest", return_value=json.dumps(payload)
        ):
            result = _handle_generate_digest(
                domain="medical-research",
                period="weekly",
                format="json",
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(outputs_dir, "medical-research", "digest-json-*.json")
        assert result["persisted_path"].endswith(f"medical-research/{file.name}")
        written = json.loads(file.read_text(encoding="utf-8"))
        assert written == payload

    @patch("autoinfo.mcp.server.logger")
    def test_digest_markdown_persist_writes_md(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """persist=True with format=markdown writes a .md file with the text."""
        content = "# Weekly Digest\n\nSome **content** here"
        with patch("autoinfo.output.generate_digest", return_value=content):
            result = _handle_generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                persist=True,
            )

        assert result["success"] is True
        assert result["content"] == content
        file = _unique_output_file(
            outputs_dir, "medical-research", "digest-markdown-*.md"
        )
        assert file.read_text(encoding="utf-8") == content

    @patch("autoinfo.mcp.server.logger")
    def test_digest_audio_persist_writes_mp3(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """persist=True with format=audio base64-decodes content into an .mp3."""
        audio_bytes = b"\x00\x01\x02\x03\xff\xfeID3FAKEMP3"
        payload = base64.b64encode(audio_bytes).decode("ascii")
        with patch("autoinfo.output.generate_digest", return_value=payload):
            result = _handle_generate_digest(
                domain="medical-research",
                period="weekly",
                format="audio",
                persist=True,
            )

        assert result["success"] is True
        assert result["encoding"] == "base64"
        file = _unique_output_file(outputs_dir, "medical-research", "digest-audio-*.mp3")
        assert file.read_bytes() == audio_bytes

    @patch("autoinfo.mcp.server.logger")
    def test_digest_persist_false_and_omitted_write_nothing(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """persist=False (and omitted) keeps the exact envelope, writes nothing."""
        content = "# Weekly Digest\n\ncontent"
        with patch("autoinfo.output.generate_digest", return_value=content):
            explicit = _handle_generate_digest(
                domain="medical-research",
                period="weekly",
                format="markdown",
                persist=False,
            )
            omitted = _handle_generate_digest(
                domain="medical-research", period="weekly", format="markdown"
            )

        assert "persisted_path" not in explicit
        assert "persisted_path" not in omitted
        assert explicit == omitted
        assert explicit["success"] is True
        assert explicit["content"] == content
        assert list(outputs_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Test 5 — persist wiring across the remaining four generate_* handlers
# ---------------------------------------------------------------------------


class TestAllHandlersPersist:
    @patch("autoinfo.mcp.server.logger")
    def test_report_persist_writes_md(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        content = "# Report\n\nbody"
        with patch("autoinfo.output.generate_report", return_value=content):
            result = _handle_generate_report(
                domain="medical-research", format="markdown", persist=True
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(outputs_dir, "medical-research", "report-markdown-*.md")
        assert file.read_text(encoding="utf-8") == content

    def test_cross_domain_report_persist_writes_md(self, outputs_dir) -> None:
        config = SimpleNamespace(
            domains=[
                SimpleNamespace(name="medical-research"),
                SimpleNamespace(name="ai-commercial"),
            ]
        )
        content = "# Cross Domain\n\nbody"
        with (
            patch("autoinfo.mcp.server._load_config", return_value=config),
            patch("autoinfo.output.generate_report", return_value=content),
        ):
            result = _handle_generate_cross_domain_report(
                domains=["medical-research", "ai-commercial"],
                format="markdown",
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "report-markdown-*.md"
        )
        assert file.read_text(encoding="utf-8") == content

    def test_tutorial_persist_writes_md(self, outputs_dir) -> None:
        content = "# Tutorial\n\nContent here"
        with patch("autoinfo.output.generate_tutorial", return_value=content):
            result = _handle_generate_tutorial(
                domain="medical-research", topic="IVF", format="markdown", persist=True
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "tutorial-markdown-*.md"
        )
        assert file.read_text(encoding="utf-8") == content

    def test_presentation_persist_writes_md(self, outputs_dir) -> None:
        content = "# Slide 1\n\nContent"
        with patch("autoinfo.output.generate_presentation", return_value=content):
            result = _handle_generate_presentation(
                domain="medical-research",
                topic="IVF breakthroughs",
                slides=10,
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "presentation-markdown-*.md"
        )
        assert file.read_text(encoding="utf-8") == content

    def test_persist_false_leaves_outputs_dir_empty_for_all_handlers(
        self, outputs_dir, kb_store_with_entries
    ) -> None:
        """All five handlers with persist=False/omitted write nothing."""
        with (
            patch("autoinfo.output.generate_digest", return_value="# D"),
            patch("autoinfo.output.generate_report", return_value="# R"),
            patch("autoinfo.output.generate_tutorial", return_value="# T"),
            patch("autoinfo.output.generate_presentation", return_value="# P"),
        ):
            _handle_generate_digest(domain="d1", format="markdown")
            _handle_generate_report(domain="d1", format="markdown")
            _handle_generate_tutorial(domain="d1", format="markdown")
            _handle_generate_presentation(domain="d1", topic="t", format="markdown")
        assert list(outputs_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Test 6 — report_type='column' persists under the column product name (#229)
# ---------------------------------------------------------------------------
# regression: _handle_generate_report always persisted with product='report',
# so report_type='column' artifacts were saved as report-markdown-* and the
# coverage_matrix filename parser never counted them for the column:markdown
# cell. column products must persist as column-<format>-*. The video branch
# (added after #229) must follow the same mapping.


class TestReportColumnPersistNaming:
    @patch("autoinfo.mcp.server.logger")
    def test_column_report_persist_writes_column_markdown(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """report_type='column' + format=markdown persists as column-markdown-*."""
        content = "# Column\n\nbody"
        with patch("autoinfo.output.generate_report", return_value=content):
            result = _handle_generate_report(
                domain="medical-research",
                format="markdown",
                report_type="column",
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "column-markdown-*.md"
        )
        assert file.read_text(encoding="utf-8") == content

    @patch("autoinfo.mcp.server.logger")
    def test_column_video_persist_writes_column_video(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """report_type='column' + format=video persists as column-video-* (#229 follow-up)."""
        video_b64 = base64.b64encode(b"fake-video-bytes").decode()
        with patch("autoinfo.output.generate_report", return_value=video_b64):
            result = _handle_generate_report(
                domain="medical-research",
                format="video",
                report_type="column",
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "column-video-*.mp4"
        )
        assert file.read_bytes() == base64.b64decode(video_b64)

    @patch("autoinfo.mcp.server.logger")
    def test_standard_video_persist_still_writes_report_video(
        self, mock_logger: MagicMock, outputs_dir, kb_store_with_entries
    ) -> None:
        """Default report_type keeps the report-* product name for video (no regression)."""
        video_b64 = base64.b64encode(b"fake-video-bytes").decode()
        with patch("autoinfo.output.generate_report", return_value=video_b64):
            result = _handle_generate_report(
                domain="medical-research",
                format="video",
                persist=True,
            )

        assert result["success"] is True
        assert "persisted_path" in result
        file = _unique_output_file(
            outputs_dir, "medical-research", "report-video-*.mp4"
        )
        assert file.read_bytes() == base64.b64decode(video_b64)
