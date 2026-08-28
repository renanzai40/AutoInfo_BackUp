"""Agent callback system — push-based agent subscription, persisted in SQLite.

NOT shared with the existing ``set_domain_webhooks`` system.
Events fire when products are generated: ``new_digest``, ``new_report``,
``new_tutorial``.  Agents subscribe via ``register_agent_callback`` and
receive HTTP POST notifications when matching products are created.

Callbacks survive MCP server restarts because they are stored in the
same ``autoinfo.db`` SQLite database used by the KB pipeline (shared
connection pattern, ``CREATE TABLE IF NOT EXISTS``).

Notifications are delivered through a **durable outbox** (SQLite): the
event row is persisted BEFORE any delivery attempt, and a background
worker drains the outbox asynchronously. Rows survive process restarts —
on startup, undelivered rows are requeued and the worker re-attempts
them. Fire-and-forget: no retry/backoff, and the callback path never
blocks or fails the caller.

Usage::

    cid = register_agent_callback("https://agent.example.com/hook",
                                  ["new_digest", "new_report"])
    notify_agent("new_digest", {"title": "Weekly Digest", ...})
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite table DDL
# ---------------------------------------------------------------------------

_AGENT_CALLBACK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agent_callbacks (
    callback_id TEXT PRIMARY KEY,
    agent_url   TEXT NOT NULL,
    events      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

# Durable outbox: one row per notification event. The row is the source of
# truth — written BEFORE any delivery attempt. Status transitions:
#   pending → delivered | failed
#   failed  → pending  (only via requeue_undelivered() at process start)
_AGENT_OUTBOX_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agent_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT NOT NULL,
    payload         TEXT NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    trace_id        TEXT NOT NULL,
    product_id      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    delivered_at    TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT ''
);
"""

_VALID_EVENTS = {
    "new_digest",
    "new_report",
    "new_tutorial",
    "source_requires_key",
}

_SCHEMA_VERSION = 1

_OUTBOX_STATUS_PENDING = "pending"
_OUTBOX_STATUS_DELIVERED = "delivered"
_OUTBOX_STATUS_FAILED = "failed"

# In-process counters (same pattern as billing._stripe_sync_failures).
_delivery_failures_total = 0
_delivery_failures_lock = threading.Lock()
# Serializes outbox drains so concurrent drains never double-deliver.
_drain_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Connection helpers (same pattern as delivery_log.py / SQLiteIndex)
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    """Return the default path to ``autoinfo.db`` in CWD."""
    return Path.cwd() / "autoinfo.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the shared SQLite database.

    Creates the ``agent_callbacks`` table on first connection (idempotent).
    Uses WAL journal mode for better concurrency with the KB pipeline, and a
    busy_timeout so parallel writers wait for the lock instead of raising
    ``OperationalError: database is locked`` (issue #67 — high-concurrency
    product generation drops outbox events without it).
    """
    resolved = db_path or _default_db_path()
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    # busy_timeout FIRST — before any other pragma — so the WAL transition
    # and every later statement wait on the lock instead of raising
    # OperationalError under write contention (issue #67).  Same contract as
    # the KB pipeline (kb.py): default 30s, env-configurable via
    # AUTOINFO_DB_BUSY_TIMEOUT_MS.
    from autoinfo.kb import _db_busy_timeout_ms  # noqa: PLC0415

    _ = conn.execute(f"PRAGMA busy_timeout={_db_busy_timeout_ms()}")
    _ = conn.execute("PRAGMA journal_mode=WAL")
    _ = conn.execute("PRAGMA synchronous=NORMAL")
    _ = conn.executescript(_AGENT_CALLBACK_TABLE_DDL)
    _ = conn.executescript(_AGENT_OUTBOX_TABLE_DDL)
    return conn


def _now_utc() -> str:
    """Return ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite Row to the dict shape expected by callers."""
    return {
        "callback_id": row["callback_id"],
        "agent_url": row["agent_url"],
        "events": json.loads(row["events"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_agent_callback(agent_url: str, events: list[str]) -> str:
    """Register a new agent callback URL for specified events.

    Persisted to SQLite so callbacks survive server restarts.

    Args:
        agent_url: Callback URL (must start with ``http://`` or ``https://``).
        events: List of event names from {new_digest, new_report,
            new_tutorial, source_requires_key}.

    Returns:
        A short callback ID string (8-char UUID prefix).

    Raises:
        ValueError: If *agent_url* is invalid or *events* contains unknown names.
    """
    if not agent_url.startswith(("http://", "https://")):
        raise ValueError(
            (
                f"Invalid agent_url: must start with http:// or https://, "
                f"got {agent_url!r}"
            )
        )

    invalid = [e for e in events if e not in _VALID_EVENTS]
    if invalid:
        raise ValueError(
            f"Invalid events: {invalid}. Valid events: {sorted(_VALID_EVENTS)}"
        )

    callback_id = str(uuid.uuid4())[:8]
    now = _now_utc()
    events_json = json.dumps(list(events))

    with _connect() as conn:
        _ = conn.execute(
            (
                "INSERT INTO agent_callbacks (callback_id, agent_url, events, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (callback_id, agent_url, events_json, now, now),
        )
        conn.commit()

    logger.info(
        "Registered agent callback %s for %s (events: %s)",
        callback_id, agent_url, events,
    )
    return callback_id


def list_agent_callbacks() -> list[dict[str, Any]]:
    """Return all registered agent callbacks as a list of dicts.

    Reads from SQLite so results reflect the persisted state.
    """
    with _connect() as conn:
        rows = conn.execute(
            (
                "SELECT callback_id, agent_url, events, created_at, updated_at "
                "FROM agent_callbacks ORDER BY created_at DESC"
            )
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def remove_agent_callback(callback_id: str) -> bool:
    """Remove a registered callback from the SQLite store.

    Returns:
        ``True`` if the callback was found and removed, ``False`` otherwise.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM agent_callbacks WHERE callback_id = ?",
            (callback_id,),
        )
        conn.commit()
        removed = cursor.rowcount > 0
    if removed:
        logger.info("Removed agent callback %s", callback_id)
    return removed


