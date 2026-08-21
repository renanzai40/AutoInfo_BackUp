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

* ``AssertionResult`` + a formalized 19-assertion set (``run_assertions``) —
  one readable function per assertion, each with the source issue commented.
* ``run_matrix`` — generates products over a domains x products grid on the real
  KB path (``generate_digest``/``generate_report``) and asserts each; supports
  ``only_assert`` (scan existing persisted products, no regeneration).
* ``MatrixReport`` / ``save_report_card`` — report-card JSON (per
  product x assertion pass/fail + summary) persisted with commit sha + timestamp.
* ``diff_report_cards`` (#332-A) — regression diff classifying each
  (product, assertion) as new / regressed / fixed / existing-failing.
* ``_references_reachable`` (#352) — deterministic form-check on every
  ``[View Source]`` / References / bare http(s) URL plus an OPTIONAL network
  reachability HEAD pass.  The slow (network) half runs ONLY when explicitly
  requested via ``run_assertions(..., include_slow=True)`` / the CLI
  ``--link-check`` flag; the default fast path never touches the network.

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
            "schema_version": 2,
            "tool": "autoinfo validate --matrix",
            "generated_at": self.generated_at,
            "commit": self.commit,
            "batch_id": self.batch_id,
            "products": self.products,
            "summary": self.summary,
        }


@dataclass
class SkipPolicy:
    """#348 — smart-skip policy for ``validate --matrix``.

    When ``allow_skip`` is True and a (domain, product) pair has passed
    ``threshold`` consecutive batches with no code change and no new raw data,
    the pair is NOT regenerated: the last persisted artifact is reused, the
    cheap assertion pass runs on it (防漏 — a now-failing artifact is reported
    as failing, not skipped), and the row is marked ``frozen``/``stale``.

    Default ``allow_skip=False`` keeps every existing caller regenerating.
    """

    allow_skip: bool = False
    threshold: int = 3
    skip_premium: bool = False
    data_dir: Path | None = None  # KB root; raw-entry counts under <data_dir>/<domain>/01-Raw/


# ---------------------------------------------------------------------------
# #348 — smart-skip of stable (domain, product) pairs
# ---------------------------------------------------------------------------


def _premium_products() -> set[str]:
    """The products held to the stricter #348 skip bar: the non-free
    PRODUCT_TEMPLATES rows that appear in the matrix grid."""
    from autoinfo.output import PRODUCT_TEMPLATES

    return {
        row["name"]
        for row in PRODUCT_TEMPLATES
        if row.get("access_level") != "free" and row["name"] in MATRIX_PRODUCTS
    }


def _load_batch_history(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Glob ``report-card-*.json`` under the snapshot dir's batch subdirs and
    return the parsed cards sorted oldest→newest by ``(generated_at, batch_id)``."""
    if snapshot_dir is None or not snapshot_dir.is_dir():
        return []
    cards: list[dict[str, Any]] = []
    for batch_dir in snapshot_dir.iterdir():
        if not batch_dir.is_dir():
            continue
        for card_path in batch_dir.glob("report-card-*.json"):
            try:
                cards.append(json.loads(card_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    cards.sort(
        key=lambda c: (
            str(c.get("generated_at", "")),
            str(c.get("batch_id", "")),
        )
    )
    return cards


def _find_product_row(
    card: dict[str, Any], domain: str, product: str
) -> dict[str, Any] | None:
    """The (domain, product) row of one report card, or None when absent."""
    return next(
        (
            p for p in card.get("products", [])
            if p.get("domain") == domain and p.get("product") == product
        ),
        None,
    )


def _row_passes(card: dict[str, Any], domain: str, product: str) -> bool:
    """True when the (domain, product) row exists, status == "ok" and every
    stored assertion passed."""
    row = _find_product_row(card, domain, product)
    if row is None or row.get("status") != "ok":
        return False
    return all(a.get("passed") for a in row.get("assertions", []))


def _consecutive_passes(
    history: list[dict[str, Any]], domain: str, product: str
) -> int:
    """TRAILING count of consecutive fully-passing batches for (domain,
    product); a failing/missing row anywhere in the middle resets the count."""
    count = 0
    for card in reversed(history):
        if _row_passes(card, domain, product):
            count += 1
        else:
            break
    return count


def _last_pass_commit(
    history: list[dict[str, Any]], domain: str, product: str
) -> str | None:
    """The commit of the newest trailing fully-passing batch, or None when the
    newest batch's row is missing or failing."""
    if not history or not _row_passes(history[-1], domain, product):
        return None
    return history[-1].get("commit")


def _code_changed(
    since_commit: str, product: str, domain: str, template_paths: list[str]
) -> bool:
    """True when any tracked file under the product's template/render paths
    changed since ``since_commit``.  Conservative on failure: a git error
    returns True (regenerate rather than skip on unknown state)."""
    if not template_paths:
        return False
    paths = [str(p) for p in template_paths]
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{since_commit}..HEAD", "--", *paths],
            capture_output=True, text=True, cwd=Path.cwd(), timeout=5,
        )
        if out.returncode != 0:
            return True
        return bool(out.stdout.strip())
    except Exception:
        return True


def _raw_entry_count(domain: str, data_dir: Path) -> int:
    """Count ``.md`` files under ``<data_dir>/<domain>/01-Raw/`` (recursively —
    entries live under ``01-Raw/<topic>/...``).  Missing dir → 0."""
    raw_dir = data_dir / domain / "01-Raw"
    if not raw_dir.is_dir():
        return 0
    return len(list(raw_dir.rglob("*.md")))


def _should_skip(
    history: list[dict[str, Any]],
    domain: str,
    product: str,
    *,
    policy: SkipPolicy,
    template_paths: list[str],
    raw_counts: dict[str, int],
) -> bool:
    """Pure #348 skip decision for one (domain, product) pair.

    All of the following must hold:

    * trailing consecutive passes >= threshold (premium products need
      ``threshold + 2`` unless ``skip_premium`` opts in);
    * no code change since the newest passing commit (only checked when that
      commit is real — with a None commit the consecutive count is 0 anyway);
    * raw data unchanged: if the newest card recorded per-domain raw counts,
      the run's counts must match.
    """
    threshold = policy.threshold
    if product in _premium_products() and not policy.skip_premium:
        threshold += 2
    if _consecutive_passes(history, domain, product) < threshold:
        return False
    last_commit = _last_pass_commit(history, domain, product)
    if last_commit is not None and _code_changed(
        last_commit, product, domain, template_paths
    ):
        return False
    if history:
        recorded = history[-1].get("summary", {}).get("raw_counts", {}).get(domain)
        if recorded is not None and raw_counts.get(domain) != recorded:
            return False
    return True


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
# #351 — hard security assertions.  Years below 1950 (and any future year) are
# treated as hallucination in product prose; years 1950..current year are the
# only plausible ones.  ``datetime.now()`` is a small helper so tests can patch
# the current year without touching the module's regex constants.
_MIN_PLAUSIBLE_YEAR = 1950
_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
_MONTH_YEAR_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<y>(?:18|19|20)\d{2})\b"
)
# URL-embedded 4-digit runs (e.g. "https://x.com/2023/01") are legitimate —
# never fire the year checks on the path/query portion of a URL.
_URL_RE = re.compile(r"https?://\S+")
# #351 V4 — a FUTURE year is only a hallucination when it is asserted as a
# completed fact.  Forward-looking projections ("Revenue to double by 2030",
# "targeting 2027", "2025-2030 runway") are legitimate financial prose.
# Projection markers searched on the line containing the year:
_FORWARD_LOOKING_RE = re.compile(
    r"\b(?:target(?:s|ed|ing)?|forecast(?:s|ed|ing)?|project(?:s|ed|ion|ions|ing)?|"
    r"expect(?:s|ed|ing)?|plan(?:s|ned|ning)?|aim(?:s|ed|ing)?|outlook|guidance|"
    r"goal(?:s)?|fiscal|trajectory|pipeline|runway|through|until|toward|towards|"
    r"anticipated?|envisioned?)\b",
    re.IGNORECASE,
)
# "by 2030" / "by the year 2027" / "by July 2027" — strong forward markers
# (bare "by" as a preposition is too common to be one, so it must directly
# precede a year, optionally via a month name).
_BY_YEAR_RE = re.compile(
    r"\bby\s+(?:the\s+)?(?:calendar\s+)?(?:year\s+)?"
    r"(?:(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+)?(?:18|19|20)\d{2}\b",
    re.IGNORECASE,
)
# A year range "2025-2030" / "2027–2030" is inherently forward-looking.
_YEAR_RANGE_RE = re.compile(r"\b(?:18|19|20)\d{2}\s*[-–]\s*(?:18|19|20)\d{2}\b")
# Fenced code blocks are never acceptable in a delivered product.
_FENCE_RE = re.compile(r"```[\s\S]*?```")
# API-key / token / secret prefix shapes: sk- (OpenAI), AIza (Google),
# AKIA (AWS access key id), ghp_/gho_/github_pat_ (GitHub), eyJ (JWT header).
_KEY_SHAPES_RE = re.compile(
    r"\b(?:sk-|AIza[0-9A-Za-z_-]+|AKIA[0-9A-Z]+|gh[pous]_[0-9A-Za-z]+"
    r"|github_pat_[0-9A-Za-z_]+|eyJ[A-Za-z0-9_-]+)"
)
# Long hex runs (>=32 chars) and long base64 runs (>=40 chars, optional ==
# padding) are credential-shaped.
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_LONG_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
# Broken-reference shapes (#351): [View Source](...) targets that are empty or
# scheme-less; References entries carrying no URL/identifier-bearing token.
_VIEW_SOURCE_RE = re.compile(r"\[View Source\]\(([^)]*)\)")
_REF_URL_TOKEN = re.compile(
    r"https?://|doi:|pmid:|arxiv:|isbn:", re.IGNORECASE
)
# Cross-domain noise markers (issue #319) / financial dilution markers.
_AI_COMMERCIAL_NOISE = (
    "贝达药业", "华能", "株冶", "平安好医生", "DURAVYU", "SEC 8-K", "SEC 8K",
    "10-Q", "10Q", "财报", "年报",
)
# #332: bare form ids ("8-K", "10-K") are included — stale SEC KB entries
# carry titles like "8-K Apple Inc. (2026-07-30)" / "10-K Apple Inc.
# (2026-01-15)" with no "SEC"/"filing" qualifier, so the dilution markers
# must match the bare form string too.
_FIN_DILUTION = (
    "SEC 8-K", "SEC 8K", "8-K", "8K",
    "10-Q", "10Q", "10-K", "10K",
    "8-K filing", "8K filing",
)

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
    """#325 — every label surface (masthead/byline/table/references) carries a
    specific source name; '(RSS)' residue is 0 anywhere in the product.

    Scans the WHOLE body (not just the References section): stale
    pre-#323 entries can render the generic ``(RSS)`` label in the magazine
    byline/clusters, the digest entry table, or the masthead — all of which
    sit BEFORE the References heading and previously escaped detection.
    """
    body = text
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


