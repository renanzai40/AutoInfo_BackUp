#!/usr/bin/env python3
"""All-dimension product quality gate over rendered .md product files.

Issue #188 (2026-09-02 retrospective): the R2-review battery
(``/tmp/m1_review_battery_r2.py``) proved its value during the M1-r2 rebuild —
it caught the cross fake-entry, med-report empty-shell, and cross-domain CJK
defects that the previous "all-green" wave missed.  But it lived in ``/tmp``,
was rewritten every session, scanned a single directory by glob, and had no
cross-product entity-consistency check.  This script versions that battery as
the standard delivery quality gate.

The check set (mirrors the R2 battery; rule ids below match the issue):

Format layer (F):
  F1  empty shell             — rendered file < 500 bytes of real text
  F2  placeholder markers     — TODO / PLACEHOLDER / 待补 / 占位 / TBD / {{
                               / [[待
  F3  doubled citations       — "(Source: A) (Source: A)" / "(Sources: B) …
                               (Sources: B)" back-to-back with the SAME source
                               (one-item-multi-source is legal and NOT flagged)
  F4  domain-forbidden words  — configurable per-domain blocklist (defaults:
                                none for demo domains; pass --forbidden-words
                                / --domain-blocklist to enable)

Content layer (C):
  C1  synthesized fake entry  — placeholder template title leaked into a
                               product body: "金融市场情报 N" / "AI 商业周报
                               N" / "医学研究前沿 N" / "英语学习素材 N" /
                               "weekly:" (mirrors the output-layer
                               _TITLE_PLACEHOLDER_RE + _SUMMARY_PLACEHOLDER_RE)
  C2  log / stack leak        — LiteLLM / Give Feedback / litellm._turn_on_debug
                               / ANSI escapes / raw JSON / prompt echo /
                               "Traceback (most recent call last):" (mirrors
                               output-layer _contains_raw_llm_leak + #328)
  C3  CJK residue             — non-bilingual product carries Chinese; count of
                               CJK ideographs above a per-domain threshold
                               (default 5, mirrors output _CJK_RE threshold).
                               Bilingual-by-design domains exempt (mirrors
                               _CJK_EXEMPT_DOMAINS): the *-learning domains.
                               NOTE (issue #188 design note vs codebase #181/
                               #186): the issue text suggested "ai-commercial
                               双语域豁免", but the shipped #181/#186 design
                               treats CJK in ai-commercial as a DEFECT (36kr
                               leaks into English products).  The gate follows
                               the codebase: default exemption = *-learning,
                               pass --cjk-exempt-domains to override.
  C4  truncated line          — 80-250 char line that ends without terminal
                               punctuation AND is not a markdown construct
                               (heading/link/table/fence/list/code).  A long
                               complete sentence with terminal punct is fine.
  C5  source integrity        — every (Source: <URL>) / [label](<URL>) cited in
                               the body must appear in the file's References
                               list (real products list their full source set
                               in a "## References" section).  Fabricated /
                               dangling citations are flagged.

Cross-product consistency (X1, the P0-4 addition — simple version):
  entity extraction + cross-file conflict marking.  For every real product
  file under a delivery directory, extract capitalized entity phrases
  (title-case company/product tokens of length >= 4) that appear in the body
  more than once, then for each entity collect the sentence-level claim
  fragments (the clause that mentions it).  Two files that both mention the
  same entity with DIFFERENT claim fragments are flagged as a possible
  conflict — the complex LLM-judged version is deferred (per issue: "先做
  简单版").

Exit code: 0 = all files clean, 1 = defects found, 2 = usage / IO error.

Usage (from repo root):

    python3 scripts/quality_gate.py outputs/ai-commercial   # exit 0
    # multi-dir + bilingual CJK exemption:
    python3 scripts/quality_gate.py outputs/ai-commercial outputs/b2b \
        --cjk-exempt-domains english-learning
    # domain-forbidden words (F4):
    python3 scripts/quality_gate.py <dir> --forbidden-words "horse" \
        --domain-blocklist "medical-research:cervical cancer,NICE"

Pure functions are unit-tested under tests/scripts/test_quality_gate.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# Constants (calibrated to the output-layer guards they mirror)
# ---------------------------------------------------------------------------

# C3 — CJK ideographs (mirrors output._CJK_RE).
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# Domains exempt from the CJK residue check because bilingual output is by
# design (mirrors output._CJK_EXEMPT_DOMAINS = {"english-learning"}, extended
# to every *-learning domain which is the language-learning family).
_CJK_EXEMPT_DOMAINS_DEFAULT = frozenset(
    {
        "english-learning",
        "french-learning",
        "hindi-learning",
        "italian-learning",
        "korean-learning",
        "language-learning",
        "portuguese-learning",
        "russian-learning",
        "spanish-learning",
    }
)

_CJK_DEFAULT_THRESHOLD = 5  # a stray ideograph in a code sample is not noise

# C1 — synthesized fake-entry placeholder markers.  Mirrors the output-layer
# _TITLE_PLACEHOLDER_RE + _SUMMARY_PLACEHOLDER_RE.  ``weekly:`` must appear as
# a BARE marker (entry title line or leading fragment) — a real editorial
# title like "SaaS Weekly: Strategic Insights" is legitimate and never a fake
# entry, so "Weekly:" alone mid-title is not enough.
_FAKE_ENTRY_RE = re.compile(
    r"(?:^\s*weekly:\s*$|金融市场情报\s*\d+|AI\s*商业周报\s*\d+"
    r"|医学研究前沿\s*\d+|英语学习素材\s*\d+|情报\s*\d+|周报\s*\d+"
    r"|素材\s*\d+|前沿\s*\d+|^本期.*要点)",
    re.IGNORECASE | re.MULTILINE,
)

# C2 — log / stack / raw-LLM leak (mirrors output._LEAK_* + #328).
_LEAK_RE = re.compile(
    r"(?:\x1b\[[0-9;]*m|"
    r"Give Feedback / Get Help|"
    r"BerriAI|"
    r"LiteLLM\.Info|"
    r"litellm\._turn_on_debug|"
    r"litellm\.exceptions\.|"
    r"Traceback \(most recent call last\):|"
    r"```json|"
    r'^\s*\{\s*"(?:title|entries|@type|digest_type)"\s*:'
    r"|(?:^|\n)\s*(?:You are a |As an AI |You are an AI ))",
    re.IGNORECASE | re.MULTILINE,
)

# F2 — placeholder / empty-state markers.  Latin markers (TODO/PLACEHOLDER/
# TBD) are matched CASE-SENSITIVELY: the literal artifact markers are
# uppercase, and case-insensitive matching fires on the Spanish word "todo"
# (all) and on prose that merely DESCRIBES a placeholder ("a mismatched
# placeholder for the actual article" is a report ABOUT one, not a marker).
# CJK markers are inherently unambiguous.
_PLACEHOLDER_RE = re.compile(r"(?:\bTODO\b|\bPLACEHOLDER\b|\bTBD\b|\{\{|\[\[待|待补|占位)")

# C4 — a line that is 80-250 chars and lacks terminal punctuation.  A line
# ending in a balanced citation ``)`` is treated as terminated (real products
# end key-finding bullets with ``(Source: <url>)``), so only a line that just
# STOPS mid-thought is flagged as truncated.
_TERMINAL_PUNCT_RE = re.compile(r"[.!?。！？…:)]$")

# C5 — body citation shapes.  A body citation is "(Source: <URL>)" or
# "(Sources: <URL> and <URL>)" or "[label](<URL>)".  We extract the cited URLs
# and require each to be listed under the file's References section.
_BODY_SOURCE_RE = re.compile(
    r"\(Source[s]?:\s*((?:https?://[^)\s]+)(?:\s+and\s+https?://[^)\s]+)*)\)",
    re.IGNORECASE,
)
_BODY_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
_REFERENCES_HEADING_RE = re.compile(r"^#{1,6}\s*References\s*$", re.IGNORECASE)
_REF_LINE_URL_RE = re.compile(r"https?://[^\s)\]]+")

# F3 — doubled back-to-back citations with the SAME source.
_DOUBLED_CITATION_RE = re.compile(
    r"\(Source[s]?:\s*(https?://[^)\s]+)\)\s*\(Source[s]?:\s*(https?://[^)\s]+)\)",
    re.IGNORECASE,
)

# C5 — minimum required References section: real products carry one.  We flag
# a file whose body has >= 3 citations but NO References heading at all.
_MIN_CITATIONS_FOR_REF_CHECK = 3

# Empty-shell floor (F1) — a rendered product under this size is hollow.
_MIN_FILE_BYTES = 500


# ---------------------------------------------------------------------------
# Domain / language helpers
# ---------------------------------------------------------------------------


def _normalize_domain(raw: str) -> str:
    """Lowercase/trim a domain key, and derive it from a path when possible."""
    raw = raw.strip().lower()
    # "outputs/ai-commercial" or "outputs/ai-commercial/digest.md" -> the dir
    # name right under outputs/ is the domain; a bare filename has no domain.
    parts = [p for p in Path(raw).parts if p and p not in (".", "outputs")]
    if parts and parts[0] == "outputs":
        parts = parts[1:]
    if parts:
        return parts[0]
    return raw


def _domain_language(domain: str) -> str:
    """Best-effort language for a domain dir (reads the domain seed yaml)."""
    seed = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "autoinfo"
        / "data"
        / "domains"
        / domain
        / "sources.yaml"
    )
    if not seed.is_file():
        return ""
    try:
        import yaml  # PyYAML is a project dependency

        with open(seed, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return str(data.get("default_language") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Check primitives (pure — unit tested)
# ---------------------------------------------------------------------------


def find_empty_shell(text: str, min_bytes: int = _MIN_FILE_BYTES) -> list[str]:
    """F1: return defect strings when *text* is a hollow shell."""
    stripped = re.sub(r"\s+", "", text)
    if len(stripped.encode("utf-8")) < min_bytes:
        return [
            f"F1 empty shell: {len(stripped.encode('utf-8'))} non-space bytes "
            f"< {min_bytes}"
        ]
    return []


def find_placeholders(text: str) -> list[str]:
    """F2: return defect strings for placeholder markers."""
    out: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(text):
        start = max(0, m.start() - 30)
        ctx = text[start : m.end() + 30].replace("\n", " ")
        out.append(f"F2 placeholder marker {m.group(0)!r} near ...{ctx}...")
    return out


def find_doubled_citations(text: str) -> list[str]:
    """F3: flag back-to-back "(Source: X) (Source: X)" SAME-source duplicates.

    A one-item-multi-source citation "(Sources: A and B)" is legal and never
    flagged; only a literal doubled citation where the SECOND URL equals the
    FIRST (or where both halves name the same URL) is a defect.
    """
    out: list[str] = []
    for m in _DOUBLED_CITATION_RE.finditer(text):
        first, second = m.group(1), m.group(2)
        def _norm_url(url: str) -> str:
            return url.rstrip(".,;:!?)]").rstrip("/")
        if _norm_url(first) == _norm_url(second):
            out.append(
                f"F3 doubled citation: {first!r} repeated back-to-back"
            )
    return out


def find_forbidden_words(text: str, words: Sequence[str]) -> list[str]:
    """F4: return defect strings for domain-forbidden *words* present."""
    out: list[str] = []
    for w in words:
        wl = w.strip().lower()
        if not wl:
            continue
        if wl in text.lower():
            out.append(f"F4 forbidden word {w!r} present")
    return out


def find_fake_entries(text: str) -> list[str]:
    """C1: flag synthesized fake-entry placeholder titles in a product body."""
    out: list[str] = []
    for m in _FAKE_ENTRY_RE.finditer(text):
        start = max(0, m.start() - 40)
        ctx = text[start : m.end() + 40].replace("\n", " ")
        out.append(f"C1 synthesized fake entry marker {m.group(0)!r} near ...{ctx}...")
    return out


def find_llm_leaks(text: str) -> list[str]:
    """C2: flag raw LLM/log/stack leakage into a product.

    A single repeated error block (the same fragment hundreds of times — a
    corrupted product) is ONE defect, not one per occurrence: distinct
    fragments are collapsed to their first context each.
    """
    seen_fragments: set[str] = set()
    out: list[str] = []
    for m in _LEAK_RE.finditer(text):
        frag = m.group(0).strip()[:40]
        if frag in seen_fragments:
            continue
        seen_fragments.add(frag)
        start = max(0, m.start() - 40)
        ctx = text[start : m.end() + 40].replace("\n", " ")
        out.append(f"C2 log/stack/LLM leak {frag!r} near ...{ctx}...")
    return out


def count_cjk(text: str) -> int:
    """Return the number of CJK ideographs in *text*."""
    return len(_CJK_RE.findall(text))


def find_cjk_residue(
    text: str,
    domain: str,
    threshold: int = _CJK_DEFAULT_THRESHOLD,
    exempt_domains: frozenset[str] = _CJK_EXEMPT_DOMAINS_DEFAULT,
) -> list[str]:
    """C3: flag CJK residue in a non-bilingual domain product.

    ``*-learning`` domains are exempt (bilingual by design).  A CJK char
    count above *threshold* is a leak (a stray ideograph in a code sample is
    not).
    """
    domain_key = _normalize_domain(domain)
    if domain_key in exempt_domains:
        return []
    count = count_cjk(text)
    if count > threshold:
        return [
            f"C3 CJK residue: {count} CJK chars (threshold {threshold}) in "
            f"domain {domain_key!r}"
        ]
    return []


def find_truncated_lines(text: str) -> list[str]:
    """C4: flag 80-250 char lines lacking terminal punctuation.

    Skips markdown constructs: ATX headings, fenced-code fences, table rows,
    list items, blockquotes, horizontal rules, and lines that are bare links
    or image embeds.  Also skips product chrome: metadata lines
    (``**domain** · date · **N articles**``), footer signatures
    (``*AutoInfo <family> · domain · timestamp*``), and bold ``**Label:**``
    action/field lines (which are complete by construction).
    """
    out: list[str] = []
    seen_lines: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not (80 <= len(line) <= 250):
            continue
        # ANSI-escaped log lines are C2 leak territory (a raw error block was
        # prepended), not truncated prose — skip so C2 owns that defect class.
        if line.startswith("\x1b["):
            continue
        if _TERMINAL_PUNCT_RE.search(line):
            continue
        if re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|---+$|\|.*\||!?\[[^\]]*\]\()", line
        ):
            continue
        # Bold label/action lines: "**Actions:** **Council: Draft ..." are
        # chrome (label + instruction), never truncated prose.
        if re.match(r"^\*\*[^*]+:\*\*", line):
            continue
        # Metadata chrome: "**domain** · 2026-08-19 – 2026-08-26 · **N
        # articles** from M publications" (a real summary is not truncated).
        if re.match(r"^\*\*[a-z-]+\*\*\s*·", line):
            continue
        # Italic metadata line: "*Source — Name* · relevance N/100 ·
        # timestamp" (magazine-digest per-source chrome).
        if re.match(r"^\*[^*]+\*\s*·", line):
            continue
        # Footer signature: "*AutoInfo <Family> · domain · <timestamp>*".
        if re.match(r"^\*AutoInfo .*· .*· 20\d\d-", line):
            continue
        # A bare markdown link / image is complete without punctuation.
        if re.fullmatch(r"!?\[[^\]]*\]\([^)]*\)", line):
            continue
        # Collapse repeated identical truncated lines (a corrupted block
        # repeats the same broken line) to ONE defect with a count.
        if line[:80] in seen_lines:
            continue
        seen_lines.add(line[:80])
        out.append(
            f"C4 truncated line {lineno}: {len(line)} chars, no terminal "
            f"punctuation: {line[:60]!r}..."
        )
    return out


def _normalize_url(url: str) -> str:
    """Normalize a URL for citation comparison.

    Strips trailing punctuation/slashes and percent-decodes the URL so two
    spellings of the same resource compare equal (france24 renders the same
    video URL once percent-encoded and once as raw UTF-8: ``vid%C3%A9o`` vs
    ``vidéo``).
    """
    from urllib.parse import unquote

    u = url.rstrip(".,;:!?)]").rstrip("/")
    return unquote(u)


def _body_cited_urls(text: str) -> set[str]:
    """Return the normalized set of URLs cited in the body text."""
    urls: set[str] = set()
    for m in _BODY_SOURCE_RE.finditer(text):
        for u in m.group(1).split(" and "):
            urls.add(_normalize_url(u))
    for m in _BODY_MD_LINK_RE.finditer(text):
        urls.add(_normalize_url(m.group(1)))
    return urls


def _reference_urls(text: str) -> set[str]:
    """Return URLs found under the file's References section(s)."""
    lines = text.splitlines()
    in_refs = False
    urls: set[str] = set()
    for line in lines:
        if _REFERENCES_HEADING_RE.match(line.strip()):
            in_refs = True
            continue
        if in_refs:
            if re.match(r"^#{1,6}\s", line.strip()):
                break  # next top-level section ends References
            for u in _REF_LINE_URL_RE.findall(line):
                urls.add(_normalize_url(u))
    return urls