def notify_agent(event: str, payload: dict[str, Any]) -> int:
    """Fire-and-forget POST of *payload* to every agent URL registered for *event*.

    Sync-safe entry point backed by the durable outbox: the event row is
    persisted to SQLite BEFORE any delivery attempt, and the actual HTTP
    POST happens on a background worker thread. Individual delivery
    failures are logged and counted (``delivery_failures_total``) but
    never propagate. No retry / backoff.

    Reads target callbacks from SQLite.

    Args:
        event: One of ``new_digest``, ``new_report``, ``new_tutorial``,
            ``source_requires_key``.
        payload: Arbitrary JSON-serialisable dict to POST.

    Returns:
        The outbox row id, or ``0`` if the event could not be enqueued.
    """
    return enqueue_agent_notification(
        event=event,
        payload=payload,
        trace_id=str(uuid.uuid4()),
        product_id="",
    )


def notify_source_requires_key(
    source: str,
    source_type: str,
    key_ref: str,
    domain: str,
    trace_id: str | None = None,
) -> int:
    """Fire-and-forget push that a configured source lacks its required credential.

    B3 escalation event (user-lifecycle-definition.md §4.1: "source API key
    expired" is a B3 intervention case): delivered through the durable
    outbox to every agent callback subscribed to ``source_requires_key``.

    The payload carries the source name and the **environment variable
    NAME** (``key_ref``) that must be set — never the key value.

    Args:
        source: Source name (e.g. ``"NYT"``).
        source_type: Source type (e.g. ``"nyt"``).
        key_ref: Env var name that supplies the credential, e.g.
            ``"AUTOINFO_NYT_API_KEY"``. Never the value itself.
        domain: Domain the source belongs to.
        trace_id: Optional per-event trace identifier (generated when omitted).

    Returns:
        The outbox row id, or ``0`` if the event could not be enqueued.
    """
    payload = {
        "source": source,
        "source_type": source_type,
        "key_ref": key_ref,
        "domain": domain,
        "severity": "critical",
        "triggered_at": _now_utc(),
    }
    return enqueue_agent_notification(
        event="source_requires_key",
        payload=payload,
        trace_id=trace_id or str(uuid.uuid4()),
        product_id="",
    )


# ---------------------------------------------------------------------------
# Durable outbox — rows survive process restarts; a worker drains async
# ---------------------------------------------------------------------------


def get_delivery_failures() -> int:
    """Return the in-process count of failed agent callback deliveries."""
    with _delivery_failures_lock:
        return _delivery_failures_total


def enqueue_agent_notification(
    event: str,
    payload: Any,
    trace_id: str,
    product_id: str = "",
) -> int:
    """Durably enqueue an agent notification into the SQLite outbox.

    The outbox row is the source of truth: it is inserted BEFORE any
    delivery attempt, so the event survives process restarts (a crashed
    process cannot lose it). After the insert, a daemon worker is
    scheduled to drain the outbox asynchronously — this function never
    blocks on delivery and never raises into the caller.

    Args:
        event: One of ``new_digest``, ``new_report``, ``new_tutorial``,
            ``source_requires_key``.
        payload: JSON-serialisable generated output (the product payload).
        trace_id: Per-event trace identifier (canonical payload key).
        product_id: Product identifier, e.g. ``"medical-research-week"``.

    Returns:
        The outbox row id, or ``0`` if the event could not be persisted.
    """
    if event not in _VALID_EVENTS:
        logger.warning("Unknown event %r — skipping notification", event)
        return 0
    try:
        payload_json = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        logger.warning(
            "Payload for event %r is not JSON-serialisable", event, exc_info=True
        )
        return 0

    now = _now_utc()
    row_id = 0
    try:
        with _connect() as conn:
            cursor = conn.execute(
                (
                    "INSERT INTO agent_outbox "
                    "(event, payload, schema_version, trace_id, product_id, "
                    " status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    event, payload_json, _SCHEMA_VERSION, trace_id, product_id,
                    _OUTBOX_STATUS_PENDING, now,
                ),
            )
            conn.commit()
            row_id = int(cursor.lastrowid or 0)
    except Exception:
        logger.warning(
            "Failed to persist outbox row for event %r", event, exc_info=True
        )
        return 0

    _schedule_drain()
    return row_id


