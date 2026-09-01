"""Regression guard for issue #128: product stdout must stay pure.

Issue #128 observed internal diagnostics (``G0 first attempt failed``,
``Promotion rejected ... marker written to``, ``Failed to parse LLM response
as JSON``) leaking into product files when a user redirected ``> file``.
The root cause would be a logging StreamHandler writing to stdout — mixing
logger diagnostics with the product body that ``cli/output.py`` echoes via
``typer.echo(result)``.

Current contract (verified): the stdlib loggers (quality/kb/llm) have no
stdout handler — their warnings route to stderr (logging.lastResort), and
stdout carries only the product content + intentional user-facing lines
(``Persisted to ...``).  This guard locks that contract so a future logging
refactor cannot silently reintroduce the leak.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner


def _runner() -> CliRunner:
    from typer.testing import CliRunner

    return CliRunner()


def test_logger_diagnostics_go_to_stderr_not_stdout(
    capsys: Any, caplog: Any
) -> None:
    """logger.warning from quality/kb/llm must never appear on stdout."""
    # Emit the exact diagnostic classes issue #128 flagged, on the loggers
    # the product pipeline uses.  Without any stdout handler configured,
    # these MUST land on stderr (lastResort) and NOT stdout.  pytest's
    # logging plugin captures the stderr via caplog, so we assert both:
    # stdout holds only the product body, and the diagnostics were emitted.
    logging.getLogger("autoinfo.quality").warning("G0 first attempt failed for fields: ['source_platform']")
    logging.getLogger("autoinfo.kb").warning(
        "Promotion rejected for medical-research-draft-1 "
        "(incomplete-source-provenance) — marker written to /tmp/_failed/"
    )
    logging.getLogger("autoinfo.llm").warning("Failed to parse LLM response as JSON: {...}")

    print("PRODUCT CONTENT HERE")

    captured = capsys.readouterr()
    assert captured.out == "PRODUCT CONTENT HERE\n", (
        "logger diagnostics leaked into stdout:\n" + captured.out
    )
    # The diagnostics were emitted as warnings (pytest captured them in
    # caplog rather than raw capsys.err because the logging plugin owns the
    # stderr StreamHandler during the test).
    assert "G0 first attempt failed" in caplog.text
    assert "Promotion rejected" in caplog.text
    assert "Failed to parse LLM response as JSON" in caplog.text


def test_cli_output_stdout_holds_only_product_body(cli_runner: Any) -> None:
    """``autoinfo output tutorial`` stdout is the product body, not logs.

    The tutorial path emits logger warnings (stale-guard, synthesis) during
    generation; those must not appear in the redirected stdout.
    """
    from autoinfo.cli import app

    with patch(
        "autoinfo.output.generate_tutorial",
        return_value="# Tutorial\n\nBody content.",
    ) as mock_gen:
        result = cli_runner.invoke(
            app,
            ["output", "tutorial", "--domain", "medical-research", "--format", "markdown"],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == "# Tutorial\n\nBody content.\n"
        mock_gen.assert_called_once()
        # The generated call must have been invoked with the CLI default
        # include_stale=False.
        assert mock_gen.call_args.kwargs.get("include_stale") is False
