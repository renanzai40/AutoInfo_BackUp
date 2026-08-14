"""Coverage-audit tests (E3, issue #134).

Covers three things:

1. ``kb-promote.yaml`` — valid YAML with the required scenario keys.
2. ``kb-promote.yaml`` — a two-section admission matrix: section 1 [pass]
   promotes an eligible draft to 03-Wiki (tier 03, promotion_source=agent);
   section 2 [reject] refuses a draft whose source lacks source_url with no
   03-Wiki row.  Its cleanup purges BOTH the 03-Wiki and 01-Raw entries via
   the DIRECTOR path (T5: 03-Wiki is append-only for non-directors).
3. ``scripts/coverage_audit.py`` — the counting logic must be
   ``covered = declared ∩ scenario_used`` so that phantom scenario tools
   (e.g. ``definitely_not_a_real_tool`` in error-boundary.yaml) can never
   inflate the covered count and mask genuinely-missing declared tools.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = ROOT / "src" / "autoinfo" / "mcp" / "scenarios"
KB_PROMOTE_YAML = SCENARIOS_DIR / "kb-promote.yaml"

SERVER_SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
AUDIT_SCRIPT = ROOT / "scripts" / "coverage_audit.py"


# ---------------------------------------------------------------------------
# Import the real coverage_audit.py so the tests exercise the script's own
# logic rather than a reimplementation.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def coverage_audit() -> Any:
    spec = importlib.util.spec_from_file_location("coverage_audit", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# kb-promote.yaml: validity + structure
# ---------------------------------------------------------------------------


def test_kb_promote_yaml_exists_and_parses() -> None:
    assert KB_PROMOTE_YAML.is_file(), "kb-promote.yaml must exist"
    data = yaml.safe_load(KB_PROMOTE_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # Required top-level keys enforced by validation.load_scenarios
    for key in ("name", "description", "steps"):
        assert key in data, f"missing required key: {key}"
    assert data["name"] == "kb-promote"
    assert data["category"] == "kb"
    assert data["requires_env"] == []
    assert data["requires_domain"] == ["medical-research"]
    assert data["collect_artifacts"] == [
        "knowledge/medical-research/01-Raw/**/*.md",
        "knowledge/medical-research/02-Draft/**/*.md",
        "knowledge/medical-research/03-Wiki/**/*.md",
        "knowledge/_failed/medical-research/**/*.md",
    ]


def test_kb_promote_steps_and_cleanup() -> None:
    """kb-promote.yaml is a two-section admission matrix: [pass] eligible
    draft -> 03-Wiki with promotion_source=agent; [reject] draft whose source
    lacks source_url -> refused with no 03-Wiki row.  The cleanup routes every
    delete through the DIRECTOR path (T5: 03-Wiki is append-only, non-director
    deletes are refused with DirectorOnlyError / WIKI_PROTECTED)."""
    data = yaml.safe_load(KB_PROMOTE_YAML.read_text(encoding="utf-8"))
    steps = data["steps"]
    # 8 steps: 2 sections x (seed raw -> create draft -> promote -> verify)
    assert len(steps) == 8
    tools = [s.get("tool") for s in steps]
    # Section 1 [pass]: seeds the raw via the store (real G1/G3 gate scores —
    # MCP create_kb_entry cannot set scores), then drives draft + promote
    # through the MCP surface.
    assert steps[0].get("kind") == "cli"
    assert tools[1:3] == ["create_kb_draft", "promote_kb_draft"]
    # Section 2 [reject]: promote is refused with an error envelope.
    assert tools[5:7] == ["create_kb_draft", "promote_kb_draft"]
    assert steps[6]["expect"].get("success") is False
    assert any("03-Wiki" in s for s in steps[3]["expect"]["stdout_has"])  # pass-side verify
    assert any("02-Draft" in s for s in steps[7]["expect"]["stdout_has"])  # reject-side verify

    cleanup = data.get("cleanup_steps")
    assert isinstance(cleanup, list) and len(cleanup) >= 1
    cleanup_cmd = cleanup[0]["command"]
    # Cleanup must purge the promoted 03-Wiki entry AND the original 01-Raw
    # entries (promotion keeps the draft's entry_id in 03-Wiki).
    assert "medical-research-general-t9-kbp-pass-entry" in cleanup_cmd
    assert "medical-research-draft-t9-kbp-pass-draft" in cleanup_cmd
    # T5 alignment: deletes run through the director path (03-Wiki is
    # append-only; non-director deletes are refused).
    assert 'actor="director"' in cleanup_cmd
    assert "03-Wiki" in cleanup_cmd
    assert cleanup[0]["expect"].get("success") is True
    assert "CLEANED" in cleanup[0]["expect"]["stdout_has"]


def test_kb_promote_passes_load_scenarios_validation() -> None:
    """kb-promote.yaml must be accepted by the real scenario loader."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from autoinfo.mcp.validation import load_scenarios
    finally:
        sys.path.remove(str(ROOT / "src"))
    names = {s["name"] for s in load_scenarios()}
    assert "kb-promote" in names


