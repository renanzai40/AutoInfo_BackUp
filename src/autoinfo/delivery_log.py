"""Delivery log — append-only record of delivery attempts with retry tracking.

Every call to :func:`append_delivery_log` writes one entry to the
``delivery_log`` SQLite table.  No UPDATE or DELETE operations are exposed
(append-only semantics).

Query via :func:`query_delivery_log` with optional filters by subscription_id,
channel, and time range.  Aggregated stats via :func:`get_delivery_stats`.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoinfo.models import DeliveryLog

# ---------------------------------------------------------------------------
# Table DDL (append-only)
# ---------------------------------------------------------------------------

_DELIVERY_LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS delivery_log (
    log_id          TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL DEFAULT '',
    channel         TEXT NOT NULL,
    message_type    TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_attempt    TEXT NOT NULL,
    error_message   TEXT NOT NULL DEFAULT '',
    sla_tier        TEXT NOT NULL DEFAULT 'standard'
);

CREATE INDEX IF NOT EXISTS idx_delivery_log_subscription
    ON delivery_log(subscription_id);

CREATE INDEX IF NOT EXISTS idx_delivery_log_channel
    ON delivery_log(channel);

CREATE INDEX IF NOT EXISTS idx_delivery_log_last_attempt
    ON delivery_log(last_attempt);
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    """Return the default path to ``autoinfo.db`` in CWD."""
    return Path.cwd() / "autoinfo.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the delivery log SQLite database.

    Creates the ``delivery_log`` table on first connection (idempotent).
    """
    resolved = db_path or _default_db_path()
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_DELIVERY_LOG_TABLE_DDL)
    return conn


