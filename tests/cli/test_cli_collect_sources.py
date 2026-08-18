"""CLI ``collect --source`` regression tests (issue #296).

Two confirmed defects:

(a) ``--source`` was declared as a single ``str`` despite claiming
    "repeatable" — Typer collapses repeated flags to the LAST value, so
    ``--source pubmed --source rss`` silently dropped ``pubmed``.
(b) requested-but-unknown source names were silently filtered out by
    ``_resolve_sources`` and the CLI exited 0 even when a requested source
    was dropped or failed.

These tests lock the fixed behavior: repeated ``--source`` flags accumulate,
and an unknown/failed requested source produces a warning + non-zero exit.
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

from typer.testing import CliRunner

from autoinfo.cli.collect import app


def _mock_result(**overrides: object) -> dict[str, object]:
    """A minimal ``run_collection`` result dict for CLI wiring tests."""
    result: dict[str, object] = {
        "collection_id": "col-src",
        "domain": "medical-research",
        "total_found": 0,
        "total_new": 0,
        "duration_s": 0.1,
        "per_source": [],
        "dry_run": False,
    }
    result.update(overrides)
    return result


class TestCollectSourceFlags:
    """Repeated ``--source`` flags must accumulate (issue #296a)."""

    @patch("autoinfo.collect.run_collection")
    def test_two_source_flags_both_collect(
        self, mock_run_collection: MagicMock, cli_runner: CliRunner
    ) -> None:
        """``--source pubmed --source rss`` passes BOTH names to run_collection."""
        mock_run_collection.return_value = _mock_result()

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--source", "pubmed", "--source", "rss"],
        )

        assert result.exit_code == 0, result.output
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="",
            sources=["pubmed", "rss"],
            limit=20,
            dry_run=False,
            progress_cb=ANY,
        )

    @patch("autoinfo.collect.run_collection")
    def test_comma_separated_source_still_splits(
        self, mock_run_collection: MagicMock, cli_runner: CliRunner
    ) -> None:
        """``--source "pubmed,rss"`` still splits into a list (legacy behavior)."""
        mock_run_collection.return_value = _mock_result()

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--source", "pubmed,rss"],
        )

        assert result.exit_code == 0, result.output
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="",
            sources=["pubmed", "rss"],
            limit=20,
            dry_run=False,
            progress_cb=ANY,
        )


class TestCollectUnknownSource:
    """Unknown/failed requested sources must warn + exit non-zero (#296b)."""

    @patch("autoinfo.collect.run_collection")
    def test_unknown_source_warns_and_exits_nonzero(
        self, mock_run_collection: MagicMock, cli_runner: CliRunner
    ) -> None:
        """A requested source missing from the domain config exits non-zero."""
        mock_run_collection.return_value = _mock_result(unknown_sources=["rss"])

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--source", "rss"],
        )

        assert result.exit_code != 0
        assert "rss" in result.output

    @patch("autoinfo.collect.run_collection")
    def test_failed_requested_source_exits_nonzero(
        self, mock_run_collection: MagicMock, cli_runner: CliRunner
    ) -> None:
        """A requested source that errors during collection exits non-zero."""
        mock_run_collection.return_value = _mock_result(
            per_source=[
                {
                    "source": "pubmed",
                    "status": "error",
                    "items_found": 0,
                    "items_new": 0,
                    "errors": [{"message": "PubMed down"}],
                    "duration_s": 0.1,
                },
            ],
        )

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research", "--source", "pubmed"],
        )

        assert result.exit_code != 0
        assert "pubmed" in result.output

    @patch("autoinfo.collect.run_collection")
    def test_no_source_flag_collects_all(
        self, mock_run_collection: MagicMock, cli_runner: CliRunner
    ) -> None:
        """Without ``--source``, sources=None (collect all) — unchanged behavior."""
        mock_run_collection.return_value = _mock_result()

        result = cli_runner.invoke(
            app,
            ["--domain", "medical-research"],
        )

        assert result.exit_code == 0, result.output
        mock_run_collection.assert_called_once_with(
            domain="medical-research",
            topic="",
            sources=None,
            limit=20,
            dry_run=False,
            progress_cb=ANY,
        )
