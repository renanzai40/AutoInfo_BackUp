"""REST API routes — CRUD + search endpoints for the knowledge base.

All routes are mounted under ``/api/v1`` in ``server.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from autoinfo.kb import KBStore
from autoinfo.mcp.errors import ErrorCode
from autoinfo.models import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KBStore singleton (lazy-init)
# ---------------------------------------------------------------------------

_store: KBStore | None = None


def _get_store() -> KBStore:
    global _store
    if _store is None:
        _store = KBStore()
    return _store


# ---------------------------------------------------------------------------
# Domain validation
# ---------------------------------------------------------------------------


def _known_domains() -> set[str]:
    """Return the set of known domain names (config + filesystem fallback)."""
    domains: set[str] = set()

    # From config
    try:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if config_path and config_path.is_file():
            config = load_config(config_path)
            for d in config.domains:
                domains.add(d.name)
    except Exception:
        pass

    # From filesystem (fallback)
    from pathlib import Path as _Path

    kb_dir = _Path("knowledge")
    if kb_dir.is_dir():
        for entry in kb_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                domains.add(entry.name)

    return domains


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class EntryCreate(BaseModel):
    """Request body for ``POST /entries``."""

    title: str = Field(..., min_length=1, description="Entry title")
    content: str = Field("", description="Entry body text")
    domain: str = Field("default", description="Domain namespace")
    tier: str = Field("01-Raw", description="KB pipeline tier")
    source_url: str = Field("", description="Original source URL")
    source_type: str = Field("api", description="Source type (rss, api, web)")
    source_platform: str = Field("api", description="Source platform name")
    tags: list[str] = Field(default_factory=list, description="Topic tags")
    language: str = Field("", description="Content language code")


class EntryResponse(BaseModel):
    """Response body for a single entry."""

    entry_id: str
    title: str
    domain: str
    tier: str
    source_url: str
    source_type: str
    source_platform: str
    collected_at: str
    summary: str
    tags: list[str]
    quality_tier: int
    relevance_score: float
    dedup_status: str
    file_path: str
    content: str = ""
    language: str = ""
    cefr: str = ""
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error payload."""

    detail: str
    error_code: ErrorCode | str = "unknown"