# Product families whose real render contract includes a "## References"
# section (report, premium/enterprise briefings).  Digest/column/magazine/
# tutorial/presentation cite sources INLINE by design — the References-
# integrity check (C5) only applies to families that are SUPPOSED to carry
# the section (verified across every demo-domain output).
_REFERENCE_BEARING_FAMILIES = frozenset(
    {"report", "premium-briefing", "enterprise-briefing"}
)


def _family_of(path: Path) -> str:
    """Best-effort product family from the file name (digest.md -> digest)."""
    return path.stem.lower()


def find_source_integrity(
    text: str, family: str = "", path: Path | None = None
) -> list[str]:
    """C5: flag body-cited URLs missing from the References section.

    Only applies to reference-bearing families (report / *-briefing /
    tutorial).  A product that cites >= _MIN_CITATIONS_FOR_REF_CHECK distinct
    URLs but has NO References heading is structurally broken; otherwise every
    body-cited URL must appear in the References section.
    """
    if path is not None:
        family = _family_of(path)
    if family and family not in _REFERENCE_BEARING_FAMILIES:
        return []
    body = _body_cited_urls(text)
    if not body:
        return []
    refs = _reference_urls(text)
    out: list[str] = []
    if not refs:
        if len(body) >= _MIN_CITATIONS_FOR_REF_CHECK:
            out.append(
                f"C5 source integrity: {len(body)} body citations but no "
                "References section"
            )
        return out
    missing = sorted(body - refs)
    # A References URL that is a PREFIX of a body URL (path-boundary) aligns
    # to the same article — the References renderer may truncate a long URL
    # while the body cites the full form (france24/observador style).  Only a
    # URL with NO aligned prefix in References is a genuine dangling citation.
    dangles = [
        u
        for u in missing
        if not any(u.startswith(r) and u[len(r) : len(r) + 1] in ("", "/", "-", "?")
                   for r in refs)
    ]
    for u in dangles:
        out.append(f"C5 dangling citation not in References: {u}")
    return out


