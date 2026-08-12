"""Tests for the Agent-native MCP validation toolset.

Covers the scenario loader and executor (:mod:`autoinfo.mcp.validation`)
as well as the server-integrated MCP tools ``list_validation_scenarios``
and ``run_validation_scenario``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp import validation as validation_mod
from autoinfo.mcp.validation import (
    _normalize_envelope,
    diff_scenario_runs,
    list_scenarios,
    list_validation_runs,
    load_scenario_results,
    load_scenarios,
    run_scenario,
    save_scenario_results,
)

# ============================================================================
# Unit tests: load_scenarios
# ============================================================================


class TestLoadScenarios:
    """Test the scenario YAML loader."""

    def test_loads_packaged_scenarios(self) -> None:
        """Should load 6 or more scenarios from the built-in scenarios/ dir."""
        scs = load_scenarios()
        assert len(scs) >= 6, f"Expected ≥6 scenarios, got {len(scs)}"

        for sc in scs:
            assert "name" in sc
            assert "description" in sc
            assert "steps" in sc
            assert isinstance(sc["steps"], list)
            assert len(sc["steps"]) >= 1
            for step in sc["steps"]:
                assert "name" in step
                # Each step must have a dispatch target for its kind:
                # mcp → tool, cli → command, http → url
                kind = step.get("kind", "mcp")
                assert ("tool" in step) or ("command" in step) or ("url" in step), (
                    f"step {step['name']!r} (kind={kind}) missing tool/command/url"
                )

    def test_loads_from_custom_dir(self, tmp_path: Path) -> None:
        """Should load scenarios from a user-provided directory."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "my-test.yaml").write_text(
            "name: my-test\ndescription: Test\nsteps:\n"
            "  - name: step1\n    tool: health_check\n",
            encoding="utf-8",
        )
        scs = load_scenarios(sd)
        assert len(scs) == 1
        assert scs[0]["name"] == "my-test"

    def test_raises_on_bad_yaml(self, tmp_path: Path) -> None:
        """Bad YAML should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        bad_path = sd / "bad.yaml"
        bad_path.write_text(": : : bad yaml\n", encoding="utf-8")

        with pytest.raises(ValueError, match="bad\\.yaml"):
            load_scenarios(sd)

    def test_raises_on_missing_name(self, tmp_path: Path) -> None:
        """Missing 'name' field should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "no-name.yaml").write_text(
            "description: Test\nsteps:\n  - name: s\n    tool: health_check\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no-name\\.yaml.*missing.*'name'"):
            load_scenarios(sd)

    def test_raises_on_missing_steps(self, tmp_path: Path) -> None:
        """Missing 'steps' field should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "no-steps.yaml").write_text(
            "name: test\ndescription: Test\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no-steps\\.yaml.*missing.*'steps'"):
            load_scenarios(sd)

    def test_raises_on_empty_steps(self, tmp_path: Path) -> None:
        """Empty steps list should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "empty-steps.yaml").write_text(
            "name: test\ndescription: Test\nsteps: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="empty-steps\\.yaml.*non-empty"):
            load_scenarios(sd)

    def test_raises_on_step_missing_name(self, tmp_path: Path) -> None:
        """Step missing 'name' should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad-step.yaml").write_text(
            "name: test\ndescription: Test\nsteps:\n  - tool: health_check\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="bad-step\\.yaml.*step\\[0\\].*'name'"):
            load_scenarios(sd)

    def test_raises_on_step_missing_tool(self, tmp_path: Path) -> None:
        """Step missing 'tool' should raise ValueError."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad-step.yaml").write_text(
            "name: test\ndescription: Test\nsteps:\n  - name: s\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="bad-step\\.yaml.*step\\[0\\].*'tool'"):
            load_scenarios(sd)


# ============================================================================
# Unit tests: keyword-management scenario seeds (issue #194)
# ============================================================================


class TestKeywordManagementScenario:
    """The packaged keyword-management scenario must seed its own keywords.

    Regression for #194: the scenario approves ``multicenter`` and rejects
    ``time-lapse embryo imaging``, but those keywords no longer exist in the
    runtime keyword store.  Because approve/reject return ``None`` (and the
    MCP layer surfaces ``KEYWORD_NOT_FOUND``) for unknown keywords, the
    scenario must create both keywords via ``kind: cli`` seed steps that run
    BEFORE the mutating MCP steps — while keeping the backup/restore
    self-cleaning contract (backup first, restore last).
    """

    @pytest.fixture()
    def scenario(self) -> dict[str, Any]:
        matches = [sc for sc in load_scenarios() if sc["name"] == "keyword-management"]
        assert len(matches) == 1, (
            f"expected exactly one keyword-management scenario, got {len(matches)}"
        )
        return matches[0]

    @staticmethod
    def _seed_step_index(steps: list[dict[str, Any]], keyword: str) -> int:
        """Index of the kind: cli step that seeds *keyword* via add_keyword."""
        for i, step in enumerate(steps):
            command = step.get("command", "")
            if step.get("kind") == "cli" and "add_keyword" in command and keyword in command:
                return i
        raise AssertionError(f"no seed step calls add_keyword for {keyword!r}")

    @staticmethod
    def _mutate_step_index(
        steps: list[dict[str, Any]], keyword: str, tool: str
    ) -> int:
        """Index of the mcp step that approves/rejects *keyword* via *tool*."""
        for i, step in enumerate(steps):
            if (
                step.get("tool") == tool
                and step.get("arguments", {}).get("keyword") == keyword
            ):
                return i
        raise AssertionError(f"no {tool} step found for keyword {keyword!r}")

    def test_seed_steps_precede_approve_reject(self, scenario: dict[str, Any]) -> None:
        """Each keyword is seeded by a cli step before its mutate step."""
        steps = scenario["steps"]
        for keyword, tool in (
            ("multicenter", "approve_keyword"),
            ("time-lapse embryo imaging", "reject_keyword"),
        ):
            seed_i = self._seed_step_index(steps, keyword)
            mutate_i = self._mutate_step_index(steps, keyword, tool)
            assert seed_i < mutate_i, (
                f"seed step for {keyword!r} (index {seed_i}) must run before "
                f"{tool} step (index {mutate_i})"
            )

    def test_seed_steps_expect_success_marker(self, scenario: dict[str, Any]) -> None:
        """Seed steps must pass (exit_code 0) and print a SEEDED marker."""
        steps = scenario["steps"]
        for keyword in ("multicenter", "time-lapse embryo imaging"):
            step = steps[self._seed_step_index(steps, keyword)]
            expect = step.get("expect", {})
            assert expect.get("exit_code") == 0, (
                f"seed step for {keyword!r} must expect exit_code 0, got {expect}"
            )
            markers = expect.get("stdout_has", [])
            assert any("SEEDED" in m and keyword in m for m in markers), (
                f"seed step for {keyword!r} must expect a 'SEEDED:{keyword}' "
                f"stdout marker, got {markers}"
            )

    def test_self_cleaning_order(self, scenario: dict[str, Any]) -> None:
        """Backup runs first, seeds in between, restore runs last."""
        steps = scenario["steps"]
        backup_i = next(
            i
            for i, step in enumerate(steps)
            if step.get("kind") == "cli" and "copyfile" in step.get("command", "")
        )
        restore_i = next(
            i
            for i, step in enumerate(steps)
            if step.get("kind") == "cli" and "KEYWORDS_RESTORED" in step.get("command", "")
        )
        assert restore_i == len(steps) - 1, (
            f"restore step (index {restore_i}) must be last of {len(steps)} steps"
        )
        for keyword in ("multicenter", "time-lapse embryo imaging"):
            seed_i = self._seed_step_index(steps, keyword)
            assert backup_i < seed_i < restore_i, (
                f"seed step for {keyword!r} (index {seed_i}) must run after "
                f"backup (index {backup_i}) and before restore (index {restore_i})"
            )


# ============================================================================
# Unit tests: list_scenarios
# ============================================================================


class TestListScenarios:
    """Test the scenario listing function."""

    def test_returns_summary_shape(self) -> None:
        """Should return scenarios list with summary fields."""
        result = list_scenarios()
        assert "scenarios" in result
        assert "count" in result
        assert result["count"] >= 6
        for sc in result["scenarios"]:
            assert "name" in sc
            assert "description" in sc
            assert "category" in sc
            assert "step_count" in sc
            assert "requires_env" in sc


# ============================================================================
# Unit tests: _normalize_envelope
# ============================================================================


class TestNormalizeEnvelope:
    """Test the envelope normaliser for flat health_check responses."""

    def test_passes_through_envelope(self) -> None:
        """Envelope dicts pass through unchanged."""
        env = {"success": True, "data": {"key": "value"}}
        assert _normalize_envelope(env) == env

    def test_wraps_flat_dict(self) -> None:
        """Flat dicts (e.g. health_check) get wrapped into an envelope."""
        flat = {"status": "ok", "version": "1.0"}
        result = _normalize_envelope(flat)
        assert result["success"] is True
        assert result["data"] == flat

    def test_wraps_flat_error_error_code(self) -> None:
        """Flat error dicts with error_code (legacy) get wrapped."""
        flat = {"error_code": "NotFound", "message": "not found"}
        result = _normalize_envelope(flat)
        assert result["success"] is True  # no "success" key → treated as success
        assert result["data"] == flat


# ============================================================================
# Unit tests: run_scenario (with fake dispatch)
# ============================================================================


class TestRunScenarioFakeDispatch:
    """run_scenario tests using a controlled fake dispatch."""

    SCENARIO_YAML = """\
name: fake-scenario
description: "Fake scenario for unit testing"
category: test
requires_env: []
steps:
  - name: "all-pass step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]

  - name: "error-expected step"
    tool: fake_error
    arguments: {}
    expect:
      success: false
      error_code: "Timeout"

  - name: "missing-key step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["missing_key"]
"""

    SCENARIO_LLM_YAML = """\
name: llm-scenario
description: "LLM-assert scenario"
category: test
requires_env: []
steps:
  - name: "llm-pass step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      llm_assert: "Is the result ok?"

  - name: "llm-fail step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      llm_assert: "Is the result bad?"
"""

    SCENARIO_ENV_GATED_YAML = """\
name: env-gated
description: "Env-gated scenario"
category: test
requires_env: ["MISSING_VAR_XYZ"]
steps:
  - name: "should report unconfigured"
    tool: health_check
    arguments: {}
"""

    @pytest.fixture
    def scenario_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "fake-scenario.yaml").write_text(self.SCENARIO_YAML, encoding="utf-8")
        (sd / "llm-scenario.yaml").write_text(self.SCENARIO_LLM_YAML, encoding="utf-8")
        (sd / "env-gated.yaml").write_text(self.SCENARIO_ENV_GATED_YAML, encoding="utf-8")
        return sd

    async def _fake_dispatch(self, name: str, arguments: dict) -> dict:
        """Return controlled envelopes for fake tools."""
        if name == "fake_tool":
            return {"success": True, "data": {"result": "ok"}}
        if name == "fake_error":
            return {"success": False, "error": {"code": "Timeout", "message": "timeout"}}
        if name == "fake_error_actionable":
            return {
                "success": False,
                "error": {"code": "Timeout", "message": "timeout", "actionable": True},
            }
        if name == "bad_tool":
            return 42  # non-dict response — should trigger exception
        return {"success": True, "data": {}}

    async def test_all_pass_scenario(self, scenario_dir: Path) -> None:
        """All-pass steps should return status 'passed'."""
        result = await run_scenario(
            "fake-scenario",
            dispatch=self._fake_dispatch,
            steps=[1, 2],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["summary"]["passed"] == 2
        assert result["summary"]["failed"] == 0
        assert result["summary"]["total"] == 2

    async def test_collect_artifacts_skips_excluded_paths(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """collect_artifacts never collects non-deliverable artifacts (#192).

        Rejected KB promotion drafts under ``knowledge/_failed/<domain>/**``
        and internal ``outputs/coverage-matrix/**`` reports must be absent
        from the artifacts list, while a legit file next to them is kept.
        """
        # Trailing "**" matches only dirs on Python < 3.13 (CPython gh-70303),
        # so all patterns follow the "**/*.ext" convention the packaged
        # scenarios use — otherwise 3.12 collects zero files here.
        sd = self._write_scenario(
            tmp_path,
            "artifact-glob",
            "name: artifact-glob\ndescription: Test\n"
            'collect_artifacts: ["knowledge/**/*.md", "outputs/**/*.md"]\n'
            "steps:\n"
            "  - name: step\n    tool: fake_tool\n    arguments: {}\n"
            "    expect:\n      success: true\n",
        )
        cwd = tmp_path / "cwd"
        legit = cwd / "knowledge" / "medical-research" / "01-Raw" / "x" / "entry.md"
        legit.parent.mkdir(parents=True)
        legit.write_text("# Legit entry\n", encoding="utf-8")
        rejected = cwd / "knowledge" / "_failed" / "medical-research" / "rejected.md"
        rejected.parent.mkdir(parents=True)
        rejected.write_text("# Rejected draft\n", encoding="utf-8")
        matrix = cwd / "outputs" / "coverage-matrix" / "matrix-report.md"
        matrix.parent.mkdir(parents=True)
        matrix.write_text("# Coverage Matrix\n", encoding="utf-8")

        monkeypatch.chdir(cwd)
        result = await run_scenario(
            "artifact-glob", dispatch=self._fake_dispatch, scenarios_dir=sd
        )
        artifact_paths = {a["path"] for a in result["artifacts"]}
        assert str(legit) in artifact_paths, f"legit artifact missing: {artifact_paths}"
        assert not any("_failed" in p for p in artifact_paths), (
            f"_failed draft leaked into artifacts: {artifact_paths}"
        )
        assert not any("coverage-matrix" in p for p in artifact_paths), (
            f"coverage-matrix report leaked into artifacts: {artifact_paths}"
        )

    async def test_assertion_mismatch_fails(self, scenario_dir: Path) -> None:
        """An assertion mismatch should report failed step."""
        # Step 3 expects data_has: ["missing_key"] which is not in the response
        result = await run_scenario(
            "fake-scenario",
            dispatch=self._fake_dispatch,
            steps=[3],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "failed"
        assert result["summary"]["failed"] == 1
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert "missing_key" in step.get("detail", "")

    async def test_error_code_check_passes(self, scenario_dir: Path) -> None:
        """Error code assertion should pass when codes match."""
        result = await run_scenario(
            "fake-scenario",
            dispatch=self._fake_dispatch,
            steps=[2],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "passed"

    async def test_error_code_check_fails_on_mismatch(self, tmp_path: Path) -> None:
        """Error code mismatch should report a failure."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad-code.yaml").write_text(
            "name: bad-code\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: fake_error\n    arguments: {}\n"
            "    expect:\n      success: false\n      error_code: WrongCode\n",
            encoding="utf-8",
        )
        result = await run_scenario(
            "bad-code",
            dispatch=self._fake_dispatch,
            scenarios_dir=sd,
        )
        assert result["status"] == "failed"
        assert result["steps"][0]["status"] == "failed"
        assert "WrongCode" in result["steps"][0].get("detail", "")

    async def test_error_actionable_check_passes_when_actionable(
        self, tmp_path: Path
    ) -> None:
        """error_actionable: true passes when the envelope carries actionable."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "act-ok.yaml").write_text(
            "name: act-ok\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: fake_error_actionable\n    arguments: {}\n"
            "    expect:\n      success: false\n      error_code: Timeout\n"
            "      error_actionable: true\n",
            encoding="utf-8",
        )
        result = await run_scenario(
            "act-ok",
            dispatch=self._fake_dispatch,
            scenarios_dir=sd,
        )
        assert result["status"] == "passed"
        assert result["steps"][0]["status"] == "passed"

    async def test_error_actionable_check_fails_when_missing(
        self, tmp_path: Path
    ) -> None:
        """error_actionable: true fails when the envelope omits actionable."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "act-bad.yaml").write_text(
            "name: act-bad\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: fake_error\n    arguments: {}\n"
            "    expect:\n      success: false\n      error_code: Timeout\n"
            "      error_actionable: true\n",
            encoding="utf-8",
        )
        result = await run_scenario(
            "act-bad",
            dispatch=self._fake_dispatch,
            scenarios_dir=sd,
        )
        assert result["status"] == "failed"
        assert result["steps"][0]["status"] == "failed"
        assert "actionable" in result["steps"][0].get("detail", "")

    async def test_requires_env_reports_unconfigured(self, scenario_dir: Path) -> None:
        """Scenario with missing env var should report 'unconfigured' — not
        silently skipped. Director User is obligated to provide BYOK keys."""
        env_before = os.environ.pop("MISSING_VAR_XYZ", None)
        try:
            result = await run_scenario(
                "env-gated",
                dispatch=self._fake_dispatch,
                scenarios_dir=scenario_dir,
            )
            assert result["status"] == "unconfigured"
            assert "MISSING_VAR_XYZ" in result["unconfigured_reason"]
            assert "Director User" in result["unconfigured_reason"]
            assert result["summary"]["unconfigured"] == result["summary"]["total"]
            assert result["steps"][0]["status"] == "unconfigured"
        finally:
            if env_before is not None:
                os.environ["MISSING_VAR_XYZ"] = env_before

    async def test_llm_assert_pass(self, scenario_dir: Path, monkeypatch) -> None:
        """llm_assert step should PASS when the real LLM judge says PASS."""
        monkeypatch.setattr(
            os.environ, "get",
            lambda k, d=None: "sk-test" if k == "AUTOINFO_LLM_API_KEY" else d,
        )
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured",
            lambda: True,
        )

        def fake_judge(assertion: str, output: Any) -> dict:
            if "bad" in assertion.lower():
                return {"verdict": "FAIL", "reason": "result is bad"}
            return {"verdict": "PASS", "reason": "result is ok"}

        monkeypatch.setattr(
            "autoinfo.mcp.validation._llm_judge",
            fake_judge,
        )

        result = await run_scenario(
            "llm-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["steps"][0]["status"] == "passed"
        assert "llm_reason" in result["steps"][0]

    async def test_llm_assert_fail(self, scenario_dir: Path, monkeypatch) -> None:
        """llm_assert step should FAIL when the real LLM judge says FAIL."""
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured",
            lambda: True,
        )

        def fake_judge(assertion: str, output: Any) -> dict:
            return {"verdict": "FAIL", "reason": "output is bad"}

        monkeypatch.setattr(
            "autoinfo.mcp.validation._llm_judge",
            fake_judge,
        )

        result = await run_scenario(
            "llm-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "failed"
        assert result["steps"][0]["status"] == "failed"
        assert "output is bad" in result["steps"][0]["detail"]

    async def test_llm_assert_unconfigured_without_key(
        self, scenario_dir: Path, monkeypatch
    ) -> None:
        """llm_assert step without LLM key should report 'unconfigured' — not
        silently skipped and not falsely passed."""
        monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured",
            lambda: False,
        )

        result = await run_scenario(
            "llm-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "unconfigured"
        assert result["steps"][0]["status"] == "unconfigured"
        assert "LLM API key" in result["steps"][0]["detail"]

    async def test_llm_assert_judge_error_fails(
        self, scenario_dir: Path, monkeypatch
    ) -> None:
        """A judge exception should surface as FAIL — no silent swallowing."""
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured",
            lambda: True,
        )

        async def broken_judge(assertion: str, output: Any) -> dict:
            raise RuntimeError("simulated LLM outage")

        monkeypatch.setattr(
            "autoinfo.mcp.validation._llm_judge",
            broken_judge,
        )

        result = await run_scenario(
            "llm-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "failed"
        assert "llm_assert error" in result["steps"][0]["detail"]

    async def test_unknown_scenario_raises(self, scenario_dir: Path) -> None:
        """Unknown scenario name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown validation scenario: no-such.*Available:"):
            await run_scenario(
                "no-such",
                dispatch=self._fake_dispatch,
                scenarios_dir=scenario_dir,
            )

    async def test_steps_subset_runs_only_selected(self, scenario_dir: Path) -> None:
        """steps=[1] should only run step 1."""
        result = await run_scenario(
            "fake-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["summary"]["total"] == 1
        assert result["steps"][0]["name"] == "all-pass step"

    async def test_steps_out_of_range_raises(self, scenario_dir: Path) -> None:
        """Out-of-range step index should raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            await run_scenario(
                "fake-scenario",
                dispatch=self._fake_dispatch,
                steps=[99],
                scenarios_dir=scenario_dir,
            )

    async def test_empty_steps_raises(self, scenario_dir: Path) -> None:
        """Empty steps list should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            await run_scenario(
                "fake-scenario",
                dispatch=self._fake_dispatch,
                steps=[],
                scenarios_dir=scenario_dir,
            )

    async def test_dispatch_exception_handled(self, tmp_path: Path) -> None:
        """A dispatch that raises should be caught and reported as failed step."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "exc.yaml").write_text(
            "name: exc-test\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: will_raise\n    arguments: {}\n",
            encoding="utf-8",
        )

        async def raise_dispatch(name: str, arguments: dict) -> dict:
            raise RuntimeError("simulated crash")

        result = await run_scenario(
            "exc-test",
            dispatch=raise_dispatch,
            scenarios_dir=sd,
        )
        assert result["status"] == "failed"
        assert result["steps"][0]["status"] == "failed"
        assert "dispatch exception" in result["steps"][0].get("detail", "")

    # --- #157: env-prereq failures report "unconfigured", not "failed" ----

    HTTP_REQUIRED_YAML = """\
name: http-required
description: "Scenario requiring a reachable HTTP endpoint"
category: test
requires_http: ["http://127.0.0.1:9/health"]
steps:
  - name: "all-pass step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
"""

    def _write_scenario(self, tmp_path: Path, name: str, content: str) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / f"{name}.yaml").write_text(content, encoding="utf-8")
        return sd

    async def test_requires_http_unreachable_reports_unconfigured(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A scenario whose requires_http endpoint is unreachable reports
        'unconfigured' with the URL in the reason — not 'failed' (#157)."""
        sd = self._write_scenario(tmp_path, "http-required", self.HTTP_REQUIRED_YAML)
        monkeypatch.setattr(
            "autoinfo.mcp.validation._http_reachable", lambda url: False
        )
        result = await run_scenario(
            "http-required", dispatch=self._fake_dispatch, scenarios_dir=sd
        )
        assert result["status"] == "unconfigured"
        assert "http://127.0.0.1:9/health" in result["unconfigured_reason"]
        assert result["summary"]["unconfigured"] == result["summary"]["total"]
        assert result["summary"]["failed"] == 0
        assert all(
            step["status"] == "unconfigured" for step in result["steps"]
        )

    async def test_requires_http_reachable_runs_steps(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When the requires_http endpoint is reachable the steps run and are
        NOT marked unconfigured (#157)."""
        sd = self._write_scenario(tmp_path, "http-required", self.HTTP_REQUIRED_YAML)
        monkeypatch.setattr(
            "autoinfo.mcp.validation._http_reachable", lambda url: True
        )
        result = await run_scenario(
            "http-required", dispatch=self._fake_dispatch, scenarios_dir=sd
        )
        assert result["status"] == "passed"
        assert result["steps"][0]["status"] == "passed"
        assert result["summary"]["unconfigured"] == 0

    async def test_reddit_oauth_missing_classified_unconfigured(
        self, tmp_path: Path
    ) -> None:
        """A dispatch raising Reddit-OAuth-missing ValueError is classified
        as unconfigured, not failed (#157)."""
        sd = self._write_scenario(
            tmp_path,
            "reddit-oauth",
            "name: reddit-oauth\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: reddit_tool\n    arguments: {}\n",
        )

        async def raise_dispatch(name: str, arguments: dict) -> dict:
            raise ValueError(
                "Reddit OAuth2 requires client_id and client_secret in config."
            )

        result = await run_scenario(
            "reddit-oauth", dispatch=raise_dispatch, scenarios_dir=sd
        )
        step = result["steps"][0]
        assert step["status"] == "unconfigured"
        assert "Reddit" in step["detail"]
        assert result["status"] == "unconfigured"

    async def test_tts_network_error_classified_unconfigured(
        self, tmp_path: Path
    ) -> None:
        """A dispatch raising the TTS network RuntimeError is classified as
        unconfigured, not failed (#157)."""
        sd = self._write_scenario(
            tmp_path,
            "tts-net",
            "name: tts-net\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: tts_tool\n    arguments: {}\n",
        )

        async def raise_dispatch(name: str, arguments: dict) -> dict:
            raise RuntimeError("OpenAI TTS network error: Network is unreachable")

        result = await run_scenario(
            "tts-net", dispatch=raise_dispatch, scenarios_dir=sd
        )
        step = result["steps"][0]
        assert step["status"] == "unconfigured"
        assert "TTS" in step["detail"]

    async def test_connect_error_classified_unconfigured(
        self, tmp_path: Path
    ) -> None:
        """An httpx connection error raised from dispatch is classified as
        unconfigured, not failed (#157)."""
        sd = self._write_scenario(
            tmp_path,
            "connect-err",
            "name: connect-err\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: http_tool\n    arguments: {}\n",
        )

        async def raise_dispatch(name: str, arguments: dict) -> dict:
            raise httpx.ConnectError("connection refused")

        result = await run_scenario(
            "connect-err", dispatch=raise_dispatch, scenarios_dir=sd
        )
        step = result["steps"][0]
        assert step["status"] == "unconfigured"
        assert "connect" in step["detail"].lower()

    async def test_other_exception_still_failed(self, tmp_path: Path) -> None:
        """BACKWARD-COMPAT GUARD: exceptions that are NOT an environment
        prereq gap keep the historic 'failed' classification (#157)."""
        sd = self._write_scenario(
            tmp_path,
            "generic-boom",
            "name: generic-boom\ndescription: Test\nsteps:\n"
            "  - name: step\n    tool: boom_tool\n    arguments: {}\n",
        )

        async def raise_dispatch(name: str, arguments: dict) -> dict:
            raise RuntimeError("boom")

        result = await run_scenario(
            "generic-boom", dispatch=raise_dispatch, scenarios_dir=sd
        )
        step = result["steps"][0]
        assert step["status"] == "failed"  # NOT unconfigured
        assert "dispatch exception" in step["detail"]
        assert result["status"] == "failed"


class TestRunScenarioCliHttp:
    """run_scenario tests for the cli/http step kinds (real execution)."""

    CLI_SCENARIO_YAML = """\
name: cli-scenario
description: "CLI execution scenario"
category: test
requires_env: []
steps:
  - name: "echo success"
    kind: cli
    command: "echo validation-works"
    expect:
      success: true
      exit_code: 0
      stdout_has: ["validation-works"]

  - name: "exit code check"
    kind: cli
    command: "exit 3"
    expect:
      success: false
"""

    HTTP_SCENARIO_YAML = """\
name: http-scenario
description: "HTTP execution scenario"
category: test
requires_env: []
steps:
  - name: "example.com reachable"
    kind: http
    method: GET
    url: "https://example.com"
    expect:
      success: true
      status_code: 200
"""

    HTTP_JSON_SCENARIO_YAML = """\
name: http-json-scenario
description: "HTTP JSON body assertion"
category: test
requires_env: []
steps:
  - name: "jsonplaceholder returns json"
    kind: http
    method: GET
    url: "https://jsonplaceholder.typicode.com/todos/1"
    expect:
      success: true
      status_code: 200
      json_has: ["userId", "id", "title"]
"""

    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir(exist_ok=True)
        p = sd / f"{name}.yaml"
        p.write_text(content, encoding="utf-8")
        return sd

    async def test_cli_success_and_exit_code(self, tmp_path: Path) -> None:
        sd = self._write(tmp_path, "cli-scenario", self.CLI_SCENARIO_YAML)
        result = await run_scenario("cli-scenario", dispatch=None, scenarios_dir=sd)
        assert result["status"] == "passed"
        assert result["summary"]["passed"] == 2

    async def test_cli_missing_command_raises(self, tmp_path: Path) -> None:
        yaml_text = "name: bad\ndescription: T\nsteps:\n  - name: s\n    kind: cli\n"
        sd = self._write(tmp_path, "bad", yaml_text)
        with pytest.raises(ValueError, match="kind=cli.*'command'"):
            load_scenarios(sd)

    async def test_http_success(self, tmp_path: Path) -> None:
        sd = self._write(tmp_path, "http-scenario", self.HTTP_SCENARIO_YAML)
        result = await run_scenario("http-scenario", dispatch=None, scenarios_dir=sd)
        assert result["status"] == "passed"
        assert result["summary"]["passed"] == 1

    async def test_http_json_assert(self, tmp_path: Path) -> None:
        sd = self._write(tmp_path, "http-json-scenario", self.HTTP_JSON_SCENARIO_YAML)
        result = await run_scenario("http-json-scenario", dispatch=None, scenarios_dir=sd)
        assert result["status"] == "passed"
        assert result["summary"]["passed"] == 1

    async def test_http_missing_url_raises(self, tmp_path: Path) -> None:
        sd = self._write(
            tmp_path, "badhttp",
            "name: badhttp\ndescription: T\nsteps:\n"
            "  - name: s\n    kind: http\n    method: GET\n",
        )
        with pytest.raises(ValueError, match="kind=http.*'url'"):
            load_scenarios(sd)


class TestRunScenarioCleanupSteps:
    """run_scenario tests for the cleanup_steps contract: always-run,
    best-effort, verdict-neutral cleanup of scenario-created state."""

    CLEANUP_SCENARIO_YAML = """\
name: cleanup-scenario
description: "Cleanup-steps scenario"
category: test
requires_env: []
steps:
  - name: "main pass step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
cleanup_steps:
  - name: "cleanup step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
"""

    FAILING_CLEANUP_SCENARIO_YAML = """\
name: cleanup-fail-scenario
description: "Cleanup-steps scenario with failing main step"
category: test
requires_env: []
steps:
  - name: "main fail step"
    tool: fake_error
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
cleanup_steps:
  - name: "cleanup step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
"""

    FAILING_CLEANUP_STEP_YAML = """\
name: cleanup-bad-step-scenario
description: "Cleanup-steps scenario with failing cleanup step"
category: test
requires_env: []
steps:
  - name: "main pass step"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
cleanup_steps:
  - name: "cleanup fail step"
    tool: fake_error
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
"""

    ENV_GATED_CLEANUP_YAML = """\
name: env-gated-cleanup
description: "Env-gated scenario with cleanup"
category: test
requires_env: ["MISSING_VAR_XYZ"]
steps:
  - name: "should report unconfigured"
    tool: health_check
    arguments: {}
cleanup_steps:
  - name: "cleanup must not run"
    tool: fake_tool
    arguments: {}
"""

    @pytest.fixture
    def cleanup_scenario_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "cleanup-scenario.yaml").write_text(
            self.CLEANUP_SCENARIO_YAML, encoding="utf-8"
        )
        (sd / "cleanup-fail-scenario.yaml").write_text(
            self.FAILING_CLEANUP_SCENARIO_YAML, encoding="utf-8"
        )
        (sd / "cleanup-bad-step-scenario.yaml").write_text(
            self.FAILING_CLEANUP_STEP_YAML, encoding="utf-8"
        )
        (sd / "env-gated-cleanup.yaml").write_text(
            self.ENV_GATED_CLEANUP_YAML, encoding="utf-8"
        )
        return sd

    @pytest.fixture
    def cleanup_calls(self) -> list[str]:
        return []

    async def _fake_dispatch(self, name: str, arguments: dict) -> dict:
        if name == "fake_tool":
            return {"success": True, "data": {"result": "ok"}}
        if name == "fake_error":
            return {"success": False, "error": {"code": "Timeout", "message": "timeout"}}
        return {"success": True, "data": {}}

    async def _tracking_dispatch(
        self, name: str, arguments: dict, cleanup_calls: list[str]
    ) -> dict:
        cleanup_calls.append(name)
        return await self._fake_dispatch(name, arguments)

    async def test_cleanup_runs_and_is_reported(
        self, cleanup_scenario_dir: Path
    ) -> None:
        """Cleanup steps run after a passing scenario and are reported."""
        result = await run_scenario(
            "cleanup-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=cleanup_scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["summary"]["passed"] == 1
        assert "cleanup" in result
        assert result["cleanup"]["summary"]["passed"] == 1
        assert result["cleanup"]["summary"]["total"] == 1
        assert result["cleanup"]["steps"][0]["status"] == "passed"

    async def test_cleanup_runs_after_main_failure(
        self, cleanup_scenario_dir: Path
    ) -> None:
        """Cleanup runs even when a main step failed (state may exist)."""
        result = await run_scenario(
            "cleanup-fail-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=cleanup_scenario_dir,
        )
        assert result["status"] == "failed"
        assert result["summary"]["failed"] == 1
        assert "cleanup" in result
        assert result["cleanup"]["summary"]["passed"] == 1

    async def test_cleanup_failure_does_not_flip_status(
        self, cleanup_scenario_dir: Path
    ) -> None:
        """A failing cleanup step is reported but never flips scenario status."""
        result = await run_scenario(
            "cleanup-bad-step-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=cleanup_scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["summary"]["failed"] == 0
        assert "cleanup" in result
        assert result["cleanup"]["summary"]["failed"] == 1
        assert result["cleanup"]["steps"][0]["status"] == "failed"

    async def test_cleanup_runs_on_subset_run(
        self, cleanup_scenario_dir: Path, cleanup_calls: list[str]
    ) -> None:
        """steps=[1] still triggers cleanup (partial runs create state too)."""
        async def dispatch(name: str, arguments: dict) -> dict:
            return await self._tracking_dispatch(name, arguments, cleanup_calls)

        result = await run_scenario(
            "cleanup-scenario",
            dispatch=dispatch,
            steps=[1],
            scenarios_dir=cleanup_scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["summary"]["total"] == 1
        assert "cleanup" in result
        assert result["cleanup"]["summary"]["total"] == 1
        assert cleanup_calls.count("fake_tool") == 2  # main + cleanup

    async def test_cleanup_skipped_when_unconfigured(
        self, cleanup_scenario_dir: Path
    ) -> None:
        """Env-gated early return runs nothing, so cleanup must not run."""
        env_before = os.environ.pop("MISSING_VAR_XYZ", None)
        try:
            result = await run_scenario(
                "env-gated-cleanup",
                dispatch=self._fake_dispatch,
                scenarios_dir=cleanup_scenario_dir,
            )
            assert result["status"] == "unconfigured"
            assert "cleanup" not in result
        finally:
            if env_before is not None:
                os.environ["MISSING_VAR_XYZ"] = env_before

    async def test_cleanup_step_missing_tool_raises(
        self, tmp_path: Path
    ) -> None:
        """cleanup_steps are schema-validated like steps."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad-cleanup.yaml").write_text(
            "name: bad-cleanup\ndescription: T\nsteps:\n"
            "  - name: s\n    tool: fake_tool\n"
            "cleanup_steps:\n  - name: no-tool-step\n",
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="cleanup_step\\[0\\].*'tool'"
        ):
            load_scenarios(sd)

    async def test_cleanup_cli_step_validates_command(
        self, tmp_path: Path
    ) -> None:
        """kind=cli cleanup steps require a command."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad-cli-cleanup.yaml").write_text(
            "name: bad-cli-cleanup\ndescription: T\nsteps:\n"
            "  - name: s\n    tool: fake_tool\n"
            "cleanup_steps:\n  - name: no-command\n    kind: cli\n",
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="cleanup_step\\[0\\].*kind=cli.*'command'"
        ):
            load_scenarios(sd)


class TestRunScenarioRecovery:
    """Issue #138: per-step recovery_steps + scenario-level partial policy.

    A failed primary step (assertion mismatch, dispatch exception, or
    timeout) runs its recovery_steps; a recovery success is counted as
    ``recovered`` (never a plain failure), and ``min_passing``/``pass_ratio``
    turn partial success into a scenario pass.
    """

    RECOVERY_SCENARIO_YAML = """\
name: recovery-scenario
description: "Recovery-steps scenario"
category: test
requires_env: []
steps:
  - name: "primary fails, recovery succeeds"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
    recovery_steps:
      - name: "recovery pass step"
        tool: fake_tool
        arguments: {}
        expect:
          success: true
          data_has: ["result"]

  - name: "primary fails, recovery also fails"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
    recovery_steps:
      - name: "recovery fail step"
        tool: fake_error
        arguments: {}
        expect:
          success: true
          data_has: ["result"]

  - name: "passing step never triggers recovery"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]
    recovery_steps:
      - name: "recovery must not run"
        tool: fake_tool
        arguments: {}
        expect:
          success: true
"""

    PARTIAL_SCENARIO_YAML = """\
name: partial-recovery-scenario
description: "Partial-pass policy scenario"
category: test
requires_env: []
min_passing: 2
steps:
  - name: "primary fails, recovery succeeds"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
    recovery_steps:
      - name: "recovery pass"
        tool: fake_tool
        arguments: {}
        expect:
          success: true

  - name: "plain pass"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]

  - name: "unrecovered failure"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
"""

    STRICT_PARTIAL_SCENARIO_YAML = """\
name: strict-partial-recovery-scenario
description: "Strict partial-pass policy scenario"
category: test
requires_env: []
min_passing: 3
steps:
  - name: "primary fails, recovery succeeds"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
    recovery_steps:
      - name: "recovery pass"
        tool: fake_tool
        arguments: {}
        expect:
          success: true

  - name: "plain pass"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      data_has: ["result"]

  - name: "unrecovered failure"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
"""

    RATIO_SCENARIO_YAML = """\
name: ratio-recovery-scenario
description: "Pass-ratio policy scenario"
category: test
requires_env: []
pass_ratio: 0.5
steps:
  - name: "primary fails, recovery succeeds"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
    recovery_steps:
      - name: "recovery pass"
        tool: fake_tool
        arguments: {}
        expect:
          success: true

  - name: "unrecovered failure"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
"""

    RATIO_STRICT_SCENARIO_YAML = """\
name: ratio-strict-recovery-scenario
description: "Strict pass-ratio policy scenario"
category: test
requires_env: []
pass_ratio: 0.9
steps:
  - name: "primary fails, recovery succeeds"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
    recovery_steps:
      - name: "recovery pass"
        tool: fake_tool
        arguments: {}
        expect:
          success: true

  - name: "unrecovered failure"
    tool: flaky_tool
    arguments: {}
    expect:
      success: true
"""

    TIMEOUT_RECOVERY_SCENARIO_YAML = """\
name: timeout-recovery-scenario
description: "Timeout-triggered recovery scenario"
category: test
requires_env: []
steps:
  - name: "hanging primary triggers recovery"
    tool: slow_tool
    arguments: {}
    expect:
      success: true
    recovery_steps:
      - name: "recovery after timeout"
        tool: fake_tool
        arguments: {}
        expect:
          success: true
          data_has: ["result"]
"""

    @pytest.fixture
    def recovery_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        files = {
            "recovery-scenario.yaml": self.RECOVERY_SCENARIO_YAML,
            "partial-recovery-scenario.yaml": self.PARTIAL_SCENARIO_YAML,
            "strict-partial-recovery-scenario.yaml": self.STRICT_PARTIAL_SCENARIO_YAML,
            "ratio-recovery-scenario.yaml": self.RATIO_SCENARIO_YAML,
            "ratio-strict-recovery-scenario.yaml": self.RATIO_STRICT_SCENARIO_YAML,
            "timeout-recovery-scenario.yaml": self.TIMEOUT_RECOVERY_SCENARIO_YAML,
        }
        for name, content in files.items():
            (sd / name).write_text(content, encoding="utf-8")
        return sd

    async def _fake_dispatch(self, name: str, arguments: dict) -> dict:
        if name == "fake_tool":
            return {"success": True, "data": {"result": "ok"}}
        if name == "fake_error":
            return {"success": False, "error": {"code": "Timeout", "message": "timeout"}}
        if name == "flaky_tool":
            return {"success": False, "error": {"code": "SourceUnreachable", "message": "boom"}}
        if name == "slow_tool":
            await asyncio.sleep(5)
            return {"success": True, "data": {}}
        return {"success": True, "data": {}}

    async def test_recovery_step_runs_and_expect_is_evaluated(
        self, recovery_dir: Path
    ) -> None:
        """A failed primary runs its recovery step; the recovery step's own
        expect assertions are evaluated (data_has on fake_tool passes)."""
        result = await run_scenario(
            "recovery-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=recovery_dir,
        )
        step = result["steps"][0]
        assert step["status"] == "failed"  # primary's own assertion failed
        assert step["recovered"] is True
        assert step["recovery_status"] == "passed"
        assert len(step["recovery"]) == 1
        assert step["recovery"][0]["status"] == "passed"
        assert step["recovery"][0]["name"] == "recovery pass step"
        # Recovery is counted separately from failed.
        assert result["summary"]["recovered"] == 1
        assert result["summary"]["failed"] == 0
        # No unrecovered failure → default all-or-nothing still passes.
        assert result["status"] == "passed"

    async def test_recovery_failure_fails_scenario(self, recovery_dir: Path) -> None:
        """When the recovery step's own expect fails, the primary stays a
        plain failure and the scenario fails."""
        result = await run_scenario(
            "recovery-scenario",
            dispatch=self._fake_dispatch,
            steps=[2],
            scenarios_dir=recovery_dir,
        )
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert step["recovered"] is False
        assert step["recovery_status"] == "failed"
        assert step["recovery"][0]["status"] == "failed"
        # The recovery step's own expect was evaluated and failed on success.
        assert "expected success=True, got success=False" in step["recovery"][0].get("detail", "")
        assert result["summary"]["failed"] == 1
        assert result["summary"]["recovered"] == 0
        assert result["status"] == "failed"

    async def test_recovery_skipped_when_primary_passes(self, recovery_dir: Path) -> None:
        """A passing primary never runs its recovery steps."""
        result = await run_scenario(
            "recovery-scenario",
            dispatch=self._fake_dispatch,
            steps=[3],
            scenarios_dir=recovery_dir,
        )
        step = result["steps"][0]
        assert step["status"] == "passed"
        assert "recovered" not in step
        assert "recovery" not in step
        assert result["summary"]["recovered"] == 0
        assert result["status"] == "passed"

    async def test_mixed_scenario_counts_recovered_not_failed(
        self, recovery_dir: Path
    ) -> None:
        """Recovered + failed mix: summary separates them; one unrecovered
        failure still fails the default all-or-nothing policy."""
        result = await run_scenario(
            "recovery-scenario",
            dispatch=self._fake_dispatch,
            steps=[1, 2],
            scenarios_dir=recovery_dir,
        )
        assert result["summary"]["recovered"] == 1
        assert result["summary"]["failed"] == 1
        assert result["status"] == "failed"

    async def test_partial_policy_min_passing_satisfied(self, recovery_dir: Path) -> None:
        """min_passing satisfied → scenario passes even with an unrecovered
        failure (3/7-sources-OK style partial success is not an overall fail)."""
        result = await run_scenario(
            "partial-recovery-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=recovery_dir,
        )
        assert result["summary"] == {
            "passed": 1, "failed": 1, "unconfigured": 0,
            "recovered": 1, "total": 3,
        }
        assert result["status"] == "passed"

    async def test_partial_policy_min_passing_not_met(self, recovery_dir: Path) -> None:
        """min_passing not met → scenario fails."""
        result = await run_scenario(
            "strict-partial-recovery-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=recovery_dir,
        )
        assert result["summary"]["recovered"] == 1
        assert result["summary"]["passed"] == 1
        assert result["summary"]["failed"] == 1
        assert result["status"] == "failed"

    async def test_partial_policy_pass_ratio(self, recovery_dir: Path) -> None:
        """pass_ratio 0.5 with 1 recovered of 2 → pass; 0.9 → fail."""
        result = await run_scenario(
            "ratio-recovery-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=recovery_dir,
        )
        assert result["summary"]["recovered"] == 1
        assert result["status"] == "passed"

        strict = await run_scenario(
            "ratio-strict-recovery-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=recovery_dir,
        )
        assert strict["status"] == "failed"

    async def test_recovery_triggered_by_timeout(self, recovery_dir: Path) -> None:
        """A per-step timeout (simulated outage) triggers recovery too."""
        result = await run_scenario(
            "timeout-recovery-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=recovery_dir,
            timeout=0.1,
        )
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert "timed out" in step["detail"]
        assert step["recovered"] is True
        assert step["recovery"][0]["status"] == "passed"
        assert result["summary"]["recovered"] == 1
        assert result["status"] == "passed"

    async def test_recovery_schema_validation(self, tmp_path: Path) -> None:
        """recovery_steps must be a list of valid steps (same schema)."""
        bad_cases = {
            "bad-recovery-list.yaml": (
                "name: bad-recovery-list\ndescription: T\nsteps:\n"
                "  - name: s\n    tool: fake_tool\n"
                "    recovery_steps: {}\n",
                "recovery_steps.*must be a list",
            ),
            "bad-recovery-tool.yaml": (
                "name: bad-recovery-tool\ndescription: T\nsteps:\n"
                "  - name: s\n    tool: fake_tool\n"
                "    recovery_steps:\n      - name: no-tool-step\n",
                r"recovery_steps\[0\].*'tool'",
            ),
            "bad-min-passing.yaml": (
                "name: bad-min-passing\ndescription: T\nmin_passing: 0\n"
                "steps:\n  - name: s\n    tool: fake_tool\n",
                "min_passing.*positive integer",
            ),
            "bad-pass-ratio.yaml": (
                "name: bad-pass-ratio\ndescription: T\npass_ratio: 2.5\n"
                "steps:\n  - name: s\n    tool: fake_tool\n",
                "pass_ratio.*\\(0, 1\\]",
            ),
        }
        for i, (file_name, (content, pattern)) in enumerate(bad_cases.items()):
            sd = tmp_path / f"scenarios{i}"
            sd.mkdir()
            (sd / file_name).write_text(content, encoding="utf-8")
            with pytest.raises(ValueError, match=pattern):
                load_scenarios(sd)

    def test_diff_populates_recovered_bucket(self, tmp_path) -> None:
        """A step failed in base but passing-with-recovery in head shows up
        in the recovered bucket — the previously-dead wiring (issue #138)."""
        def result(status: str, steps: list[dict]) -> dict:
            return {
                "scenario": "rec", "status": status,
                "summary": {"passed": 0, "failed": 1, "unconfigured": 0,
                            "recovered": 0, "total": 1},
                "steps": steps,
            }

        base = save_scenario_results(
            [result("failed", [{"name": "collect", "tool": "test_source",
                                "status": "failed"}])],
            runs_dir=tmp_path,
        )
        head = save_scenario_results(
            [result("passed", [{"name": "collect", "tool": "test_source",
                                "status": "failed", "recovered": True,
                                "recovery_status": "passed",
                                "recovery": [{"name": "fallback", "tool": "echo",
                                              "status": "passed"}]}])],
            runs_dir=tmp_path,
        )
        diff = diff_scenario_runs(base, head)
        assert diff["recovered"] == ["rec"]
        assert diff["recovered_steps"] == {"rec": ["collect"]}
        # Not double-counted as a new pass.
        assert diff["new_passes"] == []
        assert diff["head_passed"] == 1

    def test_diff_recovered_requires_base_failure(self, tmp_path) -> None:
        """Head-passed-with-recovery against a base that was not failed is a
        new pass, not a recovery."""
        def result(status: str, steps: list[dict]) -> dict:
            return {
                "scenario": "rec", "status": status,
                "summary": {"passed": 0, "failed": 1, "unconfigured": 0,
                            "recovered": 0, "total": 1},
                "steps": steps,
            }

        base = save_scenario_results([result("passed", [])], runs_dir=tmp_path)
        head = save_scenario_results(
            [result("passed", [{"name": "collect", "status": "failed",
                                "recovered": True}])],
            runs_dir=tmp_path,
        )
        diff = diff_scenario_runs(base, head)
        assert diff["recovered"] == []
        assert diff["new_passes"] == []

    def test_diff_without_recovery_data_unchanged(self, tmp_path) -> None:
        """Diff of runs without recovery metadata behaves as before."""
        base = save_scenario_results([
            {"scenario": "a", "status": "passed",
             "summary": {"passed": 1, "failed": 0, "unconfigured": 0,
                         "recovered": 0, "total": 1}},
            {"scenario": "b", "status": "failed",
             "summary": {"passed": 0, "failed": 1, "unconfigured": 0,
                         "recovered": 0, "total": 1}},
        ], runs_dir=tmp_path)
        head = save_scenario_results([
            {"scenario": "a", "status": "passed",
             "summary": {"passed": 1, "failed": 0, "unconfigured": 0,
                         "recovered": 0, "total": 1}},
            {"scenario": "b", "status": "passed",
             "summary": {"passed": 1, "failed": 0, "unconfigured": 0,
                         "recovered": 0, "total": 1}},
        ], runs_dir=tmp_path)
        diff = diff_scenario_runs(base, head)
        assert sorted(diff["new_passes"]) == ["b"]
        assert diff["recovered"] == []
        assert diff["recovered_steps"] == {}
        assert diff["unchanged"] == 1


class TestRunScenarioRecoveryPackaged:
    """Issue #138: the packaged recovery scenarios execute end-to-end via the
    real MCP dispatch and pass on partial/recovered accounting."""

    @pytest.mark.asyncio
    async def test_collect_failure_recovery_via_dispatch(self) -> None:
        """The packaged collect-failure-recovery scenario passes with
        recovered accounting via the MCP dispatch handler."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="run_validation_scenario",
                arguments={"scenario": "collect-failure-recovery"},
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is True
        assert data["data"]["status"] == "passed"
        assert data["data"]["summary"]["recovered"] == 1
        assert data["data"]["summary"]["failed"] == 0
        primary = data["data"]["steps"][0]
        assert primary["recovered"] is True
        assert primary["recovery_status"] == "passed"
        assert primary["recovery"][0]["status"] == "passed"

    @pytest.mark.asyncio
    async def test_llm_failure_recovery_via_dispatch(self) -> None:
        """The packaged llm-failure-recovery scenario passes whether or not an
        LLM key is present: without a key the LLM-required primary fails and
        the fallback recovery recovers it (min_passing 2 still met)."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="run_validation_scenario",
                arguments={"scenario": "llm-failure-recovery"},
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is True
        assert data["data"]["status"] == "passed"
        # Without a key: 1 recovered + 1 passed.  With a key: 2 passed.
        assert data["data"]["summary"]["recovered"] + data["data"]["summary"]["passed"] == 2
        assert data["data"]["summary"]["failed"] == 0


# ============================================================================
# Integration tests: MCP server dispatch
# ============================================================================


class TestValidationToolsDispatch:
    """Integration tests exercising the tools through the MCP app's
    request handler (matching the pattern used in test_mcp_server.py)."""

    @pytest.mark.asyncio
    async def test_list_validation_scenarios_via_dispatch(self, monkeypatch) -> None:
        """Should return ≥6 scenarios via the MCP dispatch handler."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="list_validation_scenarios", arguments={}
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is True
        assert data["data"]["count"] >= 6
        assert len(data["data"]["scenarios"]) >= 6

        for sc in data["data"]["scenarios"]:
            assert "name" in sc
            assert "description" in sc
            assert "category" in sc
            assert "step_count" in sc

    @pytest.mark.asyncio
    async def test_run_system_health_via_dispatch(self, monkeypatch) -> None:
        """system-health scenario should pass via MCP dispatch."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="run_validation_scenario",
                arguments={"scenario": "system-health"},
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is True
        assert data["data"]["status"] == "passed"
        assert data["data"]["summary"]["passed"] == 3
        assert data["data"]["summary"]["failed"] == 0

    @pytest.mark.asyncio
    async def test_run_llm_gated_reports_unconfigured_without_key(
        self, monkeypatch
    ) -> None:
        """llm-gated scenario should report 'unconfigured' when
        AUTOINFO_LLM_API_KEY is absent — never silently skipped."""
        # Ensure the key is not set for this test
        monkeypatch.delenv("AUTOINFO_LLM_API_KEY", raising=False)

        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="run_validation_scenario",
                arguments={"scenario": "llm-gated"},
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is True
        # Without a key this must surface as unconfigured (real environment
        # check), NOT as a pass or a silent skip.
        assert data["data"]["status"] == "unconfigured"
        # llm-gated has 3 steps (classify_cefr, suggest_keywords, cefr_batch)
        assert data["data"]["summary"]["unconfigured"] == 3

    @pytest.mark.asyncio
    async def test_unknown_scenario_via_dispatch(self) -> None:
        """Unknown scenario through dispatch should return a proper error
        envelope (not a raw traceback)."""
        handler = mcp_server.app.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="run_validation_scenario",
                arguments={"scenario": "nonexistent-scenario-xyz"},
            ),
        )
        result = await handler(request)
        call_result = result.root
        data = json.loads(call_result.content[0].text)

        assert data["success"] is False
        assert data["error"]["code"] == "ValidationError"
        assert "nonexistent-scenario-xyz" in data["error"]["message"]


# ============================================================================
# Unit tests: validation run persistence + cross-run diff (fixes #129 P0-3)
# ============================================================================


class TestValidationRunPersistence:
    """save_scenario_results / list_validation_runs / load_scenario_results /
    diff_scenario_runs regression coverage."""

    def _result(self, status: str, total: int = 1) -> dict:
        passed = 1 if status == "passed" else 0
        return {"scenario": "unused", "status": status,
                "summary": {"passed": passed, "failed": total - passed,
                            "unconfigured": 0, "total": total}}

    def test_save_writes_scenarios_json_and_latest_pointer(self, tmp_path) -> None:
        run_dir = save_scenario_results(
            [{"scenario": "a", "status": "passed", "summary": {}}], runs_dir=tmp_path
        )
        assert run_dir.is_dir()
        assert (run_dir / "scenarios.json").exists()
        assert (tmp_path / "latest.txt").read_text().strip() == run_dir.name

    def test_list_returns_newest_first(self, tmp_path) -> None:
        save_scenario_results([self._result("passed")], runs_dir=tmp_path)
        save_scenario_results([self._result("failed")], runs_dir=tmp_path)
        runs = list_validation_runs(tmp_path)
        assert len(runs) == 2
        # latest.txt points at the most recent run, and list is newest-first.
        assert (tmp_path / "latest.txt").read_text().strip() == runs[0].name

    def test_load_roundtrip(self, tmp_path) -> None:
        run_dir = save_scenario_results(
            [{"scenario": "a", "status": "passed", "summary": {"passed": 2, "total": 2}}],
            runs_dir=tmp_path,
        )
        loaded = load_scenario_results(run_dir)
        assert loaded is not None
        assert loaded["scenarios"][0]["scenario"] == "a"

    def test_diff_detects_regression_and_new_pass(self, tmp_path) -> None:
        base = save_scenario_results([
            {"scenario": "a", "status": "passed", "summary": {}},
            {"scenario": "b", "status": "failed", "summary": {}},
            {"scenario": "c", "status": "passed", "summary": {}},
        ], runs_dir=tmp_path)
        head = save_scenario_results([
            {"scenario": "a", "status": "passed", "summary": {}},
            {"scenario": "b", "status": "passed", "summary": {}},
            {"scenario": "c", "status": "failed", "summary": {}},
        ], runs_dir=tmp_path)
        diff = diff_scenario_runs(base, head)
        assert sorted(diff["regressed"]) == ["c"]
        assert sorted(diff["new_passes"]) == ["b"]
        assert diff["head_passed"] == 2
        assert diff["head_failed"] == 1


# ============================================================================
# Unit tests: run_scenario per-step timeout (issue #134, engine part)
# ============================================================================


class TestRunScenarioTimeout:
    """Per-step timeout enforcement in run_scenario (issue #134)."""

    SCENARIO_YAML = """\
name: timeout-scenario
description: "Scenario with a hang-prone step"
category: test
requires_env: []
steps:
  - name: "fast step"
    tool: fast_tool
    arguments: {}
    expect:
      success: true

  - name: "slow step"
    tool: slow_tool
    arguments: {}
    expect:
      success: true

  - name: "post-hang step"
    tool: fast_tool
    arguments: {}
    expect:
      success: true
"""

    CLEANUP_SCENARIO_YAML = """\
name: timeout-cleanup-scenario
description: "Scenario whose cleanup step hangs"
category: test
requires_env: []
steps:
  - name: "fast step"
    tool: fast_tool
    arguments: {}
    expect:
      success: true
cleanup_steps:
  - name: "slow cleanup step"
    tool: slow_tool
    arguments: {}
    expect:
      success: true
"""

    @pytest.fixture
    def scenario_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "timeout-scenario.yaml").write_text(
            self.SCENARIO_YAML, encoding="utf-8"
        )
        (sd / "timeout-cleanup-scenario.yaml").write_text(
            self.CLEANUP_SCENARIO_YAML, encoding="utf-8"
        )
        return sd

    async def _fake_dispatch(self, name: str, arguments: dict) -> dict:
        """Hang far beyond the 0.1s test timeout for slow_tool; pass otherwise."""
        if name == "slow_tool":
            await asyncio.sleep(5)
        return {"success": True, "data": {"result": "ok"}}

    async def test_hanging_step_times_out_and_fails_scenario(
        self, scenario_dir: Path
    ) -> None:
        """A step exceeding the per-step timeout reports failed with 'timed out'."""
        result = await run_scenario(
            "timeout-scenario",
            dispatch=self._fake_dispatch,
            steps=[2],
            scenarios_dir=scenario_dir,
            timeout=0.1,
        )
        assert result["status"] == "failed"
        assert result["summary"]["failed"] == 1
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert "timed out" in step["detail"]
        assert "0.1" in step["detail"]

    async def test_cleanup_timeout_reported_but_does_not_flip_status(
        self, scenario_dir: Path
    ) -> None:
        """A timed-out cleanup step is reported but never flips scenario status."""
        result = await run_scenario(
            "timeout-cleanup-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=scenario_dir,
            timeout=0.1,
        )
        assert result["status"] == "passed"
        assert result["summary"]["failed"] == 0
        assert "cleanup" in result
        assert result["cleanup"]["summary"]["failed"] == 1
        cleanup_step = result["cleanup"]["steps"][0]
        assert cleanup_step["status"] == "failed"
        assert "timed out" in cleanup_step["detail"]

    async def test_default_timeout_backward_compatible(self, scenario_dir: Path) -> None:
        """Without a timeout arg, a fast step passes as before."""
        result = await run_scenario(
            "timeout-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=scenario_dir,
        )
        assert result["status"] == "passed"
        assert result["steps"][0]["status"] == "passed"

    async def test_hang_on_middle_step_loop_continues(self, scenario_dir: Path) -> None:
        """Timeout is per-step: a hang on step 2 fails it but steps 1 and 3 still run."""
        calls: list[str] = []

        async def tracking_dispatch(name: str, arguments: dict) -> dict:
            calls.append(name)
            if name == "slow_tool":
                await asyncio.sleep(5)
            return {"success": True, "data": {"result": "ok"}}

        result = await run_scenario(
            "timeout-scenario",
            dispatch=tracking_dispatch,
            scenarios_dir=scenario_dir,
            timeout=0.1,
        )
        assert result["status"] == "failed"
        assert calls == ["fast_tool", "slow_tool", "fast_tool"]
        assert result["steps"][0]["status"] == "passed"
        assert result["steps"][1]["status"] == "failed"
        assert "timed out" in result["steps"][1]["detail"]
        assert result["steps"][2]["status"] == "passed"


class TestMCPRunValidationScenarioTimeout:
    """E4: MCP run_validation_scenario handler passes timeout to run_scenario."""

    @staticmethod
    def _mock_result() -> dict[str, Any]:
        return {
            "status": "passed",
            "steps": [],
            "counts": {"passed": 0, "failed": 0, "unconfigured": 0},
        }

    @pytest.mark.asyncio
    async def test_handler_passes_timeout_to_run_scenario(self) -> None:
        """timeout param forwarded to run_scenario."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "autoinfo.mcp.validation.run_scenario",
            new_callable=AsyncMock,
            return_value=self._mock_result(),
        ) as mock_rs:
            from autoinfo.mcp.server import _handle_run_validation_scenario

            result = await _handle_run_validation_scenario(
                scenario="test-scene", timeout=60.0
            )
            mock_rs.assert_called_once()
            call_kwargs = mock_rs.call_args.kwargs
            assert call_kwargs.get("timeout") == 60.0
            assert result["status"] == "passed"

    @pytest.mark.asyncio
    async def test_handler_default_timeout(self) -> None:
        """Default timeout is 180.0."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "autoinfo.mcp.validation.run_scenario",
            new_callable=AsyncMock,
            return_value=self._mock_result(),
        ) as mock_rs:
            from autoinfo.mcp.server import _handle_run_validation_scenario

            result = await _handle_run_validation_scenario(scenario="test-scene")
            mock_rs.assert_called_once()
            call_kwargs = mock_rs.call_args.kwargs
            assert call_kwargs.get("timeout") == 180.0
            assert result["status"] == "passed"


# ============================================================================
# Unit tests: per-step execution trace (issue #139)
# ============================================================================


class TestStepExecutionTrace:
    """Issue #139: every step result carries step_index / duration /
    arguments / trace_id, and llm_assert steps embed judge observability
    (llm_meta) while keeping the top-level llm_reason."""

    TRACE_SCENARIO_YAML = """\
name: trace-scenario
description: "Trace-field scenario"
category: test
requires_env: []
steps:
  - name: "pass with args"
    tool: fake_tool
    arguments: {limit: 5, q: "alpha"}
    expect:
      success: true
      data_has: ["result"]

  - name: "failing step"
    tool: fake_error
    arguments: {}
    expect:
      success: true
"""

    LLM_TRACE_SCENARIO_YAML = """\
name: llm-trace-scenario
description: "LLM trace-field scenario"
category: test
requires_env: []
steps:
  - name: "llm pass with meta"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      llm_assert: "Is the result ok?"

  - name: "llm fail with meta"
    tool: fake_tool
    arguments: {}
    expect:
      success: true
      llm_assert: "Is the result bad?"
"""

    @pytest.fixture
    def trace_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "trace-scenario.yaml").write_text(
            self.TRACE_SCENARIO_YAML, encoding="utf-8"
        )
        (sd / "llm-trace-scenario.yaml").write_text(
            self.LLM_TRACE_SCENARIO_YAML, encoding="utf-8"
        )
        (sd / "env-gated.yaml").write_text(
            "name: env-gated\ndescription: T\ncategory: test\n"
            "requires_env: [MISSING_VAR_XYZ]\n"
            "steps:\n  - name: gated\n    tool: health_check\n    arguments: {}\n",
            encoding="utf-8",
        )
        return sd

    async def _fake_dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "fake_tool":
            return {"success": True, "data": {"result": "ok"}}
        if name == "fake_error":
            return {"success": False, "error": {"code": "Timeout", "message": "timeout"}}
        return {"success": True, "data": {}}

    async def test_steps_carry_trace_fields(self, trace_dir: Path) -> None:
        """Every step result carries step_index/duration/arguments/trace_id."""
        result = await run_scenario(
            "trace-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=trace_dir,
        )
        assert result["status"] == "failed"  # step 2 fails
        trace_id = result["trace_id"]
        assert len(trace_id) == 36  # uuid4 string form
        assert len(result["steps"]) == 2
        for i, step in enumerate(result["steps"], start=1):
            assert step["step_index"] == i
            assert isinstance(step["duration"], float)
            assert step["duration"] >= 0.0
            assert step["trace_id"] == trace_id
            # Pre-existing keys are preserved alongside the new fields.
            assert step["name"]
            assert step["tool"]
            assert step["status"]
            assert "detail" in step
        assert result["steps"][0]["arguments"] == {"limit": 5, "q": "alpha"}
        assert result["steps"][1]["arguments"] == {}

    async def test_trace_id_shared_across_steps(self, trace_dir: Path) -> None:
        """One uuid per run, shared by every step and the top-level result."""
        result = await run_scenario(
            "trace-scenario",
            dispatch=self._fake_dispatch,
            scenarios_dir=trace_dir,
        )
        ids = {step["trace_id"] for step in result["steps"]}
        assert ids == {result["trace_id"]}

    async def test_llm_meta_embedded_on_llm_assert_pass(
        self, trace_dir: Path, monkeypatch
    ) -> None:
        """llm_assert PASS path embeds llm_meta while keeping llm_reason."""
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured", lambda: True
        )
        monkeypatch.setattr(
            "autoinfo.mcp.validation._llm_judge",
            lambda assertion, output: {
                "verdict": "PASS",
                "reason": "result is ok",
                "model": "test-model",
                "tokens": {"prompt_tokens": 10, "total_tokens": 20},
                "duration": 0.5,
            },
        )
        result = await run_scenario(
            "llm-trace-scenario",
            dispatch=self._fake_dispatch,
            steps=[1],
            scenarios_dir=trace_dir,
        )
        step = result["steps"][0]
        assert step["status"] == "passed"
        assert step["llm_reason"] == "result is ok"
        assert step["llm_meta"] == {
            "model": "test-model",
            "tokens": {"prompt_tokens": 10, "total_tokens": 20},
            "duration": 0.5,
        }
        assert step["step_index"] == 1
        assert step["trace_id"] == result["trace_id"]

    async def test_llm_meta_embedded_on_llm_assert_fail(
        self, trace_dir: Path, monkeypatch
    ) -> None:
        """llm_assert FAIL path embeds llm_meta alongside llm_reason."""
        monkeypatch.setattr(
            "autoinfo.mcp.validation._is_llm_configured", lambda: True
        )
        monkeypatch.setattr(
            "autoinfo.mcp.validation._llm_judge",
            lambda assertion, output: {
                "verdict": "FAIL",
                "reason": "output is bad",
                "model": "test-model",
                "tokens": {"prompt_tokens": 3, "total_tokens": 9},
                "duration": 0.25,
            },
        )
        result = await run_scenario(
            "llm-trace-scenario",
            dispatch=self._fake_dispatch,
            steps=[2],
            scenarios_dir=trace_dir,
        )
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert step["llm_reason"] == "output is bad"
        assert step["llm_meta"]["model"] == "test-model"
        assert step["llm_meta"]["duration"] == 0.25
        assert step["trace_id"] == result["trace_id"]

    async def test_unconfigured_early_return_carries_trace_fields(
        self, trace_dir: Path
    ) -> None:
        """Env-gated early return decorates its steps with trace fields."""
        env_before = os.environ.pop("MISSING_VAR_XYZ", None)
        try:
            result = await run_scenario(
                "env-gated",
                dispatch=self._fake_dispatch,
                scenarios_dir=trace_dir,
            )
            assert result["status"] == "unconfigured"
            assert result["trace_id"]
            step = result["steps"][0]
            assert step["step_index"] == 1
            assert step["duration"] == 0.0
            assert step["arguments"] == {}
            assert step["trace_id"] == result["trace_id"]
        finally:
            if env_before is not None:
                os.environ["MISSING_VAR_XYZ"] = env_before

    async def test_recovery_steps_carry_trace_fields(self, tmp_path: Path) -> None:
        """Recovery step results carry the primary's step_index + run trace_id,
        and the primary duration includes the recovery execution."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "rec-trace.yaml").write_text(
            "name: rec-trace\ndescription: T\ncategory: test\nrequires_env: []\n"
            "steps:\n"
            "  - name: flaky primary\n    tool: flaky_tool\n    arguments: {retry: 2}\n"
            "    expect:\n      success: true\n"
            "    recovery_steps:\n"
            "      - name: recovery pass\n        tool: fake_tool\n        arguments: {}\n"
            "        expect:\n          success: true\n",
            encoding="utf-8",
        )

        async def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "flaky_tool":
                return {"success": False, "error": {"code": "X", "message": "boom"}}
            return {"success": True, "data": {"result": "ok"}}

        result = await run_scenario(
            "rec-trace",
            dispatch=dispatch,
            scenarios_dir=sd,
        )
        step = result["steps"][0]
        assert step["recovered"] is True
        assert step["step_index"] == 1
        assert step["arguments"] == {"retry": 2}
        assert step["trace_id"] == result["trace_id"]
        rec = step["recovery"][0]
        assert rec["step_index"] == 1
        assert rec["trace_id"] == result["trace_id"]
        assert rec["arguments"] == {}
        assert isinstance(rec["duration"], float)
        # Primary duration covers the recovery execution too.
        assert step["duration"] >= rec["duration"]

    async def test_timeout_step_carries_trace_fields(self, tmp_path: Path) -> None:
        """A timed-out step still carries the per-step trace fields."""
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "slow-trace.yaml").write_text(
            "name: slow-trace\ndescription: T\ncategory: test\nrequires_env: []\n"
            "steps:\n  - name: hang\n    tool: slow_tool\n    arguments: {}\n"
            "    expect:\n      success: true\n",
            encoding="utf-8",
        )

        async def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(5)
            return {"success": True, "data": {}}

        result = await run_scenario(
            "slow-trace",
            dispatch=dispatch,
            scenarios_dir=sd,
            timeout=0.1,
        )
        step = result["steps"][0]
        assert step["status"] == "failed"
        assert "timed out" in step["detail"]
        assert step["step_index"] == 1
        assert isinstance(step["duration"], float)
        assert step["duration"] >= 0.1
        assert step["arguments"] == {}
        assert step["trace_id"] == result["trace_id"]


class TestLLMJudgeObservability:
    """Issue #139: _llm_judge captures model / tokens / duration."""

    @staticmethod
    def _patch_litellm(monkeypatch, *, with_usage: bool = True) -> dict[str, Any]:
        """Install a fake litellm module returning a canned completion."""
        import sys
        import types

        class _FakeUsage:
            prompt_tokens = 10
            total_tokens = 25

        class _FakeMessage:
            content = '{"verdict": "PASS", "reason": "looks good"}'

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeResponse:
            def __init__(self) -> None:
                self.usage = _FakeUsage() if with_usage else None
                self.choices = [_FakeChoice()]

        calls: dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> _FakeResponse:
            calls["model"] = kwargs["model"]
            return _FakeResponse()

        fake_litellm = types.SimpleNamespace(completion=fake_completion)
        monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
        monkeypatch.setattr(
            "autoinfo.mcp.validation._resolve_llm_config",
            lambda: {"model": "test-model", "api_key": "k", "api_base": None},
        )
        return calls

    def test_llm_judge_returns_model_tokens_duration(self, monkeypatch) -> None:
        """Judge result carries model, usage tokens, and wall-clock duration."""
        calls = self._patch_litellm(monkeypatch)
        verdict = validation_mod._llm_judge("assertion", {"data": 1})
        assert verdict["verdict"] == "PASS"
        assert verdict["reason"] == "looks good"
        assert verdict["model"] == "test-model"
        assert verdict["tokens"] == {"prompt_tokens": 10, "total_tokens": 25}
        assert isinstance(verdict["duration"], float)
        assert verdict["duration"] >= 0.0
        assert calls["model"] == "test-model"

    def test_llm_judge_tokens_none_without_usage(self, monkeypatch) -> None:
        """Without usage info the tokens field is None (not a crash)."""
        self._patch_litellm(monkeypatch, with_usage=False)
        verdict = validation_mod._llm_judge("assertion", {"data": 1})
        assert verdict["verdict"] == "PASS"
        assert verdict["tokens"] is None
        assert verdict["model"] == "test-model"


# ============================================================================
# Issue #140: regression scenario fields
# ============================================================================


class TestRegressionScenarios:
    """Regression scenarios carry regression / regression_issue fields."""

    def test_loads_regression_scenarios(self) -> None:
        """load_scenarios picks up regression/ subdir scenarios with new fields."""
        scs = load_scenarios()
        regr = [s for s in scs if s.get("regression")]
        assert len(regr) >= 5, f"Expected ≥5 regression scenarios, got {len(regr)}"
        for s in regr:
            assert s["regression"] is True
            assert "regression_issue" in s
            assert s["regression_issue"].startswith("#")
        func = [s for s in scs if not s.get("regression")]
        for s in func:
            assert "regression" not in s
            assert "regression_issue" not in s

    @pytest.fixture
    def regression_scenario_dir(self, tmp_path: Path) -> Path:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "regression").mkdir()
        (sd / "regression" / "fake-regression.yaml").write_text(
            "name: fake-regression\n"
            "description: \"Regression test\"\n"
            "category: regression\n"
            "regression: true\n"
            "regression_issue: \"#999\"\n"
            "requires_env: []\n"
            "steps:\n"
            "  - name: step1\n"
            "    tool: fake_tool\n"
            "    arguments: {}\n"
            "    expect:\n"
            "      success: true\n"
            "      data_has: [result]\n",
            encoding="utf-8",
        )
        (sd / "functional.yaml").write_text(
            "name: functional\n"
            "description: \"Functional test\"\n"
            "requires_env: []\n"
            "steps:\n"
            "  - name: step1\n"
            "    tool: fake_tool\n"
            "    arguments: {}\n"
            "    expect:\n"
            "      success: true\n",
            encoding="utf-8",
        )
        return sd

    async def test_run_scenario_carry_regression_fields(
        self, regression_scenario_dir: Path
    ) -> None:
        async def dispatch(name: str, args: dict) -> dict:
            return {"success": True, "data": {"result": "ok"}}

        result = await run_scenario(
            "fake-regression", dispatch, scenarios_dir=regression_scenario_dir
        )
        assert result["regression"] is True
        assert result["regression_issue"] == "#999"
        assert result["status"] == "passed"

    async def test_run_scenario_no_regression_fields_on_functional(
        self, regression_scenario_dir: Path
    ) -> None:
        async def dispatch(name: str, args: dict) -> dict:
            return {"success": True, "data": {}}

        result = await run_scenario(
            "functional", dispatch, scenarios_dir=regression_scenario_dir
        )
        assert "regression" not in result
        assert "regression_issue" not in result

    async def test_regression_env_unconfigured_carries_fields(
        self, regression_scenario_dir: Path
    ) -> None:
        """Env-gated regression scenario: unconfigured result carries regression fields."""
        (regression_scenario_dir / "regression" / "env-gated-reg.yaml").write_text(
            "name: env-gated-reg\n"
            "description: \"Env gated regression\"\n"
            "category: regression\n"
            "regression: true\n"
            "regression_issue: \"#888\"\n"
            "requires_env: [MISSING_VAR_XYZ_888]\n"
            "steps:\n"
            "  - name: gated\n"
            "    tool: health_check\n",
            encoding="utf-8",
        )
        result = await run_scenario(
            "env-gated-reg", dispatch=None, scenarios_dir=regression_scenario_dir
        )
        assert result["status"] == "unconfigured"
        assert result["regression"] is True
        assert result["regression_issue"] == "#888"
