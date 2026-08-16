"""Domain-matrix scenario parameterization tests (issue #280).

Locks the ``matrix_domains`` scenario schema key: when present,
``run_scenario`` executes the scenario once per listed domain, deep-
substituting ``{{domain}}`` in every ``kind: mcp`` step's ``arguments``
(recursively through nested dicts/lists), and aggregates the sub-runs
ALL-or-nothing.  Scenarios WITHOUT the key must behave byte-identically
to the pre-matrix harness — one execution, no substitution, no ``matrix``
key in the result envelope.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.mcp import validation as v

MATRIX_YAML = """\
name: matrix-scenario
description: "Domain-matrix fixture"
category: test
requires_env: []
matrix_domains: ["ai-commercial", "b2b"]
steps:
  - name: "schema per domain"
    tool: get_domain_schema
    kind: mcp
    arguments:
      domain: "{{domain}}"
      nested:
        x: "{{domain}}"
      list:
        - "{{domain}}"
    expect:
      success: true
"""

PLAIN_YAML = """\
name: plain-scenario
description: "No-matrix fixture (zero-regression guard)"
category: test
requires_env: []
steps:
  - name: "schema per domain"
    tool: get_domain_schema
    arguments:
      domain: "{{domain}}"
      nested:
        x: "{{domain}}"
      list:
        - "{{domain}}"
    expect:
      success: true
"""

PARTIAL_YAML = """\
name: partial-scenario
description: "Partial substitution fixture"
category: test
requires_env: []
matrix_domains: ["ai-commercial"]
steps:
  - name: "partial substitution"
    tool: get_domain_schema
    arguments:
      domain: "{{domain}}"
      label: "domain-matrix-check"
      path: "https://{{domain}}.example.com/rss"
      list:
        - "plain-string"
        - "{{domain}}-report"
    expect:
      success: true
"""

UNION_YAML = """\
name: union-scenario
description: "Union gate fixture"
category: test
requires_env: []
requires_domain: ["medical-research"]
matrix_domains: ["ai-commercial", "b2b"]
steps:
  - name: "schema per domain"
    tool: get_domain_schema
    arguments:
      domain: "{{domain}}"
    expect:
      success: true