# ---------------------------------------------------------------------------
# Cross-product consistency (X1) — simple version (entity + conflict marking)
# ---------------------------------------------------------------------------

# Entity candidate: 1-6 title-case tokens (len >= 4 chars total), optionally
# containing internal punctuation ("OpenAI's" / "Perplexity's").
_ENTITY_RE = re.compile(
    r"\b[A-Z][a-zA-Z0-9&.'-]*(?:\s+[A-Z][a-zA-Z0-9&.'-]*){0,5}\b"
)

# Generic capitalized nouns that routinely appear in product chrome
# (headings, field labels, boilerplate) — never entity names.
_GENERIC_ENTITY_STOP = frozenset(
    {
        "the", "a", "an", "this", "that", "these", "those", "how", "what",
        "why", "when", "weekly", "monthly", "daily", "digest", "report",
        "column", "tutorial", "presentation", "premium", "enterprise",
        "magazine", "briefing", "references", "source", "sources", "domain",
        "period", "generated", "total", "entries", "entry", "executive",
        "summary", "key", "findings", "recommendations", "implications",
        "risks", "action", "required", "metrics", "overview", "introduction",
        "conclusion", "appendix", "market", "trend", "trends", "news",
        "business", "analysis", "insight", "insights", "outlook", "week",
        "month", "year", "ai", "saas", "api", "url", "http", "https", "n",
        "m", "fn", "note", "notes", "e-commerce", "ecommerce", "industry",
        "industries", "technology", "software", "hardware", "platform",
        "product", "products", "services", "service", "businesses", "tools",
        "tool", "startups", "startup", "company", "companies", "enterprise",
        "b2b", "b2c", "sectors", "sector", "space", "apps", "app",
    }
)

