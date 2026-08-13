from __future__ import annotations

"""Knowledge Base CLI — search, list, and manage KB entries.

Usage::

    autoinfo kb search --query "IVF" --domain medical --limit 10 --offset 0
    autoinfo kb list --domain medical --tier raw
    autoinfo kb reindex --domain medical
    autoinfo kb promote --entry-id kb-001
"""


import json

import typer

app = typer.Typer(help="Knowledge base operations")


@app.command()
def search(
    query: str = typer.Option(..., "--query", help="Search query"),
    domain: str = typer.Option("", "--domain", help="Domain to search in"),
    limit: int = typer.Option(20, "--limit", min=1, help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Result offset"),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Search the knowledge base using FTS5 full-text search."""
    from autoinfo.kb import KBStore

    store = KBStore()
    result = store.search_knowledge_base(
        query=query, domain=domain, limit=limit, offset=offset
    )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command(name="list")
def list_entries(
    domain: str = typer.Option(..., "--domain", help="Domain to list entries for"),
    tier: str = typer.Option(
        "01-Raw", "--tier", help="KB tier (01-Raw, 02-Draft, 03-Wiki)"
    ),
    limit: int = typer.Option(20, "--limit", min=1, help="Max entries"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """List KB entries in a given tier."""
    from autoinfo.kb import KBStore

    store = KBStore()
    entries = store.list_kb_tier(
        domain=domain, tier=tier, limit=limit, offset=offset
    )
    typer.echo(json.dumps(entries, indent=2, ensure_ascii=False))


@app.command()
def reindex(
    domain: str = typer.Option(
        "", "--domain", help="Domain to reindex (empty = all)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Rebuild the FTS5 search index from knowledge/ files."""
    from autoinfo.kb import KBStore

    store = KBStore()
    result = store.reindex_knowledge_base(domain=domain or None)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command(name="create-draft")
def create_draft(
    raw_ids: list[str] = typer.Option(
        ..., "--raw-id", help="Raw entry ID(s) to compile into a Draft (repeatable)"
    ),
    title: str = typer.Option(..., "--title", help="Title for the new Draft entry"),
    summary: str = typer.Option("", "--summary", help="Optional summary text"),
    tags: list[str] = typer.Option(
        [], "--tag", help="Optional tag (repeatable)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Create a Draft entry from one or more Raw entries."""
    from autoinfo.kb import KBStore

    store = KBStore()
    try:
        entry = store.create_kb_draft(
            raw_ids=raw_ids, title=title, summary=summary, tags=tags
        )
        typer.echo(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="reject-draft")
def reject_draft(
    draft_id: str = typer.Argument(..., help="Entry ID of the Draft to reject"),
    reason: str = typer.Option("", "--reason", help="Rejection reason"),
    action: str = typer.Option(
        "back_to_raw", "--action", help="'back_to_raw' (default) or 'archive'"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Reject a Draft, moving it back to 01-Raw or archiving."""
    from autoinfo.kb import KBStore

    store = KBStore()
    try:
        result = store.reject_kb_draft(
            draft_id=draft_id, reason=reason, action=action
        )
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="list-tiers")
def list_tiers(
    ctx: typer.Context,
    domain: str = typer.Option(
        ..., "--domain", help="Domain to list tiers for"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """List available KB tiers with entry counts for a domain."""
    json_output = json_output or bool((ctx.obj or {}).get("json"))
    from autoinfo.kb import KBStore

    store = KBStore()
    tiers = ["01-Raw", "02-Draft", "03-Wiki"]
    tier_info = []
    for tier in tiers:
        entry_count = store.count_entries_by_tier(domain=domain, tier=tier)
        tier_info.append({
            "tier": tier,
            "description": {
                "01-Raw": "Sole entry point for collected content",
                "02-Draft": "Agent-created drafts from Raw entries",
                "03-Wiki": "Admission-gated agent-promoted curated entries (append-only)",
            }.get(tier, ""),
            "entry_count": entry_count,
        })

    if json_output:
        typer.echo(json.dumps({"items": tier_info, "count": len(tier_info)}, indent=2, ensure_ascii=False))
        return

    typer.echo(f"KB tiers for domain '{domain}':")
    typer.echo("")
    for t in tier_info:
        desc = t["description"]
        typer.echo(
            f"  {t['tier']:<12} ({t['entry_count']:>4} entries)  {desc}"
        )


@app.command(name="wiki-links")
def wiki_links(
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Scan all entries and update Linked References sections"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Rebuild [[wiki link]] cross-references across the knowledge base.

    Walks all markdown files in ``knowledge/``, scans for ``[[Title]]``
    syntax, resolves each title to a matching KB entry, and writes
    ``## Linked References`` sections with outgoing links and backlinks.
    """
    if not rebuild:
        typer.echo("Use --rebuild to scan and update wiki links.")
        raise typer.Exit(0)

    from autoinfo.kb import KBStore

    store = KBStore()
    result = store.rebuild_wiki_links()
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def decay(
    ctx: typer.Context,
    domain: str = typer.Option(
        ..., "--domain", help="Domain to compute decay metrics for"
    ),
    ttl_days: int = typer.Option(
        30, "--ttl-days", help="Days before an entry is considered stale"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Compute decay / staleness metrics for a domain.

    Shows staleness ratio, average TTL remaining, collection freshness,
    decay grade (🟢🟡🔴), and re-collection suggestions.
    """
    json_output = json_output or bool((ctx.obj or {}).get("json"))
    from autoinfo.kb import KBStore

    store = KBStore()
    result = store.get_domain_decay(domain=domain, ttl_days=ttl_days)

    if json_output:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    grade = result["decay_grade"]
    ratio = result["staleness_ratio"]
    typer.echo(f"Domain decay metrics for '{domain}':")
    typer.echo("")
    typer.echo(f"  Decay grade:         {grade}")
    typer.echo(f"  Total entries:       {result['total_entries']}")
    typer.echo(f"  Stale entries:       {result['stale_count']}")
    typer.echo(f"  Staleness ratio:     {ratio:.1%}")
    typer.echo(f"  Avg TTL remaining:   {result['avg_ttl_remaining_days']:.1f} days")
    fresh = result["collection_freshness_days"]
    if fresh is not None:
        typer.echo(f"  Collection freshness: {fresh} days ago")
    typer.echo("")
    typer.echo("  Suggestions:")
    for s in result["suggestions"]:
        typer.echo(f"    • {s}")


@app.command()
def promote(
    entry_id: str = typer.Option(
        ..., "--entry-id", help="Entry ID of the Draft to promote to 03-Wiki"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Promote a Draft entry to 03-Wiki (admission-gated agent promotion, append-only).

    The draft must pass the curation gate (source provenance, G1/G3
    thresholds, G4 factual consistency); rejected drafts stay in 02-Draft
    with a _failed/ marker written.
    """
    from autoinfo.kb import KBStore, PromotionRejected

    store = KBStore()
    try:
        result = store.promote_kb_draft(draft_id=entry_id)
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, FileNotFoundError, PromotionRejected) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="promote-pending")
def promote_pending(
    domain: str = typer.Option(
        ..., "--domain", help="Domain whose eligible 02-Draft entries to promote"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Promote all eligible Draft entries for a domain (batch sweep).

    Each 02-Draft entry is admission-checked via the curation gate;
    previously rejected entries (carrying a _failed/ marker) are skipped
    and never retried. Prints a summary with per-entry failure reasons.
    """
    config = None
    try:
        from autoinfo.config import get_config_path, load_config  # noqa: PLC0415

        cfg_path = get_config_path()
        if cfg_path is not None:
            config = load_config(cfg_path)
    except Exception:
        config = None

    from autoinfo.kb import KBStore

    store = KBStore()
    result = store.promote_pending_drafts(domain=domain, config=config, caller="sweep")

    if json_output:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    typer.echo(f"Promotion sweep for domain '{domain}':")
    typer.echo(f"  Total drafts:            {result['total']}")
    typer.echo(f"  Promoted:                {len(result['promoted'])}")
    typer.echo(f"  Rejected:                {len(result['rejected'])}")
    typer.echo(f"  Failed:                  {len(result['failed'])}")
    typer.echo(f"  Skipped (_failed/):      {len(result['skipped_failed_markers'])}")
    for p in result["promoted"]:
        typer.echo(f"    + {p['entry_id']}")
    for r in result["rejected"]:
        typer.echo(f"    - {r['entry_id']}: {', '.join(r['reasons'])}")
    for f in result["failed"]:
        typer.echo(f"    ! {f['entry_id']}: {f['error']}")


@app.command()
def history(
    ctx: typer.Context,
    entry_id: str = typer.Argument(..., help="Entry ID to show version history for"),
    show_git: bool = typer.Option(
        False, "--show-git", help="Show git commit SHAs alongside version history"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Show version history for a KB entry."""
    json_output = json_output or bool((ctx.obj or {}).get("json"))
    from autoinfo.kb import KBStore

    store = KBStore()
    versions = store.get_entry_history(entry_id=entry_id)
    if not versions:
        if json_output:
            typer.echo(json.dumps([], indent=2, ensure_ascii=False))
        else:
            typer.echo(f"No versions found for entry '{entry_id}'.")
        return

    if json_output:
        typer.echo(json.dumps(versions, indent=2, ensure_ascii=False))
        return

    for v in versions:
        line = (
            f"  v{v['version_num']}  {v['created_at']}"
            f"  {v['comment'] or ''}"
        )
        if show_git:
            sha = v.get("git_sha", "") or ""
            line += f"  git:{sha[:12] if sha else '—'}"
        typer.echo(line)


@app.command()
def recommend(
    ctx: typer.Context,
    query: str = typer.Option("", "--query", help="Recommendation query"),
    domain: str = typer.Option("", "--domain", help="Domain to recommend from"),
    limit: int = typer.Option(10, "--limit", min=1, help="Max recommendations"),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Recommend KB content using FTS5 + vector scoring.

    When no query is given, returns recent items.
    Short queries (<3 chars) fall back to recent items.
    """
    json_output = json_output or bool((ctx.obj or {}).get("json"))
    from autoinfo.recommend import ContentBasedEngine

    engine = ContentBasedEngine()
    items = engine.recommend(
        user_id="cli",
        query=query,
        domain=domain or None,
        limit=limit,
    )

    if json_output:
        result = {
            "query": query,
            "domain": domain,
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
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not items:
        typer.echo("No recommendations found.")
        return

    typer.echo(f"Recommendations (query='{query}', domain='{domain}'):")
    typer.echo("")
    for i, item in enumerate(items, 1):
        typer.echo(f"  {i:2d}. [{item.score:5.1f}] {item.title}")
        typer.echo(f"      {item.reason}")
        if item.source_url:
            typer.echo(f"      {item.source_url}")
        typer.echo("")
