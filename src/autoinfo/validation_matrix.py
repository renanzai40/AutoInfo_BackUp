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
    products: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tool": "autoinfo validate --matrix",
            "generated_at": self.generated_at,
            "commit": self.commit,
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


def _no_placeholder(text: str, domain: str, product: str) -> AssertionResult:
    """#329/#314/#326 — no `_No ..._` empty-state placeholders in any product."""
    found = sorted(set(_PLACEHOLDER.findall(text)))
    return AssertionResult(
        "_no_placeholder", not found, "#329", "P0", domain, product,
        "placeholders=" + ", ".join(found) if found else "none",
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


def _persisted_product_paths(domain: str, product: str) -> list[Path]:
    """Locate previously-persisted product files under outputs/<domain>/."""
    base = Path("outputs") / domain
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
) -> MatrixReport:
    """Run the domain x product matrix.

    Full mode generates each product through the REAL generation path when a
    matching ProductTemplate exists; products without a template fall back to
    digest/report with the product name (so the grid always renders).
    ``only_assert`` scans already-persisted outputs/ files instead.
    """
    chosen = list(products or MATRIX_PRODUCTS)
    templates: dict[str, Any] = dict(_product_templates())
    report = MatrixReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        commit=_current_commit(),
    )
    per_product: dict[str, list[dict[str, Any]]] = {p: [] for p in chosen}
    summary_failures = 0
    total_asserts = 0

    for domain in domains:
        for product in chosen:
            template = templates.get(product)
            if only_assert:
                paths = _persisted_product_paths(domain, product)
                if not paths:
                    per_product[product].append({
                        "domain": domain, "product": product, "status": "missing",
                        "assertions": [], "error": "no persisted product file",
                    })
                    summary_failures += 1
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
                    continue
            results = run_assertions(text, domain=domain, product=product)
            total_asserts += len(results)
            failing = [r for r in results if not r.passed]
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
        "domains": domains,
        "products": chosen,
        "total_products": sum(len(v) for v in per_product.values()),
        "total_asserts": total_asserts,
        "failures": summary_failures,
    }
    return report


# ---------------------------------------------------------------------------
# Report card persistence + regression diff (#332-A)
# ---------------------------------------------------------------------------


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
    fixed (prev-fail, cur-pass) or existing-failing (both fail)."""
    def index(card: dict[str, Any]) -> dict[tuple[str, str], bool]:
        idx: dict[tuple[str, str], bool] = {}
        for p in card.get("products", []):
            for a in p.get("assertions", []):
                key = (p.get("product", ""), a.get("assertion", ""))
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
