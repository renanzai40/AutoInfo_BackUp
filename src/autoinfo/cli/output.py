"""Output CLI — generate digests, reports, tutorials, presentations, exports, and translations.

Usage::

    autoinfo output digest --domain medical --period weekly --format markdown
    autoinfo output report --domain medical --format html
    autoinfo output tutorial --domain medical --audience student
    autoinfo output presentation --domain medical --topic "IVF" --slides 10
    autoinfo output export --domain medical --format json
    autoinfo output export --domain medical --format markdown
    autoinfo output export --format json          # full KB
    autoinfo output translate --content-id X --target-lang zh
    autoinfo output translate --content "Hello" --source-lang en --target-lang fr
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

import typer

from autoinfo.output import PRODUCT_TEMPLATES, ProductTemplate, export_kb

app = typer.Typer(help="Generate digests, reports, tutorials, presentations, exports, and translations")


def _resolve_product_template(product: str) -> ProductTemplate | None:
    """Resolve a ``--product`` name to its registry ``ProductTemplate``.

    Empty string (flag omitted) returns ``None`` so the existing call
    shape is preserved.  Unknown names print the valid registry names and
    exit with code 1.
    """
    if not product:
        return None
    for row in PRODUCT_TEMPLATES:
        if row["name"] == product:
            return cast(ProductTemplate, row["template"])
    valid = ", ".join(row["name"] for row in PRODUCT_TEMPLATES)
    typer.echo(f"Error: Unknown product '{product}'. Valid products: {valid}", err=True)
    raise typer.Exit(code=1)


@app.command(name="list-templates")
def list_templates(
    domain: str = typer.Option(
        "", "--domain", help="Optional domain filter"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """List available output templates."""
    from autoinfo.mcp.server import _handle_list_output_templates

    result = _handle_list_output_templates(domain=domain)
    if json_output:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    templates = result.get("templates", [])
    if not templates:
        typer.echo("No output templates available.")
        return

    typer.echo(f"Available output templates{(' for ' + domain) if domain else ''}:")
    for t in templates:
        typer.echo(f"  - {t}")


@app.command()
def digest(
    domain: str = typer.Option(..., "--domain", help="Domain to generate digest for"),
    period: str = typer.Option(
        "weekly", "--period", help="Digest period (daily, weekly, monthly)"
    ),
    format: str = typer.Option(
        "markdown", "--format", help="Output format (markdown, html, json, agent)"
    ),
    product: str = typer.Option(
        "",
        "--product",
        help="Product template name (see output list-templates)",
    ),
    user_id: str = typer.Option(
        "",
        "--user-id",
        help="End-user ID for content-preference filtering (default: all tiers)",
    ),
) -> None:
    """Generate a digest of KB entries for a domain over a given period.

    Queries the knowledge base for entries in the given period, optionally
    synthesizes them via LLM, and renders the result through a Jinja2 template.
    """
    from autoinfo.output import generate_digest

    product_template = _resolve_product_template(product)

    try:
        kwargs: dict[str, Any] = {
            "domain": domain,
            "period": period,
            "format": format,
            "user_id": user_id,
        }
        if product_template is not None:
            kwargs["product_template"] = product_template
        result = generate_digest(**kwargs)
        typer.echo(result)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def report(
    domain: str = typer.Option(
        "", "--domain", help="Domain to generate report for (single-domain mode)"
    ),
    collection_id: str = typer.Option(
        None, "--collection-id", help="Optional collection ID to scope the report",
    ),
    format: str = typer.Option(
        "markdown", "--format", help="Output format (markdown, json, agent)"
    ),
    audience: str = typer.Option(
        "", "--audience", help="Target audience: researcher, clinician, executive, student, investor",
    ),
    report_type: str = typer.Option(
        "standard", "--type", help="Report type: standard, industry, competitive, trend, daily-briefing, column",
    ),
    domains: list[str] = typer.Option(
        [],
        "--domains",
        help="Domains for cross-domain report (repeatable, e.g. --domains X --domains Y)",
    ),
    product: str = typer.Option(
        "",
        "--product",
        help="Product template name (see output list-templates)",
    ),
    user_id: str = typer.Option(
        "",
        "--user-id",
        help="End-user ID for content-preference filtering (default: all tiers)",
    ),
) -> None:
    """Generate a structured report with themed sections and executive summary.

    Groups KB entries by theme using LLM, generates per-section content,
    and renders through a Jinja2 template or returns a JSON structure.

    Supports cross-domain reports::

        autoinfo output report --domains medical --domains ai-commercial --format markdown
    """
    from autoinfo.output import generate_report

    if not domain and not domains:
        typer.echo("Error: Provide --domain or --domains to specify report scope.", err=True)
        raise typer.Exit(code=1)

    product_template = _resolve_product_template(product)

    try:
        kwargs: dict[str, Any] = {
            "domain": domain or (domains[0] if domains else "unknown"),
            "collection_id": collection_id,
            "format": format,
            "target_audience": audience,
            "report_type": report_type,
            "user_id": user_id,
        }
        if product_template is not None:
            kwargs["product_template"] = product_template
        if len(domains) >= 2:
            kwargs["domains"] = domains

        result = generate_report(**kwargs)
        typer.echo(result)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def export(
    domain: str | None = typer.Option(
        None, "--domain", help="Domain to export (default: all domains)"
    ),
    format: str = typer.Option(
        "json", "--format", help="Export format (json, markdown, sqlite, pdf, bundle, agent)"
    ),
) -> None:
    """Export knowledge base data to a file.

    Produces a JSON array, a Markdown tar.gz archive, a SQLite copy,
    or a PDF document in the ``exports/`` directory.
    """
    try:
        result = export_kb(domain=domain, format=format)
        typer.echo(
            f"Exported {result.get('entries_count', 0)} entries "
            f"to {result.get('path', 'unknown')}"
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def translate(
    content_id: str | None = typer.Option(
        None, "--content-id", help="KB entry ID to translate"
    ),
    content: str | None = typer.Option(
        None, "--content", help="Raw text to translate directly"
    ),
    source_lang: str = typer.Option(
        "", "--source-lang", help="Source language code (e.g. en, zh)"
    ),
    target_lang: str = typer.Option(
        ..., "--target-lang", help="Target language code (e.g. zh, fr, ja)"
    ),
    domain: str = typer.Option(
        "", "--domain", help="Domain name for terminology guardrails (e.g. medical-research)"
    ),
) -> None:
    """Translate a KB entry or raw text into a target language.

    Two modes:

    \b
    1. Content-ID mode (stores translation):
       autoinfo output translate --content-id kb-entry-001 --target-lang zh

    2. Direct content mode (returns only):
       autoinfo output translate --content "Hello" --source-lang en --target-lang fr
    """
    from autoinfo.output import localize_content

    try:
        result = localize_content(
            content_id=content_id,
            content=content,
            source_lang=source_lang,
            target_lang=target_lang,
            domain=domain,
        )
        if result.get("success"):
            typer.echo("Translation successful!")
            if result.get("translated_title"):
                typer.echo(f"  Title: {result['translated_title']}")
            if result.get("file_path"):
                typer.echo(f"  Saved to: {result['file_path']}")
            if result.get("translated_body"):
                # Print first 500 chars as preview
                body = result["translated_body"]
                preview = body[:500] + ("..." if len(body) > 500 else "")
                typer.echo(f"  Preview: {preview}")
        else:
            typer.echo(f"Translation failed: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(code=1)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def tutorial(
    domain: str = typer.Option(..., "--domain", help="Domain to generate tutorial for"),
    target_audience: str = typer.Option(
        "student",
        "--audience",
        help="Target audience: researcher, clinician, executive, student",
    ),
    collection_id: str = typer.Option(
        None, "--collection-id", help="Optional collection ID to scope the tutorial",
    ),
    format: str = typer.Option(
        "markdown", "--format", help="Output format (markdown, agent)"
    ),
    user_id: str = typer.Option(
        "",
        "--user-id",
        help="End-user ID for content-preference filtering (default: all tiers)",
    ),
) -> None:
    """Generate a structured tutorial adapted to the target audience.

    Fetches KB entries, uses LLM to structure a learning path with
    objectives, content sections, and exercises, and renders through
    a Jinja2 template.
    """
    from autoinfo.output import generate_tutorial

    try:
        result = generate_tutorial(
            domain=domain,
            collection_id=collection_id,
            target_audience=target_audience,
            format=format,
            user_id=user_id,
        )
        typer.echo(result)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def presentation(
    domain: str = typer.Option(..., "--domain", help="Domain to scope the presentation"),
    topic: str = typer.Option(..., "--topic", help="Presentation topic"),
    slide_count: int = typer.Option(
        10, "--slides", help="Number of slides (3-30, default: 10)"
    ),
    target_audience: str = typer.Option(
        "executive",
        "--audience",
        help="Target audience: researcher, clinician, executive, student",
    ),
    format: str = typer.Option(
        "markdown", "--format", help="Output format (markdown, html, mkslides, agent)"
    ),
    user_id: str = typer.Option(
        "",
        "--user-id",
        help="End-user ID for content-preference filtering (default: all tiers)",
    ),
) -> None:
    """Generate a slide-based presentation on a topic.

    Searches KB for topic-related entries, uses LLM to produce
    structured slide content, and renders through a Jinja2 template.
    """
    from autoinfo.output import generate_presentation

    try:
        result = generate_presentation(
            domain=domain,
            topic=topic,
            slide_count=slide_count,
            target_audience=target_audience,
            format=format,
            user_id=user_id,
        )
        typer.echo(result)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def sitemap(
    domain: str = typer.Option("", "--domain", "-d", help="Domain to generate sitemap for"),
    base_url: str = typer.Option(
        "",
        "--base-url",
        "-u",
        help="Base URL for sitemap (required, e.g. https://your-site.example)",
    ),
    output_dir: str = typer.Option("", "--output", "-o", help="Output directory"),
) -> None:
    """Generate XML sitemap for KB entries with real entry URLs."""
    from autoinfo.output import export_kb

    if not base_url:
        typer.echo(
            "Error: sitemap generation requires an explicit base URL. "
            "Provide it with --base-url, e.g. "
            "autoinfo output sitemap --domain medical-research "
            "--base-url https://your-site.example",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = export_kb(
            domain=domain if domain else None,
            format="sitemap",
            base_url=base_url,
        )
    except FileNotFoundError:
        # No config found — fall back to placeholder via seo module
        from autoinfo.output.seo import generate_sitemap

        xml = generate_sitemap(domain=domain, base_url=base_url)
        if domain:
            out_path = output_dir or f"outputs/{domain}/seo/sitemap.xml"
        else:
            out_path = output_dir or "outputs/seo/sitemap.xml"
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml)
        typer.echo(f"Sitemap written to {out_path} (no KB entries — placeholder only)")
        return

    out_path = result.get("path", "")
    if output_dir:
        # Copy to user-specified output dir if given
        import shutil

        dest = os.path.join(output_dir, os.path.basename(out_path))
        os.makedirs(output_dir, exist_ok=True)
        shutil.copy2(out_path, dest)
        out_path = dest

    typer.echo(f"Sitemap written to {out_path} ({result.get('entries_count', 0)} entries)")
