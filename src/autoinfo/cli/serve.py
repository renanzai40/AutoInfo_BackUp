"""``autoinfo serve`` — launch the AutoInfo MCP server from the CLI.

Thin wrapper over :mod:`autoinfo.mcp.server` (stdio transport only; SSE is
future work per AGENTS.md).  ``serve --agent`` starts the read-only server
exposing exactly the 4 read-only tools.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="serve",
    help="Run the AutoInfo MCP server (stdio transport)",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def serve(
    ctx: typer.Context,
    agent: bool = typer.Option(
        False,
        "--agent",
        help="Read-only agent mode: expose only the 4 read-only tools "
        "(search_knowledge_base, get_kb_entry, export_kb(format=agent), "
        "list_validation_scenarios).",
    ),
) -> None:
    """Run the AutoInfo MCP server over stdio."""
    if ctx.invoked_subcommand is not None:
        return
    from autoinfo.mcp.server import run

    run(readonly=agent)


if __name__ == "__main__":
    app()
