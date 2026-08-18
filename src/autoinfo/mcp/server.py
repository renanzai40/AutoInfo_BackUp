"""MCP server — exposes AutoInfo capabilities as MCP tools over stdio.

This is the primary agent-facing interface for AutoInfo.  All 35+ capabilities
are planned; v0.1 exposes 30 tools across 7 categories:

**System** (2):
    health_check, diagnose_system

**Discovery** (7):
    list_domains, get_domain_schema, list_available_models, get_effective_llm_config,
    activate_domain, deactivate_domain, get_domain_config

**Schedule Management** (4):
    list_schedules, add_schedule, remove_schedule, run_schedules

**Source Management** (5):
    add_source, add_sources, remove_source, test_source, list_sources

**Topic Management** (6):
    add_topic, remove_topic, list_topics, list_keywords,
    topic_group_add, topic_group_remove

**Collection / Processing** (5):
    collect_sources, get_collection_progress, get_collection_status,
    process_collection, get_processing_progress

**Knowledge Base** (4):
    list_summaries, get_kb_entry, search_knowledge_base, flag_for_knowledge_base

**Output** (3):
    list_output_templates, generate_tutorial, generate_presentation

Usage::

    python -m autoinfo.mcp.server

The server listens on stdio (JSON-RPC 2.0) and responds to
``CallToolRequest`` messages.  Connect with any MCP client::

    async with stdio_client(["python", "-m", "autoinfo.mcp.server"]) as (read, write):
        async with ClientSession(read, write) as session:
            result = await session.call_tool("health_check", {})
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar, cast

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from autoinfo import __version__
from autoinfo.cli.doctor import calculate_health_score
from autoinfo.cli.init import _list_demo_domains
from autoinfo.config import SOURCE_KEY_ENV_VARS, VALID_SOURCE_TYPES
from autoinfo.kb import DirectorOnlyError, is_director
from autoinfo.llm import call_with_fallback
from autoinfo.mcp.errors import ErrorCode, error_dict, error_response, success_response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config I/O helpers
# ---------------------------------------------------------------------------


def _config_path() -> Path:
    """Return the path to the project's ``.autoinfo/config.yaml``."""
    return Path.cwd() / ".autoinfo" / "config.yaml"


def _load_config() -> Any:
    """Load the AutoInfo configuration."""
    from autoinfo.config import load_config

    return load_config(_config_path())


def _save_config(config: Any) -> None:
    """Write a Config dataclass tree back to ``.autoinfo/config.yaml``."""
    from autoinfo.config import save_config as _public_save

    _public_save(config, _config_path())


def _find_domain(config: Any, name: str) -> Any | None:
    """Return the domain config object for *name*, or ``None``."""
    for d in config.domains:
        if d.name == name:
            return d
    return None

# ---------------------------------------------------------------------------
# Job state persistence (SQLite-backed, survives server restarts)
# ---------------------------------------------------------------------------

# Reuse the same autoinfo.db that KBStore uses.
# KBStore places it at ``Path("knowledge").resolve().parent / "autoinfo.db"``,
# which resolves to ``<cwd>/autoinfo.db`` when running from the project root.


def _job_db_path() -> Path:
    """Return the path to the shared ``autoinfo.db``."""
    return Path.cwd() / "autoinfo.db"


T = TypeVar('T')


