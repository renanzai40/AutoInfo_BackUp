"""M4T38 — agent callback test suite: httpx.MockTransport + restart durability.

Covers the four mandated scenarios for the durable-outbox push delivery:

1. **Happy path**: register_agent_callback → enqueue_agent_notification → drain
   worker POSTs; the captured request body matches the canonical payload
   ``{event, payload, schema_version: 1, trace_id, product_id}``.
2. **Failure path**: callback URL down (MockTransport raises) → enqueue still
   succeeds (fire-and-forget: generation success is inviolable), the outbox
   row moves to ``failed``, and ``delivery_failures_total`` is incremented
   (module counter + ``metrics.get_metrics()`` surface).
3. **Durability**: the outbox row is written BEFORE any delivery attempt;
   undrained rows survive the "restart" window and are re-delivered by a
   later drain; ``requeue_undelivered()`` (the documented restart hook,
   called by ``_startup_requeue()`` at module import) flips ``failed`` rows
   back to ``pending`` and a subsequent drain re-delivers them.
4. **Multi-callback**: 2 callbacks registered for the same event both receive
   the POST in a single drain; event filtering (a callback subscribed to a
   different event does not receive it).

Hermeticity — zero real network, zero repo pollution:

- Every test patches ``autoinfo.agent_callback._default_db_path`` to a
  per-test ``tmp_path`` SQLite DB. All ``_connect()`` calls (including the
  restart simulation) open **fresh connections** against that DB, so the
  suite never touches the repo-root ``autoinfo.db``.
- The drain worker builds its client via the module's ``httpx.Client`` name;
  tests patch that name so every client is constructed on a
  ``httpx.MockTransport`` that either captures requests or raises — no socket
  is ever opened.

Note on restart simulation: ``requeue_undelivered()`` is the module's own
restart hook (invoked at import time by ``_startup_requeue()``). Each
``_connect()`` call is a brand-new sqlite3 connection, so calling it after a
failed drain exercises the exact failed→pending transition a fresh process
would run, against the same on-disk DB.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx
import pytest

import autoinfo.agent_callback as ac
from autoinfo.metrics import get_metrics

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def ac_module(monkeypatch, tmp_path):
    """Hermetic agent_callback module: per-test tmp SQLite DB.

    Patches ``_default_db_path`` so every connection (register, outbox,
    requeue, drain) lands in ``tmp_path/autoinfo.db`` — tables are created
    idempotently by ``_connect``. The repo-root ``autoinfo.db`` is never
    touched.
    """
    db_path = tmp_path / "autoinfo.db"
    monkeypatch.setattr(ac, "_default_db_path", lambda: db_path)
    return ac


# Captured once at module import — BEFORE any monkeypatching — so factories
# created by successive _patch_client calls in one test always delegate to
# the real httpx.Client (never to an earlier factory, which would double-
# inject ``transport``).
_REAL_HTTPX_CLIENT = httpx.Client


def _patch_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Make the drain worker's ``httpx.Client`` use *transport*.

    ``_drain_outbox`` constructs ``httpx.Client(timeout=10.0)`` via the
    module-level ``httpx`` import; replacing the ``Client`` attribute injects
    the MockTransport into every request the worker makes. monkeypatch
    restores the real ``Client`` at teardown.
    """

    def _client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return _REAL_HTTPX_CLIENT(transport=transport, *args, **kwargs)

    monkeypatch.setattr(ac.httpx, "Client", _client_factory)


def _make_capture_transport(requests_by_url: dict[str, list[httpx.Request]]):
    """MockTransport recording every request, per callback URL."""

    def _handler(request: httpx.Request) -> httpx.Response:
        requests_by_url.setdefault(str(request.url), []).append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(_handler)


def _make_fail_transport() -> httpx.MockTransport:
    """MockTransport raising ConnectError — simulates an unreachable URL."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.MockTransport(_handler)


def _get_row(ac_module, row_id: int) -> dict[str, Any]:
    """Fetch an outbox row by id (fresh connection each call)."""
    for row in ac_module.list_outbox(limit=500):
        if row["id"] == row_id:
            return row
    raise AssertionError(f"outbox row {row_id} not found")


def _wait_outbox(ac_module, row_id: int, timeout: float = 5.0) -> dict[str, Any]:
    """Wait until the row leaves ``pending`` (worker drained it).

    The drain runs on a daemon worker thread; poll ``list_outbox`` (each call
    opens a fresh connection) until the status transitions or the timeout
    expires.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = _get_row(ac_module, row_id)
        if row["status"] != ac._OUTBOX_STATUS_PENDING:
            return row
        time.sleep(0.02)
    raise AssertionError(
        f"outbox row {row_id} never left 'pending' (status: {row['status']!r})"
    )


