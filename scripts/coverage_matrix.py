#!/usr/bin/env python3
"""Generate the end-user coverage matrix report (E8, issue #131).

Reads ``docs/dev/specs/end-user-matrix.yaml`` (spec: 13 demo domains
x 8 products x 8 formats) plus real evidence — ``outputs/**`` persisted
artifacts (``outputs/<domain>/<product>-<format>-<stamp>.<ext>``, written by
the MCP ``persist`` path) and the ``manifest.json`` from
``scripts/validation_delivery.py`` (bare or inside its ``*.zip`` archive) —
and renders ``matrix-report.md`` marking every cell as one of::

    有produced              evidence found for this domain x product x format
    空gap                   required cell with no evidence (LLM available,
                            or product is not LLM-gated)
    不适用not-applicable    non-required cell with no evidence
    未配置unconfigured      required cell whose product is LLM-gated while
                            the LLM key is unavailable (Oracle R8: NOT a gap)

Usage::

    python3 scripts/coverage_matrix.py \\
        --spec docs/dev/specs/end-user-matrix.yaml --evidence outputs \\
        [--llm-available | --no-llm] [--output outputs/coverage-matrix/]

Exit codes: 0 on success (report is informational — gaps are fine);
2 when the spec file or the evidence directory is missing.

The classification logic lives in :func:`classify_cell` as a pure function so
``tests/test_coverage_matrix.py`` can exercise it without a CLI run.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

# --- Cell statuses ----------------------------------------------------------
PRODUCED = "有produced"
GAP = "空gap"
NOT_APPLICABLE = "不适用not-applicable"
UNCONFIGURED = "未配置unconfigured"

_ALL_STATUSES = (PRODUCED, GAP, NOT_APPLICABLE, UNCONFIGURED)

# Scenario-library capability tokens scanned from scenario yaml (issue #156).
SCENARIO_PRODUCTS = {
    "digest", "report", "tutorial", "presentation",
    "premium-briefing", "column", "magazine-digest",
    "enterprise-briefing",
}
SCENARIO_FORMATS = {
    "markdown", "html", "json", "agent", "audio", "video",
    "epub", "audiobook",
}
# Well-known source tokens appearing in scenario yaml (name/step values).
SCENARIO_SOURCES = {
    "pubmed", "openalex", "crossref", "dblp", "arxiv", "semantic-scholar",
    "reddit", "spotify", "youtube", "bilibili", "sec", "gdelt",
    "huggingface", "kaggle", "github", "hacker", "yahoo", "quandl",
    "ssrn", "unpaywall", "akshare", "nyt", "reuters", "core",
    "apple", "edx", "stack", "producthunt", "substack", "uspto",
}

# format -> extension, mirrors _PERSIST_EXT_BY_FORMAT in src/autoinfo/mcp/server.py
FORMAT_EXT = {
    "markdown": ".md",
    "html": ".html",
    "json": ".json",
    "agent": ".json",
    "audio": ".mp3",
    "video": ".mp4",
    "epub": ".epub",
    "audiobook": ".zip",
}

# Persisted artifact filename: <product>-<format>-<YYYYmmdd-HHMMSS>.<ext>.
# Product names may contain dashes (magazine-digest, premium-briefing, ...),
# so the format token is anchored to the known format set.
# Stamp variants: standard %Y%m%d-%H%M%S (persist path) and the
# regenerate_paygrade.py literal "YYYYmmdd-paygrade" (issue #182 sweep).
_PERSISTED_RE = re.compile(
    r"^(?P<product>.+?)-(?P<format>markdown|html|json|agent|audio|video|epub|audiobook)"
    r"-\d{8}(?:-\d{6}|-paygrade)(?P<ext>\.md|\.json|\.html|\.mp3|\.mp4|\.epub|\.zip)$"
)

Cell = tuple[str, str, str]  # (domain, product, format)


# ---------------------------------------------------------------------------
# Pure classification logic (tested by tests/test_coverage_matrix.py)
# ---------------------------------------------------------------------------


def required_cells_set(spec: dict[str, Any]) -> set[Cell]:
    """Return the required cells of *spec* as ``{(domain, product, format)}``."""
    out: set[Cell] = set()
    for c in spec.get("required_cells", []):
        out.add((c["domain"], c["product"], c["format"]))
    return out


def not_implemented_cells_set(spec: dict[str, Any]) -> set[Cell]:
    """Return the capability-boundary cells of *spec*.

    Required cells annotated ``capability: not-implemented`` describe a
    deliberate capability boundary (no code implements that product x format
    combination for that domain), NOT a missing-evidence gap. They render as
    ``不适用not-applicable`` instead of ``空gap`` — a real gap is "implemented
    but no evidence".
    """
    out: set[Cell] = set()
    for c in spec.get("required_cells", []):
        if c.get("capability", "implemented") != "implemented":
            out.add((c["domain"], c["product"], c["format"]))
    return out


def classify_cell(
    cell: dict[str, str] | Cell,
    produced: set[Cell],
    llm_available: bool,
    spec: dict[str, Any],
) -> str:
    """Classify one domain x product x format cell.

    Priority (Oracle R8 — required empty LLM-gated cells are
    ``未配置unconfigured``, NEVER ``空gap``; capability-boundary cells are
    ``不适用not-applicable``, NEVER ``空gap``):

    1. produced (required or not)                -> 有produced
    2. required, capability: not-implemented     -> 不适用not-applicable
    3. required AND NOT produced:
       - product in llm_gated_products AND LLM unavailable -> 未配置unconfigured
       - otherwise                              -> 空gap
    4. non-required AND no evidence              -> 不适用not-applicable
    """
    if isinstance(cell, dict):
        key = (cell["domain"], cell["product"], cell["format"])
    else:
        key = cell
    if key in produced:
        return PRODUCED
    if key in not_implemented_cells_set(spec):
        return NOT_APPLICABLE
    if key in required_cells_set(spec):
        if key[1] in spec.get("llm_gated_products", []) and not llm_available:
            return UNCONFIGURED
        return GAP
    return NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Evidence scanning
# ---------------------------------------------------------------------------


def parse_persisted_path(rel_path: str) -> Cell | None:
    """Parse ``outputs/<domain>/<product>-<format>-<stamp>.<ext>`` into a cell.

    Returns ``None`` when the path is not a persisted output artifact (e.g.
    KB files or manifests), so the caller can silently skip it.
    """
    rel = rel_path.replace("\\", "/")
    if "outputs/" not in rel:
        return None
    parts = [p for p in rel.split("/") if p]
    try:
        idx = parts.index("outputs")
    except ValueError:
        return None
    if idx + 2 > len(parts) - 1:
        return None  # need outputs/<domain>/<file>
    domain = parts[idx + 1]
    match = _PERSISTED_RE.match(parts[idx + 2])
    if not match:
        return None
    return (domain, match.group("product"), match.group("format"))


def _cells_from_manifest(data: dict[str, Any]) -> set[Cell]:
    """Extract produced cells from a validation_delivery manifest dict.

    Only entries that passed delivery gates (``quality != "FAIL"``) count;
    rejected entries are excluded exactly like the delivery itself excludes
    them from the manifest's ``files`` list (E7).
    """
    cells: set[Cell] = set()
    for entry in data.get("files", []):
        if entry.get("quality") == "FAIL":
            continue
        cell = parse_persisted_path(str(entry.get("source", "")))
        if cell is not None:
            cells.add(cell)
    return cells


def scan_evidence(evidence_dir: str | Path) -> set[Cell]:
    """Scan *evidence_dir* for produced artifacts.

    Two evidence sources are honoured:

    1. ``outputs/**`` — persisted artifacts written by the MCP ``persist``
       path (E2): ``outputs/<domain>/<product>-<format>-<stamp>.<ext>``.
    2. ``manifest.json`` from ``scripts/validation_delivery.py`` (E7) — bare
       files and ``manifest.json`` inside ``*.zip`` archives
       (``validation-deliveries/<date>/validation-delivery-<stamp>.zip``).
       Only entries with ``quality != "FAIL"`` count.

    Returns the set of produced ``(domain, product, format)`` cells.
    """
    root = Path(evidence_dir)
    if not root.is_dir():
        return set()

    produced: set[Cell] = set()

    # The evidence dir may be the project root (contains outputs/) or the
    # outputs/ dir itself — handle both so `--evidence .` and
    # `--evidence outputs` behave identically.
    outputs_dir = root / "outputs" if (root / "outputs").is_dir() else root
    if outputs_dir.is_dir():
        for f in outputs_dir.rglob("*"):
            if not f.is_file():
                continue
            # Normalise to the expected outputs/<domain>/<file> shape so
            # parse_persisted_path resolves the domain + product + format.
            parts = f.as_posix().split("/")
            try:
                out_idx = parts.index("outputs")
            except ValueError:
                out_idx = -1
            if out_idx >= 0 and out_idx + 2 <= len(parts) - 1:
                rel = "/".join(parts[out_idx:])
            else:
                rel = f"outputs/{parts[-2]}/{parts[-1]}"
            cell = parse_persisted_path(rel)
            if cell is not None:
                produced.add(cell)

    # Manifest / zip scanning is bounded to validation-deliveries/ and
    # outputs/ — rglob over the whole project root (--evidence .) is slow
    # and finds stray manifests in unrelated dirs.
    scan_roots = [
        root / "validation-deliveries",
        root / "outputs" / "validation-deliveries",
        root / "outputs",
    ]
    for mf_root in scan_roots:
        if not mf_root.is_dir():
            continue
        for mf in mf_root.rglob("manifest.json"):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            produced |= _cells_from_manifest(data)

    for zp_root in scan_roots:
        for zp in zp_root.rglob("*.zip"):
            try:
                with zipfile.ZipFile(zp) as zf:
                    if "manifest.json" not in zf.namelist():
                        continue
                    data = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
                continue
            produced |= _cells_from_manifest(data)

    return produced


# ---------------------------------------------------------------------------
# LLM availability
# ---------------------------------------------------------------------------


def detect_llm_available(config_path: str | Path | None = None) -> bool:
    """Detect LLM availability from the project config.

    Reads ``.autoinfo/config.yaml`` (override with *config_path*) and returns
    True when ``llm.api_key`` is a non-empty string. A missing/unreadable
    config file is treated as "not available".
    """
    path = Path(config_path) if config_path else Path(".autoinfo/config.yaml")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    llm = data.get("llm") or {}
    return bool(str(llm.get("api_key", "") or "").strip())


def classify_grid(
    spec: dict[str, Any],
    produced: set[Cell],
    llm_available: bool,
) -> dict[Cell, str]:
    """Classify every domain x product x format cell of *spec*."""
    cells: dict[Cell, str] = {}
    for product in spec.get("products", []):
        for domain in spec.get("domains", []):
            for fmt in spec.get("formats", []):
                cells[(domain, product, fmt)] = classify_cell(
                    (domain, product, fmt), produced, llm_available, spec
                )
    return cells


# ---------------------------------------------------------------------------
# Source-platform & KB-tier coverage (full-capability revision, 2026-08-07)
# ---------------------------------------------------------------------------


def classify_source_coverage(
    spec: dict[str, Any],
    collected_sources: set[tuple[str, str]],
) -> list[dict[str, str]]:
    """Return source-coverage gaps from ``required_sources``.

    *collected_sources* is a set of ``(domain, source_name)`` that actually
    produced data (evidence from ``collections/<domain>/<source>/`` dirs).
    Returns a list of missing ``{domain, source}`` dicts (empty = full
    coverage).
    """
    gaps: list[dict[str, str]] = []
    for req in spec.get("required_sources", []):
        key = (req["domain"], req["source"])
        if key not in collected_sources:
            gaps.append({"domain": req["domain"], "source": req["source"]})
    return gaps


def classify_kb_tier_coverage(
    spec: dict[str, Any],
    kb_tiers_present: set[tuple[str, str]],
) -> list[dict[str, str]]:
    """Return KB-tier gaps from ``required_kb_tiers``.

    *kb_tiers_present* is a set of ``(domain, tier)`` with entries in
    ``knowledge/<domain>/<tier>/``. Returns missing ``{domain, tier}`` dicts.
    """
    gaps: list[dict[str, str]] = []
    for req in spec.get("required_kb_tiers", []):
        key = (req["domain"], req["tier"])
        if key not in kb_tiers_present:
            gaps.append({"domain": req["domain"], "tier": req["tier"]})
    return gaps


def scan_source_evidence(evidence_dir: str | Path) -> set[tuple[str, str]]:
    """Scan ``collections/`` dirs for collected ``(domain, source)`` pairs.

    A source counts as collected when its collection dir contains at least
    one JSON item file (``collections/<domain>/<source>/*.json``), i.e. the
    collector really ran and produced raw data (not dry_run-only).
    """
    root = Path(evidence_dir)
    collected: set[tuple[str, str]] = set()
    coll_root = root / "collections"
    if coll_root.is_dir():
        for domain_dir in coll_root.iterdir():
            if not domain_dir.is_dir():
                continue
            domain = domain_dir.name
            for src_dir in domain_dir.iterdir():
                if not src_dir.is_dir():
                    continue
                items = [f for f in src_dir.iterdir() if f.is_file() and f.suffix == ".json"]
                if items:
                    collected.add((domain, src_dir.name))
    return collected


def scan_kb_tier_evidence(evidence_dir: str | Path) -> set[tuple[str, str]]:
    """Scan ``knowledge/<domain>/<tier>/`` for present KB tiers."""
    root = Path(evidence_dir)
    present: set[tuple[str, str]] = set()
    kb_root = root / "knowledge"
    if kb_root.is_dir():
        for domain_dir in kb_root.iterdir():
            if not domain_dir.is_dir():
                continue
            domain = domain_dir.name
            for tier in ("01-Raw", "02-Draft", "03-Wiki"):
                tier_dir = domain_dir / tier
                if tier_dir.is_dir() and any(tier_dir.rglob("*.md")):
                    present.add((domain, tier))
    return present


# ---------------------------------------------------------------------------
# Scenario-library coverage — the validation library itself must exercise the
# full capability surface (issue #156).  A product/format/source the library
# never touches is invisible to acceptance even when the code implements it.
# ---------------------------------------------------------------------------

def scan_scenario_library(
    scenarios_dir: str | Path, source_tokens: set[str] | None = None
) -> dict[str, set[str]]:
    """Scan validation scenario YAMLs for products, formats and source names.

    Returns ``{"products", "formats", "sources"}`` — the union of every
    product/format/source token the scenario library mentions, so the report
    can show which implemented capabilities validation actually exercises.

    *source_tokens* (optional) extends the built-in ``SCENARIO_SOURCES``
    token set with the spec's own ``source_platforms`` names — the scan must
    look for the same spellings the spec declares (e.g. ``apple_podcasts``,
    ``sec_edgar``, ``yahoo_finance``), otherwise a token the library mentions
    is wrongly reported as missing.
    """
    root = Path(scenarios_dir)
    out: dict[str, set[str]] = {"products": set(), "formats": set(), "sources": set()}
    if not root.is_dir():
        return out

    source_tokens = SCENARIO_SOURCES | (source_tokens or set())

    for yf in root.glob("*.yaml"):
        text = yf.read_text(encoding="utf-8")
        low = text.lower()
        for p in SCENARIO_PRODUCTS:
            if p in low:
                out["products"].add(p)
        for f in SCENARIO_FORMATS:
            if f in low:
                out["formats"].add(f)
        for s in source_tokens:
            if s in low:
                out["sources"].add(s)
    return out


def _channel_token(channel: str) -> str:
    """Map a spec channel name to a scenario-library scan token."""
    return {
        "social_video": "social",
        "search_ai_overview": "search",
        "tv_broadcast": "tv",
        "ai_chatbot": "chatbot",
        "owned_website_app": "web",
        "push_notification": "push",
        "email_newsletter": "email",
        "mobile_app": "app",
        "podcast_directory": "podcast",
        "rss_feed": "rss",
        "browser_navigation": "browser",
        "affiliate": "affiliate",
        "mcp_a2a_agent": "mcp",
        "wechat_ecosystem": "wechat",
    }.get(channel, channel)


def _capability_token(capability: str) -> str:
    """Map a spec capability name to a scenario-library scan token."""
    return {
        "mcp_exposure": "mcp",
        "paid_user_management": "subscription",
        "usage_metering": "cost",
        "multi_channel_delivery": "delivery",
        "rag_output": "query",
        "personalized_recommendation": "recommend",
        "scheduled_tasks": "cron",
        "webhook_integration": "webhook",
        "source_credibility": "source_score",
        "content_compliance": "tos",
        "api_data_licensing": "raw",
        "single_article_payment": "checkout",
        "raas_performance_pricing": "raas",
        "content_simplification": "simplify",
        "a2a_protocol": "a2a",
    }.get(capability, capability)


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_report(
    spec: dict[str, Any],
    produced: set[Cell],
    llm_available: bool,
    *,
    spec_path: str = "",
    evidence_dir: str = "",
    source_evidence: set[tuple[str, str]] | None = None,
    kb_evidence: set[tuple[str, str]] | None = None,
    scenarios_dir: str = "",
) -> str:
    """Render the markdown matrix report for *spec*.

    Returns the full ``matrix-report.md`` text (title, meta, legend, the
    products x domains table, the ``COVERAGE_GAP`` summary, and the
    ``SOURCE_COVERAGE`` / ``KB_TIER_COVERAGE`` blocks) listing every
    required cell classified as a gap — never silent.
    """
    products: list[str] = list(spec.get("products", []))
    domains: list[str] = list(spec.get("domains", []))
    required = required_cells_set(spec)

    cells = classify_grid(spec, produced, llm_available)

    gaps = sorted(
        (c for c, s in cells.items() if s == GAP),
        key=lambda c: (c[0], c[1], c[2]),
    )
    produced_count = sum(1 for s in cells.values() if s == PRODUCED)
    gap_count = len(gaps)
    unconfigured_count = sum(1 for s in cells.values() if s == UNCONFIGURED)
    na_count = sum(1 for s in cells.values() if s == NOT_APPLICABLE)

    lines: list[str] = []
    lines.append("# End-User Coverage Matrix (E8, issue #131)")
    lines.append("")
    lines.append(f"- Spec: `{spec_path or 'docs/dev/specs/end-user-matrix.yaml'}`")
    lines.append(f"- Spec version: {spec.get('version', 1)}")
    lines.append(f"- Evidence dir: `{evidence_dir or '(none — no evidence scanned)'}`")
    llm_note = (
        "yes" if llm_available
        else "no (llm_gated products are 未配置unconfigured, not gaps)"
    )
    lines.append(f"- LLM available: {llm_note}")
    lines.append(f"- Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    lines.append(
        f"- Cells: {len(cells)} (domains={len(domains)} x products={len(products)} "
        f"x formats={len(spec.get('formats', []))}), required={len(required)} — "
        f"produced={produced_count}, gap={gap_count}, "
        f"unconfigured={unconfigured_count}, not-applicable={na_count}"
    )
    lines.append("")

    lines.append("## Legend")
    lines.append("")
    lines.append("| Symbol | Status | Meaning |")
    lines.append("|--------|--------|---------|")
    lines.append(f"| 有 | {PRODUCED} | Evidence found for this domain x product x format |")
    lines.append(
        f"| 空 | {GAP} | Required cell with no evidence "
        "(LLM available or product not LLM-gated) |"
    )
    lines.append(
        f"| 不适用 | {NOT_APPLICABLE} | Non-required cell with no evidence |"
    )
    lines.append(
        f"| 未配置 | {UNCONFIGURED} | Required LLM-gated cell while the "
        "LLM key is unavailable (not a gap) |"
    )
    lines.append("")

    lines.append("## Matrix (rows = products, columns = domains)")
    lines.append("")
    lines.append("| Product | " + " | ".join(domains) + " |")
    lines.append("|---------|" + "|".join("---" for _ in domains) + "|")
    for product in products:
        row_cells: list[str] = []
        for domain in domains:
            # Report one cell per product x domain — the most-produced format
            # wins the cell label (first format in spec order with evidence).
            cell_status = NOT_APPLICABLE
            for fmt in spec.get("formats", []):
                status = cells[(domain, product, fmt)]
                if status == PRODUCED:
                    cell_status = PRODUCED
                    break
                if status in (GAP, UNCONFIGURED):
                    cell_status = status
            row_cells.append(cell_status)
        lines.append(f"| {product} | " + " | ".join(row_cells) + " |")
    lines.append("")

    lines.append("## COVERAGE_GAP")
    lines.append("")
    lines.append(
        "Required cells with NO produced evidence and NOT LLM-unconfigured "
        "(these block acceptance — issue #131):"
    )
    lines.append("")
    if gaps:
        lines.append("| Domain | Product | Format |")
        lines.append("|--------|---------|--------|")
        for domain, product, fmt in gaps:
            lines.append(f"| {domain} | {product} | {fmt} |")
    else:
        lines.append(
            "No required-empty gap cells — every required cell is "
            "有produced or 未配置unconfigured."
        )
    lines.append("")

    # --- SOURCE_COVERAGE (full-capability revision) ---
    source_gaps = classify_source_coverage(spec, source_evidence or set())
    lines.append("## SOURCE_COVERAGE")
    lines.append("")
    lines.append(
        "Required source-platform cells (domain x source) with no collected "
        "raw data — these block acceptance for the configured demo domains:"
    )
    lines.append("")
    if source_gaps:
        lines.append("| Domain | Source |")
        lines.append("|--------|--------|")
        for g in source_gaps:
            lines.append(f"| {g['domain']} | {g['source']} |")
    else:
        lines.append("All required sources produced raw data.")
    lines.append("")

    # --- KB_TIER_COVERAGE (full-capability revision) ---
    kb_gaps = classify_kb_tier_coverage(spec, kb_evidence or set())
    lines.append("## KB_TIER_COVERAGE")
    lines.append("")
    lines.append(
        "Required KB-tier cells (domain x tier) with no entries — the "
        "pipeline must reach each tier for the configured demo domains:"
    )
    lines.append("")
    if kb_gaps:
        lines.append("| Domain | Tier |")
        lines.append("|--------|------|")
        for g in kb_gaps:
            lines.append(f"| {g['domain']} | {g['tier']} |")
    else:
        lines.append("All required KB tiers have entries.")
    lines.append("")

    # --- SCENARIO_LIBRARY_COVERAGE (issue #156) ---
    lines.append("## SCENARIO_LIBRARY_COVERAGE")
    lines.append("")
    lines.append(
        "Capabilities the validation scenario library actually exercises "
        "vs the full implemented surface (spec products/formats/sources). "
        "A capability the library never touches is invisible to acceptance:"
    )
    lines.append("")
    spec_sources = set(spec.get("source_platforms", []))
    sc = (
        scan_scenario_library(scenarios_dir, source_tokens=spec_sources)
        if scenarios_dir
        else {
            "products": set(),
            "formats": set(),
            "sources": set(),
        }
    )
    spec_products = set(spec.get("products", []))
    spec_formats = set(spec.get("formats", []))
    miss_products = sorted(spec_products - sc["products"])
    miss_formats = sorted(spec_formats - sc["formats"])
    lines.append(
        f"- Products exercised: {len(sc['products'])}/{len(spec_products)} "
        f"— missing: {', '.join(miss_products) or 'none'}"
    )
    lines.append(
        f"- Formats exercised: {len(sc['formats'])}/{len(spec_formats)} "
        f"— missing: {', '.join(miss_formats) or 'none'}"
    )
    lines.append(
        f"- Source tokens exercised: {len(sc['sources'])}/{len(spec_sources)} "
        f"(best-effort text scan) — missing: "
        f"{', '.join(sorted(set(spec_sources) - sc['sources'])) or 'none'}"
    )
    lines.append("")

    # --- CHANNEL_COVERAGE / CAPABILITY_COVERAGE (v3 dimensions) ---
    channels = spec.get("channels", [])
    if channels:
        lines.append("## CHANNEL_COVERAGE")
        lines.append("")
        lines.append(
            "Distribution channels (report §5.1 + §10.2 China touchpoints) "
            "declared in the spec — delivery adapters live in "
            "`src/autoinfo/delivery/__init__.py::_CHANNEL_REGISTRY`; "
            "scenario-library exercise status is best-effort text scan:"
        )
        lines.append("")
        lines.append("| Channel | Scenario library |")
        lines.append("|---------|------------------|")
        for ch in channels:
            token = _channel_token(ch)
            exercised = "✅" if token in sc["sources"] else "—"
            lines.append(f"| {ch} | {exercised} |")
        lines.append("")

    capabilities = spec.get("capabilities", [])
    if capabilities:
        lines.append("## CAPABILITY_COVERAGE")
        lines.append("")
        lines.append(
            "Agent capabilities (report §6.5 usage scenarios / §8.3 business "
            "models) declared in the spec — each maps to MCP tools in "
            "`src/autoinfo/mcp/server.py`; scenario-library exercise status "
            "is best-effort text scan:"
        )
        lines.append("")
        lines.append("| Capability | Scenario library |")
        lines.append("|------------|------------------|")
        for cap in capabilities:
            token = _capability_token(cap)
            exercised = "✅" if token in sc["sources"] else "—"
            lines.append(f"| {cap} | {exercised} |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the end-user coverage matrix report (E8, #131) from the "
            "spec plus real evidence (outputs/** and validation_delivery "
            "manifests)."
        )
    )
    parser.add_argument(
        "--spec",
        default="docs/dev/specs/end-user-matrix.yaml",
        help="Path to the end-user-matrix.yaml spec (default: docs/dev/specs/end-user-matrix.yaml)",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        help="Directory to scan for produced artifacts (outputs/** + manifest.json)",
    )
    llm = parser.add_mutually_exclusive_group()
    llm.add_argument(
        "--llm-available",
        dest="llm_available",
        action="store_true",
        help="Treat the LLM as configured (llm_gated products become 空gap when empty)",
    )
    llm.add_argument(
        "--no-llm",
        dest="llm_available",
        action="store_false",
        help="Treat the LLM as unavailable (required llm_gated cells become 未配置unconfigured)",
    )
    parser.set_defaults(llm_available=None)
    parser.add_argument(
        "--config",
        default=".autoinfo/config.yaml",
        help="Project config to detect LLM availability from (default: .autoinfo/config.yaml)",
    )
    parser.add_argument(
        "--output",
        default="outputs/coverage-matrix/",
        help="Output directory for matrix-report.md (default: outputs/coverage-matrix/)",
    )
    parser.add_argument(
        "--scenarios-dir",
        default="src/autoinfo/mcp/scenarios",
        help="Validation scenario library dir to scan for capability coverage "
        "(default: src/autoinfo/mcp/scenarios)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec file not found: {args.spec}", file=sys.stderr)
        return 2

    evidence_dir = Path(args.evidence)
    if not evidence_dir.is_dir():
        print(f"ERROR: evidence directory not found: {args.evidence}", file=sys.stderr)
        return 2

    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"ERROR: cannot parse spec {args.spec}: {exc}", file=sys.stderr)
        return 2

    produced = scan_evidence(evidence_dir)
    source_evidence = scan_source_evidence(evidence_dir)
    kb_evidence = scan_kb_tier_evidence(evidence_dir)

    if args.llm_available is None:
        llm_available = detect_llm_available(args.config)
    else:
        llm_available = args.llm_available

    report = render_report(
        spec,
        produced,
        llm_available,
        spec_path=args.spec,
        evidence_dir=args.evidence,
        source_evidence=source_evidence,
        kb_evidence=kb_evidence,
        scenarios_dir=args.scenarios_dir,
    )

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "matrix-report.md"
    report_path.write_text(report, encoding="utf-8")

    counts = {status: 0 for status in _ALL_STATUSES}
    for status in classify_grid(spec, produced, llm_available).values():
        counts[status] += 1
    source_gaps = classify_source_coverage(spec, source_evidence)
    kb_gaps = classify_kb_tier_coverage(spec, kb_evidence)
    print(f"MATRIX: {report_path}")
    print(f"cells={sum(counts.values())} (domains x products x formats), "
          f"llm_available={llm_available}")
    for status in _ALL_STATUSES:
        print(f"  {status}: {counts[status]}")
    print(f"source_gaps: {len(source_gaps)} / required_sources")
    print(f"kb_tier_gaps: {len(kb_gaps)} / required_kb_tiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
