"""Full-matrix validation executor + formalized assertion set (issues #331, #332-A).

The paid-user reinspection loop repeatedly found "one more thing broke after each
rerun": #316/#323 regressions passed but the real path wasn't fixed, #314 fixed
enterprise but premium regressed, 12-way concurrency exposed litellm pollution.
Root cause was not missing scenarios (100 exist) but three structural gaps:

  1. no one-command full-matrix executor (3 domains x 8 products -> assert ->
     report card);
  2. assertions not wired to the REAL generation path (`output digest --product`
     from the live KB), only to mock/template paths;
  3. no unified white-box assertion checklist, each problem discovered ad hoc.

This module provides:

* ``AssertionResult`` + a formalized assertion set (``run_assertions``) — one
  readable function per assertion, each with the source issue commented.
* ``run_matrix`` — generates products over a domains x products grid on the real
  KB path (``generate_digest``/``generate_report``) and asserts each; supports
  ``only_assert`` (scan existing persisted products, no regeneration).
* ``MatrixReport`` / ``save_report_card`` — report-card JSON (per
  product x assertion pass/fail + summary) persisted with commit sha + timestamp.
* ``diff_report_cards`` (#332-A) — regression diff classifying each
  (product, assertion) as new / regressed / fixed / existing-failing.

Deterministic and import-safe (no side effects on import); the run path reuses
the existing output generators so the deterministic fallbacks apply when no LLM
is configured.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class AssertionResult:
    """Outcome of a single formalized assertion for a (domain, product)."""

    name: str
    passed: bool
    issue: str
    severity: str  # "P0" | "P1" | "P2"
    domain: str = ""
    product: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion": self.name,
            "passed": self.passed,
            "issue": self.issue,
            "severity": self.severity,
            "domain": self.domain,
            "product": self.product,
            "details": self.details,
        }


@dataclass
class MatrixReport:
    """Aggregated report card for a domain x product matrix run."""

    generated_at: str = ""
    commit: str = ""
    batch_id: str = ""
    products: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tool": "autoinfo validate --matrix",
            "generated_at": self.generated_at,
            "commit": self.commit,
            "batch_id": self.batch_id,
            "products": self.products,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Assertion helpers (shared across assertions)
# ---------------------------------------------------------------------------

_REFS_HEADING = re.compile(r"^##\s+References", re.MULTILINE)
_REF_ENTRY = re.compile(r"^\s*(?:(\d+)\.|[-*])\s+\S", re.MULTILINE)
_RSS_LABEL = re.compile(r"\bRSS\b")
_PLACEHOLDER = re.compile(r"_No [^_]+_")
# #334 — premium/enterprise analysis layer can fill N/A / None / TBD style
# standalone cells (LLM filler), plus deterministic/skeleton echoes.
_PLACEHOLDER_TOKEN = re.compile(
    r"^(?:n/?a|tbd|tba|tbc|none|not available|not provided|not specified|"
    r"not disclosed|no data(?: available)?|no content(?: provided)?|"
    r"to be determined|to be announced|to be confirmed)[.,;:]*$",
    re.IGNORECASE,
)
_NO_ENTRIES_PLACEHOLDER = re.compile(
    r"No knowledge base entr(?:y|ies) (?:were )?(?:available|found)",
    re.IGNORECASE,
)
_SKELETON_ECHO = re.compile(r"<[a-z][a-z0-9 _-]+>", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^[-*•]?\s*(?:\[\s*[ xX]\s*\])?\s*")
# #338 — internal keyword-search/counting lines must never reach the product:
# keyword-group descriptions, "entry(ies) not matched/covered" catch-alls,
# per-theme count bullets and source-group counts.
_INTERNAL_LEAK_RE = re.compile(
    r"\d+\s+entries?\s+related to\b|"
    r"entry\(ies\)\s+not\s+(?:matched to a topic keyword|covered by other themes)|"
    r"\d+\s+entries?\s+included in this report|"
    r"knowledge base entries grouped into\s+\d+\s+themes?|"
    r"\d+\s+entries?\s+from [a-z-]+ sources?",
    re.IGNORECASE,
)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TRACEBACK = re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)
_LITELLM = re.compile(
    r"Give Feedback / Get Help|BerriAI|LiteLLM\.Info|litellm\._turn_on_debug",
    re.IGNORECASE,
)
# Cross-domain noise markers (issue #319) / financial dilution markers.
_AI_COMMERCIAL_NOISE = (
    "贝达药业", "华能", "株冶", "平安好医生", "DURAVYU", "SEC 8-K", "SEC 8K",
    "10-Q", "10Q", "财报", "年报",
)
_FIN_DILUTION = ("SEC 8-K", "SEC 8K", "10-Q", "10Q", "8-K filing", "8K filing")

_X = "cross-domain-noise-filter"


def _as_str(value: Any) -> str:
    """Coerce a ``str | DeliveryOutput`` generate_* return to plain ``str``."""
    if hasattr(value, "output"):
        return str(value.output)
    return str(value)


# ---------------------------------------------------------------------------
# Formalized assertions — one readable function per assertion, each carrying
# the source issue in its docstring (#331 requirement: 一个断言 = 一个可读函数
# + 对应 issue 注释).
# ---------------------------------------------------------------------------


def _title_first(text: str, domain: str, product: str) -> AssertionResult:
    """#318 — the rendered product's first line is a real title (not the
    litellm pollution block, not a blank line, not a stray marker)."""
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    ok = bool(first) and not _ANSI.search(first) and not _LITELLM.search(first)
    return AssertionResult(
        "_title_first", ok, "#318", "P0", domain, product,
        f"first line={first[:60]!r}",
    )


def _no_error_leak(text: str, domain: str, product: str) -> AssertionResult:
    """#328 — the file header carries no external LLM error text / ANSI codes /
    traceback / 'Give Feedback' litellm markers."""
    bad = []
    if _LITELLM.search(text):
        bad.append("litellm/BerriAI marker")
    if _ANSI.search(text[:500]):
        bad.append("ANSI escape in header")
    if _TRACEBACK.search(text):
        bad.append("traceback")
    return AssertionResult(
        "_no_error_leak", not bad, "#328", "P0", domain, product,
        "; ".join(bad) if bad else "clean header",
    )


def _references_numbered(text: str, domain: str, product: str) -> AssertionResult:
    """#322 — References numbering increments 1/2/3 (no repeated '1.')."""
    m = _REFS_HEADING.search(text)
    if not m:
        return AssertionResult(
            "_references_numbered", True, "#322", "P1", domain,
            product, "no References section",
        )
    body = text[m.end():]
    # A markdown ordered list renders 1.,2.,3. — pick only the numbered ones.
    numbered = [int(g) for g in re.findall(r"^\s*(\d+)\.\s", body, re.MULTILINE)]
    ok = all(n == i for i, n in enumerate(numbered, start=1))
    return AssertionResult(
        "_references_numbered", ok, "#322", "P1", domain, product,
        f"numbers={numbered}" if numbered else "no numbered refs",
    )


