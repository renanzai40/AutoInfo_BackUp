"""Tests for #352.2 — References/[View Source] link reachability assertion.

The matrix never validated that ``[View Source]`` / References URLs are real:
dead or fabricated links slipped through.  Two sub-checks, one deterministic
(form) and one slow/network (reachability):

* **Form** — every extracted candidate URL must be non-empty and carry an
  http/https scheme (no ``javascript:``, no bare relative paths).
* **Reachability** — HEAD-request each http(s) URL with a short timeout and
  verify it resolves (2xx/3xx).  OPTIONAL: only runs when ``include_slow=True``
  (CLI ``--link-check``); never in the default fast path.

All HTTP traffic is mocked at the module seam (``_head_url``); no real network
calls in this file.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from autoinfo import validation_matrix as vm
from autoinfo.cli.validate import app

runner = CliRunner()


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


GOOD = """# AI Commercial Report

**Domain**: ai-commercial
**Sections**: 1

## Summary

AI funding accelerated this week.

## Key Takeaways

### 1. Startup A raised $50M [View Source](https://techcrunch.com/1)

### 2. Startup B raised $30M (Source: https://techcrunch.com/2)

## References

1. **Startup A** — https://techcrunch.com/1
2. **Startup B** — https://techcrunch.com/2
"""

# Form-invalid references: empty ``[View Source]()``, ``javascript:`` scheme,
# bare relative path, and a non-http scheme — all deterministic failures.
BAD_FORM = """# AI Commercial Report

**Domain**: ai-commercial

## Summary

AI funding accelerated this week.

## Key Takeaways

### 1. Startup A raised $50M [View Source]()

### 2. Startup B raised $30M [View Source](javascript:alert(1))

### 3. Startup C raised $20M (Source: /relative/path)

## References

