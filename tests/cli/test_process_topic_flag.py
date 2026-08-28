"""CLI ``process --topic`` flag tests (issue #68, PART A).

The ``--topic`` option is forwarded into ``run_processing`` so G3 keyword
resolution can stay per-topic when the human/agent names one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from autoinfo.cli.process import app
from autoinfo.process import ProcessResult


def test_process_accepts_topic_flag(cli_runner: Any, tmp_path: Path) -> None:
    """``autoinfo process --domain d --topic my-topic`` forwards the topic."""
    captured: dict[str, Any] = {}

    def _fake_run_processing(**kwargs: Any) -> ProcessResult:
        captured.update(kwargs)
        return ProcessResult(
            domain=kwargs.get("domain", ""),
            total_items=1,
            processed_count=1,
            remaining_count=0,
            is_complete=True,
        )

    with patch(
        "autoinfo.cli.process.run_processing",
        side_effect=_fake_run_processing,
    ):
        res = cli_runner.invoke(
            app,
            ["--domain", "french-learning", "--topic", "my-topic"],
        )

    assert res.exit_code == 0, res.output
    assert captured.get("topic") == "my-topic", (
        f"run_processing did not receive topic='my-topic' (got {captured!r})"
    )
    assert captured.get("domain") == "french-learning"
