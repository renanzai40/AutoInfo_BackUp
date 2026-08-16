"""Regression test for the release-please workflow (#275).

GitHub's 2026-06-11 security change requires manual approval before
workflows run on PRs authored by github-actions[bot]. Release-please
creates the release PR as the bot, so the 6 required status checks were
stuck in `action_required` with zero jobs -> the release PR stayed blocked.

Fix: release-please-action must run with a human token. The workflow passes
`secrets.RELEASE_PLEASE_PAT` when a human has configured it, and falls back
to the default `github.token` (bot token) until then.

NOTE: the workflow uses the YAML 1.1 `on:` key, which PyYAML's safe_load
misparses as the boolean `True`. We parse with `yaml.BaseLoader` (or a
YAML-1.1-safe approach) so the document loads with the real `on` key.
"""

from pathlib import Path
from typing import Any, cast

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-please.yml"
)


def _load_workflow() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader))


def _steps() -> list[dict[str, Any]]:
    data = _load_workflow()
    return cast(list[dict[str, Any]], data["jobs"]["release-please"]["steps"])


def test_token_uses_pat_with_bot_fallback() -> None:
    steps = _steps()
    assert steps[0]["with"]["token"] == "${{ secrets.RELEASE_PLEASE_PAT || github.token }}"


def test_no_release_type_or_package_name_inputs() -> None:
    steps = _steps()
    with_inputs = steps[0]["with"]
    assert "release-type" not in with_inputs
    assert "package-name" not in with_inputs


def test_header_documents_release_please_pat() -> None:
    header = WORKFLOW.read_text().split("name: Release", 1)[0]
    assert "RELEASE_PLEASE_PAT" in header