def _current_year() -> int:
    """The current calendar year (small helper so tests can patch it)."""
    return datetime.now().year


def _no_year_hallucination(text: str, domain: str, product: str) -> AssertionResult:
    """#351 — product prose carries no hallucinated years.  A year is a TRUE
    hallucination only when it is implausible for the claim's context:
      * a FUTURE year (or bare month-year) asserted as a completed fact — no
        forward-looking marker (``by 2030`` / ``target`` / ``forecast`` /
        ``projected`` / ``fiscal`` / a ``2025-2030`` range) on the same line —
        fires P0;
      * a DISTANT-PAST year (< 1950) fires P1 "human review": historical
        references (e.g. ``founded in 1917``) are plausible in financial
        products, so the report card surfaces them for a human to judge rather
        than auto-failing them as P0.
    Plausible prose years (1950..current year) and forward-looking projections
    pass.  The References section (from the ``## References`` heading) is
    EXCLUDED — legitimate citations carry old years.  URL-embedded 4-digit
    runs never fire."""
    refs = _REFS_HEADING.search(text)
    body = text[:refs.start()] if refs else text
    body = _URL_RE.sub(" ", body)
    offending: list[str] = []
    for m in _MONTH_YEAR_RE.finditer(body):
        year = int(m.group("y"))
        if year > _current_year() and not _is_forward_looking(body, m):
            offending.append(f"future bare month-year {m.group(0)!r} ({year})")
        elif year < _MIN_PLAUSIBLE_YEAR:
            offending.append(
                f"distant-past bare month-year {m.group(0)!r} ({year}) — human review"
            )
    for m in _YEAR_RE.finditer(body):
        year = int(m.group(0))
        if year > _current_year() and not _is_forward_looking(body, m):
            offending.append(f"future year {year}")
        elif year < _MIN_PLAUSIBLE_YEAR:
            offending.append(f"distant-past year {year} — human review")
    severe = any(o.startswith(("future", "implausible")) for o in offending)
    return AssertionResult(
        "_no_year_hallucination", not offending, "#351",
        "P0" if severe else "P1", domain, product,
        "; ".join(dict.fromkeys(offending)) if offending else "no year issues",
    )


