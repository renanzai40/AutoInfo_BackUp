"""Regression guard for issue #347: scenario YAMLs must be portable.

Scenarios used to hardcode the product team's dev-machine absolute paths
(e.g. ``PYTHONPATH=/tmp/opencode/wt-342/src /mnt/d/贯维/AutoInfo/.venv/bin/python -c '...'``)
which made them fail on any other machine.  Scenario commands run verbatim
through ``subprocess.Popen(shell=True)`` with inherited cwd/env
(``validation._run_cli_step``), so any dev-machine path baked into a
scenario ``command`` / ``cwd`` / ``env`` / ``url`` / ``collect_artifacts``
breaks the run everywhere but the author's box.

This test parses every scenario through ``load_scenarios()`` (the exact
shape the runner consumes — NOT raw file grep) and asserts no banned
dev-machine token appears in any string leaf of any scenario step.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from autoinfo.mcp.validation import load_scenarios

# Banned dev-machine path tokens.  These are byte-level markers of an
# unportable hardcoded absolute path; they must never appear in a scenario.
BANNED_TOKENS: tuple[str, ...] = (
    "/tmp/opencode",
    "/mnt/",
    "/home/",
    "/Users/",
    "/root/",
    "/var/",
    "/opt/",
    "/etc/",
    ".venv/bin/python",
    r"C:\\",
    r"D:\\",
)

# Additional guard: any absolute POSIX path rooted in a known dev workspace
# directory (covers dev-root dirs the literal list above cannot enumerate).
# Deliberately excludes /tmp and /dev: /tmp/autoinfo-* scratch dirs and
# /dev/null are portable-by-intent and legitimately appear in scenarios.
ABS_DEV_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])/(?:workspace|workspaces|code|repo|project|projects|src)/"
)


def _string_leaves(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Return every string leaf of a nested dict/list as (path, value)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [(prefix, value)]
    if isinstance(value, dict):
        found: list[tuple[str, str]] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_string_leaves(child, child_path))
        return found
    if isinstance(value, list):
        found = []
        for i, child in enumerate(value):
            child_path = f"{prefix}[{i}]"
            found.extend(_string_leaves(child, child_path))
        return found
    return []


def _step_name(step: dict[str, Any]) -> str:
    return str(step.get("name", "<unnamed>"))


def _scenario_string_leaves(scenario: dict[str, Any]) -> list[tuple[str, str, str]]:
    """All (step_label, field_path, string) leaves of a scenario's steps."""
    found: list[tuple[str, str, str]] = []

    def walk_steps(steps: list[dict[str, Any]], label: str) -> None:
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            name = _step_name(step)
            step_label = f"{label}[{i}] ({name})"
            for field in ("command", "cwd", "env", "url", "arguments", "expect"):
                if field not in step:
                    continue
                for path, leaf in _string_leaves(step[field]):
                    found.append((step_label, f"{field}.{path}" if path else field, leaf))
            # Issue #138: per-step recovery steps — same shape as steps.
            if isinstance(step.get("recovery_steps"), list):
                walk_steps(step["recovery_steps"], f"{step_label}.recovery_steps")

    walk_steps(scenario.get("steps", []), "step")
    if isinstance(scenario.get("cleanup_steps"), list):
        walk_steps(scenario["cleanup_steps"], "cleanup_step")
    # Top-level collect_artifacts patterns are relative globs; still scanned.
    for path, leaf in _string_leaves(scenario.get("collect_artifacts")):
        found.append(("collect_artifacts", path, leaf))
    return found


def _banned_in(leaf: str) -> str | None:
    for token in BANNED_TOKENS:
        if token in leaf:
            return token
    m = ABS_DEV_PATH_RE.search(leaf)
    return m.group(0) if m else None


def test_no_dev_abs_paths_in_scenarios() -> None:
    """No scenario step string may contain a dev-machine absolute path."""
    scenarios = load_scenarios()
    assert scenarios, "load_scenarios() must return the packaged scenarios"

    violations: list[tuple[str, str, str, str, str]] = []
    for scenario in scenarios:
        name = str(scenario.get("name", "<unnamed>"))
        for step_label, field_path, leaf in _scenario_string_leaves(scenario):
            token = _banned_in(leaf)
            if token is not None:
                violations.append((name, step_label, field_path, token, leaf))

    if violations:
        lines = [
            "Scenario YAMLs must be portable — no dev-machine absolute paths. "
            "Found:",
        ]
        for sc_name, step_label, field_path, token, leaf in violations:
            # Report the offending line from the scenario file when possible.
            line = _locate_line(sc_name, token)
            lines.append(
                f"  scenario={sc_name} step={step_label} "
                f"field={field_path} token={token!r} line={line}"
            )
        pytest.fail("\n".join(lines))


def _locate_line(scenario_name: str, token: str) -> str:
    """Best-effort source line number for a banned token in a scenario."""
    import yaml

    from autoinfo.mcp.validation import SCENARIOS_DIR

    needle = scenario_name
    for yaml_path in sorted(SCENARIOS_DIR.rglob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and data.get("name") == needle:
            for lineno, text in enumerate(
                yaml_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if token in text:
                    return f"{yaml_path.name}:{lineno}"
            return f"{yaml_path.name}:<no match>"
    return f"{scenario_name}:<file not found>"
