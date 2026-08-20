"""B-class fixes batch (plan T11 / Wave 6) — one test per sub-fix.

Sub-fixes covered:
- B-02: portal reads/writes the ``delivery_preferences`` model field
  (``cli/portal.py`` + ``api/routes.py`` used the stale ``delivery_prefs``
  attribute — an ``AttributeError`` at runtime) and tolerates missing keys.
- B-04: ``format="agent"`` tutorial generation with no KB entries returns
  an explicit structured error instead of silently falling back to
  Markdown.
- B-05: ``cli/output.py export`` tolerates result dicts with missing keys
  (``.get`` with sensible defaults instead of bare indexing).
- B-07: ``_export_epub`` / ``_export_mobi`` derive ``lang`` from the
  entries (``language`` field or langdetect), defaulting to ``"en"``.
- B-08: validation ``_run_cli_step`` spawns the CLI subprocess in its own
  session/process group (``start_new_session=True``) and kills the whole
  group on timeout — no orphaned grandchildren.
- query_collected: ``KBStore()`` default ``base_path`` anchors to the
  project root (first ancestor with ``.autoinfo/config.yaml``) instead of
  being purely cwd-dependent.
"""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# B-02 — portal field rename: delivery_prefs → delivery_preferences
# ---------------------------------------------------------------------------


class TestB02PortalPreferenceRename:
    """CLI portal + REST portal must use the model field ``delivery_preferences``."""

    def test_cli_portal_preferences_roundtrip_uses_delivery_preferences(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """show/update roundtrip works without AttributeError and persists prefs."""
        monkeypatch.setattr(
            "autoinfo.user_store._get_db_path", lambda: tmp_path / "users.db"
        )
        from typer.testing import CliRunner

        from autoinfo.cli import portal as portal_cli
        from autoinfo.user_store import create_profile, get_profile

        create_profile(
            user_id="b11-user",
            name="B11 Tester",
            delivery_prefs={"digest": True},
        )

        runner = CliRunner()
        # update path must not raise (it echoed profile.delivery_prefs before)
        result = runner.invoke(
            portal_cli.app,
            [
                "preferences",
                "update",
                "--user-id",
                "b11-user",
                "--delivery-prefs",
                '{"digest": false, "channel": "telegram"}',
            ],
        )
        assert result.exit_code == 0, result.exception

        profile = get_profile("b11-user")
        assert profile is not None
        assert profile.delivery_preferences == {
            "digest": False,
            "channel": "telegram",
        }

        # show path must not raise (it read profile.delivery_prefs before)
        result = runner.invoke(
            portal_cli.app, ["preferences", "show", "--user-id", "b11-user"]
        )
        assert result.exit_code == 0, result.exception
        assert "digest: False" in result.output

    def test_api_portal_preferences_roundtrip(
        self, tmp_path: Path
    ) -> None:
        """GET/PUT /api/v1/portal/preferences roundtrip on delivery_preferences."""
        from autoinfo.api.server import app
        from autoinfo.models import UserProfile
        from autoinfo.user_store import get_profile, update_profile  # noqa: F401 — patch target

        profile = UserProfile(
            user_id="b11-api",
            name="B11 API",
            email="b11@example.com",
            delivery_preferences={"format": "html"},
        )

        def _update(user_id: str, **kwargs: Any) -> UserProfile:
            nonlocal profile
            profile = UserProfile(
                user_id=user_id,
                name=profile.name,
                email=kwargs.get("email", profile.email),
                delivery_preferences=kwargs.get(
                    "delivery_prefs", profile.delivery_preferences
                ),
            )
            return profile

        with (
            patch("autoinfo.user_store.get_profile", side_effect=lambda uid: profile),
            patch("autoinfo.user_store.update_profile", side_effect=_update),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/portal/preferences", params={"user_id": "b11-api"}
                )
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert "delivery_preferences" in data
                assert data["delivery_preferences"] == {"format": "html"}

                resp2 = client.put(
                    "/api/v1/portal/preferences",
                    params={"user_id": "b11-api"},
                    json={"delivery_preferences": {"format": "json"}},
                )
                assert resp2.status_code == 200
                data2 = resp2.json()["data"]
                assert "delivery_preferences" in data2
                assert data2["delivery_preferences"] == {"format": "json"}

                # read-back roundtrip
                resp3 = client.get(
                    "/api/v1/portal/preferences", params={"user_id": "b11-api"}
                )
                assert resp3.json()["data"]["delivery_preferences"] == {
                    "format": "json"
                }


# ---------------------------------------------------------------------------
# B-04 — agent-format empty guard (generate_tutorial)
# ---------------------------------------------------------------------------


class TestB04TutorialAgentEmptyGuard:
    """``format="agent"`` with no entries → explicit error, never silent Markdown."""

    def test_generate_tutorial_agent_empty_returns_explicit_error(self) -> None:
        from autoinfo.output import generate_tutorial

        with patch("autoinfo.output.KBStore") as mock_kb_cls:
            mock_kb_cls.return_value.list_entries.return_value = []
            result = generate_tutorial(domain="medical-research", format="agent")

        # Must be JSON (agent-native), not a silent Markdown fallback.
        data = json.loads(str(result))
        assert data["@type"] == "KnowledgeTutorial"
        assert data["error"]["code"] == "EMPTY_CONTENT"
        assert "No curated items are available" in data["error"]["message"]

    def test_generate_tutorial_agent_nonempty_renders_normally(self) -> None:
        from autoinfo.output import generate_tutorial

        entries = [
            {
                "entry_id": "e1",
                "title": "Quantum computing in medicine",
                "source_url": "https://example.com/q",
                "source_platform": "web",
                "summary": "Qubits accelerate molecular simulation.",
            }
        ]
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch(
                "autoinfo.output._call_llm_for_tutorial",
                return_value={
                    "title": "Quantum Tutorial",
                    "duration": "45 minutes",
                    "prerequisites": "None",
                    "objectives": ["Understand qubits"],
                    "content": [
                        {
                            "heading": "Intro",
                            "body": "Body text",
                            "code_example": None,
                            "code_language": None,
                            "key_takeaway": "Qubits",
                        }
                    ],
                    "exercises": [],
                    "summary": "A tutorial.",
                    "further_reading": [],
                },
            ),
        ):
            mock_kb_cls.return_value.list_entries.return_value = entries
            result = generate_tutorial(domain="medical-research", format="agent")

        data = json.loads(str(result))
        assert data["@type"] == "KnowledgeTutorial"
        assert data["title"] == "Quantum Tutorial"
        assert "error" not in data