def _source_labels_specific(text: str, domain: str, product: str) -> AssertionResult:
    """#325 — References source labels are specific names; '(RSS)' residue is 0."""
    body = text
    refs = _REFS_HEADING.search(text)
    if refs is not None:
        body = text[refs.end():]
    matches = _RSS_LABEL.findall(body)
    return AssertionResult(
        "_source_labels_specific", not matches, "#325", "P1", domain, product,
        f"RSS label x{len(matches)}" if matches else "no RSS label",
    )


def _collect_placeholder_tokens(text: str) -> list[str]:
    """Return every placeholder marker found in ``text``.

    Covers (a) the template ``_No ..._`` empty-state markers, (b) standalone
    analysis-layer filler values (``N/A``/``None``/``TBD``/``Not available``
    /``To be determined`` used as a whole table cell or list item — #334),
    (c) the deterministic ``No knowledge base entries were available.``
    fallback message, and (d) residual LLM skeleton echoes (``<finding 1>``).
    """
    found: list[str] = list(dict.fromkeys(_PLACEHOLDER.findall(text)))
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = line.strip("|").split("|") if line.startswith("|") else [line]
        for cell in cells:
            cell = _LIST_MARKER.sub("", cell.strip()).strip()
            if cell and _PLACEHOLDER_TOKEN.match(cell):
                found.append(cell)
    for m in _NO_ENTRIES_PLACEHOLDER.finditer(text):
        found.append(m.group(0))
    for m in _SKELETON_ECHO.finditer(text):
        found.append(m.group(0))
    return list(dict.fromkeys(found))


def _no_placeholder(text: str, domain: str, product: str) -> AssertionResult:
    """#329/#314/#326/#334 — no placeholder/empty-state residue in any product,
    including the premium/enterprise analysis layer (issues #329, #334)."""
    found = _collect_placeholder_tokens(text)
    return AssertionResult(
        "_no_placeholder", not found, "#329", "P0", domain, product,
        "placeholders=" + ", ".join(found) if found else "none",
    )


