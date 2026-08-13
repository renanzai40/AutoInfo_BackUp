"""Prometheus-format metrics collection and formatting (F57).

Provides:

* ``get_metrics()`` — gather all metrics from the running system.
* ``format_prometheus()`` — render the metrics dict as Prometheus exposition text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autoinfo.config import get_config_path

# ---------------------------------------------------------------------------
# Metric names
# ---------------------------------------------------------------------------

METRIC_NAMES: dict[str, str] = {
    "items_collected_total": "Total number of items collected across all domains",
    "items_processed_total": "Total number of items successfully processed (LLM extraction)",
    "extraction_tokens_total": "Total LLM tokens consumed during extraction",
    "errors_total": "Total number of errors recorded across the pipeline",
    "active_users": "Number of active (non-cancelled) end-user profiles",
    "storage_bytes": "Total bytes used by knowledge base Markdown files",
    "billing_stripe_sync_failures_total": "Total number of stripe_customer_id persistence failures in billing sync",
    "delivery_failures_total": "Total number of failed agent callback deliveries (durable outbox)",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_metrics() -> dict[str, Any]:
    """Collect all system metrics into a flat dict.

    Returns
    -------
    dict
        Keys are Prometheus metric names, values are numeric or dict
        values with optional ``label`` dimensions.
    """
    cwd = Path.cwd()
    autoinfo_dir = _find_autoinfo_dir()
    db_path = autoinfo_dir / "autoinfo.db" if autoinfo_dir else cwd / "autoinfo.db"
    knowledge_dir = cwd / "knowledge"
    collections_dir = cwd / "collections"

    # --- items_collected_total --------------------------------------------
    items_collected_total = _count_items_collected(db_path, knowledge_dir)

    # --- items_processed_total --------------------------------------------
    items_processed_total = _count_items_processed(knowledge_dir)

    # --- extraction_tokens_total ------------------------------------------
    extraction_tokens_total = _sum_extraction_tokens()

    # --- errors_total -----------------------------------------------------
    errors_total = _count_errors(db_path, collections_dir)

    # --- active_users -----------------------------------------------------
    active_users = _count_active_users()

    # --- storage_bytes ----------------------------------------------------
    storage_bytes = _sum_storage_bytes(knowledge_dir)

    # --- billing_stripe_sync_failures_total --------------------------------
    billing_stripe_sync_failures_total = _count_stripe_sync_failures()

    # --- delivery_failures_total -------------------------------------------
    delivery_failures_total = _get_delivery_failures()

    return {
        "items_collected_total": items_collected_total,
        "items_processed_total": items_processed_total,
        "extraction_tokens_total": extraction_tokens_total,
        "errors_total": errors_total,
        "active_users": active_users,
        "storage_bytes": storage_bytes,
        "billing_stripe_sync_failures_total": billing_stripe_sync_failures_total,
        "delivery_failures_total": delivery_failures_total,
    }


def format_prometheus(metrics: dict[str, Any]) -> str:
    """Render the *metrics* dict as Prometheus exposition format text.

    Parameters
    ----------
    metrics:
        Flat dict of metric names → values as returned by ``get_metrics()``.

    Returns
    -------
    str
        Prometheus-formatted text with ``# HELP`` and ``# TYPE`` lines.
    """
    lines: list[str] = []
    for name, value in metrics.items():
        if name not in METRIC_NAMES:
            continue
        help_text = METRIC_NAMES[name]
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")

        if isinstance(value, dict):
            # Metric with labels: value is {labels_dict: numeric}
            for labels, v in value.items():
                if isinstance(labels, dict) and labels:
                    label_str = ",".join(
                        f'{k}="{v}"' for k, v in sorted(labels.items())
                    )
                    lines.append(f'{name}{{{label_str}}} {v}')
                else:
                    lines.append(f"{name} {v}")
        else:
            lines.append(f"{name} {value}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_autoinfo_dir() -> Path | None:
    """Locate the project's ``.autoinfo`` directory."""
    config_path = get_config_path()
    if config_path:
        return config_path.parent
    candidate = Path.cwd() / ".autoinfo"
    return candidate if candidate.is_dir() else None


def _count_items_collected(db_path: Path, knowledge_dir: Path) -> int:
    """Count total KB entries across all tiers."""
    total = 0
    # Try SQLite first
    if db_path.is_file():
        try:
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE deleted_at = ''"
            ).fetchone()
            conn.close()
            if row:
                total = row[0]
        except Exception:
            total = 0

    # Fallback: count Markdown files on disk
    if total == 0 and knowledge_dir.is_dir():
        total = len(list(knowledge_dir.rglob("*.md")))
    return total


def _count_items_processed(knowledge_dir: Path) -> int:
    """Count entries in 02-Draft and 03-Wiki tiers."""
    count = 0
    for tier in ("02-Draft", "03-Wiki"):
        tier_dir = knowledge_dir / tier
        if tier_dir.is_dir():
            count += len(list(tier_dir.rglob("*.md")))
    return count


def _sum_extraction_tokens() -> int:
    """Sum LLM token usage from CostMeter data."""
    try:
        from autoinfo.cost import CostMeter

        meter = CostMeter()
        report = meter.get_report(period="all")
        # The report contains a 'total_tokens' field from the cost meter
        if isinstance(report, dict):
            return int(report.get("total_tokens", 0))
    except Exception:
        pass
    return 0


def _count_errors(db_path: Path, collections_dir: Path) -> int:
    """Count total errors from collection run logs and error entries in DB."""
    error_count = 0

    # Scan collection run logs for error entries
    if collections_dir.is_dir():
        for runs_file in collections_dir.rglob("_runs.json"):
            try:
                import json

                runs = json.loads(runs_file.read_text(encoding="utf-8"))
                for run in runs:
                    if run.get("status", "success") != "success":
                        # Count errors field if present
                        error_count += run.get("errors", 0) if "errors" in run else 1
            except Exception:
                pass

    # Count error-type feedback entries in DB
    if db_path.is_file():
        try:
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE quality_tier = 5"
            ).fetchone()
            conn.close()
            if row:
                error_count += row[0]
        except Exception:
            pass

    return error_count


def _count_active_users() -> int:
    """Count non-cancelled end-user profiles."""
    try:
        from autoinfo.user_store import list_profiles

        profiles = list_profiles()
        return sum(1 for p in profiles if p.status != "cancelled")
    except Exception:
        return 0


def _sum_storage_bytes(knowledge_dir: Path) -> int:
    """Sum file sizes of all knowledge base Markdown files."""
    total = 0
    if knowledge_dir.is_dir():
        for md_file in knowledge_dir.rglob("*.md"):
            try:
                total += md_file.stat().st_size
            except OSError:
                pass
    return total


def _count_stripe_sync_failures() -> int:
    """Return the in-memory counter of stripe_customer_id persistence failures."""
    try:
        from autoinfo.billing import _stripe_sync_failures

        return _stripe_sync_failures
    except Exception:
        return 0


def _get_delivery_failures() -> int:
    """Return the in-memory counter of failed agent callback deliveries."""
    try:
        from autoinfo.agent_callback import get_delivery_failures

        return get_delivery_failures()
    except Exception:
        return 0