def _assert_canonical_payload(
    body: dict[str, Any],
    *,
    event: str,
    payload: Any,
    trace_id: str,
    product_id: str,
) -> None:
    """Assert the exact canonical payload contract (5 keys, schema_version 1)."""
    assert set(body) == {
        "event",
        "payload",
        "schema_version",
        "trace_id",
        "product_id",
    }, f"unexpected payload keys: {sorted(body)}"
    assert body["event"] == event
    assert body["payload"] == payload
    assert body["schema_version"] == 1
    assert body["trace_id"] == trace_id
    assert body["product_id"] == product_id


_CALLBACK_URL = "https://agent.example.com/hook"
_TRACE_ID = "trace-38-abc"
_PRODUCT_ID = "medical-research-weekly"


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_post_matches_canonical_payload(ac_module, monkeypatch):
    """Register → enqueue → drain: POST body is the canonical 5-key payload."""
    captured: dict[str, list[httpx.Request]] = {}
    _patch_client(monkeypatch, _make_capture_transport(captured))

    ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest"])

    payload = {"title": "Weekly Digest", "entry_count": 2}
    row_id = ac_module.enqueue_agent_notification(
        event="new_digest",
        payload=payload,
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )
    assert row_id > 0, "enqueue must return the outbox row id"

    row = _wait_outbox(ac_module, row_id)
    assert row["status"] == "delivered"
    assert row["delivered_at"], "delivered row must record delivered_at"

    assert list(captured) == [_CALLBACK_URL], f"unexpected URLs: {list(captured)}"
    (request,) = captured[_CALLBACK_URL]
    assert request.method == "POST"
    assert request.headers["content-type"].startswith("application/json")
    _assert_canonical_payload(
        json.loads(request.content),
        event="new_digest",
        payload=payload,
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )


def test_notify_agent_convenience_generates_trace_id(ac_module, monkeypatch):
    """``notify_agent`` convenience wrapper fills trace_id; product_id empty."""
    captured: dict[str, list[httpx.Request]] = {}
    _patch_client(monkeypatch, _make_capture_transport(captured))
    ac_module.register_agent_callback(_CALLBACK_URL, ["new_report"])

    payload = {"title": "Q3 Report"}
    row_id = ac_module.notify_agent(event="new_report", payload=payload)
    assert row_id > 0

    row = _wait_outbox(ac_module, row_id)
    assert row["status"] == "delivered"
    (request,) = captured[_CALLBACK_URL]
    body = json.loads(request.content)
    assert body["event"] == "new_report"
    assert body["product_id"] == ""
    assert body["trace_id"], "notify_agent must generate a trace_id"
    assert body["payload"] == payload
    assert body["schema_version"] == 1


def test_register_list_remove_callbacks(ac_module):
    """CRUD round-trip plus input validation."""
    cid = ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest", "new_tutorial"])
    assert cid and len(cid) == 8

    listed = ac_module.list_agent_callbacks()
    assert len(listed) == 1
    assert listed[0]["callback_id"] == cid
    assert listed[0]["agent_url"] == _CALLBACK_URL
    assert listed[0]["events"] == ["new_digest", "new_tutorial"]

    assert ac_module.remove_agent_callback(cid) is True
    assert ac_module.list_agent_callbacks() == []
    assert ac_module.remove_agent_callback(cid) is False

    with pytest.raises(ValueError):
        ac_module.register_agent_callback("ftp://not-http", ["new_digest"])
    with pytest.raises(ValueError):
        ac_module.register_agent_callback(_CALLBACK_URL, ["new_unknown_event"])


# ---------------------------------------------------------------------------
# 2. Failure path
# ---------------------------------------------------------------------------