def _no_internal_leak(text: str, domain: str, product: str) -> AssertionResult:
    """#338 — products never expose internal keyword-search/counting lines
    (``N entries related to <kw>``, ``N entry(ies) not matched to a topic
    keyword``, per-theme count bullets, source-group counts)."""
    found = sorted(set(_INTERNAL_LEAK_RE.findall(text)))
    return AssertionResult(
        "_no_internal_leak", not found, "#338", "P0", domain, product,
        "leak=" + ", ".join(found) if found else "none",
    )


def _column_deep_dive(text: str, domain: str, product: str) -> AssertionResult:
    """#316/#326 — the column Deep Dive section has content (>=1 subsection)
    or is absent (non-column products skip; this is an informational pass)."""
    if product != "column":
        return AssertionResult(
            "_column_deep_dive", True, "#316", "P1", domain, product,
            "not a column product",
        )
    m = re.search(r"^##+\s+Deep Dive", text, re.MULTILINE)
    if not m:
        return AssertionResult(
            "_column_deep_dive", False, "#316", "P1", domain, product,
            "missing Deep Dive section",
        )
    tail = text[m.end():]
    subs = re.findall(r"^###\s+\S", tail, re.MULTILINE)
    return AssertionResult(
        "_column_deep_dive", len(subs) >= 1, "#316", "P1", domain, product,
        f"subsections={len(subs)}",
    )


def _report_sections(text: str, domain: str, product: str) -> AssertionResult:
    """#311/#326 — the report product's Sections metadata is non-zero (has
    semantic grouping), not an empty shell."""
    if product not in ("report", "column"):
        return AssertionResult(
            "_report_sections", True, "#311", "P1", domain, product,
            "not a report/column product",
        )
    m = re.search(r"\*\*Sections\*\*:\s*(\d+)", text)
    if not m:
        ok = "## " in text and len(text.strip()) > 200
        return AssertionResult(
            "_report_sections", ok, "#311", "P1", domain, product,
            "no Sections metadata" + ("" if ok else " (empty shell)"),
        )
    n = int(m.group(1))
    return AssertionResult(
        "_report_sections", n >= 1, "#311", "P1", domain, product,
        f"Sections={n}",
    )


def _metadata_consistency(text: str, domain: str, product: str) -> AssertionResult:
    """(—) Sections metadata equals the actual rendered section count."""
    m = re.search(r"\*\*Sections\*\*:\s*(\d+)", text)
    if not m:
        return AssertionResult(
            "_metadata_consistency", True, "—", "P2", domain, product,
            "no Sections metadata",
        )
    actual = len(re.findall(r"^###\s+\S", text, re.MULTILINE))
    n = int(m.group(1))
    return AssertionResult(
        "_metadata_consistency", n == actual, "—", "P2", domain, product,
        f"metadata={n} actual={actual}",
    )


def _no_cross_domain_noise(text: str, domain: str, product: str) -> AssertionResult:
    """#319 — ai-commercial products contain no financial/regulatory/macro
    noise entries (贝达药业/华能/SEC 8-K/财报 etc.)."""
    if domain != "ai-commercial":
        return AssertionResult(
            "_no_cross_domain_noise", True, "#319", "P1", domain, product,
            "not ai-commercial",
        )
    found = sorted({k for k in _AI_COMMERCIAL_NOISE if k in text})
    return AssertionResult(
        "_no_cross_domain_noise", not found, "#319", "P1", domain, product,
        "noise=" + ", ".join(found) if found else "clean",
    )


def _no_financial_dilution(text: str, domain: str, product: str) -> AssertionResult:
    """(—) financial-intelligence digest has no pure SEC 8-K/10-Q metadata
    dilution (v1.1 solved, v3 regressed — must be guarded)."""
    if domain != "financial-intelligence":
        return AssertionResult(
            "_no_financial_dilution", True, "—", "P1", domain, product,
            "not financial",
        )
    found = sorted({k for k in _FIN_DILUTION if k in text})
    return AssertionResult(
        "_no_financial_dilution", not found, "—", "P1", domain, product,
        "dilution=" + ", ".join(found) if found else "clean",
    )


def _not_empty(text: str, domain: str, product: str) -> AssertionResult:
    """#294 — the product is not empty (has a title + some body)."""
    ok = bool(text.strip()) and len(text.strip()) > 10
    return AssertionResult(
        "_not_empty", ok, "#294", "P1", domain, product,
        f"{len(text.strip())} chars",
    )