def requeue_undelivered() -> int:
    """Requeue undelivered outbox rows after a process restart.

    Flips ``failed`` rows back to ``pending`` so the next worker drain
    re-attempts delivery. ``pending`` rows are untouched (they were never
    attempted). Returns the number of requeued rows.
    """
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_outbox SET status = ? WHERE status = ?",
                (_OUTBOX_STATUS_PENDING, _OUTBOX_STATUS_FAILED),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
    except Exception:
        logger.warning(
            "Failed to requeue undelivered outbox rows", exc_info=True
        )
        return 0


def list_outbox(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent outbox rows (newest first) for inspection/QA."""
    with _connect() as conn:
        rows = conn.execute(
            (
                "SELECT id, event, schema_version, trace_id, product_id, "
                "status, created_at, delivered_at, last_error "
                "FROM agent_outbox ORDER BY id DESC LIMIT ?"
            ),
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _schedule_drain() -> None:
    """Start a daemon worker thread that drains the outbox."""
    thread = threading.Thread(
        target=_drain_outbox,
        name="agent-outbox-drain",
        daemon=True,
    )
    thread.start()


def _update_outbox_status(
    row_id: int,
    status: str,
    delivered_at: str = "",
    last_error: str = "",
) -> None:
    """Persist a new outbox status for *row_id* (best-effort)."""
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE agent_outbox SET status = ?, delivered_at = ?, "
                "last_error = ? WHERE id = ?",
                (status, delivered_at, last_error, row_id),
            )
            conn.commit()
    except Exception:
        logger.warning(
            "Failed to update outbox row %s", row_id, exc_info=True
        )


def _drain_outbox() -> None:
    """Deliver all pending outbox rows to their registered agent URLs.

    Serialized by ``_drain_lock`` so concurrent drains never double-deliver.
    No retry / backoff (fire-and-forget by design): a failed attempt marks
    the row ``failed`` and counts ``delivery_failures_total``; the row is
    re-attempted only by ``requeue_undelivered()`` after a process restart.
    """
    if not _drain_lock.acquire(blocking=False):
        return
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, event, payload, schema_version, trace_id, product_id "
                "FROM agent_outbox WHERE status = ? ORDER BY id",
                (_OUTBOX_STATUS_PENDING,),
            ).fetchall()
        if not rows:
            return

        with _connect() as conn:
            cb_rows = conn.execute(
                "SELECT callback_id, agent_url, events FROM agent_callbacks"
            ).fetchall()
        target_by_event: dict[str, list[tuple[str, str]]] = {}
        for cb in cb_rows:
            for ev in json.loads(cb["events"]):
                target_by_event.setdefault(ev, []).append(
                    (cb["callback_id"], cb["agent_url"])
                )

        with httpx.Client(timeout=10.0) as client:
            for row in rows:
                body = {
                    "event": row["event"],
                    "payload": json.loads(row["payload"]),
                    "schema_version": row["schema_version"],
                    "trace_id": row["trace_id"],
                    "product_id": row["product_id"],
                }
                subs = target_by_event.get(row["event"], [])
                if not subs:
                    _update_outbox_status(
                        row["id"], _OUTBOX_STATUS_DELIVERED, _now_utc()
                    )
                    continue
                delivered = True
                for callback_id, agent_url in subs:
                    try:
                        resp = client.post(
                            agent_url,
                            json=body,
                            headers={"Content-Type": "application/json"},
                        )
                        _ = resp.raise_for_status()
                        logger.info(
                            "Notified agent %s for event %s: HTTP %s",
                            callback_id, row["event"], resp.status_code,
                        )
                    except Exception:
                        delivered = False
                        logger.warning(
                            "Failed to notify agent %s at %s (outbox row %s)",
                            callback_id, agent_url, row["id"],
                            exc_info=True,
                        )
                if delivered:
                    _update_outbox_status(
                        row["id"], _OUTBOX_STATUS_DELIVERED, _now_utc()
                    )
                else:
                    _update_outbox_status(
                        row["id"], _OUTBOX_STATUS_FAILED,
                        last_error="delivery failed",
                    )
                    global _delivery_failures_total
                    with _delivery_failures_lock:
                        _delivery_failures_total += 1
    finally:
        _drain_lock.release()


def _startup_requeue() -> None:
    """At process start: requeue undelivered rows and schedule a drain.

    Import-time hook so events enqueued before a crash/exit are
    re-attempted by the new process. Guarded — the module import must
    never fail because of outbox state.
    """
    requeued = requeue_undelivered()
    undelivered = 0
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM agent_outbox WHERE status != ?",
                (_OUTBOX_STATUS_DELIVERED,),
            ).fetchone()
        undelivered = int(row["n"]) if row else 0
    except Exception:
        pass
    if requeued or undelivered:
        logger.info(
            "Startup: %d requeued, %d undelivered agent outbox row(s); "
            "scheduling drain",
            requeued, undelivered,
        )
        _schedule_drain()


_startup_requeue()