def test_director_tool_steps_carry_explicit_director_actor() -> None:
    """Success steps for force_promote / demote_kb_wiki must pass actor.

    Regression guard for #236: the director whitelist
    (``AUTOINFO_DIRECTOR_ACTORS``, default ``director``) refuses omitted
    actors at MCP dispatch (the default is ``agent``). Scenarios written
    before the guard existed omitted the actor and broke once it landed
    (director-backdoor, promotion-triggers, search-tier-boost). Success-
    expecting director steps must declare ``actor: director`` explicitly.
    """
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from autoinfo.mcp.validation import load_scenarios
    finally:
        sys.path.remove(str(ROOT / "src"))
    violations = []
    for sc in load_scenarios():
        for i, step in enumerate(sc["steps"]):
            if step.get("tool") not in ("force_promote", "demote_kb_wiki"):
                continue
            expect_success = step.get("expect", {}).get("success", True)
            if expect_success and step.get("arguments", {}).get("actor") != "director":
                violations.append(f"{sc['name']}[{i}] {step['name']}")
    assert not violations, (
        "director-only tool success steps must pass actor: director "
        f"(#236 regression guard): {violations}"
    )


# ---------------------------------------------------------------------------
# coverage_audit.py counting logic (issue #134)
# ---------------------------------------------------------------------------

SERVER_SNIPPET = (
    'Tool(\n'
    '    name="alpha_tool",\n'
    '    description="...",\n'
    ')\n'
    'Tool(name="beta_tool")\n'
    'Tool(\n'
    '    name="gamma_tool",\n'
    ')\n'
)


def _write_scenario(dirpath: Path, name: str, tools: list[str]) -> Path:
    p = dirpath / f"{name}.yaml"
    steps = []
    for t in tools:
        steps.append({"name": f"call {t}", "tool": t, "expect": {"success": True}})
    p.write_text(
        yaml.safe_dump({"name": name, "description": name, "steps": steps}),
        encoding="utf-8",
    )
    return p


def test_covered_is_declared_intersection_with_phantom(coverage_audit: Any, tmp_path: Path) -> None:
    """A phantom scenario tool must NOT count as covering a declared tool."""
    _write_scenario(tmp_path, "good", ["alpha_tool", "beta_tool"])
    # error-boundary style: references a tool that server.py never declares
    _write_scenario(tmp_path, "phantom", ["alpha_tool", "definitely_not_a_real_tool"])

    cov = coverage_audit.compute_coverage(SERVER_SNIPPET, tmp_path)

    assert cov["declared"] == ["alpha_tool", "beta_tool", "gamma_tool"]
    assert cov["scenario_used"] == ["alpha_tool", "beta_tool", "definitely_not_a_real_tool"]
    # covered = declared ∩ scenario_used — the phantom contributes nothing
    assert cov["covered"] == ["alpha_tool", "beta_tool"]
    assert len(cov["covered"]) == 2
    # gamma_tool is genuinely uncovered
    assert cov["missing"] == ["gamma_tool"]
    # phantom is separated out, informational only
    assert cov["phantom"] == ["definitely_not_a_real_tool"]