ASSERTION_FUNCS: list[tuple[str, Callable[[str, str, str], AssertionResult]]] = [
    ("_title_first", _title_first),
    ("_no_error_leak", _no_error_leak),
    ("_references_numbered", _references_numbered),
    ("_source_labels_specific", _source_labels_specific),
    ("_no_placeholder", _no_placeholder),
    ("_no_internal_leak", _no_internal_leak),
    ("_column_deep_dive", _column_deep_dive),
    ("_report_sections", _report_sections),
    ("_metadata_consistency", _metadata_consistency),
    ("_no_cross_domain_noise", _no_cross_domain_noise),
    ("_no_financial_dilution", _no_financial_dilution),
    ("_not_empty", _not_empty),
]

assertion_names = [name for name, _ in ASSERTION_FUNCS]


def run_assertions(
    text: str, *, domain: str = "", product: str = ""
) -> list[AssertionResult]:
    """Run the full formalized assertion set against one rendered product."""
    return [fn(text, domain, product) for _, fn in ASSERTION_FUNCS]


# ---------------------------------------------------------------------------
# Generation / matrix runner (real KB path)
# ---------------------------------------------------------------------------


def _current_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path.cwd(), timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _generate_product(
    domain: str, product: str, product_template: Any
) -> str:
    """Call the REAL generation functions (deterministic fallbacks apply when
    no LLM key is set) — the path `output digest --product`/`report` uses."""
    from autoinfo.output import generate_digest, generate_report

    if product in ("report", "premium-briefing", "enterprise-briefing",
                   "column", "magazine-digest"):
        return _as_str(generate_report(
            domain, format="markdown", product_template=product_template,
        ))
    return _as_str(generate_digest(
        domain, format="markdown", product_template=product_template,
    ))


def _persisted_product_paths(
    domain: str, product: str, base_dir: Path | None = None
) -> list[Path]:
    """Locate previously-persisted product files under ``<base>/<domain>/``.

    ``base`` defaults to the shared ``outputs/`` for backward compatibility;
    pass the per-batch products root (``<artifacts>/<batch_id>/products``) to
    scan an isolated batch tree (#335) instead.
    """
    base = (base_dir or Path("outputs")) / domain
    if not base.is_dir():
        return []
    # Prefer the newest matching file; names like digest-<product>-* or
    # report-<product>-*.md / digest-markdown-*.md
    candidates = [
        p for p in base.iterdir()
        if p.is_file()
        and p.suffix in (".md", ".txt", ".html")
        and (
            product in p.name
            or ("digest-" if product == "digest" else product) in p.name
        )
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def _product_templates() -> list[tuple[str, Any]]:
    from autoinfo.output import PRODUCT_TEMPLATES

    return [(row["name"], row["template"]) for row in PRODUCT_TEMPLATES]


MATRIX_PRODUCTS: tuple[str, ...] = (
    "digest", "report", "column", "premium-briefing",
    "enterprise-briefing", "magazine-digest", "tutorial", "presentation",
)


def run_matrix(
    domains: list[str],
    products: list[str] | None = None,
    *,
    only_assert: bool = False,
    batch_id: str | None = None,
    artifacts_dir: Path | None = None,
) -> MatrixReport:
    """Run the domain x product matrix.

    Full mode generates each product through the REAL generation path when a
    matching ProductTemplate exists; products without a template fall back to
    digest/report with the product name (so the grid always renders).
    ``only_assert`` scans already-persisted product files instead.

    Batch isolation (#335): every run owns a ``batch_id`` (explicit, or
    ``<commit>-<stamp>``).  When ``artifacts_dir`` is given, full mode persists
    its generated products under ``artifacts_dir/<batch_id>/products/
    <domain>/<product>-markdown-<batch_id>.md`` (successive batches never
    overwrite each other) and ``only_assert`` scans that same batch tree.
    Without ``artifacts_dir``, full mode stays in-memory and ``only_assert``
    falls back to the legacy shared ``outputs/`` scan.
    """
    chosen = list(products or MATRIX_PRODUCTS)
    templates: dict[str, Any] = dict(_product_templates())
    commit = _current_commit()
    batch_id = batch_id or (
        f"{commit}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    batch_root = (
        (artifacts_dir / batch_id / "products") if artifacts_dir is not None else None
    )
    report = MatrixReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        commit=commit,
        batch_id=batch_id,
    )
    per_product: dict[str, list[dict[str, Any]]] = {p: [] for p in chosen}
    summary_failures = 0
    failing_assertions = 0
    missing_products = 0
    error_products = 0
    total_asserts = 0

    for domain in domains:
        for product in chosen:
            template = templates.get(product)
            if only_assert:
                paths = _persisted_product_paths(
                    domain, product, base_dir=batch_root
                )
                if not paths:
                    per_product[product].append({
                        "domain": domain, "product": product, "status": "missing",
                        "assertions": [], "error": "no persisted product file",
                    })
                    summary_failures += 1
                    missing_products += 1
                    continue
                text = paths[0].read_text(encoding="utf-8", errors="replace")
            else:
                try:
                    text = _generate_product(domain, product, template)
                except Exception as exc:  # generation failure -> reportable
                    per_product[product].append({
                        "domain": domain, "product": product, "status": "error",
                        "assertions": [], "error": str(exc)[:200],
                    })
                    summary_failures += 1
                    error_products += 1
                    continue
                if batch_root is not None:
                    out_path = (
                        batch_root / domain / f"{product}-markdown-{batch_id}.md"
                    )
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(text, encoding="utf-8")
            results = run_assertions(text, domain=domain, product=product)
            total_asserts += len(results)
            failing = [r for r in results if not r.passed]
            failing_assertions += len(failing)
            summary_failures += len(failing)
            per_product[product].append({
                "domain": domain, "product": product, "status": "ok",
                "assertions": [r.to_dict() for r in results],
            })

    products_out = []
    for product in chosen:
        for entry in per_product[product]:
            products_out.append({**entry, "product": product})
    report.products = products_out
    report.summary = {
        "batch_id": batch_id,
        "domains": domains,
        "products": chosen,
        "total_products": sum(len(v) for v in per_product.values()),
        "total_asserts": total_asserts,
        "failures": summary_failures,
        "failing_assertions": failing_assertions,
        "missing_products": missing_products,
        "error_products": error_products,
    }
    return report