def _is_forward_looking(text: str, m: re.Match[str]) -> bool:
    """True when the matched year sits in a forward-looking context: the line
    carries a projection marker (``target`` / ``forecast`` / ``projected`` /
    ``expected`` / ``fiscal`` / ``by 2030`` / …) or the year is part of a
    year-range like ``2025-2030``."""
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end = text.find("\n", m.end())
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    if _YEAR_RANGE_RE.search(line):
        return True
    return bool(_BY_YEAR_RE.search(line) or _FORWARD_LOOKING_RE.search(line))


def _no_code_or_key_leak(text: str, domain: str, product: str) -> AssertionResult:
    """#351 — fenced code blocks and API-key/token shapes never reach a
    product: ``sk-``/``AIza``/``AKIA``/``ghp_``/``gho_``/``github_pat_``/
    ``eyJ`` prefixes, long hex runs (>=32), long base64 runs (>=40)."""
    bad: list[str] = []
    if _FENCE_RE.search(text):
        bad.append("fenced code block")
    for m in _KEY_SHAPES_RE.finditer(text):
        bad.append(f"{m.group(0)[:20]}...")
    for m in _LONG_HEX_RE.finditer(text):
        bad.append(f"long hex run ({len(m.group(0))} chars)")
    for m in _LONG_B64_RE.finditer(text):
        bad.append(f"long base64 run ({len(m.group(0))} chars)")
    return AssertionResult(
        "_no_code_or_key_leak", not bad, "#351", "P0", domain, product,
        "leak=" + ", ".join(dict.fromkeys(bad)) if bad else "no code/key shapes",
    )


def _no_broken_reference(text: str, domain: str, product: str) -> AssertionResult:
    """#351 — no empty ``[View Source]()``, no scheme-less ``[View Source]
    (not a url)`` target, and no References entry without a URL-bearing
    token (http/https or the legit identifier schemes doi:/pmid:/arxiv:/
    isbn:)."""
    bad: list[str] = []
    for m in _VIEW_SOURCE_RE.finditer(text):
        target = m.group(1).strip()
        if not target:
            bad.append("empty [View Source] target")
        elif not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            bad.append(f"[View Source] target {target[:30]!r} has no scheme")
    refs = _REFS_HEADING.search(text)
    if refs:
        for line in text[refs.start():].splitlines():
            if _REF_ENTRY.match(line) and not _REF_URL_TOKEN.search(line):
                bad.append(f"reference without URL/identifier: {line[:40]!r}")
    return AssertionResult(
        "_no_broken_reference", not bad, "#351", "P0", domain, product,
        "broken=" + "; ".join(bad) if bad else "no broken references",
    )


