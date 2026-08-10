"""KB import module — handles 4 import formats (Markdown+YAML, JSON, CSV, OPML)
and creates 01-Raw entries via ``KBStore.store_entry()``.

All imports land in 01-Raw (KB pipeline compliance). OPML imports return
source *suggestions* only — they do NOT auto-add sources.

Usage
-----
    from autoinfo.importer import import_kb

    result = import_kb(domain="medical-research", format="json", data='[{"title": ...}]')
    # -> {"domain": ..., "format": ..., "entries_imported": N, "entries_failed": N, "errors": [...]}

    result = import_kb(domain="medical-research", format="opml", data='<?xml version="1.0"?>...')
    # -> {"type": "source_list", "suggestions": [...], "action_required": true}
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import yaml

from autoinfo.kb import KBStore
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANDATORY_FIELDS_MD = frozenset({"source_url", "source_type", "source_platform"})
MANDATORY_FIELDS_JSON = frozenset({"title", "source_url", "content"})
REQUIRED_COLUMNS_CSV = frozenset({"title", "source_url", "content"})

YAML_DELIMITER = "---"

# ---------------------------------------------------------------------------
# Per-entry helper
# ---------------------------------------------------------------------------


def _build_entry(
    domain: str,
    title: str,
    content: str,
    source_url: str,
    source_type: str = "",
    source_platform: str = "",
    collected_at: str | None = None,
    language: str = "",
    tags: list[str] | None = None,
    **extra: Any,
) -> Item:
    """Build an ``Item`` suitable for ``KBStore.store_entry()``.

    Parameters
    ----------
    domain:
        Target domain name.
    title:
        Entry title.
    content:
        Body text.
    source_url:
        Original source URL.
    source_type:
        Source type (e.g. ``"api"``, ``"rss"``, ``"web"``).
    source_platform:
        Source platform name (e.g. ``"pubmed"``, ``"arxiv"``).
    collected_at:
        ISO-format datetime string.  Defaults to now if absent.
    language:
        Optional language code.
    tags:
        Optional list of tag strings.
    **extra:
        Ignored — allows passing arbitrary frontmatter fields without error.

    Returns
    -------
    Item
        Ready to pass to ``KBStore.store_entry()``.
    """
    if not collected_at:
        collected_at = datetime.now(timezone.utc).isoformat()

    entry_id = str(uuid.uuid4())

    return Item(
        id=entry_id,
        source_name=source_platform or source_type or "import",
        source_type=source_type or "import",
        source_url=source_url,
        title=title,
        content=content,
        content_type="text",
        collected_at=collected_at,
        language=language,
        domain=domain,
        topic_tags=tags or [],
        quality_tier=1,
        raw_data=extra,
    )


# ---------------------------------------------------------------------------
# Format-specific import functions
# ---------------------------------------------------------------------------


def import_markdown(domain: str, data: str) -> dict[str, Any]:
    """Import a single Markdown+YAML entry (YAML frontmatter + body).

    Expects the standard ``---`` delimited YAML frontmatter followed by
    Markdown body text.  Mandatory frontmatter fields:
    ``source_url``, ``source_type``, ``source_platform``.

    Parameters
    ----------
    domain:
        Target domain name.
    data:
        Raw Markdown string with YAML frontmatter.

    Returns
    -------
    dict
        ``{success, entry_id, error}``.
    """
    try:
        # Split on YAML delimiter
        parts = data.split(YAML_DELIMITER, 2)
        if len(parts) < 3:
            return {
                "success": False,
                "entry_id": None,
                "error": "Invalid Markdown+YAML format: expected --- frontmatter --- body",
            }

        _before, frontmatter_raw, body = parts
        frontmatter_raw = frontmatter_raw.strip()
        body = body.strip()

        if not frontmatter_raw:
            return {
                "success": False,
                "entry_id": None,
                "error": "Empty YAML frontmatter",
            }

        frontmatter: dict[str, Any] = yaml.safe_load(frontmatter_raw) or {}

        # Validate mandatory fields
        missing = MANDATORY_FIELDS_MD - set(frontmatter.keys())
        if missing:
            return {
                "success": False,
                "entry_id": None,
                "error": f"Missing mandatory frontmatter fields: {', '.join(sorted(missing))}",
            }

        title = frontmatter.get("title", "")
        if not title:
            # Fallback: use first line of body as title
            title = body.split("\n", 1)[0].strip().strip("#").strip()
            if not title:
                title = "Untitled import"

        item = _build_entry(
            domain=domain,
            title=title,
            content=body,
            source_url=frontmatter["source_url"],
            source_type=frontmatter.get("source_type", ""),
            source_platform=frontmatter.get("source_platform", ""),
            collected_at=frontmatter.get("collected_at"),
            language=frontmatter.get("language", ""),
            tags=frontmatter.get("tags"),
            **{
                k: v for k, v in frontmatter.items()
                if k not in MANDATORY_FIELDS_MD
                and k not in ("title", "language", "tags", "domain")
            },
        )

        store = KBStore(min_content_chars=50)
        entry = store.store_entry(item=item, tier="01-Raw")
        if entry is None:
            # Issue #182: content too short / rejected — surface a clean
            # failure instead of crashing on entry.entry_id.
            return {
                "success": False,
                "entry_id": None,
                "error": "entry rejected by KB store (content too short or unparseable)",
            }

        return {
            "success": True,
            "entry_id": entry.entry_id,
            "error": None,
        }

    except yaml.YAMLError as exc:
        return {
            "success": False,
            "entry_id": None,
            "error": f"YAML parse error: {exc}",
        }
    except Exception as exc:
        logger.exception("Markdown import failed")
        return {
            "success": False,
            "entry_id": None,
            "error": str(exc),
        }


def import_json(domain: str, data: str) -> dict[str, Any]:
    """Import entries from a JSON string.

    Accepts either a JSON array of objects or a single JSON object.
    Each entry must have at minimum: ``title``, ``source_url``, ``content``.

    Parameters
    ----------
    domain:
        Target domain name.
    data:
        Raw JSON string.

    Returns
    -------
    dict
        ``{entries_imported, entries_failed, errors}``.
    """
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        return {
            "entries_imported": 0,
            "entries_failed": 0,
            "errors": [f"JSON parse error: {exc}"],
        }

    # Normalise to list
    if isinstance(parsed, dict):
        entries_list = [parsed]
    elif isinstance(parsed, list):
        entries_list = parsed
    else:
        return {
            "entries_imported": 0,
            "entries_failed": 0,
            "errors": ["JSON root must be an object or array of objects"],
        }

    imported = 0
    failed = 0
    errors: list[str] = []

    for idx, entry_data in enumerate(entries_list):
        if not isinstance(entry_data, dict):
            failed += 1
            errors.append(f"[{idx}] Entry is not a JSON object")
            continue

        # Validate mandatory fields
        missing = MANDATORY_FIELDS_JSON - set(entry_data.keys())
        if missing:
            failed += 1
            errors.append(
                f"[{idx}] Missing mandatory fields: {', '.join(sorted(missing))}"
            )
            continue

        try:
            source_type = entry_data.get("source_type", "")
            source_platform = entry_data.get("source_platform", "")

            item = _build_entry(
                domain=domain,
                title=entry_data["title"],
                content=entry_data["content"],
                source_url=entry_data["source_url"],
                source_type=source_type,
                source_platform=source_platform,
                collected_at=entry_data.get("collected_at"),
                language=entry_data.get("language", ""),
                tags=entry_data.get("tags"),
                **{
                    k: v for k, v in entry_data.items()
                    if k not in MANDATORY_FIELDS_JSON
                    and k not in ("language", "tags")
                },
            )

            store = KBStore(min_content_chars=50)
            entry = store.store_entry(item=item, tier="01-Raw")
            if entry is None:
                # Issue #182: rejected (content too short) — count as failed
                failed += 1
                continue
            imported += 1
        except Exception as exc:
            failed += 1
            errors.append(f"[{idx}] {exc}")

    return {
        "entries_imported": imported,
        "entries_failed": failed,
        "errors": errors,
    }


def import_csv(domain: str, data: str) -> dict[str, Any]:
    """Import entries from a CSV string.

    The first row is treated as a header.  Required columns:
    ``title``, ``source_url``, ``content``.
    Optional columns map to other ``Item`` fields (``source_type``,
    ``source_platform``, ``language``, ``tags``, etc.).

    Parameters
    ----------
    domain:
        Target domain name.
    data:
        Raw CSV string.

    Returns
    -------
    dict
        ``{entries_imported, entries_failed, errors}``.
    """
    try:
        reader = csv.DictReader(StringIO(data))
    except Exception as exc:
        return {
            "entries_imported": 0,
            "entries_failed": 0,
            "errors": [f"CSV parse error: {exc}"],
        }

    # Validate that required columns exist
    if not reader.fieldnames:
        return {
            "entries_imported": 0,
            "entries_failed": 0,
            "errors": ["CSV has no header row"],
        }

    header_set = set(reader.fieldnames)
    missing_cols = REQUIRED_COLUMNS_CSV - header_set
    if missing_cols:
        return {
            "entries_imported": 0,
            "entries_failed": 0,
            "errors": [
                f"Missing required CSV columns: {', '.join(sorted(missing_cols))}. "
                f"Found columns: {', '.join(reader.fieldnames)}"
            ],
        }

    imported = 0
    failed = 0
    errors: list[str] = []

    for row_idx, row in enumerate(reader, start=1):
        try:
            # Parse tags from comma-separated string if present
            tags_raw = row.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

            item = _build_entry(
                domain=domain,
                title=row["title"],
                content=row["content"],
                source_url=row["source_url"],
                source_type=row.get("source_type", ""),
                source_platform=row.get("source_platform", ""),
                collected_at=row.get("collected_at"),
                language=row.get("language", ""),
                tags=tags,
            )

            store = KBStore(min_content_chars=50)
            entry = store.store_entry(item=item, tier="01-Raw")
            if entry is None:
                # Issue #182: rejected (content too short) — count as failed
                failed += 1
                continue
            imported += 1
        except Exception as exc:
            failed += 1
            errors.append(f"[Row {row_idx}] {exc}")

    return {
        "entries_imported": imported,
        "entries_failed": failed,
        "errors": errors,
    }


def import_opml(domain: str, data: str) -> dict[str, Any]:
    """Parse an OPML outline and return source suggestions.

    This function does **not** auto-add sources.  It returns a structured
    list of suggestions for the agent (or human) to review and act upon.

    Parameters
    ----------
    domain:
        Target domain name (for context only).
    data:
        Raw OPML XML string.

    Returns
    -------
    dict
        ``{type: "source_list", suggestions: [{name, url, type}], action_required: true}``.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return {
            "type": "source_list",
            "suggestions": [],
            "action_required": True,
            "error": f"XML parse error: {exc}",
        }

    suggestions: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # OPML <outline> elements can be nested; walk recursively
    def _walk_outlines(parent: ET.Element) -> None:
        for elem in parent.iter("outline"):
            # Extract attributes
            name = (
                elem.get("text")
                or elem.get("title")
                or elem.get("label")
                or ""
            )
            url = (
                elem.get("xmlUrl")
                or elem.get("url")
                or elem.get("htmlUrl")
                or ""
            )
            feed_type = elem.get("type", "rss")

            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            suggestions.append({
                "name": name,
                "url": url,
                "type": feed_type,
            })

    _walk_outlines(root)

    return {
        "type": "source_list",
        "suggestions": suggestions,
        "action_required": True,
        "count": len(suggestions),
    }


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