# Claim fragment = the sentence (up to 220 chars) containing the entity.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n{2,}")

# Product/company TYPE nouns — a copular identity claim must describe WHAT
# the entity is as a product/company ("a model-evaluation platform", "an
# AI-native operating system").  Description phrases WITHOUT a type noun
# ("a focal point", "a positive signal") are news-analysis, not identity
# claims, and must not fire the cross-product conflict detector.
_TYPE_NOUN_RE = re.compile(
    r"\b(?:platform|company|firm|startup|provider|vendor|tool|service|"
    r"app|application|suite|product|system|software|engine|framework|"
    r"model|solution|technology|business|network|marketplace|database|"
    r"language|library|kit|console|device|hardware|chip|processor|"
    r"operating\s+system|os)\b",
    re.IGNORECASE,
)


def extract_identity_claims(text: str) -> dict[str, list[str]]:
    """Return {entity: [identity claims]} — the P0-4 conflict signal.

    Only COPULAR identity claims are extracted ("<Entity> is/are/was/were a
    <description>", or "<Entity> —/:/, <description>"), because that is the
    exact shape of the #188 P0-4 defect: one product calling a company "a
    legal-industry AI-native OS" while another calls it "a model-evaluation
    platform".  Event sentences ("Stripe acquired OpenRouter") are NOT
    identity claims — different products legitimately summarize events at
    different lengths, so those must never be flagged.
    """
    # Strip the References section (it lists titles, not claims).
    body = text
    ref_hit = _REFERENCES_HEADING_RE.search(body, re.MULTILINE)
    if ref_hit:
        body = body[: ref_hit.start()]
    # Drop chrome LINES before sentence-splitting: table rows, ATX headings,
    # list bullets, blockquotes, fenced code, and bare markdown link/image
    # lines (per-entry title links).  Prose paragraphs are the only source of
    # a stable product-level identity claim.
    prose_lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|") or re.match(
            r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|!?\[[^\]]*\]\()", line
        ):
            continue
        prose_lines.append(line)
    sentences = [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split("\n".join(prose_lines))
        if s.strip()
    ]
    out: dict[str, list[str]] = {}
    for sentence in sentences:
        # Clip a leading markdown link or "**Label**:" chrome off the prose.
        sentence = re.sub(r"^!?\[[^\]]*\]\([^)]*\)\s*", "", sentence)
        sentence = re.sub(r"^\*\*[^*]+\*\*:?\s*", "", sentence)
        if len(sentence) < 20:
            continue
        for ent in _ENTITY_RE.findall(sentence):
            key = ent.rstrip("'s").rstrip("'")
            if len(key) < 4:
                continue
            if key.lower() in _GENERIC_ENTITY_STOP:
                continue
            # Identity claim: <Entity> is/are/was/were [a|an|the] <noun-phrase
            # describing what Entity IS> — e.g. "X is a model-evaluation
            # platform".  The ARTICLE is required: "X is bringing its robotaxi
            # to Munich" is an EVENT claim (present continuous), not an
            # identity claim — different products legitimately paraphrase
            # events, so those must never conflict.
            m = re.search(
                rf"\b{re.escape(key)}\s+(?:is|are|was|were|remains|"
                rf"has become)\s+(a|an|the)\s+([A-Za-z0-9][^.!?\n]*)",
                sentence,
                re.IGNORECASE,
            )
            if not m:
                continue
            desc = m.group(2).strip()
            if len(desc) < 8:
                continue
            # The description must name a PRODUCT/COMPANY TYPE — the P0-4
            # conflict is about what a company IS ("X is a model-evaluation
            # platform"), not news-analysis ("Ukraine is a focal point").
            if not _TYPE_NOUN_RE.search(desc):
                continue
            out.setdefault(key, []).append(f"{key} is {m.group(1)} {desc}")
    return out