def _no_external_error_text(text: str, domain: str, product: str) -> AssertionResult:
    """#351 — the WHOLE body carries no external-lib error text: ANSI
    escapes anywhere (the ``_no_error_leak`` header-only gap), litellm
    'Give Feedback / Get Help' / 'BerriAI' markers, and Python
    tracebacks."""
    bad: list[str] = []
    if _ANSI.search(text):
        bad.append("ANSI escape")
    if _LITELLM.search(text):
        bad.append("litellm/BerriAI marker")
    if _TRACEBACK.search(text):
        bad.append("traceback")
    return AssertionResult(
        "_no_external_error_text", not bad, "#351", "P0", domain, product,
        "; ".join(bad) if bad else "no external error text",
    )


# ---------------------------------------------------------------------------
# #357 — paid-tier semantic weak assertions.  The paid products must carry
# substantive analysis: per-takeaway So-what/Risk/Actions in premium-briefing,
# Action Required + Recommendations in enterprise-briefing, Implications &
# Outlook in column, and Recommendations in report.  The checks below are
# weak/WARN (P1) — they flag placeholders, sub-40-char filler, formulaic
# deterministic fallbacks, generic boilerplate risk labels, and So-what text
# that merely restates the takeaway heading.
# ---------------------------------------------------------------------------

_PAID_ANALYSIS_PRODUCTS = ("premium-briefing", "enterprise-briefing", "column", "report")
# premium-briefing per-takeaway field extraction regexes (re.MULTILINE on
# heading split; per-field match on stripped single lines).
_PREMIUM_TAKEAWAY_RE = re.compile(r"^###\s+\d+\.\s", re.MULTILINE)
_SOURCE_SUFFIX_RE = re.compile(r"\s*\(Source:\s*[^)]*\)\s*$")
_SO_WHAT_RE = re.compile(r"^>\s*\*\*So what\*\*:\s*(.*)$")
_RISK_LINE_RE = re.compile(r"^\*\*Risk / Opportunity:\*\*\s*(.*)$")
_RISK_TITLE_RE = re.compile(r"^\*\*Risk / Opportunity:\*\*\s*(.*?)(?:\s*—\s*|$)")
_ACTIONS_LINE_RE = re.compile(r"^\*\*Actions:\*\*\s*(.*)$")
# section-scoped extraction helpers
_CHECKBOX_ITEM_RE = re.compile(r"^-\s*\[\s*[ xX]\s*\]\s*(.+)$", re.MULTILINE)
_BULLET_ITEM_RE = re.compile(r"^-\s+(?:\[\s*[ xX]\s*\]\s*)?(.+)$", re.MULTILINE)
_BOLD_BULLET_TITLE_RE = re.compile(r"^-\s*\*\*(.+?)\*\*", re.MULTILINE)
# generic risk label blocklist (case-insensitive exact match)
_GENERIC_RISK_LABELS = (
    "valuation bubble risk", "market risk", "general risk",
    "unknown risk", "n/a risk", "risk risk",
)
# deterministic no-LLM fallback formula prefixes (lowered)
_FORMULAIC_PREFIXES = (
    "monitor developments around", "track ", "uncertain trajectory for",
)


# --- #357 shared helpers --------------------------------------------------


def _premium_takeaways(text: str) -> list[dict[str, str]]:
    """Split the premium-briefing ``## Key Takeaways`` section (up to
    ``## References``) into per-takeaway dicts: ``heading`` / ``so_what`` /
    ``risk`` (full line) / ``risk_title`` / ``actions`` ('' when the field
    marker line is absent — the ``_No ..._`` empty-state placeholders render
    without the ``**So what**`` / ``**Risk / Opportunity:**`` /
    ``**Actions:**`` labels)."""
    m = re.search(r"^##\s+Key Takeaways", text, re.MULTILINE)
    if not m:
        return []
    tail = text[m.end():]
    refs = _REFS_HEADING.search(tail)
    if refs:
        tail = tail[: refs.start()]
    parts = _PREMIUM_TAKEAWAY_RE.split(tail)
    takeaways: list[dict[str, str]] = []
    for part in parts[1:]:
        lines = part.splitlines()
        heading = ""
        if lines:
            heading = _SOURCE_SUFFIX_RE.sub("", lines[0].strip()).strip()
        takeaways.append({
            "heading": heading,
            "so_what": _takeaway_field(lines, _SO_WHAT_RE),
            "risk": _takeaway_field(lines, _RISK_LINE_RE),
            "risk_title": _takeaway_field(lines, _RISK_TITLE_RE),
            "actions": _takeaway_field(lines, _ACTIONS_LINE_RE),
        })
    return takeaways


def _takeaway_field(lines: list[str], field_re: re.Pattern[str]) -> str:
    """The captured text of the first line in *lines* matching *field_re*
    ('' when no line carries the field)."""
    for line in lines:
        m = field_re.match(line.strip())
        if m:
            return m.group(1).strip()
    return ""