class SearchQuery(BaseModel):
    """Query parameters for the search endpoint."""

    q: str = Field(..., description="Search query string")
    mode: str = Field("fts5", pattern=r"^(fts5|hybrid|vector)$")
    domain: str = Field("", description="Optional domain filter")
    limit: int = Field(20, ge=1, le=200)
    offset: int = Field(0, ge=0)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["entries"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _entry_to_response(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw entry dict from the index into a response dict.

    Handles deserialising the ``tags`` JSON string into a list.
    """
    tags_raw = entry.get("tags") or []
    if isinstance(tags_raw, str):
        import json
        try:
            tags = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags = [tags_raw] if tags_raw else []
    else:
        tags = list(tags_raw) if tags_raw else []

    custom_fields_raw = entry.get("custom_fields") or {}
    if isinstance(custom_fields_raw, str):
        import json
        try:
            custom_fields = json.loads(custom_fields_raw)
        except (json.JSONDecodeError, TypeError):
            custom_fields = {}
    elif isinstance(custom_fields_raw, dict):
        custom_fields = dict(custom_fields_raw)
    else:
        custom_fields = {}

    cefr = entry.get("cefr") or ""
    if not cefr and isinstance(custom_fields, dict):
        cefr = str(custom_fields.get("cefr", "")) or ""

    return {
        "entry_id": entry.get("entry_id", ""),
        "title": entry.get("title", ""),
        "domain": entry.get("domain", ""),
        "tier": entry.get("tier", "01-Raw"),
        "source_url": entry.get("source_url", ""),
        "source_type": entry.get("source_type", ""),
        "source_platform": entry.get("source_platform", ""),
        "collected_at": entry.get("collected_at", ""),
        "summary": entry.get("summary", ""),
        "tags": tags,
        "quality_tier": entry.get("quality_tier", 1),
        "relevance_score": entry.get("relevance_score", 0.0),
        "dedup_status": entry.get("dedup_status", "unique"),
        "file_path": entry.get("file_path", ""),
        "content": entry.get("content", ""),
        "language": entry.get("language", ""),
        "cefr": cefr,
        "custom_fields": custom_fields,
    }


# ---------------------------------------------------------------------------
# Response envelope helpers (M1 contract — mirror mcp/errors.py)
# ---------------------------------------------------------------------------


def success_envelope(data: Any) -> dict[str, Any]:
    """Build the canonical success envelope ``{success: True, data: ...}``.

    Mirrors :func:`autoinfo.mcp.errors.success_response`.  Every non-health
    REST success payload is wrapped in this envelope; error paths use the
    ``{success: False, error: {code, message, actionable}}`` counterpart
    (see ``autoinfo.api.server._error_envelope``).
    """
    return {"success": True, "data": data}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/entries", response_model=dict[str, Any])
async def list_entries(
    skip: int = Query(0, ge=0, description="Number of entries to skip"),
    limit: int = Query(20, ge=1, le=200, description="Max entries to return"),
    domain: str | None = Query(None, description="Optional domain filter"),
    tier: str | None = Query(None, description="Optional tier filter (01-Raw, 02-Draft, 03-Wiki)"),
    q: str | None = Query(None, description="Full-text search query"),
    date_from: str | None = Query(None, description="ISO date filter (collected_at >=)"),
) -> dict[str, Any]:
    """List entries with optional search, filters, and pagination."""
    store = _get_store()

    # When a search query is provided, use search_knowledge_base
    if q:
        result = store.search_knowledge_base(
            query=q,
            domain=domain or "",
            limit=limit,
            offset=skip,
            mode="fts5",
        )
        raw_entries: list[dict[str, Any]] = result.get("entries", [])
        return success_envelope([_entry_to_response(e) for e in raw_entries])

    # Otherwise, list all entries with optional filters
    raw = store.list_all_entries(
        domain=domain,
        tier=tier,
        date_from=date_from,
        limit=limit,
        offset=skip,
    )
    return success_envelope([_entry_to_response(e) for e in raw])


@router.get("/entries/{entry_id}", response_model=dict[str, Any])
async def get_entry(entry_id: str) -> dict[str, Any]:
    """Return a single entry with full content."""
    store = _get_store()
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found")
    return success_envelope(_entry_to_response(entry))


@router.post("/entries", response_model=dict[str, Any], status_code=201)
async def create_entry(body: EntryCreate) -> dict[str, Any]:
    """Create a new KB entry from the provided fields."""
    # Validate that the domain exists (skip validation for "default")
    if body.domain and body.domain != "default":
        known = _known_domains()
        if body.domain not in known:
            return JSONResponse(  # pyright: ignore[reportReturnType]
                status_code=404,
                content={
                    "success": False,
                    "error": {
                        "code": ErrorCode.DOMAIN_NOT_FOUND,
                        "message": (
                            f"Domain '{body.domain}' not found. "
                            f"Use add_domain(name='{body.domain}') to create it."
                        ),
                        "actionable": True,
                    },
                },
            )

    store = _get_store()

    # Build an Item from the request body
    item = Item(
        id=str(uuid4()),
        source_name=body.source_platform,
        source_type=body.source_type,
        source_url=body.source_url,
        title=body.title,
        content=body.content,
        domain=body.domain,
        topic_tags=body.tags[:],
        collected_at=datetime.now(timezone.utc).isoformat(),
        language=body.language,
        content_type="text",
        quality_tier=1,
    )

    try:
        entry = store.store_entry(item=item, tier=body.tier)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if entry is None:
        # Issue #182: rejected (content too short) — surface a clean error
        raise HTTPException(
            status_code=422,
            detail="entry rejected by KB store (content too short or unparseable)",
        )

    # Fetch the full entry with content to return
    full = store.get_entry(entry.entry_id) or entry.to_dict()
    return success_envelope(_entry_to_response(full))


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: str) -> None:
    """Delete an entry by its ID.

    Returns ``204 No Content`` on success.
    Raises ``404`` when the entry does not exist.
    """
    store = _get_store()
    result = store.delete_entry(entry_id)
    if not result.get("deleted"):
        raise HTTPException(
            status_code=404,
            detail=result.get("error", f"Entry '{entry_id}' not found"),
        )


@router.get("/search", response_model=dict[str, Any])
async def search_entries(
    q: str = Query(..., description="Search query string"),
    mode: str = Query("fts5", description="Search mode: fts5, hybrid, or vector"),
    domain: str = Query("", description="Optional domain filter"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    filter_tags: str | None = Query(None, description="Comma-separated tag filter"),
    filter_date_from: str | None = Query(None, description="ISO date lower bound"),
    filter_date_to: str | None = Query(None, description="ISO date upper bound"),
    filter_quality_tier_min: int | None = Query(None, ge=1, le=5),
    filter_quality_tier_max: int | None = Query(None, ge=1, le=5),
    filter_language: str | None = Query(None),
) -> dict[str, Any]:
    """Full-text and hybrid search across the knowledge base.

    Supports all search modes (fts5, hybrid, vector) and the full set of
    faceted filters from the underlying FTS5 engine.
    """
    store = _get_store()

    parsed_tags: list[str] = []
    if filter_tags:
        parsed_tags = [t.strip() for t in filter_tags.split(",") if t.strip()]

    result = store.search_knowledge_base(
        query=q,
        domain=domain,
        limit=limit,
        offset=offset,
        mode=mode,
        filter_tags=parsed_tags or None,
        filter_date_from=filter_date_from,
        filter_date_to=filter_date_to,
        filter_quality_tier_min=filter_quality_tier_min,
        filter_quality_tier_max=filter_quality_tier_max,
        filter_language=filter_language,
    )

    # Normalise entries in the result
    result["entries"] = [_entry_to_response(e) for e in result.get("entries", [])]
    return success_envelope(result)


# ---------------------------------------------------------------------------
# Feed endpoint (RAW product feed)
# ---------------------------------------------------------------------------


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


@router.get("/feeds", response_model=dict[str, Any])
async def list_feeds(
    domain: str = Query(..., min_length=1, description="Domain to query (required)"),
    topic: str | None = Query(None, description="Filter by topic tag"),
    source_type: str | None = Query(None, description="Filter by source type (e.g. rss, api)"),
    since: str | None = Query(None, description="ISO date filter (collected_at >=)"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    format: str = Query("json", pattern=r"^(json|rss)$", description="Output format: json or rss"),
) -> Any:
    """Return a RAW product feed of KB entries for *domain*.

    Supports optional filtering by topic tag, source type, and collected-at
    date.  Returns paginated results with ``{items, pagination}`` envelope
    for ``format=json``, or an RSS 2.0 XML feed for ``format=rss``.
    """
    if not domain.strip():
        raise HTTPException(status_code=400, detail="domain is required")

    store = _get_store()

    # Fetch all entries for the domain — apply since filter at the DB level
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
            ET.SubElement(xml_item, "source", {"url": item["url"] or ""}).text = (
                item["source_type"] or ""
            )

        from fastapi.responses import Response
        ET.indent(rss, space="  ")
        rss_content = ET.tostring(rss, encoding="unicode", xml_declaration=True)
        return Response(content=rss_content, media_type="application/rss+xml")

    return success_envelope({
        "items": items,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "next": next_offset,
        },
    })


# ---------------------------------------------------------------------------
# Portal endpoints — end-user self-service
# ---------------------------------------------------------------------------


@router.get("/portal/preferences", response_model=dict[str, Any])
async def get_portal_preferences(
    user_id: str = Query(..., min_length=1, description="End-user ID"),
) -> dict[str, Any]:
    """Return the delivery preferences for an end-user.

    Delegates to :func:`autoinfo.user_store.get_profile` and returns the
    ``delivery_preferences`` dict together with profile metadata.
    """
    from autoinfo.user_store import get_profile as _get_profile

    profile = _get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"End-user '{user_id}' not found")

    return success_envelope({
        "user_id": profile.user_id,
        "name": profile.name,
        "email": profile.email,
        "delivery_preferences": profile.delivery_preferences or {},
        "tier": profile.tier,
        "status": profile.status,
    })


class PreferencesUpdate(BaseModel):
    """Request body for ``PUT /portal/preferences``."""

    delivery_preferences: dict[str, Any] = Field(
        default_factory=dict, description="Delivery preferences key-value map"
    )
    email: str | None = Field(None, description="Optional new email address")


@router.put("/portal/preferences", response_model=dict[str, Any])
async def update_portal_preferences(
    user_id: str = Query(..., min_length=1, description="End-user ID"),
    body: PreferencesUpdate = Body(...),  # noqa: N803 — FastAPI parameter
) -> dict[str, Any]:
    """Update delivery preferences (and optionally email) for an end-user.

    Accepts partial updates — only the fields provided in the request body
    are changed on the stored profile.
    """
    from autoinfo.user_store import get_profile as _get_profile
    from autoinfo.user_store import update_profile as _update_profile

    # Verify the user exists first
    existing = _get_profile(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"End-user '{user_id}' not found")

    kwargs: dict[str, Any] = {}
    if body.delivery_preferences:
        kwargs["delivery_prefs"] = body.delivery_preferences
    if body.email is not None:
        kwargs["email"] = body.email

    updated = _update_profile(user_id=user_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update profile")

    return success_envelope({
        "user_id": updated.user_id,
        "name": updated.name,
        "email": updated.email,
        "delivery_preferences": updated.delivery_preferences or {},
        "tier": updated.tier,
        "status": updated.status,
    })


@router.get("/portal/delivery-history", response_model=dict[str, Any])
async def get_portal_delivery_history(
    user_id: str = Query(..., min_length=1, description="End-user ID"),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    channel: str | None = Query(None, description="Optional channel filter (e.g. smtp, webhook)"),
    date_from: str | None = Query(None, description="ISO date lower bound (last_attempt >=)"),
    date_to: str | None = Query(None, description="ISO date upper bound (last_attempt <=)"),
) -> dict[str, Any]:
    """Return delivery history for an end-user.

    Fetches the user's subscriptions and then queries the append-only
    delivery log for matching entries.  Results are ordered newest-first.
    """
    from autoinfo.delivery_log import query_delivery_log as _query_log
    from autoinfo.user_store import get_profile as _get_profile
    from autoinfo.user_store import list_subscriptions as _list_subs

    # Verify user exists
    profile = _get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"End-user '{user_id}' not found")

    # Collect subscription IDs for this user
    subscriptions = _list_subs(user_id=user_id)
    sub_ids = [s.subscription_id for s in subscriptions if s.subscription_id]

    if not sub_ids:
        return success_envelope({
            "user_id": user_id,
            "subscriptions": [],
            "entries": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        })

    # Query the delivery log for each subscription
    all_entries: list[dict[str, Any]] = []
    for sid in sub_ids:
        raw = _query_log(
            subscription_id=sid,
            channel=channel,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=0,
        )
        for entry in raw:
            all_entries.append(entry.to_dict())

    # Sort by last_attempt DESC
    all_entries.sort(key=lambda e: e.get("last_attempt", ""), reverse=True)

    total = len(all_entries)

    # Apply pagination slice
    page = all_entries[offset: offset + limit]

    return success_envelope({
        "user_id": user_id,
        "subscriptions": [s.to_dict() for s in subscriptions],
        "entries": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    })