# ---------------------------------------------------------------------------
# B-05 — cli/output.py export: .get guard against missing keys
# ---------------------------------------------------------------------------


class TestB05CliExportMissingKeys:
    """``autoinfo output export`` must not KeyError on sparse result dicts."""

    def test_cli_export_missing_result_keys_uses_defaults(self) -> None:
        from typer.testing import CliRunner

        from autoinfo.cli.output import app as output_app

        runner = CliRunner()
        with patch("autoinfo.cli.output.export_kb", return_value={}):
            result = runner.invoke(
                output_app,
                ["export", "--domain", "medical-research", "--format", "json"],
            )

        assert result.exit_code == 0, result.exception
        assert "Exported 0 entries" in result.output
        assert "unknown" in result.output

    def test_cli_export_partial_result_uses_defaults_for_path(self) -> None:
        from typer.testing import CliRunner

        from autoinfo.cli.output import app as output_app

        runner = CliRunner()
        with patch(
            "autoinfo.cli.output.export_kb", return_value={"entries_count": 3}
        ):
            result = runner.invoke(
                output_app,
                ["export", "--domain", "medical-research", "--format", "json"],
            )

        assert result.exit_code == 0, result.exception
        assert "Exported 3 entries" in result.output

    def test_cli_export_full_result_presented(self) -> None:
        from typer.testing import CliRunner

        from autoinfo.cli.output import app as output_app

        runner = CliRunner()
        with patch(
            "autoinfo.cli.output.export_kb",
            return_value={"entries_count": 5, "path": "/tmp/kb.json"},
        ):
            result = runner.invoke(
                output_app,
                ["export", "--domain", "medical-research", "--format", "json"],
            )

        assert result.exit_code == 0, result.exception
        assert "Exported 5 entries to /tmp/kb.json" in result.output


# ---------------------------------------------------------------------------
# B-07 — epub/mobi export lang derived from entries (default "en")
# ---------------------------------------------------------------------------