def _is_weak_analysis(field: str) -> bool:
    """True when a premium per-takeaway analysis field is weak: empty,
    a template ``_No ..._`` placeholder, ``< 40`` chars, or a deterministic
    no-LLM formulaic fallback (``Monitor developments around …``,
    ``Track …``, ``Uncertain trajectory for …``)."""
    stripped = field.strip()
    if not stripped:
        return True
    if _PLACEHOLDER.search(stripped) or _PLACEHOLDER_TOKEN.match(stripped):
        return True
    if len(stripped) < 40:
        return True
    return stripped.lower().startswith(_FORMULAIC_PREFIXES)


def _section_text(text: str, section_name: str) -> str:
    """The body between ``## <section_name>`` and the next ``##`` heading
    ('' when the section is absent)."""
    m = re.search(rf"^##\s+{re.escape(section_name)}\b", text, re.MULTILINE)
    if not m:
        return ""
    tail = text[m.end() :]
    nxt = re.search(r"^##\s+\S", tail, re.MULTILINE)
    if nxt:
        tail = tail[: nxt.start()]
    return tail


def _table_first_cells(section: str) -> list[str]:
    """First cell (the Risk name) of every data row in a markdown table;
    the header row and ``---`` separator rows are skipped."""
    rows = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")]
    cells: list[str] = []
    for i, row in enumerate(rows):
        parts = [p.strip() for p in row.strip("|").split("|")]
        if i == 0 or not parts:
            continue
        first = parts[0]
        if re.fullmatch(r"-{2,}", first) or first.lower() == "risk":
            continue
        if first:
            cells.append(first)
    return cells


def _word_jaccard(a: str, b: str) -> float:
    """Case-insensitive word-set Jaccard similarity between two strings."""
    words_a = set(re.findall(r"[a-z0-9]+", a.lower()))
    words_b = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


# --- #357 assertion functions ---------------------------------------------


def _so_what_substantive(text: str, domain: str, product: str) -> AssertionResult:
    """#357 — paid-tier products carry substantive analysis: premium-briefing
    per-takeaway So-what/Risk/Actions, enterprise Action Required +
    Recommendations, column Implications & Outlook, report Recommendations.
    Flags empty/placeholder/less-than-40-char/formulaic fields.  Other products pass
    informationally (like ``_column_deep_dive`` does for non-column)."""
    if product not in _PAID_ANALYSIS_PRODUCTS:
        return AssertionResult(
            "_so_what_substantive", True, "#357", "P1", domain, product,
            "not a paid-analysis product",
        )
    weak: list[str] = []
    if product == "premium-briefing":
        for i, tk in enumerate(_premium_takeaways(text), start=1):
            for label, field in (
                ("so-what", tk["so_what"]),
                ("risk", tk["risk"]),
                ("actions", tk["actions"]),
            ):
                if _is_weak_analysis(field):
                    weak.append(f"takeaway {i} {label} is weak")
    elif product == "enterprise-briefing":
        if not _CHECKBOX_ITEM_RE.search(_section_text(text, "Action Required")):
            weak.append("Action Required has no - [ ] item")
        recs = _section_text(text, "Recommendations")
        if recs and not _BULLET_ITEM_RE.search(recs):
            weak.append("Recommendations empty")
    elif product == "column":
        outlook = _section_text(text, "Implications & Outlook")
        if outlook and not _BULLET_ITEM_RE.search(outlook):
            weak.append("Implications & Outlook empty")
    elif product == "report":
        recs = _section_text(text, "Recommendations")
        if recs and not _BULLET_ITEM_RE.search(recs):
            weak.append("Recommendations empty")
    return AssertionResult(
        "_so_what_substantive", not weak, "#357", "P1", domain, product,
        "; ".join(weak) if weak else "substantive analysis present",
    )


def _recommendation_labels(text: str, product: str) -> list[str]:
    """Extract the recommendation/action/risk label texts for a paid product:
    premium Actions + Risk titles; enterprise Action Required + Recommendations
    + Risk Matrix Risk column; column Implications & Outlook bullet titles;
    report Recommendations bullets."""
    labels: list[str] = []
    if product == "premium-briefing":
        for tk in _premium_takeaways(text):
            labels.append(tk["risk_title"])
            labels.append(tk["actions"])
    elif product == "enterprise-briefing":
        labels.extend(
            _BULLET_ITEM_RE.findall(_section_text(text, "Action Required"))
        )
        labels.extend(
            _BULLET_ITEM_RE.findall(_section_text(text, "Recommendations"))
        )
        labels.extend(_table_first_cells(_section_text(text, "Risk Matrix")))
    elif product == "column":
        labels.extend(
            _BOLD_BULLET_TITLE_RE.findall(
                _section_text(text, "Implications & Outlook")
            )
        )
    elif product == "report":
        labels.extend(
            _BULLET_ITEM_RE.findall(_section_text(text, "Recommendations"))
        )
    return labels