def test_failure_url_down_enqueue_succeeds_row_failed_metric_incremented(
    ac_module, monkeypatch
):
    """Callback URL down: enqueue/generation still succeeds; row→failed; metric+1.

    The failure is exercised at the enqueue/worker level: the outbox row is
    persisted, the drain worker attempts the POST through a MockTransport
    that raises, the attempt fails, the row is marked ``failed`` with
    ``last_error`` and ``delivery_failures_total`` is incremented — exactly
    the fire-and-forget contract.
    """
    _patch_client(monkeypatch, _make_fail_transport())
    ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest"])

    failures_before = ac_module.get_delivery_failures()

    row_id = ac_module.enqueue_agent_notification(
        event="new_digest",
        payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )
    assert row_id > 0, "enqueue must succeed even when delivery will fail"

    row = _wait_outbox(ac_module, row_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "delivery failed"
    assert row["delivered_at"] == ""

    # Module counter incremented exactly once.
    assert ac_module.get_delivery_failures() == failures_before + 1

    # The metrics surface reads the same live counter (metrics.py recomputes
    # delivery_failures_total per call via get_delivery_failures()).
    assert get_metrics()["delivery_failures_total"] == ac_module.get_delivery_failures()


def test_unknown_event_never_enqueued(ac_module):
    """Invalid event names are rejected at enqueue — no row, no delivery."""
    row_id = ac_module.enqueue_agent_notification(
        event="new_unknown", payload={}, trace_id=_TRACE_ID
    )
    assert row_id == 0
    assert ac_module.list_outbox(limit=10) == []


# ---------------------------------------------------------------------------
# 3. Durability
# ---------------------------------------------------------------------------


def test_outbox_row_written_before_delivery_survives_undrained_window(
    ac_module, monkeypatch
):
    """Row persisted before any POST; an undrained row is re-delivered later.

    Simulates "kill the worker before delivery": the drain is suppressed
    (worker never starts), the row is already on disk as ``pending``; after
    the "restart", a drain with a working transport delivers it — proving the
    outbox row alone survives the not-yet-drained window.
    """
    captured: dict[str, list[httpx.Request]] = {}
    ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest"])

    # Worker suppressed: record that a drain was scheduled but never run.
    scheduled: list[int] = []
    original_schedule = ac_module._schedule_drain

    def _suppressed_schedule() -> None:
        scheduled.append(1)

    monkeypatch.setattr(ac_module, "_schedule_drain", _suppressed_schedule)

    row_id = ac_module.enqueue_agent_notification(
        event="new_digest",
        payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )
    assert row_id > 0
    assert scheduled == [1], "drain was scheduled but must not run yet"
    assert _get_row(ac_module, row_id)["status"] == "pending"
    assert captured == {}, "no POST may have happened before the drain"

    # "Restart": the working transport is now in place and the drain runs
    # (the real _startup_requeue() hook schedules exactly this drain).
    _patch_client(monkeypatch, _make_capture_transport(captured))
    monkeypatch.setattr(ac_module, "_schedule_drain", original_schedule)
    ac_module._schedule_drain()

    row = _wait_outbox(ac_module, row_id)
    assert row["status"] == "delivered"
    (request,) = captured[_CALLBACK_URL]
    _assert_canonical_payload(
        json.loads(request.content),
        event="new_digest",
        payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )


def test_restart_requeue_redelivers_failed_row(ac_module, monkeypatch):
    """``requeue_undelivered()`` (restart hook) re-delivers a failed row.

    Full restart cycle against one on-disk DB: (1) URL down → row ``failed``
    + metric incremented; (2) "process B" — requeue_undelivered() on a fresh
    connection flips ``failed``→``pending``; (3) drain with a working
    transport re-delivers the row with the canonical payload.
    """
    ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest"])
    _patch_client(monkeypatch, _make_fail_transport())

    failures_before = ac_module.get_delivery_failures()
    row_id = ac_module.enqueue_agent_notification(
        event="new_digest",
        payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )
    assert _wait_outbox(ac_module, row_id)["status"] == "failed"
    assert ac_module.get_delivery_failures() == failures_before + 1

    # --- "restart" ---
    assert ac_module.requeue_undelivered() == 1, "exactly one row requeued"
    assert _get_row(ac_module, row_id)["status"] == "pending"

    # Re-delivery against a working transport — no additional failure counted.
    captured: dict[str, list[httpx.Request]] = {}
    _patch_client(monkeypatch, _make_capture_transport(captured))
    ac_module._schedule_drain()

    row = _wait_outbox(ac_module, row_id)
    assert row["status"] == "delivered"
    assert ac_module.get_delivery_failures() == failures_before + 1
    (request,) = captured[_CALLBACK_URL]
    _assert_canonical_payload(
        json.loads(request.content),
        event="new_digest",
        payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )


def test_requeue_is_noop_when_nothing_failed(ac_module):
    """Fresh outbox: requeue_undelivered() flips nothing."""
    assert ac_module.requeue_undelivered() == 0


# ---------------------------------------------------------------------------
# 4. Multi-callback
# ---------------------------------------------------------------------------


def test_multi_callback_both_subscribers_receive_event(ac_module, monkeypatch):
    """2 callbacks registered → one enqueue → both receive the same POST."""
    url_b = "https://agent-two.example.com/hook"
    captured: dict[str, list[httpx.Request]] = {}
    _patch_client(monkeypatch, _make_capture_transport(captured))

    ac_module.register_agent_callback(_CALLBACK_URL, ["new_digest"])
    ac_module.register_agent_callback(url_b, ["new_digest", "new_tutorial"])

    payload = {"title": "Weekly Digest", "entry_count": 2}
    row_id = ac_module.enqueue_agent_notification(
        event="new_digest",
        payload=payload,
        trace_id=_TRACE_ID,
        product_id=_PRODUCT_ID,
    )
    assert _wait_outbox(ac_module, row_id)["status"] == "delivered"

    # Both subscribers received exactly one POST each, identical bodies.
    assert set(captured) == {_CALLBACK_URL, url_b}
    for url in (_CALLBACK_URL, url_b):
        (request,) = captured[url]
        assert request.method == "POST"
        _assert_canonical_payload(
            json.loads(request.content),
            event="new_digest",
            payload=payload,
            trace_id=_TRACE_ID,
            product_id=_PRODUCT_ID,
        )


def test_multi_callback_event_filtering(ac_module, monkeypatch):
    """A callback subscribed to other events does not receive this one."""
    url_b = "https://agent-two.example.com/hook"
    captured: dict[str, list[httpx.Request]] = {}
    _patch_client(monkeypatch, _make_capture_transport(captured))

    ac_module.register_agent_callback(_CALLBACK_URL, ["new_tutorial"])
    ac_module.register_agent_callback(url_b, ["new_digest"])

    row_id = ac_module.enqueue_agent_notification(
        event="new_digest", payload={"title": "Weekly Digest"},
        trace_id=_TRACE_ID, product_id=_PRODUCT_ID,
    )
    assert _wait_outbox(ac_module, row_id)["status"] == "delivered"

    # Only the new_digest subscriber is POSTed; the other is untouched.
    assert set(captured) == {url_b}
    assert _CALLBACK_URL not in captured


# ---------------------------------------------------------------------------
# 5. High-concurrency outbox writes (backup issue #67)
# ---------------------------------------------------------------------------


def test_concurrent_outbox_writes_no_lost_events(ac_module, monkeypatch):
    """N threads writing distinct events to the same outbox DB lose none.

    Issue #67: parallel product generation (multi-domain × high LLM
    concurrency) hit ``sqlite3.OperationalError: database is locked`` on the
    outbox INSERT because ``_connect()`` set no ``busy_timeout`` — SQLite's
    default 0 makes a write fail immediately under WAL contention, and
    ``enqueue_agent_notification`` swallows the error returning 0, silently
    dropping the event.  With the KB pipeline's busy_timeout applied, the
    writers wait for the lock instead.
    """
    import threading

    # ac_module already patches _default_db_path to tmp_path/autoinfo.db.
    n_events = 16
    results: list[int] = []
    lock = threading.Lock()

    def _writer(i: int) -> None:
        row_id = ac_module.enqueue_agent_notification(
            event="new_digest",
            payload={"writer": i},
            trace_id=f"conc-{i}",
            product_id=f"writer-{i}",
        )
        with lock:
            results.append(row_id)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(n_events)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every writer must have persisted its row (row_id > 0) — zero dropped.
    assert len(results) == n_events
    assert all(r > 0 for r in results), (
        f"{sum(1 for r in results if r <= 0)} of {n_events} events dropped "
        f"(database is locked without busy_timeout)"
    )

    # All rows present, distinct, correctly tagged.
    with ac_module._connect() as conn:
        rows = conn.execute("SELECT event, product_id FROM agent_outbox").fetchall()
    by_product = {r["product_id"] for r in rows}
    assert len(rows) == n_events, f"expected {n_events} rows, got {len(rows)}"
    assert by_product == {f"writer-{i}" for i in range(n_events)}
