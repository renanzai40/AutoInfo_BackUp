"""Tests for ``SQLiteIndex._connect()`` PRAGMA busy_timeout (issue #295).

The 4-tier KB uses SQLite.  Parallel ``autoinfo process`` workers write to
the same DB, and under external-writer contention (WAL checkpoint, another
process) a write can raise ``sqlite3.OperationalError: database is locked``.
Before the fix ``_connect()`` set WAL but NO ``PRAGMA busy_timeout``, so a
contended connection failed immediately instead of waiting for the lock.

These tests assert that every connection opened by ``_connect()`` executes
``PRAGMA busy_timeout`` with a generous default (30000 ms) that is
configurable via ``AUTOINFO_DB_BUSY_TIMEOUT_MS``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autoinfo.kb import SQLiteIndex

_DEFAULT_BUSY_TIMEOUT_MS = 30000


def _busy_timeout_ms(index: SQLiteIndex) -> int:
    """Return the effective ``busy_timeout`` of a fresh ``_connect()``."""
    with index._connect() as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
    assert row is not None
    return int(row[0])


def test_connect_sets_default_busy_timeout(tmp_path: Path) -> None:
    """``_connect()`` must set a generous default busy timeout (30000 ms)."""
    index = SQLiteIndex(tmp_path / "kb.db")
    assert _busy_timeout_ms(index) == _DEFAULT_BUSY_TIMEOUT_MS


def test_connect_busy_timeout_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AUTOINFO_DB_BUSY_TIMEOUT_MS`` overrides the default timeout.

    Uses 12345 — distinct from both the default (30000) and this SQLite
    build's compiled-in default (5000) — so the assertion genuinely proves
    the env value is read, not that it coincidentally matches a default.
    """
    monkeypatch.setenv("AUTOINFO_DB_BUSY_TIMEOUT_MS", "12345")
    index = SQLiteIndex(tmp_path / "kb.db")
    assert _busy_timeout_ms(index) == 12345


def test_connect_busy_timeout_invalid_env_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unparsable env value falls back to the default timeout."""
    monkeypatch.setenv("AUTOINFO_DB_BUSY_TIMEOUT_MS", "not-a-number")
    index = SQLiteIndex(tmp_path / "kb.db")
    assert _busy_timeout_ms(index) == _DEFAULT_BUSY_TIMEOUT_MS


def test_connect_executes_busy_timeout_pragma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_connect()`` must execute ``PRAGMA busy_timeout`` on every connection.

    Probes the executed SQL directly (a fake connection records every
    statement) so the assertion is independent of SQLite's pragma semantics.
    """
    executed: list[str] = []

    class _FakeConn:
        row_factory: Any = None

        def execute(self, sql: str) -> "_FakeConn":
            executed.append(sql)
            return self

        def __enter__(self) -> "_FakeConn":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr("autoinfo.kb.sqlite3.connect", lambda _path: _FakeConn())
    SQLiteIndex(Path("/tmp/fake-kb.db"))._connect()

    assert any(sql.startswith("PRAGMA busy_timeout=") for sql in executed), (
        f"_connect() did not execute PRAGMA busy_timeout (executed={executed})"
    )