1. **Startup A** — [View Source]()
2. **Startup B** — javascript:alert(1)
3. **Startup C** — [View Source](mailto:someone@example.com)
"""
class TestReferencesReachable:
    def test_references_reachable_form_check(self) -> None:
        """A product with a dead-form reference (empty URL, javascript:, no
        scheme) fails deterministically — no network needed."""
        with patch(
            "autoinfo.validation_matrix._head_url",
            side_effect=AssertionError("network touched on form failure"),
        ):
            r = vm._references_reachable(BAD_FORM, "ai-commercial", "report")
        assert r.name == "_references_reachable"
        assert not r.passed
        assert r.issue == "#352"
        assert r.severity == "P1"
        assert "''" in r.details  # empty [View Source]()
        for url in (
            "javascript:alert(1)",
            "/relative/path",
            "mailto:someone@example.com",
        ):
            assert repr(url) in r.details, r.details

    def test_references_reachable_all_ok(self) -> None:
        """A product with http(s) URLs passes — form-check only; the
        reachability transport is mocked to 200."""
        with patch(
            "autoinfo.validation_matrix._head_url",
            return_value=_FakeResponse(200),
        ):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert r.name == "_references_reachable"
        assert r.passed
        assert r.issue == "#352"

    def test_references_reachable_http_200(self) -> None:
        """Mocked transport returning 200 for every URL → passes."""
        with patch(
            "autoinfo.validation_matrix._head_url",
            return_value=_FakeResponse(200),
        ):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert r.passed
        assert "unknown" not in r.details

    def test_references_reachable_dead_link(self) -> None:
        """Mocked transport returning 404 / raising a connection error for one
        URL → the assertion fails with the dead URL in details."""

        def fake_head(url: str, timeout: float) -> _FakeResponse:
            if "techcrunch.com/2" in url:
                return _FakeResponse(404)
            return _FakeResponse(200)

        with patch("autoinfo.validation_matrix._head_url", side_effect=fake_head):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert not r.passed
        assert "https://techcrunch.com/2" in r.details

        # Connection-error (DNS / refused) is a hard fail too.
        def fake_head_connect(url: str, timeout: float) -> _FakeResponse:
            if "techcrunch.com/1" in url:
                raise httpx.ConnectError("connection refused")
            return _FakeResponse(200)

        with patch("autoinfo.validation_matrix._head_url",
                   side_effect=fake_head_connect):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert not r.passed
        assert "https://techcrunch.com/1" in r.details

    def test_references_reachable_timeout_treated_unknown(self) -> None:
        """Mocked transport raising a timeout → treated as 'unknown' (pass),
        not a hard fail — flaky networks must not break validation."""

        def fake_head_timeout(url: str, timeout: float) -> _FakeResponse:
            if "techcrunch.com/2" in url:
                raise httpx.TimeoutException("timed out")
            return _FakeResponse(200)

        with patch("autoinfo.validation_matrix._head_url",
                   side_effect=fake_head_timeout):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert r.passed
        assert "unknown" in r.details

        # A builtin TimeoutError must be treated the same way.
        def fake_head_builtin_timeout(url: str, timeout: float) -> _FakeResponse:
            if "techcrunch.com/2" in url:
                raise TimeoutError("builtin timeout")
            return _FakeResponse(200)

        with patch("autoinfo.validation_matrix._head_url",
                   side_effect=fake_head_builtin_timeout):
            r = vm._references_reachable(GOOD, "ai-commercial", "report")
        assert r.passed


class TestRunAssertionsIncludeSlow:
    def test_run_assertions_include_slow(self) -> None:
        """``run_assertions(..., include_slow=True)`` includes the reachability
        assertion; default ``include_slow=False`` does NOT (fast path unchanged,
        no network)."""
        default = vm.run_assertions(GOOD, domain="ai-commercial", product="report")
        assert len(default) == len(vm.ASSERTION_FUNCS)
        assert "_references_reachable" not in {r.name for r in default}

        # The default fast path must never touch the network seam.
        with patch(
            "autoinfo.validation_matrix._head_url",
            side_effect=AssertionError("network in fast path"),
        ):
            vm.run_assertions(GOOD, domain="ai-commercial", product="report")

        with patch(
            "autoinfo.validation_matrix._head_url",
            return_value=_FakeResponse(200),
        ):
            slow = vm.run_assertions(
                GOOD, domain="ai-commercial", product="report", include_slow=True
            )
        assert len(slow) == len(vm.ASSERTION_FUNCS) + len(vm.SLOW_ASSERTION_FUNCS)
        reachable = [r for r in slow if r.name == "_references_reachable"]
        assert len(reachable) == 1
        assert reachable[0].passed
        assert reachable[0].severity == "P1"

    def test_slow_assertion_funcs_registered(self) -> None:
        """``SLOW_ASSERTION_FUNCS`` carries exactly the reachability assertion
        under its module-level name, disjoint from the fast ``ASSERTION_FUNCS``."""
        assert [name for name, _ in vm.SLOW_ASSERTION_FUNCS] == [
            "_references_reachable"
        ]
        fast_names = {name for name, _ in vm.ASSERTION_FUNCS}
        assert "_references_reachable" not in fast_names


class TestCliLinkCheck:
    def test_cli_link_check_flag(self, tmp_path: object) -> None:
        """CLI ``validate matrix --link-check`` passes ``include_slow=True`` to
        run_matrix; the default invocation passes ``False``."""
        report = vm.MatrixReport(generated_at="t", commit="abc", batch_id="b1")
        report.summary = {"failures": 0, "domains": ["d"], "products": ["digest"]}
        snap = tmp_path / "snap"  # type: ignore[operator]

        with patch("autoinfo.cli.validate.run_matrix", return_value=report) as rm, \
             patch("autoinfo.cli.validate.save_report_card"), \
             patch("autoinfo.cli.validate._current_commit", return_value="abc"):
            result = runner.invoke(app, [
                "matrix", "--only-assert", "--domains", "d", "--products", "digest",
                "--link-check", "--snapshot-dir", str(snap),
            ])
        assert result.exit_code == 0, result.output
        assert rm.call_args.kwargs["include_slow"] is True

        with patch("autoinfo.cli.validate.run_matrix", return_value=report) as rm2, \
             patch("autoinfo.cli.validate.save_report_card"), \
             patch("autoinfo.cli.validate._current_commit", return_value="abc"):
            result = runner.invoke(app, [
                "matrix", "--only-assert", "--domains", "d", "--products", "digest",
                "--snapshot-dir", str(snap),
            ])
        assert result.exit_code == 0, result.output
        assert rm2.call_args.kwargs["include_slow"] is False

    def test_cli_stability_link_check_flag(self, tmp_path: object) -> None:
        """CLI ``validate stability --link-check`` threads ``include_slow=True``
        into diff_batches."""
        fake = {
            "diff": {
                "counts": {
                    "new": 0, "regressed": 0, "fixed": 0, "existing_failing": 0,
                },
                "regressed": [], "new": [], "fixed": [], "existing_failing": [],
            },
            "prev_batch": {"products": []},
            "cur_batch": {"products": []},
            "stable": True,
        }
        with patch("autoinfo.cli.validate.diff_batches", return_value=fake) as db:
            result = runner.invoke(app, [
                "stability", "prev-batch", "cur-batch",
                "--domains", "d", "--products", "digest", "--link-check",
                "--snapshot-dir", str(tmp_path / "snap"),  # type: ignore[operator]
            ])
        assert result.exit_code == 0, result.output
        assert db.call_args.kwargs["include_slow"] is True