def _with_job_db(fn: Callable[[sqlite3.Connection], T]) -> T:
    """Open a connection, call *fn*, then close.

    Uses the same PRAGMA settings as :class:`~autoinfo.kb.SQLiteIndex`.
    """
    conn = sqlite3.connect(str(_job_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _init_job_state_table(conn)
    try:
        return fn(conn)
    finally:
        conn.close()


def _init_job_state_table(conn: sqlite3.Connection) -> None:
    """Create the ``job_state`` table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_state (
            job_id          TEXT PRIMARY KEY,
            state_type      TEXT NOT NULL,
            domain          TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'running',
            progress_pct    REAL NOT NULL DEFAULT 0.0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            metadata        TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.commit()


def _save_job_state(job_id: str, state_type: str, domain: str, status: str,
                    progress_pct: float, metadata: dict[str, Any]) -> None:
    """Insert-or-update a row in ``job_state``."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata)

    def _write(conn: sqlite3.Connection) -> None:
        existing = conn.execute(
            "SELECT job_id FROM job_state WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE job_state
                   SET state_type = ?, domain = ?, status = ?,
                       progress_pct = ?, updated_at = ?,
                       metadata = ?
                   WHERE job_id = ?""",
                (state_type, domain, status, progress_pct, now, meta_json, job_id),
            )
        else:
            conn.execute(
                """INSERT INTO job_state
                   (job_id, state_type, domain, status, progress_pct,
                    created_at, updated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, state_type, domain, status, progress_pct,
                 now, now, meta_json),
            )
        conn.commit()

    _with_job_db(_write)


def _load_job_state(job_id: str) -> dict[str, Any] | None:
    """Return the full job state row as a dict, or ``None``."""

    def _read(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM job_state WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        meta = _safe_json_load(row["metadata"])
        return {
            "job_id": row["job_id"],
            "state_type": row["state_type"],
            "domain": row["domain"],
            "status": row["status"],
            "progress_pct": row["progress_pct"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **meta,
        }

    return _with_job_db(_read)


def _load_latest_domain_state(domain: str, state_type: str) -> dict[str, Any] | None:
    """Return the most recent job state for *domain*+*state_type*, or ``None``."""

    def _read(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """SELECT * FROM job_state
               WHERE domain = ? AND state_type = ?
               ORDER BY created_at DESC LIMIT 1""",
            (domain, state_type),
        ).fetchone()
        if row is None:
            return None
        meta = _safe_json_load(row["metadata"])
        return {
            "job_id": row["job_id"],
            "state_type": row["state_type"],
            "domain": row["domain"],
            "status": row["status"],
            "progress_pct": row["progress_pct"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **meta,
        }

    return _with_job_db(_read)


def _safe_json_load(raw: str) -> dict[str, Any]:
    """Parse JSON string, returning ``{}`` on failure."""
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}

# ---------------------------------------------------------------------------
# Tool implementations
#
# These are plain (sync) functions so they can be tested without an async
# test harness.  The ``call_tool`` handler wraps them in ``TextContent``.
# ---------------------------------------------------------------------------


def _handle_health_check() -> dict[str, Any]:
    """Quick status ping."""
    return {
        "status": "ok",
        "version": __version__,
        "tools_count": len(
            [name for name in globals() if name.startswith("_handle_")]
        ),
    }


def _handle_get_tool_count() -> dict[str, Any]:
    """Return the number of registered MCP tools."""
    return {
        "tools_count": len(
            [name for name in globals() if name.startswith("_handle_")]
        ),
    }


def _detect_phase(
    result: dict[str, Any],
    config_path: Any,
    collections_dir: Path,
    knowledge_dir: Path,
) -> str:
    """Determine system operational phase from diagnostic results.

    Returns one of: uninitialized, llm_unconfigured, no_sources,
    ready_to_collect, operational.
    """
    if not config_path or "config_error" in result:
        return "uninitialized"
    if not result["llm"].get("key_configured", False):
        return "llm_unconfigured"
    if result["sources"]["count"] == 0:
        return "no_sources"

    has_collected = False
    try:
        if collections_dir.is_dir():
            has_collected = any(collections_dir.iterdir())
    except OSError:
        pass
    if not has_collected:
        try:
            raw_dir = knowledge_dir / "01-Raw"
            if raw_dir.is_dir():
                has_collected = any(raw_dir.iterdir())
        except OSError:
            pass
    if not has_collected:
        return "ready_to_collect"

    return "operational"


def _detect_kb_status() -> str:
    """Detect knowledge base initialisation status.

    Returns:
        ``"uninitialized"`` — ``knowledge/`` directory does not exist.
        ``"empty"`` — ``knowledge/`` directory exists but has no content
            (no tier subdirectories with files inside).
        ``"operational"`` — ``knowledge/`` directory exists and has
            content in at least one tier subdirectory.
    """
    knowledge_dir = Path("knowledge")

    if not knowledge_dir.is_dir():
        return "uninitialized"

    # Check if any tier subdirectory (01-Raw, 02-Draft, 03-Wiki) has files
    has_content = False
    try:
        for entry in knowledge_dir.iterdir():
            if entry.is_dir() and any(entry.iterdir()):
                has_content = True
                break
    except OSError:
        pass

    if not has_content:
        return "empty"

    return "operational"


def _handle_diagnose_system() -> dict[str, Any]:
    """Comprehensive system diagnostics — llm, sources, disk, db."""
    result: dict[str, Any] = {
        "llm": {"configured": False},
        "sources": {"count": 0, "items": []},
        "disk": {},
        "db": {"exists": False},
    }

    # -- Config -----------------------------------------------------------
    config_path = None
    try:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            result["llm"] = {
                "configured": True,
                "provider": config.llm.provider,
                "model": config.llm.model,
                "key_configured": bool(
                    config.llm.api_key
                    or os.environ.get("AUTOINFO_LLM_API_KEY")
                ),
            }
            sources = []
            for d in config.domains:
                if d.active:
                    for s in d.sources:
                        sources.append({
                            "name": s.name,
                            "type": s.type,
                            "domain": d.name,
                            "quality_tier": s.quality_tier,
                            "tos_classification": s.tos_classification,
                        })
            result["sources"] = {"count": len(sources), "items": sources}
    except Exception as exc:
        result["config_error"] = str(exc)

    # -- Disk -------------------------------------------------------------
    collections_dir = Path("collections")
    knowledge_dir = Path("knowledge")
    result["disk"] = {
        "collections_dir_exists": collections_dir.is_dir(),
        "knowledge_dir_exists": knowledge_dir.is_dir(),
    }

    # -- DB ---------------------------------------------------------------
    db_path = knowledge_dir.parent / "autoinfo.db"
    result["db"] = {"exists": db_path.is_file()}

    # -- Health Score -----------------------------------------------------
    # Adapt MCP result schema to match doctor.py calculate_health_score contract:
    #   llm.status (ok/error) from llm.key_configured
    #   config.status (ok/error) from config_path presence
    #   sources list from sources.items
    llm_cfg = result["llm"]
    llm_status = "ok" if llm_cfg.get("key_configured", False) else "error"
    config_status = "ok" if config_path and "config_error" not in result else "error"
    source_items: Any = result["sources"].get("items", [])
    if not isinstance(source_items, list):
        source_items = []


    health_dict: dict[str, Any] = {
        "python": {"status": "ok"},
        "config": {"status": config_status},
        "llm": {
            "status": llm_status,
            "key_configured": llm_cfg.get("key_configured", False),
        },
        "sources": [{"status": "ok"} for _ in source_items],
    }
    result["health_score"] = calculate_health_score(health_dict)

    # -- Phase Detection --------------------------------------------------
    result["phase"] = _detect_phase(result, config_path, collections_dir, knowledge_dir)

    return result


def _handle_collect_sources(
    domain: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a collection run via ``autoinfo.collect.run_collection``.

    When *domain* is ``None``, collects from all active domains and returns a
    ``{domains: {name: job_id, ...}, collected_count: N}`` mapping.
    """
    from datetime import datetime, timezone

    from autoinfo.collect import run_collection

    # -- Domain-less: collect from ALL active domains ------------------------
    if domain is None:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if config_path is None:
            raise FileNotFoundError(
                "No configuration found. Run 'autoinfo init' first."
            )
        config = load_config(config_path)
        active_domains = [d.name for d in config.domains if d.active]

        if not active_domains:
            return {
                "domains": {},
                "collected_count": 0,
                "message": "No active domains found in configuration.",
            }

        domain_results: dict[str, str] = {}
        for dom in active_domains:
            job_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            _save_job_state(job_id, "collection", dom, "running", 0.0, {
                "started_at": started_at,
                "completed_at": "",
                "items_collected": 0,
                "errors": 0,
                "items_per_source": {},
                "duration_s": 0.0,
            })

            try:
                result = run_collection(domain=dom, **kwargs)
                total_new = (
                    result.get("total_new", 0)
                    if isinstance(result, dict)
                    else 0
                )
                total_found = (
                    result.get("total_found", 0)
                    if isinstance(result, dict)
                    else 0
                )
                errors = (
                    result.get("errors", 0)
                    if isinstance(result, dict)
                    else 0
                )
                _save_job_state(job_id, "collection", dom, "completed", 100.0, {
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "items_collected": total_new,
                    "errors": errors,
                    "items_per_source": (
                        result.get("items_per_source", {})
                        if isinstance(result, dict)
                        else {}
                    ),
                    "duration_s": 0.0,
                })
                domain_results[dom] = job_id
            except Exception:
                _save_job_state(job_id, "collection", dom, "error", 0.0, {
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                # Continue to next domain on failure

        return {
            "domains": domain_results,
            "collected_count": len(domain_results),
        }

    # -- Single-domain collection ---------------------------------------------
    cfg = _load_config()
    if _find_domain(cfg, domain) is None:
        return error_response(
            ErrorCode.DOMAIN_NOT_FOUND,
            f"Domain '{domain}' is not configured. "
            f"Use add_domain(name='{domain}') to create it.",
            actionable=True,
        )

    job_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    _save_job_state(job_id, "collection", domain, "running", 0.0, {
        "started_at": started_at,
        "completed_at": "",
        "items_collected": 0,
        "errors": 0,
        "items_per_source": {},
        "duration_s": 0.0,
    })

    try:
        result = run_collection(domain=domain, **kwargs)
        # Attempt to extract stats from result
        total_new = result.get("total_new", 0) if isinstance(result, dict) else 0
        total_found = result.get("total_found", 0) if isinstance(result, dict) else 0
        errors = result.get("errors", 0) if isinstance(result, dict) else 0
        _save_job_state(job_id, "collection", domain, "completed", 100.0, {
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "items_collected": total_new,
            "errors": errors,
            "items_per_source": result.get("items_per_source", {}) if isinstance(result, dict) else {},
            "duration_s": 0.0,
        })
        if isinstance(result, dict):
            result["job_id"] = job_id
        else:
            result = {"job_id": job_id, "result": result}
        return result
    except Exception as exc:
        _save_job_state(job_id, "collection", domain, "error", 0.0, {
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return error_response(ErrorCode.COLLECTION_FAILED, str(exc), actionable=True)


def _handle_get_collection_progress(domain: str = "", job_id: str = "") -> dict[str, Any]:
    """Return current collection progress. Supports lookup by domain or job_id."""
    if job_id:
        state = _load_job_state(job_id)
        if state:
            is_complete = state.get("status") in ("completed", "error")
            return {"job_id": job_id, **state, "is_complete": is_complete}
        return {"job_id": job_id, "status": "not_found", "is_complete": False}
    if domain:
        state = _load_latest_domain_state(domain, "collection")
        if state:
            return {"domain": domain, **state}
        return {
            "domain": domain,
            "status": "idle",
            "started_at": "",
            "completed_at": "",
            "progress_pct": 0.0,
            "items_collected": 0,
            "errors": 0,
            "items_per_source": {},
            "duration_s": 0.0,
        }

    # Return all — query distinct domains with collection entries
    def _read_all(conn: sqlite3.Connection) -> dict[str, Any]:
        rows = conn.execute(
            """SELECT DISTINCT domain FROM job_state
               WHERE state_type = 'collection'
               ORDER BY domain"""
        ).fetchall()
        results: dict[str, Any] = {}
        for row in rows:
            dom = row["domain"]
            latest = conn.execute(
                """SELECT * FROM job_state
                   WHERE domain = ? AND state_type = 'collection'
                   ORDER BY created_at DESC LIMIT 1""",
                (dom,),
            ).fetchone()
            if latest:
                meta = _safe_json_load(latest["metadata"])
                results[dom] = {
                    "status": latest["status"],
                    "progress_pct": latest["progress_pct"],
                    "created_at": latest["created_at"],
                    "updated_at": latest["updated_at"],
                    **meta,
                }
        return {"domains": results, "count": len(results)}

    return _with_job_db(_read_all)


def _handle_get_collection_status(domain: str) -> dict[str, Any]:
    """Return full collection results for *domain* (last run)."""
    state = _load_latest_domain_state(domain, "collection")
    if state is None:
        state = {
            "status": "idle",
            "started_at": "",
            "completed_at": "",
            "progress_pct": 0.0,
            "items_collected": 0,
            "errors": 0,
            "items_per_source": {},
            "duration_s": 0.0,
        }

    # Compute duration if available
    duration = 0.0
    if state.get("started_at") and state.get("completed_at"):
        try:
            from datetime import datetime
            started = datetime.fromisoformat(state["started_at"])
            completed = datetime.fromisoformat(state["completed_at"])
            duration = (completed - started).total_seconds()
        except (ValueError, TypeError):
            duration = 0.0

    return {
        "domain": domain,
        "status": state["status"],
        "last_collection_time": state.get("completed_at", ""),
        "items_per_source": state.get("items_per_source", {}),
        "error_count": state.get("errors", 0),
        "duration_s": round(duration, 2),
        "items_collected": state.get("items_collected", 0),
    }


def _handle_process_collection(**kwargs: Any) -> dict[str, Any]:
    """Execute a processing run via ``autoinfo.process.run_processing``."""
    from datetime import datetime, timezone

    from autoinfo.process import run_processing

    domain = kwargs.get("domain", "unknown")
    job_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    _save_job_state(job_id, "processing", domain, "running", 0.0, {
        "started_at": started_at,
        "kb_entries_created": 0,
        "total_items": 0,
    })

    try:
        result = run_processing(**kwargs)
        if result.total_items == 0:
            _save_job_state(job_id, "processing", domain, "noop", 100.0, {
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "total_items": 0,
            })
            return success_response({
                "status": "noop",
                "total_items": 0,
                "message": f"No cached items found for domain '{domain}'. Run collect_sources() first.",
                "domain": domain,
            })
        result_dict = asdict(result)
        _save_job_state(job_id, "processing", domain, "completed", 100.0, {
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "kb_entries_created": result_dict.get("kb_entries_created", 0),
            "total_items": result_dict.get("total_items", result_dict.get("total_new", 0)),
        })
        result_dict["job_id"] = job_id
        return result_dict
    except Exception:
        _save_job_state(job_id, "processing", domain, "error", 0.0, {
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        raise


def _handle_get_processing_progress(domain: str = "", job_id: str = "") -> dict[str, Any]:
    """Return processing progress. Supports lookup by domain or job_id."""
    if job_id:
        state = _load_job_state(job_id)
        if state:
            is_complete = state.get("status") in ("completed", "error")
            return {"job_id": job_id, **state, "is_complete": is_complete}
        return {"job_id": job_id, "status": "not_found", "is_complete": False}
    if domain:
        from autoinfo.process import get_processing_progress

        return get_processing_progress(domain=domain)
    return {"status": "idle", "is_complete": True}


def _handle_list_summaries(**kwargs: Any) -> dict[str, Any]:
    """List KB entries for a domain via ``KBStore.list_entries``.

    Expects ``domain`` in ``**kwargs`` (popped before passing the rest).
    """
    from autoinfo.kb import KBStore

    domain = kwargs.pop("domain")

    kb_status = _detect_kb_status()
    if kb_status == "uninitialized":
        return error_response(
            ErrorCode.EMPTY_RESULT,
            "Knowledge base not initialized. Run collect_sources() + process_collection() first.",
        )
    if kb_status == "empty":
        return {
            "domain": domain,
            "entries": [],
            "count": 0,
            "message": "Knowledge base initialized but has no entries yet. Run collect_sources() + process_collection() to populate.",
        }

    store = KBStore()
    entries = store.list_entries(domain, **kwargs)
    return {"domain": domain, "entries": entries, "count": len(entries)}


def _handle_get_kb_entry(entry_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Fetch a single KB entry by ID via ``KBStore.get_entry``.

    Parameters
    ----------
    entry_id:
        Unique entry identifier.
    user_id:
        Optional user_id filter (accepted for multi-user compatibility;
        direct ID lookup is user-independent).
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    entry = store.get_entry(entry_id)
    if entry is None:
        return error_response(
            code=ErrorCode.NOT_FOUND,
            message=f"Entry '{entry_id}' not found",
            actionable=True,
        )
    return entry


# ---------------------------------------------------------------------------
# Discovery tools
# ---------------------------------------------------------------------------


def _handle_list_domains() -> dict[str, Any]:
    """List all configured domains with source/topic counts."""
    try:
        config = _load_config()
    except Exception as exc:
        return {"domains": [], "count": 0, "error_code": ErrorCode.INTERNAL_ERROR.value, "message": str(exc), "actionable": True}

    domains = []
    for d in config.domains:
        domains.append({
            "name": d.name,
            "active": d.active,
            "source_count": len(d.sources),
            "topic_count": len(d.topics),
        })
    return {"domains": domains, "count": len(domains)}


# -- Platform metadata (static) -------------------------------------------

# Curated metadata for well-known source types; anything missing from this
# map still gets advertised via ``list_available_platforms`` with a default
# entry so PLATFORMS always mirrors VALID_SOURCE_TYPES.
_PLATFORM_INFO: dict[str, dict[str, Any]] = {
    "rss": {"name": "RSS/Atom Feed", "description": "Fetch content from RSS or Atom feeds", "output_formats": ["xml", "json"]},
    "api": {"name": "REST API", "description": "Call REST API endpoints that return JSON data (PubMed via name match, or generic HTTP API)", "output_formats": ["json"]},
    "web": {"name": "Web Page", "description": "Extract content from web pages using trafilatura/readability", "output_formats": ["html", "markdown"]},
    "webhook": {"name": "Webhook Receiver", "description": "Receive pushed content via HTTP POST webhooks", "output_formats": ["json"]},
    "email": {"name": "Email (IMAP)", "description": "Collect content from email inboxes via IMAP", "output_formats": ["html", "text"]},
    "email_imap": {"name": "Email (IMAP)", "description": "Collect content from email inboxes via IMAP", "output_formats": ["html", "text"]},
    "pdf": {"name": "PDF Document", "description": "Extract text content from PDF documents", "output_formats": ["text", "markdown"]},
    "apple_podcasts": {"name": "Apple Podcasts (iTunes Search)", "description": "Search Apple Podcasts via free iTunes Search API (shows only, no episodes)", "output_formats": ["json"]},
    "dblp": {"name": "DBLP", "description": "Computer science bibliography via the DBLP API", "output_formats": ["json"]},
    "nyt": {"name": "NYT", "description": "New York Times article search API", "output_formats": ["json"]},
    "openalex": {"name": "OpenAlex", "description": "Open scholarly metadata via the OpenAlex API", "output_formats": ["json"]},
    "ap_api": {"name": "AP API", "description": "Associated Press content API (paid)", "output_formats": ["json"]},
    "reuters_mcp": {"name": "Reuters MCP", "description": "Reuters content via the Reuters MCP server", "output_formats": ["json"]},
    "reddit": {"name": "Reddit", "description": "Reddit submissions and comments via the JSON API", "output_formats": ["json"]},
    "spotify": {"name": "Spotify", "description": "Spotify shows and episodes via the Spotify API", "output_formats": ["json"]},
    "youtube": {"name": "YouTube", "description": "YouTube videos and playlists via the YouTube Data API", "output_formats": ["json"]},
    "bilibili": {"name": "Bilibili", "description": "Bilibili video content via the public API", "output_formats": ["json"]},
    "yahoo_finance": {"name": "Yahoo Finance", "description": "Yahoo Finance market data quotes", "output_formats": ["json"]},
    "quandl": {"name": "Quandl (Nasdaq Data Link)", "description": "Financial and economic datasets via Quandl", "output_formats": ["json"]},
    "ssrn": {"name": "SSRN", "description": "SSRN preprint repository (working papers)", "output_formats": ["json"]},
    "gdelt": {"name": "GDELT", "description": "GDELT global news event database", "output_formats": ["json"]},
    "huggingface": {"name": "Hugging Face", "description": "Hugging Face hub datasets and content", "output_formats": ["json"]},
    "kaggle": {"name": "Kaggle", "description": "Kaggle datasets and competitions", "output_formats": ["json"]},
    "unpaywall": {"name": "Unpaywall", "description": "Open-access scholarly full text via Unpaywall", "output_formats": ["json"]},
    "core": {"name": "CORE", "description": "CORE aggregator of open-access research papers", "output_formats": ["json"]},
    "akshare": {"name": "AKShare", "description": "Chinese A-share market data via AKShare", "output_formats": ["json"]},
    "sec_edgar": {"name": "SEC EDGAR", "description": "SEC EDGAR company filings (ticker → CIK → submissions)", "output_formats": ["json"]},
    "edx_sitemap": {"name": "edX Sitemap", "description": "edX course catalog via sitemap index", "output_formats": ["xml", "json"]},
}


def _default_platform_info(source_type: str) -> dict[str, Any]:
    """Fallback metadata for source types without a curated entry."""
    return {
        "name": source_type.replace("_", " ").title(),
        "description": f"{source_type} source platform",
        "output_formats": ["json"],
    }


PLATFORMS: list[dict[str, Any]] = [
    {"type": source_type, **_PLATFORM_INFO.get(source_type, _default_platform_info(source_type))}
    for source_type in sorted(VALID_SOURCE_TYPES)
]

# ---------------------------------------------------------------------------
# Source key requirements (D4: requirement awareness at onboarding)
# ---------------------------------------------------------------------------

# Canonical env vars per source type live in
# ``autoinfo.config.SOURCE_KEY_ENV_VARS`` — the single source of truth
# shared with ``alerts.py`` (B3 credential-missing detection) so the two
# key-maps can never drift apart.  Mirrors the collector contract:
# handlers with ``requires_key() -> True`` (ap_api, reuters_mcp, unpaywall,
# youtube) plus the collect-time key guards (nyt, spotify, quandl, kaggle,
# core, email, email_imap).  Drives the missing-key detection behind
# ``init_project`` next_steps and the ``test_source`` key warning.

# Source settings keys that carry a credential directly, satisfying the
# requirement without any env var.
_SOURCE_SETTINGS_KEY_KEYS: frozenset[str] = frozenset(
    {"api_key", "client_id", "client_secret", "token", "password", "secret"}
)

_REQUIRED_KEYS_DOCS_REF = "docs/dev/required-api-keys.md"


def _source_key_status(source_type: str) -> dict[str, Any]:
    """Report whether *source_type* needs an API key and whether it is configured.

    Returns ``{"key_required", "key_configured", "env_vars", "missing_env_vars"}``.
    Types without a known key contract report ``key_required: False``.
    """
    env_vars = list(SOURCE_KEY_ENV_VARS.get(source_type, ()))
    if not env_vars:
        return {"key_required": False, "key_configured": True, "env_vars": []}
    missing = [v for v in env_vars if not os.environ.get(v)]
    return {
        "key_required": True,
        "key_configured": not missing,
        "env_vars": env_vars,
        "missing_env_vars": missing,
    }


def _demo_sources_defs(domain: str) -> list[dict[str, Any]]:
    """Load a demo domain's source definitions as plain dicts (pre-init).

    Returns ``[{"name", "type", "requires_key", "settings"}]``.  Used by
    ``_detect_missing_source_keys`` when no project config exists yet (the
    ``init_project`` flow) so onboarding can still see key requirements.
    """
    from autoinfo.cli.init import _DEMO_DOMAINS_DIR

    try:
        import yaml as _yaml

        demo_yaml = _DEMO_DOMAINS_DIR / domain / "sources.yaml"
        raw = _yaml.safe_load(demo_yaml.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    defs: list[dict[str, Any]] = []
    for s in raw.get("sources", []) or []:
        if not isinstance(s, dict):
            continue
        settings_raw = s.get("settings")
        defs.append(
            {
                "name": str(s.get("name", "")),
                "type": str(s.get("type", "api")),
                "requires_key": bool(s.get("requires_key", False)),
                "settings": dict(settings_raw) if isinstance(settings_raw, dict) else {},
            }
        )
    return defs


def _detect_missing_source_keys(
    domain: str,
    sources_yaml: Path | None = None,
) -> list[dict[str, Any]]:
    """Detect sources in *domain* whose required API keys are unconfigured.

    A source is flagged when at least one of its canonical env vars (see
    ``SOURCE_KEY_ENV_VARS``) is absent from the environment, or when the
    source declares ``requires_key: true`` in YAML with no known env var to
    point at.  A credential delivered in the source ``settings`` block
    satisfies the requirement.  Returns ``[{"name", "type", "env_vars"}]``
    where ``env_vars`` may be empty for YAML-declared requirements without a
    canonical env var.
    """
    if sources_yaml is not None:
        try:
            import yaml as _yaml

            raw = _yaml.safe_load(sources_yaml.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
        source_defs: list[dict[str, Any]] = []
        for s in raw.get("sources", []) or []:
            if not isinstance(s, dict):
                continue
            settings_raw = s.get("settings")
            source_defs.append(
                {
                    "name": str(s.get("name", "")),
                    "type": str(s.get("type", "api")),
                    "requires_key": bool(s.get("requires_key", False)),
                    "settings": dict(settings_raw) if isinstance(settings_raw, dict) else {},
                }
            )
    else:
        source_defs = []
        try:
            config = _load_config()
            domain_cfg = _find_domain(config, domain)
            if domain_cfg is not None:
                source_defs = [
                    {
                        "name": s.name,
                        "type": s.type,
                        "requires_key": bool(s.requires_key),
                        "settings": dict(s.settings or {}),
                    }
                    for s in domain_cfg.sources
                ]
        except Exception:
            source_defs = []
        if not source_defs:
            source_defs = _demo_sources_defs(domain)

    missing: list[dict[str, Any]] = []
    for sdef in source_defs:
        name = str(sdef.get("name", ""))
        stype = str(sdef.get("type", "api"))
        settings_raw = sdef.get("settings")
        settings = settings_raw if isinstance(settings_raw, dict) else {}
        if any(k in settings for k in _SOURCE_SETTINGS_KEY_KEYS):
            continue
        env_vars = list(SOURCE_KEY_ENV_VARS.get(stype, ()))
        if env_vars:
            unconfigured = [v for v in env_vars if not os.environ.get(v)]
            if unconfigured:
                missing.append({"name": name, "type": stype, "env_vars": unconfigured})
        elif sdef.get("requires_key"):
            missing.append({"name": name, "type": stype, "env_vars": []})
    return missing


def _handle_list_available_platforms() -> dict[str, Any]:
    """List all supported source platform types with descriptions."""
    return {"platforms": PLATFORMS}


def _handle_activate_domain(name: str) -> dict[str, Any]:
    """Activate a domain (set domain.active = True)."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, name)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{name}' is not configured. Use add_domain(name='{name}') to create it.",
            "actionable": True,
        }

    if domain_cfg.active:
        return {
            "domain": name,
            "active": True,
            "message": f"Domain '{name}' is already active",
        }

    domain_cfg.active = True
    _save_config(config)
    return {
        "domain": name,
        "active": True,
        "message": f"Domain '{name}' activated",
    }


def _handle_deactivate_domain(name: str) -> dict[str, Any]:
    """Deactivate a domain (set domain.active = False)."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, name)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{name}' is not configured. Use add_domain(name='{name}') to create it.",
            "actionable": True,
        }

    if not domain_cfg.active:
        return {
            "domain": name,
            "active": False,
            "message": f"Domain '{name}' is already inactive",
        }

    domain_cfg.active = False
    _save_config(config)
    return {
        "domain": name,
        "active": False,
        "message": f"Domain '{name}' deactivated",
    }


def _handle_remove_domain(name: str, confirm: bool = True, actor: str = "agent") -> dict[str, Any]:
    """Remove a domain configuration. Preserves all collected data on disk."""
    if not confirm:
        return {
            "error_code": ErrorCode.CONFIRMATION_REQUIRED.value,
            "message": (
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            "actionable": True,
        }
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, name)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{name}' is not configured. Use add_domain(name='{name}') to create it.",
            "actionable": True,
        }

    config.domains.remove(domain_cfg)
    _save_config(config)
    return {"removed": True, "domain": name}


def _handle_get_domain_config(name: str) -> dict[str, Any]:
    """Return full domain config including sources, topics, extract_fields."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, name)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{name}' is not configured. Use add_domain(name='{name}') to create it.",
            "actionable": True,
        }

    sources = [
        {
            "name": s.name,
            "type": s.type,
            "url": s.url,
            "quality_tier": s.quality_tier,
            "tos_classification": s.tos_classification,
            "requires_key": s.requires_key,
        }
        for s in domain_cfg.sources
    ]
    topics = [
        {
            "name": t.name,
            "keywords": t.keywords,
            "group": t.group,
            "relevance_threshold": t.relevance_threshold,
        }
        for t in domain_cfg.topics
    ]

    return {
        "domain": domain_cfg.name,
        "active": domain_cfg.active,
        "search_mode": domain_cfg.search_mode,
        "extract_fields": domain_cfg.extract_fields,
        "sources": sources,
        "source_count": len(sources),
        "topics": topics,
        "topic_count": len(topics),
    }


def _handle_set_domain_webhooks(
    domain: str,
    webhook_urls: list[str],
) -> dict[str, Any]:
    """Set webhook URLs for a domain. Replaces any existing URLs."""
    # -- Validate URLs ----------------------------------------------------
    invalid: list[str] = []
    for url in webhook_urls:
        if not url.startswith(("http://", "https://")):
            invalid.append(url)
    if invalid:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": (
                f"Invalid webhook URLs (must start with http:// or https://): "
                f"{invalid}"
            ),
            "actionable": True,
        }

    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    domain_cfg.webhook_urls = list(webhook_urls)
    _save_config(config)

    return {
        "domain": domain,
        "webhook_urls": domain_cfg.webhook_urls,
        "updated": True,
    }


def _handle_get_domain_webhooks(domain: str) -> dict[str, Any]:
    """Return the configured webhook URLs for a domain."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    return {
        "domain": domain,
        "webhook_urls": list(getattr(domain_cfg, "webhook_urls", [])),
    }


def _handle_add_domain(name: str, description: str = "") -> dict[str, Any]:
    """Create a new domain configuration (idempotent — returns existing config if domain already exists)."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, name)
    if domain_cfg is not None:
        return {
            "domain": name,
            "name": name,
            "description": domain_cfg.description,
            "sources": domain_cfg.sources,
            "topics": domain_cfg.topics,
            "active": domain_cfg.active,
            "created": False,
        }

    from autoinfo.config import DomainConfig

    new_domain = DomainConfig(name=name, description=description or "", active=True)
    config.domains.append(new_domain)
    _save_config(config)
    return {
        "domain": name,
        "name": name,
        "description": description or "",
        "sources": [],
        "topics": [],
        "active": True,
        "created": True,
    }


def _handle_get_domain_schema(domain: str) -> dict[str, Any]:
    """Return the schema / structure for a given domain."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return error_response(
            code=ErrorCode.DOMAIN_NOT_FOUND,
            message=f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            actionable=True,
        )

    sources = [
        {"name": s.name, "type": s.type, "url": s.url, "quality_tier": s.quality_tier, "tos_classification": s.tos_classification, "requires_key": s.requires_key}
        for s in domain_cfg.sources
    ]
    topics = [
        {"name": t.name, "keywords": t.keywords}
        for t in domain_cfg.topics
    ]

    extract_fields_schema: dict[str, dict[str, str]] = {
        "tl_dr": {"type": "string", "description": "One-sentence summary"},
        "key_points": {"type": "array", "description": "Bullet-point key findings"},
        "entities": {"type": "array", "description": "Extracted entities with types"},
        "relevance_score": {"type": "number", "description": "Relevance 0-100"},
    }

    # Include any custom extract_fields from the domain config
    for field_name in domain_cfg.extract_fields:
        if field_name not in extract_fields_schema:
            extract_fields_schema[field_name] = {
                "type": "string",
                "description": field_name.replace("_", " ").title(),
            }

    return {
        "domain": domain,
        "extract_fields": extract_fields_schema,
        "output_templates": [
            {"name": "digest", "description": "Scheduled knowledge digests", "access_level": "free"},
            {"name": "report", "description": "Thematic structured reports", "access_level": "free"},
            {"name": "tutorial", "description": "Learning path tutorials", "access_level": "free"},
            {"name": "presentation", "description": "Slide-based presentations", "access_level": "free"},
        ],
        "topics": topics,
        "sources": sources,
    }


def _handle_list_available_models() -> dict[str, Any]:
    """List available LLM models from configuration.

    Returns the full model pool: the primary model first, then every
    configured fallback entry (``task: fallback:<model>``), then every
    per-task model override (``task: <task name>``).  The primary entry
    keeps its historical shape (task/provider/model/api_key_configured);
    fallback and task entries are appended with additional fields
    (``inherits_provider``, ``max_tokens``).  ``count`` always equals
    ``len(models)``.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return {"models": [], "count": 0, "error_code": ErrorCode.INTERNAL_ERROR.value, "message": str(exc), "actionable": True}

    api_key_configured = bool(
        config.llm.api_key
        or os.environ.get("AUTOINFO_LLM_API_KEY")
    )

    models: list[dict[str, Any]] = [
        {
            "task": "default",
            "provider": config.llm.provider,
            "model": config.llm.model,
            "api_key_configured": api_key_configured,
        },
    ]

    # Fallback chain entries — appended after the primary.  An empty
    # provider means the entry inherits the primary provider at call time
    # (call_with_fallback, llm.py:714-727); the key is inherited too.
    for fb in config.llm.fallback:
        models.append(
            {
                "task": f"fallback:{fb.model}",
                "provider": fb.provider,
                "model": fb.model,
                "api_key_configured": bool(
                    fb.api_key
                    or config.llm.api_key
                    or os.environ.get("AUTOINFO_LLM_API_KEY")
                ),
                "inherits_provider": not bool(fb.provider),
            }
        )

    # Per-task model overrides — appended last.  Tasks inherit the
    # primary provider/model/key when their own fields are empty.
    for task_name, tc in config.llm.tasks.items():
        models.append(
            {
                "task": task_name,
                "provider": tc.provider,
                "model": tc.model,
                "api_key_configured": api_key_configured,
                "inherits_provider": not bool(tc.provider),
                "max_tokens": tc.max_tokens,
            }
        )

    return {"models": models, "count": len(models)}


def _handle_get_effective_llm_config(task: str | None = None) -> dict[str, Any]:
    """Resolve effective LLM config for a given task."""
    from autoinfo.config import get_effective_llm_config

    try:
        return get_effective_llm_config(task=task)
    except Exception as exc:
        return _error_from_exc(exc, "Failed to resolve the effective LLM configuration")


# ---------------------------------------------------------------------------
# Source management tools
# ---------------------------------------------------------------------------

_VALID_SOURCE_TYPES = VALID_SOURCE_TYPES


def _validate_url(
    url: str,
    source_type: str | None = None,
) -> str | None:
    """Return an error message if *url* is invalid, or ``None``.

    Accepts different URL schemes depending on *source_type*:
    - email: imap://, imaps://
    - pdf: file://, http://, https://
    - other types: http://, https://
    """
    if not url or not isinstance(url, str):
        return "URL is required"
    url = url.strip()
    if not url:
        return "URL is required"

    _valid_schemes: tuple[str, ...]
    if source_type == "email":
        _valid_schemes = ("imap://", "imaps://")
    elif source_type == "pdf":
        _valid_schemes = ("file://", "http://", "https://")
    else:
        _valid_schemes = ("http://", "https://")

    if not url.startswith(_valid_schemes):
        schemes_str = ", ".join(s.rstrip("/") + "://" for s in _valid_schemes)
        return f"URL must start with {schemes_str} for source type '{source_type or 'default'}'"
    parts = url.split("://", 1)
    if len(parts) != 2 or not parts[1]:
        return "URL must have a valid host"
    return None


def _validate_source_type(type_: str) -> str | None:
    """Return an error message if *type_* is invalid, or ``None``."""
    if not type_ or not isinstance(type_, str):
        return "Source type is required"
    if type_ not in _VALID_SOURCE_TYPES:
        return (
            f"Invalid source type '{type_}'. "
            f"Must be one of: {', '.join(sorted(_VALID_SOURCE_TYPES))}"
        )
    return None


def _handle_add_source(
    name: str,
    url: str,
    type: str = "api",
    domain: str = "",
    settings: dict[str, Any] | None = None,
    requires_key: bool | None = None,
    imap_server: str | None = None,
    imap_port: int | None = None,
    imap_username: str | None = None,
    imap_password: str | None = None,
    imap_mailbox: str | None = None,
    webhook_secret: str | None = None,
) -> dict[str, Any]:
    """Add a source (idempotent — dedup by url + type + domain).

    Type-specific parameters:
    - *email*: ``imap_server``, ``imap_port``, ``imap_username``,
      ``imap_password``, ``imap_mailbox``
    - *webhook*: ``webhook_secret`` (HMAC shared secret)
    - All types: ``settings`` dict for arbitrary configuration
    - *requires_key*: whether the source needs a credential.  Defaults to
      derived from the source type via ``SOURCE_KEY_ENV_VARS`` (a type with
      canonical env vars is key-requiring).
    """
    # --- Validation -----------------------------------------------------------
    type_error = _validate_source_type(type)
    if type_error:
        return {"error_code": ErrorCode.VALIDATION_ERROR.value, "message": type_error, "actionable": True}

    url_error = _validate_url(url, source_type=type)
    if url_error:
        return {"error_code": ErrorCode.VALIDATION_ERROR.value, "message": url_error, "actionable": True}

    # --- Merge convenience params into settings dict ---------------------------
    merged_settings: dict[str, Any] = dict(settings or {})
    if type == "email":
        if imap_server:
            merged_settings["host"] = imap_server
        if imap_port is not None:
            merged_settings["port"] = imap_port
        if imap_username:
            merged_settings["username"] = imap_username
        if imap_password:
            merged_settings["password"] = imap_password
        if imap_mailbox:
            merged_settings["mailbox"] = imap_mailbox
    elif type == "webhook":
        if webhook_secret:
            merged_settings["secret"] = webhook_secret

    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    # Idempotency check: same url + type + domain
    for existing in domain_cfg.sources:
        if existing.url == url and existing.type == type:
            dup_result: dict[str, Any] = {
                "source": {
                    "name": existing.name,
                    "type": existing.type,
                    "url": existing.url,
                    "domain": domain,
                    "quality_tier": existing.quality_tier,
                    "tos_classification": existing.tos_classification,
                    "requires_key": existing.requires_key,
                },
                "created": False,
                "source_id": f"{domain}:{existing.name}",
            }
            if existing.quality_tier >= 3:
                dup_result["warning"] = "Quality tier 3+ source — content may have lower authority."
            return dup_result

    # Determine next quality_tier based on type
    quality_tier = 1 if type in ("api", "rss") else 2
    _TIER_TOS_MAP = {1: "open", 2: "licensed", 3: "restricted", 4: "sensitive"}
    tos_classification = _TIER_TOS_MAP.get(quality_tier, "open")

    # requires_key: explicit param wins; otherwise derive from the source
    # type via the consolidated key map (a type with canonical env vars is
    # key-requiring).
    if requires_key is None:
        requires_key = type in SOURCE_KEY_ENV_VARS

    from autoinfo.config import SourceConfig

    new_source = SourceConfig(
        name=name,
        type=type,
        url=url,
        quality_tier=quality_tier,
        tos_classification=tos_classification,
        requires_key=requires_key,
        settings=merged_settings,
    )
    domain_cfg.sources.append(new_source)
    _save_config(config)

    result: dict[str, Any] = {
        "source": {
            "name": name,
            "type": type,
            "url": url,
            "domain": domain,
            "quality_tier": quality_tier,
            "tos_classification": tos_classification,
            "requires_key": requires_key,
        },
        "created": True,
        "source_id": f"{domain}:{name}",
    }

    # Include settings in result if non-empty
    if merged_settings:
        result["source"]["settings"] = merged_settings

    # Advisory warning for tier 3+ sources
    if quality_tier >= 3:
        result["warning"] = "Quality tier 3+ source — content may have lower authority."

    return result


def _handle_add_sources(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch-add sources with per-source error isolation."""
    results: list[dict[str, Any]] = []
    errored = 0

    for idx, src in enumerate(sources):
        try:
            result = _handle_add_source(
                name=src.get("name", f"source-{idx}"),
                url=src.get("url", ""),
                type=src.get("type", "api"),
                domain=src.get("domain", ""),
                settings=src.get("settings"),
                requires_key=src.get("requires_key"),
            )
            if "error_code" in result:
                errored += 1
                results.append({"index": idx, **result})
            else:
                results.append({"index": idx, **result})
        except Exception as exc:
            errored += 1
            results.append({
                "index": idx,
                "error_code": ErrorCode.INTERNAL_ERROR.value,
                "message": str(exc),
                "actionable": True,
            })

    return {
        "results": results,
        "total": len(sources),
        "succeeded": len(sources) - errored,
        "errored": errored,
    }


def _handle_remove_source(source_id: str, confirm: bool = True, actor: str = "agent") -> dict[str, Any]:
    """Remove a source by its source_id (``domain:name``)."""
    if not confirm:
        return {
            "error_code": ErrorCode.CONFIRMATION_REQUIRED.value,
            "message": (
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            "actionable": True,
        }
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    parts = source_id.split(":", 1)
    if len(parts) != 2:
        return {
            "error_code": ErrorCode.INVALID_SOURCE_ID.value,
            "message": "source_id must be in format 'domain:name'",
            "actionable": True,
        }
    domain_name, source_name = parts

    domain_cfg = _find_domain(config, domain_name)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain_name}' is not configured. Use add_domain(name='{domain_name}') to create it.",
            "actionable": True,
        }

    for i, existing in enumerate(domain_cfg.sources):
        if existing.name == source_name:
            removed = domain_cfg.sources.pop(i)
            _save_config(config)
            return {
                "removed": True,
                "source_id": source_id,
                "source": {
                    "name": removed.name,
                    "type": removed.type,
                    "url": removed.url,
                },
            }

    return {
        "error_code": ErrorCode.SOURCE_NOT_FOUND.value,
        "message": f"Source '{source_name}' not found in domain '{domain_name}'",
        "actionable": True,
    }


def _suggest_extract_fields(source_type: str) -> list[str]:
    """Return recommended extract fields for a given source type."""
    suggestions: dict[str, list[str]] = {
        "pubmed": ["pmid", "doi", "authors", "journal"],
        "api": ["pmid", "doi", "authors", "journal"],
        "rss": ["title", "pub_date", "description"],
        "web": ["description", "author", "published_date"],
    }
    return suggestions.get(source_type, ["title", "description"])


def _handle_test_source(url: str, type: str = "api") -> dict[str, Any]:
    """Test whether a source URL is reachable."""
    type_error = _validate_source_type(type)
    if type_error:
        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=type_error,
            actionable=True,
        )
    url_error = _validate_url(url, source_type=type)
    if url_error:
        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=url_error,
            actionable=True,
        )
    key_status = _source_key_status(type)
    key_missing_hint = ""
    if key_status["key_required"] and not key_status["key_configured"]:
        key_missing_hint = (
            f" Source type '{type}' requires an API key ({', '.join(key_status['missing_env_vars'])}), "
            f"which is not configured; collection may return no items. See {_REQUIRED_KEYS_DOCS_REF}."
        )
    try:
        if type == "api":
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
        else:
            resp = httpx.head(url, timeout=10.0, follow_redirects=True)
            if resp.status_code >= 400:
                resp = httpx.get(url, timeout=10.0, follow_redirects=True)

        content_type_header = resp.headers.get("content-type", "").split(";")[0].strip()
        content_preview = resp.text[:500] if resp.text else ""
        size_kb = len(resp.content) / 1024.0

        # Suggested extract fields based on source type
        suggested_fields = _suggest_extract_fields(type)

        result: dict[str, Any] = {
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "content_type": content_type_header,
            "content_preview": content_preview,
            "size_kb": round(size_kb, 1),
            "format": _infer_format(content_type_header, content_preview),
            "suggested_extract_fields": suggested_fields,
            "key_required": key_status["key_required"],
            "key_configured": key_status["key_configured"],
        }
        if key_missing_hint:
            result["warning"] = key_missing_hint.strip()
        return result
    except httpx.TimeoutException:
        return error_response(
            code=ErrorCode.TIMEOUT,
            message=f"Request to '{url}' timed out.{key_missing_hint}",
            actionable=True,
        )
    except Exception as exc:
        hint = f" {key_missing_hint.strip()}" if key_missing_hint else ""
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"{exc}{hint}",
            actionable=True,
        )


def _chain_contains_timeout(exc: BaseException) -> bool:
    """Walk the exception cause/context chain looking for a timeout.

    ``call_with_fallback`` raises ``RuntimeError`` with the last provider
    error as ``__cause__``; a timeout can sit anywhere in that chain (e.g.
    a wrapped ``httpx.TimeoutException``).
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.TimeoutException):
            return True
        current = current.__cause__ or current.__context__
    return False


def _handle_test_llm_connection(
    provider: str = "",
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """Test LLM connectivity with the current or overridden configuration.

    Mirrors ``_handle_test_source``: entry validation → error envelope →
    result dict.  Key validation is handler-internal (NOT the dispatcher
    guard) so an explicit ``api_key`` param can bypass the config/env key
    check.  ``config_source`` is ``"params"`` when any override param is
    supplied, else ``"config"``.
    """
    import time

    from autoinfo.config import Config, LLMConfig, get_config_path, load_config

    # Resolve current effective config — param overrides win, the rest
    # inherits the on-disk values (the same source get_effective_llm_config
    # reads internally).
    current_provider = ""
    current_model = ""
    current_base_url = ""
    current_key = ""
    current_timeout: float | None = None
    current_json_mode = False
    current_reasoning_model = False
    current_fallback: list[LLMConfig] = []
    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            current_provider = config.llm.provider
            current_model = config.llm.model
            current_base_url = config.llm.base_url
            current_key = config.llm.api_key
            current_timeout = config.llm.timeout
            current_json_mode = config.llm.json_mode
            current_reasoning_model = config.llm.reasoning_model
            current_fallback = config.llm.fallback
    except Exception:
        pass

    eff_provider = provider or current_provider
    eff_model = model or current_model
    eff_base_url = base_url or current_base_url
    eff_key = api_key or current_key

    # Resolve ${ENV} references so a placeholder without a backing env var
    # does not count as a real key.
    if eff_key.startswith("${") and eff_key.endswith("}"):
        eff_key = os.environ.get(eff_key[2:-1], "")
    if not eff_key:
        eff_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")

    # Handler-internal key check (mirrors _handle_suggest_keywords): an
    # explicit api_key param skips the check; otherwise a config/env key is
    # required.  NOT the dispatcher guard — that only inspects config/env
    # keys and would make explicit overrides unreachable.
    if not eff_key:
        return error_response(
            code=ErrorCode.LLM_NOT_CONFIGURED,
            message=(
                "LLM is not configured. Use configure_llm() to set up your "
                "API key or pass api_key explicitly. "
                f"See {_REQUIRED_KEYS_DOCS_REF} for the full list of API keys "
                "and environment variables."
            ),
            actionable=True,
        )

    # Temporary config: param overrides on top of the inherited values so the
    # configured fallback chain still applies to the probe call.
    temp_llm = LLMConfig(
        provider=eff_provider,
        model=eff_model,
        api_key=eff_key,
        base_url=eff_base_url,
        json_mode=current_json_mode,
        reasoning_model=current_reasoning_model,
        # current_timeout is Optional (absent when no on-disk config exists);
        # coerce to the LLMConfig default (120.0) so LLMConfig.timeout stays float.
        timeout=current_timeout or 120.0,
        fallback=current_fallback,
    )
    temp_config = Config(llm=temp_llm)

    tested_model = temp_llm.resolve_model() or (
        f"{eff_provider or 'openrouter'}/{eff_model or 'deepseek/deepseek-chat'}"
    )
    config_source = (
        "params" if any([provider, model, base_url, api_key]) else "config"
    )

    start = time.monotonic()
    try:
        response = call_with_fallback(
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=16,
            temperature=0.0,
            timeout=current_timeout,
            config=temp_config,
        )
        latency_ms = round((time.monotonic() - start) * 1000.0, 1)
        content = ""
        if response is not None and getattr(response, "choices", None):
            content = response.choices[0].message.content or ""
        return {
            "connectable": True,
            "tested_model": tested_model,
            "latency_ms": latency_ms,
            "message": f"LLM connection successful ({tested_model}).",
            "config_source": config_source,
        }
    except Exception as exc:
        logger.exception("LLM connection test failed")
        if _chain_contains_timeout(exc):
            return error_response(
                code=ErrorCode.TIMEOUT,
                message=(
                    f"LLM connection test timed out for '{tested_model}'. "
                    "Check the base_url and network connectivity. "
                    f"See {_REQUIRED_KEYS_DOCS_REF}."
                ),
                actionable=True,
            )
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message=(
                f"LLM connection test failed for '{tested_model}': {exc}. "
                "Check the provider/model/base_url configuration. "
                f"See {_REQUIRED_KEYS_DOCS_REF}."
            ),
            actionable=True,
        )


def _infer_format(content_type: str, content_preview: str) -> str:
    """Infer content format from content-type header and body preview."""
    if "xml" in content_type:
        return "xml"
    if "json" in content_type:
        return "json"
    if "html" in content_type or "xhtml" in content_type:
        return "html"
    if content_preview.strip().startswith(("<rss", "<feed", "<?xml")):
        return "rss"
    if content_preview.strip().startswith("{"):
        return "json"
    return "unknown"


def _handle_list_sources(domain: str) -> dict[str, Any]:
    """List all sources for a given domain."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    sources = [
        {
            "source_id": f"{domain}:{s.name}",
            "name": s.name,
            "type": s.type,
            "url": s.url,
            "quality_tier": s.quality_tier,
            "tos_classification": s.tos_classification,
            "requires_key": s.requires_key,
        }
        for s in domain_cfg.sources
    ]
    return {"domain": domain, "sources": sources, "count": len(sources)}


# ---------------------------------------------------------------------------
# Topic management tools
# ---------------------------------------------------------------------------


def _handle_add_topic(
    domain: str,
    name: str,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Add a topic to a domain."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    # Idempotency check: same name
    for existing in domain_cfg.topics:
        if existing.name == name:
            return {
                "topic": {"name": name, "keywords": existing.keywords},
                "created": False,
                "topic_id": f"{domain}:{name}",
            }

    from autoinfo.config import TopicConfig

    new_topic = TopicConfig(name=name, keywords=keywords or [])
    domain_cfg.topics.append(new_topic)
    _save_config(config)

    return {
        "topic": {"name": name, "keywords": keywords or []},
        "created": True,
        "topic_id": f"{domain}:{name}",
    }


def _handle_remove_topic(domain: str, topic_id: str, confirm: bool = True, actor: str = "agent") -> dict[str, Any]:
    """Remove a topic by its topic_id (``domain:name``)."""
    if not confirm:
        return {
            "error_code": ErrorCode.CONFIRMATION_REQUIRED.value,
            "message": (
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            "actionable": True,
        }
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    topic_name = topic_id.split(":", 1)[-1] if ":" in topic_id else topic_id
    for i, existing in enumerate(domain_cfg.topics):
        if existing.name == topic_name:
            removed = domain_cfg.topics.pop(i)
            _save_config(config)
            return {
                "removed": True,
                "topic_id": topic_id,
                "topic": {"name": removed.name, "keywords": removed.keywords},
            }

    return {
        "error_code": ErrorCode.TOPIC_NOT_FOUND.value,
        "message": f"Topic '{topic_name}' not found in domain '{domain}'",
        "actionable": True,
    }


def _handle_list_topics(domain: str) -> dict[str, Any]:
    """List all topics for a given domain."""
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    topics = [
        {"name": t.name, "keywords": t.keywords}
        for t in domain_cfg.topics
    ]
    return {"domain": domain, "topics": topics, "count": len(topics)}


def _handle_list_keywords(
    domain: str,
    topic: str | None = None,
) -> dict[str, Any]:
    """List keywords with topic grouping, multi-language support, and scoring info.

    Returns keywords from two sources:
    1. Topic-level keywords from ``.autoinfo/config.yaml`` (existing behaviour).
    2. Managed keywords from ``knowledge/<domain>/_keywords.yaml``.

    When *topic* is provided, only keywords for that topic are returned
    (from config only — managed keywords are returned separately).
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    # --- Topic-level keywords from config (existing behaviour) ---
    results: list[dict[str, Any]] = []
    for t in domain_cfg.topics:
        if topic and t.name != topic:
            continue
        entry: dict[str, Any] = {
            "name": t.name,
            "keywords": t.keywords,
            "group": t.group,
            "relevance_threshold": t.relevance_threshold,
            "keyword_count": len(t.keywords) if isinstance(t.keywords, list) else sum(len(v) for v in t.keywords.values()) if isinstance(t.keywords, dict) else 0,
        }
        results.append(entry)

    # --- Managed keywords from _keywords.yaml (new) ---
    from autoinfo.keywords import KeywordsFile

    kf = KeywordsFile()
    managed_entries = kf.load(domain)
    managed = [
        {
            "keyword": e.keyword,
            "state": e.state.value,
            "aliases": e.aliases,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
            "source": e.source,
        }
        for e in managed_entries
    ]

    return {
        "domain": domain,
        "topic": topic or "*",
        "topics": results,
        "count": len(results),
        "keywords_file": {
            "path": str(kf._path(domain)),
            "exists": kf._path(domain).is_file(),
            "entries": managed,
            "entry_count": len(managed),
        },
    }


# ---------------------------------------------------------------------------
# Topic group management tools
# ---------------------------------------------------------------------------


def _handle_topic_group_add(
    domain: str,
    group_name: str,
    topic_names: list[str],
) -> dict[str, Any]:
    """Assign a group to one or more topics.

    For each topic name in *topic_names*, find the matching topic in the
    domain config and set its ``group`` field to *group_name*.  Topics that
    do not exist in the domain are reported in the ``not_found`` list.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    assigned: list[str] = []
    not_found: list[str] = []

    for name in topic_names:
        found = False
        for t in domain_cfg.topics:
            if t.name == name:
                t.group = group_name
                assigned.append(name)
                found = True
                break
        if not found:
            not_found.append(name)

    if assigned:
        _save_config(config)

    return {
        "domain": domain,
        "group": group_name,
        "assigned": assigned,
        "not_found": not_found,
    }


def _handle_topic_group_remove(domain: str, group_name: str) -> dict[str, Any]:
    """Remove a group assignment from all topics in that group.

    Clears the ``group`` field (sets to ``""``) on every topic whose
    current group matches *group_name*.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    cleared: list[str] = []
    for t in domain_cfg.topics:
        if t.group == group_name:
            t.group = ""
            cleared.append(t.name)

    if cleared:
        _save_config(config)

    return {
        "domain": domain,
        "group": group_name,
        "cleared": cleared,
        "removed": len(cleared) > 0,
    }


# ---------------------------------------------------------------------------
# Keywords management tools (approve / reject / suggest)
# ---------------------------------------------------------------------------


def _handle_approve_keyword(domain: str, keyword: str) -> dict[str, Any]:
    """Approve a keyword — move from ``auto_added`` → ``verified``."""
    from autoinfo.keywords import KeywordsFile

    kf = KeywordsFile()
    result = kf.approve_keyword(domain=domain, keyword=keyword)
    if result is None:
        return {
            "error_code": ErrorCode.KEYWORD_NOT_FOUND.value,
            "message": f"Keyword '{keyword}' not found in domain '{domain}'",
            "actionable": True,
        }
    return {
        "success": True,
        "domain": domain,
        "keyword": keyword,
        "state": result.state.value,
    }


def _handle_reject_keyword(domain: str, keyword: str) -> dict[str, Any]:
    """Reject a keyword — move to ``deprecated``."""
    from autoinfo.keywords import KeywordsFile

    kf = KeywordsFile()
    result = kf.deprecate_keyword(domain=domain, keyword=keyword)
    if result is None:
        return {
            "error_code": ErrorCode.KEYWORD_NOT_FOUND.value,
            "message": f"Keyword '{keyword}' not found in domain '{domain}'",
            "actionable": True,
        }
    return {
        "success": True,
        "domain": domain,
        "keyword": keyword,
        "state": result.state.value,
    }


def _handle_suggest_keywords(
    domain: str,
    text: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Use LLM to suggest keywords from the given text."""
    import json

    from autoinfo.config import get_config_path, load_config

    timeout: float | None = None
    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            model = config.llm.resolve_model() or (
                f"{config.llm.provider or 'openrouter'}/"
                f"{config.llm.model or 'deepseek/deepseek-chat'}"
            )
            api_key = config.llm.api_key or os.environ.get("AUTOINFO_LLM_API_KEY", "")
            base_url = config.llm.base_url or None
            json_mode = config.llm.json_mode
            timeout = config.llm.timeout
        else:
            model = "deepseek/deepseek-chat"
            api_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
            base_url = None
            json_mode = False
    except Exception:
        model = "deepseek/deepseek-chat"
        api_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
        base_url = None
        json_mode = True

    if not api_key:
        return error_response(
            code=ErrorCode.LLM_NOT_CONFIGURED,
            message="LLM is not configured. Use configure_llm() to set up your API key. See docs/dev/required-api-keys.md for the full list of API keys and environment variables.",
            actionable=True,
        )

    system_prompt = (
        "You are a keyword extraction assistant. Given a text, suggest "
        f"up to {limit} relevant keywords or short phrases (2-5 words) "
        "that capture the core topics. "
        "Respond with valid JSON only: an array of strings. "
        "Example: [\"machine learning\", \"neural networks\", \"deep learning\"]"
    )

    user_prompt = f"Extract up to {limit} keywords from this text:\n\n{text}"

    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=json_mode,
            max_tokens=500,
            temperature=0.3,
            base_url=base_url,
            api_key=api_key or None,
            timeout=timeout,
        )
        content: str = response.choices[0].message.content or ""

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # LLM returned empty or non-JSON content.  Fall back to a
            # deterministic keyword extraction from the text itself so the
            # tool still returns useful suggestions instead of failing
            # (issue #215; DeepSeek-V4-Flash occasionally returns empty
            # content for longer prompts).
            import re

            from autoinfo.process import _is_valid_discovery_keyword

            words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text)
            seen: list[str] = []
            for w in words:
                wl = w.lower()
                if wl not in seen and _is_valid_discovery_keyword(wl):
                    seen.append(wl)
                if len(seen) >= limit:
                    break
            if seen:
                return {
                    "domain": domain,
                    "suggestions": seen,
                    "count": len(seen),
                    "source": "deterministic-fallback",
                }
            return error_response(
                code=ErrorCode.EMPTY_RESULT,
                message=(
                    "Keyword suggestion failed: LLM returned empty or "
                    "non-JSON content and no keywords could be extracted "
                    "from the text. Retry the request."
                ),
                actionable=True,
            )
        if isinstance(parsed, list):
            suggestions = parsed
        elif isinstance(parsed, dict):
            for key in ("keywords", "suggestions", "tags", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    suggestions = parsed[key]
                    break
            else:
                suggestions = list(parsed.values()) if parsed else []
        else:
            suggestions = []

        suggestions = [str(s).strip() for s in suggestions if s]
        suggestions = suggestions[:limit]

        return {
            "domain": domain,
            "suggestions": suggestions,
            "count": len(suggestions),
        }
    except Exception as exc:
        logger.exception("Keyword suggestion failed")
        return _error_from_exc(exc, "Keyword suggestion failed")


# ---------------------------------------------------------------------------
# Custom extraction tools
# ---------------------------------------------------------------------------


def _handle_extract_fields(content_id: str, schema: list[str]) -> dict[str, Any]:
    """On-demand re-extraction with custom schema.

    Retrieves the KB entry for *content_id*, reconstructs an :class:`Item`
    from its stored content, and runs LLM extraction with the given *schema*.
    This does **not** persist the result — it is a one-off re-extraction.
    """
    from autoinfo.kb import KBStore
    from autoinfo.llm import LLMExtractor
    from autoinfo.models import Item

    store = KBStore()
    entry = store.get_entry(content_id)
    if entry is None:
        return error_response(
            code=ErrorCode.NOT_FOUND,
            message=f"Entry '{content_id}' not found",
            actionable=True,
        )

    # Reconstruct a minimal Item from the KB entry's stored content
    item = Item(
        id=content_id,
        source_name=entry.get("source_platform", ""),
        source_type=entry.get("source_type", ""),
        source_url=entry.get("source_url", ""),
        title=entry.get("title", ""),
        content=entry.get("content", ""),
        collected_at=entry.get("collected_at", ""),
        domain=entry.get("domain", ""),
    )

    extractor = LLMExtractor()
    result = extractor.extract(item, schema=schema)

    return {
        "content_id": content_id,
        "tl_dr": result.tl_dr,
        "key_points": result.key_points,
        "entities": result.entities,
        "relevance_score": result.relevance_score,
        "custom_fields": result.custom_fields,
    }


def _handle_get_extraction(content_id: str) -> dict[str, Any]:
    """Return what was extracted for a KB entry.

    Reads the Markdown frontmatter to retrieve ``extracted_fields`` (populated
    when custom extraction fields were used during processing).
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    entry = store.get_entry(content_id)
    if entry is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"Entry '{content_id}' not found",
            "actionable": True,
        }

    # Parse the Markdown frontmatter for extracted_fields
    file_path = entry.get("file_path", "")
    extracted_fields: dict[str, Any] = {}
    if file_path:
        fp = Path(file_path)
        if fp.is_file():
            raw = fp.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end_idx = raw.find("---", 3)
                if end_idx != -1:
                    fm_raw = raw[3:end_idx]
                    import yaml  # noqa: PLC0415 — deferred import

                    fm = yaml.safe_load(fm_raw) or {}
                    extracted_fields = fm.get("extracted_fields", {})

    return {
        "content_id": content_id,
        "title": entry.get("title", ""),
        "summary": entry.get("summary", ""),
        "relevance_score": entry.get("relevance_score", 0),
        "dedup_status": entry.get("dedup_status", "unknown"),
        "quality_tier": entry.get("quality_tier", 1),
        "extracted_fields": extracted_fields,
    }


# ---------------------------------------------------------------------------
# KB / output tools (v0.1 stubs — v0.2+ implementation)
# ---------------------------------------------------------------------------


def _handle_search_knowledge_base(
    query: str,
    domain: str | None = None,
    limit: int = 20,
    offset: int = 0,
    mode: str = "fts5",
    filter_tags: list[str] | None = None,
    filter_date_from: str | None = None,
    filter_date_to: str | None = None,
    filter_quality_tier_min: int | None = None,
    filter_quality_tier_max: int | None = None,
    filter_content_type: str | None = None,
    filter_language: str | None = None,
    user_id: str | None = None,
    include_stale: bool = False,
    filter_custom_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Search the knowledge base using FTS5 full-text search.

    Parameters
    ----------
    domain:
        Optional domain filter. When ``None`` (default), searches across
        all domains. When an empty string or a specific domain name is
        passed, results are filtered to that domain.
    mode:
        Search mode: ``"fts5"`` (default), ``"hybrid"`` (FTS5 + vector),
        or ``"vector"``.  Falls back to FTS5 when vector search is
        unavailable.
    include_stale:
        If False (default), stale entries are demoted to the bottom
        of search results.
    filter_custom_fields:
        Faceted filter over the ``custom_fields`` JSON column (todo 25,
        output-quality-mega — product-analysis metadata search).  Each
        key is a dot-path into ``custom_fields`` (e.g.
        ``"product_analysis.action_required"``); an empty-string value
        matches entries where the field exists and is non-empty, any
        other value matches entries where the field's JSON value equals
        that text.
    """
    from autoinfo.kb import KBStore

    kb_status = _detect_kb_status()
    if kb_status == "uninitialized":
        return error_response(
            ErrorCode.EMPTY_RESULT,
            "Knowledge base not initialized. Run collect_sources() + process_collection() first.",
        )
    if kb_status == "empty":
        return {
            "entries": [],
            "count": 0,
            "message": "Knowledge base initialized but has no entries yet. Run collect_sources() + process_collection() to populate.",
        }

    store = KBStore()
    return store.search_knowledge_base(
        query=query,
        domain=domain or "",
        limit=limit,
        offset=offset,
        mode=mode,
        filter_tags=filter_tags,
        filter_date_from=filter_date_from,
        filter_date_to=filter_date_to,
        filter_quality_tier_min=filter_quality_tier_min,
        filter_quality_tier_max=filter_quality_tier_max,
        filter_content_type=filter_content_type,
        filter_language=filter_language,
        filter_user_id=user_id,
        include_stale=include_stale,
        filter_custom_fields=filter_custom_fields,
    )


def _handle_query_knowledge_graph(
    entity: str,
    relation: str = "related_to",
    domain: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Query the knowledge graph for entities related to *entity*."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.query_knowledge_graph(
        entity=entity,
        relation=relation,
        domain=domain,
        limit=limit,
    )


def _handle_flag_for_knowledge_base(
    summary_id: str,
    tags: list[str] | None = None,
    importance: int = 3,
) -> dict[str, Any]:
    """Flag a summary for KB inclusion.

    Dispatches to ``KBStore.flag_for_knowledge_base``.
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.flag_for_knowledge_base(
        summary_id=summary_id, tags=tags, importance=importance
    )


def _handle_get_summary(summary_id: str) -> dict[str, Any]:
    """Return full detail for a summary entry.

    Dispatches to ``KBStore.get_summary``.
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.get_summary(summary_id=summary_id)


def _handle_link_items(
    item_a_id: str,
    item_b_id: str,
    relation_type: str = "related",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a link between two KB entries."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.link_items(
        item_a_id=item_a_id,
        item_b_id=item_b_id,
        relation_type=relation_type,
        metadata=metadata,
    )


def _handle_get_item_relations(
    item_id: str,
    relation_type: str | None = None,
) -> dict[str, Any]:
    """Return all relations where an item participates."""
    from autoinfo.kb import KBStore

    store = KBStore()
    relations = store.get_item_relations(
        item_id=item_id, relation_type=relation_type
    )
    return {"item_id": item_id, "relations": relations, "count": len(relations)}


def _handle_get_entry_history(entry_id: str) -> dict[str, Any]:
    """Return all saved backup versions for an entry."""
    from autoinfo.kb import KBStore

    store = KBStore()
    versions = store.get_entry_history(entry_id=entry_id)
    return {"entry_id": entry_id, "versions": versions, "count": len(versions)}


def _handle_restore_entry_version(version_id: str) -> dict[str, Any]:
    """Restore an entry from a saved version backup."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.restore_entry_version(version_id=version_id)


def _handle_compare_versions(
    entry_id: str, version_a: str, version_b: str
) -> dict[str, Any]:
    """Compare two versions of a KB entry and return a structured diff."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.compare_versions(
        entry_id=entry_id, version_a=version_a, version_b=version_b
    )


def _handle_get_collection_stats(period: str = "daily") -> dict[str, Any]:
    """Aggregated collection statistics for the given period."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.get_collection_stats(period=period)


def _handle_get_collection_diff(since_collection_id: str) -> dict[str, Any]:
    """Return entries collected since a previous collection ID."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.get_collection_diff(
        since_collection_id=since_collection_id
    )


def _handle_get_domain_decay(
    domain: str, ttl_days: int = 90
) -> dict[str, Any]:
    """Compute decay / staleness metrics for a domain."""
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.get_domain_decay(domain=domain, ttl_days=ttl_days)


def _handle_create_kb_draft(
    raw_ids: list[str],
    title: str,
    summary: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Draft entry from one or more Raw entries."""
    from autoinfo.kb import MIN_KB_CONTENT_CHARS, KBStore

    # Enforce the same 50-char content floor at the Draft boundary: a
    # Draft compiled from below-min raw content is an empty shell (#279).
    store = KBStore(min_content_chars=MIN_KB_CONTENT_CHARS)
    try:
        entry = store.create_kb_draft(
            raw_ids=raw_ids, title=title, summary=summary, tags=tags
        )
        return entry.to_dict()
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_reject_kb_draft(
    draft_id: str,
    reason: str = "",
    action: str = "back_to_raw",
) -> dict[str, Any]:
    """Reject a Draft, moving it back to 01-Raw or archiving."""
    from autoinfo.kb import KBStore

    store = KBStore()
    try:
        return store.reject_kb_draft(
            draft_id=draft_id, reason=reason, action=action
        )
    except (ValueError, FileNotFoundError) as exc:
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_list_kb_tier(
    domain: str,
    tier: str,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
) -> dict[str, Any]:
    """List entries in a specific KB tier.

    Parameters
    ----------
    user_id:
        Optional user_id filter — only entries belonging to this user
        are returned. When ``None``, no user filter is applied.
    """
    from autoinfo.kb import KBStore

    kb_status = _detect_kb_status()
    if kb_status == "uninitialized":
        return error_response(
            ErrorCode.EMPTY_RESULT,
            "Knowledge base not initialized. Run collect_sources() + process_collection() first.",
        )
    if kb_status == "empty":
        return {
            "domain": domain,
            "tier": tier,
            "entries": [],
            "count": 0,
            "message": "Knowledge base initialized but has no entries yet. Run collect_sources() + process_collection() to populate.",
        }

    store = KBStore()
    entries = store.list_kb_tier(domain=domain, tier=tier, limit=limit, offset=offset, user_id=user_id)
    return {
        "domain": domain,
        "tier": tier,
        "entries": entries,
        "count": len(entries),
    }


def _handle_promote_kb_draft(
    entry_id: str,
    user_id: str = "",
) -> dict[str, Any]:
    """Promote a Draft KB entry to the 03-Wiki tier.

    Admission-gated agent promotion: the draft must pass the curation gate
    (source provenance, G0, G1/G3 thresholds, G4 factual consistency) or
    the promotion is rejected and a ``_failed/<domain>/<entry_id>.md``
    marker is written while the draft stays in 02-Draft. The draft must be
    in 02-Draft tier. Returns the promoted entry path and metadata.
    """
    from autoinfo.kb import KBStore

    try:
        store = KBStore()
        result = store.promote_kb_draft(draft_id=entry_id)
        return result
    except FileNotFoundError as exc:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": str(exc),
            "actionable": True,
        }
    except PermissionError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("promote_kb_draft failed for '%s'", entry_id)
        return _error_from_exc(exc, "promote_kb_draft failed")


def _handle_demote_kb_wiki(entry_id: str, actor: str = "agent") -> dict[str, Any]:
    """Demote a 03-Wiki entry back to 02-Draft (director-only backdoor).

    Content is preserved: the file moves from ``03-Wiki/`` to ``02-Draft/``
    under the same domain and topic, frontmatter ``tier`` is rewritten to
    ``02-Draft`` and a ``demoted_at`` timestamp is appended; the original
    promotion provenance is kept.  The actor must be whitelisted in
    ``AUTOINFO_DIRECTOR_ACTORS`` (default ``director``) or the call is
    refused with a ``DIRECTOR_ONLY`` error envelope.
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    try:
        return store.demote_entry(entry_id=entry_id, caller=actor)
    except DirectorOnlyError as exc:
        return error_response(
            code=ErrorCode.DIRECTOR_ONLY,
            message=str(exc),
            actionable=True,
        )


def _handle_force_promote(draft_id: str, actor: str = "agent") -> dict[str, Any]:
    """Force-promote a 02-Draft entry to 03-Wiki, skipping the admission gate.

    Director-only backdoor: provenance / G0 / G1 / G3 / G4 checks are not
    evaluated; the frontmatter records ``promotion_source: director``.  The
    actor must be whitelisted in ``AUTOINFO_DIRECTOR_ACTORS`` (default
    ``director``) or the call is refused with a ``DIRECTOR_ONLY`` error
    envelope.
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    try:
        return store.force_promote_kb_draft(draft_id=draft_id, caller=actor)
    except DirectorOnlyError as exc:
        return error_response(
            code=ErrorCode.DIRECTOR_ONLY,
            message=str(exc),
            actionable=True,
        )


def _handle_promote_pending(domain: str, actor: str = "agent") -> dict[str, Any]:
    """Promote all eligible 02-Draft entries for *domain* (batch sweep).

    Each 02-Draft entry is admission-checked via the existing promote path;
    entries previously rejected (carrying a ``_failed/<domain>/<entry_id>.md``
    marker) are skipped and never retried.  Returns a summary with
    promoted/rejected/failed per entry and per-entry failure reasons; the
    sweep never raises (per-entry failures are collected in the summary).
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    config = None
    try:
        config = _load_config()
    except Exception:
        config = None
    try:
        return store.promote_pending_drafts(
            domain=domain, config=config, caller=actor
        )
    except Exception as exc:
        logger.exception("promote_pending failed for domain '%s'", domain)
        return _error_from_exc(exc, "promote_pending failed")


def _handle_reindex_kb(domain: str) -> dict[str, Any]:
    """Rebuild SQLite index from disk frontmatter.

    Dispatches to ``KBStore.reindex_knowledge_base``.
    """
    from autoinfo.kb import KBStore

    store = KBStore()
    return store.reindex_knowledge_base(domain=domain)


def _handle_list_output_templates(domain: str = "", user_id: str | None = None) -> dict[str, Any]:
    """List available output templates for a domain, optionally filtered by user tier.

    When *user_id* is provided, templates are filtered so that only those
    whose ``access_level`` is accessible to the user are returned.
    When *user_id* is ``None``, all templates are returned (backward compatible).
    """
    from autoinfo.billing import check_access
    from autoinfo.output import list_output_templates as _list_output_templates

    result = _list_output_templates(domain=domain)
    templates: list[dict[str, Any]] = result["templates"]

    if user_id is not None:
        filtered: list[dict[str, Any]] = []
        for t in templates:
            access = check_access(user_id, t["access_level"])
            if access["allowed"]:
                filtered.append(t)
        result["templates"] = filtered
        result["count"] = len(filtered)

    return result


OUTPUTS_DIR = Path("outputs")

_PERSIST_EXT_BY_FORMAT: dict[str, str] = {
    "json": ".json",
    "agent": ".json",
    "markdown": ".md",
    "html": ".html",
    "audio": ".mp3",
    "video": ".mp4",
    "epub": ".epub",
    "audiobook": ".zip",
}


def _persist_output(
    domain: str,
    product: str,
    format: str,
    content: Any,
) -> str:
    """Write *content* under ``OUTPUTS_DIR/<domain>``; return the relative path.

    Filename: ``<product>-<format>-<YYYYmmdd-HHMMSS>.<ext>`` where the
    extension is derived from *format* (json/agent → ``.json``, markdown →
    ``.md``, html → ``.html``, audio → ``.mp3``, epub → ``.epub``,
    audiobook → ``.zip``).

    Content handling:

    - json/agent: pretty-printed JSON (``ensure_ascii=False, indent=2``).
      *content* may be a dict (re-dumped for pretty JSON) or a str that is
      parsed first; unparseable strings are written raw.
    - audio/epub/audiobook: *content* is a base64 string in the envelope —
      decoded and written as bytes.
    - everything else (markdown/html): written as text as-is.
    """
    _stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    _ext = _PERSIST_EXT_BY_FORMAT.get(format, ".txt")
    _dir = OUTPUTS_DIR / domain
    os.makedirs(_dir, exist_ok=True)
    _path = _dir / f"{product}-{format}-{_stamp}{_ext}"
    if format in ("json", "agent"):
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                pass
        if isinstance(content, (dict, list)):
            _path.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            _path.write_text(str(content), encoding="utf-8")
    elif format in ("audio", "epub", "audiobook"):
        _path.write_bytes(base64.b64decode(content))
    elif format == "video":
        # Two accepted shapes: (1) _render_video_scaffold's JSON blob
        # {"video_path": ...} — copy the referenced MP4 (#254);
        # (2) base64-encoded MP4 bytes (audio-compatible test contract).
        blob: Any = None
        if isinstance(content, str):
            try:
                blob = json.loads(content)
            except (ValueError, TypeError):
                blob = None
        video_path = (
            blob.get("video_path") if isinstance(blob, dict) else None
        )
        if isinstance(video_path, str) and os.path.isfile(video_path):
            import shutil

            shutil.copy2(video_path, _path)
        elif isinstance(blob, dict):
            _path.write_text(
                json.dumps(blob, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            _path.write_bytes(base64.b64decode(content))
    else:
        _path.write_text(str(content), encoding="utf-8")
    return str(OUTPUTS_DIR / domain / _path.name)


def _output_text(result: str | Any) -> str:
    """Unwrap a generate_* result to its plain text.

    ``generate_digest``/``generate_report`` return ``str | DeliveryOutput``;
    the MCP handlers never pass *delivery_gate_configs*, so a
    ``DeliveryOutput`` can only appear if the contract changes.  Normalise to
    ``str`` so callers can safely ``json.loads`` / persist the text.
    """
    from autoinfo.output import DeliveryOutput

    return result.output if isinstance(result, DeliveryOutput) else result


def _maybe_persist_output(
    envelope: dict[str, Any],
    persist: bool,
    domain: str,
    product: str,
    format: str,
    content: Any,
) -> dict[str, Any]:
    """Add ``persisted_path`` to *envelope* when *persist* is true.

    With ``persist=False`` (the default) the envelope is returned
    unchanged — byte-identical to the pre-persistence behavior.
    """
    if persist:
        envelope["persisted_path"] = _persist_output(
            domain, product, format, content
        )
    return envelope


def _handle_generate_digest(
    domain: str,
    period: str = "weekly",
    format: str = "markdown",
    custom_instructions: str = "",
    target_audience: str = "",
    include_stale: bool = False,
    recipients: list[str] | None = None,
    user_id: str = "",
    max_items: int = 0,
    product: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """Generate a digest of KB entries for *domain* over the given *period*.

    Dispatches to :func:`autoinfo.output.generate_digest`.
    """
    from datetime import date, timedelta

    from autoinfo.kb import KBStore
    from autoinfo.output import generate_digest as _generate_digest

    product_template = None
    if product:
        from autoinfo.output import PRODUCT_TEMPLATES

        _product_row = next(
            (row for row in PRODUCT_TEMPLATES if row["name"] == product),
            None,
        )
        if _product_row is None:
            _valid = ", ".join(
                sorted(row["name"] for row in PRODUCT_TEMPLATES)
            )
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"Unknown product '{product}'. Valid products: {_valid}",
                "actionable": True,
                "success": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": f"Unknown product '{product}'. Valid products: {_valid}",
                    "actionable": True,
                },
            }
        product_template = _product_row["template"]

    _period_days = {"daily": 1, "weekly": 7, "monthly": 30}
    _days = _period_days.get(period, 7)
    _date_from = (date.today() - timedelta(days=_days)).isoformat()
    _store = KBStore()
    _preview = _store.list_entries(domain=domain, date_from=_date_from, limit=1)
    if not _preview:
        return {
            "success": True,
            "domain": domain,
            "format": format,
            "period": period,
            "status": "noop",
            "content": "",
            "message": f"No entries found for domain '{domain}' in the requested period. Run collect_sources() + process_collection() first.",
        }

    try:
        result = _generate_digest(
            domain=domain,
            period=period,
            format=format,
            custom_instructions=custom_instructions,
            target_audience=target_audience,
            include_stale=include_stale,
            recipients=recipients,
            user_id=user_id,
            max_items=max_items,
            product_template=product_template,
        )
        if format in ("json", "agent"):
            # Parse JSON string back to dict for structured MCP response
            import json as _json

            _parsed = _json.loads(_output_text(result))
            return _maybe_persist_output(
                {"success": True, "format": format, "content": _parsed},
                persist, domain, "digest", format, _parsed,
            )
        if format == "audio":
            return _maybe_persist_output(
                {
                    "success": True,
                    "format": "audio",
                    "content_type": "audio/mp3",
                    "encoding": "base64",
                    "content": result,
                },
                persist, domain, "digest", "audio", result,
            )
        if format == "video":
            # _render_video_scaffold returns a JSON status blob with video_path.
            import json as _json2

            try:
                parsed = _json2.loads(_output_text(result))
            except (ValueError, TypeError):
                parsed = {"status": "ok", "video_path": result}
            return _maybe_persist_output(
                {"success": True, "format": "video", **parsed},
                persist, domain, "digest", "video", result,
            )
        if format in ("epub", "audiobook"):
            return _maybe_persist_output(
                {
                    "success": True,
                    "format": format,
                    "content_type": (
                        "application/epub+zip" if format == "epub" else "audio/mpeg"
                    ),
                    "encoding": "base64",
                    "content": result,
                },
                persist, domain, "digest", format, result,
            )
        return _maybe_persist_output(
            {"success": True, "format": format, "content": result},
            persist, domain, "digest", format, result,
        )
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Digest generation failed for domain '%s'", domain)
        return _error_from_exc(exc, "Digest generation failed")


def _handle_generate_report(
    domain: str,
    format: str = "markdown",
    period: str = "monthly",
    custom_instructions: str = "",
    target_audience: str = "",
    user_id: str = "",
    report_type: str = "standard",
    product: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """Generate a structured report for *domain* over the given *period*.

    Dispatches to :func:`autoinfo.output.generate_report`.
    """
    from datetime import date, timedelta

    from autoinfo.kb import KBStore
    from autoinfo.output import generate_report as _generate_report

    product_template = None
    if product:
        from autoinfo.output import PRODUCT_TEMPLATES

        _product_row = next(
            (row for row in PRODUCT_TEMPLATES if row["name"] == product),
            None,
        )
        if _product_row is None:
            _valid = ", ".join(
                sorted(row["name"] for row in PRODUCT_TEMPLATES)
            )
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"Unknown product '{product}'. Valid products: {_valid}",
                "actionable": True,
                "success": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": f"Unknown product '{product}'. Valid products: {_valid}",
                    "actionable": True,
                },
            }
        product_template = _product_row["template"]
    elif report_type == "column":
        from autoinfo.output import PRODUCT_TEMPLATES

        product_template = next(
            (row["template"] for row in PRODUCT_TEMPLATES if row["name"] == "column"),
            None,
        )
    _period_days = {"daily": 1, "weekly": 7, "monthly": 30}
    _days = _period_days.get(period, 7)
    _date_from = (date.today() - timedelta(days=_days)).isoformat()
    _store = KBStore()
    _preview = _store.list_entries(domain=domain, date_from=_date_from, limit=1)
    if not _preview:
        return {
            "success": True,
            "domain": domain,
            "format": format,
            "period": period,
            "status": "noop",
            "content": "",
            "message": f"No entries found for domain '{domain}' in the requested period. Run collect_sources() + process_collection() first.",
        }

    try:
        # Persist under the spec product name so matrix evidence resolves
        # (column was persisted as report-markdown-* and never counted for
        # the column:markdown cell — issue #229).
        _persist_product = "column" if report_type == "column" else "report"
        result = _generate_report(domain=domain, format=format, period=period, custom_instructions=custom_instructions, target_audience=target_audience, user_id=user_id, report_type=report_type, product_template=product_template)
        if format in ("json", "agent"):
            import json as _json

            parsed = _json.loads(_output_text(result))
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domain,
                    "format": format,
                    "period": period,
                    "content": parsed,
                },
                persist, domain, _persist_product, format, parsed,
            )
        if format == "audio":
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domain,
                    "format": "audio",
                    "period": period,
                    "content_type": "audio/mp3",
                    "encoding": "base64",
                    "content": result,
                },
                persist, domain, _persist_product, "audio", result,
            )
        if format == "video":
            import json as _json3

            try:
                parsed = _json3.loads(_output_text(result))
            except (ValueError, TypeError):
                parsed = {"status": "ok", "video_path": result}
            content = result
            if isinstance(result, str) and os.path.isfile(result):
                # generate_video returns an MP4 file path; persist expects
                # the same base64 payload shape as audio (#254).
                content = base64.b64encode(Path(result).read_bytes()).decode("ascii")
                parsed.setdefault("encoding", "base64")
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domain,
                    "format": "video",
                    "period": period,
                    **parsed,
                },
                persist, domain, _persist_product, "video", content,
            )
        if format in ("epub", "audiobook"):
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domain,
                    "format": format,
                    "period": period,
                    "content_type": (
                        "application/epub+zip" if format == "epub" else "audio/mpeg"
                    ),
                    "encoding": "base64",
                    "content": result,
                },
                persist, domain, _persist_product, format, result,
            )
        return _maybe_persist_output(
            {
                "success": True,
                "domain": domain,
                "format": format,
                "period": period,
                "content": result,
            },
            persist, domain, _persist_product, format, result,
        )
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Report generation failed for domain '%s'", domain)
        return _error_from_exc(exc, "Report generation failed")


def _handle_generate_cross_domain_report(
    domains: list[str],
    format: str = "markdown",
    period: str = "monthly",
    target_audience: str = "",
    report_type: str = "standard",
    user_id: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """Generate a synthesis report across multiple domains.

    Delegates to :func:`autoinfo.output.generate_report` with the
    ``domains`` parameter, using the first domain as primary for
    backward-compatible metadata.

    Parameters
    ----------
    user_id:
        Optional end-user ID forwarded to ``generate_report`` so the
        user's stored ``content_preference`` is honored.  Empty by
        default (no preference lookup).
    """
    from autoinfo.output import generate_report as _generate_report

    # Validate at least 2 domains
    if not isinstance(domains, list) or len(domains) < 2:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": "At least 2 domains are required for cross-domain report generation",
            "actionable": True,
        }

    # Validate all domains exist
    try:
        config = _load_config()
    except FileNotFoundError:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": (
                "No project configuration found.  Run `init_project` "
                "first to set up at least one domain. "
                "See docs/dev/director-user-guide.md for setup instructions."
            ),
            "actionable": True,
        }
    except Exception as exc:
        return _error_from_exc(exc, "Cross-domain report generation failed")
    valid_names = {d.name for d in config.domains}
    invalid = [d for d in domains if d not in valid_names]
    if invalid:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": f"Unknown domain(s): {', '.join(invalid)}. Valid domains: {', '.join(sorted(valid_names))}",
            "actionable": True,
        }

    try:
        result = _generate_report(
            domain=domains[0],
            domains=domains,
            format=format,
            period=period,
            target_audience=target_audience,
            report_type=report_type,
            user_id=user_id,
        )
        if format in ("json", "agent"):
            import json as _json

            parsed = _json.loads(_output_text(result))
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domains[0],
                    "domains": domains,
                    "format": format,
                    "period": period,
                    "content": parsed,
                },
                persist, domains[0], "report", format, parsed,
            )
        if format == "audio":
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domains[0],
                    "domains": domains,
                    "format": "audio",
                    "period": period,
                    "content_type": "audio/mp3",
                    "encoding": "base64",
                    "content": result,
                },
                persist, domains[0], "report", "audio", result,
            )
        if format == "video":
            import json as _json4

            try:
                parsed = _json4.loads(_output_text(result))
            except (ValueError, TypeError):
                parsed = {"status": "ok", "video_path": result}
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domains[0],
                    "domains": domains,
                    "format": "video",
                    "period": period,
                    **parsed,
                },
                persist, domains[0], "report", "video", result,
            )
        if format in ("epub", "audiobook"):
            return _maybe_persist_output(
                {
                    "success": True,
                    "domain": domains[0],
                    "domains": domains,
                    "format": format,
                    "period": period,
                    "content_type": (
                        "application/epub+zip" if format == "epub" else "audio/mpeg"
                    ),
                    "encoding": "base64",
                    "content": result,
                },
                persist, domains[0], "report", format, result,
            )
        return _maybe_persist_output(
            {
                "success": True,
                "domain": domains[0],
                "domains": domains,
                "format": format,
                "period": period,
                "content": result,
            },
            persist, domains[0], "report", format, result,
        )
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception(
            "Cross-domain report generation failed for domains %s",
            domains,
        )
        return _error_from_exc(exc, "Cross-domain report generation failed")


def _handle_generate_tutorial(
    domain: str,
    topic: str | None = None,
    format: str = "markdown",
    custom_instructions: str = "",
    user_id: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """Generate a structured tutorial for *domain*.

    Thin wrapper around :func:`autoinfo.output.generate_tutorial`.

    Parameters
    ----------
    user_id:
        Optional end-user ID forwarded to ``generate_tutorial`` so the
        user's stored ``content_preference`` is honored.  Empty by
        default (no preference lookup).
    """
    from autoinfo.output import generate_tutorial as _generate_tutorial

    try:
        result = _generate_tutorial(domain=domain, format=format, custom_instructions=custom_instructions, user_id=user_id)
        if format == "agent":
            import json as _json
            return _maybe_persist_output(
                {"success": True, "format": format, "domain": domain, "topic": topic, "content": _json.loads(_output_text(result))},
                persist, domain, "tutorial", format, _json.loads(_output_text(result)),
            )
        return _maybe_persist_output(
            {"success": True, "format": format, "domain": domain, "topic": topic, "content": result},
            persist, domain, "tutorial", format, result,
        )
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Tutorial generation failed for domain '%s'", domain)
        return _error_from_exc(exc, "Tutorial generation failed")


def _handle_generate_presentation(
    domain: str,
    topic: str | None = None,
    slides: int = 10,
    format: str = "markdown",
    custom_instructions: str = "",
    user_id: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """Generate a slide-based presentation for *topic* within *domain*.

    Thin wrapper around :func:`autoinfo.output.generate_presentation`.

    Parameters
    ----------
    user_id:
        Optional end-user ID forwarded to ``generate_presentation`` so
        the user's stored ``content_preference`` is honored.  Empty by
        default (no preference lookup).
    """
    from autoinfo.output import generate_presentation as _generate_presentation

    try:
        topic_str = topic or ""
        result = _generate_presentation(domain=domain, topic=topic_str, slide_count=slides, format=format, custom_instructions=custom_instructions, user_id=user_id)
        if format == "agent":
            import json as _json
            return _maybe_persist_output(
                {"success": True, "domain": domain, "topic": topic, "slides": slides, "format": format, "content": _json.loads(_output_text(result))},
                persist, domain, "presentation", format, _json.loads(_output_text(result)),
            )
        return _maybe_persist_output(
            {"success": True, "domain": domain, "topic": topic, "slides": slides, "format": format, "content": result},
            persist, domain, "presentation", format, result,
        )
    except ValueError as exc:
        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            actionable=True,
        )
    except Exception as exc:
        logger.exception("Presentation generation failed for domain '%s'", domain)
        return _error_from_exc(exc, "Presentation generation failed")


def _handle_send_email_digest(
    domain: str,
    period: str = "weekly",
    user_id: str = "",
) -> dict[str, Any]:
    """Generate and send a digest via SMTP email.

    Dispatches to :func:`autoinfo.email_sender.send_digest`.
    Only sends when ``config.email.enabled == True``.

    Parameters
    ----------
    domain:
        Domain to generate the digest for.
    period:
        Digest period: ``"daily"``, ``"weekly"``, ``"monthly"``.
        Defaults to ``"weekly"``.
    user_id:
        Optional end-user ID forwarded to the email sender so the
        user's stored ``content_preference`` is honored.  Empty by
        default (no preference lookup).

    Returns
    -------
    dict
        ``{success, message, recipients, domain, period}``.
    """
    from autoinfo.email_sender import send_digest as _send_email

    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    if not config.email.enabled:
        return error_response(
            code=ErrorCode.EMAIL_NOT_ENABLED,
            message=(
                "Email delivery is not enabled. "
                "Set 'email.enabled: true' in .autoinfo/config.yaml "
                "and configure email.smtp_host, email.from_addr, "
                "and email.to_addrs."
            ),
            actionable=True,
        )

    try:
        result = _send_email(domain=domain, period=period, config=config, user_id=user_id)
        return result
    except RuntimeError as exc:
        return error_response(
            code=ErrorCode.EMAIL_SEND_FAILED,
            message=str(exc),
            actionable=True,
        )
    except Exception as exc:
        logger.exception("Email digest send failed for domain '%s'", domain)
        return _error_from_exc(exc, "Email digest send failed")


def _handle_localize_content(**kwargs: Any) -> dict[str, Any]:
    """Translate a KB entry or raw text via LLM.

    Dispatches to :func:`autoinfo.output.localize_content`.
    Supports both content_id mode (reads from KB, stores translation)
    and direct content mode (returns translated text only).

    Parameters match :func:`autoinfo.output.localize_content`.
    """
    from autoinfo.output import localize_content as _localize

    try:
        result = _localize(**kwargs)
        return result
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Localization failed")
        return _error_from_exc(exc, "Localization failed")


# ---------------------------------------------------------------------------
# Export / Import (2)
# ---------------------------------------------------------------------------


def _handle_export_kb(
    domain: str,
    format: str = "markdown",
    scope: str = "domain",
    entry_ids: list[str] | None = None,
    output_path: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Export knowledge base entries to specified format.

    Dispatches to :func:`autoinfo.output.export_kb`.

    Parameters
    ----------
    domain:
        Domain name (e.g. medical-research).
    format:
        Output format: ``"markdown"``, ``"json"``, ``"sqlite"``, ``"csv"``,
        ``"pdf"``, or ``"graphml"``.  Defaults to ``"markdown"``.
    scope:
        Export scope: ``"domain"`` (all entries in domain), ``"entry"``
        (specific entries by ID), or ``"collection"`` (collection-scoped).
        Defaults to ``"domain"``.
    entry_ids:
        Specific entry IDs to export (used when scope == ``"entry"``).
    output_path:
        Optional explicit output path.  When omitted, the file is written
        to the ``exports/`` directory with an auto-generated name.
    base_url:
        Site base URL required when ``format`` is ``"sitemap"`` (e.g.
        ``"https://your-site.example"``).  Ignored for other formats.

    Returns
    -------
    dict
        ``{format, path, entries_count, file_size_bytes, domain, success}``.
    """
    from autoinfo.output import export_kb as _export_kb

    try:
        collection_id: str | None = None
        if scope == "entry" and entry_ids:
            collection_id = entry_ids[0]
        elif scope == "collection":
            collection_id = "__all__"

        result = _export_kb(
            domain=domain,
            format=format,
            collection_id=collection_id,
            base_url=base_url,
        )

        file_path = result.get("path", "")
        if file_path and os.path.isfile(file_path):
            result["file_size_bytes"] = os.path.getsize(file_path)
        else:
            result["file_size_bytes"] = 0

        return result
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Export KB failed for domain '%s'", domain)
        return _error_from_exc(exc, "Export KB failed")


def _handle_import_kb(
    domain: str,
    format: str,
    data: str,
) -> dict[str, Any]:
    """Import entries or source suggestions into the KB.

    Dispatches to the appropriate handler in :mod:`autoinfo.importer`
    based on *format*.

    Parameters
    ----------
    domain:
        Target domain name (e.g. medical-research).
    format:
        Import format: ``"markdown"``, ``"json"``, ``"csv"``, or ``"opml"``.
    data:
        Raw content string to import (YAML+Markdown, JSON, CSV, or OPML XML).

    Returns
    -------
    dict
        For ``markdown`` / ``json`` / ``csv``::
            ``{domain, format, entries_imported, entries_failed, errors}``
        For ``opml``::
            ``{type: "source_list", suggestions, action_required, domain, format}``
    """
    from autoinfo.importer import import_kb as _import_kb

    try:
        result = _import_kb(domain=domain, format=format, data=data)
        return result
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("Import KB failed for domain '%s'", domain)
        return _error_from_exc(exc, "Import KB failed")


# ---------------------------------------------------------------------------
# Schedule management tools
# ---------------------------------------------------------------------------


def _handle_list_schedules() -> dict[str, Any]:
    """List all configured schedules."""
    try:
        from autoinfo.cli.cron import load_schedules

        schedules = load_schedules()
        items = []
        for name, s in schedules.items():
            items.append({
                "name": name,
                "expression": s.expression,
                "domain": s.domain,
                "enabled": s.enabled,
                "last_run": s.last_run,
                "created_at": s.created_at,
            })
        return {"schedules": items, "count": len(items)}
    except Exception as exc:
        return _error_from_exc(exc, "Failed to list schedules")


def _handle_add_schedule(
    name: str,
    expression: str,
    domain: str,
    schedule_type: str = "collection",
    recipients: list[str] | None = None,
    output_format: str = "html",
) -> dict[str, Any]:
    """Add a new collection or digest schedule."""
    try:
        if schedule_type not in ("collection", "digest"):
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"Invalid schedule type '{schedule_type}'. Must be 'collection' or 'digest'.",
                "actionable": True,
            }

        if schedule_type == "digest":
            if not recipients:
                return {
                    "error_code": ErrorCode.VALIDATION_ERROR.value,
                    "message": "Recipients are required for digest-type schedules.",
                    "actionable": True,
                }
            try:
                config = _load_config()
            except Exception as exc:
                return _error_from_exc(exc, "Failed to load the project configuration")
            if not config.email.enabled:
                return {
                    "error_code": ErrorCode.EMAIL_NOT_ENABLED.value,
                    "message": (
                        "Email delivery is not enabled. Digest schedules require "
                        "email to be configured. Set 'email.enabled: true' in "
                        ".autoinfo/config.yaml and configure email.smtp_host, "
                        "email.from_addr, and email.to_addrs."
                    ),
                    "actionable": True,
                }

        from croniter import croniter

        if not croniter.is_valid(expression):
            return {
                "error_code": ErrorCode.INVALID_CRON_EXPRESSION.value,
                "message": f"'{expression}' is not a valid cron expression",
                "actionable": True,
            }

        from autoinfo.cli.cron import Schedule, _now_iso, load_schedules, save_schedules

        schedules = load_schedules()
        if name in schedules:
            return {
                "error_code": ErrorCode.SCHEDULE_ALREADY_EXISTS.value,
                "message": f"A schedule named '{name}' already exists",
                "actionable": True,
            }

        new_schedule = Schedule(
            name=name,
            expression=expression,
            domain=domain,
            type=schedule_type,
            enabled=True,
            last_run=None,
            created_at=_now_iso(),
            recipients=recipients or [],
            format=output_format,
        )
        schedules[name] = new_schedule
        save_schedules(schedules)
        return {
            "created": True,
            "schedule": {
                "name": name,
                "expression": expression,
                "domain": domain,
                "type": schedule_type,
                "enabled": True,
                "last_run": None,
                "created_at": new_schedule.created_at,
                "recipients": recipients or [],
                "format": output_format,
            },
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to add schedule")


def _handle_remove_schedule(name: str, confirm: bool = False, actor: str = "agent") -> dict[str, Any]:
    """Remove a collection schedule."""
    if not confirm:
        return {
            "error_code": ErrorCode.CONFIRMATION_REQUIRED.value,
            "message": (
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            "actionable": True,
        }
    try:
        from autoinfo.cli.cron import load_schedules, save_schedules

        schedules = load_schedules()
        if name not in schedules:
            return {
                "error_code": ErrorCode.SCHEDULE_NOT_FOUND.value,
                "message": f"Schedule '{name}' not found",
                "actionable": True,
            }
        removed = schedules.pop(name)
        save_schedules(schedules)
        return {
            "removed": True,
            "schedule": {
                "name": removed.name,
                "expression": removed.expression,
                "domain": removed.domain,
            },
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to remove schedule")


def _handle_run_schedules(
    dry_run: bool = False,
    name: str | None = None,
) -> dict[str, Any]:
    """Run due schedules."""
    try:
        from autoinfo.cli.cron import run_due_schedules

        results = run_due_schedules(
            dry_run=dry_run,
            schedule_filter=name,
            json_output=True,
        )
        due_count = sum(1 for r in results if r.get("due"))
        ran_count = sum(1 for r in results if r.get("ran"))
        return {
            "results": results,
            "due_count": due_count,
            "ran_count": ran_count,
            "total_checked": len(results),
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to run schedules")


def _handle_get_schedule_status(
    schedule_id: str | None = None,
) -> dict[str, Any]:
    """Get status of all schedules or a specific one."""
    try:
        from autoinfo.cli.cron import get_schedule_status

        schedules = get_schedule_status(schedule_id=schedule_id)
        return {
            "schedules": schedules,
            "count": len(schedules),
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to get schedule status")


# ---------------------------------------------------------------------------
# Delivery schedule management tools
# ---------------------------------------------------------------------------


def _handle_add_delivery_schedule(
    domain: str,
    cron_expression: str,
    output_type: str = "digest",
    channel: str = "email",
    recipients: list[str] | None = None,
    output_format: str = "html",
    period: str = "weekly",
    user_id: str = "",
) -> dict[str, Any]:
    """Add a new delivery schedule for periodic output generation + delivery.

    Parameters
    ----------
    domain:
        Domain to generate output for.
    cron_expression:
        Cron expression (e.g. ``"0 8 * * 1"`` for Monday 8 AM).
    output_type:
        Output type: ``"digest"`` or ``"report"``.
    channel:
        Delivery channel name (e.g. ``"email"``, ``"webhook"``).
    recipients:
        Recipient identifiers (emails, webhook URLs, …).
    output_format:
        Output format: ``"markdown"``, ``"html"``, ``"json"``, ``"agent"``,
        ``"audio"``, ``"pdf"``.
    period:
        Content period: ``"daily"``, ``"weekly"``, ``"monthly"``.
    user_id:
        Optional end-user ID whose stored ``content_preference`` is
        applied when the scheduled output is generated.  Empty by
        default (no preference lookup).
    """
    try:
        from autoinfo.delivery.scheduler import (
            VALID_CHANNELS,
            VALID_FORMATS,
            VALID_OUTPUT_TYPES,
            DeliverySchedule,
            DeliveryScheduler,
        )

        if output_type not in VALID_OUTPUT_TYPES:
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": (
                    f"Invalid output_type '{output_type}'. "
                    f"Must be one of: {', '.join(sorted(VALID_OUTPUT_TYPES))}"
                ),
                "actionable": True,
            }
        if output_format not in VALID_FORMATS:
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": (
                    f"Invalid format '{output_format}'. "
                    f"Must be one of: {', '.join(sorted(VALID_FORMATS))}"
                ),
                "actionable": True,
            }
        if channel not in VALID_CHANNELS:
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": (
                    f"Invalid channel '{channel}'. "
                    f"Must be one of: {', '.join(sorted(VALID_CHANNELS))}"
                ),
                "actionable": True,
            }

        from croniter import croniter

        if not croniter.is_valid(cron_expression):
            return {
                "error_code": ErrorCode.INVALID_CRON_EXPRESSION.value,
                "message": f"'{cron_expression}' is not a valid cron expression",
                "actionable": True,
            }

        new_schedule = DeliverySchedule(
            cron_expression=cron_expression,
            domain=domain,
            output_type=output_type,
            format=output_format,
            channel=channel,
            recipients=recipients or [],
            period=period,
            user_id=user_id,
        )
        scheduler = DeliveryScheduler()
        scheduler.add_schedule(new_schedule)

        return {
            "created": True,
            "schedule_id": new_schedule.id,
            "schedule": {
                "id": new_schedule.id,
                "cron_expression": new_schedule.cron_expression,
                "domain": new_schedule.domain,
                "output_type": new_schedule.output_type,
                "format": new_schedule.format,
                "channel": new_schedule.channel,
                "recipients": new_schedule.recipients,
                "period": new_schedule.period,
                "user_id": new_schedule.user_id,
                "enabled": new_schedule.enabled,
                "created_at": new_schedule.created_at,
            },
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to add delivery schedule")


def _handle_list_delivery_schedules() -> dict[str, Any]:
    """List all configured delivery schedules."""
    try:
        from dataclasses import asdict

        from autoinfo.delivery.scheduler import DeliveryScheduler

        scheduler = DeliveryScheduler()
        schedules = scheduler.list_schedules()
        items = []
        for s in schedules:
            d = asdict(s)
            items.append(d)
        return {"schedules": items, "count": len(items)}
    except Exception as exc:
        return _error_from_exc(exc, "Failed to list delivery schedules")


def _handle_remove_delivery_schedule(
    schedule_id: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Remove a delivery schedule by ID."""
    if not confirm:
        return error_response(
            code=ErrorCode.CONFIRMATION_REQUIRED,
            message=(
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            actionable=True,
        )
    try:
        from autoinfo.delivery.scheduler import DeliveryScheduler

        scheduler = DeliveryScheduler()
        removed = scheduler.remove_schedule(schedule_id)
        if not removed:
            return error_response(
                code=ErrorCode.SCHEDULE_NOT_FOUND,
                message=f"Delivery schedule '{schedule_id}' not found",
                actionable=True,
            )
        return {
            "removed": True,
            "schedule_id": schedule_id,
        }
    except Exception as exc:
        return _error_from_exc(exc, "Failed to remove delivery schedule")


# ---------------------------------------------------------------------------
# CEFR classification tool
# ---------------------------------------------------------------------------


def _handle_classify_cefr(text: str, lang: str = "en") -> dict[str, Any]:
    """Classify text into a CEFR level (A1-C2) using the configured LLM.

    Dispatches to :func:`autoinfo.cefr.classify_text`.

    Parameters
    ----------
    text:
        Text to classify.
    lang:
        Language code: ``"en"``, ``"zh"``, or ``"ja"`` (default ``"en"``).

    Returns
    -------
    dict
        ``{cefr_level, confidence, text_preview}``.
    """
    try:
        config = _load_config()
        model_config: dict[str, Any] = {}
        if config.cefr.model:
            model_config["model"] = config.cefr.model
        elif config.llm.provider and config.llm.model:
            llm_model = config.llm.model
            if "/" not in llm_model:
                llm_model = f"{config.llm.provider}/{llm_model}"
            model_config["model"] = llm_model
        if config.llm.api_key:
            model_config["api_key"] = config.llm.api_key
        if config.llm.base_url:
            model_config["base_url"] = config.llm.base_url
    except Exception:
        model_config = {}

    from autoinfo.cefr import classify_text

    result = classify_text(text=text, lang=lang, model_config=model_config)
    text_preview = text[:200] + "..." if len(text) > 200 else text
    return {
        "cefr_level": result["cefr_level"],
        "confidence": result["confidence"],
        "text_preview": text_preview,
    }


# ---------------------------------------------------------------------------
# Source health / feedback tools
# ---------------------------------------------------------------------------


def _handle_get_source_health(source_id: str) -> dict[str, Any]:
    """Return health status for a single source."""
    from autoinfo.status import get_source_health

    return get_source_health(source_id=source_id)


def _handle_rate_item(
    item_id: str,
    rating: int,
    feedback: str = "",
) -> dict[str, Any]:
    """Store user rating/feedback for a collected item."""
    from autoinfo.status import rate_item

    return rate_item(item_id=item_id, rating=rating, feedback=feedback)


# ---------------------------------------------------------------------------
# Q&A tool
# ---------------------------------------------------------------------------


def _handle_query_collected(
    query: str,
    domain: str,
    content_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Q&A on collected content via FTS5 + LLM synthesis.

    Dispatches to ``autoinfo.qa.query_collected``.
    """
    from autoinfo.qa import query_collected as _qa

    return _qa(query=query, domain=domain, content_ids=content_ids)


# ---------------------------------------------------------------------------
# Project / batch / config tools (v0.5)
# ---------------------------------------------------------------------------


def _handle_init_project(
    domain: str,
    project_name: str = "",
    dry_run: bool = False,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
) -> dict[str, Any]:
    """Initialize AutoInfo project skeleton (creates .autoinfo/ directory,
    config, demo domain). Idempotent — safe to call when already initialized.

    Parameters
    ----------
    domain:
        Demo domain name (e.g. medical-research).
    project_name:
        Optional human-friendly project name.
    dry_run:
        If True, preview what would be created without writing files.
    llm_provider:
        Override the default LLM provider (e.g. \"openai\").
    llm_model:
        Override the default LLM model (e.g. \"gpt-4\").
    llm_base_url:
        Override the default LLM base URL (e.g. \"http://localhost:11434/v1\").
    """
    # Lazy imports to avoid circular dependencies
    from autoinfo.cli.init import _DEMO_DOMAINS_DIR, _ensure_dir, _run_init
    from autoinfo.mcp.errors import ErrorCode

    autoinfo_dir = Path.cwd() / ".autoinfo"
    config_path = autoinfo_dir / "config.yaml"

    # Idempotency check — skip if already initialized
    if config_path.exists() and not dry_run:
        return {
            "status": "skipped",
            "message": "Already initialized",
        }

    # Validate domain against available demo domains
    demo_sources = _DEMO_DOMAINS_DIR / domain / "sources.yaml"
    if not demo_sources.is_file():
        available = sorted(
            d.name for d in _DEMO_DOMAINS_DIR.iterdir()
            if d.is_dir()
        )
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": f"Unknown demo domain '{domain}'. Available: {available}",
            "actionable": True,
            "success": False,
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"Unknown demo domain '{domain}'. Available: {available}",
                "actionable": True,
            },
        }

    if dry_run:
        missing_keys = _detect_missing_source_keys(domain, sources_yaml=demo_sources)
        next_steps = [
            "configure_llm(api_key='...', provider='...', model='...')",
            "configure_llm(llm_fallback=[{'model': 'mimo-v2.5', 'base_url': 'https://opencode.ai/zen/go/v1'}], llm_tasks={'extraction': {'model': 'deepseek-v4-flash'}}); verify with test_llm_connection()",
            f"collect_sources(domain='{domain}')",
            f"process_collection(domain='{domain}')",
        ]
        for mk in missing_keys:
            if mk["env_vars"]:
                envs = ", ".join(mk["env_vars"])
                next_steps.append(
                    f"Set {envs} for source '{mk['name']}' (type: {mk['type']}) before collecting from it"
                )
            else:
                next_steps.append(
                    f"Configure an API key for source '{mk['name']}' (type: {mk['type']}) before collecting from it"
                )
        if missing_keys:
            next_steps.append(
                f"See {_REQUIRED_KEYS_DOCS_REF} for the full catalog of source API keys and environment variables"
            )
        return {
            "status": "dry_run",
            "domain": domain,
            "project_name": project_name,
            "autoinfo_dir": str(autoinfo_dir),
            "llm_provider": llm_provider or "(default)",
            "llm_model": llm_model or "(default)",
            "llm_base_url": llm_base_url or "(default)",
            "would_create_dirs": [
                ".autoinfo/",
                "knowledge/00-Inbox/",
                "knowledge/01-Raw/",
                "knowledge/02-Draft/",
                "knowledge/03-Wiki/",
                "collections/",
                "outputs/",
            ],
            "would_create_files": [
                ".autoinfo/config.yaml",
            ],
            "message": "Dry run — no files were created",
            "next_steps": next_steps,
        }

    try:
        _ensure_dir(autoinfo_dir)
        # _run_init takes list[str]; a bare str would iterate char-by-char.
        _run_init([domain], autoinfo_dir, project_name=project_name)

        if llm_provider or llm_model or llm_base_url:
            import yaml
            config_path = autoinfo_dir / "config.yaml"
            if config_path.exists():
                with open(config_path, "r") as f:
                    cfg = yaml.safe_load(f)
                if llm_provider:
                    cfg.setdefault("llm", {})["provider"] = llm_provider
                if llm_model:
                    cfg.setdefault("llm", {})["model"] = llm_model
                if llm_base_url:
                    cfg.setdefault("llm", {})["base_url"] = llm_base_url
                with open(config_path, "w") as f:
                    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        missing_keys = _detect_missing_source_keys(domain, sources_yaml=demo_sources)
        next_steps = [
            "configure_llm(api_key='...', provider='...', model='...')",
            "configure_llm(llm_fallback=[{'model': 'mimo-v2.5', 'base_url': 'https://opencode.ai/zen/go/v1'}], llm_tasks={'extraction': {'model': 'deepseek-v4-flash'}}); verify with test_llm_connection()",
            f"collect_sources(domain='{domain}')",
            f"process_collection(domain='{domain}')",
        ]
        for mk in missing_keys:
            if mk["env_vars"]:
                envs = ", ".join(mk["env_vars"])
                next_steps.append(
                    f"Set {envs} for source '{mk['name']}' (type: {mk['type']}) before collecting from it"
                )
            else:
                next_steps.append(
                    f"Configure an API key for source '{mk['name']}' (type: {mk['type']}) before collecting from it"
                )
        if missing_keys:
            next_steps.append(
                f"See {_REQUIRED_KEYS_DOCS_REF} for the full catalog of source API keys and environment variables"
            )
        return {
            "status": "success",
            "domain": domain,
            "project_name": project_name,
            "autoinfo_dir": str(autoinfo_dir),
            "llm_provider": llm_provider or "(default)",
            "llm_model": llm_model or "(default)",
            "llm_base_url": llm_base_url or "(default)",
            "message": f"AutoInfo initialized for '{domain}'",
            "next_steps": next_steps,
            "docs": "See docs/dev/director-user-guide.md for the full human-agent interaction workflow.",
        }
    except Exception as exc:
        logger.exception("Init project failed for domain '%s'", domain)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
            "success": False,
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": str(exc),
                "actionable": True,
            },
        }


