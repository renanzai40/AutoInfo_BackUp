from __future__ import annotations

"""Doctor CLI — checks system health and configuration.

Usage::

    autoinfo doctor [--json] [--verbose]
"""


import json  # noqa: E402
from typing import Any  # noqa: E402

import typer  # noqa: E402

app = typer.Typer()


@app.callback(invoke_without_command=True)
def doctor(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    verbose: bool = typer.Option(
        False, "--verbose",
        help="Extended diagnostics (run history, error rates, latency, source health, cost)",
    ),
) -> None:
    """Check system health and configuration."""
    try:
        from autoinfo.doctor import diagnose_pipeline, run_doctor

        result = run_doctor()
        if verbose:
            result["_verbose"] = diagnose_pipeline(deep=True)
            result["_verbose"]["health_score"] = calculate_health_score(result)
    except ImportError as exc:
        typer.echo(f"Error: doctor module not available: {exc}", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
        if verbose and "_verbose" in result:
            _print_verbose(result["_verbose"])

    # Exit with error if any critical check failed
    if result.get("python", {}).get("status") == "error":
        raise typer.Exit(code=1)
    if result.get("config", {}).get("status") == "error":
        raise typer.Exit(code=1)


def _print_human(result: dict[str, Any]) -> None:
    """Print a human-readable health report with ✅/❌ indicators."""

    # --- Python ---
    py = result.get("python", {})
    icon = "✅" if py.get("status") == "ok" else "❌"
    typer.echo(f"  {icon} Python {py.get('version', '?')}")

    # --- Config ---
    cfg = result.get("config", {})
    if cfg.get("status") == "ok":
        typer.echo(f"  ✅ Config: {cfg.get('path', '?')}")
    else:
        typer.echo(f"  ❌ Config: {cfg.get('path', '(not found)')}")
        for err in cfg.get("errors", []):
            typer.echo(f"       ↳ {err}")

    # --- LLM ---
    llm = result.get("llm", {})
    if llm.get("status") == "ok":
        typer.echo(
            f"  ✅ LLM: {llm.get('provider', '?')} / {llm.get('model', '?')} "
            f"(key {'✓' if llm.get('key_configured') else '✗'})"
        )
    else:
        typer.echo(
            "  ❌ LLM: no API key configured "
            "(set AUTOINFO_LLM_API_KEY or configure llm.api_key)"
        )
        typer.echo(
            "       Agents: use the MCP tool configure_llm() to set up the LLM "
            "(or set the AUTOINFO_LLM_API_KEY env var)"
        )
        typer.echo(
            "       See docs/dev/required-api-keys.md for API key setup"
        )

    # --- LLM fallback chain ---
    fh = result.get("fallback_health", {})
    if fh:
        if fh.get("configured"):
            typer.echo(f"  ✅ LLM fallback chain: {fh.get('count', 0)} fallback(s)")
            for entry in fh.get("entries", []):
                inherited = []
                if entry.get("inherits_provider"):
                    inherited.append("provider")
                if entry.get("inherits_key"):
                    inherited.append("key")
                inherit_str = f" (inherits {', '.join(inherited)})" if inherited else ""
                typer.echo(f"       ↳ {entry.get('model', '?')}{inherit_str}")
        else:
            typer.echo(
                "  ⚠ LLM fallback chain: not configured "
                "(add llm.fallback to .autoinfo/config.yaml)"
            )
        primary = fh.get("primary", {})
        if primary:
            flags = []
            if primary.get("reasoning_model"):
                flags.append("reasoning_model")
            if primary.get("json_mode"):
                flags.append("json_mode")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            typer.echo(
                f"       primary: {primary.get('provider', '?')}/"
                f"{primary.get('model', '?')}{flag_str}"
            )

    # --- Sources ---
    sources = result.get("sources", [])
    if sources:
        typer.echo("  Sources:")
        for src in sources:
            icon = "✅" if src.get("status") == "ok" else "❌"
            if src.get("status") == "skipped":
                icon = "–"
            latency = src.get("latency_ms", 0)
            detail = src.get("detail", "")
            line = f"    {icon} {src['name']} ({latency:.0f}ms)"
            if detail:
                line += f" — {detail}"
            typer.echo(line)
    else:
        typer.echo("  Sources: (none configured)")


def _print_verbose(v: dict[str, Any]) -> None:
    """Print extended diagnostics as ASCII tables."""

    # --- Health Score ---
    health_score = v.get("health_score")
    if health_score is not None:
        _print_health_score(health_score)

    # --- Run history ---
    runs = v.get("run_history", [])
    typer.echo("")
    typer.echo("  ── Pipeline Run History ──────────────────────────────")
    if runs:
        # Show last 10 runs
        for entry in runs[:10]:
            ts = entry.get("timestamp", "?")[:19].replace("T", " ")
            mod = entry.get("module", "?")
            lvl = entry.get("level", "?")
            msg = entry.get("message", "")[:60]
            dur = entry.get("duration_ms")
            dur_str = f" {dur:.0f}ms" if dur is not None else ""
            icon = "❌" if lvl == "ERROR" else "ℹ"
            typer.echo(f"    {icon} {ts} [{mod}] {msg}{dur_str}")
        if len(runs) > 10:
            typer.echo(f"    ... and {len(runs) - 10} more entries")
    else:
        typer.echo("    (no pipeline log data found)")

    # --- Error rates ---
    err = v.get("error_rates", {})
    typer.echo("")
    typer.echo("  ── Error Rates ───────────────────────────────────────")
    total_runs = err.get("total_runs", 0)
    total_err = err.get("total_errors", 0)
    err_pct = err.get("error_pct", 0.0)
    if total_runs:
        typer.echo(f"    Total runs:  {total_runs}")
        typer.echo(f"    Errors:      {total_err}")
        typer.echo(f"    Error rate:  {err_pct}%")
    else:
        typer.echo("    (no run data)")

    # --- Latency percentiles ---
    lat = v.get("latency", {})
    typer.echo("")
    typer.echo("  ── Latency Percentiles ───────────────────────────────")
    if lat.get("count", 0):
        typer.echo(f"    Samples:  {lat['count']}")
        typer.echo(f"    Min:      {lat.get('min_ms', 0):.1f}ms")
        typer.echo(f"    P50:      {lat['p50_ms']:.1f}ms")
        typer.echo(f"    P95:      {lat['p95_ms']:.1f}ms")
        typer.echo(f"    P99:      {lat['p99_ms']:.1f}ms")
        typer.echo(f"    Max:      {lat.get('max_ms', 0):.1f}ms")
        typer.echo(f"    Avg:      {lat.get('avg_ms', 0):.1f}ms")
    else:
        typer.echo("    (no latency data)")

    # --- Source health ---
    health = v.get("source_health", [])
    typer.echo("")
    typer.echo("  ── Source Health ─────────────────────────────────────")
    if health:
        typer.echo(f"    {'Source':<30} {'Status':<12} {'Errors':>6} {'Avg RT':>8}")
        typer.echo(f"    {'─'*30} {'─'*12} {'─'*6} {'─'*8}")
        for s in health:
            name = s.get("name", s.get("source_id", "?"))
            status_icon = {
                "healthy": "✅",
                "degraded": "⚠",
                "error": "❌",
                "paused": "⏸",
                "unknown": "?",
            }.get(s.get("status", "unknown"), "?")
            status_str = f"{status_icon} {s.get('status', 'unknown')}"
            err_cnt = s.get("error_count", 0)
            avg_rt = f"{s.get('avg_response_time_ms', 0):.0f}ms"
            typer.echo(f"    {name:<30} {status_str:<12} {err_cnt:>6} {avg_rt:>8}")
    else:
        typer.echo("    (no sources configured)")

    # --- Cost metrics ---
    cost = v.get("cost", {})
    typer.echo("")
    typer.echo("  ── Cost Metrics ──────────────────────────────────────")
    total_cost = cost.get("total_cost", 0.0)
    if total_cost > 0 or cost.get("log_count", 0) > 0:
        typer.echo(f"    Total cost:  ${total_cost:.6f}")
        typer.echo(f"    Log entries: {cost.get('log_count', 0)}")
        by_type = cost.get("by_type", {})
        if by_type:
            typer.echo("    By type:")
            for t, c in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
                typer.echo(f"      {t}: ${c:.6f}")
        llm_models = cost.get("llm_models", {})
        if llm_models:
            typer.echo("    LLM models:")
            for mdl, info in llm_models.items():
                tokens = info.get("total_tokens", 0)
                calls = info.get("call_count", 0)
                cst = info.get("cost", 0)
                typer.echo(f"      {mdl}: {tokens:,} tokens, {calls} calls, ${cst:.6f}")
        api_srcs = cost.get("api_sources", {})
        if api_srcs:
            typer.echo("    API sources:")
            for src_name, info in api_srcs.items():
                calls = info.get("call_count", 0)
                cst = info.get("cost", 0)
                typer.echo(f"      {src_name}: {calls} calls, ${cst:.6f}")
    else:
        typer.echo("    (no cost data available)")


def _print_health_score(score: int) -> None:
    """Print a visual health score bar with color indicator."""
    if score >= 80:
        color = typer.colors.GREEN
        grade = "Healthy"
    elif score >= 50:
        color = typer.colors.YELLOW
        grade = "Degraded"
    else:
        color = typer.colors.RED
        grade = "Critical"

    bar_len = max(1, score // 5)
    bar = "█" * bar_len + "░" * (20 - bar_len)

    typer.echo("")
    typer.echo("  ── Health Score ───────────────────────────────────────")
    typer.secho(f"    [{bar}] {score}/100  {grade}", fg=color)


def calculate_health_score(result: dict[str, Any]) -> int:
    """Calculate 0-100 health score based on diagnostics."""
    score = 100

    # Core component checks
    if result.get("llm", {}).get("status") != "ok":
        score -= 30
    if result.get("config", {}).get("status") != "ok":
        score -= 20
    if result.get("python", {}).get("status") != "ok":
        score -= 20

    # Source health
    sources = result.get("sources", [])
    if sources:
        failed = sum(1 for s in sources if s.get("status") not in ("ok", "skipped"))
        if failed > 0:
            score -= min(20, failed * 10)

    # Error rates from verbose pipeline diagnostics
    verbose = result.get("_verbose", {})
    if verbose:
        error_pct = verbose.get("error_rates", {}).get("error_pct", 0.0)
        score -= int(error_pct * 5)

    return max(0, score)


def calculate_error_rates() -> dict[str, float]:
    """Real error rates (0-100) per pipeline stage from logs + run records."""
    from autoinfo.doctor import compute_error_rates

    rates = compute_error_rates()
    by_stage = rates.get("by_stage", {})
    return {
        "overall": float(rates.get("error_pct", 0.0)),
        "collection": float(by_stage.get("collection", {}).get("error_pct", 0.0)),
        "processing": float(by_stage.get("processing", {}).get("error_pct", 0.0)),
        "delivery": float(by_stage.get("delivery", {}).get("error_pct", 0.0)),
    }


def calculate_latency_percentiles() -> dict[str, float]:
    """Real latency percentiles (ms) from recorded duration_ms samples."""
    from autoinfo.doctor import compute_latency_percentiles

    lat = compute_latency_percentiles()
    return {
        "p50_ms": float(lat.get("p50_ms", 0.0)),
        "p95_ms": float(lat.get("p95_ms", 0.0)),
        "p99_ms": float(lat.get("p99_ms", 0.0)),
    }
