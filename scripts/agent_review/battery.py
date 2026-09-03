#!/usr/bin/env python3
"""L1 agent-review battery — semantic blind-spot judging over a delivery dir.

Issue #194 spec A/B: the L0 dead-code gate (scripts/quality_gate.py) is the
workhorse; this battery handles ONLY the semantic residue L0 structurally
cannot reach (coverage absence, claim fabrication vs honest hedge, product
intent).  It is OPT-IN (--semantic) and never blocks the default path.

Layered QC model (issue #194 / AGENTS.md):
  L0 dead-code gate (quality_gate.py) — deterministic, default, blocking.
  L1 agent battery (this) — semantic judging, opt-in --semantic.
  ESCALATE — value/intent judgments go to a human, never machine-final.

Vendor/model agnosticism (issue #195 + #194 comment):
  - The LLM channel is the repo's config-driven ``llm.call_with_fallback``
    (provider/model/api_key/base_url + fallback chain from config.llm) —
    NO vendor or model name appears in this file.
  - Structured output is capability-probed: if the resolved config declares
    json_mode we ask for a JSON verdict; otherwise we ask for a markdown
    verdict block and parse it deterministically.  Both paths emit the SAME
    verdict schema so the caller is agnostic.
  - FAIL LOUD: an unreachable / unparseable LLM judgment yields ESCALATE,
    NEVER PASS (a silent non-judgment is worse than a wrong judgment —
    issues #127/#195).

Usage (from repo root):

    python3 scripts/agent_review/battery.py outputs/ai-commercial --semantic
      # full L1: L0 pre-filter + worklist + LLM verdicts (opt-in)
    python3 scripts/agent_review/battery.py outputs/ai-commercial
      # deterministic preview: L0 + worklist only (CI-safe, no LLM)
    python3 scripts/agent_review/battery.py outputs/ai-commercial --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_BLINDSPOTS_PATH = Path(__file__).resolve().parent / "blindspots.yaml"

# Blind-spot families that map to the file-name product families 1:1.
_FILE_FAMILY_MAP = {
    "digest": "digest",
    "magazine-digest": "magazine-digest",
    "column": "column",
    "premium-briefing": "premium-briefing",
    "enterprise-briefing": "enterprise-briefing",
    "report": "report",
    "presentation": "presentation",
    "tutorial": "tutorial",
}

# Cross-cutting manifests not tied to one file family.
_SPECIAL_FAMILIES = ("cross-domain", "all", "bilingual-domains")


def _load_blindspots() -> list[dict[str, Any]]:
    import yaml  # PyYAML is a project dependency

    with open(_BLINDSPOTS_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return data


def _family_of_file(path: Path) -> str:
    """Map a product file name to its blind-spot family (report.md -> report)."""
    return path.stem.lower()


def run_l0_gate(directory: Path) -> list[str]:
    """Run the L0 quality_gate over *directory*; return its defect lines.

    The battery only asks L1 about the semantic residue L0 does NOT flag —
    never re-judge what the deterministic gate already decided.
    """
    gate = _SCRIPTS_DIR / "quality_gate.py"
    proc = subprocess.run(
        [sys.executable, str(gate), str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [
        ln.strip()
        for ln in (proc.stdout or "").splitlines()
        if ln.strip().startswith("- ")
    ]
    return lines


def build_worklist(
    directory: Path,
    blindspots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the L1 worklist: product files x applicable blind spots.

    Each worklist item names the family, the file(s) to judge, and the
    check_desc + evidence_required from the manifest.  Special families
    (cross-domain / all / bilingual-domains) attach to the whole directory
    when its product set implies them.
    """
    files = sorted(directory.glob("*.md"))
    items: list[dict[str, Any]] = []

    for manifest in blindspots:
        family = manifest.get("family", "")
        if family in _SPECIAL_FAMILIES:
            continue  # handled below
        fam_files = [f for f in files if _family_of_file(f) == family]
        if not fam_files:
            continue
        for bs in manifest.get("blind_spots", []):
            items.append(
                {
                    "family": family,
                    "files": [str(f) for f in fam_files],
                    "blind_spot": bs["id"],
                    "name": bs.get("name", bs["id"]),
                    "check_desc": bs.get("check_desc", ""),
                    "evidence_required": bs.get("evidence_required", ""),
                }
            )

    # Cross-cutting families: attach once per directory when applicable.
    # cross-domain applies only when a cross-domain aggregate product is
    # actually present (its filename is not a 1:1 product family).  "all"
    # (cross-product entity consistency) needs >= 2 product files to compare.
    fams = {manifest.get("family") for manifest in blindspots}
    cross_domain_files = [f for f in files if "cross" in f.name.lower()]
    if "cross-domain" in fams and cross_domain_files:
        for bs in _bs_for(blindspots, "cross-domain"):
            items.append(
                {
                    "family": "cross-domain",
                    "files": [str(f) for f in cross_domain_files],
                    "blind_spot": bs["id"],
                    "name": bs.get("name", bs["id"]),
                    "check_desc": bs.get("check_desc", ""),
                    "evidence_required": bs.get("evidence_required", ""),
                }
            )
    if "all" in fams and len(files) >= 2:
        for bs in _bs_for(blindspots, "all"):
            items.append(
                {
                    "family": "all",
                    "files": [str(f) for f in files],
                    "blind_spot": bs["id"],
                    "name": bs.get("name", bs["id"]),
                    "check_desc": bs.get("check_desc", ""),
                    "evidence_required": bs.get("evidence_required", ""),
                }
            )
    return items


