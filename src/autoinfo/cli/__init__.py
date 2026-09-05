"""AutoInfo CLI entry point."""

from __future__ import annotations

import typer

from . import (
    agent_callback,
    alert_rules,
    audit,
    billing,
    cefr,
    clean,
    collect,
    cost,
    cron,
    doctor,
    domain,
    email,
    enduser,
    import_kb,
    kb,
    keywords,
    knowledge,
    mvp,
    output,
    portal,
    process,
    query_collected,
    serve,
    sources,
    status,
    summaries,
    topics,
    trace,
    validate,
    validation,
)

# Import init function directly (not as typer app — single-command module)
from .init import init as init_func

app = typer.Typer(
    name="autoinfo",
    help="Universal information tracking and knowledge base platform",
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    json: bool = typer.Option(False, "--json", help="Enable JSON output"),
) -> None:
    """AutoInfo CLI — collect, process, and manage your information."""
    ctx.obj = {"json": json}


# Register subcommand modules as top-level commands
app.command()(init_func)
app.add_typer(doctor.app, name="doctor")
app.add_typer(
    collect.app,
    name="collect",
    help="Collect content from configured sources for a domain",
)
app.add_typer(
    process.app,
    name="process",
    help="Process collected items with LLM extraction and quality gates",
)
app.add_typer(status.app, name="status", help="Show collection and processing status overview")
app.add_typer(sources.app, name="sources", help="Manage source configurations for domains")
app.add_typer(topics.app, name="topics", help="Manage topics and keywords for domains")
app.add_typer(
    topics.topic_group_app,
    name="topic-group",
    help="Manage topic groups (MCP topic_group_add/remove parity)",
)
app.add_typer(
    domain.app,
    name="domain",
    help="Manage domains (add, remove, list, activate, deactivate)",
)
app.add_typer(audit.app, name="audit")
app.add_typer(billing.app, name="billing")
app.add_typer(kb.app, name="kb")
app.add_typer(
    output.app,
    name="output",
    help="Generate digests, reports, tutorials, presentations, and exports",
)
app.add_typer(cefr.app, name="cefr", help="Classify text by CEFR reading level (EN/ZH/JA)")
app.add_typer(clean.app, name="clean")
app.add_typer(email.app, name="email", help="Send email digests via SMTP")
app.add_typer(cron.app, name="cron")
app.add_typer(summaries.app, name="summaries", help="Browse and manage collected summaries")
app.add_typer(keywords.app, name="keywords", help="Manage per-domain keyword lifecycle")
app.add_typer(knowledge.knowledge_app, name="knowledge")
app.add_typer(cost.app, name="cost")
app.add_typer(enduser.app, name="enduser")
app.add_typer(portal.app, name="portal")
app.add_typer(trace.app, name="trace")
app.add_typer(
    validate.app,
    name="validate",
    help="Run the full-matrix acceptance executor + regression guard (#331/#332)",
)
app.add_typer(
    validation.app,
    name="validation",
    help="Browse the validation scenario library (list_validation_scenarios parity)",
)
app.add_typer(
    import_kb.app,
    name="import-kb",
    help="Import entries into the KB (01-Raw) — mirrors MCP import_kb",
)
app.add_typer(
    query_collected.app,
    name="query-collected",
    help="Q&A over collected content (FTS5 + LLM) — mirrors MCP query_collected",
)
app.add_typer(
    alert_rules.app,
    name="alert-rules",
    help="Manage alert rules — mirrors MCP add/get/remove_alert_rule",
)
app.add_typer(
    agent_callback.app,
    name="agent-callback",
    help="Manage agent push callbacks — mirrors MCP set/list/remove_agent_callback",
)
app.add_typer(
    serve.app,
    name="serve",
    help="Run the AutoInfo MCP server over stdio ('serve --agent' = read-only 4-tool mode)",
)
app.add_typer(
    mvp.app,
    name="mvp",
    help="Concierge MVP pilots: provision and list paying pilot users",
)
app.add_typer(
    mvp.app,
    name="mvp",
    help="Concierge MVP pilots: provision and list paying pilot users (mvp init/list)",
)

if __name__ == "__main__":
    app()
