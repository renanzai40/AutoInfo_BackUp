"""Keywords CLI — manage per-domain keyword lifecycle.

Usage::

    autoinfo keywords list --domain medical
    autoinfo keywords list --domain medical --status auto_added
    autoinfo keywords approve medical "IVF"
    autoinfo keywords reject medical "IVF"
    autoinfo keywords suggest --domain medical --text "..." --limit 10
"""

from __future__ import annotations

import builtins
import json
import os

import typer

from autoinfo.keywords import KeywordsFile, KeywordState
from autoinfo.llm import call_with_fallback

app = typer.Typer(help="Manage per-domain keyword lifecycle")


def _find_state(status: str | None) -> KeywordState | None:
    """Parse a status string into a :class:`KeywordState`, or ``None``."""
    if status is None:
        return None
    try:
        return KeywordState(status.lower())
    except ValueError:
        typer.echo(
            f"Error: Invalid status '{status}'. "
            f"Valid: verified, auto_added, deprecated",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def list(  # noqa: A001 — shadowing built-in list is intentional for CLI
    domain: str = typer.Option(..., "--domain", help="Domain name"),
    status: str | None = typer.Option(
        None, "--status", help="Filter by state (verified, auto_added, deprecated)"
    ),
) -> None:
    """List keywords for a domain, optionally filtered by status."""
    state = _find_state(status)
    kf = KeywordsFile()
    entries = kf.list_keywords(domain=domain, status=state)

    if not entries:
        msg = f"No keywords found for domain '{domain}'"
        if status:
            msg += f" with status '{status}'"
        typer.echo(msg)
        return

    # Determine column widths
    kw_width = max(len(e.keyword) for e in entries) + 2
    state_width = max(len(e.state.value) for e in entries) + 2
    source_width = max((len(e.source) if e.source else 4) for e in entries) + 2

    header = (
        f"{'Keyword':<{kw_width}} {'State':<{state_width}} "
        f"{'Source':<{source_width}} Created"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for e in entries:
        typer.echo(
            f"{e.keyword:<{kw_width}} {e.state.value:<{state_width}} "
            f"{(e.source or '-'):<{source_width}} {e.created_at or '-'}"
        )


@app.command()
def approve(
    domain: str = typer.Argument(..., help="Domain name"),
    keyword: str = typer.Argument(..., help="Keyword to approve"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Approve a keyword (move from auto_added → verified)."""
    kf = KeywordsFile()
    result = kf.approve_keyword(domain=domain, keyword=keyword)
    if result is None:
        typer.echo(
            f"Error: Keyword '{keyword}' not found in domain '{domain}'",
            err=True,
        )
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(
            json.dumps(
                {"domain": domain, "keyword": keyword, "state": result.state.value},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    typer.echo(f"Approved keyword '{keyword}' in domain '{domain}' (→ verified)")


@app.command()
def reject(
    domain: str = typer.Argument(..., help="Domain name"),
    keyword: str = typer.Argument(..., help="Keyword to reject"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Reject a keyword (move to deprecated)."""
    kf = KeywordsFile()
    result = kf.deprecate_keyword(domain=domain, keyword=keyword)
    if result is None:
        typer.echo(
            f"Error: Keyword '{keyword}' not found in domain '{domain}'",
            err=True,
        )
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(
            json.dumps(
                {"domain": domain, "keyword": keyword, "state": result.state.value},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    typer.echo(f"Rejected keyword '{keyword}' in domain '{domain}' (→ deprecated)")


@app.command()
def suggest(
    domain: str = typer.Option(..., "--domain", help="Domain name for context"),
    text: str | None = typer.Option(
        None, "--text", help="Text to extract keywords from"
    ),
    limit: int = typer.Option(
        10, "--limit", help="Maximum number of suggestions (default 10)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Suggest keywords from a text via the LLM (mirrors MCP suggest_keywords).

    When ``--text`` is omitted the command returns a graceful empty result
    instead of failing.
    """
    if not text:
        if json_output:
            typer.echo(
                json.dumps(
                    {"domain": domain, "suggestions": [], "count": 0},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        typer.echo(
            "No text provided. Pass --text '<content>' to suggest keywords "
            f"for domain '{domain}'."
        )
        return

    # Same config resolution as the MCP suggest_keywords handler.
    # Issue #195: resolve_llm_model raises when unconfigured (no hardcoded
    # vendor default); the not-api_key guard below is the primary CLI error.
    from autoinfo.config import (  # noqa: PLC0415
        JudgmentModelNotConfiguredError,
        get_config_path,
        load_config,
        resolve_llm_model,
    )

    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            model = resolve_llm_model(config.llm)
            api_key = config.llm.api_key or os.environ.get("AUTOINFO_LLM_API_KEY", "")
            base_url = config.llm.base_url or None
            json_mode = config.llm.json_mode
        else:
            raise JudgmentModelNotConfiguredError(
                "LLM not configured: set AUTOINFO_LLM_API_KEY or run "
                "'autoinfo init'."
            )
    except Exception:
        model = ""
        api_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
        base_url = None
        json_mode = True

    if not api_key:
        typer.echo(
            "Error: LLM is not configured. Set AUTOINFO_LLM_API_KEY or run "
            "'autoinfo init' with an LLM config. See "
            "docs/dev/required-api-keys.md for the full list of API keys.",
            err=True,
        )
        raise typer.Exit(code=1)

    system_prompt = (
        "You are a keyword extraction assistant. Given a text, suggest "
        f"up to {limit} relevant keywords or short phrases (2-5 words) "
        "that capture the core topics. "
        "Respond with valid JSON only: an array of strings. "
        'Example: ["machine learning", "neural networks", "deep learning"]'
    )
    user_prompt = f"Extract up to {limit} keywords from this text:\n\n{text}"

    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=json_mode,
            max_tokens=500,
            temperature=0.3,
            base_url=base_url,
            api_key=api_key or None,
        )
        content: str = response.choices[0].message.content or ""
    except Exception as exc:
        typer.echo(f"Error: keyword suggestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        typer.echo(
            "Error: keyword suggestion failed: LLM returned empty or "
            "non-JSON content.",
            err=True,
        )
        raise typer.Exit(code=1) from None

    if isinstance(parsed, builtins.list):
        suggestions = parsed
    elif isinstance(parsed, dict):
        for key in ("keywords", "suggestions", "tags", "items"):
            if key in parsed and isinstance(parsed[key], builtins.list):
                suggestions = parsed[key]
                break
        else:
            suggestions = builtins.list(parsed.values()) if parsed else []
    else:
        suggestions = []

    suggestions = [str(s).strip() for s in suggestions if s]
    suggestions = suggestions[:limit]

    if json_output:
        typer.echo(
            json.dumps(
                {"domain": domain, "suggestions": suggestions, "count": len(suggestions)},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not suggestions:
        typer.echo(f"No keywords suggested for domain '{domain}'.")
        return
    typer.echo(f"Suggested keywords for domain '{domain}':")
    for i, s in enumerate(suggestions, 1):
        typer.echo(f"{i:>2}. {s}")
