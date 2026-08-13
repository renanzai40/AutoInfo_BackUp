"""Tests for the ``--product`` flag on ``output digest`` / ``output report``.

Verifies that ``--product`` resolves against the ``PRODUCT_TEMPLATES``
registry and is forwarded as ``product_template`` to the underlying
``generate_*`` functions, that unknown product names produce a clear
error listing the valid names, and that omitting ``--product`` preserves
the existing call shape exactly (no ``product_template`` kwarg).

The output commands import the ``generate_*`` functions inside each
command body (``from autoinfo.output import generate_*``), so patching
the module attribute is sufficient — the import resolves at call time.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.cli import app
from autoinfo.output import PRODUCT_TEMPLATES


def _registry_template(product: str) -> Any:
    """Return the ProductTemplate instance registered under *product*."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == product:
            return row["template"]
    raise AssertionError(f"product {product!r} not in PRODUCT_TEMPLATES")


@pytest.fixture
def cli_runner() -> Any:
    """Return a CliRunner instance."""
    from typer.testing import CliRunner

    return CliRunner()


class TestOutputCommandProduct:
    """``--product`` routes through to generate_report / generate_digest."""

    @patch("autoinfo.output.generate_report", return_value="# report")
    def test_report_product_premium_briefing(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output report --product premium-briefing`` passes the registry row."""
        result = cli_runner.invoke(
            app,
            [
                "output", "report",
                "--domain", "medical-research",
                "--product", "premium-briefing",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            format="markdown",
            target_audience="",
            report_type="standard",
            user_id="",
            product_template=_registry_template("premium-briefing"),
        )

    @patch("autoinfo.output.generate_digest", return_value="# digest")
    def test_digest_product_magazine_digest(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """``output digest --product magazine-digest`` routes through generate_digest."""
        result = cli_runner.invoke(
            app,
            [
                "output", "digest",
                "--domain", "medical-research",
                "--product", "magazine-digest",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_gen.assert_called_once_with(
            domain="medical-research",
            period="weekly",
            format="markdown",
            custom_instructions="",
            target_audience="",
            include_stale=False,
            recipients=None,
            user_id="",
            max_items=0,
            product_template=_registry_template("magazine-digest"),
        )

    def test_digest_unknown_product_lists_valid_names(
        self, cli_runner: Any
    ) -> None:
        """Unknown ``--product`` on digest errors out with valid names listed."""
        result = cli_runner.invoke(
            app,
            ["output", "digest", "--domain", "medical-research", "--product", "bogus"],
        )
        assert result.exit_code == 1
        assert "Unknown product 'bogus'" in result.output
        assert "premium-briefing" in result.output
        assert "magazine-digest" in result.output

    def test_report_unknown_product_lists_valid_names(
        self, cli_runner: Any
    ) -> None:
        """Unknown ``--product`` on report errors out with valid names listed."""
        result = cli_runner.invoke(
            app,
            ["output", "report", "--domain", "medical-research", "--product", "bogus"],
        )
        assert result.exit_code == 1
        assert "Unknown product 'bogus'" in result.output
        assert "premium-briefing" in result.output
        assert "magazine-digest" in result.output

    @patch("autoinfo.output.generate_digest", return_value="# digest")
    def test_digest_no_product_unchanged(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--product`` keeps the existing call shape (no product_template)."""
        result = cli_runner.invoke(
            app, ["output", "digest", "--domain", "medical-research"]
        )
        assert result.exit_code == 0, result.output
        mock_gen.assert_called_once_with(
            domain="medical-research",
            period="weekly",
            format="markdown",
            custom_instructions="",
            target_audience="",
            include_stale=False,
            recipients=None,
            user_id="",
            max_items=0,
        )

    @patch("autoinfo.output.generate_report", return_value="# report")
    def test_report_no_product_unchanged(
        self, mock_gen: MagicMock, cli_runner: Any
    ) -> None:
        """Omitting ``--product`` keeps the existing call shape (no product_template)."""
        result = cli_runner.invoke(
            app, ["output", "report", "--domain", "medical-research"]
        )
        assert result.exit_code == 0, result.output
        mock_gen.assert_called_once_with(
            domain="medical-research",
            collection_id=None,
            format="markdown",
            target_audience="",
            report_type="standard",
            user_id="",
        )
