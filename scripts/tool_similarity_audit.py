"""Tool similarity audit: D-工-7 evidence for the best-practice review.

Static audit of tool *boundary health* across the 146 MCP tool surface
(D-工-7 in ``docs/dev/best-practice-review.md``; sourced from Anthropic /
OpenAI tool-design guidance — agents must be able to tell tools apart):

- **Noun-stem families** — tools sharing a noun stem across segments
  (``get_source`` / ``list_sources`` / ``remove_source``) form a family.
  A family with several distinct verbs is healthy (query + mutate pairs);
  a family where two tools share *both* stem and verb shape is a boundary
  ambiguity risk (the agent cannot distinguish them by name).
- **Description overlap** — pairwise Jaccard overlap of stopword-stripped
  description tokens. Pairs above ``DESC_OVERLAP_THRESHOLD`` (0.5) are
  flagged: their descriptions are so similar the agent cannot pick the
  right tool from prose alone.

Run from the project root: ``python3 scripts/tool_similarity_audit.py``

Writes a timestamped report to
``validation-runs/coverage/tool-similarity-<date>.json`` and prints a
summary to stdout. Pure static analysis — no server imports. The AST
parsing helpers mirror ``scripts/tool_desc_audit.py`` (kept self-contained
so each audit script is hermetic).
"""
from __future__ import annotations

import ast
import datetime
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "autoinfo" / "mcp" / "server.py"
OUT_DIR = ROOT / "validation-runs" / "coverage"

DESC_OVERLAP_THRESHOLD = 0.5
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "of", "to", "for", "and", "or", "in", "on", "with",
    "from", "by", "as", "at", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "returns", "return",
    "the", "if", "when", "via", "using", "use", "used", "provide",
    "provides", "can", "will", "all", "any", "per", "into", "over", "not",
    "no", "see", "e.g.", "eg", "i.e.", "ie",
})

# Verb segments — distinguishing verb = healthy; identical verb+stem = risk.
VERB_SEGMENTS: frozenset[str] = frozenset({
    "add", "approve", "archive", "calculate", "check", "classify", "clean",
    "collect", "compare", "configure", "create", "deactivate", "delete",
    "diagnose", "export", "extract", "find", "flag", "generate", "get",
    "import", "init", "link", "list", "localize", "mark", "merge",
    "process", "promote", "query", "rate", "recommend", "reindex", "reject",
    "remove", "restore", "run", "search", "send", "set", "simplify",
    "suggest", "test", "trace", "update",
})


def _tool_calls(server_src: str) -> list[ast.Call]:
    tree = ast.parse(server_src)
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Tool"
    ]


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _str_literal(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    try:
        val = ast.literal_eval(node)
        return val if isinstance(val, str) else ""
    except (ValueError, SyntaxError):
        return ""


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def audit_similarity(server_src: str) -> dict[str, Any]:
    """Audit tool boundary health across the declared MCP surface.

    Parameters
    ----------
    server_src:
        Contents of ``src/autoinfo/mcp/server.py``.

    Returns
    -------
    dict
        With keys ``total``, ``summary`` (family + overlap metrics),
        ``violations`` (``same_stem_verb_pairs``, ``high_desc_overlap``),
        ``families``, and ``tools``. Sorted deterministically.
    """
    tools: list[dict[str, Any]] = []
    for call in _tool_calls(server_src):
        name = _str_literal(_kw(call, "name"))
        if not name:
            continue
        desc = _str_literal(_kw(call, "description"))
        segs = name.split("_")
        tools.append({
            "name": name,
            "description": desc,
            "segments": segs,
            "stem": "_".join(segs[1:]),  # everything after the first segment
            "first": segs[0],
            "token_set": _tokens(desc),
        })
    tools.sort(key=lambda t: t["name"])

    # --- noun-stem families ------------------------------------------------
    families: dict[str, list[str]] = {}
    for t in tools:
        if t["stem"]:
            families.setdefault(t["stem"], []).append(t["name"])
    families = {k: v for k, v in sorted(families.items()) if len(v) >= 2}

    # Same-stem pairs sharing the same *first* (verb-ish) segment = name
    # boundary ambiguity (e.g. add_topic vs add_topic_group would collide —
    # only if stems were equal; these are flagged by exact stem+first match).
    same_stem_first: dict[tuple[str, str], list[str]] = {}
    for t in tools:
        if t["stem"]:
            key = (t["first"], t["stem"])
            same_stem_first.setdefault(key, []).append(t["name"])
    same_stem_verb_pairs = [
        names for names in sorted(same_stem_first.values()) if len(names) >= 2
    ]

    # --- description overlap (pairwise Jaccard) -----------------------------
    overlap_pairs: list[dict[str, Any]] = []
    for i in range(len(tools)):
        for j in range(i + 1, len(tools)):
            a, b = tools[i], tools[j]
            if not a["token_set"] or not b["token_set"]:
                continue
            sim = _jaccard(a["token_set"], b["token_set"])
            if sim >= DESC_OVERLAP_THRESHOLD:
                overlap_pairs.append({
                    "a": a["name"],
                    "b": b["name"],
                    "jaccard": round(sim, 3),
                })
    overlap_pairs.sort(key=lambda p: (-p["jaccard"], p["a"], p["b"]))

    family_sizes = [len(v) for v in families.values()]
    summary = {
        "total": len(tools),
        "family_count": len(families),
        "largest_family": max(family_sizes, default=0),
        "same_stem_verb_pairs": len(same_stem_verb_pairs),
        "high_desc_overlap_pairs": len(overlap_pairs),
        "desc_overlap_threshold": DESC_OVERLAP_THRESHOLD,
    }
    return {
        "total": len(tools),
        "summary": summary,
        "violations": {
            "same_stem_verb_pairs": same_stem_verb_pairs,
            "high_desc_overlap": overlap_pairs,
        },
        "families": {k: v for k, v in families.items()},
        "tools": [
            {"name": t["name"], "segments": t["segments"], "stem": t["stem"],
             "first": t["first"]}
            for t in tools
        ],
    }


def main() -> int:
    result = audit_similarity(SRC.read_text(encoding="utf-8"))
    s = result["summary"]

    print(f"Tool similarity audit (D-工-7) — {datetime.date.today().isoformat()}")
    print(f"Tools: {s['total']}")
    print(f"Noun-stem families (>=2 members): {s['family_count']} "
          f"(largest: {s['largest_family']})")
    print(f"Same stem+verb name pairs (boundary risk): "
          f"{s['same_stem_verb_pairs']}")
    print(f"High description-overlap pairs (jaccard >= "
          f"{s['desc_overlap_threshold']}): {s['high_desc_overlap_pairs']}")

    if result["violations"]["same_stem_verb_pairs"]:
        print("\nsame_stem_verb_pairs:")
        for names in result["violations"]["same_stem_verb_pairs"]:
            print(f"  {', '.join(names)}")
    if result["violations"]["high_desc_overlap"]:
        print(f"\nhigh_desc_overlap "
              f"(top {min(10, len(result['violations']['high_desc_overlap']))}):")
        for p in result["violations"]["high_desc_overlap"][:10]:
            print(f"  {p['jaccard']:.2f} {p['a']} <-> {p['b']}")

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tool-similarity-{datetime.date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