def _validate_llm_pool_params(
    llm_fallback: list[dict[str, Any]] | None,
    llm_tasks: dict[str, Any] | None,
) -> str | None:
    """Validate ``llm_fallback`` / ``llm_tasks`` before any disk write.

    Returns a human-readable error message when invalid, ``None`` when
    valid.  Runs BEFORE the YAML write so a failed validation leaves the
    config file untouched (mtime unchanged).
    """
    if llm_fallback is not None:
        if not isinstance(llm_fallback, list):
            return "llm_fallback must be a list of fallback entries"
        for i, entry in enumerate(llm_fallback):
            if not isinstance(entry, dict):
                return (
                    f"llm_fallback[{i}] must be an object with at least "
                    "a 'model' field"
                )
            model = entry.get("model")
            if not isinstance(model, str) or not model.strip():
                return (
                    f"llm_fallback[{i}] is missing the required 'model' field"
                )
    if llm_tasks is not None:
        if not isinstance(llm_tasks, dict):
            return "llm_tasks must be an object mapping task names to configs"
        allowed = {"model", "provider", "max_tokens"}
        for task_name, task_cfg in llm_tasks.items():
            if not isinstance(task_cfg, dict):
                return (
                    f"llm_tasks[{task_name}] must be an object with "
                    "model/provider/max_tokens fields"
                )
            unknown = set(task_cfg) - allowed
            if unknown:
                return (
                    f"llm_tasks[{task_name}] has unknown fields: "
                    f"{', '.join(sorted(unknown))}"
                )
            for field, value in task_cfg.items():
                if field in ("model", "provider") and not isinstance(value, str):
                    return f"llm_tasks[{task_name}].{field} must be a string"
                if field == "max_tokens" and not isinstance(value, int):
                    return f"llm_tasks[{task_name}].max_tokens must be an integer"
    return None


