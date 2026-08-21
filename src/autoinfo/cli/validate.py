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
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoinfo.validation_matrix import (
    MATRIX_PRODUCTS,
    PRODUCT_STATUS,
    MatrixReport,
    SkipPolicy,
    _current_commit,
    card_issue_counts,
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
        help="Batch root: products + report-card snapshot are persisted under "
             "<snapshot-dir>/<batch_id>/ (per-batch isolation, #335)",
    ),
    batch: str = typer.Option(
        "", "--batch",
        help="Explicit batch id (default: <commit>-<stamp>); re-runs with the "
             "same id land in the same isolated batch dir",
    ),
    no_skip: bool = typer.Option(
        False, "--no-skip",
        help="Disable #348 smart-skip — force full regeneration of every "
             "(domain, product) pair",
    ),
    skip_threshold: int = typer.Option(
        3, "--skip-threshold",
        help="#348 smart-skip: consecutive passing batches required before a "
             "(domain, product) pair is reused instead of regenerated "
             "(premium products need threshold + 2 unless --skip-premium)",
    ),
    skip_premium: bool = typer.Option(
        False, "--skip-premium",
        help="#348 smart-skip: allow premium products (premium-briefing, "
             "column, enterprise-briefing) to skip at the plain threshold",
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
    batch_id = batch or (
        f"{_current_commit()}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    batch_root = Path(snapshot_dir)
    # #335: full mode always persists into an isolated per-batch dir; only-
    # assert targets the batch tree only when --batch is given, otherwise it
    # keeps the legacy shared outputs/ scan (backward compatible).
    artifacts_dir = batch_root if (not only_assert or batch) else None
    skip_policy = SkipPolicy(
        allow_skip=not no_skip,
        threshold=skip_threshold,
        skip_premium=skip_premium,
        data_dir=Path.cwd(),
    )
    report = run_matrix(
        domain_list, product_list,
        only_assert=only_assert,
        batch_id=batch_id,
        artifacts_dir=artifacts_dir,
        skip=skip_policy,
    )
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
    snap = save_report_card(report, batch_root / batch_id)
    console.print(f"[cyan]batch → {batch_id}[/cyan]")
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
    prev_counts = card_issue_counts(prev_card)
    cur_counts = card_issue_counts(cur_card)
    reconciled = counts["new"] + counts["regressed"] + counts["existing_failing"]
    cur_issues = (
        cur_counts["failing_assertions"]
        + cur_counts["missing_products"]
        + cur_counts["error_products"]
    )
    console.print(
        f"[bold]failures[/bold] {prev_card.get('batch_id', '?')} -> "
        f"{cur_card.get('batch_id', '?')} | "
        f"prev={sum(prev_counts.values())} -> cur={cur_issues} "
        f"(assertions={cur_counts['failing_assertions']} "
        f"missing={cur_counts['missing_products']} "
        f"error={cur_counts['error_products']})"
    )
    console.print(
        f"[bold]diff[/bold] new={counts['new']} regressed={counts['regressed']} "
        f"fixed={counts['fixed']} existing={counts['existing_failing']} "
        f"(new+regressed+existing={reconciled})"
    )
    if cur_issues != reconciled:
        console.print(
            f"[red]ERROR: diff buckets ({reconciled}) do not reconcile with "
            f"card failures ({cur_issues}) (#340)[/red]"
        )
        raise typer.Exit(code=1)
    table = Table(title="Regression diff")
    table.add_column("Class")
    table.add_column("Domain")
    table.add_column("Product")
    table.add_column("Assertion")
    for cls, items in (
        ("regressed", d["regressed"]),
        ("new", d["new"]),
        ("fixed", d["fixed"]),
        ("existing", d["existing_failing"]),
    ):
        for domain, product, assertion in items:
            if assertion == PRODUCT_STATUS:
                _status = next(
                    (p.get("status", "?") for p in cur_card.get("products", [])
                     if p.get("domain") == domain and p.get("product") == product),
                    "?",
                )
                assertion = f"product {_status}"
            table.add_row(cls, domain, product, assertion)
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
        f"failures={summary.get('failures')} "
        f"(assertions={summary.get('failing_assertions')} "
        f"missing={summary.get('missing_products')} "
        f"error={summary.get('error_products')})"
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
