"""Delivery-layer gate checks + per-product gate reports (shared, todo 13).

This module holds the D1-D3 + authenticity delivery-gate implementation and
the per-product gate-report rendering that was originally written for the
validation delivery packager (``scripts/validation_delivery.py``, concierge
wave task 7). Todo 13 extracted it verbatim into ``src/autoinfo`` so the
Concierge MVP CLI (``autoinfo mvp init``) and the validation packager share
the SAME gate + gate-report code — one implementation, two consumers:

- ``scripts/validation_delivery.py`` re-exports these names (the importlib
  based tests exercise ``vd.check_authenticity`` / ``vd.run_delivery_gates``
  / ``vd._qa_product_key``) and uses :func:`run_delivery_gates` +
  :func:`_build_qa_gate_report` in its bulk ``01-QA-GATES`` section writer.
- ``autoinfo.cli.mvp`` uses :func:`write_gate_report` to record the honest
  delivery-layer determinations for a pilot's first product.

Honesty contract (unchanged from task 7): G0-G5 run at PROCESS time
(``autoinfo.quality``); these functions record ONLY the delivery-layer
determinations (D1-D3 delivery gates + authenticity pre-check +
deliver/reject decisions) that were actually made. No G0-G5 data is
recomputed or persisted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from autoinfo.quality import run_delivery_gates as _quality_run_delivery_gates

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
        hm = re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip())
        if hm:
            if cur_heading:
                blocks.append((cur_heading, cur_lines))
            cur_heading = hm.group(1).lower().replace("*", "").replace("`", "").strip()
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
    parsed: Any = None
    if fmt in ("markdown", "html"):
        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        format_type = _detect_product_type(file_path, str(body))
        if product_type != "RAW":
            # Carry the inferred product (presentation/report/column/...) so
            # the D1 gate can apply product-appropriate completeness rules
            # (issue #217 follow-up: presentation decks are slide content,
            # not key_findings/summary/recommendations).
            product_type = format_type
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
    out: dict[str, Any] = {
        "product_type": product_type,
        "format": fmt or "markdown",
        "body": body,
        "key_findings": key_findings if key_findings not in (None, "") else [],
        "summary": summary if summary not in (None, []) else "",
        "recommendations": recommendations if recommendations not in (None, "") else [],
        "entries": entries,
    }
    # Agent JSON-LD payloads (@type: KnowledgeDigest/KnowledgeReport/
    # KnowledgePresentation/...) carry their contract marker here so the
    # D1 gate applies the agent-native completeness check instead of the
    # markdown sections check (issue #217).
    if isinstance(parsed, dict) and "@type" in parsed:
        out["@type"] = parsed["@type"]
    return out


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
    parsed = _parse_json_payload(file_path)
    entries = _json_entries(parsed)
    if not entries:
        return {
            "authenticity": "pass",
            "reason": "no structured source entries found in payload — nothing to verify",
        }
    problems: list[str] = []
    is_agent_ld = bool(parsed.get("@type")) if isinstance(parsed, dict) else False
    if is_agent_ld and parsed.get("@type") == "KnowledgePresentation":
        # Slides are content, not source entries; the deck's provenance
        # lives in the top-level "sources" list (issue #217).
        sources = parsed.get("sources") or []
        for i, src in enumerate(sources):
            if not isinstance(src, dict):
                continue
            url = src.get("source_url", "")
            if not isinstance(url, str) or not url.strip():
                problems.append(f"sources[{i}] missing source_url")
        if not sources:
            return {
                "authenticity": "pass",
                "reason": "presentation has no provenance sources — nothing to verify",
            }
    elif is_agent_ld and parsed.get("@type") == "KnowledgeTutorial":
        # Tutorial content (steps/exercises) is authored material; its
        # provenance lives in the top-level "source_entries" list
        # (issue #217).
        source_entries = parsed.get("source_entries") or []
        for i, src in enumerate(source_entries):
            if not isinstance(src, dict):
                continue
            url = src.get("source_url", "")
            if not isinstance(url, str) or not url.strip():
                problems.append(f"source_entries[{i}] missing source_url")
            plat = src.get("source_platform", "")
            if not isinstance(plat, str) or not plat.strip():
                problems.append(f"source_entries[{i}] missing source_platform")
        if not source_entries:
            return {
                "authenticity": "pass",
                "reason": "tutorial has no provenance source_entries — nothing to verify",
            }
    else:
        for i, entry in enumerate(entries):
            url = entry.get("source_url", "")
            if not isinstance(url, str) or not url.strip():
                problems.append(f"entry[{i}] missing source_url")
            elif "example.com" in url:
                problems.append(f"entry[{i}] placeholder source_url: {url}")
            # source_type is required for raw collection payloads but is not
            # part of agent JSON-LD entries (KnowledgeDigest etc. carry
            # source_platform instead) — only require source_platform there
            # (issue #217).
            if is_agent_ld:
                val = entry.get("source_platform", "")
                if not isinstance(val, str) or not val.strip():
                    problems.append(f"entry[{i}] missing source_platform")
            else:
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
# Per-product gate reports (concierge wave, plan task 7; shared todo 13)
# ---------------------------------------------------------------------------

_QA_GATES_DIR_NAME = "01-QA-GATES"
# Honesty note carried verbatim in every gate report: the G0-G5 gates run at
# PROCESS time (autoinfo.quality run_quality_gates / LLM extraction), not at
# packaging time. These reports record only the delivery-layer determinations
# (D1-D3 + authenticity + packager-level results) that the caller actually
# made.
_QA_LAYER_NOTE = (
    "G0-G5 于 process 层执行, 本报告记录 delivery 层判定 "
    "(G0-G5 run at process time; this report records the delivery layer's "
    "determinations only: D1-D3 delivery gates + authenticity pre-check + "
    "packager-level deliver/reject decisions). No G0-G5 data is recomputed "
    "or persisted here."
)


def _qa_product_key(path: Path, used: set[str]) -> str:
    """Deterministic, filesystem-safe, collision-free report key for a file.

    ``outputs/medical-research/digest-markdown-20260904.md`` -> ``digest``,
    nested paths keep their directory segments joined with ``__``. A second
    file mapping to the same key gets ``-2``, ``-3``, ... suffixes.
    """
    parts = path.with_suffix("").parts
    key = re.sub(r"[^A-Za-z0-9._-]", "_", "__".join(parts)) or "artifact"
    base = key
    n = 2
    while key in used:
        key = f"{base}-{n}"
        n += 1
    used.add(key)
    return key


def _qa_gate_row(gates: dict[str, Any]) -> list[dict[str, Any]]:
    """The honest gates array for one artifact (D1-D3 + authenticity)."""
    return [
        {
            "gate": name,
            "passed": bool((gates.get(name) or {}).get("passed", True)),
            "details": (gates.get(name) or {}).get("details") or {},
        }
        for name in ("D1", "D2", "D3")
    ] + [
        {
            "gate": "authenticity",
            "passed": (gates.get("authenticity") or {}).get("authenticity") == "pass",
            "details": (gates.get("authenticity") or {}).get("reason", ""),
        }
    ]


def _build_qa_gate_report(
    product_key: str,
    *,
    product: str,
    kind: str,
    delivered: bool,
    quality: str,
    gates: dict[str, Any],
    rejected_reason: str = "",
) -> tuple[str, str]:
    """Render one product's gate report as ``(markdown, json_text)``.

    Records ONLY what the packager actually determined (D1-D3 + authenticity
    + deliver/reject), with the process-layer honesty note — never fabricated
    G0-G5 data.
    """
    payload: dict[str, Any] = {
        "product": product,
        "product_key": product_key,
        "kind": kind,
        "delivered": delivered,
        "rejected_reason": rejected_reason,
        "quality": quality,
        "layer_note": _QA_LAYER_NOTE,
        "gates": _qa_gate_row(gates),
    }
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    md: list[str] = [
        f"# Gate Report — {product}",
        "",
        f"- Delivered: {'yes' if delivered else 'no (rejected)'}",
        f"- Quality: {quality}",
        f"- Kind: {kind}",
    ]
    if rejected_reason:
        md.append(f"- Rejection reason: {rejected_reason}")
    md.extend([
        "",
        "## Gates",
        "",
        "| Gate | Passed | Details |",
        "|------|--------|---------|",
    ])
    for row in payload["gates"]:
        details = row["details"]
        if isinstance(details, dict):
            details = details.get("error") or details.get("reason") or json.dumps(
                details, ensure_ascii=False, default=str
            )
        md.append(f"| {row['gate']} | {'PASS' if row['passed'] else 'FAIL'} | {details} |")
    md.extend([
        "",
        "## Scope Note",
        "",
        _QA_LAYER_NOTE,
        "",
    ])
    return "\n".join(md), json_text


def write_gate_report(
    out_dir: Path,
    product_file: Path,
    *,
    kind: str = "PROCESSED",
    bucket: str = "PROCESSED",
) -> dict[str, Any]:
    """Gate-check one product file and write its gate report into *out_dir*.

    Shared single-product entry point (concierge wave todo 13): the
    Concierge MVP CLI uses it to record the D1-D3 + authenticity
    determinations for a pilot's first product, next to the product file.
    The validation packager's bulk writer (``_write_qa_gates_section`` in
    ``scripts/validation_delivery.py``) loops over the same building blocks
    (:func:`run_delivery_gates` + :func:`_build_qa_gate_report`).

    ``delivered`` is honest: ``True`` only when every delivery gate passes;
    a failed product keeps its file but the report records
    ``delivered=false`` plus the failure reason.

    Returns ``{quality, delivered, gates, key, md, json}``.
    """
    gates_result = run_delivery_gates(product_file, bucket)
    used: set[str] = set()
    key = _qa_product_key(product_file, used)
    delivered = gates_result["quality"] == "PASS"
    md_text, json_text = _build_qa_gate_report(
        key,
        product=product_file.name,
        kind=kind,
        delivered=delivered,
        quality=gates_result["quality"],
        gates=gates_result["gates"],
        rejected_reason="" if delivered else _failure_reason(gates_result["gates"]),
    )
    md_path = out_dir / f"gate-report-{key}.md"
    json_path = out_dir / f"gate-report-{key}.json"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    return {
        "quality": gates_result["quality"],
        "delivered": delivered,
        "gates": gates_result["gates"],
        "key": key,
        "md": md_path,
        "json": json_path,
    }