def _merge_fallback_entries(
    existing: list[dict[str, Any]],
    new_entries: list[dict[str, Any]],
    primary_provider: str,
    primary_model: str,
) -> list[dict[str, Any]]:
    """Merge new fallback entries into the existing list.

    Entries are keyed on the FULL ``(provider or primary_provider, model)``
    identity (after inheritance) — same key updates fields in place,
    different key appends.  Empty-model entries are completed with the
    inherited primary model BEFORE writing so ``call_with_fallback``
    (llm.py:714-727) can never confuse a backup entry with the primary.
    """
    result = list(existing)
    for entry in new_entries:
        provider = entry.get("provider") or primary_provider
        model = entry.get("model") or primary_model
        key = (provider, model)
        replaced = False
        for i, ex in enumerate(result):
            ex_provider = ex.get("provider") or primary_provider
            ex_model = ex.get("model") or primary_model
            if (ex_provider, ex_model) == key:
                merged = dict(ex)
                merged.update(entry)
                if not merged.get("model"):
                    merged["model"] = primary_model
                result[i] = merged
                replaced = True
                break
        if not replaced:
            completed = dict(entry)
            if not completed.get("model"):
                completed["model"] = primary_model
            result.append(completed)
    return result


def _handle_configure_llm(
    provider: str = "",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    llm_fallback: list[dict[str, Any]] | None = None,
    llm_tasks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update LLM configuration in .autoinfo/config.yaml.

    Parameters
    ----------
    provider:
        LLM provider name (e.g. \"openai\", \"openrouter\").
    model:
        LLM model name (e.g. \"gpt-4\", \"deepseek/deepseek-chat\").
    api_key:
        API key reference — stored as ``${AUTOINFO_LLM_API_KEY}``
        (env var reference), never the raw key.
        The caller should set the ``AUTOINFO_LLM_API_KEY`` env var.
    base_url:
        LLM base URL (e.g. \"http://localhost:11434/v1\").
    llm_fallback:
        Fallback chain entries (list of dicts, each with a required
        ``model``).  ``None`` leaves the existing fallback untouched;
        ``[]`` clears it; entries merge by ``(provider, model)`` identity.
    llm_tasks:
        Per-task LLM overrides keyed by task name (``model``/``provider``/
        ``max_tokens``).  ``None`` leaves existing tasks untouched;
        ``{}`` clears them.  Judgment tasks (g4_factual/g5_translation/
        llm_judge) are writable but still resolve to the release-pinned
        JUDGMENT_MODEL at runtime.
    """
    config_path = _config_path()

    # No-op when nothing is supplied
    if (
        not any([provider, model, api_key, base_url])
        and llm_fallback is None
        and llm_tasks is None
    ):
        return {
            "status": "noop",
            "message": (
                "No parameters supplied. Nothing to configure."
            ),
        }

    # Check config exists
    if not config_path.exists():
        return error_response(
            ErrorCode.CONFIG_NOT_FOUND,
            (
                "Configuration not found. "
                "Run init_project first to create .autoinfo/config.yaml. "
                "See docs/dev/required-api-keys.md for API key setup."
            ),
            actionable=True,
        )

    try:
        import yaml

        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        if cfg is None:
            cfg = {}

        llm = cfg.setdefault("llm", {})

        # Validate BEFORE writing so a failed validation leaves the file
        # untouched (mtime unchanged).
        validation_error = _validate_llm_pool_params(llm_fallback, llm_tasks)
        if validation_error:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                validation_error,
                actionable=True,
            )

        # Incremental updates — only write fields explicitly provided
        if provider:
            llm["provider"] = provider
        if model:
            llm["model"] = model
        if base_url:
            llm["base_url"] = base_url
        if api_key:
            # Store env var reference, NEVER the raw key
            llm["api_key"] = "${AUTOINFO_LLM_API_KEY}"

        # Fallback merge — keyed on (provider or primary, model) identity.
        # None = don't touch; [] = clear; list = merge with dedup.
        if llm_fallback is not None:
            if not llm_fallback:
                llm["fallback"] = []
            else:
                primary_provider = llm.get("provider", "")
                primary_model = llm.get("model", "")
                existing_fallback = llm.get("fallback", []) or []
                llm["fallback"] = _merge_fallback_entries(
                    existing_fallback,
                    llm_fallback,
                    primary_provider,
                    primary_model,
                )

        # Tasks merge — by task name.  None = don't touch; {} = clear.
        if llm_tasks is not None:
            if not llm_tasks:
                llm["tasks"] = {}
            else:
                existing_tasks = llm.get("tasks", {}) or {}
                merged_tasks = dict(existing_tasks)
                for task_name, task_cfg in llm_tasks.items():
                    merged_tasks[str(task_name)] = task_cfg
                llm["tasks"] = merged_tasks

        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        # Write-then-verify: round-trip through load_config so a malformed
        # write surfaces as an error instead of a silently-broken config.
        try:
            from autoinfo.config import load_config

            loaded = load_config(config_path)
            if llm_fallback is not None and len(loaded.llm.fallback) != len(
                llm["fallback"]
            ):
                raise RuntimeError("fallback count mismatch after round-trip")
            if llm_tasks is not None and set(loaded.llm.tasks) != set(
                llm["tasks"]
            ):
                raise RuntimeError("task names mismatch after round-trip")
        except Exception as exc:
            logger.exception("configure_llm round-trip verification failed")
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                f"Config written but failed round-trip verification: {exc}",
                actionable=True,
            )

        updated = {
            "provider": provider or "(unchanged)",
            "model": model or "(unchanged)",
            "base_url": base_url or "(unchanged)",
            "api_key": (
                "${AUTOINFO_LLM_API_KEY} (env var reference written)"
                if api_key
                else "(unchanged)"
            ),
        }
        if llm_fallback is not None:
            updated["fallback"] = llm["fallback"]
        if llm_tasks is not None:
            updated["tasks"] = llm["tasks"]

        message = (
            "LLM configured. "
            "Also set AUTOINFO_LLM_API_KEY env var for the API key. "
            "See docs/dev/required-api-keys.md for the full list of "
            "API keys and environment variables."
        )
        if llm_tasks:
            from autoinfo.config import JUDGMENT_TASKS

            judgment_written = sorted(set(llm_tasks) & set(JUDGMENT_TASKS))
            if judgment_written:
                message += (
                    f" Judgment task(s) {', '.join(judgment_written)} "
                    "are written to llm.tasks but 运行期仍强制 JUDGMENT_MODEL "
                    "(release-pinned; llm.tasks cannot override judgment models)."
                )

        return success_response({
            "status": "success",
            "message": message,
            "updated": updated,
            "config_path": str(config_path),
        })

    except Exception as exc:
        logger.exception("configure_llm failed")
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            str(exc),
            actionable=True,
        )


def _handle_list_projects(status: str = "") -> dict[str, Any]:
    """List all configured projects with domain/source summaries."""
    try:
        config = _load_config()
    except Exception as exc:
        return {"projects": [], "count": 0, "error_code": ErrorCode.INTERNAL_ERROR.value, "message": str(exc), "actionable": True}

    from autoinfo.config import get_config_path

    cfg_path = get_config_path()
    projects = [
        {
            "name": config.project.name if hasattr(config, "project") else "default",
            "config_path": str(cfg_path) if cfg_path else "",
            "domain_count": len([d for d in config.domains if d.active]),
            "total_sources": sum(
                len(d.sources) for d in config.domains if d.active
            ),
            "total_topics": sum(
                len(d.topics) for d in config.domains if d.active
            ),
            "created_at": (
                config.project.created_at
                if hasattr(config, "project") and hasattr(config.project, "created_at")
                else ""
            ),
            "llm_provider": config.llm.provider if hasattr(config, "llm") else "",
            "llm_model": config.llm.model if hasattr(config, "llm") else "",
            "status": "active",
        }
    ]

    if status:
        projects = [p for p in projects if p.get("status") == status]

    return {"projects": projects, "count": len(projects)}


def _handle_get_project_assets(type: str = "") -> dict[str, Any]:
    """Return project assets info — directories, db, exports."""
    assets: dict[str, Any] = {
        "collections_dir": {"exists": False, "path": ""},
        "knowledge_dir": {"exists": False, "path": ""},
        "database": {"exists": False, "path": ""},
        "exports_dir": {"exists": False, "path": ""},
        "config_dir": {"exists": False, "path": ""},
    }

    cwd = Path.cwd()
    collections_dir = cwd / "collections"
    knowledge_dir = cwd / "knowledge"
    db_path = cwd / "autoinfo.db"
    exports_dir = cwd / "exports"
    config_dir = cwd / ".autoinfo"

    assets["collections_dir"] = {
        "exists": collections_dir.is_dir(),
        "path": str(collections_dir),
        "item_count": len(list(collections_dir.rglob("*.json"))) if collections_dir.is_dir() else 0,
    }
    assets["knowledge_dir"] = {
        "exists": knowledge_dir.is_dir(),
        "path": str(knowledge_dir),
        "entry_count": len(list(knowledge_dir.rglob("*.md"))) if knowledge_dir.is_dir() else 0,
    }
    assets["database"] = {
        "exists": db_path.is_file(),
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size if db_path.is_file() else 0,
    }
    assets["exports_dir"] = {
        "exists": exports_dir.is_dir(),
        "path": str(exports_dir),
        "file_count": len(list(exports_dir.iterdir())) if exports_dir.is_dir() else 0,
    }
    assets["config_dir"] = {
        "exists": config_dir.is_dir(),
        "path": str(config_dir),
    }

    if type:
        asset_types_map = {
            "collections": "collections_dir",
            "knowledge": "knowledge_dir",
            "database": "database",
            "exports": "exports_dir",
            "config": "config_dir",
        }
        key = asset_types_map.get(type)
        if key:
            return {key: assets[key]}

    return assets


def _handle_archive_project(reason: str = "", confirm: bool = False) -> dict[str, Any]:
    """Archive the current project (refuses unless published to 03-Wiki)."""
    if not confirm:
        return error_response(
            code=ErrorCode.CONFIRMATION_REQUIRED,
            message=(
                "This operation is destructive and requires confirmation. "
                "Pass confirm=True to proceed."
            ),
            actionable=True,
        )
    try:
        from autoinfo.kb import KBStore

        store = KBStore()
        wiki_count = store.index.count_entries()
        wiki_entries = store.index.list_entries_by_tier(
            domain="", tier="03-Wiki", limit=1, offset=0
        )
        has_published = len(wiki_entries) > 0
    except Exception:
        has_published = False

    if not has_published:
        return error_response(
            code=ErrorCode.NOT_PUBLISHED,
            message=(
                "Cannot archive project: no entries have been promoted to "
                "03-Wiki. Publish at least one Draft entry before archiving. "
                "Use create_kb_draft raw_ids=[...] title=... to create a Draft, "
                "then the human director can promote it to 03-Wiki."
            ),
            actionable=True,
        )

    return {
        "status": "refused_by_design",
        "message": (
            "Archive is a human-only operation. The agent can prepare a "
            "summary of the project but cannot perform the archive. "
            f"Reason provided: {reason or 'not specified'}"
        ),
        "actionable": False,
    }


def _handle_batch_run(
    domain: str,
    topic: str = "",
    limit: int = 20,
    model: str = "",
) -> dict[str, Any]:
    """Run collect + process in sequence for a domain. Returns per-phase results."""
    from datetime import datetime, timezone

    from autoinfo.collect import run_collection
    from autoinfo.process import ProcessResult, run_processing

    start_time = datetime.now(timezone.utc)
    phases: list[dict[str, Any]] = []

    collect_args: dict[str, Any] = {"domain": domain, "limit": limit}
    if topic:
        collect_args["topic"] = topic

    phase_start = datetime.now(timezone.utc)
    try:
        collected = run_collection(**collect_args)
        phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
        phases.append({
            "phase": "collection",
            "status": "completed",
            "result": collected,
            "duration_s": round(phase_duration, 2),
        })
    except Exception as exc:
        phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
        phases.append({
            "phase": "collection",
            "status": "failed",
            "error": str(exc),
            "duration_s": round(phase_duration, 2),
        })

    if phases[-1]["status"] == "completed":
        process_args: dict[str, Any] = {"domain": domain}
        if model:
            process_args["model"] = model

        phase_start = datetime.now(timezone.utc)
        try:
            processed: ProcessResult = run_processing(**process_args)
            processed_dict = asdict(processed)
            phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
            phases.append({
                "phase": "processing",
                "status": "completed",
                "result": processed_dict,
                "duration_s": round(phase_duration, 2),
            })
        except Exception as exc:
            phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
            phases.append({
                "phase": "processing",
                "status": "failed",
                "error": str(exc),
                "duration_s": round(phase_duration, 2),
            })
    else:
        phases.append({
            "phase": "processing",
            "status": "skipped",
            "reason": "collection failed",
        })

    total_duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    overall_success = all(p["status"] == "completed" for p in phases)

    return {
        "domain": domain,
        "topic": topic or "*",
        "phases": phases,
        "overall_success": overall_success,
        "total_duration_s": round(total_duration, 2),
    }


def _handle_get_feeds(
    domain: str,
    topic: str | None = None,
    source_type: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
    format: str = "json",
) -> dict[str, Any]:
    """Return a paginated feed of KB entries for *domain*.

    Parameters
    ----------
    domain:
        Domain to query (required).
    topic:
        Optional filter by topic tag.
    source_type:
        Optional filter by source type (e.g. rss, api).
    since:
        Optional ISO date filter (collected_at >=).
    limit:
        Max items to return (default 50, max 200).
    offset:
        Number of items to skip for pagination (default 0).
    format:
        Output format: ``"json"`` (default) or ``"rss"``.
        ``"json"`` returns a paginated JSON envelope with ``{items, pagination}``.
        ``"rss"`` returns an RSS 2.0 XML feed.

    Returns
    -------
    dict
        For ``format="json"``: ``{domain, format, items, pagination}``.
        For ``format="rss"``: ``{domain, format, content}`` with the RSS XML string.
    """
    from autoinfo.kb import KBStore

    limit = max(1, min(limit, 200))
    store = KBStore()

    # Fetch all entries for the domain with since filter at the DB level
    all_raw = store.list_all_entries(
        domain=domain,
        date_from=since,
        limit=10000,
        offset=0,
    )

    # Apply topic filter (tags are a JSON string in the DB)
    if topic:
        topic_lower = topic.strip().lower()
        filtered: list[dict[str, Any]] = []
        for entry in all_raw:
            tags = _parse_tags(entry)
            if any(t.lower() == topic_lower for t in tags):
                filtered.append(entry)
        all_raw = filtered

    # Apply source_type filter
    if source_type:
        st = source_type.strip().lower()
        all_raw = [e for e in all_raw if e.get("source_type", "").lower() == st]

    # Sort by collected_at DESC (newest first)
    all_raw.sort(key=lambda e: e.get("collected_at", "") or "", reverse=True)

    total = len(all_raw)

    # Slice for pagination
    page = all_raw[offset: offset + limit]

    # Determine next offset
    next_offset: int | None = offset + limit if offset + limit < total else None

    items = []
    for entry in page:
        items.append({
            "id": entry.get("entry_id", ""),
            "title": entry.get("title", ""),
            "url": entry.get("source_url", ""),
            "source_type": entry.get("source_type", ""),
            "source_platform": entry.get("source_platform", ""),
            "collected_at": entry.get("collected_at", ""),
            "summary": entry.get("summary", ""),
            "relevance_score": entry.get("relevance_score", 0.0),
        })

    if format == "rss":
        import xml.etree.ElementTree as ET  # noqa: PLC0415 — deferred import

        rss = ET.Element("rss", {"version": "2.0"})
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = f"AutoInfo Feed — {domain}"
        ET.SubElement(channel, "description").text = f"Knowledge base feed for domain: {domain}"
        ET.SubElement(channel, "link").text = "https://autoinfo.local"
        ET.SubElement(channel, "lastBuildDate").text = (
            items[0]["collected_at"] if items else ""
        )

        for item in items:
            xml_item = ET.SubElement(channel, "item")
            ET.SubElement(xml_item, "guid", {"isPermaLink": "false"}).text = item["id"]
            ET.SubElement(xml_item, "title").text = item["title"] or "(untitled)"
            ET.SubElement(xml_item, "link").text = item["url"] or ""
            ET.SubElement(xml_item, "description").text = item["summary"] or ""
            if item["collected_at"]:
                ET.SubElement(xml_item, "pubDate").text = item["collected_at"]
            ET.SubElement(xml_item, "source", {"url": item["url"] or ""}).text = item["source_type"] or ""

        ET.indent(rss, space="  ")
        rss_content = ET.tostring(rss, encoding="unicode", xml_declaration=True)
        return {
            "domain": domain,
            "format": "rss",
            "content": rss_content,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "next": next_offset,
            },
        }

    return {
        "domain": domain,
        "format": "json",
        "items": items,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "next": next_offset,
        },
    }


def _parse_tags(raw: dict[str, Any]) -> list[str]:
    """Deserialise the ``tags`` column from a raw entry dict."""
    import json as _json

    tags_raw = raw.get("tags") or []
    if isinstance(tags_raw, str):
        try:
            return list(_json.loads(tags_raw))
        except (_json.JSONDecodeError, TypeError):
            return [tags_raw] if tags_raw else []
    return list(tags_raw) if tags_raw else []


def _handle_list_active_collections(domain: str = "") -> dict[str, Any]:
    """List active / in-progress collection runs."""
    from autoinfo.collect import list_active_collections as _list_active

    try:
        active = _list_active()
    except Exception as exc:
        return {"active_collections": [], "count": 0, "error_code": ErrorCode.INTERNAL_ERROR.value, "message": str(exc), "actionable": True}

    if domain:
        active = [c for c in active if c.get("domain") == domain]

    return {
        "active_collections": active,
        "count": len(active),
    }


# ---------------------------------------------------------------------------
# Gate config handlers
# ---------------------------------------------------------------------------


def _handle_get_gate_config(domain: str, gate: str) -> dict[str, Any]:
    """Return gate configuration for a domain.

    Checks both quality gates (G0-G5 etc.) and delivery gates (D1-D3 etc.),
    falling back to global defaults when the gate is not set at the domain level.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(config, domain)
    if domain_cfg is None:
        return error_response(
            code=ErrorCode.DOMAIN_NOT_FOUND,
            message=f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            actionable=True,
        )

    from dataclasses import asdict as _asdict

    # Normalise the queried gate name to its canonical long form — config
    # keys are stored as e.g. "G3-RelevanceScoring" (short "G3" accepted).
    from autoinfo.config import _GATE_CONFIG_KEY_MAP

    gate_key = _GATE_CONFIG_KEY_MAP.get(gate, gate)

    # Check quality gates first, then delivery gates, then global defaults
    gate_config: dict[str, Any] | None = None
    gate_type: str = ""

    if gate_key in domain_cfg.quality_gates:
        gate_config = _asdict(domain_cfg.quality_gates[gate_key])
        gate_type = "quality"
    elif gate_key in domain_cfg.delivery_gates:
        gate_config = _asdict(domain_cfg.delivery_gates[gate_key])
        gate_type = "delivery"
    elif gate_key in config.quality_gates:
        gate_config = _asdict(config.quality_gates[gate_key])
        gate_type = "quality"
    elif gate_key in config.delivery_gates:
        gate_config = _asdict(config.delivery_gates[gate_key])
        gate_type = "delivery"

    if gate_config is None:
        return error_response(
            code="GateNotFound",
            message=f"Gate '{gate}' is not configured for domain '{domain}'",
            actionable=True,
        )

    # Remove internal fields from serialization
    gate_config.pop("name", None)

    return {
        "domain": domain,
        "gate": gate,
        "gate_type": gate_type,
        "config": gate_config,
    }


def _handle_set_gate_config(
    domain: str,
    gate: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Update gate configuration for a domain.

    *config* should contain gate-specific fields (e.g. ``action``, ``threshold``
    for quality gates; ``enabled``, ``action_on_failure`` for delivery gates).
    """
    try:
        cfg = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(cfg, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    from autoinfo.config import DeliveryGateConfig, QualityGateConfig

    # Determine if this is a quality or delivery gate. CurationGate is
    # always a quality gate: its dict carries ``enabled`` (the G4 switch),
    # which the generic heuristic below would otherwise misread as delivery.
    is_delivery = (
        gate in domain_cfg.delivery_gates
        or ("action_on_failure" in config)
        or (gate != "CurationGate" and "enabled" in config and "category" not in config)
    )
    is_quality = (gate in domain_cfg.quality_gates) or not is_delivery

    new_gc: QualityGateConfig | None = None
    new_dc: DeliveryGateConfig | None = None

    if is_quality:
        new_gc = QualityGateConfig(
            name=gate,
            category=str(config.get("category", "soft")),
            retries=int(config.get("retries", 0)),
            retry_models=list(config.get("retry_models", [])),
            action=str(config.get("action", "flag")),
            threshold=config.get("threshold", None),
            enabled=bool(config.get("enabled", True)),
        )
        domain_cfg.quality_gates[gate] = new_gc
    else:
        new_dc = DeliveryGateConfig(
            name=gate,
            enabled=bool(config.get("enabled", True)),
            action_on_failure=str(config.get("action_on_failure", "block")),
        )
        domain_cfg.delivery_gates[gate] = new_dc

    _save_config(cfg)

    # Both branches of is_quality/is_delivery set one of new_gc/new_dc
    if is_quality and new_gc is not None:
        from dataclasses import asdict as _asdict
        config_dict = _asdict(new_gc)
    elif new_dc is not None:
        from dataclasses import asdict as _asdict
        config_dict = _asdict(new_dc)
    else:
        config_dict = {}

    return {
        "domain": domain,
        "gate": gate,
        "updated": True,
        "config": config_dict,
    }


# ---------------------------------------------------------------------------
# Budget threshold handlers (F45)
# ---------------------------------------------------------------------------


def _handle_get_budget_thresholds() -> dict[str, Any]:
    """Return current budget thresholds with spend status.

    Reads ``cost_alerts.budget_thresholds`` from the project config and
    queries ``CostMeter`` for total spend, then returns each threshold
    with its comparison status.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    thresholds = config.cost_alerts.budget_thresholds
    if not thresholds:
        thresholds = [50.0, 75.0, 90.0, 100.0]

    from autoinfo.cost import CostMeter
    meter = CostMeter()
    report = meter.get_report()
    current_spend = report["total_cost"]

    status: list[dict[str, Any]] = []
    for t in sorted(thresholds):
        pct = round(current_spend / t * 100, 2) if t > 0 else 0.0
        breached = current_spend >= t
        status.append({
            "threshold": t,
            "current_spend": round(current_spend, 8),
            "pct_used": pct,
            "breached": breached,
            "severity": "critical" if t >= 100 and breached else "warning" if breached else "ok",
        })

    return {
        "budget_thresholds": thresholds,
        "current_spend": round(current_spend, 8),
        "auto_remediation_enabled": config.cost_alerts.auto_remediation_enabled,
        "alert_webhook": config.cost_alerts.alert_webhook,
        "threshold_status": status,
    }


def _handle_set_budget_thresholds(
    thresholds: list[float],
    auto_remediation_enabled: bool = False,
    alert_webhook: str = "",
) -> dict[str, Any]:
    """Update budget thresholds in the project config (in-memory + persist).

    Parameters
    ----------
    thresholds:
        New percentage thresholds (e.g. ``[30.0, 60.0, 90.0, 100.0]``).
    auto_remediation_enabled:
        Whether auto-remediation is active (V2 — not yet implemented).
    alert_webhook:
        Optional webhook URL for budget alert notifications.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    if not thresholds:
        return {
            "error_code": "InvalidArguments",
            "message": "thresholds must be a non-empty list of floats",
            "actionable": True,
        }

    config.cost_alerts.budget_thresholds = [float(t) for t in thresholds]
    if auto_remediation_enabled:
        config.cost_alerts.auto_remediation_enabled = True
    if alert_webhook:
        config.cost_alerts.alert_webhook = alert_webhook

    _save_config(config)

    return {
        "budget_thresholds": config.cost_alerts.budget_thresholds,
        "auto_remediation_enabled": config.cost_alerts.auto_remediation_enabled,
        "alert_webhook": config.cost_alerts.alert_webhook,
        "updated": True,
    }


# ---------------------------------------------------------------------------
# Product handlers
# ---------------------------------------------------------------------------


def _handle_get_product(domain: str, product_type: str) -> dict[str, Any]:
    """Return product configuration for a domain and product type.

    *product_type* is ``"RAW"`` or ``"PROCESSED"``.  Products are derived
    from the domain's configuration (sources, quality gates, delivery
    channels, etc.).
    """
    try:
        cfg = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(cfg, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    product_type_upper = product_type.upper()
    if product_type_upper not in ("RAW", "PROCESSED"):
        return {
            "error_code": "ValidationError",
            "message": f"Invalid product_type '{product_type}'. Must be 'RAW' or 'PROCESSED'.",
            "actionable": True,
        }

    if product_type_upper == "RAW":
        product = {
            "id": f"{domain}-raw",
            "domain": domain,
            "type": "raw",
            "name": f"{domain} RAW Feed",
            "config": {
                "sources": [
                    {"name": s.name, "type": s.type, "url": s.url}
                    for s in domain_cfg.sources
                ],
                "extract_fields": list(getattr(domain_cfg, "extract_fields", [])),
            },
            "templates": [],
            "delivery_channels": ["api"],
            "quality_gates": list(domain_cfg.quality_gates.keys()),
            "variants": ["api_feed", "webhook", "bulk_export"],
        }
    else:
        product = {
            "id": f"{domain}-processed",
            "domain": domain,
            "type": "processed",
            "name": f"{domain} PROCESSED Output",
            "config": {
                "delivery_gates": {
                    dg: _gate_to_dict(gc)
                    for dg, gc in domain_cfg.delivery_gates.items()
                },
                "webhook_urls": list(getattr(domain_cfg, "webhook_urls", [])),
                "search_mode": getattr(domain_cfg, "search_mode", "keyword"),
            },
            "templates": ["digest", "report", "tutorial", "presentation"],
            "delivery_channels": ["webhook", "smtp", "api", "export"],
            "quality_gates": list(domain_cfg.quality_gates.keys()),
        }

    return {"product": product}


def _handle_list_products(domain: str) -> dict[str, Any]:
    """List all configured products for a domain.

    Returns both RAW and PROCESSED product types derived from the
    domain's configuration.
    """
    try:
        cfg = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    domain_cfg = _find_domain(cfg, domain)
    if domain_cfg is None:
        return {
            "error_code": ErrorCode.DOMAIN_NOT_FOUND.value,
            "message": f"Domain '{domain}' is not configured. Use add_domain(name='{domain}') to create it.",
            "actionable": True,
        }

    raw_product = {
        "id": f"{domain}-raw",
        "domain": domain,
        "type": "raw",
        "name": f"{domain} RAW Feed",
        "source_count": len(domain_cfg.sources),
        "extract_fields": list(getattr(domain_cfg, "extract_fields", [])),
        "quality_gate_count": len(domain_cfg.quality_gates),
        "variants": ["api_feed", "webhook", "bulk_export"],
    }

    processed_product = {
        "id": f"{domain}-processed",
        "domain": domain,
        "type": "processed",
        "name": f"{domain} PROCESSED Output",
        "delivery_channel_count": len(
            list(getattr(domain_cfg, "webhook_urls", [])) + ["smtp", "api", "export"]
        ),
        "delivery_gate_count": len(domain_cfg.delivery_gates),
        "templates": ["digest", "report", "tutorial", "presentation"],
    }

    return {
        "domain": domain,
        "products": [raw_product, processed_product],
        "count": 2,
    }


def _handle_send_to_enduser(
    end_user_id: str,
    product_type: str,
    product_id: str,
    channel: str | None = None,
) -> dict[str, Any]:
    """Dispatch a product to an end user through a delivery channel.

    Looks up the end-user profile, resolves the delivery channel
    (from the *channel* parameter or the user's stored preferences),
    builds a :class:`Product` model, and dispatches through the
    existing :func:`deliver_with_retry` framework.

    Parameters
    ----------
    end_user_id:
        User ID of the recipient (must exist in the user store).
    product_type:
        ``"raw"`` or ``"processed"``.
    product_id:
        Product identifier (e.g. ``"medical-research-processed"``).
    channel:
        Delivery channel name (``"smtp"``, ``"webhook"``, …).
        Falls back to the user's ``delivery_preferences["channel"]``
        when omitted, then to ``"smtp"``.

    Returns
    -------
    dict
        ``{delivery_id, status, channel, recipient_count, error}``.
    """
    import uuid as _uuid

    from autoinfo.delivery import deliver_with_retry, get_channel
    from autoinfo.models import Product, ProductType
    from autoinfo.user_store import get_profile as _get_profile

    profile = _get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": f"End user '{end_user_id}' not found",
            "actionable": True,
        }

    # --- Content-preference tier guard (B-001) -------------------------------
    # Block deliveries whose product kind conflicts with the user's stored
    # content_preference instead of silently bypassing the preference gate.
    from autoinfo.user_store import (  # noqa: PLC0415
        resolve_content_preference as _resolve_cp,
    )

    effective_preference = _resolve_cp(profile.preferences)
    product_kind = (
        product_type.lower()
        if product_type.lower() in ("raw", "processed")
        else "processed"
    )
    preference_conflict: str | None = None
    if effective_preference == "raw_only" and product_kind != "raw":
        preference_conflict = (
            f"User '{end_user_id}' has content_preference='raw_only' "
            f"(wants only 01-Raw content), but product '{product_id}' "
            f"is a '{product_kind}' product. "
            "Use update_preferences() to switch content_preference to "
            "'both' or 'processed_only', or deliver a raw product instead."
        )
    elif effective_preference == "processed_only" and product_kind != "processed":
        preference_conflict = (
            f"User '{end_user_id}' has content_preference='processed_only' "
            f"(wants only 02-Draft/03-Wiki content), but product "
            f"'{product_id}' is a '{product_kind}' product. "
            "Use update_preferences() to switch content_preference to "
            "'both' or 'raw_only', or deliver a processed product instead."
        )
    if preference_conflict is not None:
        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=preference_conflict,
            actionable=True,
        )

    channel_name: str = (
        channel
        or profile.delivery_preferences.get("channel")
        or "smtp"
    )

    domain: str = product_id
    for suffix in ("-raw", "-processed"):
        if product_id.endswith(suffix):
            domain = product_id[: -len(suffix)]
            break

    product = Product(
        id=product_id,
        domain=domain,
        type=ProductType(product_type.lower()) if product_type.lower() in ("raw", "processed") else ProductType.PROCESSED,
        name=f"Product {product_id}",
        delivery_channels=[channel_name],
    )

    delivery_id = str(_uuid.uuid4())
    payload: dict[str, Any] = {
        "delivery_id": delivery_id,
        "product_id": product_id,
        "product_type": product_type,
        "end_user_id": end_user_id,
        "domain": domain,
    }

    recipients: list[str] = [profile.email] if profile.email else []


    try:
        channel_instance = get_channel(channel_name)
        result = deliver_with_retry(
            channel=channel_instance,
            product=product,
            payload=payload,
            recipients=recipients,
            subscription_id=delivery_id,
        )
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("send_to_enduser dispatch failed")
        return _error_from_exc(exc, "send_to_enduser dispatch failed")

    return {
        "delivery_id": delivery_id,
        "status": result.status,
        "channel": channel_name,
        "recipient_count": result.recipient_count,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Alert rule handlers
# ---------------------------------------------------------------------------


def _handle_get_alert_rules(domain: str) -> dict[str, Any]:
    """List alert rules for a domain."""
    from autoinfo.alerts import list_alert_rules

    try:
        rules = list_alert_rules(domain=domain)
    except Exception as exc:
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": f"Failed to list alert rules: {exc}",
            "actionable": True,
        }

    from dataclasses import asdict as _asdict

    return {
        "domain": domain,
        "alert_rules": [_asdict(r) for r in rules],
        "count": len(rules),
    }


def _handle_add_alert_rule(
    domain: str,
    topic_keywords: list[str] | None = None,
    relevance_threshold: float = 0.0,
    channel: Literal["email", "webhook"] = "email",
    enabled: bool = True,
    kind: str = "content",
) -> dict[str, Any]:
    """Add a new alert rule for a domain."""
    from autoinfo.alerts import add_alert_rule

    try:
        rule = add_alert_rule(
            domain=domain,
            topic_keywords=topic_keywords,
            relevance_threshold=relevance_threshold,
            channel=channel,
            enabled=enabled,
            kind=kind,
        )
    except Exception as exc:
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": f"Failed to add alert rule: {exc}",
            "actionable": True,
        }

    from dataclasses import asdict as _asdict

    return {
        "alert_rule": _asdict(rule),
        "created": True,
    }


def _handle_remove_alert_rule(id: str) -> dict[str, Any]:
    """Remove an alert rule by ID."""
    from autoinfo.alerts import remove_alert_rule

    try:
        removed = remove_alert_rule(id)
    except Exception as exc:
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to remove alert rule: {exc}",
            actionable=True,
        )

    if not removed:
        return error_response(
            code="AlertRuleNotFound",
            message=f"Alert rule '{id}' not found",
            actionable=True,
        )

    return {
        "removed": True,
        "alert_rule_id": id,
    }


def _gate_to_dict(gate_obj: Any) -> dict[str, Any]:
    """Serialize a QualityGateConfig or DeliveryGateConfig to a plain dict."""
    from dataclasses import asdict as _asdict

    d = _asdict(gate_obj)
    d.pop("name", None)
    return d


def _handle_get_config(section: str = "") -> dict[str, Any]:
    """Return the current configuration as a structured dict.

    Supports optional *section* filter: 'project', 'llm', 'domains'.
    Returns the full config when *section* is empty.
    """
    try:
        config = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    config_dict: dict[str, Any] = {}

    if section in ("", "project"):
        if hasattr(config, "project"):
            prj = config.project
            config_dict["project"] = {
                "name": prj.name if hasattr(prj, "name") else "",
                "created_at": prj.created_at if hasattr(prj, "created_at") else "",
            }

    if section in ("", "llm"):
        if hasattr(config, "llm"):
            llm = config.llm
            config_dict["llm"] = {
                "provider": llm.provider if hasattr(llm, "provider") else "",
                "model": llm.model if hasattr(llm, "model") else "",
                "api_key_configured": bool(
                    (llm.api_key if hasattr(llm, "api_key") else "")
                    or os.environ.get("AUTOINFO_LLM_API_KEY")
                ),
            }

    if section in ("", "domains"):
        domains_list = []
        if hasattr(config, "domains"):
            for d in config.domains:
                domains_list.append({
                    "name": d.name,
                    "active": d.active if hasattr(d, "active") else False,
                    "source_count": len(d.sources) if hasattr(d, "sources") else 0,
                    "topic_count": len(d.topics) if hasattr(d, "topics") else 0,
                })
        config_dict["domains"] = domains_list

    if section and section not in ("project", "llm", "domains"):
        return {
            "error_code": ErrorCode.INVALID_SECTION.value,
            "message": f"Unknown config section '{section}'. Valid: project, llm, domains",
            "actionable": True,
        }

    config_dict["config_path"] = str(_config_path())

    return {"config": config_dict}


def _handle_trace_item(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Trace the full pipeline history for a trace_id.

    Searches pipeline logs (``logs/pipeline-*.log``) and KB frontmatter
    for all events associated with the trace_id.
    """
    trace_id = arguments["trace_id"]

    # -- Search pipeline logs ---------------------------------------------
    pipeline_events: list[dict[str, Any]] = []
    log_dir = Path("logs")
    if log_dir.is_dir():
        for log_file in sorted(log_dir.glob("pipeline-*.log"), reverse=True):
            try:
                lines = log_file.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if entry.get("trace_id") == trace_id or (
                    isinstance(entry.get("extra"), dict)
                    and entry["extra"].get("trace_ids")
                    and trace_id in entry["extra"]["trace_ids"]
                ):
                    pipeline_events.append(entry)
            if pipeline_events:
                break

    # -- Search KB frontmatter for the entry ----------------------------
    kb_entries: list[dict[str, Any]] = []
    knowledge_dir = Path("knowledge")
    if knowledge_dir.is_dir():
        import yaml as _yaml
        for md_file in knowledge_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            try:
                fm = _yaml.safe_load(parts[1])
            except Exception:
                continue
            if isinstance(fm, dict) and fm.get("trace_id") == trace_id:
                kb_entries.append({
                    "entry_id": fm.get("entry_id", ""),
                    "title": fm.get("title", ""),
                    "domain": fm.get("domain", ""),
                    "tier": fm.get("tier", ""),
                    "file_path": str(md_file),
                    "collected_at": fm.get("collected_at", ""),
                    "language": fm.get("language", ""),
                    "dedup_status": fm.get("dedup_status", ""),
                })

    # -- Timeline from pipeline events -----------------------------------
    timeline: list[dict[str, Any]] = []
    for evt in pipeline_events:
        timeline.append({
            "stage": evt.get("module", "?"),
            "timestamp": evt.get("timestamp", ""),
            "status": evt.get("level", "?"),
            "message": evt.get("message", ""),
            "item_id": evt.get("item_id", ""),
        })

    return {
        "trace_id": trace_id,
        "pipeline_events": pipeline_events,
        "timeline": timeline,
        "kb_entries": kb_entries,
        "event_count": len(pipeline_events),
        "kb_entry_count": len(kb_entries),
    }


def _handle_get_metrics(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.metrics import get_metrics as _get_metrics
    return _get_metrics()


def _handle_get_prometheus_metrics(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return raw Prometheus exposition-format metrics in a dict wrapper."""
    from autoinfo.metrics import format_prometheus
    from autoinfo.metrics import get_metrics as _get_metrics

    data = _get_metrics()
    return {"format": "prometheus", "metrics_text": format_prometheus(data)}


def _handle_soft_delete_entry(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.kb import KBStore
    store = KBStore()
    actor = arguments.get("actor") or "agent"
    purge = arguments.get("purge", False)
    try:
        if purge:
            return store.delete_entry(arguments["entry_id"], actor=actor)
        return store.soft_delete_entry(arguments["entry_id"], actor=actor)
    except DirectorOnlyError as exc:
        return error_response(
            code=ErrorCode.DIRECTOR_ONLY,
            message=str(exc),
            actionable=True,
        )


def _handle_mark_stale(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.kb import mark_stale
    return mark_stale(arguments["entry_id"])


def _handle_restore_entry(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.kb import KBStore
    store = KBStore()
    return store.restore_entry(arguments["entry_id"])


def _handle_export_user_data(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.user_store import get_profile
    profile = get_profile(arguments["user_id"])
    return {"user_id": arguments["user_id"], "profile": profile}


def _handle_delete_user_data(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from autoinfo.kb import KBStore
    store = KBStore()
    purge = arguments.get("purge", False)
    if not purge:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": "Must set purge=True for permanent deletion",
            "actionable": True,
            "success": False,
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "Must set purge=True for permanent deletion",
                "actionable": True,
            },
        }
    return store.delete_user_data(arguments["user_id"])


def _handle_query_delivery_log(name: str, arguments: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    import dataclasses

    from autoinfo.delivery_log import query_delivery_log
    subscription_id = arguments.get("subscription_id")
    limit = arguments.get("limit", 50)
    status = arguments.get("status")
    from_date = arguments.get("from_date")
    to_date = arguments.get("to_date")
    results = query_delivery_log(
        subscription_id=subscription_id,
        limit=limit,
        date_from=from_date,
        date_to=to_date,
    )
    if status:
        results = [r for r in results if r.status == status]
    return [dataclasses.asdict(r) for r in results]


def _handle_list_active_deliveries() -> dict[str, Any]:
    """List all active/in-progress deliveries (status retrying/pending/in_progress)."""
    try:
        from autoinfo.delivery_log import list_active_deliveries

        items = list_active_deliveries()
        import dataclasses

        return {
            "deliveries": [dataclasses.asdict(item) for item in items],
            "count": len(items),
        }
    except Exception as exc:
        logger.exception("list_active_deliveries failed")
        return _error_from_exc(exc, "list_active_deliveries failed")


def _handle_get_delivery_log(
    status: str | None = None,
    domain: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Query delivery log with optional filters (status, domain) and pagination."""
    try:
        from autoinfo.delivery_log import query_delivery_log

        items = query_delivery_log(
            limit=limit,
            offset=offset,
        )
        if status:
            items = [item for item in items if item.status == status]
        # domain filter is accepted for API compatibility; delivery_log
        # table does not currently store domain — no-op filtering.
        if domain:
            pass
        import dataclasses

        return {
            "deliveries": [dataclasses.asdict(item) for item in items],
            "count": len(items),
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.exception("get_delivery_log failed")
        return _error_from_exc(exc, "get_delivery_log failed")


def _handle_get_channel_health(
    channel_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return health status for all or a specific delivery channel."""
    from autoinfo.delivery import _CHANNEL_REGISTRY

    results: list[dict[str, Any]] = []
    if channel_name is not None:
        channel_cls = _CHANNEL_REGISTRY.get(channel_name)
        if channel_cls is None:
            return [{"healthy": False, "latency_ms": 0.0, "error": f"unknown channel: {channel_name}", "channel": channel_name}]
        instance = channel_cls()
        results.append(instance.health_check())
    else:
        for name, channel_cls in _CHANNEL_REGISTRY.items():
            try:
                instance = channel_cls()
                results.append(instance.health_check())
            except Exception as exc:
                results.append({"healthy": False, "latency_ms": 0.0, "error": str(exc), "channel": name})
    return results


# ---------------------------------------------------------------------------
# Portal / end-user self-service tools
# ---------------------------------------------------------------------------


def _handle_get_enduser_history(end_user_id: str, limit: int = 20) -> dict[str, Any]:
    """Return delivery history for an end-user.

    Mirrors the ``portal history`` CLI command — looks up the end-user's
    subscriptions and queries the delivery log for their delivery attempts.

    Parameters
    ----------
    end_user_id:
        End-user ID (e.g. ``alice``).
    limit:
        Max entries to return (default 20).

    Returns
    -------
    dict
        ``{end_user_id, entries, count, subscription_count}``.
    """
    from autoinfo.delivery_log import query_delivery_log as _query_log
    from autoinfo.user_store import get_profile, list_subscriptions

    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    subscriptions = list_subscriptions(user_id=end_user_id)
    sub_ids: list[str] = []
    for s in subscriptions:
        sid = getattr(s, "sub_id", None) or getattr(s, "subscription_id", None)
        if sid:
            sub_ids.append(sid)

    if not sub_ids:
        return {
            "end_user_id": end_user_id,
            "entries": [],
            "count": 0,
            "subscription_count": 0,
        }

    all_entries: list[dict[str, Any]] = []
    for sid in sub_ids:
        raw = _query_log(subscription_id=sid, limit=limit)
        for entry in raw:
            all_entries.append(asdict(entry))

    all_entries.sort(key=lambda e: e.get("last_attempt", ""), reverse=True)
    page = all_entries[:limit]

    return {
        "end_user_id": end_user_id,
        "entries": page,
        "count": len(page),
        "subscription_count": len(sub_ids),
    }


def _handle_get_enduser_products(end_user_id: str) -> dict[str, Any]:
    """Return products (subscriptions) for an end-user.

    Mirrors the ``portal`` CLI's subscription lookup — retrieves all
    subscriptions linked to the given end-user and returns their product
    details (plan, status, dates, auto-renew flag).

    Parameters
    ----------
    end_user_id:
        End-user ID (e.g. ``alice``).

    Returns
    -------
    dict
        ``{end_user_id, products, count}``.
    """
    from autoinfo.user_store import get_profile, list_subscriptions

    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    subscriptions = list_subscriptions(user_id=end_user_id)
    products: list[dict[str, Any]] = []
    for sub in subscriptions:
        products.append({
            "subscription_id": getattr(sub, "subscription_id", getattr(sub, "sub_id", "")),
            "user_id": sub.user_id,
            "plan": getattr(sub, "plan", getattr(sub, "product_id", "")),
            "status": sub.status,
            "start_date": sub.start_date,
            "end_date": sub.end_date,
            "auto_renew": sub.auto_renew,
        })

    return {
        "end_user_id": end_user_id,
        "products": products,
        "count": len(products),
    }


# ---------------------------------------------------------------------------
# Error response helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cross-collection merge (F53)
# ---------------------------------------------------------------------------


def _handle_merge_items(
    item_ids: list[str],
    strategy: str = "simple",
) -> dict[str, Any]:
    """Merge multiple KB entries into one.

    Parameters
    ----------
    item_ids:
        List of KB entry IDs to merge (min 2).
    strategy:
        ``"simple"`` (default) or ``"title_first"``.

    Returns
    -------
    dict
        Merged result from :func:`autoinfo.quality.merge_items`.
    """
    from autoinfo.quality import merge_items

    try:
        result = merge_items(item_ids=item_ids, strategy=strategy)
        return result
    except Exception as exc:
        logger.exception("merge_items failed")
        return _error_from_exc(exc, "merge_items failed")


def _handle_find_similar_items(
    query: str,
    threshold: float = 0.8,
    limit: int | None = None,
) -> dict[str, Any]:
    """Find items similar to *query* using text similarity.

    Parameters
    ----------
    query:
        Text to match against KB entries.
    threshold:
        Minimum similarity ratio (0.0–1.0). Default 0.8.
    limit:
        Maximum number of results to return. Default (None) returns
        up to 20.

    Returns
    -------
    dict
        ``{"entries": [...]}`` from :func:`autoinfo.quality.find_similar_items`.
    """
    from autoinfo.quality import find_similar_items

    try:
        result = find_similar_items(query=query, threshold=threshold)
        if limit is not None:
            result = result[:limit]
        return {"entries": result}
    except Exception as exc:
        logger.exception("find_similar_items failed")
        return _error_from_exc(exc, "find_similar_items failed")


def _handle_calculate_freshness_score(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle calculate_freshness_score — fetch entry, compute freshness."""
    entry_id = arguments["entry_id"]
    ttl_days = arguments.get("ttl_days", 90)
    from autoinfo.kb import KBStore, calculate_freshness_score

    store = KBStore()
    entry = store.get_entry(entry_id)
    if entry is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"Entry not found: {entry_id}",
            "actionable": True,
            "success": False,
            "error": {
                "code": ErrorCode.NOT_FOUND.value,
                "message": f"Entry not found: {entry_id}",
                "actionable": True,
            },
        }
    score = calculate_freshness_score(entry, ttl_days)
    return {"entry_id": entry_id, "freshness_score": score, "ttl_days": ttl_days}


# ---------------------------------------------------------------------------
# End-User Trial handlers (Task 14)
# ---------------------------------------------------------------------------


def _handle_activate_trial(
    end_user_id: str,
    days: int = 14,
) -> dict[str, Any]:
    """Activate or reset the trial period for an end-user."""
    from autoinfo.user_store import activate_trial

    try:
        return activate_trial(end_user_id=end_user_id, days=days)
    except Exception as exc:
        logger.exception("activate_trial failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_check_trial_expiry(end_user_id: str) -> dict[str, Any]:
    """Check trial expiry status for an end-user."""
    from autoinfo.user_store import check_trial_expiry

    try:
        return check_trial_expiry(end_user_id=end_user_id)
    except Exception as exc:
        logger.exception("check_trial_expiry failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


# ---------------------------------------------------------------------------
# Stripe Billing handlers (2)
# ---------------------------------------------------------------------------


def _handle_create_checkout_session(
    product_id: str,
    end_user_id: str,
    *,
    mode: str = "subscription",
    success_url: str = "http://localhost:8741/success",
    cancel_url: str = "http://localhost:8741/cancel",
    email: str = "",
    name: str = "",
    article_id: str = "",
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for a product."""
    from autoinfo.billing import create_checkout_session

    try:
        return create_checkout_session(
            product_id=product_id,
            end_user_id=end_user_id,
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            email=email,
            name=name,
            article_id=article_id,
        )
    except Exception as exc:
        logger.exception("create_checkout_session failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_get_subscription_status(end_user_id: str = "") -> dict[str, Any]:
    """Check Stripe subscription status for an end-user."""
    from autoinfo.billing import get_subscription_status, resolve_user_id

    end_user_id = resolve_user_id(end_user_id or None)
    try:
        return get_subscription_status(end_user_id=end_user_id)
    except Exception as exc:
        logger.exception("get_subscription_status failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_get_billing_summary(
    user_id: str = "",
    period: str = "month",
) -> dict[str, Any]:
    """Return combined billing summary — usage + subscription.

    Combines CostMeter usage data with Stripe subscription status into
    a single read-only summary.

    Parameters
    ----------
    user_id:
        AutoInfo end-user ID (e.g. ``alice``).  Optional — falls back
        to ``multi_user.default_user_id`` from config, then ``"default"``.
    period:
        Time period: ``"today"``, ``"week"``, ``"month"``, ``"all"``.
        Defaults to ``"month"``.

    Returns
    -------
    dict with keys: ``user_id``, ``period``, ``usage``, ``subscription``.
    """
    from autoinfo.billing import get_subscription_status, resolve_user_id
    from autoinfo.cost import CostMeter

    user_id = resolve_user_id(user_id or None)
    try:
        meter = CostMeter()
        usage = meter.get_enduser_usage(end_user_id=user_id, period=period)
        subscription = get_subscription_status(end_user_id=user_id)
    except Exception as exc:
        logger.exception("get_billing_summary failed for '%s'", user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }

    return {
        "user_id": user_id,
        "period": period,
        "usage": {
            "llm_units": usage.get("llm_units", 0),
            "storage_mb": usage.get("storage_mb", 0.0),
            "api_call_units": usage.get("api_call_units", 0),
        },
        "subscription": {
            "status": subscription.get("profile_status", "unknown"),
            "plan": subscription.get("plan", "free"),
            "stripe_status": subscription.get("stripe_status", "none"),
            "customer_id": subscription.get("customer_id", ""),
        },
    }


# ---------------------------------------------------------------------------
# Usage-based billing handlers (G16 — 2)
# ---------------------------------------------------------------------------


def _handle_get_enduser_usage(
    end_user_id: str,
    period: str = "month",
) -> dict[str, Any]:
    """Return billable usage for an end-user over a period.

    Delegates to ``CostMeter.get_enduser_usage``, which queries the cost_log
    and maps internal CostMeter units to customer-billable units:
    LLM tokens → llm_units, storage items → storage_mb, API calls → api_call_units.
    """
    from autoinfo.cost import CostMeter

    try:
        meter = CostMeter()
        return meter.get_enduser_usage(end_user_id=end_user_id, period=period)
    except Exception as exc:
        logger.exception("get_enduser_usage failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_get_enduser_invoice(
    end_user_id: str,
    period: str = "month",
) -> dict[str, Any]:
    """Return an invoice-like summary with usage and estimated cost.

    Delegates to ``CostMeter.get_enduser_invoice``, which computes billable
    units via get_enduser_usage and applies configurable unit pricing.
    """
    from autoinfo.cost import CostMeter

    try:
        meter = CostMeter()
        return meter.get_enduser_invoice(end_user_id=end_user_id, period=period)
    except Exception as exc:
        logger.exception("get_enduser_invoice failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


# ---------------------------------------------------------------------------
# Agent Callback handlers (3)
# ---------------------------------------------------------------------------
# End-User Preferences handlers (Task 16)
# ---------------------------------------------------------------------------


def _handle_update_preferences(
    end_user_id: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Merge preferences into stored preferences for an end-user."""
    from autoinfo.user_store import (  # noqa: PLC0415
        CONTENT_PREFERENCE_VALUES,
        update_preferences,
    )

    if "content_preference" in preferences:
        cp = preferences["content_preference"]
        if cp not in CONTENT_PREFERENCE_VALUES:
            return error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message=(
                    f"Invalid content_preference '{cp}'. "
                    f"Must be one of: {', '.join(sorted(CONTENT_PREFERENCE_VALUES))}"
                ),
                actionable=True,
            )

    try:
        return update_preferences(end_user_id=end_user_id, preferences=preferences)
    except Exception as exc:
        logger.exception("update_preferences failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_get_preferences(end_user_id: str) -> dict[str, Any]:
    """Return stored preferences for an end-user."""
    from autoinfo.user_store import get_preferences

    try:
        return get_preferences(end_user_id=end_user_id)
    except Exception as exc:
        logger.exception("get_preferences failed for '%s'", end_user_id)
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


# ---------------------------------------------------------------------------
# End-User CRUD handlers (5)
# ---------------------------------------------------------------------------


def _handle_enduser_create(
    user_id: str,
    name: str,
    email: str = "",
    delivery_prefs: dict[str, Any] | None = None,
    status: str = "trial",
    tier: str = "free",
) -> dict[str, Any]:
    """Create a new end-user profile (mirrors ``autoinfo enduser create``)."""
    from dataclasses import asdict as _asdict

    from autoinfo.user_store import create_profile

    try:
        profile = create_profile(
            user_id=user_id,
            name=name,
            email=email,
            delivery_prefs=delivery_prefs or {},
            status=status,
            tier=tier,
        )
    except Exception as exc:
        logger.exception("enduser_create failed for '%s'", user_id)
        return _error_from_exc(exc, "enduser_create failed")

    return success_response(_asdict(profile))


def _handle_enduser_get(user_id: str) -> dict[str, Any]:
    """Get an end-user profile by user ID (mirrors ``autoinfo enduser get``)."""
    from dataclasses import asdict as _asdict

    from autoinfo.user_store import get_profile

    try:
        profile = get_profile(user_id)
    except Exception as exc:
        logger.exception("enduser_get failed for '%s'", user_id)
        return _error_from_exc(exc, "enduser_get failed")

    if profile is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"End-user '{user_id}' not found",
            "actionable": True,
        }

    return success_response(_asdict(profile))


def _handle_enduser_update(
    user_id: str,
    name: str | None = None,
    email: str | None = None,
    delivery_prefs: dict[str, Any] | None = None,
    status: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Update an end-user profile (partial update, mirrors ``autoinfo enduser update``)."""
    from dataclasses import asdict as _asdict

    from autoinfo.user_store import update_profile

    try:
        profile = update_profile(
            user_id=user_id,
            name=name,
            email=email,
            delivery_prefs=delivery_prefs,
            status=status,
            tier=tier,
        )
    except Exception as exc:
        logger.exception("enduser_update failed for '%s'", user_id)
        return _error_from_exc(exc, "enduser_update failed")

    if profile is None:
        return {
            "error_code": ErrorCode.NOT_FOUND.value,
            "message": f"End-user '{user_id}' not found",
            "actionable": True,
        }

    return success_response(_asdict(profile))


def _handle_enduser_delete(user_id: str) -> dict[str, Any]:
    """Delete an end-user profile and associated subscriptions (mirrors ``autoinfo enduser delete``)."""
    from autoinfo.user_store import delete_profile

    try:
        ok = delete_profile(user_id)
    except Exception as exc:
        logger.exception("enduser_delete failed for '%s'", user_id)
        return _error_from_exc(exc, "enduser_delete failed")

    if not ok:
        return error_response(
            code=ErrorCode.NOT_FOUND,
            message=f"End-user '{user_id}' not found",
            actionable=True,
        )

    return success_response({"user_id": user_id, "deleted": True})


def _handle_enduser_list() -> dict[str, Any]:
    """List all end-user profiles (mirrors ``autoinfo enduser list``)."""
    from dataclasses import asdict as _asdict

    from autoinfo.user_store import list_profiles

    try:
        profiles = list_profiles()
    except Exception as exc:
        logger.exception("enduser_list failed")
        return _error_from_exc(exc, "enduser_list failed")

    items = [_asdict(p) for p in profiles]
    return success_response({"items": items, "count": len(items)})


# ---------------------------------------------------------------------------
# Agent Callback handlers (3)
# ---------------------------------------------------------------------------

def _handle_set_agent_callback(
    agent_url: str,
    events: list[str],
) -> dict[str, Any]:
    """Register a new agent callback URL for specified events."""
    from autoinfo.agent_callback import register_agent_callback

    try:
        callback_id = register_agent_callback(agent_url=agent_url, events=events)
        return {
            "callback_id": callback_id,
            "agent_url": agent_url,
            "events": events,
            "created": True,
        }
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("set_agent_callback failed")
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_list_agent_callbacks() -> dict[str, Any] | list[dict[str, Any]]:
    """List all registered agent callbacks."""
    from autoinfo.agent_callback import list_agent_callbacks

    try:
        return list_agent_callbacks()
    except Exception as exc:
        logger.exception("list_agent_callbacks failed")
        return {
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }


def _handle_remove_agent_callback(callback_id: str) -> dict[str, Any]:
    """Remove a registered agent callback."""
    from autoinfo.agent_callback import remove_agent_callback

    try:
        removed = remove_agent_callback(callback_id)
        if removed:
            return {"callback_id": callback_id, "removed": True}
        return error_response(
            code=ErrorCode.NOT_FOUND,
            message=f"Callback '{callback_id}' not found",
            actionable=True,
        )
    except Exception as exc:
        logger.exception("remove_agent_callback failed")
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message=str(exc),
            actionable=True,
        )


# ---------------------------------------------------------------------------
# Recommendation (1)
# ---------------------------------------------------------------------------


def _handle_simplify_content(
    content: str,
    target_level: str,
    language: str = "en",
) -> dict[str, Any]:
    """Handle simplify_content MCP tool."""
    from autoinfo.output import simplify_text

    result = simplify_text(content, target_level, language)

    if target_level not in (frozenset({"A1", "A2", "B1", "B2", "C1"})):
        return error_dict(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=(
                f"Invalid target_level: '{target_level}'. "
                "Must be one of A1, A2, B1, B2, C1."
            ),
            actionable=True,
        )

    error_msg = result.get("error")
    if error_msg and not result["verified"]:
        return success_response({**result, "warning": error_msg})

    return success_response(result)


# ---------------------------------------------------------------------------
# Validation (2)
# ---------------------------------------------------------------------------


def _handle_list_validation_scenarios() -> dict[str, Any]:
    """Handle list_validation_scenarios MCP tool."""
    from autoinfo.mcp.validation import list_scenarios

    return list_scenarios()


async def _handle_run_validation_scenario(
    scenario: str,
    steps: list[int] | None = None,
    save_results: bool = False,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Handle run_validation_scenario MCP tool."""
    from autoinfo.mcp.validation import run_scenario, save_scenario_results

    async def _validation_dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        texts = await call_tool(name, arguments)
        return cast(dict[str, Any], json.loads(texts[0].text))

    try:
        result = await run_scenario(
            scenario,
            dispatch=_validation_dispatch,
            steps=steps,
            timeout=timeout,
        )
        if save_results:
            run_dir = save_scenario_results([result])
            result["saved_run"] = str(run_dir)
        return result
    except ValueError as exc:
        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            actionable=True,
        )


def _handle_recommend_content(
    user_id: str,
    query: str = "",
    domain: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Handle recommend_content MCP tool."""
    try:
        from autoinfo.recommend import ContentBasedEngine

        engine = ContentBasedEngine()
        items = engine.recommend(
            user_id=user_id,
            query=query,
            domain=domain or None,
            limit=limit,
        )
        return {
            "user_id": user_id,
            "query": query,
            "items": [
                {
                    "entry_id": item.entry_id,
                    "title": item.title,
                    "score": item.score,
                    "reason": item.reason,
                    "source_url": item.source_url,
                    "domain": item.domain,
                }
                for item in items
            ],
            "count": len(items),
        }
    except Exception as exc:
        logger.error("recommend_content failed: %s", exc)
        return error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message=str(exc),
            actionable=True,
        )


# ---------------------------------------------------------------------------
# KB: Create entry from scratch (1)
# ---------------------------------------------------------------------------


def _handle_create_kb_entry(
    domain: str,
    title: str,
    content: str,
    source_url: str,
    source_type: str,
    topics: list[str] | None = None,
    author: str = "",
) -> dict[str, Any]:
    """Create a KB entry from scratch in the 01-Raw tier.

    Architecture rule: 01-Raw is the sole entry point for all
    collected and manually-created content.  This tool writes to
    01-Raw only — 02-Draft and 03-Wiki are reached through separate
    promotion steps.

    Parameters
    ----------
    domain:
        Target domain name (e.g. medical-research).
    title:
        Entry title.
    content:
        Full text / Markdown content of the entry.
    source_url:
        Source URL (mandatory provenance).
    source_type:
        Source type (e.g. web, api, manual).
    topics:
        Optional list of topic tags.
    author:
        Optional author name (stored in KBEntry frontmatter).

    Returns
    -------
    dict
        ``{entry_id, tier, source_url, created_at, title, domain}``
        wrapped in ``success_response()`` envelope.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from autoinfo.kb import MIN_KB_CONTENT_CHARS, KBStore
    from autoinfo.models import Item

    try:
        if not domain or not title or not content or not source_url:
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": (
                    "domain, title, content, and source_url are required"
                ),
                "actionable": True,
            }

        if len(content.strip()) < MIN_KB_CONTENT_CHARS:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                f"content must be at least {MIN_KB_CONTENT_CHARS} characters",
                actionable=True,
            )

        topic_tags = topics or []

        item = Item(
            id=str(uuid4()),
            source_name=source_type,
            source_type=source_type,
            source_url=source_url,
            source_platform=source_type,
            title=title,
            content=content,
            domain=domain,
            topic_tags=topic_tags,
            collected_at=datetime.now(timezone.utc).isoformat(),
            content_type="text",
            quality_tier=1,
        )

        store = KBStore(min_content_chars=MIN_KB_CONTENT_CHARS)
        entry = store.store_entry(item=item, tier="01-Raw")

        if entry is None:
            # Issue #182: rejected (content too short) — clean error response
            return {
                "error_code": ErrorCode.VALIDATION_ERROR.value,
                "message": "entry rejected by KB store (content too short or unparseable)",
                "actionable": True,
            }

        return success_response({
            "entry_id": entry.entry_id,
            "tier": entry.tier,
            "source_url": entry.source_url,
            "created_at": entry.collected_at,
            "title": entry.title,
            "domain": entry.domain,
        })
    except ValueError as exc:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": str(exc),
            "actionable": True,
        }
    except Exception as exc:
        logger.exception("create_kb_entry failed")
        return _error_from_exc(exc, "create_kb_entry failed")


# ---------------------------------------------------------------------------
# T15: Audit Log Query
# ---------------------------------------------------------------------------


def _handle_query_audit_log(
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Query the immutable audit log with optional filters.

    Parameters
    ----------
    actor:
        Filter by actor name.
    action:
        Filter by action name.
    resource_type:
        Filter by resource type.
    date_from:
        ISO-8601 lower bound on timestamp.
    date_to:
        ISO-8601 upper bound on timestamp.
    limit:
        Max entries to return (default 100).
    offset:
        Pagination offset (default 0).

    Returns
    -------
    dict
        ``{entries, count}``.
    """
    try:
        from autoinfo.audit import query_audit_log

        entries = query_audit_log(
            actor=actor,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return {
            "entries": [asdict(e) for e in entries],
            "count": len(entries),
        }
    except Exception as exc:
        logger.exception("Audit log query failed")
        return _error_from_exc(exc, "Audit log query failed")


# ---------------------------------------------------------------------------
# T16: CEFR Batch Classification
# ---------------------------------------------------------------------------


def _handle_cefr_batch(
    texts: list[str],
    lang: str = "en",
) -> dict[str, Any]:
    """Batch classify multiple texts into CEFR levels (A1-C2).

    Parameters
    ----------
    texts:
        List of texts to classify.
    lang:
        Language code: ``"en"``, ``"zh"``, or ``"ja"`` (default ``"en"``).

    Returns
    -------
    dict
        ``{results, total, errors}`` where each result is
        ``{text, cefr_level, confidence}`` or ``{text, error}``.
    """
    try:
        config = _load_config()
        model_config: dict[str, Any] = {}
        if hasattr(config, "cefr") and config.cefr.model:
            model_config["model"] = config.cefr.model
        elif config.llm.provider and config.llm.model:
            llm_model = config.llm.model
            if "/" not in llm_model:
                llm_model = f"{config.llm.provider}/{llm_model}"
            model_config["model"] = llm_model
        if config.llm.api_key:
            model_config["api_key"] = config.llm.api_key
        if config.llm.base_url:
            model_config["base_url"] = config.llm.base_url
    except Exception:
        model_config = {}

    from autoinfo.cefr import classify_text

    if not texts:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": "texts must be a non-empty list",
            "actionable": True,
        }

    results: list[dict[str, Any]] = []
    errors = 0

    # Bounded fan-out: at most 8 concurrent classifications (env override
    # AUTOINFO_CEFR_BATCH_WORKERS), never more than the number of texts.
    # Each per-text task runs through classify_text -> call_with_fallback,
    # which acquires the shared per-provider semaphore (llm.py) so the
    # fan-out stays rate-limited.  Futures are keyed by original index and
    # collected in insertion order, preserving the sequential response order.
    max_workers = min(len(texts), 8)
    raw_workers = os.environ.get("AUTOINFO_CEFR_BATCH_WORKERS", "")
    if raw_workers.isdigit():
        max_workers = min(len(texts), max(1, int(raw_workers)))

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="cefr-batch",
    ) as pool:
        futures = {
            i: pool.submit(classify_text, text=t, lang=lang, model_config=model_config)
            for i, t in enumerate(texts)
        }
        for i, future in futures.items():
            try:
                result = future.result()
                results.append({
                    "text": texts[i],
                    "cefr_level": result["cefr_level"],
                    "confidence": result["confidence"],
                })
            except Exception as exc:
                results.append({"text": texts[i], "error": str(exc)})
                errors += 1

    return {
        "results": results,
        "total": len(texts),
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# T17: Email SMTP Config
# ---------------------------------------------------------------------------


def _handle_email_config(
    smtp_server: str = "",
    smtp_port: int = 0,
    username: str = "",
    password: str = "",
    enable: bool = False,
    disable: bool = False,
    test: bool = False,
) -> dict[str, Any]:
    """View or update email SMTP configuration.

    Parameters
    ----------
    smtp_server:
        SMTP server hostname.
    smtp_port:
        SMTP server port.
    username:
        SMTP username.
    password:
        SMTP password.
    enable:
        Enable email sending.
    disable:
        Disable email sending.
    test:
        Send a test email using current config.

    Returns
    -------
    dict
        ``{config: {smtp_host, smtp_port, enabled, ...}, updated, test_result}``.
    """
    import smtplib
    from email.mime.text import MIMEText

    try:
        cfg = _load_config()
    except Exception as exc:
        return _error_from_exc(exc, "Failed to load the project configuration")

    email_cfg = cfg.email

    if enable and disable:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": "Cannot use both enable and disable.",
            "actionable": True,
        }

    changed = False
    if smtp_server:
        email_cfg.smtp_host = smtp_server
        changed = True
    if smtp_port > 0:
        email_cfg.smtp_port = smtp_port
        changed = True
    if username:
        email_cfg.smtp_user = username
        changed = True
    if password:
        email_cfg.smtp_pass = password
        changed = True
    if enable:
        email_cfg.enabled = True
        changed = True
    if disable:
        email_cfg.enabled = False
        changed = True

    if changed:
        _save_config(cfg)

    config_summary: dict[str, Any] = {
        "smtp_host": email_cfg.smtp_host or "(not set)",
        "smtp_port": email_cfg.smtp_port,
        "smtp_user": email_cfg.smtp_user or "(not set)",
        "smtp_pass": "****" if email_cfg.smtp_pass else "(not set)",
        "from_addr": email_cfg.from_addr or "(not set)",
        "to_addrs": email_cfg.to_addrs or [],
        "enabled": email_cfg.enabled,
    }

    response: dict[str, Any] = {
        "config": config_summary,
        "updated": changed,
        "test_result": None,
    }

    if test:
        if not email_cfg.smtp_host:
            response["test_result"] = "skipped: SMTP server not configured"
        elif not email_cfg.from_addr and not email_cfg.smtp_user:
            response["test_result"] = "skipped: no from address configured"
        elif not email_cfg.to_addrs:
            response["test_result"] = "skipped: no recipients configured"
        else:
            from_addr = email_cfg.from_addr or email_cfg.smtp_user
            to_addrs = email_cfg.to_addrs

            msg = MIMEText(
                "This is a test email from AutoInfo.\n\n"
                "If you received this, SMTP configuration is working correctly."
            )
            msg["Subject"] = "[AutoInfo] Test Email"
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)

            server = None
            try:
                server = smtplib.SMTP(
                    email_cfg.smtp_host, email_cfg.smtp_port, timeout=30
                )
                server.ehlo()
                if server.has_extn("STARTTLS"):
                    server.starttls()
                    server.ehlo()
                if email_cfg.smtp_user and email_cfg.smtp_pass:
                    server.login(email_cfg.smtp_user, email_cfg.smtp_pass)
                server.sendmail(from_addr, to_addrs, msg.as_string())
                response["test_result"] = f"success: sent to {', '.join(to_addrs)}"
            except (smtplib.SMTPException, OSError) as exc:
                response["test_result"] = f"failed: {exc}"
            finally:
                if server is not None:
                    try:
                        server.quit()
                    except Exception:
                        pass

    return response


# ---------------------------------------------------------------------------
# T18: Knowledge Graph Export
# ---------------------------------------------------------------------------


def _handle_knowledge_graph_export(
    domain: str,
    format: str = "json",
    output: str = "",
) -> dict[str, Any]:
    """Export the knowledge graph for a domain.

    Parameters
    ----------
    domain:
        Domain name (e.g. medical-research).
    format:
        Export format: ``"json"``, ``"graphml"``, or ``"csv"``.
    output:
        Optional output file path (auto-generated if omitted).

    Returns
    -------
    dict
        ``{domain, format, output_path, entity_count, relation_count}``.
    """
    valid_formats = {"json", "graphml", "csv"}
    if format not in valid_formats:
        return {
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": f"Unsupported format '{format}'. Supported: {', '.join(sorted(valid_formats))}",
            "actionable": True,
        }

    from autoinfo.kb import KBStore

    store = KBStore()

    try:
        data = store.export_knowledge_graph(domain=domain)
    except Exception as exc:
        logger.exception("Knowledge graph export failed for domain '%s'", domain)
        return _error_from_exc(exc, "Knowledge graph export failed")

    out_path = (Path(output) if output
                else Path(f"knowledge_graph_export.{format}"))

    try:
        if format == "json":
            content = json.dumps(data, ensure_ascii=False, indent=2)
            out_path.write_text(content, encoding="utf-8")
        elif format == "graphml":
            from autoinfo.cli.knowledge import _build_graphml
            xml_content = _build_graphml(data)
            out_path.write_text(xml_content, encoding="utf-8")
        elif format == "csv":
            from autoinfo.cli.knowledge import _write_csv
            stem = str(out_path.with_suffix(""))
            _write_csv(data, stem)
    except OSError as exc:
        logger.exception("Error writing knowledge graph export file")
        return _error_from_exc(exc, "Error writing knowledge graph export file")

    return {
        "domain": domain,
        "format": format,
        "output_path": str(out_path),
        "entity_count": len(data.get("entities", [])),
        "relation_count": len(data.get("relations", [])),
    }


# ---------------------------------------------------------------------------
# T19: Clean Cache
# ---------------------------------------------------------------------------


def _handle_clean_cache(
    collections: bool = False,
    outputs: bool = False,
    everything: bool = False,
    dry_run: bool = False,
    confirm: bool = False,
    actor: str = "agent",
) -> dict[str, Any]:
    """Remove cached artifacts and temporary files.

    Parameters
    ----------
    collections:
        Remove cached collections/ contents.
    outputs:
        Remove outputs/ contents.
    everything:
        Remove ALL cached data (collections + outputs + knowledge + DB).
    dry_run:
        Show what would be deleted without deleting (default False).

    Returns
    -------
    dict
        ``{items_removed, dry_run, targets}``.
    """
    if everything and not confirm and not dry_run:
        return error_response(
            code=ErrorCode.CONFIRMATION_REQUIRED,
            message="clean_cache(everything=True) requires confirm=true — this deletes the entire knowledge/ directory and database",
            actionable=True,
        )
    import shutil

    targets: list[str] = []
    total = 0

    if collections or everything:
        path = Path("collections")
        if path.is_dir():
            if dry_run:
                cnt = sum(1 for _ in path.iterdir())
            else:
                cnt = 0
                for child in path.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    cnt += 1
            total += cnt
            targets.append(f"collections ({cnt} items)")
    if outputs or everything:
        path = Path("outputs")
        if path.is_dir():
            if dry_run:
                cnt = sum(1 for _ in path.iterdir())
            else:
                cnt = 0
                for child in path.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    cnt += 1
            total += cnt
            targets.append(f"outputs ({cnt} items)")
    if everything:
        path = Path("knowledge")
        if path.is_dir():
            if dry_run:
                cnt = sum(1 for _ in path.iterdir())
            else:
                cnt = 0
                for child in path.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    cnt += 1
            total += cnt
            targets.append(f"knowledge ({cnt} items)")

        db_path = Path("autoinfo.db")
        if db_path.is_file():
            if not dry_run:
                db_path.unlink()
            total += 1
            targets.append("autoinfo.db")

    return {
        "items_removed": total,
        "dry_run": dry_run,
        "targets": targets,
    }


# ---------------------------------------------------------------------------
# T20: Cost Dashboard
# ---------------------------------------------------------------------------


def _handle_cost_dashboard(
    period: str = "week",
) -> dict[str, Any]:
    """Show cost dashboard — totals by domain, daily trend, top models/sources, budget status.

    Parameters
    ----------
    period:
        Time period: ``"today"``, ``"week"``, ``"month"``, ``"all"`` (default ``"week"``).

    Returns
    -------
    dict
        Cost dashboard data with ``total_cost``, ``by_domain``, ``daily_trend``,
        ``top_models``, ``top_sources``, ``budget_status``.
    """
    try:
        from autoinfo.cost import CostMeter

        meter = CostMeter()
        return meter.get_cost_dashboard(period=period)
    except Exception as exc:
        logger.exception("Cost dashboard failed")
        return _error_from_exc(exc, "Cost dashboard failed")


# ---------------------------------------------------------------------------
# T21: Cost Allocation
# ---------------------------------------------------------------------------


def _handle_cost_allocation(
    domain: str = "",
    user_id: str = "",
    period: str = "all",
) -> dict[str, Any]:
    """Show cost allocation broken down by domain and user.

    Parameters
    ----------
    domain:
        Optional domain filter (empty = all).
    user_id:
        Optional user ID filter (empty = all).
    period:
        Time period: ``"all"``, ``"today"``, ``"week"``, ``"month"`` (default ``"all"``).

    Returns
    -------
    dict
        ``{period, domain_filter, user_id_filter, total_cost, log_count, by_domain, by_user}``.
    """
    try:
        from autoinfo.cost import CostMeter

        meter = CostMeter()
        return meter.get_cost_allocation(
            domain=domain, user_id=user_id, period=period
        )
    except Exception as exc:
        logger.exception("Cost allocation failed")
        return _error_from_exc(exc, "Cost allocation failed")


def _error_from_exc(exc: Exception, context: str) -> dict[str, Any]:
    """Build an actionable error dict from an unexpected exception.

    Replaces the old ``_error_dict(exc)`` which leaked the raw exception
    string as the agent-facing message (D-工-4: no raw-exception leakage).
    The message now carries a human-readable operation context plus the
    exception detail and a concrete next step.

    Returns both the legacy flat fields (``error_code``, ``message``,
    ``actionable``) and the new envelope fields (``success``, ``error``).
    Callers receive a fully populated error dict that passes through the
    standard call_tool wrapping unchanged (idempotent).
    """
    code_str = ErrorCode.INTERNAL_ERROR.value
    message_str = (
        f"{context}: {exc}. Check the request parameters and retry, "
        "or consult the docs for supported inputs."
    )
    return {
        "error_code": code_str,
        "message": message_str,
        "actionable": True,
        "success": False,
        "error": {
            "code": code_str,
            "message": message_str,
            "actionable": True,
        },
    }


def _error_response(exc: Exception) -> list[TextContent]:
    """Build a standardised error response in the envelope format.

    Maps well-known exception types to appropriate ``ErrorCodes``.
    Falls back to ``INTERNAL_ERROR`` for unrecognised exceptions.

    Returns ``list[TextContent]`` with the uniform ``{success, error}`` shape.
    """
    # -- Determine ErrorCode from exception type ---------------------------
    if isinstance(exc, DirectorOnlyError):
        code = ErrorCode.DIRECTOR_ONLY
    elif isinstance(exc, FileNotFoundError):
        code = ErrorCode.NOT_FOUND
    elif isinstance(exc, (ValueError, KeyError)):
        code = ErrorCode.VALIDATION_ERROR
    elif isinstance(exc, ConnectionError):
        code = ErrorCode.TIMEOUT
    else:
        code = ErrorCode.INTERNAL_ERROR
        # httpx.ConnectError → Timeout (httpx is optional)
        try:
            import httpx

            if isinstance(exc, httpx.ConnectError):
                code = ErrorCode.TIMEOUT
        except ImportError:
            pass

    # Lazy litellm check — AuthenticationError → LLM_NOT_CONFIGURED
    if code == ErrorCode.INTERNAL_ERROR:
        try:
            import litellm.exceptions

            if isinstance(exc, litellm.exceptions.AuthenticationError):
                code = ErrorCode.LLM_NOT_CONFIGURED
        except ImportError:
            pass

    return [
        TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": {
                    "code": code.value,
                    "message": str(exc),
                    "actionable": True,
                },
            }),
        )
    ]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

app = Server("autoinfo")


@app.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
async def list_tools() -> list[Tool]:
    """Declare the available MCP tools with their input schemas."""
    return [
        # -- System (2) ---------------------------------------------------
        Tool(
            name="health_check",
            description="Check server health status",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_tool_count",
            description="Return the number of registered MCP tools",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="diagnose_system",
            description=(
                "Comprehensive system diagnostics — LLM config, "
                "sources, disk, database, health_score (0-100), "
                "and phase detection (uninitialized/llm_unconfigured/"
                "no_sources/ready_to_collect/operational)"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        # -- Discovery (7) ------------------------------------------------
        Tool(
            name="list_domains",
            description="List all configured domains with source/topic counts",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_available_platforms",
            description="List all supported source platform types with descriptions",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_domain_schema",
            description="Return the extraction schema and structure for a domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="list_available_models",
            description="List configured LLM models with provider and task info",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_effective_llm_config",
            description="Resolve the effective LLM configuration for a task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "Optional task name (e.g. extraction, "
                            "summarization)"
                        ),
                        "default": None,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="activate_domain",
            description="Activate a domain (set domain.active = True)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Domain name to activate",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="deactivate_domain",
            description="Deactivate a domain (set domain.active = False)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Domain name to deactivate",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="add_domain",
            description="Create a new domain configuration (idempotent — returns existing config if domain already exists)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Domain name (e.g. my-custom-domain)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of the domain",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="remove_domain",
            description="Remove a domain configuration. Preserves all collected data on disk. Requires confirm=True (destructive operation).",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Domain name to remove",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to remove a domain (destructive operation)",
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["name", "confirm", "actor"],
            },
        ),
        Tool(
            name="get_domain_config",
            description="Return full domain config including sources, topics, extract_fields",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["name"],
            },
        ),
        # -- Source Management (5) ----------------------------------------
        Tool(
            name="add_source",
            description=(
                "Add a data source (idempotent — dedup by url + type + domain). "
                "Supports 6 source types: api, rss, web, webhook, email, pdf. "
                "For email sources, pass imap_server/imap_port/imap_username/"
                "imap_password/imap_mailbox convenience params. "
                "For webhook sources, pass webhook_secret for HMAC verification. "
                "All types accept an optional settings dict for arbitrary configuration."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable source name",
                    },
                    "url": {
                        "type": "string",
                        "description": "Source URL. email: imap(s)://host, pdf: file://path or http(s)://url, others: http(s)://url",
                    },
                    "type": {
                        "type": "string",
                        "description": "Source type (api, rss, web, webhook, email, pdf)",
                        "default": "api",
                        "enum": ["api", "rss", "web", "webhook", "email", "pdf", "akshare", "sec_edgar", "edx_sitemap"],
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domain to add this source to",
                    },
                    "settings": {
                        "type": "object",
                        "description": "Optional key-value configuration (stored in SourceConfig.settings)",
                    },
                    "requires_key": {
                        "type": "boolean",
                        "description": (
                            "Whether this source requires an API key/credential. "
                            "Defaults to derived from the source type (true for "
                            "known key-requiring types, e.g. nyt, ap_api, "
                            "reuters_mcp, unpaywall, youtube)."
                        ),
                    },
                    "imap_server": {
                        "type": "string",
                        "description": "Email type only: IMAP server hostname (e.g. imap.gmail.com)",
                    },
                    "imap_port": {
                        "type": "integer",
                        "description": "Email type only: IMAP port (default 993)",
                    },
                    "imap_username": {
                        "type": "string",
                        "description": "Email type only: IMAP username",
                    },
                    "imap_password": {
                        "type": "string",
                        "description": "Email type only: IMAP password (or set AUTOINFO_EMAIL_PASSWORD env var)",
                    },
                    "imap_mailbox": {
                        "type": "string",
                        "description": "Email type only: IMAP mailbox name (default INBOX)",
                    },
                    "webhook_secret": {
                        "type": "string",
                        "description": "Webhook type only: HMAC shared secret for payload verification",
                    },
                },
                "required": ["name", "url", "domain"],
            },
        ),
        Tool(
            name="add_sources",
            description="Batch-add sources with per-source error isolation. Each source object supports the same parameters as add_source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Human-readable source name",
                                },
                                "url": {
                                    "type": "string",
                                    "description": "Source URL. email: imap(s)://host, pdf: file://path or http(s)://url, others: http(s)://url",
                                },
                                "type": {
                                    "type": "string",
                                    "default": "api",
                                    "description": "Source type (api, rss, web, webhook, email, pdf)",
                                    "enum": ["api", "rss", "web", "webhook", "email", "pdf", "akshare", "sec_edgar", "edx_sitemap"],
                                },
                                "domain": {
                                    "type": "string",
                                    "description": "Domain to add this source to",
                                },
                                "settings": {
                                    "type": "object",
                                    "description": "Optional key-value configuration (stored in SourceConfig.settings)",
                                },
                                "requires_key": {
                                    "type": "boolean",
                                    "description": (
                                        "Whether this source requires an API key/credential. "
                                        "Defaults to derived from the source type (true for "
                                        "known key-requiring types, e.g. nyt, ap_api, "
                                        "reuters_mcp, unpaywall, youtube)."
                                    ),
                                },
                                "imap_server": {
                                    "type": "string",
                                    "description": "Email type only: IMAP server hostname",
                                },
                                "imap_port": {
                                    "type": "integer",
                                    "description": "Email type only: IMAP port (default 993)",
                                },
                                "imap_username": {
                                    "type": "string",
                                    "description": "Email type only: IMAP username",
                                },
                                "imap_password": {
                                    "type": "string",
                                    "description": "Email type only: IMAP password",
                                },
                                "imap_mailbox": {
                                    "type": "string",
                                    "description": "Email type only: IMAP mailbox name (default INBOX)",
                                },
                                "webhook_secret": {
                                    "type": "string",
                                    "description": "Webhook type only: HMAC shared secret",
                                },
                            },
                            "required": ["name", "url", "domain"],
                        },
                        "description": "List of source objects to add",
                    },
                },
                "required": ["sources"],
            },
        ),
        Tool(
            name="remove_source",
            description="Remove a source by its source_id (format: 'domain:name')",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source identifier in 'domain:name' format (e.g. 'medical-research:pubmed'). Returned by add_source in the response.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to confirm this destructive operation",
                        "default": False,
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["source_id", "actor"],
            },
        ),
        Tool(
            name="test_source",
            description="Test whether a source URL is reachable and return metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Source URL to test",
                    },
                    "type": {
                        "type": "string",
                        "description": "Source type (api, rss, web, webhook, email, pdf)",
                        "default": "api",
                        "enum": ["api", "rss", "web", "webhook", "email", "pdf", "akshare", "sec_edgar", "edx_sitemap"],
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="list_sources",
            description=(
                "List all configured collection sources for a domain, with "
                "each source's id, type, and platform. Use to inspect what "
                "feeds a domain before adding or removing sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        # -- Topic Management (6) -----------------------------------------
        Tool(
            name="add_topic",
            description="Add a topic to a domain (idempotent by name+domain)",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name",
                    },
                    "name": {
                        "type": "string",
                        "description": "Topic name",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of related keywords",
                        "default": [],
                    },
                },
                "required": ["domain", "name"],
            },
        ),
        Tool(
            name="remove_topic",
            description="Remove a topic from a domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name",
                    },
                    "topic_id": {
                        "type": "string",
                        "description": "Topic identifier — name or 'domain:name' format (e.g. 'IVF breakthroughs' or 'medical-research:IVF breakthroughs'). Returned by add_topic in the response.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to confirm this destructive operation",
                        "default": False,
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["domain", "topic_id", "actor"],
            },
        ),
        Tool(
            name="list_topics",
            description=(
                "List all tracked topics and their keywords for a domain. "
                "Topics group collected items by area; use to review "
                "coverage before collecting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="list_keywords",
            description="List keywords with topic grouping, multi-language support, and scoring info",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional topic name filter",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="topic_group_add",
            description="Assign a group to one or more topics within a domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "group_name": {
                        "type": "string",
                        "description": "Name of the group to assign topics to",
                    },
                    "topic_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of topic names to assign to this group",
                    },
                },
                "required": ["domain", "group_name", "topic_names"],
            },
        ),
        Tool(
            name="topic_group_remove",
            description="Remove a group assignment from all topics in that group",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "group_name": {
                        "type": "string",
                        "description": "Name of the group whose assignment should be removed from all topics",
                    },
                },
                "required": ["domain", "group_name"],
            },
        ),
        # -- Keywords Management (3) ---------------------------------------
        Tool(
            name="approve_keyword",
            description="Approve a keyword — move from auto_added to verified state",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Keyword to approve",
                    },
                },
                "required": ["domain", "keyword"],
            },
        ),
        Tool(
            name="reject_keyword",
            description="Reject a keyword — move to deprecated state",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Keyword to reject",
                    },
                },
                "required": ["domain", "keyword"],
            },
        ),
        Tool(
            name="suggest_keywords",
            description="Use LLM to suggest relevant keywords from a text input",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name for context",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to extract keywords from",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of suggestions (default 10)",
                        "default": 10,
                    },
                },
                "required": ["domain", "text"],
            },
        ),
        # -- Collection / Processing (5) ----------------------------------
        Tool(
            name="collect_sources",
            description=(
                "Execute a collection run for a domain. When domain is "
                "omitted, collects from ALL active domains and returns a "
                "{domains: {name: job_id, ...}, collected_count: N} mapping."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": (
                            "Domain name (e.g. medical-research). "
                            "Omit to collect from all active domains."
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional topic / keyword filter",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of source names to restrict to"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items per source",
                        "default": 20,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "If true, preview only — no storage"
                        ),
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_collection_progress",
            description="Return current collection progress for a domain (in-memory state)",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain name — returns all domains if omitted",
                        "default": "",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Optional job_id to look up collection progress by job",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_collection_status",
            description="Return full collection results for a domain (last run)",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="process_collection",
            description=(
                "Execute a processing (LLM extraction) run for a domain. "
                "Optionally runs G4 factual consistency gate (check_factual) "
                "and G5 translation accuracy gate (check_translation)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Optional LLM model override "
                            "(e.g. deepseek/deepseek-chat)"
                        ),
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": (
                            "Max number of items to process per run "
                            "(0 = all, default 0)"
                        ),
                        "default": 0,
                    },
                    "check_factual": {
                        "type": "boolean",
                        "description": (
                            "Run G4 factual consistency gate "
                            "(LLM-based check of summary vs source). "
                            "Default: False."
                        ),
                        "default": False,
                    },
                    "check_translation": {
                        "type": "boolean",
                        "description": (
                            "Run G5 translation accuracy gate "
                            "(LLM-based check of translation vs source). "
                            "Default: False."
                        ),
                        "default": False,
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="get_processing_progress",
            description="Get processing progress for a domain or job_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Optional job_id to look up processing progress by job",
                    },
                },
                "required": [],
            },
        ),
        # -- Knowledge Base (4) -------------------------------------------
        Tool(
            name="list_summaries",
            description="Browse KB entries for a domain, newest first",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "date_from": {
                        "type": "string",
                        "description": (
                            "ISO date filter — only entries from "
                            "this date onward"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return",
                        "default": 20,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0,
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="get_kb_entry",
            description="Fetch a single KB entry by its entry ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "Unique entry identifier",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user_id filter (accepted for multi-user compatibility; direct ID lookup is user-independent)",
                    },
                },
                "required": ["entry_id"],
            },
        ),
        Tool(
            name="search_knowledge_base",
            description=(
                "Search the knowledge base using FTS5 full-text, vector, "
                "or hybrid (FTS5 + vector) search. "
                "Supports simple term queries with optional domain and "
                "faceted filters (tags, date range, quality tier, "
                "content type, language)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter. When omitted or None, searches across all domains.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 20,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0,
                    },
                    "mode": {
                        "type": "string",
                        "description": "Search mode: 'fts5' (default, full-text only), 'hybrid' (FTS5 + vector fusion), or 'vector' (vector-only). Falls back to FTS5 when vector search is unavailable.",
                        "default": "fts5",
                        "enum": ["fts5", "hybrid", "vector"],
                    },
                    "filter_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only include entries whose tags contain ANY of the given values",
                    },
                    "filter_date_from": {
                        "type": "string",
                        "description": "Only entries with collected_at >= this ISO date (e.g. 2025-01-01)",
                    },
                    "filter_date_to": {
                        "type": "string",
                        "description": "Only entries with collected_at <= this ISO date (e.g. 2025-06-30)",
                    },
                    "filter_quality_tier_min": {
                        "type": "integer",
                        "description": "Only entries with quality_tier >= this value",
                    },
                    "filter_quality_tier_max": {
                        "type": "integer",
                        "description": "Only entries with quality_tier <= this value",
                    },
                    "filter_content_type": {
                        "type": "string",
                        "description": "Only entries with this exact content_type",
                    },
                    "filter_language": {
                        "type": "string",
                        "description": "Only entries with this exact language",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user_id filter — only entries belonging to this user",
                    },
                    "filter_custom_fields": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Faceted filter over the custom_fields JSON column (product-analysis metadata). Each key is a dot-path into custom_fields (e.g. 'product_analysis.action_required'); an empty-string value matches entries where the field exists and is non-empty, any other value matches entries where the field's JSON value equals that text.",
                    },
                    "include_stale": {
                        "type": "boolean",
                        "description": "If false (default), stale entries are demoted to the bottom of search results. If true, stale entries are mixed normally with fresh results.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="query_knowledge_graph",
            description=(
                "Query the knowledge graph for entities related to a given "
                "entity.  Returns related entities with relation type and "
                "co-occurrence strength."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Entity name to query (case-insensitive partial match)",
                    },
                    "relation": {
                        "type": "string",
                        "description": "Relation type filter (default: 'related_to'). Use empty string for all.",
                        "default": "related_to",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain scope filter",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 20,
                    },
                },
                "required": ["entity"],
            },
        ),
        # -- Knowledge Graph Export (1) -------------------------------------
        Tool(
            name="knowledge_graph_export",
            description=(
                "Export the knowledge graph for a domain. "
                "Supports json, graphml, and csv formats. "
                "Returns entity and relation counts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format: json, graphml, csv",
                        "default": "json",
                        "enum": ["json", "graphml", "csv"],
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output file path (auto-generated if omitted)",
                        "default": "",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="flag_for_knowledge_base",
            description=(
                "Flag a summary entry for KB inclusion — tags it in the "
                "SQLite index with importance rating.  Does NOT create a "
                "Draft; call create_kb_draft separately."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_id": {
                        "type": "string",
                        "description": "Summary entry ID",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to apply (merged with existing, no duplicates)",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "Importance rating 1-5",
                        "default": 3,
                    },
                },
                "required": ["summary_id"],
            },
        ),
        # -- KB: get_summary -----------------------------------------
        Tool(
            name="get_summary",
            description=(
                "Return full detail for a summary entry including key "
                "points parsed from the body, quality scores, tags, "
                "importance, and source provenance."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_id": {
                        "type": "string",
                        "description": "Summary entry ID",
                    },
                },
                "required": ["summary_id"],
            },
        ),
        # -- KB: Relations (2) --------------------------------------------
        Tool(
            name="link_items",
            description=(
                "Create a link between two KB entries. Idempotent — "
                "calling with the same (item_a, item_b, relation_type) "
                "returns the existing relation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_a_id": {
                        "type": "string",
                        "description": "First entry ID",
                    },
                    "item_b_id": {
                        "type": "string",
                        "description": "Second entry ID",
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Relation type (e.g. related, references)",
                        "default": "related",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata dict (e.g. matched_tags)",
                    },
                },
                "required": ["item_a_id", "item_b_id"],
            },
        ),
        Tool(
            name="get_item_relations",
            description=(
                "Return all relations where an item participates. "
                "Optionally filtered by relation_type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Entry ID to query",
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Optional relation type filter",
                    },
                },
                "required": ["item_id"],
            },
        ),
        # -- KB: Versioning (2) -------------------------------------------
        Tool(
            name="get_entry_history",
            description=(
                "Return all saved backup versions for an entry, "
                "newest first. Up to 5 versions are retained."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "Entry ID to query",
                    },
                },
                "required": ["entry_id"],
            },
        ),
        Tool(
            name="restore_entry_version",
            description=(
                "Restore an entry from a saved version backup. "
                "Copies the .bak file back over the original."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "version_id": {
                        "type": "string",
                        "description": "Version ID to restore",
                    },
                },
                "required": ["version_id"],
            },
        ),
        Tool(
            name="compare_versions",
            description=(
                "Compare two versions of a KB entry and return a "
                "structured diff showing which fields changed, their "
                "old and new values, and a summary of changes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "KB entry ID whose versions to compare",
                    },
                    "version_a": {
                        "type": "string",
                        "description": (
                            "First version identifier (version_id like "
                            "'entry_abc--v1' or version number string like '1')"
                        ),
                    },
                    "version_b": {
                        "type": "string",
                        "description": (
                            "Second version identifier (version_id like "
                            "'entry_abc--v2' or version number string like '2')"
                        ),
                    },
                },
                "required": ["entry_id", "version_a", "version_b"],
            },
        ),
        # -- KB: Monitor (2) ----------------------------------------------
        Tool(
            name="get_collection_stats",
            description=(
                "Aggregated collection statistics across all domains "
                "for daily, weekly, or monthly periods."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Period: daily (default), weekly, monthly",
                        "default": "daily",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_collection_diff",
            description=(
                "Return entries collected since a previous collection ID, "
                "showing new entries grouped by domain."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "since_collection_id": {
                        "type": "string",
                        "description": "Collection ID (timestamp) to compare against",
                    },
                },
                "required": ["since_collection_id"],
            },
        ),
        Tool(
            name="get_domain_decay",
            description=(
                "Compute decay / staleness metrics for a domain. "
                "Returns staleness ratio, average TTL remaining, "
                "decay grade (GREEN/YELLOW/RED), and re-collection suggestions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name to compute decay metrics for",
                    },
                    "ttl_days": {
                        "type": "integer",
                        "description": (
                            "Days before an entry is considered fully stale "
                            "(default: 90)"
                        ),
                        "default": 90,
                    },
                },
                "required": ["domain"],
            },
        ),
        # -- KB: Draft tools (4) ------------------------------------------
        Tool(
            name="create_kb_draft",
            description=(
                "Create a Draft entry from one or more Raw entries. "
                "Validates all raw_ids exist in 01-Raw, merges content, "
                "and creates a file in 02-Draft/."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One or more 01-Raw entry IDs to compile into a Draft",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the new Draft entry",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional summary text",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for the Draft entry",
                    },
                },
                "required": ["raw_ids", "title"],
            },
        ),
        Tool(
            name="reject_kb_draft",
            description=(
                "Reject a Draft entry, moving it back to 01-Raw or "
                "archiving it.  Adds rejection_reason to frontmatter."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "Entry ID of the Draft to reject",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional rejection reason",
                    },
                    "action": {
                        "type": "string",
                        "description": (
                            "'back_to_raw' (default) moves to 01-Raw; "
                            "'archive' moves to _archive/"
                        ),
                        "default": "back_to_raw",
                        "enum": ["back_to_raw", "archive"],
                    },
                },
                "required": ["draft_id"],
            },
        ),
        Tool(
            name="list_kb_tier",
            description=(
                "List all entries in a specific KB tier (01-Raw, 02-Draft, 03-Wiki) "
                "for a domain."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "tier": {
                        "type": "string",
                        "description": "Tier to list (01-Raw, 02-Draft, 03-Wiki)",
                        "enum": ["01-Raw", "02-Draft", "03-Wiki"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0,
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user_id filter — only entries belonging to this user",
                    },
                },
                "required": ["domain", "tier"],
            },
        ),
        Tool(
            name="promote_kb_draft",
            description=(
                "Promote a Draft KB entry (02-Draft) to the 03-Wiki tier. "
                "Admission-gated agent promotion: the draft must satisfy "
                "the curation gate (source provenance, G1/G3 thresholds, "
                "G4 factual consistency) or the promotion is rejected and "
                "a _failed/ marker is written while the draft stays in "
                "02-Draft. Once promoted, entries are append-only and "
                "cannot be demoted. The entry must already exist in 02-Draft."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "ID of the Draft KB entry to promote (e.g. medical-research-draft-some-title)",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID for audit trail",
                        "default": "",
                    },
                },
                "required": ["entry_id"],
            },
        ),
        Tool(
            name="demote_kb_wiki",
            description=(
                "Demote a 03-Wiki entry back to 02-Draft (director-only backdoor). "
                "Content is preserved: the file moves to 02-Draft with a "
                "demoted_at marker; the original promotion provenance is kept. "
                "The actor must be whitelisted in AUTOINFO_DIRECTOR_ACTORS "
                "(default 'director') or the call is refused with DIRECTOR_ONLY."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "ID of the 03-Wiki entry to demote",
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Acting director (must be whitelisted in AUTOINFO_DIRECTOR_ACTORS)",
                    },
                },
                "required": ["entry_id", "actor"],
            },
        ),
        Tool(
            name="force_promote",
            description=(
                "Force-promote a 02-Draft entry to 03-Wiki, skipping the "
                "admission gate (director-only backdoor). Records "
                "promotion_source: director. The actor must be whitelisted "
                "in AUTOINFO_DIRECTOR_ACTORS (default 'director') or the "
                "call is refused with DIRECTOR_ONLY."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "ID of the 02-Draft entry to force-promote",
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Acting director (must be whitelisted in AUTOINFO_DIRECTOR_ACTORS)",
                    },
                },
                "required": ["draft_id", "actor"],
            },
        ),
        Tool(
            name="promote_pending",
            description=(
                "Batch-promote all eligible 02-Draft entries for a domain "
                "(promotion sweep). Each draft is admission-checked via the "
                "curation gate (source provenance, G1/G3 thresholds, G4 "
                "factual consistency); drafts previously rejected (carrying "
                "a _failed/ marker) are skipped and never retried. "
                "Idempotent: already-promoted entries are naturally skipped. "
                "Returns a summary with promoted/rejected/failed per entry "
                "and per-entry failure reasons."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "actor": {
                        "type": "string",
                        "description": "Acting agent recorded in promoted_by (default 'agent')",
                        "default": "agent",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="reindex_kb",
            description="Rebuild SQLite FTS5 search index from disk frontmatter",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to reindex (empty = all domains)",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="create_kb_entry",
            description=(
                "Create a KB entry from scratch in 01-Raw tier. "
                "Architecture: 01-Raw is the sole entry point — "
                "all content enters the KB pipeline here. "
                "No quality gates are applied (matching REST behavior)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Target domain name (e.g. medical-research)",
                    },
                    "title": {
                        "type": "string",
                        "description": "Entry title",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text / Markdown content of the entry",
                    },
                    "source_url": {
                        "type": "string",
                        "description": "Source URL (mandatory provenance)",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Source type (e.g. web, api, manual)",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of topic tags",
                    },
                    "author": {
                        "type": "string",
                        "description": "Optional author name",
                    },
                },
                "required": [
                    "domain",
                    "title",
                    "content",
                    "source_url",
                    "source_type",
                ],
            },
        ),
        # -- Output (5) ---------------------------------------------------
        Tool(
            name="list_output_templates",
            description="List available output templates for a domain. Each template includes access_level (free/premium/enterprise) for freemium gating (G15).",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (optional)",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": (
                            "Optional end-user ID for tier-based filtering. "
                            "When set, only templates accessible to this user "
                            "are returned. When omitted, all templates are returned."
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="generate_digest",
            description=(
                "Compile a periodic digest summarizing recent KB entries for "
                "a domain over a chosen period (daily, weekly, monthly). "
                "Default markdown; also html, json, agent (JSON-LD), and "
                "audio MP3. Optional recipients emails the digest directly; "
                "max_items, include_stale, and target_audience tailor "
                "content; product supports magazine-digest."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "period": {
                        "type": "string",
                        "description": "Digest period: daily, weekly, monthly",
                        "default": "weekly",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Output format: markdown, html, json, agent, audio, epub, "
                            "audiobook"
                        ),
                        "default": "markdown",
                        "enum": [
                            "markdown", "html", "json", "agent", "audio",
                            "video", "epub", "audiobook",
                        ],
                    },
                    "custom_instructions": {
                        "type": "string",
                        "description": "Optional custom instructions to tailor the output content",
                        "default": "",
                    },
                    "target_audience": {
                        "type": "string",
                        "description": "Optional target audience description to tailor output tone and depth (e.g. \"healthcare professionals\", \"general public\")",
                        "default": "",
                    },
                    "include_stale": {
                        "type": "boolean",
                        "description": "Include stale entries in the digest (default: false). When false, entries below the domain freshness threshold are excluded.",
                        "default": False,
                    },
                    "recipients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of email recipient addresses for direct digest delivery",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID for preference-based personalization. When provided, stored preferences (target_audience, format, max_items) are auto-loaded from the user's profile.",
                        "default": "",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Optional maximum number of KB entries to include (default: 0 = use built-in limit of 200). Can be auto-set from stored user preferences when user_id is provided.",
                        "default": 0,
                    },
                    "product": {
                        "type": "string",
                        "description": (
                            "Optional product name from the PRODUCT_TEMPLATES registry "
                            "(e.g. magazine-digest, premium-briefing, enterprise-briefing, "
                            "column). When provided, the digest is rendered through that "
                            "product's template family (e.g. magazine-digest.md.j2). "
                            "Valid products: digest, report, tutorial, presentation, "
                            "premium-briefing, column, magazine-digest, enterprise-briefing."
                        ),
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When true, write the generated artifact to outputs/<domain>/ and return its persisted_path in the envelope (default: false).",
                        "default": False,
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="generate_report",
            description=(
                "Produce a deep structured report analyzing collected items "
                "for a domain over a period (daily, weekly, monthly). "
                "Default markdown; also json, html, agent (JSON-LD), audio, "
                "epub, audiobook, video. report_type switches industry, "
                "competitive, trend, daily-briefing, or column templates; "
                "product supports premium-briefing and enterprise-briefing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Output format: markdown, json, html, agent, audio, epub, "
                            "audiobook"
                        ),
                        "default": "markdown",
                        "enum": [
                            "markdown", "json", "html", "agent", "audio",
                            "video", "epub", "audiobook",
                        ],
                    },
                    "period": {
                        "type": "string",
                        "description": "Report period: daily, weekly, monthly",
                        "default": "monthly",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "custom_instructions": {
                        "type": "string",
                        "description": "Optional custom instructions to tailor the output content",
                        "default": "",
                    },
                    "target_audience": {
                        "type": "string",
                        "description": "Optional target audience description to tailor output tone and depth (e.g. \"healthcare professionals\", \"general public\")",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional end-user ID for freemium access gating (G15). Premium reports are blocked for non-subscribers.",
                        "default": "",
                    },
                    "report_type": {
                        "type": "string",
                        "description": "Report type: standard (default), industry, competitive, trend, daily-briefing, column",
                        "default": "standard",
                        "enum": ["standard", "industry", "competitive", "trend", "daily-briefing", "column"],
                    },
                    "product": {
                        "type": "string",
                        "description": (
                            "Optional product name from the PRODUCT_TEMPLATES registry "
                            "(e.g. premium-briefing, enterprise-briefing, column). When "
                            "provided, the report is rendered through that product's "
                            "template family. Valid products: digest, report, tutorial, "
                            "presentation, premium-briefing, column, magazine-digest, "
                            "enterprise-briefing."
                        ),
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When true, write the generated artifact to outputs/<domain>/ and return its persisted_path in the envelope (default: false).",
                        "default": False,
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="generate_cross_domain_report",
            description=(
                "Generate a synthesis report across multiple domains, "
                "connecting findings and identifying cross-domain trends. "
                "Returns markdown by default; also supports json, html, "
                "agent (JSON-LD), audio, epub, and audiobook.  "
                "At least 2 domains are required.  Period: daily, weekly, monthly."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domain names to synthesize across (e.g. [\"medical-research\", \"ai-commercial\"]). At least 2 required.",
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Output format: markdown, json, html, agent, audio, epub, "
                            "audiobook"
                        ),
                        "default": "markdown",
                        "enum": ["markdown", "json", "html", "agent", "audio", "video", "epub", "audiobook"],
                    },
                    "period": {
                        "type": "string",
                        "description": "Report period: daily, weekly, monthly",
                        "default": "monthly",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "target_audience": {
                        "type": "string",
                        "description": "Optional target audience description to tailor output tone and depth (e.g. \"healthcare professionals\", \"general public\")",
                        "default": "",
                    },
                    "report_type": {
                        "type": "string",
                        "description": "Report type: standard (default), industry, competitive, trend, daily-briefing, column",
                        "default": "standard",
                        "enum": ["standard", "industry", "competitive", "trend", "daily-briefing", "column"],
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID for preference-based personalization. When provided, stored content_preference (raw_only / processed_only / both) is auto-loaded and KB entries are tier-filtered accordingly.",
                        "default": "",
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When true, write the generated artifact to outputs/<domain>/ and return its persisted_path in the envelope (default: false).",
                        "default": False,
                    },
                },
                "required": ["domains"],
            },
        ),
        Tool(
            name="generate_tutorial",
            description=(
                "Create a step-by-step tutorial teaching a topic for a "
                "domain, with learning goals and hands-on steps. "
                "Default markdown; also agent (JSON-LD). topic filters the "
                "content; custom_instructions shape the teaching style."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional topic filter",
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: 'markdown' (default), 'agent' (JSON-LD for LLM re-consumption)",
                        "default": "markdown",
                        "enum": ["markdown", "agent"],
                    },
                    "custom_instructions": {
                        "type": "string",
                        "description": "Optional custom instructions to tailor the output content",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID for preference-based personalization. When provided, stored content_preference (raw_only / processed_only / both) is auto-loaded and KB entries are tier-filtered accordingly.",
                        "default": "",
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When true, write the generated artifact to outputs/<domain>/ and return its persisted_path in the envelope (default: false).",
                        "default": False,
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="generate_presentation",
            description=(
                "Build a slide deck for a topic within a domain (slides 3-30). "
                "Outputs markdown (Reveal.js flavored), standalone html, "
                "mkslides build, or agent (JSON-LD). Pass custom_instructions "
                "for visual narrative and pacing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Presentation topic",
                    },
                    "slides": {
                        "type": "integer",
                        "description": "Desired number of slides (3-30)",
                        "default": 10,
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Output format: 'markdown' (default, Reveal.js-flavoured "
                            "Markdown), 'html' (standalone Reveal.js HTML5 via CDN), "
                            "'mkslides' (mkslides build with HTML fallback), "
                            "or 'agent' (JSON-LD for LLM re-consumption)."
                        ),
                        "default": "markdown",
                        "enum": ["markdown", "html", "mkslides", "agent"],
                    },
                    "custom_instructions": {
                        "type": "string",
                        "description": "Optional custom instructions to tailor the output content",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID for preference-based personalization. When provided, stored content_preference (raw_only / processed_only / both) is auto-loaded and KB entries are tier-filtered accordingly.",
                        "default": "",
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "When true, write the generated artifact to outputs/<domain>/ and return its persisted_path in the envelope (default: false).",
                        "default": False,
                    },
                },
                "required": ["domain", "topic"],
            },
        ),
        Tool(
            name="localize_content",
            description=(
                "Translate a KB entry or raw text into a target language. "
                "Two modes: (1) pass content_id to translate a stored KB "
                "entry (stores the translation as a new file), or (2) pass "
                "content + source_lang for direct translation without storage. "
                "Preserves medical terminology, drug names, procedures, "
                "statistics, and citations. Optionally accepts a domain "
                "name to inject terminology guardrails."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {
                        "type": "string",
                        "description": (
                            "KB entry ID to translate.  The entry must "
                            "exist in the KB store."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Raw text to translate directly (no KB lookup). "
                            "Requires source_lang."
                        ),
                    },
                    "source_lang": {
                        "type": "string",
                        "description": (
                            "Source language code (e.g. en, zh).  Required "
                            "for direct content mode; auto-detected from "
                            "the KB entry for content_id mode."
                        ),
                    },
                    "target_lang": {
                        "type": "string",
                        "description": (
                            "Target language code (e.g. zh, fr, ja)."
                        ),
                    },
                    "domain": {
                        "type": "string",
                        "description": (
                            "Domain name (e.g. medical-research). When "
                            "provided, loads domain-specific terminology "
                            "guardrails from knowledge/<domain>/_terminology.yaml. "
                            "In content_id mode, inferred from KB entry "
                            "if not specified."
                        ),
                    },
                },
                "required": ["target_lang"],
            },
        ),
        # -- Export / Import (2) -----------------------------------------------
        Tool(
            name="export_kb",
            description=(
                "Export knowledge base entries to specified format. "
                "Supports markdown, json, sqlite, csv, pdf, graphml, rss, agent, bundle, sitemap, epub, mobi formats."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Output format: markdown, json, sqlite, csv, pdf, graphml, rss, "
                            "agent, bundle (ZIP with PDF+JSON+MD+YAML), epub, mobi"
                        ),
                        "default": "markdown",
                        "enum": [
                            "markdown", "json", "sqlite", "csv", "pdf",
                            "graphml", "rss", "agent", "bundle", "sitemap",
                            "epub", "mobi",
                        ],
                    },
                    "scope": {
                        "type": "string",
                        "description": "Export scope: domain (all entries), entry (specific IDs), collection (collection-scoped)",
                        "default": "domain",
                        "enum": ["entry", "collection", "domain"],
                    },
                    "entry_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific entry IDs to export (used when scope is 'entry')",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional explicit output path. Auto-generated when omitted.",
                    },
                    "base_url": {
                        "type": "string",
                        "description": (
                            "Site base URL required when format is 'sitemap' "
                            "(e.g. https://your-site.example); ignored for other formats"
                        ),
                    },
                },
                "required": ["domain", "format"],
            },
        ),
        Tool(
            name="import_kb",
            description=(
                "Import entries or source suggestions into the KB. "
                "Supports 4 formats: markdown (YAML+Markdown frontmatter), "
                "json, csv, and opml. "
                "All entry imports land in 01-Raw (KB pipeline). "
                "OPML returns source suggestions only — does NOT auto-add sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Target domain name (e.g. medical-research)",
                    },
                    "format": {
                        "type": "string",
                        "description": "Import format: markdown (YAML+Markdown), json, csv, opml",
                        "enum": ["markdown", "json", "csv", "opml"],
                    },
                    "data": {
                        "type": "string",
                        "description": (
                            "Raw content string to import. "
                            "For markdown: YAML frontmatter (--- delimited) + Markdown body. "
                            "For json: JSON array or single object with title, source_url, content. "
                            "For csv: CSV with header row (title, source_url, content required). "
                            "For opml: OPML XML with <outline> elements."
                        ),
                    },
                },
                "required": ["domain", "format", "data"],
            },
        ),
        # -- Email (1) --------------------------------------------------------
        Tool(
            name="send_email_digest",
            description=(
                "Generate and send a digest via SMTP email. "
                "Only sends when email is enabled in config "
                "(email.enabled: true). Requires email.smtp_host, "
                "email.from_addr, and email.to_addrs to be configured."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to generate digest for (e.g. medical-research)",
                    },
                    "period": {
                        "type": "string",
                        "description": "Digest period: daily, weekly, monthly",
                        "default": "weekly",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "user_id": {
                        "type": "string",
                        "description": (
                            "Optional end-user ID. When provided, the digest "
                            "honors the user's stored content_preference "
                            "(e.g. raw_only / processed_only / both). "
                            "Empty by default (no preference lookup)."
                        ),
                        "default": "",
                    },
                },
                "required": ["domain"],
            },
        ),
        # -- Email Config (1) --------------------------------------------------
        Tool(
            name="email_config",
            description=(
                "View or update email SMTP configuration. "
                "Get current settings, set SMTP host/port/credentials, "
                "enable/disable email, or send a test email."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "smtp_server": {
                        "type": "string",
                        "description": "SMTP server hostname",
                        "default": "",
                    },
                    "smtp_port": {
                        "type": "integer",
                        "description": "SMTP server port",
                        "default": 0,
                    },
                    "username": {
                        "type": "string",
                        "description": "SMTP username",
                        "default": "",
                    },
                    "password": {
                        "type": "string",
                        "description": "SMTP password",
                        "default": "",
                    },
                    "enable": {
                        "type": "boolean",
                        "description": "Enable email sending",
                        "default": False,
                    },
                    "disable": {
                        "type": "boolean",
                        "description": "Disable email sending",
                        "default": False,
                    },
                    "test": {
                        "type": "boolean",
                        "description": "Send a test email using current config",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        # -- Custom Extraction (2) -----------------------------------------
        Tool(
            name="extract_fields",
            description=(
                "On-demand re-extraction with a custom schema. "
                "Retrieves the KB entry, runs LLM extraction with the "
                "given field names, and returns the result "
                "(does NOT persist)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {
                        "type": "string",
                        "description": "KB entry ID to re-extract",
                    },
                    "schema": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Custom field names to extract "
                            "(e.g. methodology, findings)"
                        ),
                    },
                },
                "required": ["content_id", "schema"],
            },
        ),
        Tool(
            name="get_extraction",
            description=(
                "Return the extracted fields stored for a KB entry. "
                "Reads the Markdown frontmatter to retrieve "
                "``extracted_fields``."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {
                        "type": "string",
                        "description": "KB entry ID",
                    },
                },
                "required": ["content_id"],
            },
        ),
        # -- Schedule Management (4) ----------------------------------------
        Tool(
            name="list_schedules",
            description=(
                "List all scheduled collection jobs that fetch sources on a "
                "cron cadence, showing job id and enabled state. Use to "
                "review or remove collection automation."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="add_schedule",
            description="Add a new collection or digest schedule with a cron expression",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique schedule name",
                    },
                    "expression": {
                        "type": "string",
                        "description": (
                            "Cron expression (e.g. '0 2 * * *' for daily at 2 AM)"
                        ),
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domain to collect or generate digest for",
                    },
                    "schedule_type": {
                        "type": "string",
                        "description": "Schedule type: collection or digest",
                        "default": "collection",
                    },
                    "recipients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Email recipients (required for digest type)",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Digest format: html or markdown",
                        "default": "html",
                    },
                },
                "required": ["name", "expression", "domain"],
            },
        ),
        Tool(
            name="remove_schedule",
            description="Remove a collection schedule by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Schedule name to remove",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to confirm this destructive operation",
                        "default": False,
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["name", "actor"],
            },
        ),
        Tool(
            name="run_schedules",
            description="Run due schedules now (checks cron expressions against last_run)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "If true, report which schedules would run "
                            "without executing"
                        ),
                        "default": False,
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Optional single schedule name to run "
                            "(runs all due if omitted)"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_schedule_status",
            description="Get status of all schedules or a specific one (last_run, next_run, is_active, domain)",
            inputSchema={
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "string",
                        "description": (
                            "Optional schedule name to get status for. "
                            "When omitted, returns status for all schedules."
                        ),
                    },
                },
                "required": [],
            },
        ),
        # -- Delivery Schedule Management (3) ---------------------------------
        Tool(
            name="add_delivery_schedule",
            description="Add a new delivery schedule for periodic output generation + channel delivery",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to generate output for",
                    },
                    "cron_expression": {
                        "type": "string",
                        "description": "Cron expression (e.g. '0 8 * * 1' for Monday 8 AM)",
                    },
                    "output_type": {
                        "type": "string",
                        "description": "Output type: digest or report",
                        "default": "digest",
                        "enum": ["digest", "report"],
                    },
                    "channel": {
                        "type": "string",
                        "description": "Delivery channel: email, webhook, rest, telegram, discord, etc.",
                        "default": "email",
                    },
                    "recipients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recipient identifiers (emails, webhook URLs, etc.)",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Output format: markdown, html, json, agent, audio, pdf",
                        "default": "html",
                    },
                    "period": {
                        "type": "string",
                        "description": "Content period: daily, weekly, monthly",
                        "default": "weekly",
                        "enum": ["daily", "weekly", "monthly"],
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional end-user ID whose stored content_preference (raw_only / processed_only / both) is applied when generating the scheduled output. Empty = no preference lookup.",
                        "default": "",
                    },
                },
                "required": ["domain", "cron_expression"],
            },
        ),
        Tool(
            name="list_delivery_schedules",
            description=(
                "List all delivery schedules that generate and push outputs "
                "(digests, reports) to end-user channels on a cron cadence. "
                "Shows output type, channel, and next run time per schedule."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="remove_delivery_schedule",
            description="Remove a delivery schedule by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "string",
                        "description": "Schedule ID to remove",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to confirm this destructive operation",
                        "default": False,
                    },
                },
                "required": ["schedule_id"],
            },
        ),
        # -- Q&A (1) -------------------------------------------------------
        Tool(
            name="query_collected",
            description=(
                "Search collected content via FTS5 and synthesise an answer "
                "using the LLM.  Provide a natural-language question; the "
                "tool returns an answer with source citations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language question to answer",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domain to scope the search to (e.g. medical-research)",
                    },
                    "content_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional explicit list of entry IDs to use "
                            "instead of FTS5 search"
                        ),
                    },
                },
                "required": ["query", "domain"],
            },
        ),
        # -- Source Health / Feedback (2) ----------------------------------
        Tool(
            name="get_source_health",
            description=(
                "Return health status for a single source. "
                "Status values: healthy, degraded, error, paused, unknown."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source identifier in 'domain:name' format (e.g. 'medical-research:pubmed'). Returned by add_source in the response.",
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="rate_item",
            description=(
                "Store a user rating and optional feedback for a "
                "collected item or KB entry.  Rating must be 1-5."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Collected item or KB entry ID to rate",
                    },
                    "rating": {
                        "type": "integer",
                        "description": "Rating value 1 (worst) to 5 (best)",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Optional free-text feedback",
                    },
                },
                "required": ["item_id", "rating"],
            },
        ),
        # -- Audit (1) -------------------------------------------------------
        Tool(
            name="query_audit_log",
            description=(
                "Query the immutable audit log with optional filters. "
                "All filters are optional and combined with AND logic. "
                "Results returned newest-first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "actor": {
                        "type": "string",
                        "description": "Filter by actor name",
                    },
                    "action": {
                        "type": "string",
                        "description": "Filter by action name",
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Filter by resource type",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "ISO-8601 lower bound on timestamp",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "ISO-8601 upper bound on timestamp",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return (default 100)",
                        "default": 100,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (default 0)",
                        "default": 0,
                    },
                },
                "required": [],
            },
        ),
        # -- CEFR Classification (1) ----------------------------------------
        Tool(
            name="classify_cefr",
            description=(
                "Classify text into a CEFR level (A1-C2) using the "
                "configured LLM. Supports English (en), Chinese (zh), "
                "and Japanese (ja)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to classify",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code: en, zh, or ja",
                        "default": "en",
                        "enum": ["en", "zh", "ja"],
                    },
                },
                "required": ["text"],
            },
        ),
        # -- CEFR Batch (1) ---------------------------------------------------
        Tool(
            name="cefr_batch",
            description=(
                "Batch classify multiple texts into CEFR levels (A1-C2). "
                "Each text is classified independently. Per-text errors are "
                "included with an error key in the results array."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "texts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Texts to classify (non-empty)",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code: en, zh, or ja",
                        "default": "en",
                        "enum": ["en", "zh", "ja"],
                    },
                },
                "required": ["texts"],
            },
        ),
        # -- Project / Batch / Config (6) ------------------------------------
        Tool(
            name="list_projects",
            description=(
                "List all configured projects with domain count, source/topic "
                "summaries, and LLM provider info."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Optional status filter (active, archived)",
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_project_assets",
            description=(
                "Return project asset paths and sizes — collections, knowledge "
                "directories, database, exports, and config directory."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Optional asset type filter (collections, knowledge, database, exports, config)",
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="archive_project",
            description=(
                "Archive the current project. Refuses unless at least one "
                "entry has been promoted to 03-Wiki.  Archive itself is a "
                "human-only operation; this tool reports whether prerequisites "
                "are met."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for archiving",
                        "default": "",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be True to confirm this destructive operation",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="batch_run",
            description=(
                "Execute collection and processing in sequence for a domain. "
                "Runs collect_sources then process_collection automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional topic / keyword filter for collection",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items per source",
                        "default": 20,
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional LLM model override for processing",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="get_feeds",
            description=(
                "Return a paginated feed of KB entries for a domain. "
                "Supports optional filters by topic tag, source type, "
                "and collected-at date.  Output format: JSON (default) or RSS 2.0 XML."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to query (required)",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional filter by topic tag",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Optional filter by source type (e.g. rss, api)",
                    },
                    "since": {
                        "type": "string",
                        "description": "Optional ISO date filter (collected_at >=)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items to return (1-200)",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip for pagination",
                        "default": 0,
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: 'json' (paginated JSON envelope) or 'rss' (RSS 2.0 XML feed)",
                        "default": "json",
                        "enum": ["json", "rss"],
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="list_active_collections",
            description=(
                "List currently active or in-progress collection runs. "
                "Optionally filter by domain."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. medical-research)",
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_config",
            description=(
                "Return the current configuration as a structured dict. "
                "Supports optional 'section' filter: project, llm, domains. "
                "Returns the full config when section is omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Optional config section: project, llm, domains",
                        "default": "",
                        "enum": ["project", "llm", "domains"],
                    },
                },
                "required": [],
            },
        ),
        # -- Webhooks (2) ----------------------------------------------------
        Tool(
            name="set_domain_webhooks",
            description=(
                "Set webhook URLs for a domain. All newly collected items "
                "will be POSTed to these URLs as JSON. Replaces any existing "
                "URLs. Fire-and-forget with retry (3 attempts)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "webhook_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of webhook URLs (must start with "
                            "http:// or https://)"
                        ),
                    },
                },
                "required": ["domain", "webhook_urls"],
            },
        ),
        Tool(
            name="get_domain_webhooks",
            description="Return the configured webhook URLs for a domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        # -- Gate Config (2) ------------------------------------------------
        Tool(
            name="get_gate_config",
            description="Return gate configuration (quality or delivery) for a domain — checks domain-level config, falls back to global defaults",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "gate": {
                        "type": "string",
                        "description": "Gate name (e.g. G0, G1, D1, D2, CurationGate)",
                    },
                },
                "required": ["domain", "gate"],
            },
        ),
        Tool(
            name="set_gate_config",
            description="Update gate configuration for a domain. Provide gate-specific fields (action, threshold, retries for quality gates; enabled, action_on_failure for delivery gates)",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "gate": {
                        "type": "string",
                        "description": "Gate name (e.g. G0, G1, D1, D2, CurationGate)",
                    },
                    "config": {
                        "type": "object",
                        "description": "Gate configuration dict (e.g. {\"action\": \"block\", \"retries\": 3, \"retry_models\": [...]} for quality gates; {\"enabled\": true, \"action_on_failure\": \"flag\"} for delivery gates)",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "Action on failure: block, retry, flag, skip, archive",
                            },
                            "retries": {
                                "type": "integer",
                                "description": "Number of retry attempts (quality gates)",
                            },
                            "retry_models": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Fallback model chain (quality gates)",
                            },
                            "threshold": {
                                "type": "number",
                                "description": "Score threshold 0-100 (quality gates)",
                            },
                            "enabled": {
                                "type": "boolean",
                                "description": "Whether enabled (delivery gates; CurationGate G4)",
                            },
                            "action_on_failure": {
                                "type": "string",
                                "description": "Action on failure: block, fallback, flag (delivery gates)",
                            },
                        },
                    },
                },
                "required": ["domain", "gate", "config"],
            },
        ),
        # -- Product (2) ----------------------------------------------------
        Tool(
            name="get_product",
            description=(
                "Return configuration of a single product (RAW or PROCESSED) "
                "for a domain by product type — channels, formats, and "
                "platform limits derived from domain config. Inspect a "
                "specific product before generating or delivering."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "product_type": {
                        "type": "string",
                        "description": "Product type: RAW or PROCESSED",
                        "enum": ["RAW", "PROCESSED"],
                    },
                },
                "required": ["domain", "product_type"],
            },
        ),
        Tool(
            name="list_products",
            description=(
                "Enumerate all products (RAW and PROCESSED) configured for a "
                "domain with their product id, channels, and formats. Use "
                "for an overview before choosing one to generate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        # -- End User Delivery (1) -------------------------------------------
        Tool(
            name="send_to_enduser",
            description="Dispatch a product to an end user through a delivery channel. Looks up the user profile, resolves the channel, and dispatches via the DeliveryChannel framework",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "User ID of the recipient (must exist in the user store)",
                    },
                    "product_type": {
                        "type": "string",
                        "description": "Product type: raw or processed",
                        "enum": ["raw", "processed"],
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Product identifier (e.g. medical-research-processed)",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Delivery channel name (e.g. smtp, webhook, discord). Falls back to user's preferences, then smtp",
                    },
                },
                "required": ["end_user_id", "product_type", "product_id"],
            },
        ),
        # -- Alert Rules (3) ------------------------------------------------
        Tool(
            name="get_alert_rules",
            description="List alert rules for a domain. Returns all rules filtered by domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="add_alert_rule",
            description="Create a new threshold-based alert rule for a domain. Triggers notifications when collected items match the configured keywords and relevance threshold, or when a configured source is missing its required API key (kind=source_credential_missing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. medical-research)",
                    },
                    "topic_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords to match against item title and content. Empty list matches all items",
                        "default": [],
                    },
                    "relevance_threshold": {
                        "type": "number",
                        "description": "Minimum relevance score (0-100) to trigger",
                        "default": 0.0,
                    },
                    "channel": {
                        "type": "string",
                        "description": "Delivery channel: email or webhook",
                        "default": "email",
                        "enum": ["email", "webhook"],
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether the rule is active",
                        "default": True,
                    },
                    "kind": {
                        "type": "string",
                        "description": "Rule kind: content (item matching) or source_credential_missing (fires when a configured source requires an API key absent from the operator environment)",
                        "default": "content",
                        "enum": ["content", "source_credential_missing"],
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="remove_alert_rule",
            description="Remove an alert rule by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Alert rule ID to remove (returned by add_alert_rule in the response)",
                    },
                },
                "required": ["id"],
            },
        ),
        # -- Budget Thresholds (2) -------------------------------------------
        Tool(
            name="get_budget_thresholds",
            description=(
                "Return current budget thresholds with spend status. "
                "Compares total spend from CostMeter against each threshold "
                "and reports breach status (ok/warning/critical)."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="set_budget_thresholds",
            description=(
                "Update budget thresholds in the project config. "
                "Thresholds are percentage values (0-100+) at which budget "
                "alerts fire. Persisted to .autoinfo/config.yaml."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "thresholds": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Percentage thresholds (e.g. [30.0, 60.0, 90.0, 100.0])",
                    },
                    "auto_remediation_enabled": {
                        "type": "boolean",
                        "description": "Whether auto-remediation is active (V2 — not yet implemented)",
                        "default": False,
                    },
                    "alert_webhook": {
                        "type": "string",
                        "description": "Optional webhook URL for budget alert notifications",
                        "default": "",
                    },
                },
                "required": ["thresholds"],
            },
        ),
        # -- Cost Dashboard & Allocation (2) ----------------------------------
        Tool(
            name="cost_dashboard",
            description=(
                "Show cost dashboard — totals by domain, daily trend, "
                "top models/sources, and budget status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Time period: today, week, month, all",
                        "default": "week",
                        "enum": ["today", "week", "month", "all"],
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="cost_allocation",
            description=(
                "Show cost allocation broken down by domain and user. "
                "Supports filtering by domain, user_id, and time period."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (empty = all)",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user ID filter (empty = all)",
                        "default": "",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period: all, today, week, month",
                        "default": "all",
                        "enum": ["all", "today", "week", "month"],
                    },
                },
                "required": [],
            },
        ),
        # -- Init (1) --------------------------------------------------------
        Tool(
            name="init_project",
            description=(
                "Initialize AutoInfo project skeleton (creates .autoinfo/ "
                "directory, config, demo domain). Idempotent — safe to call "
                "when already initialized."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Demo domain name (e.g. medical-research)",
                        "enum": _list_demo_domains(),
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Optional human-friendly project name",
                        "default": "",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview what would be created without writing files",
                        "default": False,
                    },
                    "llm_provider": {
                        "type": "string",
                        "description": "Override default LLM provider (e.g. \"openai\")",
                        "default": "",
                    },
                    "llm_model": {
                        "type": "string",
                        "description": "Override default LLM model (e.g. \"gpt-4\")",
                        "default": "",
                    },
                    "llm_base_url": {
                        "type": "string",
                        "description": "Override default LLM base URL (e.g. \"http://localhost:11434/v1\")",
                        "default": "",
                    },
                },
                "required": ["domain"],
            },
        ),
        Tool(
            name="configure_llm",
            description=(
                "Update LLM configuration in .autoinfo/config.yaml. "
                "Incremental: only updates fields explicitly provided. "
                "api_key is stored as env var reference (${AUTOINFO_LLM_API_KEY}), "
                "never the raw key. No-op when no parameters are supplied. "
                "llm_fallback configures the fallback chain (None = unchanged, "
                "[] = clear, entries merge by (provider, model) identity); "
                "llm_tasks configures per-task model routing (None = unchanged, "
                "{} = clear; judgment tasks still resolve to the release-pinned "
                "JUDGMENT_MODEL at runtime)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "LLM provider name (e.g. \"openai\", \"openrouter\")",
                        "default": "",
                    },
                    "model": {
                        "type": "string",
                        "description": "LLM model name (e.g. \"gpt-4\", \"deepseek/deepseek-chat\")",
                        "default": "",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key — stored as env var reference (${AUTOINFO_LLM_API_KEY}), not raw key. Set AUTOINFO_LLM_API_KEY env var separately.",
                        "default": "",
                    },
                    "base_url": {
                        "type": "string",
                        "description": "LLM base URL (e.g. \"http://localhost:11434/v1\")",
                        "default": "",
                    },
                    "llm_fallback": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "model": {
                                    "type": "string",
                                    "description": "Fallback model name (required)",
                                },
                                "provider": {
                                    "type": "string",
                                    "description": "Fallback provider; empty inherits the primary provider",
                                },
                                "base_url": {
                                    "type": "string",
                                    "description": "Fallback base URL",
                                },
                                "api_key": {
                                    "type": "string",
                                    "description": "Fallback API key (env var reference ${...}); empty inherits the primary key",
                                },
                                "json_mode": {
                                    "type": "boolean",
                                    "description": "Force JSON response format for this fallback",
                                },
                                "reasoning_model": {
                                    "type": "boolean",
                                    "description": "Mark this fallback as a reasoning model",
                                },
                                "timeout": {
                                    "type": "number",
                                    "description": "Per-call timeout in seconds",
                                },
                            },
                            "required": ["model"],
                        },
                        "description": "Fallback chain entries. None = leave unchanged; [] = clear; entries merge by (provider, model) identity.",
                    },
                    "llm_tasks": {
                        "type": "object",
                        "description": "Per-task LLM overrides keyed by task name (model/provider/max_tokens). None = leave unchanged; {} = clear. Judgment tasks (g4_factual/g5_translation/llm_judge) still resolve to the release-pinned JUDGMENT_MODEL at runtime.",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "model": {
                                    "type": "string",
                                    "description": "Task model override",
                                },
                                "provider": {
                                    "type": "string",
                                    "description": "Task provider override",
                                },
                                "max_tokens": {
                                    "type": "integer",
                                    "description": "Task max_tokens override",
                                },
                            },
                        },
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="test_llm_connection",
            description=(
                "Test LLM connectivity with the current or overridden "
                "configuration. Makes a minimal completion call and reports "
                "connectable, tested_model, latency_ms, and config_source "
                "(params when any override is supplied, else config). "
                "Pass api_key explicitly to test a key without persisting it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "LLM provider override (e.g. \"openai\", \"openrouter\")",
                        "default": "",
                    },
                    "model": {
                        "type": "string",
                        "description": "LLM model override (e.g. \"gpt-4\", \"deepseek/deepseek-chat\")",
                        "default": "",
                    },
                    "base_url": {
                        "type": "string",
                        "description": "LLM base URL override (e.g. \"http://localhost:11434/v1\")",
                        "default": "",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key override for this test only (never persisted). Empty inherits the config/env key.",
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        # -- Metrics (2) --------------------------------------------------
        Tool(
            name="get_metrics",
            description="Get Prometheus-format metrics for monitoring",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_prometheus_metrics",
            description="Get raw Prometheus exposition-format metrics (same format as /metrics HTTP endpoint)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        # -- Soft-delete & GDPR (4) -------------------------------------------
        Tool(
            name="soft_delete_entry",
            description="Mark an entry as deleted (soft-delete) or permanently remove it (hard-delete). Set purge=True for permanent deletion. 03-Wiki entries are append-only: only an actor whitelisted in AUTOINFO_DIRECTOR_ACTORS (default 'director') can delete them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "purge": {
                        "type": "boolean",
                        "description": "If False (default), performs soft-delete (mark as deleted). If True, permanently deletes the entry from index, FTS5, and disk.",
                        "default": False,
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Acting actor. 03-Wiki entries require an actor whitelisted in AUTOINFO_DIRECTOR_ACTORS",
                    },
                },
                "required": ["entry_id", "actor"],
            },
        ),
        Tool(
            name="mark_stale",
            description="Mark a knowledge base entry as stale (demoted in search, excluded from digests)",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                },
                "required": ["entry_id"],
            },
        ),
        Tool(
            name="restore_entry",
            description="Restore a soft-deleted entry",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["entry_id", "actor"],
            },
        ),
        Tool(
            name="export_user_data",
            description="Export all data for a user (GDPR compliance)",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="delete_user_data",
            description="Delete all user data (GDPR right to be forgotten)",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "purge": {"type": "boolean"},
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["user_id", "actor"],
            },
        ),
        # -- Trace (1) -------------------------------------------------------
        Tool(
            name="trace_item",
            description="Trace the full pipeline history for a trace_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_id": {
                        "type": "string",
                        "description": "UUID trace identifier from collection",
                    },
                },
                "required": ["trace_id"],
            },
        ),
        # -- Merge (1) -------------------------------------------------------
        Tool(
            name="merge_items",
            description="Merge multiple KB entries into one (cross-collection dedup)",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of KB entry IDs to merge",
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Merge strategy: 'simple' or 'title_first'",
                        "default": "simple",
                    },
                },
                "required": ["item_ids"],
            },
        ),
        # -- Find Similar (1) -------------------------------------------------
        Tool(
            name="find_similar_items",
            description="Find items similar to a query using text similarity",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "threshold": {
                        "type": "number",
                        "description": "Minimum similarity ratio (0.0–1.0)",
                        "default": 0.8,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        # -- KB Freshness (1) --------------------------------------------------
        Tool(
            name="calculate_freshness_score",
            description="Calculate freshness score (0.0–1.0) for a KB entry based on age and TTL",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "KB entry ID to calculate freshness for",
                    },
                    "ttl_days": {
                        "type": "integer",
                        "description": "Time-to-live in days (default: 90)",
                        "default": 90,
                    },
                },
                "required": ["entry_id"],
            },
        ),
        # -- Portal / End-user Self-service (2) ------------------------------
        Tool(
            name="get_enduser_history",
            description="Return delivery history for an end-user. Mirrors the portal CLI history command — looks up subscriptions and queries the delivery log for delivery attempts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        Tool(
            name="get_enduser_products",
            description="Return products (subscriptions) for an end-user. Mirrors the portal CLI subscription lookup — returns plan, status, dates, and auto-renew flag.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        # -- Delivery Log (1) ------------------------------------------------
        Tool(
            name="query_delivery_log",
            description="Query the delivery log with optional filters (subscription_id, status, date range)",
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Filter by subscription ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of entries to return (default: 50)",
                        "default": 50,
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by delivery status (e.g. success, failed, retrying)",
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Filter by last_attempt >= this ISO-8601 timestamp",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Filter by last_attempt <= this ISO-8601 timestamp",
                    },
                },
                "required": [],
            },
        ),
        # -- Delivery Monitor (2) -------------------------------------------
        Tool(
            name="list_active_deliveries",
            description="List all active/in-progress deliveries (status: retrying, pending, in_progress)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_delivery_log",
            description="Query delivery history with optional filters (status, domain) and pagination",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by delivery status (e.g. success, failed, retrying, pending)",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Filter by domain name (delivery_log does not store domain yet — accepted for API compatibility)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return (default: 20)",
                        "default": 20,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (default: 0)",
                        "default": 0,
                    },
                },
                "required": [],
            },
        ),
        # -- End-User Trial (2) ------------------------------------------------
        Tool(
            name="activate_trial",
            description="Activate or reset trial period for an end-user. Sets trial_started_at to now with configurable duration (default 14 days). Also sets user status to trial if not active.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Trial duration in days (default: 14)",
                        "default": 14,
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        Tool(
            name="check_trial_expiry",
            description="Check trial status for an end-user. Returns days_remaining (int), status (expired/active/no_trial), trial_started_at, and trial_days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        # -- End-User Preferences (2) ------------------------------------------
        Tool(
            name="update_preferences",
            description="Merge preferences into stored preferences for an end-user. Accepts a dict of keys to update (format, delivery_channel, timezone, max_items). Deep-merges with existing preferences.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                    "preferences": {
                        "type": "object",
                        "description": "Dict of preference keys to set (e.g. {format: markdown, delivery_channel: email, timezone: UTC, max_items: 50})",
                    },
                },
                "required": ["end_user_id", "preferences"],
            },
        ),
        Tool(
            name="get_preferences",
            description="Return stored preferences for an end-user. Returns dict with user_id and preferences object.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        # -- End-User CRUD (5) -------------------------------------------------
        Tool(
            name="enduser_create",
            description="Create a new end-user profile. Requires user_id and name. Optional: email, delivery_prefs (JSON dict), status (trial/active/suspended/cancelled), tier (free/pro/enterprise).",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Unique user identifier (e.g. alice)",
                    },
                    "name": {
                        "type": "string",
                        "description": "User display name",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address",
                        "default": "",
                    },
                    "delivery_prefs": {
                        "type": "object",
                        "description": "Delivery preferences as a JSON object (e.g. {channel: email})",
                    },
                    "status": {
                        "type": "string",
                        "description": "Account status (trial/active/suspended/cancelled)",
                        "default": "trial",
                        "enum": ["trial", "active", "suspended", "cancelled"],
                    },
                    "tier": {
                        "type": "string",
                        "description": "Account tier (free/pro/enterprise)",
                        "default": "free",
                        "enum": ["free", "pro", "enterprise"],
                    },
                },
                "required": ["user_id", "name"],
            },
        ),
        Tool(
            name="enduser_get",
            description="Get an end-user profile by user ID. Returns the full profile dict or an error if not found.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier to look up (e.g. alice)",
                    },
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="enduser_update",
            description="Update an end-user profile (partial update). Only provided fields are changed. Returns the updated profile.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier to update (e.g. alice)",
                    },
                    "name": {
                        "type": "string",
                        "description": "New display name (optional)",
                    },
                    "email": {
                        "type": "string",
                        "description": "New email address (optional)",
                    },
                    "delivery_prefs": {
                        "type": "object",
                        "description": "New delivery preferences JSON object (optional)",
                    },
                    "status": {
                        "type": "string",
                        "description": "New account status (optional)",
                    },
                    "tier": {
                        "type": "string",
                        "description": "New account tier (optional)",
                    },
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="enduser_delete",
            description="Delete an end-user profile and associated subscriptions. Returns success or not-found error.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier to delete (e.g. alice)",
                    },
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="enduser_list",
            description="List all end-user profiles. Returns items array and count.",
            inputSchema={"type": "object", "properties": {}},
        ),
        # -- Stripe Billing (2) ------------------------------------------------
        Tool(
            name="create_checkout_session",
            description="Create a Stripe Checkout Session for a product (subscription or one-time payment). Creates (or looks up) a Stripe Customer for the end-user and generates a checkout URL. Works with stripe-mock (localhost:12111) or live/test Stripe keys via STRIPE_API_KEY env var.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Stripe Price ID (e.g. price_xxx for subscriptions; name for payment mode)",
                    },
                    "end_user_id": {
                        "type": "string",
                        "description": "AutoInfo end-user ID (e.g. alice)",
                    },
                    "mode": {
                        "type": "string",
                        "description": "Checkout mode: 'subscription' (default) or 'payment' (one-time purchase)",
                        "default": "subscription",
                        "enum": ["subscription", "payment"],
                    },
                    "article_id": {
                        "type": "string",
                        "description": "Article identifier for single-purchase metadata (payment mode only)",
                        "default": "",
                    },
                    "success_url": {
                        "type": "string",
                        "description": "Redirect URL after successful payment (default: http://localhost:8741/success)",
                        "default": "http://localhost:8741/success",
                    },
                    "cancel_url": {
                        "type": "string",
                        "description": "Redirect URL on cancellation (default: http://localhost:8741/cancel)",
                        "default": "http://localhost:8741/cancel",
                    },
                    "email": {
                        "type": "string",
                        "description": "Customer email (optional)",
                        "default": "",
                    },
                    "name": {
                        "type": "string",
                        "description": "Customer display name (optional)",
                        "default": "",
                    },
                },
                "required": ["product_id", "end_user_id"],
            },
        ),
        Tool(
            name="get_subscription_status",
            description="Check Stripe subscription status for an end-user. Looks up the Stripe subscription via stored stripe_subscription_id and returns status, plan, and customer info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "AutoInfo end-user ID (e.g. alice). Optional — defaults to config multi_user.default_user_id, then \"default\".",
                        "default": "",
                    },
                },
            },
        ),
        Tool(
            name="get_billing_summary",
            description="Return combined billing summary — usage data and subscription status for an end-user. Combines CostMeter usage data (LLM tokens, storage, API calls) with Stripe subscription info in a single read-only result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "AutoInfo end-user ID (e.g. alice). Optional — defaults to config multi_user.default_user_id, then \"default\".",
                        "default": "",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period: today, week, month, all (default: month)",
                        "default": "month",
                    },
                },
            },
        ),
        # -- End-user Usage & Invoice (G16 — 2) ------------------------------
        Tool(
            name="get_enduser_usage",
            description="Return billable usage for an end-user over a period. Queries CostMeter and maps internal tracking to customer-billable units: LLM tokens → llm_units, storage items → storage_mb, API calls → api_call_units.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period: today, week, month, all (default: month)",
                        "default": "month",
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        Tool(
            name="get_enduser_invoice",
            description="Return an invoice-like summary with usage and estimated cost for an end-user. Computes billable units via CostMeter and applies configurable unit pricing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "end_user_id": {
                        "type": "string",
                        "description": "End-user ID (e.g. alice)",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period: today, week, month, all (default: month)",
                        "default": "month",
                    },
                },
                "required": ["end_user_id"],
            },
        ),
        # -- Clean Cache (1) --------------------------------------------------
        Tool(
            name="clean_cache",
            description=(
                "Remove cached artifacts and temporary files. "
                "Supports selective cleanup (collections, outputs) or "
                "--everything mode. dry_run shows what would be deleted "
                "without actually deleting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "collections": {
                        "type": "boolean",
                        "description": "Remove cached collections/ contents",
                        "default": False,
                    },
                    "outputs": {
                        "type": "boolean",
                        "description": "Remove outputs/ contents",
                        "default": False,
                    },
                    "everything": {
                        "type": "boolean",
                        "description": "Remove ALL cached data (collections + outputs + knowledge + DB)",
                        "default": False,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Show what would be deleted without deleting",
                        "default": False,
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Required. Must be True when everything=True — this deletes the entire knowledge/ directory and database",
                    },
                    "actor": {
                        "type": "string",
                        "description": "Required. Actor requesting this destructive operation (must be passed explicitly)",
                    },
                },
                "required": ["actor", "confirm"],
            },
        ),
        # -- Channel Health (1) -------------------------------------------
        Tool(
            name="get_channel_health",
            description=(
                "Check health of delivery channels. "
                "Return health status (healthy, latency_ms, error) for one or all channels. "
                "When channel_name is omitted, returns health for all 13 channels."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": (
                            "Specific channel to check (smtp, webhook, rest_api, file_export, "
                            "discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, push). "
                            "When omitted, all channels are checked."
                        ),
                    },
                },
                "required": [],
            },
        ),
        # -- Agent Callbacks (3) --------------------------------------------
        Tool(
            name="set_agent_callback",
            description=(
                "Register an agent callback URL for push events "
                "(new_digest, new_report, new_tutorial). "
                "Returns a callback_id for later removal. "
                "NOT shared with set_domain_webhooks — this is a separate system."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_url": {
                        "type": "string",
                        "description": "Callback URL (must start with http:// or https://)",
                    },
                    "events": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Events to subscribe to: new_digest, new_report, new_tutorial",
                    },
                },
                "required": ["agent_url", "events"],
            },
        ),
        Tool(
            name="list_agent_callbacks",
            description="List all registered agent callbacks with their URLs and subscribed events",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="remove_agent_callback",
            description="Remove a registered agent callback by its callback_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "callback_id": {
                        "type": "string",
                        "description": "Callback ID returned by set_agent_callback",
                    },
                },
                "required": ["callback_id"],
            },
        ),
        # -- Recommendation (1) ---------------------------------------------
        Tool(
            name="recommend_content",
            description="Return content-based recommendations for a user query",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User identifier",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search/recommendation query",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domain filter (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                },
                "required": ["user_id"],
            },
        ),
        # -- Simplification (1) ----------------------------------------------
        Tool(
            name="simplify_content",
            description=(
                "Simplify text content to a target CEFR reading level using LLM. "
                "Classifies original level, rewrites at target level, and verifies "
                "the result. Returns simplified text, original/simplified CEFR levels, "
                "and a verified flag. Target levels: A1, A2, B1, B2, C1."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Text content to simplify",
                    },
                    "target_level": {
                        "type": "string",
                        "description": "Target CEFR level: A1, A2, B1, B2, or C1",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code: en, zh, or ja (default: en)",
                    },
                },
                "required": ["content", "target_level"],
            },
        ),

        # -- Validation (2) -------------------------------------------------
        Tool(
            name="list_validation_scenarios",
            description=(
                "List available Agent-native validation scenarios "
                "(MCP tool-call scenarios; SKIP when requires_env vars missing)"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="run_validation_scenario",
            description=(
                "Execute an Agent-native validation scenario in-process: "
                "each step calls an MCP tool and asserts on the "
                "{success, data} envelope. Returns per-step passed/failed/skipped status"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scenario": {
                        "type": "string",
                        "description": "Scenario name from list_validation_scenarios",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "1-based step indices to run only a subset",
                    },
                    "save_results": {
                        "type": "boolean",
                        "description": (
                            "Persist this run's result to validation-runs/<date>/"
                            " (scenarios.json + latest.txt) for cross-run regression"
                        ),
                    },
                    "timeout": {
                        "type": "number",
                        "default": 180.0,
                        "description": (
                            "Per-step timeout in seconds (default 180). "
                            "Each step may run for at most this long."
                        ),
                    },
                },
                "required": ["scenario"],
            },
        ),
    ]

# -- LLM-required tools (16) ------------------------------------------------
# Tools in this set require LLM configuration to function.  When the LLM
# is not configured (no api_key), call_tool will block them with a clear
# error response before dispatching to the handler.
_LLM_REQUIRED_TOOLS: frozenset[str] = frozenset({
    "suggest_keywords",
    "classify_cefr",
    "cefr_batch",
    "extract_fields",
    "generate_digest",
    "generate_report",
    "generate_cross_domain_report",
    "generate_tutorial",
    "generate_presentation",
    "localize_content",
    "query_collected",
    "process_collection",
    "recommend_content",
    "simplify_content",
    "promote_kb_draft",
    "batch_run",
})


def _is_llm_configured() -> bool:
    """Return ``True`` if an LLM API key has been configured.

    Mirrors the logic in ``_handle_diagnose_system`` — reads the config
    and checks both the config field and the ``AUTOINFO_LLM_API_KEY``
    environment variable.  Fails closed (``False``) on error.
    """
    try:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            return bool(
                config.llm.api_key
                or os.environ.get("AUTOINFO_LLM_API_KEY")
            )
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Dispatch-level audit hook (M1T15)
#
# Every MCP tool call is recorded in the append-only audit log with the
# whitelisted fields ONLY: actor, action, tool, resource, result_code,
# trace_id.  Tool inputs and response data are NEVER written here — the
# privacy grep (`grep -rn "api_key\|arguments\|payload" server.py |
# grep -i audit`) must stay empty.
# ---------------------------------------------------------------------------

# Explicit exclusion list (volume control): high-frequency read probes.
#  * ``health_check``  — entry-point health probe
#  * ``get_tool_count`` — static introspection
#  * every ``list_*`` tool (list_domains, list_sources, list_topics,
#    list_summaries, ...) — read-only discovery probes that fire in tight
#    agent loops and would otherwise dominate the log.
# All other tools (mutations + parameterised reads) are audited.
_AUDIT_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "health_check",
    "get_tool_count",
})

_AUDIT_WRITE_FAILURES = 0  # in-process counter surfaced via pipeline logs


def _audit_excluded(tool_name: str) -> bool:
    """Return ``True`` when *tool_name* is on the audit exclusion list.

    Exclusion list (documented, explicit):
      * ``health_check``
      * ``get_tool_count``
      * every tool whose name starts with ``list_``
    """
    return (
        tool_name in _AUDIT_EXCLUDED_TOOLS
        or tool_name.startswith("list_")
    )


def _current_actor() -> str:
    """Resolve a stable actor id for dispatch-level audit entries.

    Taxonomy: ``"agent:<session>"`` (interactive MCP agent client),
    ``"cli"`` (command-line driven), ``"cron"`` (scheduled job),
    ``"system"`` (internal / server-originated).

    The MCP dispatch does not carry caller identity in its handler
    signature, so the actor is taken from the ``AUTOINFO_ACTOR``
    environment variable when a launcher (cron wrapper, CLI shim) sets
    it, defaulting to ``"agent:mcp"`` for the stdio/SSE agent surface.
    """
    return os.environ.get("AUTOINFO_ACTOR") or "agent:mcp"


def _safe_resource(args: dict[str, Any]) -> str:
    """Extract a single low-sensitivity resource identifier for audit rows.

    Returns the ``domain`` (then ``topic``, then ``name``) argument when
    present, else ``""``.  Only configuration-level identifiers (domain /
    topic / entity names) are ever used — never URLs, credentials, or
    free-form content — so the audit row's resource field cannot carry
    secrets.
    """
    for key in ("domain", "topic", "name"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _audit_tool_call(tool_name: str, code: str, resource: str = "") -> None:
    """Append one dispatch-level row to the audit log (fire-and-forget).

    Writes exactly the whitelisted fields: ``actor``, ``action``,
    ``tool``, ``resource``, ``result_code``, ``trace_id`` — nothing else
    (no tool inputs, no response data).

    Best-effort by design: the write is wrapped in try/except so an audit
    failure can never fail the tool call itself; failures are logged and
    counted (``_AUDIT_WRITE_FAILURES``) instead.
    """
    global _AUDIT_WRITE_FAILURES
    if _audit_excluded(tool_name):
        return
    try:
        from autoinfo.audit import append_audit_log

        append_audit_log(
            actor=_current_actor(),
            action="tool_call",
            tool=tool_name,
            resource_id=resource,
            details={
                "result_code": code,
                "trace_id": str(uuid.uuid4()),
            },
        )
    except Exception:
        _AUDIT_WRITE_FAILURES += 1
        logger.warning(
            "Audit write failed for tool '%s' (code=%s) — call result unaffected",
            tool_name,
            code,
            exc_info=True,
        )
        from autoinfo.logging import get_pipeline_logger

        get_pipeline_logger("mcp.dispatch").warning(
            "Audit write failure",
            extra={"tool": tool_name, "result_code": code,
                   "failures": _AUDIT_WRITE_FAILURES},
        )


@app.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch tool calls to the appropriate implementation."""
    _dispatch_audit: dict[str, str] = {"code": "success"}
    result: dict[str, Any] | list[dict[str, Any]]
    try:
        # -- health_check is exempted — keep flat for the entry-point tool
        if name == "health_check":
            result = _handle_health_check()
            return [TextContent(type="text", text=json.dumps(result))]

        # -- LLM guard: block LLM-required tools when not configured ------
        if name in _LLM_REQUIRED_TOOLS and not _is_llm_configured():
            _dispatch_audit["code"] = "blocked"
            return [
                TextContent(
                    type="text",
                    text=json.dumps(error_response(
                        code=ErrorCode.LLM_NOT_CONFIGURED,
                        message="LLM is not configured. Use configure_llm() to set up your API key. See docs/dev/required-api-keys.md for the full list of API keys and environment variables.",
                        actionable=True,
                    )),
                )
            ]

        # -- Director-only backdoor guard: demote / force-promote ---------
        # Blocks non-whitelisted actors at dispatch so neither the store nor
        # the audit trail records the attempt as a real mutation.  The
        # handlers repeat the check so direct handler calls stay safe too.
        if name in ("demote_kb_wiki", "force_promote"):
            actor = arguments.get("actor") or "agent"
            if not is_director(actor):
                _dispatch_audit["code"] = "director_only"
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(error_response(
                            code=ErrorCode.DIRECTOR_ONLY,
                            message=(
                                f"actor '{actor}' not whitelisted "
                                "in AUTOINFO_DIRECTOR_ACTORS"
                            ),
                            actionable=True,
                        )),
                    )
                ]

        # -- System (2) ---------------------------------------------------
        if name == "get_tool_count":
            result = _handle_get_tool_count()
        elif name == "diagnose_system":
            result = _handle_diagnose_system()

        # -- Discovery (7) ------------------------------------------------
        elif name == "list_domains":
            result = _handle_list_domains()
        elif name == "list_available_platforms":
            result = _handle_list_available_platforms()
        elif name == "get_domain_schema":
            result = _handle_get_domain_schema(**arguments)
        elif name == "list_available_models":
            result = _handle_list_available_models()
        elif name == "get_effective_llm_config":
            result = _handle_get_effective_llm_config(**arguments)
        elif name == "activate_domain":
            result = _handle_activate_domain(**arguments)
        elif name == "deactivate_domain":
            result = _handle_deactivate_domain(**arguments)
        elif name == "add_domain":
            result = _handle_add_domain(**arguments)
        elif name == "remove_domain":
            result = _handle_remove_domain(**arguments)
        elif name == "get_domain_config":
            result = _handle_get_domain_config(**arguments)

        # -- Source Management (5) ----------------------------------------
        elif name == "add_source":
            result = _handle_add_source(**arguments)
        elif name == "add_sources":
            result = _handle_add_sources(**arguments)
        elif name == "remove_source":
            result = _handle_remove_source(**arguments)
        elif name == "test_source":
            result = _handle_test_source(**arguments)
        elif name == "list_sources":
            result = _handle_list_sources(**arguments)

        # -- Topic Management (6) -----------------------------------------
        elif name == "add_topic":
            result = _handle_add_topic(**arguments)
        elif name == "remove_topic":
            result = _handle_remove_topic(**arguments)
        elif name == "list_topics":
            result = _handle_list_topics(**arguments)
        elif name == "list_keywords":
            result = _handle_list_keywords(**arguments)
        elif name == "topic_group_add":
            result = _handle_topic_group_add(**arguments)
        elif name == "topic_group_remove":
            result = _handle_topic_group_remove(**arguments)

        # -- Keywords Management (3) --------------------------------------
        elif name == "approve_keyword":
            result = _handle_approve_keyword(**arguments)
        elif name == "reject_keyword":
            result = _handle_reject_keyword(**arguments)
        elif name == "suggest_keywords":
            result = await asyncio.to_thread(_handle_suggest_keywords, **arguments)

        # -- Collection / Processing (5) ----------------------------------
        # collect/process/batch_run are long-running sync handlers; offload
        # them so the asyncio event loop stays responsive and the progress
        # tools (get_collection_progress / get_processing_progress) keep
        # answering while a run is in flight (issue #136).
        elif name == "collect_sources":
            result = await asyncio.to_thread(_handle_collect_sources, **arguments)
        elif name == "get_collection_progress":
            result = _handle_get_collection_progress(**arguments)
        elif name == "get_collection_status":
            result = _handle_get_collection_status(**arguments)
        elif name == "process_collection":
            result = await asyncio.to_thread(_handle_process_collection, **arguments)
        elif name == "get_processing_progress":
            result = _handle_get_processing_progress(**arguments)

        # -- Knowledge Base (4) -------------------------------------------
        elif name == "list_summaries":
            result = _handle_list_summaries(**arguments)
        elif name == "get_kb_entry":
            result = _handle_get_kb_entry(**arguments)
        elif name == "search_knowledge_base":
            result = _handle_search_knowledge_base(**arguments)
        elif name == "query_knowledge_graph":
            result = _handle_query_knowledge_graph(**arguments)
        elif name == "knowledge_graph_export":
            result = _handle_knowledge_graph_export(**arguments)
        elif name == "flag_for_knowledge_base":
            result = _handle_flag_for_knowledge_base(**arguments)
        elif name == "get_summary":
            result = _handle_get_summary(**arguments)

        elif name == "link_items":
            result = _handle_link_items(**arguments)
        elif name == "get_item_relations":
            result = _handle_get_item_relations(**arguments)

        elif name == "get_entry_history":
            result = _handle_get_entry_history(**arguments)
        elif name == "restore_entry_version":
            result = _handle_restore_entry_version(**arguments)
        elif name == "compare_versions":
            result = _handle_compare_versions(**arguments)

        elif name == "get_collection_stats":
            result = _handle_get_collection_stats(**arguments)
        elif name == "get_collection_diff":
            result = _handle_get_collection_diff(**arguments)

        elif name == "get_domain_decay":
            result = _handle_get_domain_decay(**arguments)

        # -- KB: Draft tools (4) ------------------------------------------
        elif name == "create_kb_draft":
            result = _handle_create_kb_draft(**arguments)
        elif name == "reject_kb_draft":
            result = _handle_reject_kb_draft(**arguments)
        elif name == "list_kb_tier":
            result = _handle_list_kb_tier(**arguments)
        elif name == "promote_kb_draft":
            result = await asyncio.to_thread(_handle_promote_kb_draft, **arguments)
        elif name == "demote_kb_wiki":
            result = _handle_demote_kb_wiki(**arguments)
        elif name == "force_promote":
            result = _handle_force_promote(**arguments)
        elif name == "promote_pending":
            result = _handle_promote_pending(**arguments)
        elif name == "reindex_kb":
            result = _handle_reindex_kb(**arguments)
        elif name == "create_kb_entry":
            result = _handle_create_kb_entry(**arguments)

        # -- Audit (1) -------------------------------------------------------
        elif name == "query_audit_log":
            qa_kwargs = arguments
            result = _handle_query_audit_log(**qa_kwargs)

        # -- CEFR Classification (1) ----------------------------------------
        elif name == "classify_cefr":
            result = await asyncio.to_thread(_handle_classify_cefr, **arguments)
        elif name == "cefr_batch":
            result = await asyncio.to_thread(_handle_cefr_batch, **arguments)

        # -- Output (6) ---------------------------------------------------
        elif name == "list_output_templates":
            result = _handle_list_output_templates(**arguments)
        elif name == "generate_digest":
            result = await asyncio.to_thread(_handle_generate_digest, **arguments)
        elif name == "generate_report":
            result = await asyncio.to_thread(_handle_generate_report, **arguments)
        elif name == "generate_cross_domain_report":
            result = await asyncio.to_thread(_handle_generate_cross_domain_report, **arguments)
        elif name == "generate_tutorial":
            result = await asyncio.to_thread(_handle_generate_tutorial, **arguments)
        elif name == "generate_presentation":
            result = await asyncio.to_thread(_handle_generate_presentation, **arguments)
        elif name == "localize_content":
            result = await asyncio.to_thread(_handle_localize_content, **arguments)

        # -- Export / Import (2) -----------------------------------------------
        elif name == "export_kb":
            result = _handle_export_kb(**arguments)
        elif name == "import_kb":
            result = _handle_import_kb(**arguments)

        # -- Email (1) --------------------------------------------------------
        elif name == "send_email_digest":
            result = _handle_send_email_digest(**arguments)
        elif name == "email_config":
            result = _handle_email_config(**arguments)

        # -- Custom Extraction (2) ----------------------------------------
        elif name == "extract_fields":
            result = await asyncio.to_thread(_handle_extract_fields, **arguments)
        elif name == "get_extraction":
            result = _handle_get_extraction(**arguments)

        # -- Schedule Management (5) ---------------------------------------
        elif name == "list_schedules":
            result = _handle_list_schedules()
        elif name == "add_schedule":
            result = _handle_add_schedule(**arguments)
        elif name == "remove_schedule":
            result = _handle_remove_schedule(**arguments)
        elif name == "run_schedules":
            result = _handle_run_schedules(**arguments)
        elif name == "get_schedule_status":
            result = _handle_get_schedule_status(**arguments)

        # -- Delivery Schedule Management (3) --------------------------------
        elif name == "add_delivery_schedule":
            result = _handle_add_delivery_schedule(**arguments)
        elif name == "list_delivery_schedules":
            result = _handle_list_delivery_schedules()
        elif name == "remove_delivery_schedule":
            result = _handle_remove_delivery_schedule(**arguments)

        # -- Q&A (1) -------------------------------------------------------
        elif name == "query_collected":
            result = await asyncio.to_thread(_handle_query_collected, **arguments)

        # -- Source Health / Feedback (2) ----------------------------------
        elif name == "get_source_health":
            result = _handle_get_source_health(**arguments)
        elif name == "rate_item":
            result = _handle_rate_item(**arguments)

        # -- Webhooks (2) -------------------------------------------------
        elif name == "set_domain_webhooks":
            result = _handle_set_domain_webhooks(**arguments)
        elif name == "get_domain_webhooks":
            result = _handle_get_domain_webhooks(**arguments)

        # -- Init / Project / Batch / Config (8) --------------------------
        elif name == "init_project":
            result = _handle_init_project(**arguments)
        elif name == "configure_llm":
            result = _handle_configure_llm(**arguments)
        elif name == "test_llm_connection":
            result = await asyncio.to_thread(
                _handle_test_llm_connection, **arguments
            )
        elif name == "list_projects":
            result = _handle_list_projects()
        elif name == "get_project_assets":
            result = _handle_get_project_assets()
        elif name == "archive_project":
            result = _handle_archive_project(**arguments)
        elif name == "batch_run":
            result = await asyncio.to_thread(_handle_batch_run, **arguments)
        elif name == "get_feeds":
            result = _handle_get_feeds(**arguments)
        elif name == "list_active_collections":
            result = _handle_list_active_collections()
        elif name == "get_config":
            result = _handle_get_config(**arguments)

        # -- Gate Config (2) ------------------------------------------------
        elif name == "get_gate_config":
            result = _handle_get_gate_config(**arguments)
        elif name == "set_gate_config":
            result = _handle_set_gate_config(**arguments)

        # -- Product (2) ----------------------------------------------------
        elif name == "get_product":
            result = _handle_get_product(**arguments)
        elif name == "list_products":
            result = _handle_list_products(**arguments)

        # -- End User Delivery (1) -------------------------------------------
        elif name == "send_to_enduser":
            result = _handle_send_to_enduser(**arguments)

        # -- Alert Rules (3) ------------------------------------------------
        elif name == "get_alert_rules":
            result = _handle_get_alert_rules(**arguments)
        elif name == "add_alert_rule":
            result = _handle_add_alert_rule(**arguments)
        elif name == "remove_alert_rule":
            result = _handle_remove_alert_rule(**arguments)

        # -- Budget Thresholds (2) -------------------------------------------
        elif name == "get_budget_thresholds":
            result = _handle_get_budget_thresholds()
        elif name == "set_budget_thresholds":
            result = _handle_set_budget_thresholds(**arguments)
        elif name == "cost_dashboard":
            result = _handle_cost_dashboard(**arguments)
        elif name == "cost_allocation":
            result = _handle_cost_allocation(**arguments)

        # -- Metrics (2) --------------------------------------------------
        elif name == "get_metrics":
            result = _handle_get_metrics(name, arguments)
        elif name == "get_prometheus_metrics":
            result = _handle_get_prometheus_metrics(name, arguments)

        # -- Trace (1) ----------------------------------------------------
        elif name == "trace_item":
            result = _handle_trace_item(name, arguments)

        # -- Soft-delete & GDPR (4) -----------------------------------------
        elif name == "soft_delete_entry":
            result = _handle_soft_delete_entry(name, arguments)
        elif name == "mark_stale":
            result = _handle_mark_stale(name, arguments)
        elif name == "restore_entry":
            result = _handle_restore_entry(name, arguments)
        elif name == "export_user_data":
            result = _handle_export_user_data(name, arguments)
        elif name == "delete_user_data":
            result = _handle_delete_user_data(name, arguments)

        # -- Portal / End-user Self-service (2) ------------------------------
        elif name == "get_enduser_history":
            result = _handle_get_enduser_history(**arguments)
        elif name == "get_enduser_products":
            result = _handle_get_enduser_products(**arguments)

        # -- Delivery Log (1) ------------------------------------------------
        elif name == "query_delivery_log":
            result = _handle_query_delivery_log(name, arguments)

        # -- Delivery Monitor (2) ------------------------------------------
        elif name == "list_active_deliveries":
            result = _handle_list_active_deliveries()
        elif name == "get_delivery_log":
            result = _handle_get_delivery_log(**arguments)

        # -- Clean Cache (1) -------------------------------------------------
        elif name == "clean_cache":
            result = _handle_clean_cache(**arguments)

        # -- Channel Health (1) ------------------------------------------
        elif name == "get_channel_health":
            result = _handle_get_channel_health(**arguments)

        # -- Merge / Find Similar (2) ---------------------------------
        elif name == "merge_items":
            result = _handle_merge_items(**arguments)
        elif name == "find_similar_items":
            result = _handle_find_similar_items(**arguments)

        # -- KB Freshness (1) ---------------------------------------------
        elif name == "calculate_freshness_score":
            result = _handle_calculate_freshness_score(name, arguments)

        # -- End-User Trial (2) ----------------------------------------------
        elif name == "activate_trial":
            result = _handle_activate_trial(**arguments)
        elif name == "check_trial_expiry":
            result = _handle_check_trial_expiry(**arguments)

        # -- End-User Preferences (2) ----------------------------------------
        elif name == "update_preferences":
            result = _handle_update_preferences(**arguments)
        elif name == "get_preferences":
            result = _handle_get_preferences(**arguments)

        # -- End-User CRUD (5) --------------------------------------------------
        elif name == "enduser_create":
            result = _handle_enduser_create(**arguments)
        elif name == "enduser_get":
            result = _handle_enduser_get(**arguments)
        elif name == "enduser_update":
            result = _handle_enduser_update(**arguments)
        elif name == "enduser_delete":
            result = _handle_enduser_delete(**arguments)
        elif name == "enduser_list":
            result = _handle_enduser_list()

        # -- Stripe Billing (3) ------------------------------------------------
        elif name == "create_checkout_session":
            result = _handle_create_checkout_session(**arguments)
        elif name == "get_subscription_status":
            result = _handle_get_subscription_status(**arguments)
        elif name == "get_billing_summary":
            result = _handle_get_billing_summary(**arguments)

        # -- Usage-based Billing (G16 — 2) -----------------------------------
        elif name == "get_enduser_usage":
            result = _handle_get_enduser_usage(**arguments)
        elif name == "get_enduser_invoice":
            result = _handle_get_enduser_invoice(**arguments)

        # -- Agent Callbacks (3) --------------------------------------------
        elif name == "set_agent_callback":
            result = _handle_set_agent_callback(**arguments)
        elif name == "list_agent_callbacks":
            result = _handle_list_agent_callbacks()
        elif name == "remove_agent_callback":
            result = _handle_remove_agent_callback(**arguments)

        # -- Recommendation (1) --------------------------------------------
        elif name == "recommend_content":
            result = await asyncio.to_thread(_handle_recommend_content, **arguments)

        # -- Simplification (1) --------------------------------------------
        elif name == "simplify_content":
            result = await asyncio.to_thread(_handle_simplify_content, **arguments)

        # -- Validation (2) ------------------------------------------------
        elif name == "list_validation_scenarios":
            result = _handle_list_validation_scenarios()
        elif name == "run_validation_scenario":
            result = await _handle_run_validation_scenario(**arguments)

        else:
            _dispatch_audit["code"] = "unknown_tool"
            return [
                TextContent(
                    type="text",
                    text=json.dumps(error_response(
                        code=ErrorCode.UNKNOWN_TOOL,
                        message=f"Unknown tool: {name}",
                        actionable=False,
                    )),
                )
            ]

        # Wrap non-health responses in uniform envelope
        # Backward-compat: detect pre-wrapped dual-format responses
        if isinstance(result, dict) and "success" in result:
            # Already in envelope format (dual-format from handlers),
            # pass through unchanged — no re-wrapping needed.
            wrapped = result
        elif isinstance(result, dict) and "error_code" in result:
            # Legacy flat format: wrap into envelope with both
            # flat fields and nested error for backward compat.
            logger.warning(
                "Flat error response detected from tool '%s' — auto-wrapping into envelope. "
                "Migrate handler to return error_response() for consistency.",
                name,
            )
            wrapped = {
                "success": False,
                "error_code": result["error_code"],
                "message": result.get("message", ""),
                "actionable": result.get("actionable", True),
                "error": {
                    "code": result["error_code"],
                    "message": result.get("message", ""),
                    "actionable": result.get("actionable", True),
                },
            }
        else:
            wrapped = success_response(result)
        return [TextContent(type="text", text=json.dumps(wrapped))]
    except NotImplementedError:
        # Stub tools return a graceful error response using canonical envelope
        _dispatch_audit["code"] = "not_implemented"
        return [
            TextContent(
                type="text",
                text=json.dumps(error_response(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=str(arguments.get("message", "Not implemented in v0.1")),
                    actionable=True,
                )),
            )
        ]
    except TypeError as exc:
        # Missing required arguments — client-side call error, not a server bug
        _dispatch_audit["code"] = "validation_error"
        return [
            TextContent(
                type="text",
                text=json.dumps(error_response(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=str(exc),
                    actionable=True,
                )),
            )
        ]
    except Exception as exc:
        _dispatch_audit["code"] = "error"
        logger.exception("Tool '%s' failed", name)
        return _error_response(exc)
    finally:
        resource = _safe_resource(arguments)
        _audit_tool_call(name, _dispatch_audit["code"], resource)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the MCP server over stdio transport.

    Opens the stdio read/write streams and enters the server's main loop.
    The server processes incoming JSON-RPC messages until the client
    disconnects.
    """
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def run() -> None:
    """Synchronous entry point (used by ``python -m autoinfo.mcp.server``)."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
