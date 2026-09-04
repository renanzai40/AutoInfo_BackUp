"""Cron CLI — manage scheduled collection jobs.

Usage::

    autoinfo cron run
    autoinfo cron list-schedules
    autoinfo cron add-schedule --name nightly --expression "0 2 * * *" --domain medical
    autoinfo cron remove-schedule --name nightly
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import yaml

logger = logging.getLogger(__name__)

app = typer.Typer(help="Manage scheduled collection jobs")

# ---------------------------------------------------------------------------
# Schedule data model
# ---------------------------------------------------------------------------

SCHEDULES_PATH = Path(".autoinfo/schedules.yaml")
HEARTBEAT_PATH = Path(".autoinfo/cron-heartbeat.json")


@dataclass
class Schedule:
    name: str = ""
    expression: str = ""
    domain: str = ""
    type: str = "collection"  # "collection" or "digest"
    enabled: bool = True
    last_run: str | None = None  # ISO-8601 datetime, or None if never run
    created_at: str = ""
    recipients: list[str] = field(default_factory=list)  # email recipients (digest type)
    format: str = "html"  # digest output format: "html" or "markdown"
    user_id: str = ""  # end-user ID for content-preference filtering (digest type)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Schedule storage
# ---------------------------------------------------------------------------


def _schedules_path() -> Path:
    return Path.cwd() / SCHEDULES_PATH


def _load_schedules_raw() -> dict[str, Any]:
    """Load the schedules YAML file, returning a dict with a 'schedules' key."""
    path = _schedules_path()
    if not path.is_file():
        return {"schedules": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {"schedules": {}}
    except yaml.YAMLError:
        logger.warning("Failed to parse schedules file at %s", path)
        return {"schedules": {}}


def _dump_schedules_raw(data: dict[str, Any]) -> None:
    """Write the schedules YAML file."""
    path = _schedules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_schedules() -> dict[str, Schedule]:
    """Load all schedules from disk as Schedule objects."""
    raw = _load_schedules_raw()
    schedules: dict[str, Schedule] = {}
    for name, s in raw.get("schedules", {}).items():
        schedules[name] = Schedule(
            name=name,
            expression=s.get("expression", ""),
            domain=s.get("domain", ""),
            type=s.get("type", "collection"),
            enabled=s.get("enabled", True),
            last_run=s.get("last_run"),
            created_at=s.get("created_at", ""),
            recipients=s.get("recipients", []),
            format=s.get("format", "html"),
            user_id=s.get("user_id", ""),
        )
    return schedules


def save_schedules(schedules: dict[str, Schedule]) -> None:
    """Persist schedules to disk."""
    raw: dict[str, Any] = {"schedules": {}}
    for name, s in schedules.items():
        schedule_dict: dict[str, Any] = {
            "expression": s.expression,
            "domain": s.domain,
            "enabled": s.enabled,
            "last_run": s.last_run,
            "created_at": s.created_at,
        }
        # Only serialize type and digest fields when not default "collection"
        if s.type != "collection":
            schedule_dict["type"] = s.type
            schedule_dict["format"] = s.format
            schedule_dict["user_id"] = s.user_id
            if s.recipients:
                schedule_dict["recipients"] = s.recipients
        raw["schedules"][name] = schedule_dict
    _dump_schedules_raw(raw)


def get_schedule(name: str) -> Schedule | None:
    """Return a single schedule by name, or None."""
    return load_schedules().get(name)


# ---------------------------------------------------------------------------
# Heartbeat persistence (cron health tracking)
# ---------------------------------------------------------------------------


def _heartbeat_path() -> Path:
    return Path.cwd() / HEARTBEAT_PATH


def _load_heartbeat() -> dict[str, Any]:
    """Load the cron heartbeat JSON file.

    Returns
    -------
    dict
        ``{"schedules": {"name": {"last_run_at": "...", "status": "...", "last_error": "..."}}}``.
        Empty ``{"schedules": {}}`` when no file exists or parse fails.
    """
    path = _heartbeat_path()
    if not path.is_file():
        return {"schedules": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to parse heartbeat file at %s", path)
        return {"schedules": {}}
    # Ensure "schedules" key exists
    if "schedules" not in data:
        data["schedules"] = {}
    return data


def _save_heartbeat(data: dict[str, Any]) -> None:
    """Persist heartbeat data to disk."""
    path = _heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _update_heartbeat(
    name: str,
    status: str = "ok",
    last_error: str | None = None,
) -> None:
    """Update a single schedule's heartbeat entry.

    Parameters
    ----------
    name:
        Schedule name.
    status:
        ``"ok"`` or ``"error"``.
    last_error:
        Error message when ``status="error"``.
    """
    heartbeat = _load_heartbeat()
    schedules_heartbeat = heartbeat.setdefault("schedules", {})
    schedules_heartbeat[name] = {
        "last_run_at": _now_iso(),
        "status": status,
        "last_error": last_error,
    }
    _save_heartbeat(heartbeat)


def get_schedule_status(schedule_id: str | None = None) -> list[dict]:
    """Return status for all schedules or a specific one.

    Parameters
    ----------
    schedule_id : str | None
        Optional schedule name to filter.  When ``None``, returns all.

    Returns
    -------
    list[dict]
        Each dict contains: ``schedule_id``, ``domain``, ``cron_expr``,
        ``is_active``, ``last_run``, ``next_run``, ``schedule_type``,
        ``recipients``, ``health`` (``"ok"`` | ``"missed"`` | ``"unknown"``),
        ``last_error``.
        Returns empty list when no schedules are configured.
    """
    import sys

    now = datetime.now(timezone.utc)
    result: list[dict] = []

    schedules = load_schedules()
    if not schedules:
        return result

    # Lazy import croniter — only needed for next_run computation
    croniter_mod = sys.modules.get("croniter")
    if croniter_mod is None:
        try:
            import croniter as croniter_mod  # type: ignore[no-redef]
        except ImportError:
            croniter_mod = None  # type: ignore[assignment]

    heartbeat = _load_heartbeat()
    schedules_heartbeat = heartbeat.get("schedules", {})

    for name, s in schedules.items():
        if schedule_id is not None and name != schedule_id:
            continue

        hb = schedules_heartbeat.get(name, {})
        hb_last_run = hb.get("last_run_at")
        hb_status = hb.get("status")
        hb_last_error = hb.get("last_error")

        next_run: str | None = None
        health: str = "unknown"

        if s.enabled and croniter_mod is not None:
            try:
                base = (
                    datetime.fromisoformat(hb_last_run)
                    if hb_last_run
                    else (datetime.fromisoformat(s.last_run) if s.last_run else now)
                )
                cron = croniter_mod.croniter(s.expression, base)
                next_dt = cron.get_next(datetime)
                next_run = next_dt.isoformat()

                # Missed detection: if next expected run is in the past,
                # the schedule should have run but didn't
                if hb_last_run:
                    last_dt = datetime.fromisoformat(hb_last_run)
                    expected_next = croniter_mod.croniter(s.expression, last_dt).get_next(datetime)
                    if expected_next < now:
                        health = "missed"
                    else:
                        health = "ok"
                else:
                    health = "unknown"
            except Exception:
                pass

        # Override health if last heartbeat recorded an error
        if hb_status == "error":
            health = "error"

        result.append({
            "schedule_id": name,
            "domain": s.domain,
            "cron_expr": s.expression,
            "is_active": s.enabled,
            "last_run": hb_last_run or s.last_run,
            "next_run": next_run,
            "schedule_type": s.type,
            "recipients": s.recipients if s.type == "digest" else [],
            "health": health,
            "last_error": hb_last_error,
        })

    return result


# ---------------------------------------------------------------------------
# Cron check logic
# ---------------------------------------------------------------------------


def _is_due(
    expression: str,
    last_run: str | None,
    now: datetime | None = None,
) -> bool:
    """Check whether a schedule is due to run.

    A schedule is due when:

    * It has never run (``last_run is None``), **or**
    * The next occurrence of the cron expression after *last_run* is
      at or before *now*.
    """
    from croniter import croniter

    if now is None:
        now = datetime.now(timezone.utc)

    if last_run is None:
        return True

    last_dt = datetime.fromisoformat(last_run)
    cron = croniter(expression, last_dt)
    next_time = cron.get_next(datetime)
    return next_time <= now


def run_due_schedules(
    dry_run: bool = False,
    schedule_filter: str | None = None,
    json_output: bool = False,
) -> list:  # list of result dicts
    """Run all due schedules, returning a list of result dicts.

    Parameters
    ----------
    dry_run : bool
        If True, only report which schedules *would* run without executing.
    schedule_filter : str | None
        Optional single schedule name to check instead of all.
    json_output : bool
        If True, include full collection results as JSON in the output.

    Returns
    -------
    list[dict]
        One dict per schedule that was due, each with keys:
        ``name``, ``domain``, ``expression``, ``ran`` (bool),
        ``collection_result`` (dict, only when ``ran=True``),
        ``error`` (str, only on failure).
    """

    schedules = load_schedules()
    now = datetime.now(timezone.utc)
    results = []

    for name, sched in schedules.items():
        if schedule_filter and name != schedule_filter:
            continue
        if not sched.enabled:
            continue

        due = _is_due(sched.expression, sched.last_run, now)

        entry: dict[str, Any] = {
            "name": name,
            "domain": sched.domain,
            "expression": sched.expression,
            "due": due,
        }

        if not due:
            entry["ran"] = False
            results.append(entry)
            continue

        if dry_run:
            entry["ran"] = False
            entry["dry_run"] = True
            results.append(entry)
            continue

        # Execute based on schedule type
        try:
            if sched.type == "digest":
                from autoinfo.email_sender import send_digest

                send_digest(
                    domain=sched.domain,
                    period="daily",
                    config=None,
                    user_id=sched.user_id,
                )
                sched.last_run = now.isoformat()
                save_schedules(schedules)
                _update_heartbeat(name, status="ok")
                entry["ran"] = True
                entry["type"] = "digest"
            else:
                from autoinfo.collect import run_collection

                coll_result = run_collection(domain=sched.domain)
                sched.last_run = now.isoformat()
                save_schedules(schedules)
                _update_heartbeat(name, status="ok")
                entry["ran"] = True
                if json_output:
                    entry["collection_result"] = coll_result
                else:
                    entry["collection_result"] = {
                        "collection_id": coll_result.get("collection_id"),
                        "total_new": coll_result.get("total_new", 0),
                        "total_found": coll_result.get("total_found", 0),
                    }
            entry["last_run"] = sched.last_run
        except Exception as exc:
            logger.exception("Schedule '%s' failed", name)
            _update_heartbeat(name, status="error", last_error=str(exc))
            entry["ran"] = False
            entry["error"] = str(exc)

        results.append(entry)

    # --- Delivery schedules --------------------------------------------------
    try:
        from autoinfo.delivery.scheduler import SCHEDULES_PATH, run_delivery_schedules

        delivery_path = Path.cwd() / SCHEDULES_PATH
        if delivery_path.is_file():
            delivery_results = run_delivery_schedules(
                dry_run=dry_run,
                json_output=json_output,
            )
            for dr in delivery_results:
                if schedule_filter and dr.get("domain") != schedule_filter:
                    continue
                dr_entry: dict[str, Any] = {
                    "name": f"delivery:{dr['schedule_id'][:12]}",
                    "domain": dr.get("domain", ""),
                    "expression": dr.get("cron_expression", ""),
                    "due": dr.get("due", True),
                }
                if dr.get("dry_run"):
                    dr_entry["ran"] = False
                    dr_entry["dry_run"] = True
                elif dr.get("ran"):
                    dr_entry["ran"] = True
                    dr_entry["type"] = "delivery"
                    dr_entry["collection_result"] = {
                        "output_type": dr.get("output_type", ""),
                        "channel": dr.get("channel", ""),
                    }
                else:
                    dr_entry["ran"] = False
                    dr_entry["error"] = dr.get("error", "unknown error")
                dr_entry["last_run"] = dr.get("last_run", "")
                results.append(dr_entry)
    except ImportError:
        pass
    except Exception:
        logger.debug("Delivery schedule execution failed", exc_info=True)

    # --- Trial expiry check (cron-based automated notification) -------------
    try:
        from autoinfo.notifications import check_expiring_trials  # noqa: PLC0415

        _ = check_expiring_trials()
    except Exception:
        logger.debug("Trial expiry check failed", exc_info=True)

    return results


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


@app.command()
def run(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report which schedules would run without executing",
    ),
    name: str | None = typer.Option(
        None, "--name", help="Run only a specific schedule by name",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output full results as JSON",
    ),
) -> None:
    """Run pending scheduled collections."""
    try:
        results = run_due_schedules(
            dry_run=dry_run,
            schedule_filter=name,
            json_output=json_output,
        )
    except ImportError:
        typer.echo(
            "Error: croniter is required for scheduled collection.\n"
            "Install it with: pip install croniter",
            err=True,
        )
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(
            json.dumps(
                {"items": results, "count": len(results)}, ensure_ascii=False, indent=2
            )
        )
        return

    due = [r for r in results if r.get("due")]
    ran = [r for r in results if r.get("ran")]

    if not due:
        typer.echo("No schedules are due.")
        return

    for entry in due:
        entry_type = entry.get("type", "")
        if entry.get("dry_run"):
            type_suffix = f" [{entry_type}]" if entry_type else ""
            typer.echo(
                f"  🔄 {entry['name']} ({entry['domain']}) — "
                f"[{entry['expression']}] — would run{type_suffix}"
            )
        elif entry.get("ran"):
            cr = entry.get("collection_result", {})
            if entry_type == "delivery":
                typer.echo(
                    f"  ✓ {entry['name']} ({entry['domain']}) — "
                    f"{cr.get('output_type', 'output')} via {cr.get('channel', 'channel')}"
                )
            else:
                typer.echo(
                    f"  ✓ {entry['name']} ({entry['domain']}) — "
                    f"{cr.get('total_new', 0)} new / {cr.get('total_found', 0)} found"
                )
        elif "error" in entry:
            typer.echo(
                f"  ✗ {entry['name']} ({entry['domain']}) — FAILED: {entry['error']}",
                err=True,
            )
        else:
            typer.echo(
                f"  – {entry['name']} ({entry['domain']}) — skipped"
            )

    due_count = len(due)
    ran_count = len(ran)
    typer.echo("")
    typer.echo(f"{ran_count} of {due_count} due schedule(s) executed.")


@app.command(name="list-schedules")
def list_schedules(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all configured schedules."""
    schedules = load_schedules()

    if json_output:
        data = []
        for name, s in schedules.items():
            data.append(asdict(s))
        typer.echo(json.dumps({"items": data, "count": len(data)}, ensure_ascii=False, indent=2))
        return

    if not schedules:
        typer.echo("No schedules configured.")
        return

    typer.echo(f"{'Name':<20} {'Expression':<18} {'Domain':<22} {'Enabled':<8} {'Last Run':<30}")
    typer.echo("-" * 100)
    for name, s in schedules.items():
        last = s.last_run or "—"
        enabled = "yes" if s.enabled else "no"
        typer.echo(
            f"{name:<20} {s.expression:<18} {s.domain:<22} {enabled:<8} {last:<30}"
        )


