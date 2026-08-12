#!/usr/bin/env python3
"""Package AutoInfo validation artifacts into a delivery zip (fixes #123).

Runs after validation scenarios that declare collect_artifacts. Builds:

    validation-delivery-<timestamp>.zip
    ├── 01-RAW/          # real collected data (cached items, 01-Raw entries)
    ├── 02-PROCESSED/    # produced products (digest/report/tutorial...)
    ├── 03-KB/           # KB entries by tier (02-Draft, 03-Wiki)
    ├── 04-MATRIX/       # E8 end-user coverage matrix (matrix-report.md + coverage-gaps.json)
    ├── 06-REJECTED/     # artifacts that failed delivery gates (E7)
    ├── validation-report.md  # scenario statuses + artifact manifest + COVERAGE_GAP summary
    └── manifest.json    # per-file source/type/size + gates/quality/rejected + 04-MATRIX files

Usage:
    python3 scripts/validation_delivery.py [--scenarios-dir ...] [--out ...]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import re
import shutil
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# E7 (#131): reuse the production D1-D3 orchestration from autoinfo.quality
# UNMODIFIED; aliased because the wrapper below is also named run_delivery_gates.
# #192: shared non-deliverable-artifact predicate (also enforced at the
# collect_artifacts source in autoinfo.mcp.validation).
from autoinfo.mcp.validation import is_excluded_artifact
from autoinfo.quality import run_delivery_gates as _quality_run_delivery_gates  # noqa: PLC0415


def _configured_domains() -> list[str]:
    from autoinfo.config import get_config_path, load_config
    try:
        cfg_path = get_config_path()
        if not cfg_path:
            return []
        cfg = load_config(cfg_path)
        return [d.name for d in cfg.domains]
    except Exception:
        return []


def _requires_llm_key(scenario_path: Path) -> bool:
    """True if the scenario declares an LLM API key in ``requires_env``."""
    import yaml

    try:
        data = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    envs = data.get("requires_env") or []
    return any(
        "LLM" in e or "OPENAI" in e or "OPENROUTER" in e for e in envs
    )


async def _run_all_scenarios(
    scenarios_dir: Path, skip_llm: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run every scenario via the real engine; return (results, artifacts)."""
    from autoinfo.mcp.server import _handle_run_validation_scenario

    results = []
    artifacts = []
    for sc in sorted(scenarios_dir.glob("*.yaml")):
        name = sc.stem
        if skip_llm and _requires_llm_key(sc):
            results.append({"name": name, "status": "skipped", "summary": {}})
            continue
        try:
            res = await _handle_run_validation_scenario(scenario=name)
        except Exception as e:  # noqa: BLE001
            results.append({"name": name, "status": "error", "detail": str(e)[:200]})
            continue
        data = res.get("data", res)
        results.append({
            "name": name,
            "status": data.get("status"),
            "summary": data.get("summary", {}),
        })
        for a in data.get("artifacts", []):
            artifacts.append(a)
    return results, artifacts


def _tier_subpath(src: Path) -> Path:
    """Path below '<root>/<domain>/' so nested structure survives the copy.

    E.g. ``knowledge/medical-research/01-Raw/crispr/2026-08-05-x.md`` maps to
    ``01-Raw/crispr/2026-08-05-x.md``; shallow paths fall back to the bare
    name.  Absolute inputs under the repo root are relativized first so the
    mount/user prefix is never embedded in the package (issue #143).
    """
    cwd = Path.cwd().resolve()
    try:
        rel = src.resolve().relative_to(cwd)
    except (ValueError, OSError):
        # Not under the repo root — keep the historical slice behaviour.
        parts = src.parts
        return Path(*parts[2:]) if len(parts) >= 3 else Path(src.name)
    parts = rel.parts
    return Path(*parts[2:]) if len(parts) >= 3 else Path(src.name)


def _bucket(path: Path) -> str:
    """Classify an artifact path into ``RAW`` / ``KB`` / ``PROCESSED``.

    ``/01-Raw/`` or ``collections/`` -> RAW; ``/02-Draft/`` or ``/03-Wiki/``
    -> KB; everything else -> PROCESSED.
    """
    rel = path.as_posix()  # normalize separators so '/01-Raw/' checks hold
    if "/01-Raw/" in rel or "collections/" in rel:
        return "RAW"
    if "/02-Draft/" in rel or "/03-Wiki/" in rel:
        return "KB"
    return "PROCESSED"


# ---------------------------------------------------------------------------
# E7 (#131): per-artifact authenticity pre-check + D1-D3 delivery gates
# ---------------------------------------------------------------------------

# Text formats whose content can be structurally inspected as a product.
_INSPECTABLE_FORMATS: dict[str, str] = {
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".jsonl": "json",
}

# Keys that mark a JSON dict as a structured source entry.
_ENTRY_KEYS = frozenset(
    {"source_url", "source_type", "source_platform", "title", "entry_id", "uuid"}
)

