"""Process CLI — LLM extraction and quality gates pipeline.

Usage::

    autoinfo process --domain medical-research [--model deepseek/deepseek-chat] [--json]
"""

from __future__ import annotations

import json

import typer

from autoinfo.process import ProcessResult, run_processing

app = typer.Typer()


@app.callback(invoke_without_command=True)
def process(
    domain: str = typer.Option(..., "--domain", help="Domain to process"),
    topic: str | None = typer.Option(
        None,
        "--topic",
        help=(
            "Topic name whose keywords seed the G3 relevance gate. When "
            "omitted, G3 falls back to the union of all the domain's topic "
            "keywords."
        ),
    ),
    model: str = typer.Option(
        None, "--model", help="LLM model override (e.g. deepseek/deepseek-chat)"
    ),
    batch_size: int = typer.Option(
        0,
        "--batch-size",
        help="Process only N items per run (0 = all). Prevents MCP timeout on large collections.",
    ),
    check_factual: bool = typer.Option(
        False,
        "--check-factual",
        help="Run G4 factual consistency gate (LLM-based check of summary vs source)",
    ),
    check_translation: bool = typer.Option(
        False,
        "--check-translation",
        help="Run G5 translation accuracy gate (LLM-based check of translation vs source)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Process collected items (LLM extraction, quality gates G1-G5, KB storage)."""
    try:
        result = run_processing(
            domain=domain,
            topic=topic,
            model=model,
            batch_size=batch_size,
            check_factual=check_factual,
            check_translation=check_translation,
        )
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=1)

    # -- Output -------------------------------------------------------------
    if json_output:
        if result.total_items == 0:
            # Noop parity with MCP process_collection (server.py:673-678).
            typer.echo(
                json.dumps(
                    {
                        "status": "noop",
                        "total_items": 0,
                        "message": (
                            f"No cached items found for domain '{result.domain}'. "
                            "Run collect_sources() first."
                        ),
                        "domain": result.domain,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        typer.echo(
            json.dumps(
                {
                    "domain": result.domain,
                    "total_items": result.total_items,
                    "processed_count": result.processed_count,
                    "remaining_count": result.remaining_count,
                    "is_complete": result.is_complete,
                    "passed_gates": result.passed_gates,
                    "kb_entries_created": result.kb_entries_created,
                    "errors": result.errors,
                    "duration_s": result.duration_s,
                    "per_item_logs": result.per_item_logs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_human(result)

    # Exit with error code when any items failed
    if result.errors:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_human(result: ProcessResult) -> None:
    """Print a human-readable processing summary."""
    if result.total_items == 0:
        typer.echo(f"No cached items found for domain '{result.domain}'.")
        return

    typer.echo(f"Processing domain: {result.domain}")
    typer.echo("")

    # Per-item progress
    for log in result.per_item_logs:
        status_icon = {
            "ok": "✓",
            "duplicate": "⚠",
            "error": "✗",
        }.get(log.get("status", ""), "?")

        title = log.get("title", "?")[:72]
        item_id = log.get("item_id", "?")

        if log.get("status") == "error":
            typer.echo(
                f"  {status_icon} {item_id}: {title}",
                err=True,
            )
            typer.echo(f"      ↳ {log.get('error', 'unknown error')}", err=True)
        elif log.get("status") == "duplicate":
            typer.echo(
                f"  {status_icon} {item_id}: {title} "
                f"(duplicate, matched by {log.get('detail', '?')})"
            )
        else:
            score = log.get("g3_score", 0)
            dur = log.get("duration_s", 0)
            typer.echo(
                f"  {status_icon} {item_id}: {title} "
                f"[score={score:.0f}, {dur:.2f}s]"
            )

    # Summary line
    typer.echo("")
    summary_parts = [
        f"Summary: {result.total_items} items → "
        f"{result.passed_gates} passed G1-G3 → "
        f"{result.kb_entries_created} KB entries created "
        f"({result.duration_s:.1f}s)",
    ]
    if not result.is_complete:
        summary_parts.append(
            f"  Batch progress: {result.processed_count} processed, "
            f"{result.remaining_count} remaining (incomplete)"
        )
    typer.echo("".join(summary_parts))

    if result.errors:
        summary = f"  {len(result.errors)} item(s) failed processing"
        typer.echo(summary, err=True)