@app.command(name="add-schedule")
def add_schedule(
    name: str = typer.Option(..., "--name", help="Schedule name"),
    expression: str = typer.Option(
        ..., "--expression", help="Cron expression (e.g. '0 2 * * *')",
    ),
    domain: str = typer.Option(
        ..., "--domain", help="Domain to collect on this schedule",
    ),
    schedule_type: str = typer.Option(
        "collection", "--type", help="Schedule type: collection or digest",
    ),
    recipients: str = typer.Option(
        "", "--recipients", help="Comma-separated email recipients (for digest type)",
    ),
    output_format: str = typer.Option(
        "html", "--format", help="Digest format: html or markdown",
    ),
) -> None:
    """Add a new collection or digest schedule."""
    if schedule_type not in ("collection", "digest"):
        typer.echo(
            f"Error: Invalid schedule type '{schedule_type}'. Must be 'collection' or 'digest'.",
            err=True,
        )
        raise typer.Exit(code=1)

    if schedule_type == "digest" and not recipients:
        typer.echo(
            "Error: --recipients is required for digest-type schedules.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Validate cron expression
    try:
        from croniter import croniter

        if not croniter.is_valid(expression):
            typer.echo(
                f"Error: '{expression}' is not a valid cron expression.",
                err=True,
            )
            raise typer.Exit(code=1)
    except ImportError:
        typer.echo(
            "Error: croniter is required for scheduled collection.\n"
            "Install it with: pip install croniter",
            err=True,
        )
        raise typer.Exit(code=1)

    schedules = load_schedules()
    if name in schedules:
        typer.echo(f"Error: A schedule named '{name}' already exists.", err=True)
        raise typer.Exit(code=1)

    recipients_list = [r.strip() for r in recipients.split(",") if r.strip()] if recipients else []

    new_schedule = Schedule(
        name=name,
        expression=expression,
        domain=domain,
        type=schedule_type,
        enabled=True,
        last_run=None,
        created_at=_now_iso(),
        recipients=recipients_list,
        format=output_format,
    )
    schedules[name] = new_schedule
    save_schedules(schedules)

    type_label = "digest" if schedule_type == "digest" else "collection"
    typer.echo(
        f"Schedule '{name}' added: {expression} → domain '{domain}' "
        f"(type: {type_label})"
    )


@app.command(name="remove-schedule")
def remove_schedule(
    name: str = typer.Option(..., "--name", help="Schedule name to remove"),
) -> None:
    """Remove a collection schedule."""
    schedules = load_schedules()
    if name not in schedules:
        typer.echo(f"Error: Schedule '{name}' not found.", err=True)
        raise typer.Exit(code=1)

    removed = schedules.pop(name)
    save_schedules(schedules)
    typer.echo(
        f"Schedule '{name}' removed (was: {removed.expression} → domain '{removed.domain}')."
    )


@app.command(name="health")
def health(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    notify: bool = typer.Option(
        False, "--notify", help="Send email alerts for missed schedules",
    ),
) -> None:
    """Show per-schedule health status with missed-schedule detection.

    Reports ``health`` field for each schedule:
    - ``ok`` — last run was on time
    - ``missed`` — schedule was expected to run but didn't
    - ``error`` — last run failed
    - ``unknown`` — schedule has never run (no heartbeat data)

    Use ``--notify`` to send email alerts to the admin address
    (``AUTOINFO_ADMIN_EMAIL`` env var or ``email.to_addrs`` from config).
    """
    statuses = get_schedule_status()
    if not statuses:
        typer.echo("No schedules configured.")
        return

    # Collect missed schedules for notification
    missed = [s for s in statuses if s["health"] == "missed"]

    if notify and missed:
        _send_missed_alerts(missed)

    if json_output:
        typer.echo(json.dumps({
            "schedules": statuses,
            "count": len(statuses),
            "missed_count": len(missed),
        }, ensure_ascii=False, indent=2))
        return

    # Table header
    header = f"{'Name':<20} {'Health':<10} {'Domain':<22} {'Last Run':<28} {'Next Run':<28}"
    typer.echo(header)
    typer.echo("-" * len(header))

    for s in statuses:
        health_icon = _health_icon(s["health"])
        health_label = f"{health_icon} {s['health']}"
        last = s["last_run"] or "—"
        next_r = s["next_run"] or "—"
        typer.echo(
            f"{s['schedule_id']:<20} {health_label:<10} {s['domain']:<22} "
            f"{last:<28} {next_r:<28}"
        )
        if s.get("last_error"):
            typer.echo(f"  ↳ Error: {s['last_error']}")

    typer.echo("")
    summary_parts = [f"{len(statuses)} schedule(s)"]
    ok_count = sum(1 for s in statuses if s["health"] == "ok")
    error_count = sum(1 for s in statuses if s["health"] == "error")
    unknown_count = sum(1 for s in statuses if s["health"] == "unknown")
    if ok_count:
        summary_parts.append(f"{ok_count} ok")
    if missed:
        summary_parts.append(f"{len(missed)} missed")
    if error_count:
        summary_parts.append(f"{error_count} error")
    if unknown_count:
        summary_parts.append(f"{unknown_count} unknown")
    typer.echo(", ".join(summary_parts))


def _health_icon(health: str) -> str:
    """Map health status to display icon."""
    return {"ok": "✓", "missed": "✗", "error": "✗", "unknown": "?"}.get(health, "?")


def _send_missed_alerts(missed_schedules: list[dict]) -> None:
    """Send email notification for missed schedules.

    Reads admin email from ``AUTOINFO_ADMIN_EMAIL`` env var or falls back
    to the configured ``email.to_addrs`` list.

    Parameters
    ----------
    missed_schedules : list[dict]
        Schedule status dicts with ``health == "missed"``.
    """
    import os

    from autoinfo.email_sender import send_notification

    admin_email = os.environ.get("AUTOINFO_ADMIN_EMAIL", "")
    if not admin_email:
        try:
            from autoinfo.config import get_config_path, load_config

            config_path = get_config_path()
            if config_path:
                cfg = load_config(config_path)
                if cfg.email.to_addrs:
                    admin_email = cfg.email.to_addrs[0]
        except Exception:
            pass

    if not admin_email:
        logger.warning(
            "Cannot send missed-schedule alert: no admin email configured. "
            "Set AUTOINFO_ADMIN_EMAIL or configure email.to_addrs in config."
        )
        return

    for s in missed_schedules:
        name = s["schedule_id"]
        domain = s["domain"]
        expr = s["cron_expr"]
        last_run = s["last_run"] or "never"
        next_run = s["next_run"] or "unknown"

        subject = f"[AutoInfo] Missed schedule: {name} ({domain})"
        body = (
            f"Schedule '{name}' was expected to run but didn't.\n\n"
            f"  Domain:      {domain}\n"
            f"  Cron expr:   {expr}\n"
            f"  Last run:    {last_run}\n"
            f"  Expected:    {next_run}\n\n"
            f"Please check the AutoInfo cron configuration and logs.\n"
        )
        try:
            send_notification(to=admin_email, subject=subject, body=body)
            logger.info("Missed schedule alert sent for '%s' to %s", name, admin_email)
        except Exception as exc:
            logger.exception("Failed to send missed-schedule alert for '%s': %s", name, exc)


# ---------------------------------------------------------------------------
# Crontab management (system crontab install/uninstall)
# ---------------------------------------------------------------------------

CRONTAB_MARKER = "# autoinfo-cron-managed"


def _check_crontab() -> None:
    """Exit with helpful message if ``crontab`` binary is missing."""
    if not shutil.which("crontab"):
        typer.echo(
            "Error: `crontab` command not found.\n"
            "Install cronie or your system's cron package to use this feature.\n"
            "  Debian/Ubuntu: sudo apt-get install cronie\n"
            "  RHEL/Fedora:  sudo dnf install cronie\n"
            "  macOS:         Already preinstalled.\n"
            "  Windows:       Use WSL or install cron via cygwin.",
            err=True,
        )
        raise typer.Exit(code=1)


def _get_crontab_lines() -> list[str]:
    """Return current crontab lines (empty list if no crontab yet)."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return [line for line in result.stdout.splitlines() if line.strip()]
        return []
    except FileNotFoundError:
        _check_crontab()
        return []
    except subprocess.TimeoutExpired:
        logger.warning("`crontab -l` timed out after 15s; treating as empty crontab")
        return []


def _set_crontab_lines(lines: list[str]) -> None:
    """Write *lines* as the new crontab."""
    text = "\n".join(lines)
    if text:
        text += "\n"
    try:
        _ = subprocess.run(
            ["crontab", "-"],
            input=text,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except FileNotFoundError:
        _check_crontab()
    except subprocess.TimeoutExpired:
        logger.error("`crontab -` timed out after 30s; crontab not updated")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# CLI Commands — install / uninstall
# ---------------------------------------------------------------------------


@app.command()
def install() -> None:
    """Install autoinfo crontab entry (runs daily at 6:00 AM).

    The entry is marked with ``# autoinfo-cron-managed`` and can be
    removed with ``autoinfo cron uninstall``.
    """
    _check_crontab()

    lines = _get_crontab_lines()
    if any(CRONTAB_MARKER in line for line in lines):
        typer.echo("autoinfo crontab entry already installed.")
        return

    cron_line = (
        f"0 6 * * * cd {Path.cwd()} && autoinfo cron run "
        f">> /tmp/autoinfo-cron.log 2>&1 {CRONTAB_MARKER}"
    )
    lines.append(cron_line)
    _set_crontab_lines(lines)
    typer.echo("autoinfo crontab entry installed (daily at 6:00 AM).")


@app.command()
def uninstall() -> None:
    """Remove all autoinfo-managed crontab entries."""
    _check_crontab()

    lines = _get_crontab_lines()
    filtered = [line for line in lines if CRONTAB_MARKER not in line]
    removed = len(lines) - len(filtered)

    if removed == 0:
        typer.echo("No autoinfo crontab entries found.")
        return

    _set_crontab_lines(filtered)
    typer.echo(
        f"Removed {removed} autoinfo crontab entr{'y' if removed == 1 else 'ies'}."
    )


# ---------------------------------------------------------------------------
# Delivery schedule commands
# ---------------------------------------------------------------------------


@app.command(name="add-delivery")
def add_delivery(
    domain: str = typer.Option(
        ..., "--domain", help="Domain to generate output for",
    ),
    schedule: str = typer.Option(
        ..., "--schedule", help="Cron expression (e.g. '0 8 * * 1' for Monday 8 AM)",
    ),
    output: str = typer.Option(
        "digest", "--output", help="Output type: digest or report",
    ),
    channel: str = typer.Option(
        "email",
        "--channel",
        help="Delivery channel: email, webhook, rest, telegram, discord, etc.",
    ),
    to: str = typer.Option(
        "", "--to", help="Comma-separated recipients (emails, webhook URLs, etc.)",
    ),
    output_format: str = typer.Option(
        "html", "--format", help="Output format: markdown, html, json, agent, audio, pdf",
    ),
    period: str = typer.Option(
        "weekly", "--period", help="Content period: daily, weekly, monthly",
    ),
    schedule_user_id: str = typer.Option(
        "",
        "--user-id",
        help="End-user ID bound to the schedule (content-preference filtering; "
        "free-tier frequency limits apply to named users only)",
    ),
) -> None:
    """Add a delivery schedule: periodic output generation + channel delivery."""
    try:
        from croniter import croniter

        if not croniter.is_valid(schedule):
            typer.echo(
                f"Error: '{schedule}' is not a valid cron expression.",
                err=True,
            )
            raise typer.Exit(code=1)
    except ImportError:
        typer.echo(
            "Error: croniter is required. Install with: pip install croniter",
            err=True,
        )
        raise typer.Exit(code=1)

    from autoinfo.delivery.scheduler import (
        VALID_CHANNELS,
        VALID_FORMATS,
        VALID_OUTPUT_TYPES,
        DeliverySchedule,
        DeliveryScheduler,
    )

    if output not in VALID_OUTPUT_TYPES:
        typer.echo(
            f"Error: Invalid output type '{output}'. "
            f"Must be one of: {', '.join(sorted(VALID_OUTPUT_TYPES))}",
            err=True,
        )
        raise typer.Exit(code=1)

    if output_format not in VALID_FORMATS:
        typer.echo(
            f"Error: Invalid format '{output_format}'. "
            f"Must be one of: {', '.join(sorted(VALID_FORMATS))}",
            err=True,
        )
        raise typer.Exit(code=1)

    if channel not in VALID_CHANNELS:
        typer.echo(
            f"Error: Invalid channel '{channel}'. "
            f"Must be one of: {', '.join(sorted(VALID_CHANNELS))}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Free-tier frequency gate (todo 12) — named users only; empty skips
    from autoinfo.delivery.frequency_gate import check_schedule_frequency

    gate = check_schedule_frequency(user_id=schedule_user_id, frequency=period)
    if not gate["allowed"]:
        typer.echo(
            f"Error: [{gate['code']}] {gate['message']}",
            err=True,
        )
        raise typer.Exit(code=1)

    recipients_list = [r.strip() for r in to.split(",") if r.strip()] if to else []

    new_schedule = DeliverySchedule(
        cron_expression=schedule,
        domain=domain,
        output_type=output,
        format=output_format,
        channel=channel,
        recipients=recipients_list,
        period=period,
        user_id=schedule_user_id,
    )
    scheduler = DeliveryScheduler()
    scheduler.add_schedule(new_schedule)

    typer.echo(
        f"Delivery schedule '{new_schedule.id}' added: "
        f"{schedule} → domain '{domain}' "
        f"({output}, {output_format}, via {channel})"
    )


@app.command(name="list-deliveries")
def list_deliveries(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all configured delivery schedules."""
    from dataclasses import asdict

    from autoinfo.delivery.scheduler import DeliveryScheduler

    scheduler = DeliveryScheduler()
    schedules = scheduler.list_schedules()

    if json_output:
        data = []
        for s in schedules:
            d = asdict(s)
            if d.get("last_error") is None:
                d["last_error"] = ""
            data.append(d)
        typer.echo(json.dumps({"items": data, "count": len(data)}, ensure_ascii=False, indent=2))
        return

    if not schedules:
        typer.echo("No delivery schedules configured.")
        return

    header = f"{'ID':<38} {'Cron':<18} {'Domain':<22} {'Type':<8} {'Channel':<10} {'Enabled':<8}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for s in schedules:
        s_id = s.id[:36] if len(s.id) > 36 else s.id
        enabled = "yes" if s.enabled else "no"
        typer.echo(
            f"{s_id:<38} {s.cron_expression:<18} {s.domain:<22} "
            f"{s.output_type:<8} {s.channel:<10} {enabled:<8}"
        )
    typer.echo(f"\n{schedules.__len__()} delivery schedule(s).")


@app.command(name="remove-delivery")
def remove_delivery(
    schedule_id: str = typer.Argument(..., help="Schedule ID to remove"),
) -> None:
    """Remove a delivery schedule by its ID."""
    from autoinfo.delivery.scheduler import DeliveryScheduler

    scheduler = DeliveryScheduler()
    removed = scheduler.remove_schedule(schedule_id)

    if not removed:
        typer.echo(f"Error: Delivery schedule '{schedule_id}' not found.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Delivery schedule '{schedule_id}' removed.")
