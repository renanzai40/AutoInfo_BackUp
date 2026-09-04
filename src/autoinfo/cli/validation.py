"""`autoinfo validation` CLI — validation scenario library browser (P1-1).

Distinct from ``autoinfo validate`` (the full-matrix acceptance executor,
issues #331/#332): this group is a read-only view over the validation
scenario library that backs the ``list_validation_scenarios`` MCP tool.

Subcommands:

* ``autoinfo validation list`` — list every scenario (name, category,
  regression flag, env requirements).  ``--summary`` groups the library by
  category and reports the functional vs regression split, derived at
  runtime from :func:`autoinfo.mcp.validation.list_scenarios` (never
  hardcoded — the library grows with every regression flywheel wave).
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from autoinfo.mcp.validation import list_scenarios

app = typer.Typer(
    name="validation",
    help="Browse the validation scenario library (list_validation_scenarios parity)",
    no_args_is_help=True,
)
console = Console()


@app.command(name="list")
def list_cmd(
    summary: bool = typer.Option(
        False, "--summary",
        help="Group scenarios by category with functional/regression counts",
    ),
) -> None:
    """List all validation scenarios (or a per-category --summary)."""
    result = list_scenarios()
    scenarios = result["scenarios"]

    if not scenarios:
        console.print(
            "[red]No validation scenarios found — the scenarios directory is "
            "missing or empty.[/red]"
        )
        raise typer.Exit(code=1)

    if summary:
        _render_summary(scenarios)
        return

    # Plain one-line-per-scenario output (long names must never wrap or be
    # cropped by rich's console width — the listing is machine-consumable).
    typer.echo(f"Validation scenarios ({len(scenarios)})")
    for sc in scenarios:
        env = ",".join(sc.get("requires_env") or []) or "-"
        typer.echo(
            f"{sc['name']}  category={sc.get('category', 'general')}  "
            f"regression={'yes' if sc.get('regression') else 'no'}  env={env}"
        )


def _render_summary(scenarios: list[dict]) -> None:
    """Group scenarios by category; print functional vs regression counts.

    All counts are derived at runtime from the discovered scenarios — no
    hardcoded library totals.
    """
    by_category: dict[str, list[dict]] = {}
    for sc in scenarios:
        by_category.setdefault(sc.get("category", "general"), []).append(sc)

    functional = sum(1 for sc in scenarios if not sc.get("regression"))
    regression = sum(1 for sc in scenarios if sc.get("regression"))

    table = Table(title=f"Validation scenario summary ({len(scenarios)} total)")
    table.add_column("Category")
    table.add_column("Functional", justify="right")
    table.add_column("Regression", justify="right")
    table.add_column("Total", justify="right")
    for cat in sorted(by_category):
        items = by_category[cat]
        cat_reg = sum(1 for sc in items if sc.get("regression"))
        table.add_row(cat, str(len(items) - cat_reg), str(cat_reg), str(len(items)))
    console.print(table)
    console.print(f"total: {len(scenarios)}")
    console.print(f"functional: {functional}")
    console.print(f"regression: {regression}")