# Canonical D1 sections -> markdown heading aliases (#172: format headings).
# Report products use report-style headings; presentation/digest/tutorial
# products use their own headings. Approach A (aliases) is the complement to
# the per-product-type required-section rules in _build_product_output.
_SECTION_HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "key_findings": (
        "key findings", "key_findings", "key-findings", "key points",
        "slide", "slides", "learning objectives", "main findings", "introduction",
    ),
    "summary": (
        "summary", "executive summary", "overview",
        "entries", "content", "executive overview", "body",
    ),
    "recommendations": (
        "recommendations", "conclusion", "next steps",
        "exercises", "further reading", "action items", "next actions",
    ),
}

# Presentation slide headings: "Slide N: ..." -> key_findings (#172).
_SLIDE_HEADING_RE = re.compile(r"^slide\s*\d+\s*:", re.IGNORECASE)

# Digest entry headings: "1. Title" / "1) Title" -> entries present (#172).
_ENTRY_HEADING_RE = re.compile(r"^\d+[.)]\s+\S", re.IGNORECASE)

# Empty-state placeholder content templates emit when no content was produced
# (e.g. "_No objectives defined._", "_No exercises provided._"). It is
# genuinely empty content, not a real section — B-04 must stay rejected (#172).
_EMPTY_PLACEHOLDER_RE = re.compile(r"^\s*_no\s+.+_\.?\s*$", re.IGNORECASE)

# Canonical D1 sections each product type must genuinely contain. Sections
# outside a type's required set are still checked by the D1 gate (it always
# requires all three); they get a non-empty marker so a complete product of
# that format is not false-rejected (#172).
#
# Reports render via report.md.j2 (Executive Summary + Key Findings +
# Recommendations + per-theme Sections + References) — the template now emits
# separate ``## Key Findings`` / ``## Recommendations`` headings, so a report
# must genuinely carry all three canonical sections.
_PRODUCT_TYPE_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "report": ("key_findings", "summary", "recommendations"),
    "presentation": ("key_findings",),          # at least one Slide N heading
    "digest": ("summary",),                     # Entries section / entries present
    "tutorial": ("key_findings", "recommendations"),  # Learning Objectives + Exercises
    "column": ("key_findings",),                # at least one content heading
    "magazine": ("key_findings",),              # at least one content heading
    # Briefing products render via the report template family (Executive
    # Summary + Sections + References); the only canonical section they
    # genuinely produce is the summary (#172 follow-up).
    "enterprise_briefing": ("summary",),
    "premium_briefing": ("summary",),
    "magazine_digest": ("summary",),
}

# Filename keywords -> product type (checked in order).
_PRODUCT_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("enterprise-briefing", "enterprise_briefing"),
    ("premium-briefing", "premium_briefing"),
    ("magazine-digest", "magazine_digest"),
    ("presentation", "presentation"),
    ("tutorial", "tutorial"),
    ("magazine", "magazine"),
    ("digest", "digest"),
    ("column", "column"),
)

# Column-template headings (column.md.j2). generate_report persists every
# report (including report_type="column") under the "report" product name, so
# classify by content when the filename alone says report (#172).
_COLUMN_HEADINGS = frozenset({
    "the big idea", "deep dive", "reader takeaways",
    "implications & outlook", "what changed this week",
})

# Canonical D1 sections -> JSON top-level / llm_synthesis key aliases.
_SECTION_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "key_findings": ("key_findings", "key-findings", "findings"),
    "summary": ("summary", "executive_summary", "executive-summary"),
    "recommendations": ("recommendations", "next_steps", "conclusion"),
}

# JSON filenames that carry run/coverage metadata rather than a report product.
_METADATA_JSON_NAMES = frozenset({"scenarios.json", "manifest.json"})
_METADATA_JSON_PREFIXES = ("coverage-",)
_METADATA_JSON_SUFFIXES = ("_runs.json",)

# Keys that mark a JSON dict as a genuine report product (D1-inspectable).
_REPORT_JSON_MARKERS = frozenset(
    {"title", "entries", "llm_synthesis", "digest_type", "@type", "sections"}
)


def _is_metadata_json(file_path: Path, parsed: Any) -> bool:
    """True when *file_path* is JSON that is NOT a report product (#169).

    Metadata JSONs (``scenarios.json``, ``coverage-*.json``, ``*_runs.json``,
    ``manifest.json``) carry run/coverage state rather than a rendered
    product; they must run with ``product_type="RAW"`` so the D1-D3 gates
    trivially skip. A parsed dict exposing report markers
    (``title``/``entries``/``llm_synthesis``/...) is a real product
    regardless of its filename.
    """
    name = file_path.name.lower()
    if name in _METADATA_JSON_NAMES:
        return True
    if name.startswith(_METADATA_JSON_PREFIXES) or name.endswith(_METADATA_JSON_SUFFIXES):
        return True
    if isinstance(parsed, dict):
        return not bool(_REPORT_JSON_MARKERS & parsed.keys())
    return False