_IMPORT_FORMATS = frozenset({"markdown", "json", "csv", "opml"})


def import_kb(domain: str, format: str, data: str) -> dict[str, Any]:
    """Unified KB import dispatch.

    Parameters
    ----------
    domain:
        Target domain name.
    format:
        Import format: ``"markdown"``, ``"json"``, ``"csv"``, or ``"opml"``.
    data:
        Raw content string to import.

    Returns
    -------
    dict
        For ``markdown`` / ``json`` / ``csv``::
            ``{domain, format, entries_imported, entries_failed, errors}``

        For ``opml``::
            ``{type: "source_list", suggestions, action_required}``

    Raises
    ------
    ValueError
        If *format* is not one of the supported values.
    """
    if format not in _IMPORT_FORMATS:
        raise ValueError(
            f"Unsupported import format '{format}'. "
            f"Must be one of: {', '.join(sorted(_IMPORT_FORMATS))}"
        )

    if format == "opml":
        result = import_opml(domain=domain, data=data)
        result["domain"] = domain
        result["format"] = format
        return result

    if format == "markdown":
        # Single entry
        entry_result = import_markdown(domain=domain, data=data)
        if entry_result["success"]:
            return {
                "domain": domain,
                "format": format,
                "entries_imported": 1,
                "entries_failed": 0,
                "errors": [],
                "entry_id": entry_result["entry_id"],
            }
        else:
            return {
                "domain": domain,
                "format": format,
                "entries_imported": 0,
                "entries_failed": 1,
                "errors": [entry_result["error"]],
            }

    if format == "json":
        json_result = import_json(domain=domain, data=data)
        json_result["domain"] = domain
        json_result["format"] = format
        # Ensure errors key exists
        json_result.setdefault("errors", [])
        return json_result

    if format == "csv":
        csv_result = import_csv(domain=domain, data=data)
        csv_result["domain"] = domain
        csv_result["format"] = format
        csv_result.setdefault("errors", [])
        return csv_result

    # Should not reach here
    return {
        "domain": domain,
        "format": format,
        "entries_imported": 0,
        "entries_failed": 0,
        "errors": [f"Unhandled format: {format}"],
    }
