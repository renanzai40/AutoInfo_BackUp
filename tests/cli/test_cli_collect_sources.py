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
from autoinfo.collect import _resolve_sources
from autoinfo.config import SourceConfig


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


class TestResolveSourcesDisabled:
    """``enabled: false`` sources must be excluded from collection (issues #6/#7).

    Before the fix, ``_resolve_sources`` returned every configured source
    regardless of ``enabled``, so a ``enabled: false`` source was still
    fetched (and failed with GFW/404 errors) during ``collect``.  The demo
    domains now carry many disabled sources — collection must skip them.
    """

    def _src(self, name: str, enabled: bool = True) -> SourceConfig:
        return SourceConfig(
            name=name,
            type="rss",
            url=f"https://{name}.example.com",
            settings={"enabled": enabled},
        )

    def test_disabled_source_excluded_when_no_request(self) -> None:
        """With no ``--source``, only enabled sources are returned."""
        srcs = [
            self._src("enabled-a"),
            self._src("disabled-b", enabled=False),
            self._src("enabled-c"),
        ]
        resolved, unknown = _resolve_sources(srcs, None)
        assert unknown == []
        assert [s.name for s in resolved] == ["enabled-a", "enabled-c"]

    def test_disabled_source_excluded_even_when_requested(self) -> None:
        """A disabled source is dropped even if explicitly requested."""
        srcs = [self._src("enabled-a"), self._src("disabled-b", enabled=False)]
        resolved, unknown = _resolve_sources(srcs, ["disabled-b"])
        assert [s.name for s in resolved] == []
        assert unknown == []

    def test_all_disabled_raises_no_active_sources(self) -> None:
        """When every source is disabled, resolution yields nothing."""
        srcs = [self._src("disabled-a", enabled=False), self._src("disabled-b", enabled=False)]
        resolved, _ = _resolve_sources(srcs, None)
        assert resolved == []