def _recommendation_relevant(
    text: str, domain: str, product: str
) -> AssertionResult:
    """#357 — recommendation/risk labels are not generic boilerplate (the
    prompt forbids labels like "Valuation Bubble Risk") and not placeholders.
    Only clearly-generic labels with no concrete entity flag; no cross-domain
    relevance scoring."""
    if product not in _PAID_ANALYSIS_PRODUCTS:
        return AssertionResult(
            "_recommendation_relevant", True, "#357", "P1", domain, product,
            "not a paid-analysis product",
        )
    flagged: list[str] = []
    for label in _recommendation_labels(text, product):
        stripped = label.strip().strip("*").rstrip(".,;:")
        if not stripped:
            continue
        if _collect_placeholder_tokens(label):
            flagged.append(f"placeholder {stripped[:40]!r}")
        elif stripped.lower() in _GENERIC_RISK_LABELS:
            flagged.append(f"generic label {stripped[:40]!r}")
    return AssertionResult(
        "_recommendation_relevant", not flagged, "#357", "P1", domain, product,
        "; ".join(flagged) if flagged else "no generic risk labels",
    )


def _analysis_not_mere_repeat(
    text: str, domain: str, product: str
) -> AssertionResult:
    """#357 — premium-briefing So-what analysis must not merely restate the
    takeaway heading (which derives from the KB entry title/summary).  Flags
    word-Jaccard > 0.75 between So-what and heading on a short (< 120 chars)
    So-what — mostly repeating the heading with little added analysis."""
    if product != "premium-briefing":
        return AssertionResult(
            "_analysis_not_mere_repeat", True, "#357", "P1", domain, product,
            "not a premium-briefing product",
        )
    repetitive: list[str] = []
    for i, tk in enumerate(_premium_takeaways(text), start=1):
        so_what = tk["so_what"].strip()
        heading = tk["heading"].strip()
        if not so_what or not heading or len(so_what) >= 120:
            continue
        if _word_jaccard(so_what, heading) > 0.75:
            repetitive.append(f"takeaway {i} So-what restates heading")
    return AssertionResult(
        "_analysis_not_mere_repeat", not repetitive, "#357", "P1", domain,
        product,
        "; ".join(repetitive) if repetitive else "analysis adds beyond heading",
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
    ("_no_year_hallucination", _no_year_hallucination),
    ("_no_code_or_key_leak", _no_code_or_key_leak),
    ("_no_broken_reference", _no_broken_reference),
    ("_no_external_error_text", _no_external_error_text),
    ("_so_what_substantive", _so_what_substantive),
    ("_recommendation_relevant", _recommendation_relevant),
    ("_analysis_not_mere_repeat", _analysis_not_mere_repeat),
]

assertion_names = [name for name, _ in ASSERTION_FUNCS]


