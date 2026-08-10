from __future__ import annotations

"""Collect CLI — runs collection pipeline.

Usage::

    autoinfo collect --domain medical-research [--topic "IVF"] [--source pubmed] \\
        [--limit 20] [--dry-run] [--auto-process] [--json]
"""


import json  # noqa: E402
from typing import Any, Callable  # noqa: E402

import typer  # noqa: E402

app = typer.Typer()


@app.callback(invoke_without_command=True)
def collect(
    domain: str = typer.Option(
        None, "--domain", help="Domain to collect for (mutually exclusive with --all)",
    ),
    all_domains: bool = typer.Option(
        False, "--all", "-A", help="Collect for all active domains",
    ),
    topic: str = typer.Option("", "--topic", help="Topic / search query filter"),
    source: str = typer.Option(
        None, "--source", help="Source name filter (repeatable: --source pubmed --source rss)",
    ),
    limit: int = typer.Option(20, "--limit", min=1, help="Max items to collect per source"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without storing"),
    auto_process: bool = typer.Option(
        False, "--auto-process", help="Run processing immediately after collection",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    force_full: bool = typer.Option(
        False, "--force-full", "-f",
        help="Skip dedup/incremental logic — collect all items fresh",
    ),
) -> None:
    """Collect items from configured sources."""
    # -- Validate mutually exclusive flags ---------------------------------
    if all_domains and domain:
        typer.echo(
            "Error: Cannot use --all with --domain. Use either --all to collect "
            "for all active domains or --domain to collect for a specific domain.",
            err=True,
        )
        raise typer.Exit(code=1)

    if not all_domains and not domain:
        typer.echo(
            "Error: Either --domain or --all must be provided.",
            err=True,
        )
        raise typer.Exit(code=1)

    # -- Parse source filter -----------------------------------------------
    # The `--source` option is repeatable, single-string pass-through is fine
    # because typer collects multiple `--source` flags into a tuple → string.
    # We normalise it into a list here.
    sources = None
    if source:
        # source is a single string; split by comma or treat as single entry
        sources = [s.strip() for s in source.split(",") if s.strip()]

    try:
        from autoinfo.collect import run_collection

        # Live per-source progress lines (human-facing only). Skipped for
        # --json so the output stays pure JSON.
        progress_cb = None if json_output else _make_progress_printer()

        if all_domains:
            # -- Multi-domain collection -----------------------------------
            from autoinfo.config import get_config_path, load_config

            config_path = get_config_path()
            if config_path is None:
                typer.echo(
                    "Error: No configuration found. Run 'autoinfo init' first. See docs/dev/required-api-keys.md for API key setup.",  # noqa: E501
                    err=True,
                )
                raise typer.Exit(code=1)

            config = load_config(config_path)
            active_domains = [d.name for d in config.domains if d.active]

            if not active_domains:
                typer.echo("Error: No active domains found in configuration.", err=True)
                raise typer.Exit(code=1)

            results: list[dict[str, Any]] = []
            for dom in active_domains:
                typer.echo(f"── Collecting for domain '{dom}' ──")
                run_kwargs: dict[str, Any] = dict(
                    domain=dom,
                    topic=topic,
                    sources=sources,
                    limit=limit,
                    dry_run=dry_run,
                    progress_cb=progress_cb,
                )
                if force_full:
                    run_kwargs["force_full"] = True
                dom_result = run_collection(**run_kwargs)
                results.append(dom_result)
                if not json_output:
                    _print_human(dom_result)
                    typer.echo("")

            # Aggregate summary
            aggregated = {
                "domains": results,
                "total_domains": len(results),
                "total_found": sum(r["total_found"] for r in results),
                "total_new": sum(r["total_new"] for r in results),
                "total_duration_s": round(sum(r["duration_s"] for r in results), 3),
                "dry_run": dry_run,
            }

            if json_output:
                typer.echo(json.dumps(aggregated, ensure_ascii=False, indent=2))

            # -- Optional: auto-process (across all domains) ---------------
            if auto_process and not dry_run:
                for dom_result in results:
                    if dom_result["total_new"] > 0:
                        typer.echo(f"── Running auto-process for '{dom_result['domain']}' ──")
                        _run_auto_process(dom_result["domain"], topic)
                    else:
                        typer.echo(
                            f"No new items for '{dom_result['domain']}' — skipping auto-process."
                        )

        else:
            # -- Single-domain collection (existing behavior) --------------
            run_kwargs: dict[str, Any] = dict(
                domain=domain,
                topic=topic,
                sources=sources,
                limit=limit,
                dry_run=dry_run,
                progress_cb=progress_cb,
            )
            if force_full:
                run_kwargs["force_full"] = True
            result = run_collection(**run_kwargs)

            # -- Output ----------------------------------------------------
            if json_output:
                typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _print_human(result)

            # -- Optional: auto-process ------------------------------------
            if auto_process and not dry_run:
                if result["total_new"] > 0:
                    typer.echo("")
                    typer.echo("── Running auto-process ──")
                    _run_auto_process(domain, topic)
                else:
                    typer.echo("")
                    typer.echo("No new items — skipping auto-process.")

    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except ImportError as exc:
        typer.echo(f"Error: collect module not available: {exc}", err=True)
        raise typer.Exit(code=1)

    if dry_run:
        typer.echo("")
        typer.echo("ℹ Dry-run — no items were stored.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_progress_printer() -> Callable[[Any], None]:
    """Return a callback printing a live per-source progress line.

    Called by ``run_collection`` as each source finishes, so the human sees
    progress during the run instead of only the final summary. Uses
    ``print(..., flush=True)`` so lines appear immediately.
    """
    icons = {
        "success": "✓",
        "partial": "⚠",
        "error": "✗",
        "skipped": "–",
    }

    def _on_source_done(src_result: Any) -> None:
        icon = icons.get(src_result.status, "?")
        line = (
            f"  {icon} {src_result.source}: {src_result.items_new} new / "
            f"{src_result.items_found} found"
        )
        filtered = getattr(src_result, "items_filtered", 0) or 0
        if filtered:
            line += f" ({filtered} filtered)"
        print(f"{line} ({src_result.duration_s:.1f}s)", flush=True)

    return _on_source_done


def _print_human(result: dict[str, Any]) -> None:
    """Print a human-readable collection summary."""
    typer.echo(
        f"Collection {result['collection_id']} for domain '{result['domain']}'"
    )
    typer.echo("")

    for src in result["per_source"]:
        status_icon = {
            "success": "✓",
            "partial": "⚠",
            "error": "✗",
            "skipped": "–",
        }.get(src["status"], "?")

        line = (
            f"  {status_icon} {src['source']}: "
            f"{src['items_new']} new / {src['items_found']} found"
        )
        filtered = src.get("items_filtered", 0) or 0
        if filtered:
            line += f" ({filtered} filtered)"
        typer.echo(f"{line} ({src['duration_s']:.1f}s)")

        for err in src.get("errors", []):
            typer.echo(f"      ↳ {err.get('message', 'unknown error')}", err=True)

    typer.echo("")
    typer.echo(
        f"Total: {result['total_new']} new items from {result['total_found']} found "
        f"in {result['duration_s']:.1f}s"
    )


def _run_auto_process(domain: str, topic: str = "") -> None:
    """Call the processing pipeline after collection."""
    try:
        from autoinfo.process import run_processing

        proc_result = run_processing(domain=domain, topic=topic if topic else None)
        typer.echo(
            f"Processing: {proc_result.total_items} items → "
            f"{proc_result.passed_gates} passed G1-G3 → "
            f"{proc_result.kb_entries_created} KB entries created "
            f"({proc_result.duration_s:.1f}s)"
        )
        if proc_result.errors:
            typer.echo(
                f"  {len(proc_result.errors)} item(s) failed", err=True
            )
    except Exception as exc:
        typer.echo(f"Auto-process failed: {exc}", err=True)