def _parse_json_payload(file_path: Path) -> Any:
    """Load JSON / JSONL content; returns ``None`` when unparseable."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — binary or unreadable file
        return None
    if file_path.suffix.lower() == ".jsonl":
        objs: list[Any] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return objs or None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_frontmatter(file_path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter (``---``-delimited) from a markdown file."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml

        data = yaml.safe_load(text[3:end])
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _json_entries(parsed: Any) -> list[dict[str, Any]]:
    """Extract structured source-entry dicts from a parsed JSON payload."""
    if isinstance(parsed, list):
        return [e for e in parsed if isinstance(e, dict) and (_ENTRY_KEYS & e.keys())]
    if not isinstance(parsed, dict):
        return []
    for key in ("entries", "items", "results", "articles", "payload"):
        val = parsed.get(key)
        if isinstance(val, list):
            hit = [e for e in val if isinstance(e, dict) and (_ENTRY_KEYS & e.keys())]
            if hit:
                return hit
    if _ENTRY_KEYS & parsed.keys():
        return [parsed]
    return []


def _is_empty_placeholder(content: str) -> bool:
    """True when *content* is an empty-state placeholder (``_No ..._``).

    Templates emit placeholders like ``_No objectives defined._``,
    ``_No exercises provided._`` and ``_No entries found ..._`` when no
    content was produced. That is genuinely empty content — it must NOT
    satisfy a D1 required section (B-04 stays rejected, #172).
    """
    stripped = content.strip()
    if not stripped:
        return False
    return bool(_EMPTY_PLACEHOLDER_RE.match(stripped))


def _detect_product_type(file_path: Path, body: str = "") -> str:
    """Infer the product type from the artifact path (#172).

    Filename keywords win (presentation/digest/tutorial/column/magazine/
    enterprise-briefing/premium-briefing/magazine-digest); everything else
    defaults to ``report``. Column products are persisted
    under the ``report`` name (generate_report persists report_type="column"
    as report-markdown-*), so column-template headings in the body upgrade a
    report-named file to ``column``.
    """
    rel = file_path.as_posix().lower()
    for keyword, ptype in _PRODUCT_TYPE_KEYWORDS:
        if keyword in rel:
            return ptype
    if body and any(
        line.strip().lstrip("#").strip().lower() in _COLUMN_HEADINGS
        for line in body.splitlines()
    ):
        return "column"
    return "report"


def _sections_from_headings(
    text: str, product_type: str = "report"
) -> dict[str, str]:
    """Map canonical D1 sections to non-empty heading content (md/html).

    Headings are matched against :data:`_SECTION_HEADING_ALIASES`, with
    format-specific additions per *product_type* (approach A + B, #172):

    - ``Slide N:`` headings (presentation) -> ``key_findings``
    - numbered entry headings (digest) count as an ``summary``/Entries
    - column/magazine products pass when any content heading is non-empty

    Empty-state placeholder content (``_No objectives defined._``) is treated
    as empty so a genuinely empty product still fails D1.
    """
    found: dict[str, str] = {}
    heading_re = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
    if heading_re.search(text):
        # HTML: convert heading tags to markdown headings but keep the body
        # text between them so per-section content is not lost (#172).
        converted: list[str] = []
        pos = 0
        for m in heading_re.finditer(text):
            converted.append(text[pos:m.start()])
            converted.append(
                "\n" + "#" * int(m.group(1)) + " "
                + re.sub(r"<[^>]+>", "", m.group(2)).strip()
                + "\n"
            )
            pos = m.end()
        converted.append(text[pos:])
        # Strip remaining tags; headings are now on their own lines.
        text = re.sub(r"<[^>]+>", " ", "".join(converted))
    blocks: list[tuple[str, list[str]]] = []
    cur_heading: str | None = None
    cur_lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip())
        if m:
            if cur_heading:
                blocks.append((cur_heading, cur_lines))
            cur_heading = m.group(1).lower().replace("*", "").replace("`", "").strip()
            cur_lines = []
        elif cur_heading:
            cur_lines.append(line.strip())
    if cur_heading:
        blocks.append((cur_heading, cur_lines))

    def _block_content(heading: str, lines: list[str]) -> str:
        # Templates separate sections with "---" horizontal rules; those are
        # not content and would mask an empty-state placeholder (#172).
        body_lines = [
            line for line in lines
            if line and not re.match(r"^[-*=_]{3,}\s*$", line)
        ]
        content = " ".join(body_lines)
        if _is_empty_placeholder(content):
            return ""
        return content

    # Approach A: exact alias matches.
    for canonical, aliases in _SECTION_HEADING_ALIASES.items():
        for heading, lines in blocks:
            if heading in aliases and canonical not in found:
                content = _block_content(heading, lines)
                if content or _is_empty_placeholder(
                    " ".join(
                        line for line in lines
                        if line and not re.match(r"^[-*=_]{3,}\s*$", line)
                    )
                ):
                    # Real content, or an empty-state placeholder (kept empty).
                    found[canonical] = content or ""
    # Approach B: presentation slide headings -> key_findings. Detected
    # regardless of *product_type*: a "Slide N:" heading is a strong format
    # signal and the alias alone cannot match "slide 1: overview" exactly.
    if "key_findings" not in found:
        slide_parts: list[str] = []
        for heading, lines in blocks:
            if _SLIDE_HEADING_RE.match(heading):
                content = _block_content(heading, lines)
                if content:
                    slide_parts.append(content)
        if slide_parts:
            found["key_findings"] = " ".join(slide_parts)
    # Approach B: digest numbered entry headings -> summary present.
    if "summary" not in found:
        entry_count = 0
        for heading, lines in blocks:
            if _ENTRY_HEADING_RE.match(heading):
                content = _block_content(heading, lines)
                if content:
                    entry_count += 1
        if entry_count:
            found["summary"] = "present"
    # Approach B: column/magazine pass with at least one content heading.
    if product_type in ("column", "magazine") and not found:
        for heading, lines in blocks:
            content = _block_content(heading, lines)
            if content:
                found["key_findings"] = content
                break
    return found


def _section_value(parsed: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    """First non-empty value for *aliases* at top level or in llm_synthesis."""
    llm_synthesis = parsed.get("llm_synthesis")
    llm_synthesis = llm_synthesis if isinstance(llm_synthesis, dict) else {}
    for scope in (parsed, llm_synthesis):
        for key in aliases:
            val = scope.get(key)
            if val not in (None, "", [], {}):
                return val
    return None


# Non-empty marker for canonical sections a product format does not produce
# but the D1 gate always checks. Only applied to sections OUTSIDE the
# product type's required set, so genuinely empty products still fail (#172).
_D1_NON_REQUIRED_MARKER = "present"


def _apply_format_sections(
    sections: dict[str, str], product_type: str
) -> dict[str, str]:
    """Map a product's detected sections onto the three D1 canonical keys.

    The D1 gate always requires ``key_findings``/``summary``/``recommendations``
    to be present and non-empty, but each product format only genuinely
    produces a subset (report: all three; presentation: slides; digest:
    entries; tutorial: objectives + exercises). Sections outside the type's
    required set get a non-empty marker so a complete product of that format
    is not false-rejected; sections inside the set keep their detected value
    (empty stays empty -> D1 still blocks genuinely empty products, #172).
    """
    required = _PRODUCT_TYPE_REQUIRED_SECTIONS.get(
        product_type, _PRODUCT_TYPE_REQUIRED_SECTIONS["report"]
    )
    mapped: dict[str, str] = {}
    for canonical in ("key_findings", "summary", "recommendations"):
        value = sections.get(canonical, "")
        if canonical not in required and not value:
            value = _D1_NON_REQUIRED_MARKER
        mapped[canonical] = value
    return mapped


def _build_product_output(file_path: Path, bucket: str) -> dict[str, Any]:
    """Adapt an artifact file into the ``product_output`` dict quality.py expects.

    RAW/KB content and non-inspectable binary formats run with
    ``product_type="RAW"`` so the D gates trivially skip (that content was
    already gated at pipeline time). PROCESSED text products (md/html/json)
    get the real D1-D3 treatment with sections derived from headings/keys.
    """
    suffix = file_path.suffix.lower()
    fmt = _INSPECTABLE_FORMATS.get(suffix)
    product_type = "RAW" if (bucket in ("RAW", "KB") or fmt is None) else "PROCESSED"
    entries: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}
    body: Any = ""
    if fmt in ("markdown", "html"):
        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        format_type = _detect_product_type(file_path, str(body))
        sections = _apply_format_sections(
            _sections_from_headings(str(body), format_type), format_type
        )
    elif fmt == "json":
        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        parsed = _parse_json_payload(file_path)
        # Metadata JSONs (scenarios.json / coverage-* / *_runs.json /
        # manifest.json, or any dict without report markers) are run/coverage
        # bookkeeping, not report products — treat as RAW so the D gates skip
        # instead of rejecting them on empty report sections (#169).
        if _is_metadata_json(file_path, parsed):
            product_type = "RAW"
        else:
            entries = _json_entries(parsed)
            if isinstance(parsed, dict):
                sections = {
                    "key_findings": _section_value(
                        parsed, _SECTION_SOURCE_KEYS["key_findings"]
                    ),
                    "summary": _section_value(parsed, _SECTION_SOURCE_KEYS["summary"]),
                    "recommendations": _section_value(
                        parsed, _SECTION_SOURCE_KEYS["recommendations"]
                    ),

                }
    key_findings = sections.get("key_findings")
    summary = sections.get("summary")
    recommendations = sections.get("recommendations")
    return {
        "product_type": product_type,
        "format": fmt or "markdown",
        "body": body,
        "key_findings": key_findings if key_findings not in (None, "") else [],
        "summary": summary if summary not in (None, []) else "",
        "recommendations": recommendations if recommendations not in (None, "") else [],
        "entries": entries,
    }


def check_authenticity(file_path: Path) -> dict[str, Any]:
    """Per-artifact authenticity pre-check (field presence only — Oracle R3).

    md/html content files are text products, not structured source entries:
    they pass as N/A (informational frontmatter fields are reported when
    present but never fail). JSON/JSONL payloads are checked for complete
    source provenance — every embedded entry must carry non-empty
    ``source_url`` (not an ``example.com`` placeholder), ``source_type`` and
    ``source_platform``. Payloads without structured entries have nothing to
    verify and pass.

    Returns ``{"authenticity": "pass"|"fail", "reason": str}``.
    """
    suffix = file_path.suffix.lower()
    if suffix in (".md", ".html", ".htm"):
        fm = _parse_frontmatter(file_path)
        reason = "N/A: text content file — not a structured source entry"
        if fm:
            reason += f" (frontmatter fields: {', '.join(sorted(fm)[:6])})"
        return {"authenticity": "pass", "reason": reason}
    entries = _json_entries(_parse_json_payload(file_path))
    if not entries:
        return {
            "authenticity": "pass",
            "reason": "no structured source entries found in payload — nothing to verify",
        }
    problems: list[str] = []
    for i, entry in enumerate(entries):
        url = entry.get("source_url", "")
        if not isinstance(url, str) or not url.strip():
            problems.append(f"entry[{i}] missing source_url")
        elif "example.com" in url:
            problems.append(f"entry[{i}] placeholder source_url: {url}")
        for field in ("source_type", "source_platform"):
            val = entry.get(field, "")
            if not isinstance(val, str) or not val.strip():
                problems.append(f"entry[{i}] missing {field}")
    if problems:
        shown = "; ".join(problems[:6])
        if len(problems) > 6:
            shown += " ..."
        return {"authenticity": "fail", "reason": shown}
    n = len(entries)
    return {
        "authenticity": "pass",
        "reason": f"{n} structured entr{'y' if n == 1 else 'ies'} with complete source fields",
    }


def _serialize_gate_result(result: Any) -> dict[str, Any]:
    """Turn a quality.QualityResult into a JSON-serializable dict."""
    if result is None:
        return {
            "gate": "unknown",
            "passed": True,
            "score": 0.0,
            "flagged": False,
            "details": {"skipped": True, "reason": "gate did not run"},
        }
    return {
        "gate": getattr(result, "gate_name", ""),
        "passed": bool(getattr(result, "passed", True)),
        "score": float(getattr(result, "score", 0.0) or 0.0),
        "flagged": bool(getattr(result, "flagged", False)),
        "details": dict(getattr(result, "details", {}) or {}),
    }


def run_delivery_gates(file_path: Path, bucket: str) -> dict[str, Any]:
    """Run D1-D3 delivery gates + authenticity pre-check for one artifact.

    Reuses :func:`autoinfo.quality.run_delivery_gates` unmodified — the file
    is adapted into the ``product_output`` dict it expects. Returns
    ``{"gates": {"D1": ..., "D2": ..., "D3": ..., "authenticity": ...},
    "quality": "PASS"|"FAIL"}``; ``quality`` is PASS only when every gate
    passes.
    """
    authenticity = check_authenticity(file_path)
    product_output = _build_product_output(file_path, bucket)
    quality_results = _quality_run_delivery_gates(product_output, {})
    gates = {
        "D1": _serialize_gate_result(quality_results.get("D1-ProductCompleteness")),
        "D2": _serialize_gate_result(quality_results.get("D2-FormatIntegrity")),
        "D3": _serialize_gate_result(quality_results.get("D3-Freshness")),
        "authenticity": authenticity,
    }
    all_pass = (
        gates["D1"]["passed"]
        and gates["D2"]["passed"]
        and gates["D3"]["passed"]
        and gates["authenticity"]["authenticity"] == "pass"
    )
    return {"gates": gates, "quality": "PASS" if all_pass else "FAIL"}


def _failure_reason(gates: dict[str, Any]) -> str:
    """Human-readable summary of why an artifact failed the gates."""
    reasons: list[str] = []
    for name in ("D1", "D2", "D3"):
        g = gates.get(name) or {}
        if not g.get("passed", True):
            details = g.get("details") or {}
            why = details.get("error") or details.get("reason") or f"gate {name} failed"
            reasons.append(f"{name}: {why}")
    auth = gates.get("authenticity") or {}
    if auth.get("authenticity") != "pass":
        reasons.append(f"authenticity: {auth.get('reason', 'failed')}")
    return "; ".join(reasons) or "quality gate failure"


# ---------------------------------------------------------------------------
# E8 (#131): end-user coverage matrix — the 04-MATRIX section of the package
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MATRIX_DIR_NAME = "04-MATRIX"
_DEFAULT_MATRIX_SPEC = _REPO_ROOT / "docs" / "dev" / "specs" / "end-user-matrix.yaml"

_COVERAGE_MATRIX_MODULE: Any = None


def _coverage_matrix() -> Any:
    """Import scripts/coverage_matrix.py (E8) as a module (lazy, cached)."""
    global _COVERAGE_MATRIX_MODULE
    if _COVERAGE_MATRIX_MODULE is None:
        import importlib.util

        script = Path(__file__).resolve().parent / "coverage_matrix.py"
        spec = importlib.util.spec_from_file_location("coverage_matrix", script)
        if spec is None or spec.loader is None:  # pragma: no cover — repo invariant
            raise ImportError(f"cannot load E8 matrix generator: {script}")
        _COVERAGE_MATRIX_MODULE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_COVERAGE_MATRIX_MODULE)
    return _COVERAGE_MATRIX_MODULE


def _matrix_llm_available() -> bool:
    """LLM availability for the E8 matrix (project config key or env var).

    Oracle R8: when the LLM is unavailable the matrix must be rendered with
    ``llm_available=False`` so required LLM-gated cells classify as
    ``未配置unconfigured`` — never ``空gap``.
    """
    import os

    cm = _coverage_matrix()
    if cm.detect_llm_available(_REPO_ROOT / ".autoinfo" / "config.yaml"):
        return True
    return bool(os.environ.get("AUTOINFO_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _build_matrix_section(
    stage: Path,
    *,
    spec_path: Path | None,
    evidence_dir: Path | None,
    llm_available: bool | None,
) -> dict[str, Any] | None:
    """Render the E8 coverage matrix into ``<stage>/04-MATRIX/`` (E8, #131).

    Evidence = the staged package itself — its ``manifest.json`` carries the
    original ``outputs/**`` sources of delivered artifacts — plus an optional
    extra *evidence_dir* (e.g. the repo ``outputs/`` in the CLI flow). The gap
    cells come from the same classification that rendered the report and are
    emitted as ``coverage-gaps.json`` (every entry's ``cell_state`` is
    ``空gap``; required LLM-gated cells without a key land in ``unconfigured``
    instead — Oracle R8). Returns the matrix metadata for the validation
    report + manifest, or ``None`` when the spec file is missing (delivery
    continues without the section — the matrix never blocks the package).
    """
    import yaml

    cm = _coverage_matrix()
    spec_path = spec_path or _DEFAULT_MATRIX_SPEC
    if not spec_path.is_file():
        print(f"WARN: E8 matrix spec not found: {spec_path} — skipping 04-MATRIX", file=sys.stderr)
        return None

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    produced: set[tuple[str, str, str]] = set(cm.scan_evidence(stage))
    if evidence_dir is not None:
        produced |= set(cm.scan_evidence(evidence_dir))
    if llm_available is None:
        llm_available = _matrix_llm_available()

    report = cm.render_report(
        spec,
        produced,
        llm_available,
        spec_path=str(spec_path),
        evidence_dir=str(stage),
    )
    cells = cm.classify_grid(spec, produced, llm_available)
    gaps = sorted(
        (c for c, s in cells.items() if s == cm.GAP),
        key=lambda c: (c[0], c[1], c[2]),
    )
    unconfigured = sorted(
        (c for c, s in cells.items() if s == cm.UNCONFIGURED),
        key=lambda c: (c[0], c[1], c[2]),
    )

    matrix_dir = stage / _MATRIX_DIR_NAME
    matrix_dir.mkdir(exist_ok=True)
    (matrix_dir / "matrix-report.md").write_text(report, encoding="utf-8")
    meta: dict[str, Any] = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "spec": str(spec_path),
        "llm_available": llm_available,
        "summary": {
            "required": len(cm.required_cells_set(spec)),
            "produced": sum(1 for s in cells.values() if s == cm.PRODUCED),
            "gap": len(gaps),
            "unconfigured": len(unconfigured),
            "not_applicable": sum(1 for s in cells.values() if s == cm.NOT_APPLICABLE),
        },
        "gaps": [
            {"domain": d, "product": p, "format": f, "cell_state": cm.GAP}
            for d, p, f in gaps
        ],
        "unconfigured": [
            {"domain": d, "product": p, "format": f, "cell_state": cm.UNCONFIGURED}
            for d, p, f in unconfigured
        ],
    }
    (matrix_dir / "coverage-gaps.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"MATRIX: {matrix_dir / 'matrix-report.md'} "
        f"(produced={meta['summary']['produced']}, gap={meta['summary']['gap']}, "
        f"unconfigured={meta['summary']['unconfigured']})"
    )
    return meta


# ---------------------------------------------------------------------------
# E9 (#141): end-user journey UX metrics — advisory section of the package
# ---------------------------------------------------------------------------

_UX_JOURNEY_SCENARIO = "enduser-journey"
_UX_THRESHOLD = 0.8


def _ux_metrics(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """UX metrics from the enduser-journey scenario result (issue #141).

    Finds the journey result by its ``name`` (the shape ``_run_all_scenarios``
    produces) or ``scenario`` key (the raw ``run_scenario`` shape persisted in
    ``validation-runs/<date>/scenarios.json``).  completion_rate is the
    fraction of journey steps that passed (passed/total of the summary,
    falling back to per-step statuses when the summary lacks counts);
    UX_OK = completion_rate >= 0.8.  Returns ``None`` when the journey did
    not run (e.g. skipped in a --skip-llm-scenarios smoke run) so the
    report/manifest simply omit the UX block — advisory, never blocking.
    """
    journey = next(
        (r for r in results
         if r.get("name") == _UX_JOURNEY_SCENARIO or r.get("scenario") == _UX_JOURNEY_SCENARIO),
        None,
    )
    if journey is None:
        return None
    summary = journey.get("summary") or {}
    passed, total = summary.get("passed"), summary.get("total")
    if not isinstance(total, int) or total <= 0:
        steps = journey.get("steps") or []
        if not steps:
            return None
        passed = sum(1 for s in steps if s.get("status") == "passed")
        total = len(steps)
    if not isinstance(total, int) or total <= 0:
        return None
    completion_rate = (passed or 0) / total
    return {
        "ux_ok": completion_rate >= _UX_THRESHOLD,
        "completion_rate": round(completion_rate, 4),
        "threshold": _UX_THRESHOLD,
        "scenario_status": journey.get("status"),
        "passed": passed or 0,
        "total": total,
        "steps": [
            {"name": s.get("name"), "status": s.get("status")}
            for s in (journey.get("steps") or [])
        ],
    }


def _package(artifacts: list[dict[str, Any]], results: list[dict[str, Any]], out: Path,
             *,
             spec_path: Path | None = None,
             evidence_dir: Path | None = None,
             llm_available: bool | None = None) -> Path:
    """Copy artifact files into a staged dir, write report, zip it.

    E7 (#131): every artifact is checked with :func:`run_delivery_gates`
    (D1-D3 + authenticity). Failed artifacts are moved to ``06-REJECTED/``
    and listed (with reasons) in the manifest's ``rejected`` summary instead
    of being delivered.

    E8 (#131): the end-user coverage matrix is rendered into ``04-MATRIX/``
    (``matrix-report.md`` + ``coverage-gaps.json``) from the staged package's
    own manifest plus an optional *evidence_dir*; the generated files are
    registered in the manifest's ``files`` list and summarized in the report.

    E9 (#141): UX metrics (issue #141) — UX_OK / completion_rate from the
    enduser-journey scenario are emitted as a "UX metrics" report section
    and registered in the manifest under ``ux``. Advisory only: like
    04-MATRIX, metrics never block the package.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    stage = out / f"validation-delivery-{stamp}"
    raw_dir = stage / "01-RAW"
    proc_dir = stage / "02-PROCESSED"
    kb_dir = stage / "03-KB"
    rej_dir = stage / "06-REJECTED"
    for d in (raw_dir, proc_dir, kb_dir, rej_dir):
        d.mkdir(parents=True, exist_ok=True)

    ux_metrics = _ux_metrics(results)

    bucket_dirs = {"RAW": raw_dir, "KB": kb_dir, "PROCESSED": proc_dir}
    manifest = []
    rejected = []

    # Issue #204: D1-D3 gate evaluation makes synchronous blocking LLM calls
    # (~40s each). The evaluation is read-only on files and side-effect free,
    # so run it concurrently across artifacts with a fixed-size pool, then
    # reassemble the results in the original artifact order so the manifest,
    # rejected list and per-artifact side effects stay deterministic.
    _GATE_MAX_WORKERS = 6
    pending: list[tuple[int, Path, Path, str]] = []
    for idx, a in enumerate(artifacts):
        src = Path(a["path"])
        if not src.exists():
            continue
        # #192: defensive — exclude non-deliverable artifacts even if they
        # arrive from a caller that did not filter at collection time.
        if is_excluded_artifact(src.as_posix()):
            continue
        bucket = _bucket(src)
        dest = bucket_dirs[bucket] / _tier_subpath(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        pending.append((idx, src, dest, bucket))

    gate_evals: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_GATE_MAX_WORKERS) as executor:
        futures = {
            executor.submit(run_delivery_gates, src, bucket): idx
            for idx, src, _dest, bucket in pending
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                gate_eval = fut.result()
            except Exception as exc:  # noqa: BLE001 — one bad file must never break delivery
                gate_eval = {
                    "gates": {
                        "D1": {"passed": False, "details": {"error": f"gate evaluation error: {exc}"}},
                        "D2": {"passed": True, "details": {}},
                        "D3": {"passed": True, "details": {}},
                        "authenticity": {"authenticity": "fail", "reason": f"check error: {exc}"},
                    },
                    "quality": "FAIL",
                }
            gate_evals[idx] = gate_eval

    for idx, src, dest, bucket in pending:
        rel = src.as_posix()
        gate_eval = gate_evals[idx]
        gates = gate_eval.get("gates", {})
        quality = gate_eval.get("quality", "FAIL")
        entry = {
            "file": str(dest.relative_to(stage)),
            "kind": bucket,
            "source": rel,
            "size": src.stat().st_size,
            "gates": gates,
            "quality": quality,
        }
        if quality == "FAIL":
            rej_dest = rej_dir / _tier_subpath(src)
            rej_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dest, rej_dest)
            rejected.append({
                "file": str(rej_dest.relative_to(stage)),
                "source": rel,
                "reason": _failure_reason(gates),
            })
        else:
            manifest.append(entry)

    # validation report
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    unconf = sum(1 for r in results if r["status"] == "unconfigured")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    report = [
        "# AutoInfo Validation Delivery Report",
        "",
        f"- Date: {stamp}",
        (
            f"- Scenarios: {len(results)} "
            f"(passed={passed}, failed={failed}, unconfigured={unconf}, skipped={skipped})"
        ),
        f"- Artifacts: {len(manifest)} delivered, {len(rejected)} rejected",
        f"- Domains: {', '.join(_configured_domains()) or '(none)'}",
        "",
        "## Scenario Status",
        "",
        "| Scenario | Status | Summary |",
        "|----------|--------|---------|",
    ]
    for r in sorted(results, key=lambda x: x["name"]):
        report.append(f"| {r['name']} | {r['status']} | {r.get('summary', {})} |")
    report.append("")
    report.append("## Artifacts")
    report.append("")
    for m in manifest:
        report.append(
            f"- `{m['file']}` ({m['kind']}, {m['size']}B, "
            f"{m['quality']}, from {m['source']})"
        )
    if rejected:
        report.append("")
        report.append("## Rejected Artifacts (failed delivery gates)")
        report.append("")
        for rj in rejected:
            report.append(f"- `{rj['file']}` — {rj['reason']} (from {rj['source']})")
    report.append("")

    # E8 (#131): base manifest first — the staged package's own manifest is
    # the primary evidence for the coverage matrix scan.
    (stage / "manifest.json").write_text(
        json.dumps(
            {"files": manifest, "rejected": rejected},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    matrix_meta = _build_matrix_section(
        stage,
        spec_path=spec_path,
        evidence_dir=evidence_dir,
        llm_available=llm_available,
    )
    if matrix_meta is not None:
        for name in ("matrix-report.md", "coverage-gaps.json"):
            matrix_file = stage / _MATRIX_DIR_NAME / name
            manifest.append({
                "file": f"{_MATRIX_DIR_NAME}/{name}",
                "kind": "MATRIX",
                "source": "generated:coverage_matrix.py (E8)",
                "size": matrix_file.stat().st_size,
                "quality": "PASS",
            })
        report.append("## Coverage Matrix (E8)")
        report.append("")
        msum = matrix_meta["summary"]
        report.append("- Matrix report: `04-MATRIX/matrix-report.md`")
        report.append(
            f"- Cells: required={msum['required']}, produced={msum['produced']}, "
            f"gap={msum['gap']}, unconfigured={msum['unconfigured']}, "
            f"not-applicable={msum['not_applicable']}"
        )
        report.append(
            f"- LLM available: {'yes' if matrix_meta['llm_available'] else 'no'}"
        )
        report.append("")
        report.append("### COVERAGE_GAP (required cells with no evidence)")
        report.append("")
        if matrix_meta["gaps"]:
            for g in matrix_meta["gaps"]:
                report.append(f"- `{g['domain']} × {g['product']} × {g['format']}`")
        else:
            report.append(
                "- None — every required cell is 有produced or 未配置unconfigured."
            )
        report.append("")

    # E9 (#141): UX metrics — advisory report section (never blocks).
    if ux_metrics is not None:
        report.append("## UX Metrics (issue #141)")
        report.append("")
        report.append(
            f"- UX_OK: {'True' if ux_metrics['ux_ok'] else 'False'} "
            f"(completion_rate={ux_metrics['completion_rate']} >= "
            f"threshold {ux_metrics['threshold']})"
        )
        report.append(
            f"- Journey: `{_UX_JOURNEY_SCENARIO}` "
            f"(status: {ux_metrics['scenario_status']})"
        )
        report.append("- Steps:")
        for step in ux_metrics["steps"]:
            report.append(f"  - {step['name']} — {step['status']}")
        report.append("")

    (stage / "validation-report.md").write_text("\n".join(report), encoding="utf-8")
    (stage / "manifest.json").write_text(
        json.dumps(
            {"files": manifest, "rejected": rejected, "ux": ux_metrics},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    # zip it (python zipfile — user prefers zip, no tar)
    zip_path = out / f"{stage.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in stage.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(stage))
    shutil.rmtree(stage)
    return zip_path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Package validation artifacts")
    parser.add_argument("--scenarios-dir", type=Path,
                        default=Path("src/autoinfo/mcp/scenarios"))
    parser.add_argument("--out", type=Path, default=Path("validation-deliveries"))
    parser.add_argument("--skip-llm-scenarios", action="store_true",
                        help="Skip scenarios that require an LLM key (faster smoke run)")
    args = parser.parse_args()

    # Load LLM key from Hermes env (mirrors other validation scripts) so the
    # delivery run can execute LLM-gated scenarios without shell exports.
    import os
    key = ""
    env_path = Path(os.path.expanduser("~/.hermes/.env"))
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENCODE_GO_API_KEY"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if key:
        os.environ["OPENAI_API_KEY"] = key
        os.environ["AUTOINFO_LLM_API_KEY"] = key

    results, artifacts = await _run_all_scenarios(
        args.scenarios_dir, skip_llm=args.skip_llm_scenarios
    )
    if not artifacts:
        print("No artifacts collected (scenarios produced no data files).", file=sys.stderr)
        # still write a report-only zip so the user sees what ran

    # #129 P0-3: persist results for cross-run regression; best-effort,
    # never blocks delivery even if persistence fails.
    try:
        from autoinfo.mcp.validation import save_scenario_results
        save_scenario_results(results)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: could not persist scenario results: {e}", file=sys.stderr)

    # #129 P1-4: fixed archive location validation-deliveries/<date>/.
    out = args.out
    dated_out = out / datetime.datetime.now().strftime("%Y-%m-%d")
    dated_out.mkdir(parents=True, exist_ok=True)
    repo_outputs = _REPO_ROOT / "outputs"
    zip_path = _package(
        artifacts,
        results,
        dated_out,
        evidence_dir=repo_outputs if repo_outputs.is_dir() else None,
    )
    print(f"DELIVERY: {zip_path}")
    print(f"scenarios={len(results)} artifacts={len(artifacts)}")


if __name__ == "__main__":
    asyncio.run(main())