def _norm_claim(claim: str) -> str:
    """Canonicalize a claim fragment for comparison.

    Lowercase, collapse whitespace, and strip trailing markdown/citation
    residue (source URLs, (host) attributions) so two products quoting the
    same fact at different lengths compare equal.
    """
    c = re.sub(r"\(Source[s]?:[^)]*\)|\([^)]*https?://[^)]*\)|\([a-z0-9.-]+\)", " ", claim)
    c = re.sub(r"[#*_`>|-]", " ", c)
    c = re.sub(r"\s+", " ", c).strip().strip(".").strip()
    return c.lower()


def find_cross_product_conflicts(files: Sequence[Path]) -> list[str]:
    """X1: flag entities whose IDENTITY claims conflict across product files.

    Simple version (issue #188: "先做简单版, 复杂版后续"): collect each
    file's copular identity claims per entity; when the same entity carries
    DIFFERENT normalized identity claims in >= 2 files, mark the differing
    claim snippets as a possible description conflict.  Identical claims
    across files are agreement (not a conflict).  The complex LLM-judged
    semantic-conflict version is deferred.
    """
    claims_per_file: list[tuple[str, dict[str, list[str]]]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        claims = extract_identity_claims(text)
        if claims:
            claims_per_file.append((str(f), claims))

    out: list[str] = []
    reported_pairs: set[tuple[str, str]] = set()
    for fname, claims in claims_per_file:
        for ent, frags in sorted(claims.items()):
            # Normalize this file's claims for this entity.
            mine = {_norm_claim(f) for f in frags}
            if not mine:
                continue
            for other_fname, other_claims in claims_per_file:
                if other_fname == fname:
                    continue
                theirs = other_claims.get(ent)
                if not theirs:
                    continue
                theirs_norm = {_norm_claim(f) for f in theirs}
                # Conflict only when BOTH sides make an identity claim AND the
                # claim sets genuinely disagree (not a subset paraphrase).
                if mine and theirs_norm and not (mine & theirs_norm):
                    # Report each unordered file pair once (scanning A then B
                    # would otherwise double-report the symmetric pair).
                    pair: tuple[str, str] = (
                        (fname, other_fname)
                        if fname <= other_fname
                        else (other_fname, fname)
                    )
                    if pair in reported_pairs:
                        continue
                    reported_pairs.add(pair)
                    sample = " || ".join(sorted(mine | theirs_norm))[:280]
                    out.append(
                        f"X1 entity identity conflict: {ent!r} described "
                        f"differently in '{fname}' vs '{other_fname}': {sample}"
                    )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_CHECKS = {
    "F1": find_empty_shell,
    "F2": find_placeholders,
    "F3": find_doubled_citations,
    "C1": find_fake_entries,
    "C2": find_llm_leaks,
    "C4": find_truncated_lines,
    # C5 needs the file family (path) — invoked explicitly in gate_file.
}


def gate_file(
    path: Path,
    *,
    domain: str = "",
    forbidden_words: Sequence[str] = (),
    cjk_threshold: int = _CJK_DEFAULT_THRESHOLD,
    cjk_exempt_domains: frozenset[str] = _CJK_EXEMPT_DOMAINS_DEFAULT,
) -> list[str]:
    """Run every per-file check on one markdown product file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"IO {exc.__class__.__name__} reading {path}: {exc}"]
    defects: list[str] = []
    for rule, fn in _CHECKS.items():
        try:
            defects.extend(fn(text))
        except Exception as exc:  # a check bug must not kill the whole gate
            defects.append(f"{rule} check error on {path}: {exc}")
    defects.extend(find_forbidden_words(text, forbidden_words))
    defects.extend(
        find_cjk_residue(
            text, domain, threshold=cjk_threshold, exempt_domains=cjk_exempt_domains
        )
    )
    # C5 needs the file family (only report/briefings/tutorial are
    # reference-bearing) — pass the path so the check self-scopes.
    defects.extend(find_source_integrity(text, path=path))
    return defects


def gate_directory(
    directory: Path,
    *,
    forbidden_words: Sequence[str] = (),
    cjk_threshold: int = _CJK_DEFAULT_THRESHOLD,
    cjk_exempt_domains: frozenset[str] = _CJK_EXEMPT_DOMAINS_DEFAULT,
) -> list[str]:
    """Run the per-file gate + cross-product check over one directory.

    Returns a flat list of defect strings (empty = clean).
    """
    if not directory.is_dir():
        return [f"IO not a directory: {directory}"]
    files = sorted(directory.glob("*.md"))
    if not files:
        return [f"IO no .md files under {directory}"]
    domain = _normalize_domain(directory.name)
    defects: list[str] = []
    for f in files:
        for d in gate_file(
            f,
            domain=domain,
            forbidden_words=forbidden_words,
            cjk_threshold=cjk_threshold,
            cjk_exempt_domains=cjk_exempt_domains,
        ):
            defects.append(f"{f.name}: {d}")
    defects.extend(find_cross_product_conflicts(files))
    return defects


def parse_domain_blocklist(spec: str) -> dict[str, list[str]]:
    """Parse "--domain-blocklist domain:word,word;domain2:word" -> map."""
    out: dict[str, list[str]] = {}
    if not spec:
        return out
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        dom, words = part.split(":", 1)
        out[dom.strip().lower()] = [w.strip() for w in words.split(",") if w.strip()]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directories",
        nargs="+",
        type=Path,
        help="one or more product directories containing *.md deliverables",
    )
    parser.add_argument(
        "--forbidden-words",
        default="",
        help="comma-separated domain-forbidden words (applies to all dirs, F4)",
    )
    parser.add_argument(
        "--domain-blocklist",
        default="",
        help="per-domain forbidden words: 'domain:word,word;other:word' (F4)",
    )
    parser.add_argument(
        "--cjk-threshold",
        type=int,
        default=_CJK_DEFAULT_THRESHOLD,
        help=f"CJK residue char threshold (default {_CJK_DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--cjk-exempt-domains",
        default=",".join(sorted(_CJK_EXEMPT_DOMAINS_DEFAULT)),
        help="comma-separated bilingual-by-design domains (default *-learning)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON summary on stdout",
    )
    args = parser.parse_args(argv)

    exempt = frozenset(
        d.strip().lower()
        for d in args.cjk_exempt_domains.split(",")
        if d.strip()
    )
    forbidden = [w.strip() for w in args.forbidden_words.split(",") if w.strip()]
    blocklist = parse_domain_blocklist(args.domain_blocklist)

    all_defects: list[str] = []
    for directory in args.directories:
        dom = _normalize_domain(directory.name)
        dom_words = forbidden + blocklist.get(dom, [])
        all_defects.extend(
            gate_directory(
                directory,
                forbidden_words=dom_words,
                cjk_threshold=args.cjk_threshold,
                cjk_exempt_domains=exempt,
            )
        )

    # IO-class defects ("IO not a directory" / "IO no .md files") mean the
    # gate could not run on a target at all — a usage error, not a product
    # defect (exit 2).  When real defects coexist they dominate (exit 1).
    io_defects = [d for d in all_defects if d.startswith("IO ")]
    real_defects = [d for d in all_defects if not d.startswith("IO ")]

    # Aggregate per-file defect counts for the summary line.
    per_file: dict[str, int] = {}
    for d in all_defects:
        fname = d.split(":", 1)[0]
        per_file[fname] = per_file.get(fname, 0) + 1

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "exit_code": 0 if not all_defects else 1,
                    "defects": all_defects,
                    "files_with_defects": sorted(per_file),
                },
                indent=2,
            )
        )
        return 0 if not all_defects else (2 if real_defects == [] else 1)

    if io_defects and not real_defects:
        print("QUALITY GATE USAGE ERROR:")
        for d in io_defects:
            print(f"  - {d}")
        return 2
    if not all_defects:
        print(f"QUALITY GATE PASSED ({len(args.directories)} dir(s), no defects)")
        return 0

    print("QUALITY GATE FAILED:")
    for d in all_defects:
        print(f"  - {d}")
    print(f"  ({len(all_defects)} defects across {len(per_file)} file(s))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