class TestB07EbookLangDerivation:
    """``_export_epub`` / ``_export_mobi`` derive ``lang`` from entries."""

    def test_export_epub_lang_derived_from_entry(self, tmp_path: Path) -> None:
        from autoinfo.output import _export_epub

        entries = [
            {
                "title": "测试标题",
                "summary": "这是摘要内容。",
                "language": "zh",
            }
        ]
        with patch(
            "autoinfo.output.ebook.render_epub"
        ) as mock_render:
            mock_render.return_value = {
                "data_b64": base64.b64encode(b"book").decode("ascii")
            }
            _export_epub(
                tmp_path,
                entries,
                timestamp="20260808-000000",
                domain_label="medical-research",
            )

        assert mock_render.call_args.kwargs["lang"] == "zh"

    def test_export_epub_lang_defaults_en_when_unknown(self, tmp_path: Path) -> None:
        from autoinfo.output import _export_epub

        entries = [
            {"title": "Untitled", "summary": "", "language": ""},
            {"title": "More", "summary": "body", "language": ""},
        ]
        with patch(
            "autoinfo.output.ebook.render_epub"
        ) as mock_render:
            mock_render.return_value = {
                "data_b64": base64.b64encode(b"book").decode("ascii")
            }
            _export_epub(
                tmp_path,
                entries,
                timestamp="20260808-000000",
                domain_label="medical-research",
            )

        assert mock_render.call_args.kwargs["lang"] == "en"

    def test_export_mobi_lang_derived_from_entry(self, tmp_path: Path) -> None:
        from autoinfo.output import _export_mobi

        entries = [
            {
                "title": "Rapport sur la recherche",
                "summary": "Un résumé en français.",
                "language": "fr",
            }
        ]
        with (
            patch("autoinfo.output.ebook.render_epub") as mock_render,
            patch(
                "autoinfo.output.ebook.render_mobi",
                return_value={
                    "data_b64": base64.b64encode(b"mobi").decode("ascii")
                },
            ),
        ):
            mock_render.return_value = {
                "data_b64": base64.b64encode(b"book").decode("ascii")
            }
            _export_mobi(
                tmp_path,
                entries,
                timestamp="20260808-000000",
                domain_label="medical-research",
            )

        assert mock_render.call_args.kwargs["lang"] == "fr"

    def test_derive_export_lang_primary_subtag(self) -> None:
        """zh-CN / en-US normalize to their primary subtag (RFC 5646)."""
        from autoinfo.output import _derive_export_lang

        assert _derive_export_lang(
            [{"title": "t", "summary": "s", "language": "zh-CN"}]
        ) == "zh"
        assert _derive_export_lang(
            [{"title": "t", "summary": "s", "language": "en-US"}]
        ) == "en"


# ---------------------------------------------------------------------------
# B-08 — validation subprocess orphan: own session + group kill on timeout
# ---------------------------------------------------------------------------


class TestB08SubprocessOrphan:
    """``_run_cli_step`` spawns the CLI in its own session and reaps the group."""

    def test_run_cli_step_uses_start_new_session(self) -> None:
        from autoinfo.mcp.validation import _run_cli_step

        with patch("autoinfo.mcp.validation.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("out", "")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            env = _run_cli_step("echo hi")

        assert env["success"] is True
        assert mock_popen.call_args.kwargs["start_new_session"] is True

    def test_run_cli_step_spawns_own_session(self) -> None:
        """A real spawned step runs in a different session than the test process."""
        from autoinfo.mcp.validation import _run_cli_step

        parent_sid = os.getsid(os.getpid())
        env = _run_cli_step(
            "python3 -c \"import os; print(os.getsid(0))\""
        )
        assert env["success"] is True, env
        child_sid = int(env["data"]["stdout"].strip())
        assert child_sid != parent_sid

    def test_kill_process_group_reaps_group(self) -> None:
        """Killing the group SIGKILLs the shell AND its children."""
        from autoinfo.mcp.validation import _kill_process_group

        proc = subprocess.Popen(
            "sleep 300",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _kill_process_group(proc)
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        assert proc.returncode == -signal.SIGKILL
        # The whole process group must be gone (no orphaned `sleep`).
        with pytest.raises(ProcessLookupError):
            os.killpg(proc.pid, 0)


# ---------------------------------------------------------------------------
# query_collected — KBStore() default base_path anchored to project root
# ---------------------------------------------------------------------------


class TestQueryCollectedKBStoreBasePath:
    """``KBStore()`` default ``base_path`` resolves deterministically."""

    def test_kbstore_default_base_path_anchors_to_project_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """From a subdirectory, the default anchors at the project root."""
        from autoinfo.kb import KBStore

        project = tmp_path / "proj"
        (project / ".autoinfo").mkdir(parents=True)
        (project / ".autoinfo" / "config.yaml").write_text(
            "domains: []\n", encoding="utf-8"
        )
        subdir = project / "sub" / "dir"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        store = KBStore()

        assert store.base_path == (project / "knowledge").resolve()
        assert store.base_path != (subdir / "knowledge").resolve()

    def test_kbstore_default_base_path_falls_back_to_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without any project config, the historical cwd-relative default holds."""
        from autoinfo.kb import KBStore

        monkeypatch.chdir(tmp_path)
        store = KBStore()

        assert store.base_path == (tmp_path / "knowledge").resolve()