def test_missing_is_declared_minus_covered(coverage_audit: Any, tmp_path: Path) -> None:
    """missing = declared - (declared ∩ scenario_used) = declared - scenario_used."""
    _write_scenario(tmp_path, "partial", ["alpha_tool"])
    cov = coverage_audit.compute_coverage(SERVER_SNIPPET, tmp_path)
    assert cov["covered"] == ["alpha_tool"]
    assert cov["missing"] == ["beta_tool", "gamma_tool"]
    assert set(cov["missing"]) == set(cov["declared"]) - set(cov["covered"])


def test_full_coverage_when_all_declared_used(coverage_audit: Any, tmp_path: Path) -> None:
    _write_scenario(
        tmp_path,
        "full",
        ["alpha_tool", "beta_tool", "gamma_tool", "definitely_not_a_real_tool"],
    )
    cov = coverage_audit.compute_coverage(SERVER_SNIPPET, tmp_path)
    assert len(cov["covered"]) == len(cov["declared"]) == 3
    assert cov["missing"] == []
    assert cov["phantom"] == ["definitely_not_a_real_tool"]


def test_non_mcp_steps_do_not_count(coverage_audit: Any, tmp_path: Path) -> None:
    """kind: cli steps reference no tool and must not enter scenario_used."""
    p = tmp_path / "mixed.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "mixed",
                "description": "mixed kinds",
                "steps": [
                    {"name": "mcp step", "tool": "alpha_tool", "expect": {"success": True}},
                    {
                        "name": "cli step",
                        "kind": "cli",
                        "command": "python3 -c 'print(1)'",
                        "expect": {"success": True},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    cov = coverage_audit.compute_coverage(SERVER_SNIPPET, tmp_path)
    assert cov["scenario_used"] == ["alpha_tool"]
    assert cov["covered"] == ["alpha_tool"]


def test_live_audit_prints_full_coverage() -> None:
    """End-to-end: the real script against the real repo must report 145/145
    with an empty MISSING list (145 tools = 142 baseline + T5's director
    backdoor tools demote_kb_wiki/force_promote + T6's promote_pending sweep;
    all three are covered by the director-backdoor and promotion-triggers
    scenarios; the phantom from error-boundary.yaml is not counted as a real
    tool)."""
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Covered by scenarios: 145/145" in result.stdout
    assert "MISSING tools (0):" in result.stdout
    # phantom must be reported separately, never as missing
    assert "definitely_not_a_real_tool" in result.stdout
    assert result.stdout.index("MISSING tools (0):") < result.stdout.index(
        "definitely_not_a_real_tool"
    )


def test_live_audit_prints_regression_scenarios() -> None:
    """The real coverage_audit.py must print 'Regression scenarios: N (issues: ...)'."""
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Regression scenarios:" in result.stdout
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("Regression scenarios:")]
    assert len(lines) == 1
    line = lines[0]
    assert "#104" in line
    assert "#119" in line
    assert "#121" in line
    assert "#126" in line
    assert "#135" in line


def test_compute_coverage_includes_regression_subdir(coverage_audit: Any, tmp_path: Path) -> None:
    """compute_coverage with rglob scans regression/ subdirectory for tool coverage."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _write_scenario(tmp_path, "top-level", ["alpha_tool"])
    reg_dir = tmp_path / "regression"
    reg_dir.mkdir()
    _write_scenario(reg_dir, "reg-sub", ["beta_tool"])
    cov = coverage_audit.compute_coverage(SERVER_SNIPPET, tmp_path)
    assert cov["covered"] == ["alpha_tool", "beta_tool"]
    assert "reg-sub" in cov["scenario_names"]