def _bs_for(blindspots: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
    for manifest in blindspots:
        if manifest.get("family") == family:
            return list(manifest.get("blind_spots", []))
    return []


def _detect_bilingual_domains(directory: Path) -> list[str]:
    """Best-effort bilingual-domain detection from the delivery dir name.

    ai-commercial (#190) and *-learning are bilingual by design.  The
    bilingual-domains manifest's local-market-presence blind spot applies
    only when one of these domains is under review.
    """
    name = directory.name.lower()
    if name in ("ai-commercial", "cross-domain"):
        return [name]
    if name.endswith("-learning"):
        return [name]
    return []


_FILE_SNIPPET_CHAR_LIMIT = 8000
_TRUNCATION_MARKER = "\u2026[truncated]"


def _read_file_snippet(path: str, limit: int = _FILE_SNIPPET_CHAR_LIMIT) -> str:
    """Return the first *limit* chars of a product file, marked if truncated.

    Products are local files the review runs against; the LLM is a stateless
    API call and cannot read them itself, so the caller embeds a bounded
    snippet in the prompt.  Truncated tails are explicitly marked so a
    judgment never silently bases itself on a partial file.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return f"<unreadable file: {path}>"
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_MARKER


def _judge_prompt(item: dict[str, Any]) -> str:
    """Build the judgment prompt for one worklist item (no vendor naming).

    The product files' actual contents are embedded (bounded to
    *limit* chars each) so the LLM, which is a stateless API call and cannot
    open local files, can judge against real text instead of file paths
    (#197).  The output contract below is aligned exactly with what
    :func:`_parse_markdown_verdicts` parses.
    """
    file_list = "\n".join(f"- {f}" for f in item["files"])
    snippets = "\n\n".join(
        f"--- File: {f} ---\n{_read_file_snippet(f)}" for f in item["files"]
    )
    return (
        "You are a quality reviewer for a knowledge-digest product family.\n"
        f"Family: {item['family']}\n"
        f"Files under review:\n{file_list}\n"
        f"Blind spot: {item['name']} ({item['blind_spot']})\n"
        f"What to check: {item['check_desc']}\n"
        f"Evidence required: {item['evidence_required']}\n\n"
        "File contents:\n"
        f"{snippets}\n\n"
        "Rules:\n"
        "- Verdict PASS only when the product satisfies the blind spot; "
        "FLAG when it violates it; ESCALATE when you cannot judge or it is "
        "a product-intent/value call for a human.\n"
        "- Honest hedges ('not disclosed', 'not provided in the sources') "
        "are CORRECT behavior — never FLAG them.\n"
        "- Every verdict MUST cite evidence (file:line or source URL). A "
        "verdict without evidence is invalid.\n"
        "- If you cannot reach a judgment for any reason, output ESCALATE — "
        "never PASS on an unverified claim.\n\n"
        "OUTPUT SCHEMA — respond with EXACTLY ONE block starting with the "
        "header '## Verdict', followed by these four lines:\n"
        "- **blind_spot**: <id>\n"
        "- **verdict**: PASS | FLAG | ESCALATE\n"
        "- **evidence**: <file:line or source URL>\n"
        "- **note**: <1-3 sentences>\n"
        "Output NOTHING outside that block.  Do not add prose before or "
        "after it.\n"
    )


def _parse_markdown_verdicts(text: str) -> list[dict[str, str]]:
    """Deterministically parse markdown verdict blocks (non-json_mode path).

    Expects one or more blocks of the form:

        ## Verdict
        - **blind_spot**: <id>
        - **verdict**: PASS | FLAG | ESCALATE
        - **evidence**: ...
        - **note**: ...

    Returns [{blind_spot, verdict, evidence, note}].  A block missing a
    required field is dropped (its item then falls back to ESCALATE at
    assembly — fail loud, never silent PASS).
    """
    out: list[dict[str, str]] = []
    for block in re.split(r"(?=^## Verdict)", text, flags=re.MULTILINE):
        if "## Verdict" not in block:
            continue
        entry: dict[str, str] = {}
        for key in ("blind_spot", "verdict", "evidence", "note"):
            m = re.search(
                rf"^\s*(?:- )?\*\*{re.escape(key)}\*\*:\s*(.+)$",
                block,
                re.MULTILINE,
            )
            if m:
                entry[key] = m.group(1).strip()
        if {"blind_spot", "verdict", "evidence"} <= entry.keys():
            out.append(entry)
    return out


def _judge_with_llm(prompt: str, want_json: bool) -> dict[str, Any]:
    """Call the config-driven LLM channel (vendor-agnostic, #195).

    Routes through ``autoinfo.llm.call_with_fallback`` with NO task routing
    (the base config model).  Structured output: when the resolved config
    declares json_mode we request JSON; otherwise the model returns a
    markdown verdict block parsed by :func:`_parse_markdown_verdicts`.

    FAIL LOUD: any exception or unparseable output surfaces as an
    ESCALATE-carrying result — never a PASS.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
        from autoinfo.llm import call_with_fallback

        if want_json:
            system = (
                "You are a rigorous product-quality reviewer. Respond with "
                "a single JSON object: "
                '{"verdict": "PASS"|"FLAG"|"ESCALATE", '
                '"evidence": "<file:line or URL>", "note": "<1-3 sentences>"}'
            )
            resp = call_with_fallback(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                task="",  # base config model — no judgment pin (battery is not a hard gate)
            )
            verdict = _extract_json_verdict(resp)
            if verdict is None:
                return _escalate("unparseable LLM output", _extract_text(resp)[:200])
            return verdict
        # Markdown path.
        resp = call_with_fallback(
            messages=[
                {"role": "user", "content": prompt},
            ],
            task="",
        )
        raw = _extract_text(resp)
        blocks = _parse_markdown_verdicts(raw)
        if not blocks:
            return _escalate("no parseable verdict block in LLM output", raw[:200])
        b = blocks[0]
        return {
            "verdict": str(b.get("verdict", "ESCALATE")).upper(),
            "evidence": b.get("evidence", ""),
            "note": b.get("note", ""),
        }
    except Exception as exc:  # noqa: BLE001 - fail loud for ANY channel failure
        return _escalate(f"LLM channel unreachable: {exc}", "")


def _extract_json_verdict(content: Any) -> dict[str, Any] | None:
    """Pull {verdict, evidence, note} from a JSON-mode LLM response."""
    text = _extract_text(content)
    # Strip possible ```json fences.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "verdict" not in data:
        return None
    return {
        "verdict": str(data.get("verdict", "ESCALATE")).upper(),
        "evidence": str(data.get("evidence", "")),
        "note": str(data.get("note", "")),
    }


def _extract_text(resp: Any) -> str:
    """Extract the message text from an LLM response.

    call_with_fallback returns a litellm ModelResponse whose text lives at
    .choices[0].message.content; str() of it yields the repr with literal
    backslash-n escapes that defeat line-based markdown parsing and
    json.loads.  Robust to providers that already return a plain string.
    """
    if hasattr(resp, "choices") and resp.choices:
        msg = resp.choices[0].message
        text = getattr(msg, "content", None)
        if isinstance(text, str):
            return text
    return str(resp)


def _escalate(reason: str, detail: str) -> dict[str, Any]:
    return {
        "verdict": "ESCALATE",
        "evidence": f"battery internal: {reason}",
        "note": reason + (f" — {detail}" if detail else ""),
    }


def _channel_json_capable() -> bool:
    """Probe whether the configured channel supports structured output.

    Reads config.llm.json_mode (declared capability).  No vendor probing
    beyond the config — a deployment that declares json_mode but fails it
    falls back to the markdown parser via the ESCALATE path.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        config = load_config(config_path) if config_path else None
        if config is None:
            return False
        return bool(config.llm.json_mode)
    except Exception:
        return False


def run_battery(directory: Path, *, semantic: bool = False) -> dict[str, Any]:
    """Run the L1 battery over *directory*; return the full report dict."""
    blindspots = _load_blindspots()
    l0_defects = run_l0_gate(directory)
    worklist = build_worklist(directory, blindspots)
    bilingual = _detect_bilingual_domains(directory)
    if bilingual:
        # Attach the local-market-presence blind spot for bilingual domains.
        for bs in _bs_for(blindspots, "bilingual-domains"):
            worklist.append(
                {
                    "family": "bilingual-domains",
                    "files": [str(f) for f in sorted(directory.glob("*.md"))],
                    "blind_spot": bs["id"],
                    "name": bs.get("name", bs["id"]),
                    "check_desc": bs.get("check_desc", ""),
                    "evidence_required": bs.get("evidence_required", ""),
                }
            )

    want_json = _channel_json_capable()
    verdicts: list[dict[str, Any]] = []
    if semantic:
        for item in worklist:
            prompt = _judge_prompt(item)
            res = _judge_with_llm(prompt, want_json=want_json)
            res["blind_spot"] = item["blind_spot"]
            res["family"] = item["family"]
            res["file"] = item["files"][0] if item["files"] else str(directory)
            verdicts.append(res)

    reviewed = [f"{v['blind_spot']} ({v['family']})" for v in verdicts]
    return {
        "directory": str(directory),
        "l0_defects": l0_defects,
        "worklist": worklist,
        "verdicts": verdicts,
        "honesty": {
            "reviewed": reviewed if verdicts else [],
            "not_reviewed": (
                [f"{i['blind_spot']} ({i['family']})" for i in worklist]
                if not semantic
                else []
            ),
            "channel": "deterministic preview (no --semantic)" if not semantic
            else ("config.llm json_mode" if want_json else "config.llm markdown"),
        },
        "summary": {
            "l0_failed": bool(l0_defects),
            "flagged": sum(1 for v in verdicts if v["verdict"] == "FLAG"),
            "escalated": sum(1 for v in verdicts if v["verdict"] == "ESCALATE"),
            "passed": sum(1 for v in verdicts if v["verdict"] == "PASS"),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="delivery directory (domain-organized products)"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the machine-readable report"
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="enable the LLM verdict pass (opt-in; default runs L0 + worklist only)",
    )
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"ERROR: {args.directory} is not a directory", file=sys.stderr)
        return 2

    report = run_battery(args.directory, semantic=args.semantic)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if (report["summary"]["flagged"] or report["summary"]["escalated"]) else 0

    print(f"L1 battery — {report['directory']}")
    print(f"L0 defects: {len(report['l0_defects'])}")
    if report["l0_defects"]:
        for d in report["l0_defects"][:8]:
            print(f"  L0: {d[:110]}")
    print(f"Worklist: {len(report['worklist'])} item(s)")
    if not args.semantic:
        for it in report["worklist"]:
            print(f"  [judge] {it['blind_spot']} ({it['family']}) -> {it['files'][0]}")
        print("L1_PREVIEW_OK (L0 + worklist; rerun with --semantic for verdicts)")
        return 0
    for v in report["verdicts"]:
        print(f"  [{v['verdict']}] {v['blind_spot']} ({v['family']}): {v['note'][:100]}")
    print("Honesty:", report["honesty"]["reviewed"])
    flagged = report["summary"]["flagged"]
    escalated = report["summary"]["escalated"]
    print(f"SUMMARY: {report['summary']['passed']} PASS / {flagged} FLAG / {escalated} ESCALATE")
    return 1 if (flagged or escalated) else 0


if __name__ == "__main__":
    sys.exit(main())
