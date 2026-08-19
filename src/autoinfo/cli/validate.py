"""`autoinfo validate` CLI — full-matrix acceptance executor (issue #331) +
version regression guard (issue #332-A).

Subcommands:

* ``autoinfo validate matrix`` — generate products over a domains x products
  grid on the REAL KB path, run the formalized assertion set, and emit a
  report card (JSON, optional HTML).  ``--only-assert`` scans already-persisted
  outputs/ without regenerating.  Exit code is non-zero when any P0/P1
  assertion fails (usable as a CI / release gate).
* ``autoinfo validate diff <prev> <cur>`` — compare two report-card snapshots
  and classify every (product, assertion) as new / regressed / fixed /
  existing-failing (#332-A).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoinfo.validation_matrix import (
    MATRIX_PRODUCTS,
    MatrixReport,
    diff_report_cards,
    run_matrix,
    save_report_card,
)

app = typer.Typer(
    name="validate",
    help="Run the full-matrix acceptance executor and regression guard",
    no_args_is_help=True,
)
console = Console()


def _default_domains() -> list[str]:
    from autoinfo.config import get_config_path, load_config

    cfg_path = get_config_path()
    if cfg_path is None or not Path(cfg_path).is_file():
        return ["medical-research", "ai-commercial", "financial-intelligence"]
    try:
        cfg = load_config(cfg_path)
        names = [d.name for d in cfg.domains if d.active]
        return names or ["medical-research", "ai-commercial", "financial-intelligence"]
    except Exception:
        return ["medical-research", "ai-commercial", "financial-intelligence"]


@app.command(name="matrix")
def matrix(
    domains: str = typer.Option(
        "", "--domains", "--domain",
        help="Comma-separated domain subset (default: all active domains)",
    ),
    products: str = typer.Option(
        "", "--products", "--product",
        help=(
            "Comma-separated product subset (default: all 8) — "
            f"{', '.join(MATRIX_PRODUCTS)}"
        ),
    ),
    only_assert: bool = typer.Option(
        False, "--only-assert",
        help="Do not regenerate — assert on already-persisted outputs/ files",
    ),
    json_out: str = typer.Option("", "--json-out", help="Write report card JSON to this path"),
    html_out: str = typer.Option("", "--html-out", help="Write report card HTML to this path"),
    snapshot_dir: str = typer.Option(
        "validation-runs/matrix", "--snapshot-dir",
        help="Directory to persist report-card snapshots for validate diff",
    ),
) -> None:
    """Run the full-matrix acceptance executor (#331).

    Generates products per domain x product on the real KB generation path,
    runs the formalized assertion set, and emits a report card.  Non-zero exit
    code when any P0/P1 assertion fails.
    """
    domain_list = [d.strip() for d in domains.split(",") if d.strip()] or _default_domains()
    product_list = (
        [p.strip() for p in products.split(",") if p.strip()]
        or list(MATRIX_PRODUCTS)
    )
    report = run_matrix(domain_list, product_list, only_assert=only_assert)
    _render_report_card(report)
    if json_out:
        Path(json_out).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(f"[green]report card JSON → {json_out}[/green]")
    if html_out:
        _write_html(report, Path(html_out))
        console.print(f"[green]report card HTML → {html_out}[/green]")
    snap = save_report_card(report, Path(snapshot_dir))
    console.print(f"[cyan]snapshot → {snap}[/cyan]")

    # Non-zero exit when any P0/P1 assertion failed (CI / release gate).
    if report.summary.get("failures", 0):
        raise typer.Exit(code=1)


@app.command(name="diff")
def diff_cmd(
    prev: str = typer.Argument(..., help="Previous report-card JSON path"),
    cur: str = typer.Argument(..., help="Current report-card JSON path"),
) -> None:
    """Compare two report-card snapshots (#332-A regression guard)."""
    prev_card = json.loads(Path(prev).read_text(encoding="utf-8"))
    cur_card = json.loads(Path(cur).read_text(encoding="utf-8"))
    d = diff_report_cards(prev_card, cur_card)
    counts = d["counts"]
    console.print(
        f"[bold]diff[/bold] new={counts['new']} regressed={counts['regressed']} "
        f"fixed={counts['fixed']} existing={counts['existing_failing']}"
    )
    table = Table(title="Regression diff")
    table.add_column("Class")
    table.add_column("Product")
    table.add_column("Assertion")
    for cls, items in (
        ("regressed", d["regressed"]),
        ("new", d["new"]),
        ("fixed", d["fixed"]),
        ("existing", d["existing_failing"]),
    ):
        for product, assertion in items:
            table.add_row(cls, product, assertion)
    console.print(table)
    if d["regressed"] or d["new"]:
        raise typer.Exit(code=1)


def _render_report_card(report: MatrixReport) -> None:
    """Print the report card as a rich table + summary."""
    summary = report.summary
    console.print(
        f"[bold]validate --matrix[/bold] (commit {report.commit}) — "
        f"{summary.get('domains', [])} x {summary.get('products', [])}"
    )
    table = Table(title="Report card")
    table.add_column("Domain")
    table.add_column("Product")
    table.add_column("Status")
    for p in report.products:
        table.add_row(
            p.get("domain", ""),
            p.get("product", ""),
            p.get("status", ""),
        )
    console.print(table)
    console.print(
        f"total_products={summary.get('total_products')} "
        f"total_asserts={summary.get('total_asserts')} "
        f"failures={summary.get('failures')}"
    )


def _write_html(report: MatrixReport, out: Path) -> None:
    """Write a minimal self-contained HTML report card."""
    rows = []
    for p in report.products:
        rows.append(
            "<tr>"
            f"<td>{p.get('domain','')}</td>"
            f"<td>{p.get('product','')}</td>"
            f"<td>{p.get('status','')}</td>"
            "</tr>"
        )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>AutoInfo validate --matrix report card</title></head><body>"
        "<h1>validate &mdash; matrix report card</h1>"
        f"<p>commit <code>{report.commit}</code> — generated "
        f"{report.generated_at}</p>"
        "<table border='1' cellpadding='4'><tr><th>domain</th><th>product</th>"
        "<th>status</th></tr>" + "".join(rows) + "</table>"
        "</body></html>"
    )
    out.write_text(html, encoding="utf-8")
