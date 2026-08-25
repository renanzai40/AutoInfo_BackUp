"""CLI tests for ``autoinfo output localize`` (issue #38)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner


def _runner() -> CliRunner:
    """Return a CliRunner instance."""
    from typer.testing import CliRunner

    return CliRunner()


def test_localize_command_writes_language_file(
    cli_runner: Any, tmp_path: Any
) -> None:
    """``output localize`` writes the lang-suffixed product + manifest."""
    from autoinfo.cli import app

    with patch(
        "autoinfo.output.localize.localize_product",
        return_value={
            "file_path": str(tmp_path / "zh" / "digest-zh.md"),
            "language": "zh",
            "source_lang": "en",
            "domain": "medical-research",
            "product": "digest",
            "qa": {"gate": "passed", "avg_score": 91.0, "refined_count": 0, "failed_count": 0},
        },
    ) as mock_loc:
        result = cli_runner.invoke(
            app,
            [
                "output", "localize",
                "--domain", "medical-research",
                "--product", "digest",
                "--period", "weekly",
                "--target-lang", "zh",
            ],
        )
    assert result.exit_code == 0, result.output
    mock_loc.assert_called_once_with(
        domain="medical-research",
        product="digest",
        period="weekly",
        target_lang="zh",
        source_lang="",
        out_dir="outputs/localized",
    )
    assert "digest-zh.md" in result.output
    assert "qa=passed" in result.output


def test_localize_requires_target_lang(cli_runner: Any) -> None:
    """Missing ``--target-lang`` is a usage error, not a crash."""
    from autoinfo.cli import app

    result = cli_runner.invoke(
        app, ["output", "localize", "--domain", "medical-research"]
    )
    assert result.exit_code != 0
    assert "--target-lang" in result.output


def test_localize_value_error_surfaces(
    cli_runner: Any, tmp_path: Any
) -> None:
    """A ValueError from the pipeline prints ``Error:`` and exits 1."""
    from autoinfo.cli import app

    with patch(
        "autoinfo.output.localize.localize_product",
        side_effect=ValueError("Unsupported product 'presentation'"),
    ):
        result = cli_runner.invoke(
            app,
            [
                "output", "localize",
                "--domain", "medical-research",
                "--product", "presentation",
                "--target-lang", "zh",
            ],
        )
    assert result.exit_code == 1
    assert "Unsupported product 'presentation'" in result.output
