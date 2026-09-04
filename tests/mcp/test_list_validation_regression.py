"""list_scenarios() must surface a ``regression`` boolean per scenario.

Ground truth: each scenario YAML's top-level ``regression: true`` key.
The expected True/False counts are derived dynamically from
``load_scenarios()`` at test time — never hardcoded — because later
work keeps adding files to ``scenarios/regression/``.

Also asserts that the MCP server handler
``_handle_list_validation_scenarios`` does not strip the flag: it is a
pure passthrough of ``list_scenarios()``, verified by patching the
validation module's ``list_scenarios`` (the handler imports it inside
the function body, so the module attribute is the seam).
"""

from __future__ import annotations

from typing import Any

import pytest

from autoinfo.mcp import server as mcp_server
from autoinfo.mcp import validation as validation_mod
from autoinfo.mcp.validation import list_scenarios, load_scenarios


def _expected_regression_map() -> dict[str, bool]:
    """Derive {scenario_name: regression_bool} from the loader ground truth."""
    return {sc["name"]: bool(sc.get("regression", False)) for sc in load_scenarios()}


class TestListScenariosRegressionFlag:
    """Every list_scenarios() item carries a `regression: bool` flag."""

    def test_every_item_has_regression_bool(self) -> None:
        result = list_scenarios()
        assert "scenarios" in result
        assert result["count"] == len(result["scenarios"])
        assert result["count"] > 0
        for sc in result["scenarios"]:
            assert "regression" in sc, f"scenario {sc['name']!r} missing 'regression' key"
            assert isinstance(sc["regression"], bool), (
                f"scenario {sc['name']!r}: 'regression' is "
                f"{type(sc['regression']).__name__}, expected bool"
            )

    def test_flag_matches_yaml_ground_truth_dynamically(self) -> None:
        expected = _expected_regression_map()
        assert expected, "load_scenarios() returned no scenarios"
        result = list_scenarios()
        actual = {sc["name"]: sc["regression"] for sc in result["scenarios"]}
        assert result["count"] == len(expected)
        assert actual == expected

    def test_both_true_and_false_present(self) -> None:
        """The live library must contain both kinds (regression/ vs root)."""
        expected = _expected_regression_map()
        true_count = sum(1 for v in expected.values() if v)
        false_count = sum(1 for v in expected.values() if not v)
        assert true_count > 0, "expected at least one regression: true scenario"
        assert false_count > 0, "expected at least one non-regression scenario"

    def test_existing_fields_unchanged(self) -> None:
        """Existing summary fields must still be present with same semantics."""
        result = list_scenarios()
        for sc in result["scenarios"]:
            for key in (
                "name",
                "description",
                "category",
                "step_count",
                "requires_env",
                "requires_http",
                "matrix_domains",
            ):
                assert key in sc, f"scenario {sc['name']!r} lost existing field {key!r}"


class TestServerPassthrough:
    """_handle_list_validation_scenarios must not strip the regression flag."""

    def test_handler_passes_regression_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = {
            "scenarios": [
                {
                    "name": "fake-regression-scenario",
                    "description": "d",
                    "category": "regression",
                    "step_count": 1,
                    "requires_env": [],
                    "requires_http": [],
                    "matrix_domains": [],
                    "regression": True,
                },
                {
                    "name": "fake-functional-scenario",
                    "description": "d",
                    "category": "general",
                    "step_count": 1,
                    "requires_env": [],
                    "requires_http": [],
                    "matrix_domains": [],
                    "regression": False,
                },
            ],
            "count": 2,
        }

        def fake_list_scenarios(
            scenarios_dir: Any = None,
        ) -> dict[str, Any]:
            return fake

        # The handler imports list_scenarios inside its body from
        # autoinfo.mcp.validation — patch the module attribute.
        monkeypatch.setattr(validation_mod, "list_scenarios", fake_list_scenarios)
        result = mcp_server._handle_list_validation_scenarios()
        assert result == fake, "server handler must be a pure passthrough of list_scenarios()"
        flags = {sc["name"]: sc["regression"] for sc in result["scenarios"]}
        assert flags == {
            "fake-regression-scenario": True,
            "fake-functional-scenario": False,
        }

    def test_handler_with_real_scenarios(self) -> None:
        """End-to-end: real handler output carries the flag on real data."""
        result = mcp_server._handle_list_validation_scenarios()
        assert result["count"] > 0
        for sc in result["scenarios"]:
            assert isinstance(sc["regression"], bool)
        expected = _expected_regression_map()
        actual = {sc["name"]: sc["regression"] for sc in result["scenarios"]}
        assert actual == expected