def _now_utc() -> str:
    """Return ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_delivery_log(row: sqlite3.Row) -> DeliveryLog:
    """Convert a SQLite row to a :class:`DeliveryLog` instance."""
    return DeliveryLog(
        log_id=row["log_id"],
        subscription_id=row["subscription_id"],
        channel=row["channel"],
        message_type=row["message_type"],
        status=row["status"],
        attempt_count=row["attempt_count"],
        last_attempt=row["last_attempt"],
        error_message=row["error_message"] or "",
        sla_tier=row["sla_tier"] or "standard",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_delivery_log(
    subscription_id: str,
    channel: str,
    message_type: str,
    status: str,
    attempt_count: int,
    error_message: str = "",
    sla_tier: str = "standard",
    db_path: Path | None = None,
) -> DeliveryLog:
    """Append one entry to the delivery log.

    Parameters
    ----------
    subscription_id:
        Subscription ID this delivery relates to (may be empty for
        system-triggered deliveries without a subscription).
    channel:
        Delivery channel name (e.g. ``"smtp"``, ``"webhook"``).
    message_type:
        Type of message delivered (e.g. ``"digest"``, ``"report"``,
        ``"alert"``).
    status:
        Outcome — ``"success"``, ``"failed"``, or ``"retrying"``.
    attempt_count:
        Which attempt number this is (1-based).
    error_message:
        Error details when status is ``"failed"`` or ``"retrying"``.
    sla_tier:
        SLA classification — ``"critical"``, ``"standard"``, or ``"bulk"``.
    db_path:
        Path to the SQLite database.  Defaults to ``autoinfo.db`` in CWD.

    Returns
    -------
    DeliveryLog
        The entry that was written.
    """
    log_id = str(uuid.uuid4())
    timestamp = _now_utc()

    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO delivery_log
               (log_id, subscription_id, channel, message_type, status,
                attempt_count, last_attempt, error_message, sla_tier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id,
                subscription_id,
                channel,
                message_type,
                status,
                attempt_count,
                timestamp,
                error_message,
                sla_tier,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return DeliveryLog(
        log_id=log_id,
        subscription_id=subscription_id,
        channel=channel,
        message_type=message_type,
        status=status,
        attempt_count=attempt_count,
        last_attempt=timestamp,
        error_message=error_message,
        sla_tier=sla_tier,
    )


def query_delivery_log(
    subscription_id: str | None = None,
    channel: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[DeliveryLog]:
    """Query the delivery log with optional filters.

    All filters are **optional** — omit a filter to skip it.
    Filters are combined with AND logic.

    Parameters
    ----------
    subscription_id:
        Only entries whose ``subscription_id`` equals this value.
    channel:
        Only entries whose ``channel`` equals this value.
    date_from:
        Only entries with ``last_attempt >=`` this ISO-8601 string.
    date_to:
        Only entries with ``last_attempt <=`` this ISO-8601 string.
    limit:
        Maximum number of entries to return (default 100).
    offset:
        Pagination offset (default 0).
    db_path:
        Path to the SQLite database.  Defaults to ``autoinfo.db`` in CWD.

    Returns
    -------
    list[DeliveryLog]
        Matching entries ordered by **last_attempt descending** (newest first).
    """
    clauses: list[str] = []
    params: list[Any] = []

    if subscription_id:
        clauses.append("subscription_id = ?")
        params.append(subscription_id)
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if date_from:
        clauses.append("last_attempt >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("last_attempt <= ?")
        params.append(date_to)

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = (
        f"SELECT * FROM delivery_log {where}"
        " ORDER BY last_attempt DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_delivery_log(r) for r in rows]
    finally:
        conn.close()


def get_delivery_stats(
    channel: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Return aggregated delivery statistics.

    Parameters
    ----------
    channel:
        Optional channel filter.
    date_from:
        Only entries with ``last_attempt >=`` this ISO-8601 string.
    date_to:
        Only entries with ``last_attempt <=`` this ISO-8601 string.
    db_path:
        Path to the SQLite database.  Defaults to ``autoinfo.db`` in CWD.

    Returns
    -------
    dict
        Dict with keys ``total``, ``success``, ``failed``, ``retrying``,
        ``by_channel``, ``by_sla_tier``, and ``period``.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if date_from:
        clauses.append("last_attempt >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("last_attempt <= ?")
        params.append(date_to)

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    conn = _connect(db_path)
    try:
        # Total count and per-status breakdown
        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM delivery_log {where}", params
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        success = conn.execute(
            f"SELECT COUNT(*) as cnt FROM delivery_log {where} AND status = 'success'",
            params,
        ).fetchone()["cnt"]

        failed = conn.execute(
            f"SELECT COUNT(*) as cnt FROM delivery_log {where} AND status = 'failed'",
            params,
        ).fetchone()["cnt"]

        retrying = conn.execute(
            f"SELECT COUNT(*) as cnt FROM delivery_log {where} AND status = 'retrying'",
            params,
        ).fetchone()["cnt"]

        # Per-channel breakdown
        by_channel_raw = conn.execute(
            f"SELECT channel, COUNT(*) as cnt FROM delivery_log {where} GROUP BY channel ORDER BY cnt DESC",
            params,
        ).fetchall()
        by_channel = {r["channel"]: r["cnt"] for r in by_channel_raw}

        # Per-SLA-tier breakdown
        by_sla_raw = conn.execute(
            f"SELECT sla_tier, COUNT(*) as cnt FROM delivery_log {where} GROUP BY sla_tier ORDER BY cnt DESC",
            params,
        ).fetchall()
        by_sla_tier = {r["sla_tier"]: r["cnt"] for r in by_sla_raw}

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "retrying": retrying,
            "by_channel": by_channel,
            "by_sla_tier": by_sla_tier,
            "period": {
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        }
    finally:
        conn.close()


def list_active_deliveries(
    db_path: Path | None = None,
) -> list[DeliveryLog]:
    """Return deliveries with active/pending status (``"retrying"``, ``"pending"``, ``"in_progress"``).

    Parameters
    ----------
    db_path:
        Path to the SQLite database.  Defaults to ``autoinfo.db`` in CWD.

    Returns
    -------
    list[DeliveryLog]
        Matching entries ordered by **last_attempt descending** (newest first).
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM delivery_log
               WHERE status IN ('retrying', 'pending', 'in_progress')
               ORDER BY last_attempt DESC""",
        ).fetchall()
        return [_row_to_delivery_log(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Convenience: ensure the table exists
# ---------------------------------------------------------------------------


def init_delivery_log_table(db_path: Path | None = None) -> None:
    """Explicitly create the ``delivery_log`` table and indexes.

    Idempotent — safe to call multiple times.  The table is also created
    lazily on first :func:`append_delivery_log` or :func:`query_delivery_log`.
    """
    conn = _connect(db_path)
    try:
        conn.executescript(_DELIVERY_LOG_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()