# ---------------------------------------------------------------------------
# Report card persistence + regression diff (#332-A, #336)
# ---------------------------------------------------------------------------

PRODUCT_STATUS = "@status"


def card_issue_counts(card: dict[str, Any]) -> dict[str, int]:
    """Break a report card's failures down into the components a reader would
    count by hand (#336): failing assertions, missing products, error products."""
    failing = missing = error = 0
    for p in card.get("products", []):
        status = p.get("status", "ok")
        if status == "missing":
            missing += 1
        elif status == "error":
            error += 1
        for a in p.get("assertions", []):
            if not a.get("passed"):
                failing += 1
    return {
        "failing_assertions": failing,
        "missing_products": missing,
        "error_products": error,
    }


def save_report_card(
    report: MatrixReport, out_dir: Path
) -> Path:
    """Persist the report card as JSON; returns the written path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"report-card-{report.commit}-{stamp}.json"
    out.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def diff_report_cards(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    """#332-A regression diff: classify every (product, assertion) pair as
    new (cur-fail, not in prev), regressed (prev-pass, cur-fail),
    fixed (prev-fail, cur-pass) or existing-failing (both fail).

    Product-level failures (``status`` missing/error) are first-class diff
    items via the ``(product, PRODUCT_STATUS)`` pseudo-assertion (#336), so
    the counts reconcile with the failure count a reader computes from the
    cards: ``cur issues == new + regressed + existing_failing``.
    """
    def index(card: dict[str, Any]) -> dict[tuple[str, str], bool]:
        idx: dict[tuple[str, str], bool] = {}
        for p in card.get("products", []):
            product = p.get("product", "")
            idx[(product, PRODUCT_STATUS)] = p.get("status", "ok") == "ok"
            for a in p.get("assertions", []):
                key = (product, a.get("assertion", ""))
                idx[key] = bool(a.get("passed"))
        return idx

    prev_idx = index(prev)
    cur_idx = index(cur)
    new: list[tuple[str, str]] = []
    regressed: list[tuple[str, str]] = []
    fixed: list[tuple[str, str]] = []
    existing: list[tuple[str, str]] = []
    for key, cur_pass in cur_idx.items():
        prev_pass = prev_idx.get(key)
        if prev_pass is None:
            if not cur_pass:
                new.append(key)
        elif prev_pass and not cur_pass:
            regressed.append(key)
        elif not prev_pass and cur_pass:
            fixed.append(key)
        elif not prev_pass and not cur_pass:
            existing.append(key)
    return {
        "schema_version": 1,
        "new": new,
        "regressed": regressed,
        "fixed": fixed,
        "existing_failing": existing,
        "counts": {
            "new": len(new), "regressed": len(regressed),
            "fixed": len(fixed), "existing_failing": len(existing),
        },
    }
