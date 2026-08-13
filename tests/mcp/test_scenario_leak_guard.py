"""SCENARIO_LEAK guard tests (B-03): scenarios writing ``*.autoinfo.test``
fixtures into the real KB must either clean them up or surface a leak warning.

Both tests write a fixture into the real knowledge base via the real scenario
engine (``kind: cli`` steps), then assert the guard's leak-scan behavior.
Each test uses its own marker entry; an autouse fixture purges the marker
before and after every test so no residue survives assertion failures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoinfo.kb import KBStore
from autoinfo.mcp.validation import run_scenario

LEAK_MARKER_URL = "https://leak-guard.autoinfo.test/leak-guard-leak-a"
LEAK_MARKER_ID = "medical-research-general-leak-guard-leak-a"
CLEAN_MARKER_URL = "https://leak-guard.autoinfo.test/leak-guard-clean-b"
CLEAN_MARKER_ID = "medical-research-general-leak-guard-clean-b"

_MARKERS = (LEAK_MARKER_ID, CLEAN_MARKER_ID)


@pytest.fixture(autouse=True)
def purge_marker_entries() -> None:
    store = KBStore()
    for entry_id in _MARKERS:
        store.delete_entry(entry_id)
    yield
    for entry_id in _MARKERS:
        store.delete_entry(entry_id)


def _write_scenario(
    tmp_path: Path, marker_url: str, marker_id: str, title: str, cleanup: bool
) -> tuple[Path, str]:
    cleanup_cmd = (
        "python3 -c 'from autoinfo.kb import KBStore; "
        f'KBStore().delete_entry("{marker_id}")\''
    ) if cleanup else "true"
    yaml = f"""name: leak-guard-scenario
description: "B-03 guard: fixture written under the reserved *.autoinfo.test hostname"
category: kb
requires_env: []
steps:
  - name: "write marker entry"
    kind: cli
    command: |-
      python3 -c '
      from datetime import datetime, timezone
      from autoinfo.kb import KBStore
      from autoinfo.models import Item
      NOW = datetime.now(timezone.utc).isoformat()
      store = KBStore()
      store.store_entry(Item(id="leak-guard-a", source_name="scenario", source_type="api",
          source_url="{marker_url}",
          title="{title}",
          content="Marker entry for the SCENARIO_LEAK guard.",
          collected_at=NOW, domain="medical-research"))
      print("MARKER_WRITTEN")
      '
    expect:
      success: true
      exit_code: 0
      stdout_has: ["MARKER_WRITTEN"]
cleanup_steps:
  - name: "cleanup marker"
    kind: cli
    command: |-
      {cleanup_cmd}
    expect:
      success: true
      exit_code: 0
"""
    path = tmp_path / "leak-guard.yaml"
    path.write_text(yaml)
    return path, "leak-guard-scenario"


def _fake_dispatch(tool: str, arguments: dict, trace_id: str) -> dict:
    return {"status": "passed"}


async def test_leak_scenario_reports_warning(tmp_path: Path) -> None:
    _, scenario_name = _write_scenario(
        tmp_path, LEAK_MARKER_URL, LEAK_MARKER_ID,
        title="Leak Guard Leak A", cleanup=False,
    )
    result = await run_scenario(scenario_name, _fake_dispatch, scenarios_dir=tmp_path)
    assert result["status"] == "passed", result
    assert "warnings" in result, "leak must produce a SCENARIO_LEAK warning"
    joined = " ".join(result["warnings"])
    assert "SCENARIO_LEAK" in joined
    assert LEAK_MARKER_ID in joined
    store = KBStore()
    entry = store.get_entry_by_source_url(LEAK_MARKER_URL)
    assert entry is not None, "fixture should still exist when cleanup is skipped"


async def test_clean_scenario_has_no_warning(tmp_path: Path) -> None:
    _, scenario_name = _write_scenario(
        tmp_path, CLEAN_MARKER_URL, CLEAN_MARKER_ID,
        title="Leak Guard Clean B", cleanup=True,
    )
    result = await run_scenario(scenario_name, _fake_dispatch, scenarios_dir=tmp_path)
    assert result["status"] == "passed", result
    assert "warnings" not in result, "clean scenario must not warn"
    store = KBStore()
    entry = store.get_entry_by_source_url(CLEAN_MARKER_URL)
    assert entry is None, "cleanup must remove the fixture"