def run_assertions(
    text: str, *, domain: str = "", product: str = "", include_slow: bool = False
) -> list[AssertionResult]:
    """Run the full formalized assertion set against one rendered product.

    ``include_slow`` appends the SLOW (network) assertions — currently the
    #352 link-reachability pass.  Default ``False`` keeps the fast path
    deterministic and network-free.
    """
    results = [fn(text, domain, product) for _, fn in ASSERTION_FUNCS]
    if include_slow:
        results.extend(fn(text, domain, product) for _, fn in SLOW_ASSERTION_FUNCS)
    return results


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
    skip: SkipPolicy | None = None,
    include_slow: bool = False,
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

    #348 smart-skip: when ``skip`` is enabled (``allow_skip``) and not in
    ``only_assert`` mode, a (domain, product) pair that has passed
    ``threshold`` consecutive batches with no code change and no new raw data
    reuses its last persisted artifact instead of regenerating.
    ``include_slow`` (#352) threads the opt-in network link-reachability
    assertion into every ``run_assertions`` call below.
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
    skipped_products: list[str] = []

    skip_enabled = (
        skip is not None and skip.allow_skip and not only_assert
        and artifacts_dir is not None
    )
    history: list[dict[str, Any]] = []
    raw_counts: dict[str, int] = {}
    template_paths: list[str] = []
    skip_policy: SkipPolicy | None = None
    artifacts_root: Path | None = None
    if skip_enabled and skip is not None and artifacts_dir is not None:
        # mypy narrowing: skip_enabled is a compound boolean, so re-check the
        # two Optionals here to give mypy concrete types for the block below.
        skip_policy = skip
        artifacts_root = artifacts_dir
        history = _load_batch_history(artifacts_root)
        if skip.data_dir is not None:
            raw_counts = {
                d: _raw_entry_count(d, skip.data_dir) for d in domains
            }
        template_paths = [
            "src/autoinfo/data/templates",
            "src/autoinfo/output",
            "src/autoinfo/validation_matrix.py",
            "src/autoinfo/cli/validate.py",
        ]

    for domain in domains:
        for product in chosen:
            if skip_policy is not None and artifacts_root is not None and _should_skip(
                history, domain, product,
                policy=skip_policy, template_paths=template_paths,
                raw_counts=raw_counts,
            ):
                reused_batch = history[-1]["batch_id"]
                paths = _persisted_product_paths(
                    domain, product,
                    base_dir=artifacts_root / reused_batch / "products",
                )
                if paths:
                    reused_text = paths[0].read_text(
                        encoding="utf-8", errors="replace"
                    )
                    reused_results = run_assertions(
                        reused_text, domain=domain, product=product,
                        include_slow=include_slow,
                    )
                    reused_failing = [r for r in reused_results if not r.passed]
                    if not reused_failing:
                        reused_row = _find_product_row(
                            history[-1], domain, product
                        ) or {}
                        per_product[product].append({
                            "domain": domain, "product": product, "status": "ok",
                            "frozen": True, "reused_batch": reused_batch,
                            "freshness": "stale",
                            "consecutive_passes": _consecutive_passes(
                                history, domain, product
                            ),
                            "assertions": reused_row.get("assertions", []),
                        })
                        skipped_products.append(product)
                        continue
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
            results = run_assertions(
                text, domain=domain, product=product, include_slow=include_slow
            )
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
        "skipped_products": skipped_products,
        "raw_counts": raw_counts,
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
    """#332-A regression diff: classify every (domain, product, assertion)
    triple as new (cur-fail, not in prev), regressed (prev-pass, cur-fail),
    fixed (prev-fail, cur-pass) or existing-failing (both fail).

    The identity includes the DOMAIN (#340): a real matrix card spans
    several domains x the same product, so a ``(product, assertion)`` key
    would collide across domains and silently drop failures.  Product-level
    failures (``status`` missing/error) are first-class diff items via the
    ``(domain, product, PRODUCT_STATUS)`` pseudo-assertion (#336), so the
    counts reconcile with the failure count a reader computes from the
    cards: ``cur issues == new + regressed + existing_failing``.
    """
    def index(card: dict[str, Any]) -> dict[tuple[str, str, str], bool]:
        idx: dict[tuple[str, str, str], bool] = {}
        for p in card.get("products", []):
            domain = p.get("domain", "")
            product = p.get("product", "")
            idx[(domain, product, PRODUCT_STATUS)] = p.get("status", "ok") == "ok"
            for a in p.get("assertions", []):
                key = (domain, product, a.get("assertion", ""))
                idx[key] = bool(a.get("passed"))
        return idx

    prev_idx = index(prev)
    cur_idx = index(cur)
    new: list[tuple[str, str, str]] = []
    regressed: list[tuple[str, str, str]] = []
    fixed: list[tuple[str, str, str]] = []
    existing: list[tuple[str, str, str]] = []
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


# ---------------------------------------------------------------------------
# Cross-day stability (#352.1) — deterministic re-assertion + batch diff
# ---------------------------------------------------------------------------


def _newest_persisted_product(
    products_root: Path, domain: str, product: str
) -> Path | None:
    """Newest ``<product>-markdown-*.md`` for (domain, product), or None.

    Newest = highest ``-markdown-*`` suffix (lexical; the #335 stamps are
    zero-padded ``%Y%m%d-%H%M%S`` so lexical order == chronological and is
    immune to mtime skew from copy/rsync).
    """
    base = products_root / domain
    if not base.is_dir():
        return None
    matches = sorted(
        (p for p in base.iterdir()
         if p.is_file() and p.name.startswith(f"{product}-markdown-")),
        key=lambda p: p.name,
        reverse=True,
    )
    return matches[0] if matches else None


def assert_persisted_batch(
    batch_root: Path,
    domains: list[str],
    products: list[str],
    *,
    include_slow: bool = False,
) -> dict[str, Any]:
    """Re-assert the persisted products of one batch into a report-card-shaped
    dict (#352.1).  NEVER regenerates: each (domain, product) row reads the
    newest ``<product>-markdown-*.md`` file and runs the deterministic
    ``run_assertions`` on it, so a stability diff reflects genuine assertion
    pass/fail drift — LLM nondeterminism cannot produce a false diff.

    Returns a ``MatrixReport.to_dict()``-shaped card: ``schema_version 2``,
    ``tool``, ``commit`` (via ``_current_commit``), ``batch_id`` (the root
    dir name), ``products`` rows with ``status`` ``ok``/``missing``/``error``
    and per-assertion dicts, plus a ``summary`` breakdown.
    """
    rows: list[dict[str, Any]] = []
    failures = missing = error = total = 0
    for domain in domains:
        for product in products:
            path = _newest_persisted_product(batch_root, domain, product)
            if path is None:
                rows.append({
                    "domain": domain, "product": product, "status": "missing",
                    "assertions": [], "error": "no persisted product file",
                })
                missing += 1
                failures += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                rows.append({
                    "domain": domain, "product": product, "status": "error",
                    "assertions": [], "error": str(exc)[:200],
                })
                error += 1
                failures += 1
                continue
            results = run_assertions(
                text, domain=domain, product=product, include_slow=include_slow
            )
            failing = [r for r in results if not r.passed]
            failures += len(failing)
            total += len(results)
            rows.append({
                "domain": domain, "product": product, "status": "ok",
                "assertions": [r.to_dict() for r in results],
            })
    batch_id = batch_root.name
    summary = {
        "batch_id": batch_id,
        "domains": domains,
        "products": products,
        "total_products": len(rows),
        "total_asserts": total,
        "failures": failures,
        "failing_assertions": failures - missing - error,
        "missing_products": missing,
        "error_products": error,
    }
    return {
        "schema_version": 2,
        "tool": "autoinfo validate --matrix",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _current_commit(),
        "batch_id": batch_id,
        "products": rows,
        "summary": summary,
    }


def diff_batches(
    prev_root: Path,
    cur_root: Path,
    domains: list[str],
    products: list[str],
    *,
    include_slow: bool = False,
) -> dict[str, Any]:
    """Cross-day stability diff of two persisted batches (#352.1).

    Re-asserts both batches (deterministic, no regeneration) and runs
    ``diff_report_cards`` on the two report cards.  Returns ``prev_batch``
    and ``cur_batch`` cards, the ``diff`` output and ``stable`` — True when
    nothing regressed and nothing is new.

    ``include_slow`` (#352) threads the opt-in link-reachability assertion
    into both batch re-assertions.
    """
    prev_card = assert_persisted_batch(
        prev_root, domains, products, include_slow=include_slow
    )
    cur_card = assert_persisted_batch(
        cur_root, domains, products, include_slow=include_slow
    )
    diff = diff_report_cards(prev_card, cur_card)
    stable = diff["counts"]["regressed"] == 0 and diff["counts"]["new"] == 0
    return {
        "prev_batch": prev_card,
        "cur_batch": cur_card,
        "stable": stable,
        "diff": diff,
    }


# ---------------------------------------------------------------------------
# References link reachability (#352.2) — deterministic form-check + opt-in
# network reachability.  The network half runs ONLY when the caller asks
# (``include_slow=True`` / CLI ``--link-check``); the default fast path never
# touches the network.
# ---------------------------------------------------------------------------

# ``[View Source](url)`` targets, ``(Source: url)`` citations, bare http(s).
# Target groups allow one balanced paren level and the empty target (a bare
# ``[View Source]()`` is itself a form violation the check must catch).
_URL_EXTRACT_RE = re.compile(
    r"(?:\[View Source\]\(((?:\([^()]*\)|[^()])*)\)"
    r"|\(Source:\s*((?:\([^()]*\)|[^()])+)\)"
    r"|(https?://\S+))"
)

_LINK_CHECK_TIMEOUT = 3.0


def _extract_candidate_urls(text: str) -> list[str]:
    """Ordered candidate URLs in a product body: ``[View Source](url)``
    targets, ``(Source: url)`` citations and bare http(s) URLs.

    Duplicates are dropped keeping first occurrence order.  The link text
    itself is intentionally ignored — only the target is reachability-relevant.
    An empty ``[View Source]()`` target IS a candidate (it is a form
    violation), so empty captures are preserved, not skipped.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_EXTRACT_RE.finditer(text):
        target = next(
            (g for g in (m.group(1), m.group(2), m.group(3)) if g is not None),
            None,
        )
        if target is None:
            continue
        target = target.strip()
        if target not in seen:
            seen.add(target)
            out.append(target)
    return out


def _head_url(url: str, timeout: float) -> Any:
    """HEAD ``url``; returns the response (``.status_code``).  Deferred httpx
    import keeps module import safe; this seam is what tests patch."""
    import httpx

    return httpx.head(url, timeout=timeout, follow_redirects=True)


def _references_reachable(text: str, domain: str, product: str) -> AssertionResult:
    """#352 — every ``[View Source]``/References candidate URL must be real.

    Sub-check 1 (deterministic, always): the URL is non-empty and has an
    http/https scheme — ``javascript:``, bare relative paths and empty
    targets fail instantly, no network.

    Sub-check 2 (network, only when actually requested): HEAD each http(s)
    URL with a short timeout; 2xx/3xx resolves → ok; 4xx/5xx/connection
    error → fail (dead URL listed); timeout / unreachable → "unknown" (pass —
    flaky networks must not break validation).

    This assertion is wired ONLY into ``SLOW_ASSERTION_FUNCS`` (opt-in), so
    the deterministic form half never runs on the default fast path either.
    """
    import httpx  # noqa: PLC0415 — deferred import (network paths are opt-in)

    urls = _extract_candidate_urls(text)
    bad_form = [u for u in urls if not re.match(r"^https?://", u)]
    if bad_form:
        return AssertionResult(
            "_references_reachable", False, "#352", "P1", domain, product,
            f"invalid reference URL(s): {', '.join(repr(u) for u in bad_form)}",
        )
    http_urls = [u for u in urls if re.match(r"^https?://", u)]
    dead: list[str] = []
    unknown: list[str] = []
    for url in http_urls:
        try:
            resp = _head_url(url, _LINK_CHECK_TIMEOUT)
            code = int(getattr(resp, "status_code", 0))
            if 200 <= code < 400:
                continue
            dead.append(f"{url} (HTTP {code})")
        except (TimeoutError, httpx.TimeoutException):
            unknown.append(url)
        except httpx.RequestError:
            dead.append(url)
    if dead:
        return AssertionResult(
            "_references_reachable", False, "#352", "P1", domain, product,
            "unreachable reference URL(s): " + ", ".join(dead),
        )
    detail = f"checked {len(http_urls)} URL(s)"
    if unknown:
        detail += f"; {len(unknown)} timeout/unreachable treated as unknown"
    return AssertionResult(
        "_references_reachable", True, "#352", "P1", domain, product, detail,
    )


SLOW_ASSERTION_FUNCS: list[tuple[str, Callable[[str, str, str], AssertionResult]]] = [
    ("_references_reachable", _references_reachable),
]