"""


def _write_scenario(tmp_path: Path, body: str) -> Path:
    sd = tmp_path / "scenarios"
    sd.mkdir(exist_ok=True)
    (sd / "fixture.yaml").write_text(body, encoding="utf-8")
    return sd


def _scenario_body(**extra: Any) -> str:
    data: dict[str, Any] = {
        "name": "schema-scenario",
        "description": "schema fixture",
        "steps": [
            {
                "name": "s",
                "tool": "t",
                "arguments": {},
                "expect": {"success": True},
            }
        ],
    }
    data.update(extra)
    return yaml.safe_dump(data)


class _CapturingDispatch:
    """Stub dispatch recording every (tool, arguments) call.

    Fails (success=false) when the resolved ``domain`` argument is in
    ``fail_domains`` so sub-run aggregation can be exercised.
    """

    def __init__(self, fail_domains: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail = fail_domains or set()

    async def __call__(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, dict(arguments)))
        if arguments.get("domain") in self._fail:
            return {
                "success": False,
                "error": {"code": "DOMAIN_NOT_FOUND", "message": "no such domain"},
            }
        return {"success": True, "data": {"ok": True}}


class TestRunScenarioMatrix:
    """run_scenario domain-matrix expansion."""

    async def test_matrix_expands_once_per_domain_with_deep_substitution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each member domain fires the step once, ``{{domain}}`` replaced
        everywhere — top-level, nested dicts, and list items."""
        monkeypatch.setattr(
            v, "_configured_domain_names", lambda: ["ai-commercial", "b2b"]
        )
        sd = _write_scenario(tmp_path, MATRIX_YAML)
        dispatch = _CapturingDispatch()

        result = await v.run_scenario("matrix-scenario", dispatch=dispatch, scenarios_dir=sd)

        assert [tool for tool, _ in dispatch.calls] == [
            "get_domain_schema",
            "get_domain_schema",
        ]
        expected_args = {
            "ai-commercial": {
                "domain": "ai-commercial",
                "nested": {"x": "ai-commercial"},
                "list": ["ai-commercial"],
            },
            "b2b": {
                "domain": "b2b",
                "nested": {"x": "b2b"},
                "list": ["b2b"],
            },
        }
        assert {args["domain"] for _, args in dispatch.calls} == {
            "ai-commercial",
            "b2b",
        }
        for _, args in dispatch.calls:
            assert args == expected_args[args["domain"]]

        assert result["status"] == "passed"
        assert result["summary"]["total"] == 2
        assert result["summary"]["passed"] == 2
        assert [s["domain"] for s in result["steps"]] == ["ai-commercial", "b2b"]
        matrix = result["matrix"]
        assert matrix["domains"] == ["ai-commercial", "b2b"]
        assert set(matrix["per_domain"]) == {"ai-commercial", "b2b"}
        for domain in matrix["domains"]:
            sub = matrix["per_domain"][domain]
            assert sub["status"] == "passed"
            assert sub["summary"]["total"] == 1
            assert sub["summary"]["passed"] == 1

    async def test_without_matrix_domains_dispatches_exactly_once(
        self, tmp_path: Path
    ) -> None:
        """Zero-regression guard: no matrix key -> one execution, no
        substitution (the literal ``{{domain}}`` token arrives untouched),
        and the envelope carries no ``matrix`` key."""
        sd = _write_scenario(tmp_path, PLAIN_YAML)
        dispatch = _CapturingDispatch()

        result = await v.run_scenario("plain-scenario", dispatch=dispatch, scenarios_dir=sd)

        assert len(dispatch.calls) == 1
        assert dispatch.calls[0][0] == "get_domain_schema"
        assert dispatch.calls[0][1] == {
            "domain": "{{domain}}",
            "nested": {"x": "{{domain}}"},
            "list": ["{{domain}}"],
        }
        assert "matrix" not in result
        assert result["status"] == "passed"
        assert result["summary"]["total"] == 1

    async def test_partial_substitution_keeps_sibling_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the exact ``{{domain}}`` token is replaced — the substituted
        value must never appear inside a non-placeholder string (e.g. the
        word 'domain' in 'domain-matrix-check' must survive untouched)."""
        monkeypatch.setattr(v, "_configured_domain_names", lambda: ["ai-commercial"])
        sd = _write_scenario(tmp_path, PARTIAL_YAML)
        dispatch = _CapturingDispatch()

        result = await v.run_scenario("partial-scenario", dispatch=dispatch, scenarios_dir=sd)

        args = dispatch.calls[0][1]
        assert args["domain"] == "ai-commercial"
        assert args["label"] == "domain-matrix-check"
        assert args["path"] == "https://ai-commercial.example.com/rss"
        assert args["list"] == ["plain-string", "ai-commercial-report"]
        assert result["status"] == "passed"

    async def test_matrix_failure_fails_scenario_with_per_domain_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Aggregation is ALL-or-nothing: one failing sub-run fails the whole
        scenario, with every sub-run's result recorded per domain."""
        monkeypatch.setattr(
            v, "_configured_domain_names", lambda: ["ai-commercial", "b2b"]
        )
        sd = _write_scenario(tmp_path, MATRIX_YAML)
        dispatch = _CapturingDispatch(fail_domains={"b2b"})

        result = await v.run_scenario("matrix-scenario", dispatch=dispatch, scenarios_dir=sd)

        assert result["status"] == "failed"
        assert result["summary"]["failed"] == 1
        assert result["summary"]["passed"] == 1
        assert result["matrix"]["per_domain"]["ai-commercial"]["status"] == "passed"
        assert result["matrix"]["per_domain"]["b2b"]["status"] == "failed"
        # the failing sub-run's step keeps its failed status with detail
        b2b_steps = result["matrix"]["per_domain"]["b2b"]["steps"]
        assert b2b_steps[0]["status"] == "failed"

    async def test_matrix_members_join_requires_domain_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Effective requires_domain is the union of the declared domains and
        the matrix members: a member missing from the project config gates the
        whole scenario unconfigured (no dispatch), all present -> runs."""
        monkeypatch.setattr(
            v, "_configured_domain_names", lambda: ["medical-research", "ai-commercial"]
        )
        sd = _write_scenario(tmp_path, UNION_YAML)
        dispatch = _CapturingDispatch()

        result = await v.run_scenario("union-scenario", dispatch=dispatch, scenarios_dir=sd)
        assert result["status"] == "unconfigured"
        assert "b2b" in result.get("unconfigured_reason", "")
        assert dispatch.calls == []

        monkeypatch.setattr(
            v,
            "_configured_domain_names",
            lambda: ["medical-research", "ai-commercial", "b2b"],
        )
        result = await v.run_scenario("union-scenario", dispatch=dispatch, scenarios_dir=sd)
        assert result["status"] == "passed"
        assert len(dispatch.calls) == 2


class TestLoadScenariosMatrixSchema:
    """load_scenarios schema validation for the matrix_domains key."""

    @pytest.mark.parametrize(
        "bad",
        [[], "ai-commercial", [123], [""], ["ai-commercial", 7]],
    )
    def test_load_scenarios_rejects_invalid_matrix_domains(
        self, tmp_path: Path, bad: Any
    ) -> None:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "bad.yaml").write_text(
            _scenario_body(matrix_domains=bad), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="matrix_domains"):
            v.load_scenarios(sd)

    def test_load_scenarios_defaults_matrix_domains_to_empty(
        self, tmp_path: Path
    ) -> None:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "plain.yaml").write_text(_scenario_body(), encoding="utf-8")
        scs = v.load_scenarios(sd)
        assert scs[0]["matrix_domains"] == []

    def test_load_scenarios_accepts_matrix_domains(self, tmp_path: Path) -> None:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "mat.yaml").write_text(
            _scenario_body(matrix_domains=["ai-commercial", "b2b"]),
            encoding="utf-8",
        )
        scs = v.load_scenarios(sd)
        assert scs[0]["matrix_domains"] == ["ai-commercial", "b2b"]


class TestListScenariosMatrix:
    """list_scenarios surfaces matrix_domains per scenario."""

    def test_list_scenarios_surfaces_matrix_domains(self, tmp_path: Path) -> None:
        sd = tmp_path / "scenarios"
        sd.mkdir()
        (sd / "mat.yaml").write_text(
            _scenario_body(name="mat-scenario", matrix_domains=["b2b"]),
            encoding="utf-8",
        )
        (sd / "plain.yaml").write_text(
            _scenario_body(name="plain-scenario"), encoding="utf-8"
        )
        summary = {s["name"]: s for s in v.list_scenarios(sd)["scenarios"]}
        assert summary["mat-scenario"]["matrix_domains"] == ["b2b"]
        assert summary["plain-scenario"]["matrix_domains"] == []
