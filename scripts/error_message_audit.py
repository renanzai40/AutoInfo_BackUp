"""Error-message audit: D-工-4 evidence for the best-practice review.

Static audit of the MCP error envelope call sites in
``src/autoinfo/mcp/server.py`` against agent-actionable error guidance
(D-工-4 in ``docs/dev/best-practice-review.md``):

- **Actionable messages** — every ``error_response`` / ``error_dict`` message
  should carry a concrete fix hint (use/add/set/configure/install/enable/
  provide/pass/check/supported/see/docs), per the OWASP actionable-error
  model and the MCP spec's agent-readable message guidance.
- **No raw-exception leakage** — ``_error_dict(exc)`` currently builds
  ``message_str = str(exc)``; a message that equals the exception string is
  flagged as raw-leakage (stack-trace / internal detail exposure to agents).
- **429 Retry-After** — RATE_LIMITED call sites should mention a retry or
  backoff hint.

Run from the project root: ``python3 scripts/error_message_audit.py``

Writes a timestamped report to
``validation-runs/coverage/error-message-<date>.json`` and prints a summary
to stdout. Pure static analysis — no server imports.
"""
from __future__ import annotations

import ast
import datetime
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
OUT_DIR = ROOT / "validation-runs" / "coverage"

# Fix-hint markers that make a message agent-actionable. Based on the
# actionable-error model (OWASP): tell the agent WHAT to do next.
HINT_MARKERS: tuple[str, ...] = (
    "use ", "use_", "add", "set", "create", "configure", "install",
    "enable", "provide", "pass", "check", "supported", "requires",
    "must", "see ", "docs", "run ", "try ", "retry", "re-run", "format",
    "valid", "missing", "expected", "either", "choose", "not found",
)

RETRY_MARKERS: tuple[str, ...] = (
    "retry", "backoff", "later", "throttl", "rate limit", "429", "too many",
)


def _call_sites(src: str) -> list[dict[str, Any]]:
    """Collect error_response / error_dict / _error_dict call nodes."""
    tree = ast.parse(src)
    sites: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name not in ("error_response", "error_dict", "_error_dict"):
            continue
        msg = ""
        if name == "_error_dict":
            # _error_dict(exc) — message is str(exc) at runtime
            arg = node.args[0] if node.args else None
            arg_name = ""
            if isinstance(arg, ast.Name):
                arg_name = arg.id
            msg = f"<str({arg_name or 'exc'})>"
        else:
            for kw in node.keywords:
                if kw.arg == "message" and isinstance(kw.value, ast.Constant):
                    msg = str(kw.value.value)
        sites.append({
            "line": node.lineno,
            "call": name,
            "message": msg,
        })
    return sites


def audit_errors(src: str) -> dict[str, Any]:
    """Audit every error call site against the D-工-4 conventions.

    Parameters
    ----------
    src:
        Contents of ``src/autoinfo/mcp/server.py``.

    Returns
    -------
    dict
        With keys ``total_sites``, ``summary``, ``violations``
        (``raw_exception``, ``no_fix_hint``, ``rate_limited_no_retry``),
        and ``sites``. Sorted deterministically by line.
    """
    sites = _call_sites(src)
    sites.sort(key=lambda s: s["line"])

    raw_exception = [
        s for s in sites
        if s["call"] == "_error_dict" or s["message"].startswith("<str(")
    ]
    no_hint = [
        s for s in sites
        if s["call"] in ("error_response", "error_dict")
        and s["message"]
        and not any(m in s["message"].lower() for m in HINT_MARKERS)
    ]
    # RATE_LIMITED sites should carry a retry/backoff hint; find them by the
    # code argument referencing RATE_LIMITED.
    rate_sites: list[dict[str, Any]] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (
            fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else ""
            )
        )
        if name not in ("error_response", "error_dict"):
            continue
        code_arg = next(
            (k.value for k in node.keywords if k.arg == "code"), None
        )
        code_src = (
            ast.get_source_segment(src, code_arg) if code_arg else ""
        ) or ""
        if "RATE_LIMITED" in code_src or "RateLimited" in code_src:
            msg = next(
                (
                    str(k.value.value) for k in node.keywords
                    if k.arg == "message" and isinstance(k.value, ast.Constant)
                ),
                "",
            )
            rate_sites.append({
                "line": node.lineno,
                "message": msg,
                "has_retry_hint": any(
                    m in msg.lower() for m in RETRY_MARKERS
                ),
            })

    rate_limited_no_retry = [s for s in rate_sites if not s["has_retry_hint"]]

    summary = {
        "total_sites": len(sites),
        "raw_exception_sites": len(raw_exception),
        "no_fix_hint_sites": len(no_hint),
        "rate_limited_sites": len(rate_sites),
        "rate_limited_no_retry": len(rate_limited_no_retry),
    }
    return {
        "total_sites": len(sites),
        "summary": summary,
        "violations": {
            "raw_exception": [s["line"] for s in raw_exception],
            "no_fix_hint": [
                {"line": s["line"], "call": s["call"], "message": s["message"]}
                for s in no_hint
            ],
            "rate_limited_no_retry": [
                {"line": s["line"], "message": s["message"]}
                for s in rate_limited_no_retry
            ],
        },
        "sites": sites,
    }


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    result = audit_errors(src)
    s = result["summary"]

    print(f"Error-message audit (D-工-4) — {datetime.date.today().isoformat()}")
    print(f"Total error call sites: {s['total_sites']}")
    print(f"Raw-exception sites (_error_dict, str(exc) as message): "
          f"{s['raw_exception_sites']}")
    print(f"Messages without fix hint: {s['no_fix_hint_sites']}")
    print(f"RATE_LIMITED sites: {s['rate_limited_sites']} "
          f"(no retry hint: {s['rate_limited_no_retry']})")

    v = result["violations"]
    if v["raw_exception"]:
        print(f"\nraw_exception lines: {v['raw_exception'][:30]}")
    if v["no_fix_hint"]:
        print(f"\nno_fix_hint ({len(v['no_fix_hint'])}):")
        for row in v["no_fix_hint"][:12]:
            print(f"  L{row['line']} {row['call']}: {row['message'][:80]}")
    if v["rate_limited_no_retry"]:
        print(f"\nrate_limited_no_retry ({len(v['rate_limited_no_retry'])}):")
        for row in v["rate_limited_no_retry"][:5]:
            print(f"  L{row['line']}: {row['message'][:80]}")

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"error-message-{datetime.date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
