"""Output generation — digests, reports, and KB export.

Provides the ``export_kb`` function for exporting knowledge base data
in Markdown (tar.gz), JSON, or SQLite format.

Usage::

    from autoinfo.output import export_kb

    # Export a single domain as JSON
    result = export_kb(domain="medical-research", format="json")

    # Export the entire KB as Markdown tar.gz
    result = export_kb(format="markdown")
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import html
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tarfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import format_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Final, Literal, cast
from urllib.parse import urlsplit

import yaml

if TYPE_CHECKING:
    from autoinfo.config import SourceConfig  # noqa: F811
    from autoinfo.llm import LLMExtractor
    from autoinfo.quality import QualityResult

import httpx
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, TemplateNotFound

from autoinfo.config import Config, get_config_path, load_config
from autoinfo.kb import KBStore, PromotionRejected, SQLiteIndex
from autoinfo.llm import call_with_fallback

logger = logging.getLogger(__name__)

# Demo-domain seed directory (issue #319): the same seed ``init`` reads when
# scaffolding a domain.  Used as the exclude_keywords fallback so existing
# projects whose runtime config predates the field still filter noise.
_DEMO_DOMAINS_DIR = Path(__file__).resolve().parent.parent / "data" / "domains"

# Generic theme labels that never name a meaningful report section (issue #9).
# They come from auto-discovery keyword fragments (e.g. ``new``, ``year``,
# ``user``, ``market``) whose normalized form is a bare generic word.  A group
# whose normalized theme lands here is dropped in ``_merge_theme_groups`` and
# its entries reassigned to the nearest surviving group or "Additional Topics".
_GENERIC_THEME_LABELS: Final[frozenset[str]] = frozenset({
    "new", "year", "the year", "user", "activity", "growth",
    "apps", "market", "update", "summary",
})

# Theme synonym map (issue #9): canonical spelling -> the key every variant
# normalizes to.  Applied in ``_normalize_theme_text`` BEFORE the near-dup
# pass so synonym variants merge in the exact-name pass (e.g. ``Year`` and
# ``The Year`` collapse onto one group before the blocklist runs).
_THEME_SYNONYMS: Final[dict[str, str]] = {"year": "the year"}

# Structural catch-all themes the report/product templates render as their
# own sections.  Exempt from the generic-label blocklist (they are not
# keyword-derived noise) and excluded when deciding whether a keyword
# grouping found any meaningful theme at all.
_STRUCTURAL_THEME_LABELS: Final[frozenset[str]] = frozenset({
    "general", "additional topics",
})


def _fire_agent_notification(event: str, output: Any, product_id: str) -> None:
    """Fire a fire-and-forget agent callback for a just-generated product.

    The event is persisted to the durable outbox (SQLite) BEFORE any
    delivery attempt; a background worker performs the HTTP POST. This
    hook NEVER raises — generation success is inviolable. Failures are
    logged and counted via the ``delivery_failures_total`` metric.
    """
    try:
        from autoinfo.agent_callback import enqueue_agent_notification

        enqueue_agent_notification(
            event=event,
            payload=output,
            trace_id=str(uuid.uuid4()),
            product_id=product_id,
        )
    except Exception:
        logger.warning(
            "Failed to enqueue agent notification for event %r (product %s)",
            event, product_id, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Agent-native JSON-LD constants (single source of truth)
# ---------------------------------------------------------------------------
# One @context/@type pair per agent-native payload kind, defined once so the
# identifiers cannot drift between producers. Producers MUST spread the
# constant FIRST (before "uuid") to keep @context/@type/uuid as the leading
# keys — that key order is part of the serialized output contract.

_JSONLD_DIGEST: dict[str, str] = {
    "@context": "https://autoinfo.ai/schemas/knowledge-digest-v1",
    "@type": "KnowledgeDigest",
}

# Optional per-product analysis keys of the digest JSON-LD shape (spec §2.4,
# todo 7; surfaced into the agent payload by _render_agent_json, todo 22;
# pinned by docs/schemas/knowledge-digest-v1.json, todo 23). Emitted on
# product paths ONLY (premium-briefing / enterprise-briefing /
# magazine-digest) when the synthesis carries them; ABSENT from default
# digest/report agent output (round-trip contract — see
# TestAgentProductFields.test_default_*_agent_output_unchanged). Deliberately
# NOT runtime values of _JSONLD_DIGEST: this dict is spread verbatim into
# every agent payload, so carrying the keys here would leak them into default
# output and break the serialized contract. Shapes:
#   implications:    list[str]            # "so-what" per key_findings entry
#   risks:           list[dict[str, str]] # title / likelihood / impact / mitigation
#   action_required: list[str]            # action per key_findings entry
#   key_metrics:     list[dict[str, str]] # metric / value / source (enterprise)

# Per-product analysis fields shared by the agent JSON-LD payload
# (_render_agent_json) and the KB metadata persistence (_persist_product_analysis_to_kb).
_PRODUCT_ANALYSIS_FIELDS: tuple[str, ...] = (
    "implications",
    "risks",
    "action_required",
    "key_metrics",
)

_JSONLD_TUTORIAL: dict[str, str] = {
    "@context": "https://autoinfo.ai/schemas/knowledge-tutorial-v1",
    "@type": "KnowledgeTutorial",
}

_JSONLD_PRESENTATION: dict[str, str] = {
    "@context": "https://autoinfo.ai/schemas/knowledge-presentation-v1",
    "@type": "KnowledgePresentation",
}

_JSONLD_BASE_EXPORT: dict[str, str] = {
    "@context": "https://autoinfo.ai/schemas/knowledge-base-export-v1",
    "@type": "KnowledgeBaseExport",
}


# ---------------------------------------------------------------------------
# Delivery gate output container
# ---------------------------------------------------------------------------


@dataclass
class DeliveryOutput:
    """Output from a product generation run, extended with delivery gate results.

    When :func:`generate_digest` or :func:`generate_report` is called with
    *delivery_gate_configs* explicitly provided, the function returns a
    :class:`DeliveryOutput` instead of a plain ``str``.  Existing callers
    that do not pass *delivery_gate_configs* continue to receive a plain
    ``str`` (backward compatible).
    """

    output: str
    gate_results: dict[str, "QualityResult"] = field(default_factory=dict)
    delivery_blocked: bool = False
    delivery_format: str = ""
    warnings: list[str] = field(default_factory=list)


class StaleSourceError(ValueError):
    """Raised when freshness filtering removes all candidate entries for a
    digest/report, so the product would be an empty shell.

    Subclasses :class:`ValueError` so the CLI and MCP layers (which catch
    ``ValueError`` around ``generate_digest`` / ``generate_report``) surface a
    clean, actionable error instead of silently producing a product with no
    content (backup issue #52).
    """


# ---------------------------------------------------------------------------
# Language-teaching topic guard (backup #63)
# ---------------------------------------------------------------------------
# A language-learning domain's entries must not include content that teaches
# a language OTHER than the domain's ``default_language`` — e.g. a Spanish
# grammar post on blog.duolingo.com leaking into english-learning (the list
# is about the topic, so the language filter cannot catch it).  This is a
# deterministic title/summary heuristic that drops entries whose text
# combines a non-target language name with a language-teaching signal.

_LANG_TEACHING_SIGNALS: tuple[str, ...] = (
    " mean ",
    "means",
    "meaning",
    "grammar",
    "vocabulary",
    "conjugation",
    "pronunciation",
    "how to say",
    "how do you say",
)


_LANGUAGE_NAMES: frozenset[str] = frozenset(
    {
        "arabic",
        "chinese",
        "czech",
        "danish",
        "dutch",
        "english",
        "finnish",
        "french",
        "german",
        "greek",
        "hebrew",
        "hindi",
        "hungarian",
        "indonesian",
        "italian",
        "japanese",
        "korean",
        "mandarin",
        "norwegian",
        "polish",
        "portuguese",
        "russian",
        "spanish",
        "swedish",
        "turkish",
        "ukrainian",
        "vietnamese",
    }
)

# ISO-639-1 code -> human-readable language name, used to phrase the
# language-learning prompt ("for Russian" instead of "for ru").
_LANG_DISPLAY_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "zh": "Chinese",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "fi": "Finnish",
    "fr": "French",
    "de": "German",
    "el": "Greek",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "es": "Spanish",
    "sv": "Swedish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
}


def _lang_display_name(lang: str) -> str:
    """Return a human-readable language name for an ISO code/alias."""
    code = _normalize_lang(lang)
    return _LANG_DISPLAY_NAMES.get(code, lang or "the target language")


def _filter_foreign_language_teaching_entries(
    entries: list[dict[str, Any]],
    target_language: str,
) -> list[dict[str, Any]]:
    """Drop language-learning entries that teach a language other than
    *target_language* (backup issue #63).

    Deterministic: an entry is dropped only when its title+summary contains a
    non-target language name **and** a teaching signal phrase
    (``means`` / ``grammar`` / ``vocabulary`` / …).  Plain news that merely
    names a country or language is never dropped; non-language-learning
    domains (``target_language == ""``) pass through unchanged.
    """
    if not target_language:
        return entries
    target_norm = target_language.strip().lower()
    # Language names that are NOT the target (teaching *another* language).
    foreign_names = {name for name in _LANGUAGE_NAMES if name != target_norm}
    if not foreign_names:
        return entries

    kept: list[dict[str, Any]] = []
    dropped = 0
    for entry in entries:
        haystack = " ".join(
            filter(
                None,
                (
                    str(entry.get("title") or ""),
                    str(entry.get("summary") or ""),
                ),
            )
        ).lower()
        if not haystack:
            kept.append(entry)
            continue
        hit = False
        for name in foreign_names:
            if name not in haystack:
                continue
            for signal in _LANG_TEACHING_SIGNALS:
                if signal in haystack:
                    hit = True
                    break
            if hit:
                break
        if hit:
            dropped += 1
            logger.info(
                "Excluded foreign-language teaching entry from %s tutorial "
                "(teaches '%s' ≠ default_language)",
                target_language,
                next((n for n in foreign_names if n in haystack), "?"),
            )
        else:
            kept.append(entry)
    if dropped:
        logger.info(
            "Excluded %d foreign-language teaching entries (target '%s')",
            dropped,
            target_language,
        )
    return kept


# ---------------------------------------------------------------------------
# Content-ready notification helper
# ---------------------------------------------------------------------------


def _try_notify_content_ready(
    user_id: str,
    product_type: str,
    title: str,
) -> None:
    """Call :func:`autoinfo.notifications.notify_content_ready` with error suppression.

    Any failure is logged at DEBUG level — notification errors must never
    prevent the generated product from being returned to the caller.
    """
    try:
        from autoinfo.notifications import notify_content_ready  # noqa: PLC0415

        notify_content_ready(
            user_id=user_id,
            product_type=product_type,
            title=title,
        )
    except Exception:
        logger.debug(
            "Content-ready notification failed for user '%s' (%s)",
            user_id,
            product_type,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Product entry filtering (issue #298 — 3-layer guardrail, layer 1)
# ---------------------------------------------------------------------------
# Test/placeholder markers that identify non-production KB entries.  A product
# must never ship entries that are empty shells, test fixtures, or placeholder
# content — they pollute the LLM synthesis input AND the rendered body.

_TEST_TITLE_MARKERS: frozenset[str] = frozenset({
    "Get Test", "Entry A", "Entry B", "Entry C", "QA Article", "Test Entry",
    "Test", "test",
})
_TEST_TITLE_RE = re.compile(r"parity-t\d+|test\s+\d{4}-\d{2}-\d{2}", re.IGNORECASE)
_TEST_TITLE_SUBSTRINGS: tuple[str, ...] = (
    "validation import", "spotcheck", "test entry", "lorem ipsum",
    "placeholder", "test content",
)
_TEST_URL_MARKERS: tuple[str, ...] = (
    "example.org", "localhost", "127.0.0.1", ".local",
)
_TEST_SOURCE_PLATFORMS: frozenset[str] = frozenset({
    "fixture", "mock", "stub", "sample",
    "test-fixture", "test_fixture", "test-source", "test_source",
})

_NO_CONTENT_SUMMARY_RE: re.Pattern[str] = re.compile(
    r"^\s*(no\s+content\s+provided(?:\s+to\s+summarize)?\.?"
    r"|not\s+available\.?|n/?a\.?"
    r"|no\s+summary(?:\s+available)?\.?|no\s+content\.?)\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Platform display-name mapping (issue #302 — ③)
# ---------------------------------------------------------------------------

_PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    "pubmed": "PubMed",
    "semantic_scholar": "Semantic Scholar",
    "openalex": "OpenAlex",
    "sec_edgar": "SEC EDGAR",
    "rss": "RSS",
    "web": "Web",
    "api": "API",
    "arxiv": "arXiv",
    "dblp": "DBLP",
    "nyt": "NYT",
    "hackernews": "HackerNews",
    "reddit": "Reddit",
    "youtube": "YouTube",
    "bilibili": "Bilibili",
    "spotify": "Spotify",
    "apple_podcasts": "Apple Podcasts",
    "gdelt": "GDELT",
    "uspto": "USPTO",
    "crossref": "CrossRef",
    "unpaywall": "Unpaywall",
    "core": "CORE",
    "ssrn": "SSRN",
    "akshare": "AKShare",
    "edgar": "EDGAR",
}


def _platform_name(value: Any) -> str:
    """Map internal source_platform id to a display name (issue #302 — ③).

    Known ids are mapped to human-readable names; unknown ids fall back to
    the raw id.  Empty/None values return an em-dash.
    """
    if not value:
        return "\u2014"
    s = str(value).strip()
    if not s:
        return "\u2014"
    return _PLATFORM_DISPLAY_NAMES.get(s.lower(), s)


# ---------------------------------------------------------------------------
# LLM leak detection (issue #302 — ①)
# ---------------------------------------------------------------------------

_LEAK_FENCED_JSON_RE: re.Pattern[str] = re.compile(
    r"```json\s*\n", re.IGNORECASE
)
_LEAK_JSON_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^\s*\{\s*\"(?:title|entries|@type|digest_type)\"\s*:", re.IGNORECASE
)
_LEAK_PROMPT_ECHO_RE: re.Pattern[str] = re.compile(
    r"(?:^|\n)\s*(?:You are a |As an AI |You are an AI |System:\s|User:\s|Assistant:\s)",
    re.IGNORECASE,
)

# External LLM-library error text leaking into a product (issue #328):
# ANSI color escapes plus litellm / BerriAI markers.  Under high concurrency a
# failed LLM call can leave a raw error block (e.g. "Give Feedback / Get Help:
# https://github.com/BerriAI/litellm/issues/new\nLiteLLM.Info: If you need to
# debug this error, use `litellm._turn_on_debug()'") prepended to the rendered
# output, pushing the real title down.  The #294 guard never sniffed for this.
_LEAK_ERROR_TEXT_RE: re.Pattern[str] = re.compile(
    r"(?:\x1b\[[0-9;]*m|"
    r"Give Feedback / Get Help|"
    r"BerriAI|"
    r"LiteLLM\.Info|"
    r"litellm\._turn_on_debug|"
    r"litellm\.exceptions\.|"
    r"^Traceback \(most recent call last\):)",
    re.IGNORECASE | re.MULTILINE,
)


def _contains_raw_llm_leak(text: str) -> bool:
    """Heuristic check for raw LLM output leaking into a product (issue #302 — ①).

    Returns True when *text* contains fenced JSON blocks, raw JSON object
    prefixes, prompt-echo patterns, or external LLM-library error text
    (litellm/BerriAI/ANSI — issue #328) that indicate unreconstructed LLM
    output.  This is a defensive flag, not a hard block — the caller
    decides whether to warn or block.
    """
    if _LEAK_FENCED_JSON_RE.search(text):
        return True
    if _LEAK_JSON_PREFIX_RE.search(text):
        return True
    if _LEAK_PROMPT_ECHO_RE.search(text):
        return True
    if _LEAK_ERROR_TEXT_RE.search(text):
        return True
    return False


def _is_empty_summary(summary: str) -> bool:
    """True when *summary* is blank or a known placeholder string (issue #294).

    Returns True for empty, whitespace-only, or LLM-generated placeholder
    summaries like ``"No content provided to summarize."``.
    """
    stripped = summary.strip()
    if not stripped:
        return True
    return bool(_NO_CONTENT_SUMMARY_RE.match(stripped))


def _is_empty_content(content: Any) -> bool:
    """True when *content* is blank (no real body text).

    Issue #326: the product pipeline enriches real KB entries with their
    ``content`` (body loaded from the KB markdown file).  An entry whose
    ``content`` is missing, empty, or whitespace-only has no extractable body
    and is treated as an empty entry (like issue #294's empty summaries).  A
    non-empty ``content`` signals a real Draft/Wiki entry even when the DB
    ``summary`` column is empty.
    """
    if content is None:
        return True
    stripped = str(content).strip()
    return not stripped


def _enrich_entry_content(entry: dict[str, Any]) -> dict[str, Any]:
    """Load an entry's body ``content`` from its KB markdown file when the
    DB ``summary`` column is empty (issue #326).

    Real Draft/Wiki entries store their extracted text under
    ``## Original Content`` in the KB markdown file, but the SQLite
    ``entries`` table has no ``content`` column and its ``summary`` column
    may be empty.  ``_is_test_entry`` would otherwise drop these real entries
    as "empty-summary" (issue #294) — leaving the column Deep Dive / report
    Sections empty.  This helper reads the file body so ``_is_empty_content``
    sees real content and the entry is kept.

    The file is only read when the summary is empty (the common case has a
    non-empty summary and skips the I/O entirely).
    """
    if not _is_empty_summary(str(entry.get("summary") or "")):
        return entry
    file_path = entry.get("file_path")
    if not file_path or not Path(str(file_path)).is_file():
        return entry
    try:
        raw = Path(str(file_path)).read_text(encoding="utf-8")
    except OSError:
        return entry
    # Prefer the "## Original Content" section; fall back to the raw body.
    marker = "## Original Content"
    if marker in raw:
        body = raw.split(marker, 1)[1].strip()
    else:
        body = raw.strip()
    if body:
        entry["content"] = body
    return entry


def _enrich_product_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich product entries with file ``content`` (issue #326).

    Applied after entry loading and before ``_filter_product_entries`` so real
    Draft/Wiki entries with an empty DB summary but file content survive the
    empty-entry guard.
    """
    return [_enrich_entry_content(dict(e)) if isinstance(e, dict) else e for e in entries]


def _entry_custom_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Parse an entry's ``custom_fields`` (JSON string or dict) into a dict."""
    raw = entry.get("custom_fields")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _is_test_entry(entry: dict[str, Any]) -> bool:
    """True when *entry* carries a test/placeholder marker (issue #298).

    Also returns True for entries with empty/placeholder summary
    (issue #294) — these produce blank cells or "No content provided"
    strings in rendered products.
    """
    title = str(entry.get("title") or "").strip()
    summary = str(entry.get("summary") or "").strip()
    source_url = str(entry.get("source_url") or "").strip()
    source_platform = str(entry.get("source_platform") or "").strip()

    # (a) empty title AND empty summary -> no usable content
    if not title and not summary:
        return True
    # (a2) empty/placeholder summary -> only treated as a test/empty entry
    # when there is no real body content either.  A real Draft/Wiki entry
    # whose body lives in the KB markdown file (loaded into the entry dict's
    # ``content`` field by the product pipeline) but whose DB ``summary``
    # column is empty is meaningful and must NOT be dropped (issue #326).
    # Entries without a ``content`` field (never enriched from a file) keep
    # the #294 behaviour: empty summary -> dropped.
    if _is_empty_summary(summary) and _is_empty_content(entry.get("content")):
        return True
    # (a3) summary contains lorem ipsum -> placeholder text (issue #293)
    if "lorem ipsum" in summary.lower():
        return True
    # (b) URL placeholder markers
    if any(marker in source_url.lower() for marker in _TEST_URL_MARKERS):
        return True
    # (b) title markers
    if title in _TEST_TITLE_MARKERS:
        return True
    if _TEST_TITLE_RE.search(title):
        return True
    title_lower = title.lower()
    if any(sub in title_lower for sub in _TEST_TITLE_SUBSTRINGS):
        return True
    # (c) custom_fields.test / status markers (issue #293)
    cf = _entry_custom_fields(entry)
    if cf.get("test") is True:
        return True
    cf_status = str(cf.get("status") or "").strip().lower()
    if cf_status in ("test", "placeholder", "mock", "sample", "demo"):
        return True
    # (d) known test source platforms
    if source_platform.lower() in _TEST_SOURCE_PLATFORMS:
        return True
    return False


def _filter_product_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop empty / test / placeholder entries from a product's entry list.

    Layer 1 of the 3-layer guardrail (issue #298): the synthesis input AND the
    rendered body must be clean.  Applied by every product generator
    (digest/report/tutorial/presentation) BEFORE synthesis and BEFORE render.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for entry in entries:
        if _is_test_entry(entry):
            dropped += 1
            continue
        kept.append(entry)
    if dropped:
        logger.info("Filtered %d test/empty entries from product input", dropped)
    return kept


# ---------------------------------------------------------------------------
# Near-duplicate convergence (backup issue #69)
# ---------------------------------------------------------------------------
# Cross-language / cross-source same-event duplicates (e.g. "Dolly Parton
# has died" vs "Mort de la star américaine Dolly Parton") are invisible to
# the char-level G2Dedup similarity gate, so the same event can be ingested
# many times across domains/languages and flood every product that consumes
# the KB.  This product-layer convergence clusters entries that share a
# distinctive proper-noun signature within a short time window and keeps ONE
# representative per cluster — non-destructive (entries stay in the KB; only
# the product picks a representative) and deterministic (no LLM).
# ---------------------------------------------------------------------------

# Common geopolitical/institutional phrases whose shared presence is NOT a
# same-event signal (e.g. two unrelated "New York"-mentioning stories).
# People names ("Dolly Parton", "Donald Trump") are intentionally absent —
# a shared person name within a short window IS the event signal.
_PROPER_NOUN_STOPLIST: frozenset[str] = frozenset({
    "New York",
    "United States",
    "White House",
    "European Union",
    "Silicon Valley",
    "Wall Street",
    "Los Angeles",
    "Hong Kong",
    "San Francisco",
    "South Korea",
    "North Korea",
    "Middle East",
    "United Nations",
    "World Health",
    "Prime Minister",
    "Federal Reserve",
    "New York City",
    "World War",
    "International Space",
    "Golden Globe",
    "Grammy Award",
})

# ≥2-word capitalized sequence — language-agnostic proper-noun extraction
# ("Dolly Parton", "Donald Trump", "Le Figaro").  Single capitalized words
# are too ambiguous to be an event signature on their own.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z0-9'\-]+(?:\s+[A-Z][a-zA-Z0-9'\-]+)+\b")

# Time window (days) inside which a shared proper noun is treated as the
# same event.  Deaths/crises/launches cluster within days; a month apart is
# a different story.
_NEAR_DUP_WINDOW_DAYS = 3

# G2Dedup's fuzzy-title threshold (quality.py): title similarity >=0.85 is
# flagged duplicate at ingest.  The stored dedup_status fast-path below only
# trusts the flag when the two titles actually meet this bar — a bare
# dedup_status alone is not a same-event signal (a re-collection can flag
# every entry, and multi-angle reports of one event may all carry it).
_NEAR_DUP_CHAR_SIM_MAX = 0.85


def _extract_proper_nouns(title: str) -> list[str]:
    """Return distinctive ≥2-word proper-noun phrases from *title*.

    Deterministic, language-agnostic: a capitalized multi-word sequence
    ("Dolly Parton") survives translation/rewriting, unlike char-level
    similarity.  Phrases equal to — or containing — a stoplisted
    geopolitical/institutional phrase are dropped ("New York Stock
    Exchange" contains "New York").  Results are deduplicated preserving
    order.
    """
    if not title:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _PROPER_NOUN_RE.findall(title):
        if match in seen:
            continue
        seen.add(match)
        if any(stop in match for stop in _PROPER_NOUN_STOPLIST):
            continue
        found.append(match)
    return found


# Cross-language EVENT-WORD lexicon for the death/obituary news class
# (backup issue #73).  Multi-angle reports of the SAME event visibly rewrite
# the headline ("Mort de Dolly Parton", "Dolly Parton ... est morte à l'âge de
# 80 ans"), so title character-similarity is low, they never carry a second
# shared noun, and a bare dedup flag (G2 fuzzy-title) cannot see them — yet
# they ARE the same event.  These canonical headline/predicate forms per
# language give those pairs a deterministic secondary signal so they converge.
# Forms are deliberately the FULL headline constructions (lead "mort de",
# predicate "est morte", formal obituary "décédé(e)") rather than bare
# participles/adjectives: "morte"/"dead" alone appear appositionally in
# tribute/feature titles ("... l'icône de la country morte à 80 ans") that must
# NOT dissolve into the obituary cluster.
_DEATH_EVENT_WORDS: dict[str, tuple[str, ...]] = {
    "en": (
        "died", "has died", "dies", "death of", "death", "deaths", "dead",
        "passed away", "passes away", "obituary",
    ),
    "fr": (
        "mort de", "est mort", "est morte", "morte à l'âge", "mort à l'âge",
        "décédé", "décédée", "décès", "est décédé", "est décédée",
        "s'éteint", "s'est éteint", "s'est éteinte",
    ),
    "es": (
        "muere", "murió", "ha muerto", "muerte de", "fallece", "falleció",
        "fallecimiento de", "fallecimiento",
    ),
    "pt": (
        "morre", "morreu", "morte de", "falece", "faleceu",
        "falecimento de",
    ),
    "it": (
        "è morta", "è morto", "morte di", "muore", "deceduto", "deceduta",
        "decesso",
    ),
    "de": (
        "gestorben", "tod von", "stirbt", "verstorben", "todesfall",
    ),
    "zh": ("逝世", "去世", "病逝"),
}

# Union of every language's forms — fallback lexicon for entries whose
# language tag is unknown/empty (best-effort; still canonical forms only).
_ALL_DEATH_EVENT_WORDS: tuple[str, ...] = tuple(
    word for words in _DEATH_EVENT_WORDS.values() for word in words
)


def _has_death_event_word(title: str, language: str | None) -> bool:
    """True when *title* carries a canonical death/obituary event word.

    Language-keyed via the entry's ``language`` (normalised with
    :func:`_normalize_lang`); an unknown/empty tag scans the union of every
    lexicon language (best-effort).  Co-occurrence with the shared proper noun
    in the same title is enforced by the caller.
    """
    if not title:
        return False
    lowered = title.lower()
    words = _DEATH_EVENT_WORDS.get(_normalize_lang(language or ""))
    if words is None:
        words = _ALL_DEATH_EVENT_WORDS
    return any(word in lowered for word in words)


def _converge_near_duplicates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse same-event near-duplicates to one representative per cluster.

    Cluster rule: two entries belong to the same event when they share a
    distinctive proper-noun phrase (≥2-word capitalized sequence) within
    :data:`_NEAR_DUP_WINDOW_DAYS` days AND carry at least one secondary
    signal — an already-stored ``dedup_status == "duplicate"`` **corroborated
    by ≥0.85 title similarity** (G2Dedup's fuzzy-title threshold — a bare
    dedup flag alone is not a same-event signal), a second
    shared proper noun, or (backup issue #73) a canonical death/obituary event
    word in BOTH titles, each co-occurring with the shared proper noun in its
    own title.  Identical
    ``source_url`` is never merged (syndication is intentional).

    The representative is the highest ``relevance_score`` entry of the
    cluster (tie-break: earliest ``collected_at``, then ``entry_id``) — the
    order in which candidates are promoted to representatives.  Returns a
    NEW list; input dicts are never mutated and never dropped from the KB.
    """
    if not entries:
        return []
    nouns_by_key: dict[int, set[str]] = {}
    for idx, entry in enumerate(entries):
        nouns_by_key[idx] = set(_extract_proper_nouns(str(entry.get("title") or "")))

    def _sort_key(entry: dict[str, Any]) -> tuple[float, str, str]:
        relevance = float(entry.get("relevance_score") or 0.0)
        collected = str(entry.get("collected_at") or "")
        eid = str(entry.get("entry_id") or "")
        return (-relevance, collected, eid)

    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    def _within_window(rep: dict[str, Any], entry: dict[str, Any]) -> bool:
        rep_dt = _parse_dt(rep.get("collected_at"))
        entry_dt = _parse_dt(entry.get("collected_at"))
        if rep_dt is None or entry_dt is None:
            # Unparseable/missing dates: skip the window clause (conservative —
            # allow merge on the other signals).
            return True
        return abs((entry_dt - rep_dt).days) <= _NEAR_DUP_WINDOW_DAYS

    def _shares_noun(rep_idx: int, entry_idx: int) -> bool:
        rep_nouns = nouns_by_key.get(rep_idx, set())
        entry_nouns = nouns_by_key.get(entry_idx, set())
        if rep_nouns & entry_nouns:
            return True
        # Phrase subsumption: "Muere Dolly Parton" contains "Dolly Parton"
        # as a whole-word substring — same signature, different leading verb
        # (title-initial capitalized verb in Romance languages).
        for a in rep_nouns:
            for b in entry_nouns:
                if a in b or b in a:
                    return True
        return False

    def _death_event_signal(rep: dict[str, Any], entry: dict[str, Any]) -> bool:
        """Death/obituary event-word co-occurrence signal (backup issue #73).

        Two reworded reports of the SAME death event each carry a canonical
        death event word in their own title, in the language of that title,
        and each event word co-occurs with a shared proper noun in the same
        title.  Requiring the word in BOTH titles — not either — keeps a
        tribute/feature title that merely mentions the deceased out of the
        obituary cluster.
        """
        rep_title = str(rep.get("title") or "").strip()
        entry_title = str(entry.get("title") or "").strip()
        if not rep_title or not entry_title:
            return False
        rep_idx = next(
            (i for i, e in enumerate(entries) if e is rep), -1
        )
        entry_idx = next(
            (i for i, e in enumerate(entries) if e is entry), -1
        )
        if rep_idx < 0 or entry_idx < 0:
            return False
        rep_nouns = nouns_by_key.get(rep_idx, set())
        entry_nouns = nouns_by_key.get(entry_idx, set())
        shared: set[str] = set(rep_nouns) & set(entry_nouns)
        for a in rep_nouns:
            for b in entry_nouns:
                if a in b:
                    shared.add(a)
                if b in a:
                    shared.add(b)
        if not shared:
            return False
        # The event word must co-occur with the shared proper noun in the
        # same title — satisfied when a shared phrase is a substring of both.
        if not any(noun in rep_title for noun in shared):
            return False
        if not any(noun in entry_title for noun in shared):
            return False
        return (
            _has_death_event_word(rep_title, rep.get("language"))
            and _has_death_event_word(entry_title, entry.get("language"))
        )

    def _secondary_signal(rep: dict[str, Any], entry: dict[str, Any]) -> bool:
        a = (str(rep.get("title") or "")).lower()
        b = (str(entry.get("title") or "")).lower()
        # The stored dedup_status fast-path is ONLY trustworthy when it
        # corroborates its own G2 premise: dedup_status="duplicate" is set by
        # G2Dedup for URL/PMID/DOI/fuzzy-title matches, and the fuzzy-title
        # verdict fires at >=0.85 title similarity (quality.py G2Dedup).  A
        # bare dedup_status alone is NOT a same-event signal — a re-collection
        # can flag every entry duplicate, and multi-angle reports of one event
        # (obituary + tribute + song-list) may all carry the flag while being
        # distinct stories.  Requiring >=0.85 similarity confines the fast-path
        # to true near-identical duplicates and forces multi-angle merges
        # through the noun/event-word signals instead (backup issues #69/#73).
        if (
            a
            and b
            and str(entry.get("dedup_status") or "").lower() == "duplicate"
            and SequenceMatcher(None, a, b).ratio() >= _NEAR_DUP_CHAR_SIM_MAX
        ):
            return True
        rep_idx = next(
            (i for i, e in enumerate(entries) if e is rep), -1
        )
        entry_idx = next(
            (i for i, e in enumerate(entries) if e is entry), -1
        )
        if rep_idx >= 0 and entry_idx >= 0:
            shared = nouns_by_key.get(rep_idx, set()) & nouns_by_key.get(entry_idx, set())
            if len(shared) >= 2:
                return True
        return _death_event_signal(rep, entry)

    reps: list[dict[str, Any]] = []
    dropped = 0
    for entry in sorted(entries, key=_sort_key):
        entry_idx = entries.index(entry)
        merged = False
        for rep in reps:
            rep_idx = entries.index(rep)
            if str(rep.get("source_url") or "") == str(entry.get("source_url") or ""):
                continue  # syndication — never merge identical URLs
            if not _shares_noun(rep_idx, entry_idx):
                continue
            if not _within_window(rep, entry):
                continue
            if not _secondary_signal(rep, entry):
                continue
            merged = True
            dropped += 1
            logger.info(
                "Converged near-duplicate entry '%s' into representative '%s'",
                entry.get("title", "")[:60],
                rep.get("title", "")[:60],
            )
            break
        if not merged:
            reps.append(entry)
    if dropped:
        logger.info("Converged %d near-duplicate entries in product input", dropped)
    return reps


_LANG_ALIASES: dict[str, str] = {
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "zh-tw": "zh",
    "zh-hk": "zh",
    "cn": "zh",
    "中文": "zh",
    "chinese": "zh",
    "en-us": "en",
    "en-gb": "en",
    "eng": "en",
    "english": "en",
}


def _normalize_lang(value: str) -> str:
    """Normalize an ISO-639/alias language tag to the canonical 2-letter code.

    ``zh_CN``, ``en-US``, ``中文``, ``chinese`` → ``zh`` / ``en``.  Unknown
    values pass through lowercased.
    """
    v = (value or "").strip().replace("_", "-").replace(" ", "-").lower()
    if not v:
        return ""
    return _LANG_ALIASES.get(v, v.split("-")[0])


def _filter_entries_by_language(
    entries: list[dict[str, Any]], language: str
) -> list[dict[str, Any]]:
    """Keep only entries whose ``language`` field matches *language* (issue #309).

    *language* is normalized via :func:`_normalize_lang`; matching is done on
    the canonical code so ``"zh"`` matches ``zh_CN``/``中文`` and ``"en"``
    matches ``en-US``/``english``.  Entries with an empty/unknown language are
    dropped when a language filter is active (an unfiltered product should not
    silently mix languages).  Returns the input unchanged when *language* is
    empty.
    """
    target = _normalize_lang(language)
    if not target:
        return entries
    kept: list[dict[str, Any]] = []
    dropped = 0
    for entry in entries:
        entry_lang = _normalize_lang(str(entry.get("language") or ""))
        if entry_lang == target:
            kept.append(entry)
        else:
            dropped += 1
    if dropped:
        logger.info(
            "Excluded %d entries from product input for language='%s'",
            dropped, target,
        )
    return kept


# Issue #53: a stale seed/config ``default_language`` that mismatches the real
# data distribution (e.g. a ``zh`` seed on an English domain) can collapse a
# healthy product input to an empty/near-empty shell.  ``_LANGUAGE_COLLAPSE_*``
# bound the anti-collapse safety net in
# :func:`_filter_entries_by_language_product_safe`: input of at least
# ``_LANGUAGE_COLLAPSE_MIN_INPUT`` entries that filters down to at most
# ``_LANGUAGE_COLLAPSE_MAX_KEPT`` is treated as a stale-language collapse.
_LANGUAGE_COLLAPSE_MIN_INPUT = 3
_LANGUAGE_COLLAPSE_MAX_KEPT = 1


def _filter_entries_by_language_product_safe(
    entries: list[dict[str, Any]], language: str
) -> tuple[list[dict[str, Any]], bool]:
    """Language filter with an anti-collapse safety net (issue #53).

    Applying *language* at the product level must never silently wipe out a
    domain's primary corpus: when the plain filter would keep at most
    ``_LANGUAGE_COLLAPSE_MAX_KEPT`` entries out of an input of
    ``>= _LANGUAGE_COLLAPSE_MIN_INPUT`` — a resolved (seed or configured)
    language that no longer matches the domain's actual data distribution —
    fall back to the FULL unfiltered input and log a warning instead of
    shipping an empty/near-empty product.

    Returns ``(entries, collapsed)``: ``collapsed`` True means *entries* is the
    unfiltered input (the safety net already fired and logged); False means
    *entries* is the plain filtered result.  Inputs smaller than
    ``_LANGUAGE_COLLAPSE_MIN_INPUT`` are too small to judge and pass through
    the plain filter untouched (keeps the pinned #8 ai-commercial two-entry
    enforcement intact).
    """
    filtered = _filter_entries_by_language(entries, language)
    if (
        len(entries) >= _LANGUAGE_COLLAPSE_MIN_INPUT
        and len(filtered) <= _LANGUAGE_COLLAPSE_MAX_KEPT
    ):
        logger.warning(
            "Language filter '%s' would reduce %d inputs to %d — treating the "
            "resolved language as stale and falling back to unfiltered input "
            "(issue #53)",
            language, len(entries), len(filtered),
        )
        return entries, True
    return filtered, False


def _resolve_effective_language(
    language: str, domain: str, *, cross_domain: bool = False
) -> str:
    """Resolve the effective language for a product (issue #317).

    Precedence:
    1. An explicit *language* param always wins.
    2. Otherwise, for a single-domain product, fall back to the domain's
       configured ``default_language`` (so mixed-language domains like
       ai-commercial come out single-language without manual params).
    3. Otherwise ``""`` — no filtering (legacy behavior).

    Seed fallback (issue #8): when a project config file EXISTS but its
    domain block carries no ``default_language`` key at all (projects
    initialized before the field existed — ``init`` only propagates it for
    NEW domains), fall back to the demo-domain seed
    ``src/autoinfo/data/domains/<domain>/sources.yaml`` so live surfaces
    come out single-language immediately without a config migration.  An
    explicitly declared (even empty) value always wins — empty means "no
    filtering", backward compatible.  A project with NO config file at all
    stays ``""`` (no filtering) — seeding never engages on a missing config.

    For a cross-domain product (*cross_domain* True) we never silently pick
    one domain's default across multiple domains: an explicit param wins,
    otherwise no filtering.
    """
    if language:
        return language
    if cross_domain:
        return ""
    config_path = get_config_path()
    if config_path is None or not config_path.is_file():
        return ""
    try:
        config = load_config(config_path)
    except Exception:
        return ""
    for d in config.domains:
        if d.name == domain:
            if _config_declares_default_language(config_path, domain):
                return d.default_language or ""
            break
    return _seed_domain_default_language(domain)


def _config_declares_default_language(config_path: Path, domain: str) -> bool:
    """True when the raw config YAML declares a ``default_language`` key for
    *domain* (even an empty value).

    The parsed :class:`DomainConfig` cannot distinguish "key present but
    empty" from "key missing" — both parse to ``""`` — so the raw dict is
    consulted for the seed-fallback decision (issue #8).
    """
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    for d in raw.get("domains", []):
        if d.get("name") == domain:
            return "default_language" in d
    return False


def _seed_domain_default_language(domain: str) -> str:
    """Demo-domain seed fallback for ``default_language`` (issue #8).

    Reads ``src/autoinfo/data/domains/<domain>/sources.yaml`` (the same seed
    ``init`` uses) so existing projects whose runtime config predates the
    field still come out single-language without a config migration.
    Returns ``""`` when the seed file is absent or carries no
    ``default_language``.
    """
    seed_path = _DEMO_DOMAINS_DIR / domain / "sources.yaml"
    if not seed_path.is_file():
        return ""
    try:
        with open(seed_path, encoding="utf-8") as f:
            seed = yaml.safe_load(f) or {}
    except Exception:
        return ""
    return str(seed.get("default_language") or "")


def _get_domain_exclude_keywords(domain: str) -> list[str]:
    """Load the ``exclude_keywords`` list for *domain* from the project config.

    Returns an empty list when the config cannot be loaded or the domain is
    not found — an empty list means "no filtering" (backward compatible).
    Mirrors the config-loading pattern of :func:`_get_domain_source_configs`.

    Seed fallback (issue #319): when the runtime config's domain carries no
    ``exclude_keywords`` key at all (projects initialized before the field
    existed — ``init`` only propagates it for NEW domains), fall back to the
    demo-domain seed ``src/autoinfo/data/domains/<domain>/sources.yaml`` so
    live surfaces filter immediately without a config migration.  An
    explicitly declared (even empty) list always wins — backward compatible
    "no filtering".  The seed file is read once per call (tiny YAML); an
    absent file yields ``[]``.
    """
    config_path = get_config_path()
    if config_path is None or not config_path.is_file():
        return _seed_domain_exclude_keywords(domain)
    try:
        config = load_config(config_path)
    except Exception:
        return _seed_domain_exclude_keywords(domain)
    for d in config.domains:
        if d.name == domain:
            if _config_declares_exclude_keywords(config_path, domain):
                return list(d.exclude_keywords)
            break
    return _seed_domain_exclude_keywords(domain)


def _config_declares_exclude_keywords(config_path: Path, domain: str) -> bool:
    """True when the raw config YAML declares an ``exclude_keywords`` key for
    *domain* (even an empty list).

    The parsed :class:`DomainConfig` cannot distinguish "key present but
    empty" from "key missing" — both parse to ``[]`` — so the raw dict is
    consulted for the seed-fallback decision (issue #319).
    """
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    for d in raw.get("domains", []):
        if d.get("name") == domain:
            return "exclude_keywords" in d
    return False


def _seed_domain_exclude_keywords(domain: str) -> list[str]:
    """Demo-domain seed fallback for ``exclude_keywords`` (issue #319).

    Reads ``src/autoinfo/data/domains/<domain>/sources.yaml`` (the same seed
    ``init`` uses) so existing projects whose runtime config predates the
    field still filter cross-domain noise without a config migration.
    Returns ``[]`` when the seed file is absent or unreadable.
    """
    seed_path = _DEMO_DOMAINS_DIR / domain / "sources.yaml"
    if not seed_path.is_file():
        return []
    try:
        with open(seed_path, encoding="utf-8") as f:
            seed = yaml.safe_load(f) or {}
    except Exception:
        return []
    return list(seed.get("exclude_keywords") or [])


def _entry_matches_exclude_keywords(
    entry: dict[str, Any], keywords: list[str]
) -> bool:
    """Return True when any excluded keyword appears in the entry's content.

    Matching is a deterministic substring check (casefold for latin, CJK-aware)
    over the entry's title + summary + tags.  Tags may arrive as a JSON string
    (SQLite) or a list — the same parsing pattern as ``_build_digest_llm_prompt``.
    """
    if not keywords:
        return False
    title = str(entry.get("title") or "")
    summary = str(entry.get("summary") or "")
    tags_raw = entry.get("tags", "")
    if isinstance(tags_raw, str):
        try:
            tags_list = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags_list = [tags_raw] if tags_raw else []
    elif isinstance(tags_raw, list):
        tags_list = tags_raw
    else:
        tags_list = []
    tags_text = " ".join(str(t) for t in tags_list)
    haystack = f"{title}\n{summary}\n{tags_text}".casefold()
    return any(kw and kw.casefold() in haystack for kw in keywords)


def _filter_entries_by_domain_exclusions(
    entries: list[dict[str, Any]], domain: str
) -> list[dict[str, Any]]:
    """Drop entries matching a per-domain ``exclude_keywords`` blacklist (#319).

    Issue #319: ai-commercial digests contained medical entries (贝达药业,
    EyePoint DURAVYU) that passed the G1-G3 relevance gates.  This is a
    product-generation-layer filter (NOT a gate change): each entry is checked
    against the ``exclude_keywords`` of its OWN domain (entry dicts carry
    ``domain``; falls back to *domain* when absent), so a cross-domain digest
    filters per-entry.  Matching is deterministic — substring on
    title+summary+tags, no LLM involvement.  Returns the input unchanged when
    no domain declares exclusions.
    """
    if not entries:
        return entries
    exclude_by_domain: dict[str, list[str]] = {}
    kept: list[dict[str, Any]] = []
    dropped = 0
    for entry in entries:
        entry_domain = str(entry.get("domain") or domain)
        if entry_domain not in exclude_by_domain:
            exclude_by_domain[entry_domain] = _get_domain_exclude_keywords(
                entry_domain
            )
        keywords = exclude_by_domain[entry_domain]
        if keywords and _entry_matches_exclude_keywords(entry, keywords):
            dropped += 1
            continue
        kept.append(entry)
    if dropped:
        logger.info(
            "Excluded %d entries from product input for domain '%s' via "
            "exclude_keywords (cross-domain noise filter)",
            dropped, domain,
        )
    return kept


class _DeliveryGatesBypass:
    """Sentinel type for explicitly bypassing delivery-gate resolution."""


_DELIVERY_GATES_BYPASS: Final = _DeliveryGatesBypass()


def _resolve_delivery_gate_configs(
    domain: str,
    delivery_gate_configs: dict[str, dict[str, Any]] | _DeliveryGatesBypass | None,
) -> dict[str, dict[str, Any]] | None:
    """Resolve the effective delivery-gate config for *domain*.

    - An explicit dict is used as-is.
    - The ``_DELIVERY_GATES_BYPASS`` sentinel resolves to ``None`` (gates
      bypassed, plain ``str`` output).
    - ``None`` resolves from the project config: the domain's
      ``delivery_gates`` first, falling back to the global
      ``delivery_gates``.  Returns ``None`` when the config carries no
      delivery gates (backward-compatible plain ``str`` output).
    """
    if delivery_gate_configs is _DELIVERY_GATES_BYPASS:
        return None
    if delivery_gate_configs is not None:
        # Both guards passed: not the sentinel, not None -> provably a dict.
        return cast(dict[str, dict[str, Any]], delivery_gate_configs)
    try:
        cfg_path = get_config_path()
        if cfg_path is None:
            return None
        cfg = load_config(cfg_path)
    except Exception:
        return None
    domain_cfg = next((d for d in cfg.domains if d.name == domain), None)
    gates = domain_cfg.delivery_gates if domain_cfg is not None else {}
    if not gates:
        gates = cfg.delivery_gates
    if not gates:
        return None
    return {
        name: {
            "enabled": dgc.enabled,
            "action_on_failure": dgc.action_on_failure,
        }
        for name, dgc in gates.items()
    }


# ---------------------------------------------------------------------------
# D1 section detection on the rendered body (issue #298 — layer 2)
# ---------------------------------------------------------------------------
# Brought in from scripts/validation_delivery.py (do NOT import from scripts):
# D1 completeness must be checked against the RENDERED body, not just the LLM
# synthesis dict — a body that is empty/garbled but whose synthesis dict is
# non-empty must fail D1.

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

_SLIDE_HEADING_RE = re.compile(r"^slide\s*\d+\s*:", re.IGNORECASE)
_ENTRY_HEADING_RE = re.compile(r"^\d+[.)]\s+\S", re.IGNORECASE)
_EMPTY_PLACEHOLDER_RE = re.compile(r"^\s*_no\s+.+_\.?\s*$", re.IGNORECASE)
_LLM_SKELETON_RE = re.compile(
    r"^\s*[-*|]?\s*<[a-z0-9 _\-]+>"
    r"(\s*[-*|]\s*<[a-z0-9 _\-]+>)*\s*$",
    re.IGNORECASE,
)

_PRODUCT_TYPE_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "report": ("key_findings", "summary", "recommendations"),
    "presentation": ("key_findings",),
    "digest": ("summary",),
    "tutorial": ("key_findings", "recommendations"),
    "column": ("key_findings",),
    "magazine": ("key_findings",),
    "enterprise_briefing": ("summary",),
    "premium_briefing": ("summary",),
    "magazine_digest": ("summary",),
}

_D1_NON_REQUIRED_MARKER = "present"


def _is_empty_placeholder(content: str) -> bool:
    """True when *content* is an empty-state placeholder or LLM skeleton echo."""
    stripped = content.strip()
    if not stripped:
        return False
    return bool(_EMPTY_PLACEHOLDER_RE.match(stripped) or _LLM_SKELETON_RE.match(stripped))


_SKELETON_TOKEN_RE = re.compile(r"<[a-z][a-z0-9 _\-]+>", re.IGNORECASE)


def _clean_skeleton_placeholders(text: str) -> str:
    """Strip LLM skeleton placeholders (``<finding 1>``, ``<metric>``, etc.)
    that the model echoed verbatim from the prompt template.

    Returns the cleaned text with placeholder tokens removed.  Lines that
    become empty after stripping are removed.  Table rows that become
    all-pipes are removed.
    """
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        new_line = _SKELETON_TOKEN_RE.sub("", line)
        # Collapse runs of whitespace left by removal
        new_line = re.sub(r"  +", " ", new_line).strip()
        # Remove empty table rows (e.g. "| | | |" → empty)
        if re.match(r"^[\s|]*$", new_line):
            continue
        # Remove empty list items (e.g. "- " after stripping)
        if re.match(r"^[-*]\s*$", new_line):
            continue
        cleaned.append(new_line)
    return "\n".join(cleaned)


def _sections_from_headings(text: str, product_type: str = "report") -> dict[str, str]:
    """Map canonical D1 sections to non-empty heading content (md/html)."""
    found: dict[str, str] = {}
    heading_re = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
    if heading_re.search(text):
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
        body_lines = [
            line for line in lines
            if line and not re.match(r"^[-*=_]{3,}\s*$", line)
        ]
        content = " ".join(body_lines)
        if _is_empty_placeholder(content):
            return ""
        return content

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
                    found[canonical] = content or ""
    if "key_findings" not in found:
        slide_parts: list[str] = []
        for heading, lines in blocks:
            if _SLIDE_HEADING_RE.match(heading):
                content = _block_content(heading, lines)
                if content:
                    slide_parts.append(content)
        if slide_parts:
            found["key_findings"] = " ".join(slide_parts)
    if "summary" not in found:
        entry_count = 0
        for heading, lines in blocks:
            if _ENTRY_HEADING_RE.match(heading):
                content = _block_content(heading, lines)
                if content:
                    entry_count += 1
        if entry_count:
            found["summary"] = "present"
    if product_type in ("column", "magazine") and not found:
        for heading, lines in blocks:
            content = _block_content(heading, lines)
            if content:
                found["key_findings"] = content
                break
    return found


def _apply_format_sections(
    sections: dict[str, str], product_type: str
) -> dict[str, str]:
    """Map a product's detected sections onto the three D1 canonical keys."""
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


def _sections_from_rendered_body(
    body: str, output_format: str, product_type: str
) -> dict[str, str] | None:
    """Detect D1 sections from the RENDERED body.

    Returns a ``{key_findings, summary, recommendations}`` mapping for
    markdown/html bodies (possibly all-empty when the body is empty), or
    ``None`` for formats that cannot be parsed (json/agent/audio/...).
    """
    if output_format not in ("markdown", "html"):
        return None
    sections = _sections_from_headings(body, product_type)
    return _apply_format_sections(sections, product_type)


# Minimum content substance for a PROCESSED markdown/html product (issue #298).
_MIN_PRODUCT_CONTENT_CHARS = 200
_MIN_PRODUCT_HEADINGS = 1


def _product_body_text_len(body: str, output_format: str) -> int:
    """Length of the rendered body's visible text (tags stripped for html)."""
    if output_format == "html":
        return len(re.sub(r"<[^>]+>", " ", body).strip())
    return len(body.strip())


def _product_heading_count(body: str, output_format: str) -> int:
    """Number of headings in the rendered body (md ``#`` or html ``<hN>``)."""
    if output_format == "html":
        return len(re.findall(r"<h[1-6][^>]*>", body, re.IGNORECASE))
    return len(re.findall(r"^#{1,6}\s+", body, re.MULTILINE))


# ---------------------------------------------------------------------------
# LLM product judge (issue #298 — layer 3, optional)
# ---------------------------------------------------------------------------
_PRODUCT_JUDGE_ENABLED = True  # env AUTOINFO_PRODUCT_JUDGE=0 disables


def _product_judge_enabled() -> bool:
    raw = os.environ.get("AUTOINFO_PRODUCT_JUDGE", "")
    if raw.strip().lower() in ("0", "false", "no", "off"):
        return False
    return _PRODUCT_JUDGE_ENABLED


def _llm_key_available(llm_config: Config | None) -> bool:
    """True when an LLM API key is resolvable (config or environment)."""
    if llm_config is not None and (llm_config.llm.api_key or "").strip():
        return True
    if os.environ.get("AUTOINFO_LLM_API_KEY", "").strip():
        return True
    try:
        cfg_path = get_config_path()
        if cfg_path is not None and cfg_path.is_file():
            cfg = load_config(cfg_path)
            if (cfg.llm.api_key or "").strip():
                return True
    except Exception:
        pass
    return False


def _build_product_judge_prompt(body: str, output_format: str) -> str:
    return (
        "You are a product quality reviewer. Review the following rendered "
        f"{output_format} product body and decide whether it contains "
        "non-trivial content covering the required sections (executive "
        "summary, key findings, recommendations).\n\n"
        "Return ONLY a JSON object: {\"ok\": true|false, \"reason\": \"...\"}.\n"
        "Set ok=false when the body is empty, garbled, or missing required "
        "sections.\n\n"
        f"--- BODY START ---\n{body}\n--- BODY END ---"
    )


def _escalate_product_judge_prompt(prompt: str, reason: str) -> str:
    return (
        prompt
        + f"\n\nA previous review found the body inadequate: {reason}. "
        "Re-review carefully and return the same JSON verdict shape."
    )


def _parse_product_judge_verdict(response: Any) -> tuple[bool, str] | None:
    """Parse the judge's JSON verdict; ``None`` when unparseable."""
    content = getattr(response, "content", None)
    if content is None:
        content = response
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
    elif isinstance(content, dict):
        data = content
    else:
        return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    return bool(data["ok"]), str(data.get("reason") or "")


def _run_product_judge(
    body: str,
    output_format: str,
    product_type: str,
    llm_config: Config | None = None,
) -> tuple[bool, str]:
    """LLM-judge the rendered body for non-trivial content.

    Returns ``(passed, reason)``.  Fails open on any error (no key, network,
    parse) so the judge never blocks a product on infrastructure failure.
    Retries once with escalating context before failing.
    """
    if not _product_judge_enabled():
        return True, ""
    if product_type.upper() != "PROCESSED" or output_format not in ("markdown", "html"):
        return True, ""
    if not _llm_key_available(llm_config):
        return True, ""
    try:
        prompt = _build_product_judge_prompt(body, output_format)
        for attempt in range(2):
            response = call_with_fallback(
                [{"role": "user", "content": prompt}],
                config=llm_config,
                task="product_judge",
                json_mode=True,
            )
            verdict = _parse_product_judge_verdict(response)
            if verdict is not None:
                ok, reason = verdict
                if ok:
                    return True, ""
                if attempt == 0:
                    prompt = _escalate_product_judge_prompt(prompt, reason)
                    continue
                return False, reason
        return False, "judge returned no verdict"
    except Exception:
        logger.debug("Product judge skipped (fail-open)", exc_info=True)
        return True, ""


def _apply_min_content_guard(
    result: DeliveryOutput,
    entries: list[dict[str, Any]],
    product_type: str,
) -> DeliveryOutput:
    """Force the blocked flag when a PROCESSED product has zero usable entries.

    Layer 1 min-content guard (issue #298): a product with zero usable entries
    after filtering must never be silently shipped as an empty shell.
    """
    if not entries and product_type != "RAW":
        result.delivery_blocked = True
        if not any("min-content guard" in w for w in result.warnings):
            result.warnings.append(
                "min-content guard: 0 usable entries after filtering"
            )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _apply_delivery_gates(
    rendered_output: str,
    output_format: str,
    entries: list[dict[str, Any]],
    context: dict[str, Any],
    product_type: str,
    delivery_gate_configs: dict[str, dict[str, Any]] | None = None,
    fallback_render_fn: Callable[[], str] | None = None,
    llm_config: Config | None = None,
) -> DeliveryOutput:
    """Run D1-D3 delivery gates on rendered output.

    Parameters
    ----------
    rendered_output:
        The rendered output string (markdown, html, or json).
    output_format:
        The format of the rendered output (``"markdown"``, ``"html"``,
        ``"json"``).
    entries:
        List of KB entry dicts used to produce the output.
    context:
        Digest or report context dict.  May contain ``llm_synthesis``
        (for D1 completeness checks).
    product_type:
        ``"PROCESSED"`` or ``"RAW"``.  RAW skips all delivery gates.
    delivery_gate_configs:
        Optional dict of ``{gate_name: config_dict}``.  When ``None``,
        no gates are run and the output is returned as-is.
    fallback_render_fn:
        Optional callable that re-renders the output as markdown.
        Invoked when D2 fails with ``action="fallback"``.
    llm_config:
        Optional :class:`Config` for the LLM product judge (layer 3).

    Returns
    -------
    DeliveryOutput
        Contains the (possibly modified) output, gate results, and
        delivery metadata (blocked flag, warnings).
    """
    if delivery_gate_configs is None:
        return DeliveryOutput(
            output=rendered_output,
            gate_results={},
            delivery_format=output_format,
        )

    # Deferred imports to avoid circular dependencies
    from autoinfo.quality import QualityResult, run_delivery_gates  # noqa: PLC0415, F401

    llm_synthesis: dict[str, Any] = context.get("llm_synthesis", {})

    # D1 completeness is checked against the RENDERED body (issue #298): a
    # body that is empty/garbled but whose synthesis dict is non-empty must
    # fail D1.  Fall back to the synthesis dict only when the body cannot be
    # parsed (json/agent/audio/...).
    body_sections = _sections_from_rendered_body(
        rendered_output, output_format, product_type
    )
    if body_sections is not None:
        key_findings: Any = body_sections.get("key_findings", "")
        summary: Any = body_sections.get("summary", "")
        recommendations: Any = body_sections.get("recommendations", "")
    else:
        key_findings = llm_synthesis.get("key_findings", [])
        summary = llm_synthesis.get("executive_summary", "")
        recommendations = llm_synthesis.get("recommendations", [])

    # Build product_output dict expected by run_delivery_gates
    product_output: dict[str, Any] = {
        "product_type": product_type,
        "format": output_format,
        "body": rendered_output,
        "key_findings": key_findings,
        "summary": summary,
        "recommendations": recommendations,
        "entries": entries,
    }

    gate_results = run_delivery_gates(product_output, context, delivery_gate_configs)
    warnings: list[str] = []
    delivery_blocked = False
    output = rendered_output
    final_format = output_format

    # --- D1: Completeness -----------------------------------------------
    d1_result = gate_results.get("D1-ProductCompleteness")
    if d1_result is not None and not d1_result.passed:
        action = d1_result.details.get("action", "block")
        if action == "block":
            error_detail = d1_result.details.get("error", "incomplete product")
            logger.warning("Delivery blocked by D1: %s", error_detail)
            delivery_blocked = True
            warnings.append(f"D1 blocked: {error_detail}")

    # --- D2: Format integrity (ToS block + format fallback + content) ------
    d2_result = gate_results.get("D2-FormatIntegrity")
    if d2_result is not None:
        # Content-substance check (issue #298): markdown/html bodies must
        # carry a minimum amount of content and at least one heading — the
        # quality.py D2 check treats markdown as "trivially valid".
        _leak_detected = bool(
            rendered_output
            and output_format in ("markdown", "html")
            and _contains_raw_llm_leak(rendered_output)
        )
        if (
            d2_result.passed
            and output_format in ("markdown", "html")
            and product_type.upper() != "RAW"
        ):
            text_len = _product_body_text_len(rendered_output, output_format)
            heading_count = _product_heading_count(rendered_output, output_format)
            if (
                text_len < _MIN_PRODUCT_CONTENT_CHARS
                or heading_count < _MIN_PRODUCT_HEADINGS
                or _leak_detected
            ):
                d2_result = QualityResult(
                    gate_name="D2-FormatIntegrity",
                    passed=False,
                    score=0.0,
                    flagged=True,
                    details={
                        "action": "fallback",
                        "format": output_format,
                        "valid": False,
                        "error": (
                            f"insufficient content: {text_len} chars, "
                            f"{heading_count} headings"
                            + (
                                "; raw LLM error text detected"
                                if _leak_detected
                                else ""
                            )
                        ),
                        "content_chars": text_len,
                        "heading_count": heading_count,
                    },
                )
                gate_results["D2-FormatIntegrity"] = d2_result

        # ToS-based block: RAW delivery from restricted/sensitive sources (F46)
        if not d2_result.passed:
            action = d2_result.details.get("action", "")
            if action == "block":
                error_detail = d2_result.details.get("error", "delivery blocked")
                logger.warning("Delivery blocked by D2 (ToS): %s", error_detail)
                delivery_blocked = True
                warnings.append(f"D2 blocked (ToS): {error_detail}")

        # Format integrity fallback (flagged with action="fallback")
        if d2_result.flagged:
            action = d2_result.details.get("action", "fallback")
            if action == "fallback":
                d2_error = d2_result.details.get("error", "format integrity issue")
                if fallback_render_fn is not None and output_format != "markdown":
                    logger.warning(
                        "D2 fallback: %s — re-rendering as markdown",
                        d2_error,
                    )
                    output = fallback_render_fn()
                    final_format = "markdown"
                    warnings.append("D2 fallback: re-rendered as markdown")
                else:
                    logger.warning("D2 flagged: %s", d2_error)
                    warnings.append(f"D2 flagged: {d2_error}")

    # --- D3: Freshness (flag) -------------------------------------------
    d3_result = gate_results.get("D3-Freshness")
    if d3_result is not None and d3_result.flagged:
        stale = d3_result.details.get("stale_count", 0)
        total = d3_result.details.get("total_entries", 0)
        if stale:
            logger.warning("D3 flagged: %d/%d stale entries", stale, total)
            warnings.append(f"D3: {stale}/{total} entries stale")

    # --- LLM product judge (issue #298 — layer 3, optional) --------------
    if not delivery_blocked:
        judge_passed, judge_reason = _run_product_judge(
            output, final_format, product_type, llm_config
        )
        if not judge_passed:
            logger.warning("Product judge blocked: %s", judge_reason)
            delivery_blocked = True
            warnings.append(f"product judge blocked: {judge_reason}")

    return DeliveryOutput(
        output=output,
        gate_results=gate_results,
        delivery_blocked=delivery_blocked,
        delivery_format=final_format,
        warnings=warnings,
    )


def export_kb(
    domain: str | None = None,
    format: str = "markdown",
    collection_id: str | None = None,  # reserved for future use
    base_url: str | None = None,
) -> dict[str, Any]:
    """Export knowledge base data to the requested format.

    Parameters
    ----------
    domain:
        Optional domain filter.  When ``None``, the entire KB is exported.
    format:
        Output format: ``"markdown"`` (default), ``"json"``, ``"sqlite"``,
        ``"pdf"``, ``"rss"``, ``"csv"``, ``"graphml"``, ``"agent"``,
        ``"bundle"``, ``"sitemap"``, ``"epub"``, or ``"mobi"``.
    collection_id:
        Reserved for future collection-scoped export (not yet implemented).
    base_url:
        Site base URL used for ``format="sitemap"`` (e.g.
        ``"https://your-site.example"``).  Required for sitemap export;
        ignored for other formats.

    Returns
    -------
    dict
        Keys: ``format``, ``path`` (absolute path to the exported file),
        ``entries_count``, ``domain`` (filter used or ``"*"`` for all),
        ``success`` (bool).

    Raises
    ------
    FileNotFoundError
        If no configuration file is found (project not initialized).
    ValueError
        If *format* is not one of the supported values, or if
        *format* is ``"sitemap"`` and *base_url* is not provided.
    """
    if format not in (
        "markdown", "json", "sqlite", "pdf", "rss",
        "csv", "graphml", "agent", "bundle", "sitemap",
        "epub", "mobi",
    ):
        raise ValueError(
            f"Unsupported export format: '{format}'. "
            f"Supported: markdown, json, sqlite, pdf, rss, csv, graphml, "
            f"agent, bundle, sitemap, epub, mobi"
        )

    # --- Locate project root & KB paths ------------------------------------
    config_path = get_config_path()
    if config_path is None or not config_path.is_file():
        raise FileNotFoundError(
            "No configuration found. Run 'autoinfo init' first."
        )

    # config_path is <project>/.autoinfo/config.yaml
    # project_root is <project>/
    autoinfo_dir = config_path.parent
    project_root = autoinfo_dir.parent
    knowledge_dir = project_root / "knowledge"
    db_path = project_root / "autoinfo.db"

    # Configurable weasyprint render timeout (output.pdf_timeout, default 120s)
    try:
        pdf_timeout: float = float(load_config(config_path).output.pdf_timeout)
    except Exception:
        pdf_timeout = 120.0

    # --- Resolve entries to export ----------------------------------------
    entries: list[dict[str, Any]] = []
    if db_path.exists():
        index = SQLiteIndex(db_path)
        if domain:
            entries = index.list_entries(domain, limit=99999)
        else:
            # Fetch all domains by iterating known ones
            known_domains = _list_domains_from_db(index)
            for d in known_domains:
                entries.extend(index.list_entries(d, limit=99999))

    domain_label = domain if domain else "*"

    # --- Source attribution enrichment for text formats (F46) --------------
    if entries and format in ("json", "csv"):
        if domain:
            srcs = _get_domain_source_configs(domain)
        else:
            srcs = []
            for d_name in {e.get("domain", "") for e in entries if e.get("domain")}:
                srcs.extend(_get_domain_source_configs(d_name))
        url_to_source: dict[str, Any] = {}
        for s in srcs:
            url_to_source[(s.url or "").strip().rstrip("/")] = s
        for entry in entries:
            url = (entry.get("source_url") or "").strip().rstrip("/")
            if url in url_to_source:
                s = url_to_source[url]
                entry["attribution"] = (
                    f"Source: {s.name} ({s.url}) — "
                    f"Tier {s.quality_tier}, {s.tos_classification}"
                )
            else:
                entry["attribution"] = ""

    # --- Prepare export directory -----------------------------------------
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_dir = project_root / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # --- Format-specific export -------------------------------------------
    if format == "markdown":
        result = _export_markdown(
            knowledge_dir=knowledge_dir,
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "json":
        result = _export_json(
            knowledge_dir=knowledge_dir,
            export_dir=export_dir,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "sqlite":
        result = _export_sqlite(
            db_path=db_path,
            export_dir=export_dir,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "pdf":
        result = _export_pdf(
            knowledge_dir=knowledge_dir,
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
            pdf_timeout=pdf_timeout,
        )
    elif format == "rss":
        result = _export_rss(
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "csv":
        result = _export_csv(
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "graphml":
        result = _export_graphml(
            export_dir=export_dir,
            domain=domain,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "agent":
        result = _export_agent_json(entries, domain, domain_label)
    elif format == "bundle":
        result = _export_bundle(
            knowledge_dir=knowledge_dir,
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
            pdf_timeout=pdf_timeout,
        )
    elif format == "sitemap":
        result = _export_sitemap(
            export_dir=export_dir,
            domain=domain,
            entries=entries,
            domain_label=domain_label,
            base_url=base_url,
        )
    elif format == "epub":
        result = _export_epub(
            export_dir=export_dir,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    elif format == "mobi":
        result = _export_mobi(
            export_dir=export_dir,
            entries=entries,
            timestamp=timestamp,
            domain_label=domain_label,
        )
    else:
        raise ValueError(f"Unsupported export format: '{format}'")

    result["collection_id"] = collection_id
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _list_domains_from_db(index: SQLiteIndex) -> list[str]:
    """Return distinct domain names from the SQLite index."""
    try:
        conn = sqlite3.connect(str(index.db_path))
        rows = conn.execute("SELECT DISTINCT domain FROM entries").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _parse_tags_list(raw: Any) -> list[str]:
    """Coerce a ``tags`` value into a real list of strings.

    Entries read from the SQLite index carry ``tags`` as a JSON-encoded
    TEXT string (e.g. ``'["ivf", "embryo"]'``), but callers may also pass
    an already-parsed list.  This mirrors the defensive parse used in the
    digest and report renderers so every export format emits real JSON
    arrays instead of JSON-encoded strings.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else [raw] if raw else []
        except (json.JSONDecodeError, TypeError):
            return [raw] if raw else []
    return []


def _export_markdown(
    knowledge_dir: Path,
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Create a tar.gz archive of knowledge base Markdown files."""
    if domain:
        source_dir = knowledge_dir / domain
    else:
        source_dir = knowledge_dir

    out_name = f"autoinfo-export-{domain_label}-{timestamp}.tar.gz"
    out_path = export_dir / out_name

    count = 0
    with tarfile.open(str(out_path), "w:gz") as tar:
        if source_dir.is_dir():
            for md_file in sorted(source_dir.rglob("*.md")):
                arcname = str(md_file.relative_to(knowledge_dir))
                tar.add(str(md_file), arcname=arcname)
                count += 1

    return {
        "format": "markdown",
        "path": str(out_path),
        "entries_count": count,
        "domain": domain_label,
        "success": True,
    }


def _export_json(
    knowledge_dir: Path,
    export_dir: Path,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export all entries as a JSON array, including file content."""
    out_name = f"autoinfo-export-{domain_label}-{timestamp}.json"
    out_path = export_dir / out_name

    export_data: list[dict[str, Any]] = []
    for e in entries:
        file_path = e.get("file_path") or ""
        content = ""
        if file_path and Path(file_path).is_file():
            content = Path(file_path).read_text(encoding="utf-8")

        export_data.append({
            "entry_id": e.get("entry_id"),
            "title": e.get("title"),
            "domain": e.get("domain"),
            "tier": e.get("tier"),
            "source_url": e.get("source_url"),
            "source_type": e.get("source_type"),
            "source_platform": e.get("source_platform"),
            "attribution": e.get("attribution", ""),
            "collected_at": e.get("collected_at"),
            "summary": e.get("summary"),
            "tags": _parse_tags_list(e.get("tags")),
            "relevance_score": e.get("relevance_score"),
            "dedup_status": e.get("dedup_status"),
            "file_path": file_path,
            "content": content,
        })

    out_path.write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "format": "json",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
    }


def _export_sqlite(
    db_path: Path,
    export_dir: Path,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Copy the SQLite database, optionally filtering by domain.

    When *domain* is specified, creates a filtered copy with only the
    matching entries.  When *domain* is ``None``, copies the entire DB.
    """
    out_name = f"autoinfo-export-{domain_label}-{timestamp}.db"
    out_path = export_dir / out_name

    if domain_label == "*" and db_path.is_file():
        # Full DB copy — simple file copy is fast and preserves indexes.
        # First checkpoint WAL to ensure the file is fully synced.
        _wal_checkpoint(db_path)
        shutil.copy2(str(db_path), str(out_path))
        count = len(entries)
    else:
        # Filtered or missing-source copy — create a new DB with schema + filtered entries
        count = _create_filtered_sqlite_copy(db_path, out_path, entries)

    return {
        "format": "sqlite",
        "path": str(out_path),
        "entries_count": count,
        "domain": domain_label,
        "success": True,
    }


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


def _run_pdf_with_timeout(fn: Callable[[], Any], timeout: float, desc: str) -> Any:
    """Run a weasyprint render callable, aborting after *timeout* seconds.

    WeasyPrint's ``write_pdf`` is synchronous and cannot be interrupted in
    process, so the render runs in a worker thread and the caller observes a
    timeout as a raised ``ValueError``.  ``timeout <= 0`` disables the limit.
    """
    if timeout <= 0:
        return fn()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False)
        raise ValueError(
            f"{desc} timed out after {timeout:.0f}s. "
            "Increase output.pdf_timeout in .autoinfo/config.yaml "
            "(default 120s) for large knowledge bases."
        ) from None
    except BaseException:
        pool.shutdown(wait=False)
        raise


def _export_pdf(
    knowledge_dir: Path,
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
    pdf_timeout: float = 120.0,
) -> dict[str, Any]:
    """Export all entries as a PDF file.

    Converts each entry's Markdown content to HTML, combines them into
    a single styled HTML document, and renders via weasyprint.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``.

    Raises
    ------
    ValueError
        If weasyprint is not installed or PDF generation fails.
    """
    try:
        import weasyprint  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        raise ValueError(
            "weasyprint is not installed. PDF export requires weasyprint.\n"
            "Install it with: pip install weasyprint\n"
            "On Ubuntu/Debian: sudo apt install libpango-1.0-0 libpangocairo-1.0-0 "
            "libgdk-pixbuf2.0-dev libffi-dev\n"
            "On macOS: brew install pango\n"
            f"Original error: {exc}"
        ) from exc

    try:
        import markdown as md_lib  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        raise ValueError(
            "markdown library is not installed.\n"
            f"Original error: {exc}"
        ) from exc

    out_name = f"autoinfo-export-{domain_label}-{timestamp}.pdf"
    out_path = export_dir / out_name

    # --- Build HTML document ------------------------------------------------
    html_parts: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>",
        "body{font-family:sans-serif;margin:2em;line-height:1.6;color:#333;}",
        "h1{color:#222;border-bottom:2px solid #ddd;padding-bottom:0.3em;}",
        "h2{color:#444;margin-top:1.5em;}",
        "h3{color:#555;}",
        ".meta{color:#777;font-size:0.9em;margin-bottom:1em;}",
        ".entry{page-break-inside:avoid;margin-bottom:2em;}",
        ".entry-content{margin-top:0.5em;}",
        "pre{background:#f5f5f5;padding:1em;border-radius:4px;",
        "overflow-x:auto;border:1px solid #e0e0e0;}",
        "code{background:#f0f0f0;padding:0.2em 0.4em;border-radius:3px;font-size:0.9em;}",
        "pre code{background:none;padding:0;}",
        "table{border-collapse:collapse;width:100%;margin:1em 0;}",
        "th,td{border:1px solid #ddd;padding:0.5em;text-align:left;}",
        "th{background:#f5f5f5;}",
        "blockquote{border-left:4px solid #ddd;margin:1em 0;padding:0.5em 1em;color:#666;}",
        "img{max-width:100%;height:auto;}",
        "</style></head><body>",
    ]

    if domain:
        html_parts.append(f"<h1>{html.escape(domain)}</h1>")
    else:
        html_parts.append("<h1>AutoInfo Knowledge Base Export</h1>")

    html_parts.append(
        f"<p class='meta'>Exported: {html.escape(timestamp)}  |  "
        f"Entries: {len(entries)}</p>"
    )

    for e in entries:
        title = e.get("title", "Untitled")
        file_path = e.get("file_path") or ""

        content = ""
        if file_path and Path(file_path).is_file():
            raw = Path(file_path).read_text(encoding="utf-8")
            if raw.startswith("---"):
                end_idx = raw.find("---", 3)
                if end_idx != -1:
                    content = raw[end_idx + 3 :].strip()
                else:
                    content = raw
            else:
                content = raw

        html_parts.append("<div class='entry'>")
        html_parts.append(f"<h2>{html.escape(title)}</h2>")

        meta_bits: list[str] = []
        if e.get("source_url"):
            url = html.escape(e["source_url"])
            meta_bits.append(f'Source: <a href="{url}">{url}</a>')
        if e.get("source_type"):
            meta_bits.append(f"Type: {html.escape(e['source_type'])}")
        if e.get("tier"):
            meta_bits.append(f"Tier: {html.escape(e['tier'])}")
        if e.get("relevance_score") is not None:
            meta_bits.append(f"Relevance: {e['relevance_score']}")
        if meta_bits:
            html_parts.append(f"<p class='meta'>{' | '.join(meta_bits)}</p>")

        summary = e.get("summary", "")
        if summary:
            html_parts.append(
                f"<p><strong>Summary:</strong> {html.escape(summary[:1000])}</p>"
            )

        if content:
            content_html = md_lib.markdown(
                content, extensions=["fenced_code", "tables"]
            )
            html_parts.append(f"<div class='entry-content'>{content_html}</div>")

        html_parts.append("</div>")

    html_parts.append("</body></html>")

    full_html = "\n".join(html_parts)

    # --- Render PDF ---------------------------------------------------------
    try:
        _run_pdf_with_timeout(
            lambda: weasyprint.HTML(string=full_html).write_pdf(str(out_path)),
            timeout=pdf_timeout,
            desc="PDF rendering",
        )
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        raise ValueError(
            f"PDF generation failed: {exc}\n"
            "Ensure weasyprint system dependencies are installed.\n"
            "See: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
        ) from exc

    return {
        "format": "pdf",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
    }


def _derive_export_lang(entries: list[dict[str, Any]]) -> str:
    """Derive the ebook language code from *entries*.

    Uses the first entry that declares a ``language`` field, normalized to
    its primary RFC 5646 subtag (``zh-CN`` → ``zh``); otherwise runs
    ``langdetect`` over the concatenated titles/summaries; falls back to
    ``"en"`` when no signal is available.
    """
    for e in entries:
        lang = (e.get("language") or "").strip()
        if lang:
            return lang.split("-")[0].lower()
    sample = " ".join(
        f"{e.get('title', '')} {e.get('summary', '')}".strip()
        for e in entries
        if (e.get("title") or e.get("summary"))
    ).strip()
    if sample:
        try:
            from langdetect import detect  # noqa: PLC0415 — deferred import

            detected = detect(sample)
            if detected:
                return str(detected)
        except Exception:
            logger.debug("langdetect failed on export sample", exc_info=True)
    return "en"


def _export_epub(
    export_dir: Path,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export all entries as an EPUB3 ebook.

    Builds a Markdown book from the entries (one chapter per entry) and
    renders it via :func:`autoinfo.output.ebook.render_epub`.  The file is
    written to ``exports/autoinfo-export-<domain>-<timestamp>.epub``.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``, plus ``data_b64``
        (base64-encoded EPUB bytes).
    """
    from autoinfo.output.ebook import render_epub  # noqa: PLC0415

    chapters: list[tuple[str, str]] = []
    for e in entries:
        title = e.get("title", "Untitled")
        file_path = e.get("file_path") or ""
        content = ""
        if file_path and Path(file_path).is_file():
            raw = Path(file_path).read_text(encoding="utf-8")
            if raw.startswith("---"):
                end_idx = raw.find("---", 3)
                content = raw[end_idx + 3 :].strip() if end_idx != -1 else raw
            else:
                content = raw
        summary = e.get("summary", "") or ""
        body = f"{summary}\n\n{content}".strip() if summary else content
        chapters.append((title, body))

    result = render_epub(
        title=f"{domain_label} \u2014 Export",
        author="AutoInfo",
        lang=_derive_export_lang(entries),
        chapters=chapters,
    )

    out_name = f"autoinfo-export-{domain_label}-{timestamp}.epub"
    out_path = export_dir / out_name
    out_path.write_bytes(base64.b64decode(result["data_b64"]))

    return {
        "format": "epub",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
        "data_b64": result["data_b64"],
    }


def _export_mobi(
    export_dir: Path,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export all entries as a Kindle MOBI file.

    Renders an EPUB in memory (same book as :func:`_export_epub`) and
    converts it via calibre's ``ebook-convert``
    (:func:`autoinfo.output.ebook.render_mobi`).  The file is written to
    ``exports/autoinfo-export-<domain>-<timestamp>.mobi``.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``, plus ``data_b64``
        (base64-encoded MOBI bytes).
    """
    from autoinfo.output.ebook import render_epub, render_mobi  # noqa: PLC0415

    chapters: list[tuple[str, str]] = []
    for e in entries:
        title = e.get("title", "Untitled")
        file_path = e.get("file_path") or ""
        content = ""
        if file_path and Path(file_path).is_file():
            raw = Path(file_path).read_text(encoding="utf-8")
            if raw.startswith("---"):
                end_idx = raw.find("---", 3)
                content = raw[end_idx + 3 :].strip() if end_idx != -1 else raw
            else:
                content = raw
        summary = e.get("summary", "") or ""
        body = f"{summary}\n\n{content}".strip() if summary else content
        chapters.append((title, body))

    epub_result = render_epub(
        title=f"{domain_label} \u2014 Export",
        author="AutoInfo",
        lang=_derive_export_lang(entries),
        chapters=chapters,
    )
    result = render_mobi(epub_result["data_b64"])

    out_name = f"autoinfo-export-{domain_label}-{timestamp}.mobi"
    out_path = export_dir / out_name
    out_path.write_bytes(base64.b64decode(result["data_b64"]))

    return {
        "format": "mobi",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
        "data_b64": result["data_b64"],
    }


# ---------------------------------------------------------------------------
# RSS export
# ---------------------------------------------------------------------------


def _export_rss(
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export all entries as an RSS 2.0 XML feed (stdlib only).

    Builds a valid RSS 2.0 feed with channel metadata and one ``<item>``
    per entry.  Written to ``exports/<domain>/autoinfo-rss-*.xml``.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``.
    """
    # Create domain subdirectory under exports/
    domain_dir = export_dir / (domain if domain else "all")
    domain_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"autoinfo-rss-{domain_label}-{timestamp}.xml"
    out_path = domain_dir / out_name

    # --- Build RSS 2.0 XML --------------------------------------------------
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    title_text = domain_label if domain_label != "*" else "AutoInfo Knowledge Base"
    ET.SubElement(channel, "title").text = f"AutoInfo - {title_text}"
    ET.SubElement(channel, "link").text = "https://autoinfo.ai"
    ET.SubElement(channel, "description").text = (
        f"Knowledge base feed for {title_text}"
    )
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )
    ET.SubElement(channel, "generator").text = "AutoInfo v1.5"

    for e in entries:
        item = ET.SubElement(channel, "item")

        title = e.get("title") or "Untitled"
        source_url = e.get("source_url") or ""
        description = e.get("summary") or ""
        entry_id = e.get("entry_id") or ""
        collected_at = e.get("collected_at") or ""

        ET.SubElement(item, "title").text = title
        if source_url:
            ET.SubElement(item, "link").text = source_url
        if description:
            ET.SubElement(item, "description").text = description

        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = entry_id or source_url or title

        if collected_at:
            try:
                dt = datetime.fromisoformat(collected_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ET.SubElement(item, "pubDate").text = format_datetime(dt)
            except (ValueError, TypeError):
                pass

    # --- Serialize -----------------------------------------------------------
    tree = ET.ElementTree(rss)
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)

    return {
        "format": "rss",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
    }


def _export_sitemap(
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    domain_label: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Export all entries as an XML sitemap (sitemaps.org protocol).

    Builds one ``<url>`` element per KB entry using the entry's source
    URL as ``<loc>`` and a ``<lastmod>`` derived from ``collected_at``.
    An index page is always included via :func:`generate_sitemap`.
    Written to ``exports/<domain>/sitemap.xml``.

    Parameters
    ----------
    export_dir:
        Directory under which the ``<domain>/sitemap.xml`` file is written.
    domain:
        Domain filter; ``None`` means all domains.
    entries:
        KB entries to include in the sitemap.
    domain_label:
        Domain label used in the result dict (``"*"`` when no domain).
    base_url:
        Site base URL for the sitemap index page (e.g.
        ``"https://your-site.example"``).  Required.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``.

    Raises
    ------
    ValueError
        If *base_url* is not provided.
    """
    from autoinfo.output.seo import generate_sitemap

    if not base_url:
        raise ValueError(
            "Sitemap export requires an explicit base_url (no default is "
            "assumed). Pass base_url='https://your-site.example' to "
            "export_kb(format='sitemap', base_url='https://your-site.example'), "
            "or use the CLI: autoinfo output sitemap --base-url https://your-site.example"
        )

    # Create domain subdirectory under exports/
    domain_dir = export_dir / (domain if domain else "all")
    domain_dir.mkdir(parents=True, exist_ok=True)

    out_path = domain_dir / "sitemap.xml"

    sitemap_entries: list[dict[str, Any]] = []
    for e in entries:
        url = e.get("source_url") or ""
        if not url:
            continue

        lastmod = ""
        collected_at = e.get("collected_at") or ""
        if collected_at:
            try:
                dt = datetime.fromisoformat(collected_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                lastmod = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        sitemap_entries.append({
            "url": url,
            "lastmod": lastmod,
            "changefreq": "weekly",
            "priority": 0.8,
        })

    xml = generate_sitemap(
        domain=domain or "",
        base_url=base_url,
        entries=sitemap_entries,
    )
    out_path.write_text(xml, encoding="utf-8")

    return {
        "format": "sitemap",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
    }


def _export_csv(
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export all entries as a CSV file (stdlib csv module).

    Writes one row per entry with headers matching KBEntry field names.
    Complex fields (lists, dicts) are serialised as JSON strings.
    Written to ``exports/<domain>/autoinfo-csv-<timestamp>.csv``.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``.
    """
    import csv as _csv
    import json as _json

    domain_dir = export_dir / (domain if domain else "all")
    domain_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"autoinfo-csv-{domain_label}-{timestamp}.csv"
    out_path = domain_dir / out_name

    field_names: list[str] = []
    field_set: set[str] = set()
    for e in entries:
        for k in e:
            if k not in field_set:
                field_set.add(k)
                field_names.append(k)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(f, fieldnames=field_names, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            row: dict[str, str] = {}
            for k in field_names:
                val = e.get(k)
                if isinstance(val, (list, dict)):
                    row[k] = _json.dumps(val, ensure_ascii=False)
                elif val is None:
                    row[k] = ""
                else:
                    row[k] = str(val)
            writer.writerow(row)

    return {
        "format": "csv",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
    }


def _export_graphml(
    export_dir: Path,
    domain: str | None,
    timestamp: str,
    domain_label: str,
) -> dict[str, Any]:
    """Export the knowledge graph as GraphML.

    Uses :meth:`KBStore.export_knowledge_graph` to retrieve entities
    and relations, then builds a GraphML XML document.

    Written to ``exports/<domain>/autoinfo-graphml-<timestamp>.graphml``.

    Returns
    -------
    dict
        Standard export result dict with keys: ``format``, ``path``,
        ``entries_count``, ``domain``, ``success``.
    """
    from xml.etree import ElementTree as _ET  # noqa: N814

    store = KBStore()
    data = store.export_knowledge_graph(domain=domain or "")

    root = _ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

    key_id = _ET.SubElement(root, "key")
    key_id.set("id", "k0")
    key_id.set("for", "node")
    key_id.set("attr.name", "entity_type")
    key_id.set("attr.type", "string")

    key_name = _ET.SubElement(root, "key")
    key_name.set("id", "k1")
    key_name.set("for", "node")
    key_name.set("attr.name", "entity_name")
    key_name.set("attr.type", "string")

    key_rel = _ET.SubElement(root, "key")
    key_rel.set("id", "k2")
    key_rel.set("for", "edge")
    key_rel.set("attr.name", "relation_type")
    key_rel.set("attr.type", "string")

    key_str = _ET.SubElement(root, "key")
    key_str.set("id", "k3")
    key_str.set("for", "edge")
    key_str.set("attr.name", "strength")
    key_str.set("attr.type", "double")

    graph = _ET.SubElement(root, "graph")
    graph.set("id", "G")
    graph.set("edgedefault", "undirected")

    for ent in data.get("entities", []):
        eid = str(ent.get("id", ""))
        if not eid:
            continue
        node = _ET.SubElement(graph, "node")
        node.set("id", eid)
        d0 = _ET.SubElement(node, "data")
        d0.set("key", "k0")
        d0.text = str(ent.get("entity_type", ent.get("type", "entity")))
        d1 = _ET.SubElement(node, "data")
        d1.set("key", "k1")
        d1.text = str(ent.get("name", ent.get("label", eid)))

    for rel in data.get("relations", []):
        src = str(rel.get("source_id", ""))
        tgt = str(rel.get("target_id", ""))
        if not src or not tgt:
            continue
        edge = _ET.SubElement(graph, "edge")
        edge.set("id", f"e{rel.get('id', '')}")
        edge.set("source", src)
        edge.set("target", tgt)
        d2 = _ET.SubElement(edge, "data")
        d2.set("key", "k2")
        d2.text = str(rel.get("relation_type", rel.get("type", "related_to")))
        d3 = _ET.SubElement(edge, "data")
        d3.set("key", "k3")
        d3.text = str(rel.get("strength", rel.get("weight", "1.0")))

    xml_bytes = _ET.tostring(root, encoding="unicode", xml_declaration=True)

    domain_dir = export_dir / (domain if domain else "all")
    domain_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"autoinfo-graphml-{domain_label}-{timestamp}.graphml"
    out_path = domain_dir / out_name
    out_path.write_text(xml_bytes, encoding="utf-8")

    return {
        "format": "graphml",
        "path": str(out_path),
        "entries_count": len(data.get("entities", [])),
        "domain": domain_label,
        "success": True,
    }


def _export_agent_json(
    entries: list[dict[str, Any]],
    domain: str | None,
    domain_label: str,
) -> dict[str, Any]:
    """Export KB entries as agent-native JSON-LD (``@type: KnowledgeBaseExport``)."""
    agent_entries: list[dict[str, Any]] = []
    for e in entries[:200]:
        agent_entries.append({
            "entry_id": e.get("entry_id", ""),
            "title": e.get("title", ""),
            "summary": e.get("summary", ""),
            "source_url": e.get("source_url", ""),
            "source_platform": e.get("source_platform", ""),
            "tier": e.get("tier", ""),
            "tags": _parse_tags_list(e.get("tags")),
            "relevance_score": e.get("relevance_score"),
            "collected_at": e.get("collected_at", ""),
        })

    output: dict[str, Any] = {
        **_JSONLD_BASE_EXPORT,
        "uuid": str(uuid.uuid4()),
        "domain": domain_label,
        "entries": agent_entries,
        "schema_summary": {
            "fields": [
                "entry_id", "title", "summary", "source_url",
                "source_platform", "tier", "tags", "relevance_score",
                "collected_at",
            ],
            "entry_schema_version": "1.0",
        },
        "stats": {
            "total_entries": len(entries),
            "exported_entries": len(agent_entries),
            "domain": domain or "*",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "success": True,
    }
    return output


# ---------------------------------------------------------------------------
# Bundle export
# ---------------------------------------------------------------------------


def _export_bundle(
    knowledge_dir: Path,
    export_dir: Path,
    domain: str | None,
    entries: list[dict[str, Any]],
    timestamp: str,
    domain_label: str,
    pdf_timeout: float = 120.0,
) -> dict[str, Any]:
    """Export a multi-format ZIP bundle containing PDF + JSON + Markdown + YAML.

    Generates four files inside a ZIP archive:

    - ``report.pdf`` — PDF report (skipped gracefully if weasyprint unavailable)
    - ``data.json`` — JSON data with full entry details
    - ``summary.md`` — Markdown summary listing all entries
    - ``metadata.yaml`` — Export metadata (domain, timestamp, entry count, etc.)

    Returns
    -------
    dict
        Standard export result dict with additional key ``formats`` listing
        the formats actually included in the bundle.
    """
    out_name = f"bundle-{domain_label}-{timestamp}.zip"
    out_path = export_dir / out_name

    # Buffer for in-memory ZIP
    buf = io.BytesIO()
    included_formats: list[str] = []
    pdf_skipped = False

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # --- 1. JSON data ----------------------------------------------------
        json_content = _build_bundle_json(entries)
        zf.writestr("data.json", json_content)
        included_formats.append("json")

        # --- 2. Markdown summary ---------------------------------------------
        md_content = _build_bundle_markdown(entries, domain, domain_label, timestamp)
        zf.writestr("summary.md", md_content)
        included_formats.append("md")

        # --- 3. Metadata YAML ------------------------------------------------
        yaml_content = _build_bundle_metadata(
            domain_label, timestamp, entries, included_formats
        )
        zf.writestr("metadata.yaml", yaml_content)
        included_formats.append("yaml")

        # --- 4. PDF report (graceful fallback) --------------------------------
        try:
            pdf_bytes = _build_bundle_pdf(
                entries, domain, domain_label, timestamp, pdf_timeout=pdf_timeout
            )
            zf.writestr("report.pdf", pdf_bytes)
            included_formats.append("pdf")
        except Exception as exc:
            logger.warning(
                "Bundle PDF generation skipped: %s. "
                "Bundle will contain JSON, Markdown, and YAML only.",
                exc,
            )
            pdf_skipped = True

    # Write ZIP to disk
    out_path.write_bytes(buf.getvalue())

    result: dict[str, Any] = {
        "format": "bundle",
        "path": str(out_path),
        "entries_count": len(entries),
        "domain": domain_label,
        "success": True,
        "formats": included_formats,
    }
    if pdf_skipped:
        result["warning"] = (
            "PDF was skipped — weasyprint not available. "
            "Install with: pip install weasyprint"
        )
    # Empty-state guard (issue #301): signal when the bundle has no entries
    # so callers never silently ship an empty deliverable.
    if not entries:
        result.setdefault("warnings", []).append(
            "Bundle contains no entries — the export is an empty shell."
        )
    return result


def _build_bundle_json(entries: list[dict[str, Any]]) -> str:
    """Build JSON content for the bundle."""
    export_data: list[dict[str, Any]] = []
    for e in entries:
        file_path = e.get("file_path") or ""
        content = ""
        if file_path and Path(file_path).is_file():
            content = Path(file_path).read_text(encoding="utf-8")

        export_data.append({
            "entry_id": e.get("entry_id"),
            "title": e.get("title"),
            "domain": e.get("domain"),
            "tier": e.get("tier"),
            "source_url": e.get("source_url"),
            "source_type": e.get("source_type"),
            "source_platform": e.get("source_platform"),
            "attribution": e.get("attribution", ""),
            "collected_at": e.get("collected_at"),
            "summary": e.get("summary"),
            "tags": json.loads(e.get("tags", "[]")) if e.get("tags") else [],
            "relevance_score": e.get("relevance_score"),
            "dedup_status": e.get("dedup_status"),
            "file_path": file_path,
            "content": content,
        })

    return json.dumps(export_data, ensure_ascii=False, indent=2)


def _build_bundle_markdown(
    entries: list[dict[str, Any]],
    domain: str | None,
    domain_label: str,
    timestamp: str,
) -> str:
    """Build a Markdown summary of all entries for the bundle."""
    lines: list[str] = []
    if domain:
        lines.append(f"# {domain} — Knowledge Base Export")
    else:
        lines.append("# AutoInfo Knowledge Base Export")

    lines.append("")
    lines.append(f"**Exported:** {timestamp}  ")
    lines.append(f"**Entries:** {len(entries)}  ")
    lines.append(f"**Domain:** {domain_label}  ")
    lines.append("")

    for i, e in enumerate(entries, 1):
        title = e.get("title", "Untitled")
        summary = e.get("summary", "")
        source_url = e.get("source_url", "")
        tier = e.get("tier", "")
        relevance = e.get("relevance_score")

        lines.append(f"## {i}. {title}")
        lines.append("")

        if summary:
            lines.append(summary)
            lines.append("")

        meta: list[str] = []
        if source_url:
            meta.append(f"Source: {source_url}")
        if tier:
            meta.append(f"Tier: {tier}")
        if relevance is not None:
            meta.append(f"Relevance: {relevance}")
        if meta:
            lines.append(" | ".join(meta))
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _build_bundle_metadata(
    domain_label: str,
    timestamp: str,
    entries: list[dict[str, Any]],
    included_formats: list[str],
) -> str:
    """Build YAML metadata for the bundle."""
    metadata: dict[str, Any] = {
        "domain": domain_label,
        "generated_at": timestamp,
        "entry_count": len(entries),
        "export_version": "1.0",
        "formats_included": included_formats,
        "generator": "AutoInfo",
    }
    return str(yaml.dump(metadata, default_flow_style=False, allow_unicode=True))


def _build_bundle_pdf(
    entries: list[dict[str, Any]],
    domain: str | None,
    domain_label: str,
    timestamp: str,
    pdf_timeout: float = 120.0,
) -> bytes:
    """Build a PDF report in memory using weasyprint.

    Raises ``ValueError`` if weasyprint or markdown are not installed.
    Returns the raw PDF bytes.
    """
    try:
        import weasyprint  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        raise ValueError(
            "weasyprint is not installed. PDF export requires weasyprint."
        ) from exc

    try:
        import markdown as md_lib  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError) as exc:
        raise ValueError(
            "markdown library is not installed."
        ) from exc

    # Build HTML document
    html_parts: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>",
        "body{font-family:sans-serif;margin:2em;line-height:1.6;color:#333;}",
        "h1{color:#222;border-bottom:2px solid #ddd;padding-bottom:0.3em;}",
        "h2{color:#444;margin-top:1.5em;}",
        "h3{color:#555;}",
        ".meta{color:#777;font-size:0.9em;margin-bottom:1em;}",
        ".entry{page-break-inside:avoid;margin-bottom:2em;}",
        ".entry-content{margin-top:0.5em;}",
        "pre{background:#f5f5f5;padding:1em;border-radius:4px;",
        "overflow-x:auto;border:1px solid #e0e0e0;}",
        "code{background:#f0f0f0;padding:0.2em 0.4em;border-radius:3px;font-size:0.9em;}",
        "pre code{background:none;padding:0;}",
        "table{border-collapse:collapse;width:100%;margin:1em 0;}",
        "th,td{border:1px solid #ddd;padding:0.5em;text-align:left;}",
        "th{background:#f5f5f5;}",
        "blockquote{border-left:4px solid #ddd;margin:1em 0;padding:0.5em 1em;color:#666;}",
        "img{max-width:100%;height:auto;}",
        "</style></head><body>",
    ]

    if domain:
        html_parts.append(f"<h1>{html.escape(domain)}</h1>")
    else:
        html_parts.append("<h1>AutoInfo Knowledge Base Export</h1>")

    html_parts.append(
        f"<p class='meta'>Exported: {html.escape(timestamp)}  |  "
        f"Entries: {len(entries)}</p>"
    )

    for e in entries:
        title = e.get("title", "Untitled")
        file_path = e.get("file_path") or ""

        content = ""
        if file_path and Path(file_path).is_file():
            raw = Path(file_path).read_text(encoding="utf-8")
            if raw.startswith("---"):
                end_idx = raw.find("---", 3)
                if end_idx != -1:
                    content = raw[end_idx + 3:].strip()
                else:
                    content = raw
            else:
                content = raw

        html_parts.append("<div class='entry'>")
        html_parts.append(f"<h2>{html.escape(title)}</h2>")

        meta_bits: list[str] = []
        if e.get("source_url"):
            url = html.escape(e["source_url"])
            meta_bits.append(f'Source: <a href="{url}">{url}</a>')
        if e.get("source_type"):
            meta_bits.append(f"Type: {html.escape(e['source_type'])}")
        if e.get("tier"):
            meta_bits.append(f"Tier: {html.escape(e['tier'])}")
        if e.get("relevance_score") is not None:
            meta_bits.append(f"Relevance: {e['relevance_score']}")
        if meta_bits:
            html_parts.append(f"<p class='meta'>{' | '.join(meta_bits)}</p>")

        summary = e.get("summary", "")
        if summary:
            html_parts.append(
                f"<p><strong>Summary:</strong> {html.escape(summary[:1000])}</p>"
            )

        if content:
            content_html = md_lib.markdown(
                content, extensions=["fenced_code", "tables"]
            )
            html_parts.append(f"<div class='entry-content'>{content_html}</div>")

        html_parts.append("</div>")

    html_parts.append("</body></html>")

    full_html = "\n".join(html_parts)

    # Render to PDF bytes
    try:
        return cast(
            bytes,
            _run_pdf_with_timeout(
                lambda: weasyprint.HTML(string=full_html).write_pdf(),
                timeout=pdf_timeout,
                desc="Bundle PDF rendering",
            ),
        )
    except Exception as exc:
        logger.error("Bundle PDF generation failed: %s", exc)
        raise ValueError(
            f"PDF generation failed: {exc}"
        ) from exc


# DDL for the entries table — used as fallback when no source DB exists
_ENTRIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS entries (
    entry_id        TEXT PRIMARY KEY,
    title           TEXT,
    domain          TEXT,
    tier            TEXT DEFAULT '01-Raw',
    source_url      TEXT,
    source_type     TEXT,
    source_platform TEXT,
    collected_at    TEXT,
    summary         TEXT,
    quality_tier    INTEGER,
    relevance_score REAL,
    dedup_status    TEXT,
    file_path       TEXT,
    tags            TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _wal_checkpoint(db_path: Path) -> None:
    """Force a WAL checkpoint so the main DB file is fully synced.

    SQLite's WAL journal can leave committed transactions in a
    separate ``-wal`` file.  This function checkpoints them back
    into the main database file so file-level operations (copy,
    backup) see a consistent snapshot.
    """
    if not db_path.is_file():
        return
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?checkpoint=truncate", uri=True)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        pass


def _create_filtered_sqlite_copy(
    src_path: Path,
    dst_path: Path,
    entries: list[dict[str, Any]],
) -> int:
    """Create a new SQLite DB at *dst_path* with only *entries*.

    Reads the table schema from *src_path* (if it exists) or creates it
    from scratch.  Returns the number of entries copied.
    """
    dst_conn = sqlite3.connect(str(dst_path))
    dst_conn.row_factory = sqlite3.Row
    dst_conn.execute("PRAGMA journal_mode=WAL")
    dst_conn.execute("PRAGMA synchronous=NORMAL")

    schema_sql: list[str] = []
    index_sql: list[str] = []
    fts5_sql: list[str] = []

    if src_path.is_file():
        # Open source to read schema
        src_conn = sqlite3.connect(str(src_path))
        src_conn.row_factory = sqlite3.Row

        # Get table DDL
        for row in src_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'"
        ).fetchall():
            if row["sql"]:
                schema_sql.append(row["sql"])

        for row in src_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'idx_%_tier'"
        ).fetchall():
            if row["sql"] and row["sql"].strip():
                index_sql.append(row["sql"])

        for row in src_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries_fts5'"
        ).fetchall():
            if row["sql"]:
                fts5_sql.append(row["sql"])

        src_conn.close()

    # Fallback: create schema from scratch if source has none
    if not schema_sql:
        schema_sql = [_ENTRIES_TABLE_DDL]

    # Create tables
    for sql_str in schema_sql:
        dst_conn.execute(sql_str)
    for sql_str in index_sql:
        try:
            dst_conn.execute(sql_str)
        except Exception:
            pass
    for sql_str in fts5_sql:
        try:
            dst_conn.execute(sql_str)
        except Exception:
            pass

    # Insert entries
    count = 0
    for e in entries:
        dst_conn.execute(
            """
            INSERT OR REPLACE INTO entries
                (entry_id, title, domain, tier, source_url, source_type,
                 source_platform, collected_at, summary, quality_tier,
                 relevance_score, dedup_status, file_path, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e.get("entry_id"),
                e.get("title"),
                e.get("domain"),
                e.get("tier", "01-Raw"),
                e.get("source_url"),
                e.get("source_type"),
                e.get("source_platform"),
                e.get("collected_at"),
                e.get("summary"),
                e.get("quality_tier", 1),
                e.get("relevance_score", 0.0),
                e.get("dedup_status", "unique"),
                e.get("file_path"),
                e.get("tags", "[]"),
            ),
        )
        count += 1

    dst_conn.commit()
    dst_conn.close()

    return count


# ---------------------------------------------------------------------------
# Digest generation
# ---------------------------------------------------------------------------

PERIOD_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}

PERIOD_LABELS: dict[str, str] = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
}


def _compute_date_range(period: str) -> tuple[str, str]:
    """Return (date_from, date_to) ISO strings for the given period.

    Parameters
    ----------
    period:
        One of ``"daily"``, ``"weekly"``, ``"monthly"``.

    Returns
    -------
    tuple[str, str]
        ``(date_from, date_to)`` — ``date_from`` is *period* days ago,
        ``date_to`` is today (both as ``YYYY-MM-DD``).
    """
    days = PERIOD_DAYS.get(period, 7)
    today = date.today()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to = today.isoformat()
    return date_from, date_to


def _curated_sort_key(entry: dict[str, Any]) -> tuple[float, str]:
    """Sort key for curated consumption: relevance desc, stable tie by entry_id."""
    score = entry.get("relevance_score")
    try:
        quality = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        quality = 0.0
    return (-quality, str(entry.get("entry_id", "")))


def _filter_entries_by_content_preference(
    entries: list[dict[str, Any]],
    content_preference: str,
) -> list[dict[str, Any]]:
    """Filter KB entries by the end-user ``content_preference`` tier policy.

    - ``"raw_only"``: keep only 01-Raw tier entries.
    - ``"processed_only"``: keep 02-Draft and 03-Wiki tier entries with
      curated-priority consumption: 03-Wiki entries come first (sorted by
      relevance desc, stable ties), 02-Draft entries fill the remainder.
      Each selected entry carries ``source_tier`` — ``"curated"`` for
      Wiki, ``"fresh"`` for Draft — for tier badge rendering.
    - ``"both"`` (or any unknown value): return entries unchanged.

    The input list is not mutated.
    """
    if content_preference == "raw_only":
        return [e for e in entries if e.get("tier", "") == "01-Raw"]
    if content_preference == "processed_only":
        wiki = sorted(
            (e for e in entries if e.get("tier", "") == "03-Wiki"),
            key=_curated_sort_key,
        )
        draft = sorted(
            (e for e in entries if e.get("tier", "") == "02-Draft"),
            key=_curated_sort_key,
        )
        return [
            *({**e, "source_tier": "curated"} for e in wiki),
            *({**e, "source_tier": "fresh"} for e in draft),
        ]
    return entries


def _source_tier_badge_enabled() -> bool:
    """Resolve ``output.source_tier_badge`` from config (default True)."""
    try:
        config_path = get_config_path()
        if config_path is not None:
            return bool(load_config(config_path).output.source_tier_badge)
    except Exception:
        logger.debug(
            "Failed to load output.source_tier_badge, defaulting to True",
            exc_info=True,
        )
    return True


def _output_config_ref_limit() -> int:
    """Resolve ``output.ref_limit`` from config (default 60).

    The CLI/MCP default path (no explicit ``ref_limit`` param) falls back
    to the project config's ``output.ref_limit``, which defaults to 60
    (issue #11 — references render uncapped).
    """
    try:
        config_path = get_config_path()
        if config_path is not None:
            return int(load_config(config_path).output.ref_limit)
    except Exception:
        logger.debug(
            "Failed to load output.ref_limit, defaulting to 60",
            exc_info=True,
        )
    return 60


def _ref_sort_key(e: dict[str, Any]) -> tuple[bool, float]:
    """Deterministic References sort key: (has summary desc, relevance desc)."""
    return (
        bool(str(e.get("summary") or "").strip()),
        float(e.get("relevance_score") or 0.0),
    )


# --- Low-value reference relegation (issue #42) ------------------------------
# Paid-user audit flagged References entries that are URL-valid + real but
# off-domain noise for commercial domains: promos / ticket sales (``save up to
# $300 on a TechCrunch Disrupt pass``), obituaries (``Dolly Parton ... has died
# at age 80``), and celebrity/entertainment fluff.  These entries are NOT
# deleted (traceability stays in Raw) — they are re-ranked to the tail of the
# References list and, for non-language-learning domains with enough real
# entries, dropped from References entirely.
#
# Signals are PHRASE-SHAPED (issue #42 Do-NOT): bare words like ``died`` /
# ``discount`` are deliberately NOT used, so a legit sentence ("pricing models
# to promote value", "discounts up to 10% in regions") never fires.

_REF_LANG_LEARNING_DOMAINS: frozenset[str] = frozenset({
    "language-learning",
    "english-learning", "french-learning", "spanish-learning",
    "hindi-learning", "korean-learning", "portuguese-learning",
    "russian-learning", "italian-learning",
})

_REF_LOW_VALUE_PATTERNS: dict[str, tuple[str, ...]] = {
    "promo": (
        r"save up to",
        r"save\s+\$",
        r"\blast chance\b",
        r"\bdisrupt pass\b",
        r"\bregister now\b",
        r"\bearly access\b",
        r"\bgiveaway",
        r"\bsale ends\b",
        r"\bcoupon\b",
        r"\bdeal of the (?:day|week)\b",
        r"\btickets? (?:on sale|available|now|remaining)\b",
        r"(?:buy|book|purchase|grab|secure|get) (?:your )?tickets?",
        r"\bdiscount (?:code|coupon|offer|of \d+%?|\d+%? off)\b",
        r"\d+%?\s*discount\b",
    ),
    "obituary": (
        r"\bdied\b",
        r"\bhas died\b",
        r"\bdied at age\b",
        r"\bdies at\b",
        r"\bdeath of\b",
        r"\bobituary\b",
        r"\bfuneral\b",
        r"\bin memoriam\b",
    ),
    "celebrity": (
        r"\bcelebrity\b",
        r"\bdolly parton\b",
        r"\bdavid bowie\b",
        r"\bfilm star\b",
        r"\bhollywood\b",
        r"\bpop star\b",
        r"\breality tv\b",
    ),
}

_COMPILED_LOW_VALUE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in _REF_LOW_VALUE_PATTERNS.items()
}

_REF_LOW_VALUE_CONTEXT_CHARS = 200
_REF_LOW_VALUE_MIN_REAL_ENTRIES = 20


def _is_lang_learning_domain(domain: str) -> bool:
    """True when *domain* is a language-learning umbrella or sub-domain."""
    return domain in _REF_LANG_LEARNING_DOMAINS


def _low_value_signal_penalty(entry: dict[str, Any]) -> int:
    """Score *entry* on the phrase-shaped low-value signals (issue #42).

    Returns the number of distinct low-value categories (promo / obituary /
    celebrity) matched across the title + first ~200 chars of the
    summary/content.  0 = clean.  Deterministic: no LLM, no randomness.
    """
    haystack = " ".join(filter(None, (
        str(entry.get("title") or ""),
        str(entry.get("summary") or "")[:_REF_LOW_VALUE_CONTEXT_CHARS],
        str(entry.get("content") or "")[:_REF_LOW_VALUE_CONTEXT_CHARS],
    )))
    return sum(
        1
        for patterns in _COMPILED_LOW_VALUE_PATTERNS.values()
        if any(p.search(haystack) for p in patterns)
    )


def _sorted_ref_entries(
    entries: list[dict[str, Any]], domain: str | None = None
) -> list[dict[str, Any]]:
    """Return *entries* ordered for the References list (issues #11, #42).

    Issue #11: the references context list is capped at ``ref_limit``, so the
    sort MUST run on the full ``entries`` list BEFORE the ref dicts are built
    (ref dicts drop ``relevance_score``/``summary``).  Title-only entries
    (empty summary — e.g. ProductHunt) de-prioritize below summary-bearing
    ones; the deterministic tiebreak is ``relevance_score`` desc.

    Issue #42: entries carrying low-value signals (promo / obituary /
    celebrity — see :func:`_low_value_signal_penalty`) are re-ranked AFTER
    the clean entries, so they only surface when the domain has very few real
    entries.  Language-learning domains keep their cultural/historical
    teaching material: flagged entries always stay in the returned list, at
    the tail (reduce, don't delete).  For non-language-learning domains,
    flagged entries are dropped from References entirely when the domain still
    has at least ``_REF_LOW_VALUE_MIN_REAL_ENTRIES`` clean candidates;
    otherwise a few survive at the tail rather than leaving the list sparse.
    Entries are never deleted from the KB — this only affects References
    ordering.  Deterministic: same input → same output, no LLM calls.
    """
    lang_mode = domain is None or _is_lang_learning_domain(domain or "")
    clean: list[dict[str, Any]] = []
    lang_flagged: list[dict[str, Any]] = []
    commercial_flagged: list[dict[str, Any]] = []
    for entry in entries:
        if _low_value_signal_penalty(entry) == 0:
            clean.append(entry)
            continue
        entry_domain = str(entry.get("domain") or domain or "")
        if _is_lang_learning_domain(entry_domain):
            lang_flagged.append(entry)
        else:
            commercial_flagged.append(entry)
    clean_sorted = sorted(clean, key=_ref_sort_key, reverse=True)
    drop_commercial = (
        commercial_flagged and not lang_mode
        and len(clean) >= _REF_LOW_VALUE_MIN_REAL_ENTRIES
    )
    kept = lang_flagged + ([] if drop_commercial else commercial_flagged)
    if not kept:
        return clean_sorted
    return clean_sorted + sorted(kept, key=_ref_sort_key, reverse=True)


def _cap_product_key_findings(
    key_findings: list[Any], references: list[dict[str, Any]]
) -> list[Any]:
    """Cap *key_findings* to ``min(MAX_FINDINGS, len(references))``.

    Issue #11 (decision a): the enterprise ``selected N of M`` label renders
    ``selected {{ key_findings|length }} of {{ references|length }}``, and the
    PRIMARY synthesis ``key_findings`` is LLM-produced and unbounded (only the
    §2.4 re-prompt is bounded by ``_DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS``).
    When ``ref_limit`` drops BELOW the findings count the label would invert
    (``selected 9 of 8``).  Cap the findings in the render context to
    ``min(12, len(references))`` so the label can never invert.
    """
    cap = min(_DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS, len(references))
    return list(key_findings[:cap])


def _promote_eligible_drafts(
    store: KBStore,
    domains: list[str],
    caller: str = "digest",
) -> dict[str, Any]:
    """Promote eligible 02-Draft entries for the given domains (T6 trigger).

    Best-effort promotion sweep run before entry selection: every 02-Draft
    entry is admission-checked by the existing promote path
    (:meth:`KBStore.promote_kb_draft`) inside its own try/except, so a
    rejection or an unexpected failure never blocks content generation.
    Project gate thresholds apply when a config is present (defaults
    otherwise).  Idempotent — already-promoted entries are no longer in
    02-Draft and are naturally skipped.

    Returns a summary dict ``{promoted: [entry_id], rejected:
    [{entry_id, reasons}], failed: [{entry_id, error}]}`` which callers
    may log or ignore.
    """
    summary: dict[str, Any] = {"promoted": [], "rejected": [], "failed": []}
    if not domains:
        return summary
    try:
        config_path = get_config_path()
        config = load_config(config_path) if config_path is not None else None
    except Exception:
        config = None
    for domain in domains:
        try:
            drafts = store.list_kb_tier(
                domain=domain, tier="02-Draft", limit=10000
            )
        except Exception as exc:
            logger.warning(
                "promote_eligible: could not list 02-Draft for '%s': %s",
                domain,
                exc,
            )
            continue
        for draft in drafts:
            draft_id = draft.get("entry_id", "")
            if not draft_id:
                continue
            try:
                store.promote_kb_draft(
                    draft_id=draft_id, config=config, caller=caller
                )
                summary["promoted"].append(draft_id)
                logger.info(
                    "Product-driven promotion of %s (caller=%s)",
                    draft_id,
                    caller,
                )
            except PromotionRejected as exc:
                summary["rejected"].append(
                    {
                        "entry_id": draft_id,
                        "reasons": [str(r) for r in exc.reasons],
                    }
                )
            except Exception as exc:
                summary["failed"].append({"entry_id": draft_id, "error": str(exc)})
                logger.warning(
                    "Promotion failed for %s: %s", draft_id, exc
                )
    return summary


def _resolve_content_preference(user_id: str) -> str:
    """Resolve the end-user ``content_preference`` tier policy (B-001).

    Lazy-loads stored preferences for *user_id* via
    :func:`autoinfo.user_store.get_preferences` and resolves the effective
    ``content_preference`` via
    :func:`autoinfo.user_store.resolve_content_preference`.

    Returns ``"both"`` when *user_id* is empty, the user has no stored
    preferences, or the stored value is missing/invalid — so callers
    without a user context keep the pre-B-001 behavior (no filtering).
    """
    if not user_id:
        return "both"
    try:
        from autoinfo.user_store import (  # noqa: PLC0415
            get_preferences,
            resolve_content_preference,
        )
        prefs_result = get_preferences(user_id)
        if "preferences" in prefs_result:
            content_preference = resolve_content_preference(
                prefs_result["preferences"]
            )
            logger.debug(
                "Applied stored content_preference='%s' for user '%s'",
                content_preference,
                user_id,
            )
            return content_preference
    except Exception:
        logger.debug(
            "Failed to load preferences for user '%s'",
            user_id,
            exc_info=True,
        )
    return "both"


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "data" / "templates"

_jinja_env: Environment | None = None


def _html_autoescape(template_name: str | None) -> bool:
    """Enable Jinja2 autoescaping for HTML templates only.

    Markdown templates (``*.md.j2``) keep autoescaping OFF so they can
    emit raw Markdown freely.  HTML templates (``*.html.j2``) turn
    autoescaping ON so user-supplied text is safely escaped; pre-rendered
    HTML content is marked ``|safe`` in the template where needed.
    """
    if template_name is None:
        return False
    return template_name.endswith(".html.j2")


def _get_jinja_env() -> Environment:
    """Return a cached Jinja2 environment for the ``data/templates/`` directory.

    The environment loads any template file in ``data/templates/`` —
    including both ``.md.j2`` (Markdown) and ``.html.j2`` (HTML)
    templates.  Autoescaping is enabled selectively for ``.html.j2``
    files via :func:`_html_autoescape`.

    Registers a ``product_summary`` filter that returns ``""`` for
    empty/placeholder summaries (defense-in-depth for issue #294).
    """
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=_html_autoescape,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _jinja_env.filters["product_summary"] = lambda v: "" if _is_empty_summary(str(v)) else v
        _jinja_env.filters["platform_name"] = _platform_name
    return _jinja_env


# ---------------------------------------------------------------------------
# ProductTemplate — template selection with domain overrides
# ---------------------------------------------------------------------------

# Maps output format strings to template variant suffixes.
# E.g. format="markdown" → template variant "md" → digest.md.j2
FORMAT_TO_VARIANT: dict[str, str] = {
    "markdown": "md",
    "html": "html",
    "json": "json",
    "pdf": "pdf",
}


class ProductTemplate:
    """Wraps Jinja2 rendering with product metadata and template selection.

    Template selection strategy (first match wins):

    1. ``.autoinfo/templates/<domain>/<type>/<variant>.j2`` — domain-specific
       override (e.g. ``.autoinfo/templates/medical-research/digest/weekly.j2``)
    2. ``data/templates/<type>/<variant>.j2`` — built-in base template
       (e.g. ``data/templates/digest/weekly.j2``)
    3. ``data/templates/<type>/default.j2`` — default variant for that type
    4. ``data/templates/<type>.<variant>.j2`` — legacy flat naming (backward
       compatible with the existing ``digest.md.j2`` convention)

    The *access_level* controls freemium gating (G15):

    - ``"free"`` (default) — available to all users
    - ``"premium"`` — requires active paid subscription
    - ``"enterprise"`` — requires enterprise-tier subscription

    Usage::

        pt = ProductTemplate(domain="medical-research", access_level="premium")
        output = pt.render("digest", "md", context_dict)
    """

    def __init__(
        self,
        domain: str,
        access_level: Literal["free", "premium", "enterprise"] = "free",
    ):
        self.domain = domain
        self.access_level: Literal["free", "premium", "enterprise"] = access_level
        self._base_dir = _TEMPLATES_DIR
        self._domain_dir = Path.cwd() / ".autoinfo" / "templates" / domain

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        product_type: str,
        variant: str,
        data: dict[str, Any],
    ) -> str:
        """Render a template for *product_type* and *variant* with *data*.

        Parameters
        ----------
        product_type:
            Template category (e.g. ``"digest"``, ``"report"``,
            ``"tutorial"``, ``"presentation"``).
        variant:
            Template variant (e.g. ``"md"``, ``"html"``, ``"weekly"``).
        data:
            Template context variables.

        Returns
        -------
        str
            Rendered template output.

        Raises
        ------
        FileNotFoundError
            If no matching template is found in any search path.
        """
        env = self._get_env()

        candidates = [
            f"{product_type}/{variant}.j2",
            f"{product_type}/default.j2",
            f"{product_type}.{variant}.j2",   # legacy flat naming
            f"{product_type}.default.j2",      # legacy default
        ]

        for name in candidates:
            try:
                template = env.get_template(name)
                return template.render(**data)
            except TemplateNotFound:
                continue

        raise FileNotFoundError(
            f"No template found for domain={self.domain}, "
            f"type={product_type}, variant={variant}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_env(self) -> Environment:
        """Create a Jinja2 environment that checks domain overrides first.

        Uses :class:`ChoiceLoader` so that domain-specific templates (in
        ``.autoinfo/templates/<domain>/``) are preferred over built-in
        base templates (in ``data/templates/``).
        """
        loaders: list[FileSystemLoader] = []
        if self._domain_dir.is_dir():
            loaders.append(FileSystemLoader(str(self._domain_dir)))
        loaders.append(FileSystemLoader(str(self._base_dir)))

        if len(loaders) == 1:
            # Only base dir exists — no ChoiceLoader needed
            env = Environment(
                loader=loaders[0],
                autoescape=_html_autoescape,
                trim_blocks=True,
                lstrip_blocks=True,
            )
        else:
            env = Environment(
                loader=ChoiceLoader(loaders),
                autoescape=_html_autoescape,
                trim_blocks=True,
                lstrip_blocks=True,
            )
        # Defense-in-depth for issue #294: normalize empty/placeholder summaries
        env.filters["product_summary"] = lambda v: "" if _is_empty_summary(str(v)) else v
        # Defense-in-depth for issue #302: map internal platform ids to display names
        env.filters["platform_name"] = _platform_name
        return env


# ---------------------------------------------------------------------------
# Product template registry
# ---------------------------------------------------------------------------

PRODUCT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "digest",
        "description": "Scheduled knowledge digests",
        "access_level": "free",
        "template": ProductTemplate(domain="*", access_level="free"),
    },
    {
        "name": "report",
        "description": "Thematic structured reports",
        "access_level": "free",
        "template": ProductTemplate(domain="*", access_level="free"),
    },
    {
        "name": "tutorial",
        "description": "Learning path tutorials",
        "access_level": "free",
        "template": ProductTemplate(domain="*", access_level="free"),
    },
    {
        "name": "presentation",
        "description": "Slide-based presentations",
        "access_level": "free",
        "template": ProductTemplate(domain="*", access_level="free"),
    },
    {
        "name": "premium-briefing",
        "description": "Premium briefings with deep analysis and actionable insights",
        "access_level": "premium",
        "template": ProductTemplate(domain="*", access_level="premium"),
    },
    {
        "name": "column",
        "description": "Paid deep-dive column",
        "access_level": "premium",
        "template": ProductTemplate(domain="*", access_level="premium"),
    },
    {
        "name": "magazine-digest",
        "description": "Magazine-styled digest of per-title RSS",
        "access_level": "free",
        "template": ProductTemplate(domain="*", access_level="free"),
    },
    {
        "name": "enterprise-briefing",
        "description": "Enterprise briefings with custom data, white-labeling, and priority support",  # noqa: E501
        "access_level": "enterprise",
        "template": ProductTemplate(domain="*", access_level="enterprise"),
    },
]


# Product family → H1 product word (issue #318).  Keyed by the family name
# resolved by :func:`_resolve_digest_product_type` /
# :func:`_resolve_report_product_type` (the registry row name when its flat
# template file exists, else the default family).  The default
# ``digest``/``report`` families map to their own words so the non-product
# paths keep their historical titles byte-identical.
_PRODUCT_H1_WORDS: dict[str, str] = {
    "digest": "Digest",
    "report": "Report",
    "premium-briefing": "Premium Briefing",
    "column": "Column",
    "magazine-digest": "Magazine Digest",
    "enterprise-briefing": "Enterprise Briefing",
}


def _product_h1_word(family: str, default: str = "Digest") -> str:
    """Return the H1 product word for a resolved product *family* (issue #318).

    *family* is the template family name produced by
    :func:`_resolve_digest_product_type` / :func:`_resolve_report_product_type`
    (e.g. ``"premium-briefing"``).  Unknown families fall back to *default*
    so the non-product paths keep their historical titles.
    """
    return _PRODUCT_H1_WORDS.get(family, default)


def _resolve_digest_product_type(template: ProductTemplate, variant: str) -> str:
    """Map a ProductTemplate instance back to its digest template family.

    ``generate_digest``'s *product_template* parameter is expected to be a
    row's ``template`` from :data:`PRODUCT_TEMPLATES`. Rows whose name has
    a flat template file of its own (e.g. ``magazine-digest`` →
    ``magazine-digest.md.j2``) render through their own family; every other
    row — and any non-registry template — keeps the default ``digest``
    family, so the base ``digest`` row (and report-family rows, should one
    ever be passed) still render ``digest.md.j2`` unchanged.

    This mirrors how ``generate_report`` derives ``product_type`` for the
    ``column`` template (T40): the render site selects the family, and the
    identity lookup is guarded by an on-disk existence check so a registry
    name can never point at a template that does not exist (FileNotFoundError
    trap from the T40 premium-briefing/enterprise-briefing rows).
    """
    for row in PRODUCT_TEMPLATES:
        if row["template"] is template:
            name = str(row["name"])
            if (_TEMPLATES_DIR / f"{name}.{variant}.j2").is_file():
                return name
            return "digest"
    return "digest"


def _resolve_report_product_type(
    template: ProductTemplate, variant: str, report_type: str
) -> str:
    """Map a ProductTemplate instance back to its report template family.

    ``generate_report``'s *product_template* parameter is expected to be a
    row's ``template`` from :data:`PRODUCT_TEMPLATES`. Rows whose name has
    a flat template file of its own (e.g. ``premium-briefing`` →
    ``premium-briefing.md.j2``, ``enterprise-briefing`` →
    ``enterprise-briefing.md.j2``, ``column`` → ``column.md.j2``) render
    through their own family; every other row — and any non-registry
    template — keeps the default ``report`` family, so the base ``report``
    row still renders ``report.md.j2`` unchanged. The ``column`` report
    type keeps its own family even for non-registry templates (T40
    backward compatibility).

    This mirrors the ``column`` selection previously hardcoded at the
    render site and the guard-first identity lookup of
    :func:`_resolve_digest_product_type`: the on-disk existence check
    ensures a registry name can never point at a template that does not
    exist (FileNotFoundError trap from the T40
    premium-briefing/enterprise-briefing rows).
    """
    for row in PRODUCT_TEMPLATES:
        if row["template"] is template:
            name: str = row["name"]
            if (_TEMPLATES_DIR / f"{name}.{variant}.j2").is_file():
                return name
            return "column" if report_type == "column" else "report"
    return "column" if report_type == "column" else "report"


def list_output_templates(domain: str = "") -> dict[str, Any]:
    """List available output templates for a domain.

    Parameters
    ----------
    domain:
        Domain name filter (optional; empty string = all domains).

    Returns
    -------
    dict with keys: ``domain``, ``templates``, ``count``.
    """
    templates = [
        {"name": t["name"], "description": t["description"], "access_level": t["access_level"]}
        for t in PRODUCT_TEMPLATES
    ]
    return {"domain": domain, "templates": templates, "count": len(templates)}


# ---------------------------------------------------------------------------
# LLM synthesis for digests
# ---------------------------------------------------------------------------

_DIGEST_SYSTEM_PROMPT = (
    "You are a research digest assistant. Given a list of knowledge base "
    "entries from the past period, synthesize them into a concise digest. "
    "Respond with valid JSON only, no markdown formatting."
)

_DIGEST_FIELD_DESCRIPTIONS = [
    '"executive_summary": "2-3 sentence overview of the period\'s key developments"',
    '"key_findings": [{"topic": "Topic name", "detail": "Key finding sentence"}], '
    "list 3-5 most important findings",
    '"trends": ["Trend or pattern observed across multiple entries"], '
    "list relevant cross-cutting trends",
    '"recommendations": ["Actionable recommendation based on the data"], '
    "list actionable recommendations if any",
]

# Product-family field sections appended to the digest synthesis prompt
# (spec §2.4, todo 7). Keyed by the resolved product family so the default
# ``digest`` family stays unchanged. ``implications`` / ``risks`` /
# ``action_required`` are index-aligned 1:1 with ``key_findings`` (spec
# §5.2-5.4 per-takeaway pairing); ``key_metrics`` is enterprise-only.
_DIGEST_PRODUCT_BASE_FIELDS: list[str] = [
    '"implications": ["So-what implication for finding 1", ...], one item per '
    "key_findings entry, index-aligned 1:1 (item N matches finding N)",
    '"risks": [{"title": "Risk title", "likelihood": "high|medium|low", '
    '"impact": "high|medium|low", "mitigation": "Mitigation action"}], '
    "one item per key_findings entry, same order",
    '"action_required": ["Action for finding 1", ...], one item per '
    "key_findings entry, index-aligned 1:1",
]

_DIGEST_ENTERPRISE_METRICS_FIELDS: list[str] = [
    '"key_metrics": [{"metric": "Metric name", "value": "Quantified value", '
    '"source": "Entry/study/dataset"}], quantified metrics only '
    "(enterprise decision-support table)",
]

# Issue #313: magazine-digest editorial framing — an editor's note framing
# the week plus a personality profile / deep-dive feature story, so the
# magazine is a narrative product rather than a bare summary list.
_DIGEST_MAGAZINE_EDITORIAL_FIELDS: list[str] = (
    _DIGEST_PRODUCT_BASE_FIELDS
    + [
        '"editorial_intro": "A 2-3 sentence editorial introduction paragraph '
        'for this magazine edition \u2014 the editor\'s framing of the week, '
        'written in a magazine voice (opinionated but factual)"',
        '"feature_story": "A 3-5 paragraph personality profile / deep-dive '
        "story on one notable person, company, or trend from the period, in "
        "magazine feature style \u2014 a narrative beyond the summary list\"",
    ]
)

# Issue #316: column deep-dive sections — the column template renders a
# Deep Dive from a ``sections`` array (each ``{title, content}``), so the
# digest synthesis must request it (mirroring the #308 report-path wording).
_DIGEST_COLUMN_SECTIONS_FIELDS: list[str] = [
    '"sections": [{"title": "Subsection title", "content": "2-3 paragraphs '
    'of analysis grounded in specific entries \u2014 quote concrete numbers, '
    'dates, and named companies/studies from the source material; no filler '
    'paragraphs"}], 8-10 distinct deep-dive subsections, each with '
    'substantive content',
]

_DIGEST_PRODUCT_FIELD_DESCRIPTIONS: dict[str, list[str]] = {
    "premium-briefing": _DIGEST_PRODUCT_BASE_FIELDS,
    "magazine-digest": _DIGEST_MAGAZINE_EDITORIAL_FIELDS,
    "enterprise-briefing": (
        _DIGEST_PRODUCT_BASE_FIELDS + _DIGEST_ENTERPRISE_METRICS_FIELDS
    ),
    "column": _DIGEST_COLUMN_SECTIONS_FIELDS,
}


def _build_digest_llm_prompt(
    entries: list[dict[str, Any]], product_family: str = "digest"
) -> str:
    """Build the user prompt for LLM digest synthesis.

    For product template families (``premium-briefing`` /
    ``enterprise-briefing`` / ``magazine-digest``) the requested field set
    additionally includes the §2.4 product fields — ``implications`` /
    ``risks`` / ``action_required`` (index-aligned with ``key_findings``),
    plus ``key_metrics`` for enterprise-briefing — keyed by the resolved
    family. The default ``digest`` family is unchanged (spec §2.4, todo 7).
    """
    lines: list[str] = [
        "Synthesize the following knowledge base entries into a digest.",
        "",
    ]

    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "(no title)")
        summary = entry.get("summary", "")
        tags_raw = entry.get("tags", "")
        if isinstance(tags_raw, str):
            try:
                tags_list = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags_list = [tags_raw] if tags_raw else []
        elif isinstance(tags_raw, list):
            tags_list = tags_raw
        else:
            tags_list = []
        tags_str = ", ".join(tags_list) if tags_list else "\u2014"

        lines.append(f"Entry {i}:")
        lines.append(f"  Title: {title}")
        lines.append(f"  Summary: {summary[:500] if summary else chr(8212)}")
        lines.append(f"  Tags: {tags_str}")
        lines.append(f"  Source URL: {entry.get('source_url') or chr(8212)}")
        lines.append("")

    lines.append("Now generate a JSON digest with the following fields:")
    for desc in _DIGEST_FIELD_DESCRIPTIONS:
        lines.append(f"  - {desc}")
    product_descs = _DIGEST_PRODUCT_FIELD_DESCRIPTIONS.get(product_family, [])
    if product_descs:
        lines.append("")
        lines.append("Additional product fields:")
        for desc in product_descs:
            lines.append(f"  - {desc}")
    lines.append("")
    lines.append(
        "When a key finding, recommendation, or trend is backed by a "
        "specific entry, cite its source inline as (Source: URL)."
    )
    lines.append("Return all fields in a single JSON object.")

    return "\n".join(lines)


def _call_llm_for_digest(
    prompt: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Call LiteLLM to synthesize a digest from entries.

    Uses the same LiteLLM pattern as :class:`LLMExtractor` but with
    a custom summarization prompt.
    """
    from autoinfo.output import fault_inject  # noqa: PLC0415

    try:
        fault_inject.maybe_fault("digest")
    except Exception as exc:
        logger.warning("FAULT_INJECT[digest]: %s", exc)
        return {}

    if config is None:
        config_path = get_config_path()
        if config_path is not None:
            try:
                config = load_config(config_path) or Config()
            except Exception:
                config = Config()
        else:
            config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    full_model = model

    # Issue #217: DeepSeek-V4-Flash intermittently returns empty synthesis on
    # long prompts (empty content / unparseable JSON).  Retry once — a
    # probabilistic empty output usually succeeds on the second attempt —
    # before giving up and returning an empty dict (which the caller then
    # fills deterministically from the real entries).
    last: dict[str, Any] = {}
    for _attempt in range(2):
        try:
            response = call_with_fallback(
                model=full_model,
                messages=[
                    {"role": "system", "content": _DIGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                json_mode=config.llm.json_mode and not config.llm.reasoning_model,
                max_tokens=8000,
                temperature=0.1,
                api_key=config.llm.api_key or None,
                base_url=config.llm.base_url or None,
            )
        except Exception as exc:
            logger.error("LLM digest synthesis failed: %s", exc)
            break

        content: str = response.choices[0].message.content or ""
        content = fault_inject.maybe_fault_content("digest", content)
        parsed = _parse_json_response(content)
        if parsed:
            return parsed
        last = parsed
        logger.warning(
            "LLM digest synthesis returned empty/missing fields "
            "(attempt %d/2) — retrying",
            _attempt + 1,
        )

    return last


def _parse_json_response(content: str | None) -> dict[str, Any]:
    """Parse a JSON string with fallback strategies.

    1. Direct :func:`json.loads`.
    2. Extract JSON from markdown code blocks.
    3. Find the first ``{…}`` brace-delimited block.
    """
    import re  # noqa: PLC0415

    if content is None:
        logger.warning("LLM returned None content — possible json_object mode mismatch")
        return {}

    # Strategy 1 — direct
    try:
        return cast(dict[str, Any], json.loads(content))
    except json.JSONDecodeError:
        pass

    # Strategy 2 — fenced code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass

    # Strategy 3 — bare JSON object
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(0)))
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM digest response as JSON: %.200s", content)
    return {}


# ---------------------------------------------------------------------------
# Deterministic synthesis fallback (issue #217)
# ---------------------------------------------------------------------------


def _deterministic_synthesis_fallback(
    entries: list[dict[str, Any]],
    summary_prefix: str = "This digest covers",
) -> dict[str, Any]:
    """Build non-empty D1-required synthesis sections from real entries.

    Issue #217: DeepSeek-V4-Flash intermittently returns empty/missing
    synthesis fields (long prompts, empty content).  When the LLM path
    still yields nothing after the bounded retry, D1 would block the
    product for empty ``key_findings`` / ``summary`` / ``recommendations``.
    This derives those sections from the actual entry titles and summaries
    — real content, never fabricated — so the product stays complete and
    D1 passes.

    Parameters
    ----------
    entries:
        KB entry dicts used to produce the output.  Each carries at least
        ``title`` and optionally ``summary``.
    summary_prefix:
        Leading phrase for the generated executive summary (defaults to a
        digest-style phrase; reports pass ``"This report covers"``).

    Returns
    -------
    dict
        ``{"executive_summary": str, "key_findings": list[str | dict],
        "recommendations": list[str]}`` with all sections non-empty when
        entries exist.  Findings for entries that carry a ``source_url``
        are ``{"text": str, "source_url": str}`` objects (issue #279) so
        rendered output can cite per-finding provenance; entries without
        a URL keep the legacy ``"title: summary"`` string form.
    """
    titled = [e for e in entries if (e.get("title") or "").strip()]
    if not titled:
        return {
            "executive_summary": "No knowledge base entries were available.",
            "key_findings": [],
            "recommendations": [],
        }

    title_line = ", ".join(str(e["title"]).strip() for e in titled[:8])
    executive_summary = (
        f"{summary_prefix} the latest developments this period: {title_line}."
    )
    key_findings: list[Any] = []
    for e in titled[:8]:
        text = (
            f"{str(e['title']).strip()}: "
            f"{str(e.get('summary') or e['title']).strip()}"
        )
        src = str(e.get("source_url") or "").strip()
        key_findings.append({"text": text, "source_url": src} if src else text)
    recommendations = [
        f"Review the {len(titled)} knowledge base entr"
        f"{'y' if len(titled) == 1 else 'ies'} listed above for follow-up."
    ]
    return {
        "executive_summary": executive_summary,
        "key_findings": key_findings,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Source attribution (F46)
# ---------------------------------------------------------------------------


def _get_domain_source_configs(domain: str) -> list["SourceConfig"]:
    """Load SourceConfig objects for *domain* from the project config.

    Returns an empty list when the config cannot be loaded or the domain
    is not found.
    """
    config_path = get_config_path()
    if config_path is None or not config_path.is_file():
        return []
    try:
        config = load_config(config_path)
    except Exception:
        return []
    for d in config.domains:
        if d.name == domain:
            return list(d.sources)
    return []


# Generic source_platform values that carry no specific source identity (the
# #325 re-derivation replaces these with the configured source name when a
# hostname match can be made against the domain's source configs).
_GENERIC_PLATFORMS = frozenset({"", "rss", "web", "api"})

# SourceConfig types whose entries can be matched to a source by hostname.
_MATCHABLE_SOURCE_TYPES = frozenset({"rss", "web", "webhook", "api", "pdf"})


def _host_matches_source(entry_host: str, sc_host: str) -> bool:
    """True when an entry's URL host belongs to a configured source host.

    Issue #325 data layer: RSS feed URLs are often on a different host than
    the article links they carry (arXiv articles on ``arxiv.org`` vs the
    ``rss.arxiv.org`` feed), so exact-equality host matching leaves stale
    pre-#323 entries stuck on the generic ``(RSS)`` label.  Match when the
    hosts are equal or one is a subdomain of the other (``arxiv.org`` ⊂
    ``rss.arxiv.org``).  A bare substring match is rejected (``evil-arxiv.org``
    must not match ``arxiv.org``).  Pure stdlib (urllib.parse only — no
    tldextract dependency).
    """
    eh = (entry_host or "").lower().rstrip(".").lstrip("www1.").lstrip("www.")
    sh = (sc_host or "").lower().rstrip(".").lstrip("www1.").lstrip("www.")
    if not eh or not sh:
        return False
    if eh == sh:
        return True
    # Subdomain of each other (arXiv articles on arxiv.org vs the
    # rss.arxiv.org feed host) — never a bare substring (evil-arxiv.org
    # must not match arxiv.org).
    if eh.endswith("." + sh) or sh.endswith("." + eh):
        return True
    return False


def _derive_source_label(
    entry: dict[str, Any],
    domain: str,
    *,
    source_configs: list["SourceConfig"] | None = None,
) -> str:
    """Derive a specific source name for *entry* when its stored
    ``source_platform`` is a generic placeholder (``rss``/``web``/``api`` or
    empty) — issue #325.

    Pre-#323 KB entries carry ``source_platform='rss'`` even for real sources
    (TechCrunch, arXiv, 36Kr, …), so the References section rendered the
    generic ``(RSS)`` label.  The #323 collector fix only affects newly
    collected items; this re-derivation recovers the specific source name for
    existing entries by matching the entry's ``source_url`` host against the
    domain's configured source URLs.

    Returns the derived source identifier (a source config ``name``) when a
    match is found, otherwise returns the entry's stored ``source_platform``
    unchanged.  Matching is deterministic — no LLM.
    """
    platform = str(entry.get("source_platform") or "").strip()
    if platform.lower() not in _GENERIC_PLATFORMS:
        return platform
    source_url = str(entry.get("source_url") or "").strip()
    if not source_url:
        return platform
    try:
        url_host = urlsplit(source_url).hostname or ""
    except ValueError:
        return platform
    if not url_host:
        return platform
    configs = source_configs if source_configs is not None else _get_domain_source_configs(domain)
    for sc in configs:
        if sc.type not in _MATCHABLE_SOURCE_TYPES:
            continue
        sc_url = str(sc.url or "").strip()
        if not sc_url:
            continue
        try:
            sc_host = urlsplit(sc_url).hostname or ""
        except ValueError:
            continue
        # Host match (issue #325 data layer): exact or subdomain (arXiv
        # articles on arxiv.org vs the rss.arxiv.org feed host) — never a
        # bare substring.
        if _host_matches_source(url_host, sc_host):
            return sc.name.strip() or platform
    return platform


def _label_entries(entries: list[dict[str, Any]], domain: str) -> list[dict[str, Any]]:
    """Enrich each entry with a derived ``source_label`` (issue #325).

    Adds ``source_label = _derive_source_label(entry, entry.get("domain",
    domain))`` to every entry so every render surface (markdown entry table,
    magazine byline/clusters, json/agent formats) shows the specific source
    name instead of the generic ``(RSS)`` label for stale pre-#323 entries.
    Per-entry own domain is used for cross-domain products.  Returns the
    enriched list (entries are dicts, mutated in place).
    """
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry["source_label"] = _derive_source_label(
            entry, str(entry.get("domain") or domain)
        )
    return entries


def _build_attribution_footer(
    sources: list["SourceConfig"],
    output_format: str = "markdown",
) -> str:
    """Build a source attribution section for generated outputs.

    Deduplicates by URL.  Each source is formatted as::

        Source: **{name}** ({url}) — Tier {quality_tier}, {tos_classification}

    Parameters
    ----------
    sources : list[SourceConfig]
        Source configurations to attribute.  Deduplicated by URL before
        rendering.
    output_format : str
        Output format: ``"markdown"`` (default), ``"html"``, or ``"json"``.

    Returns
    -------
    str
        Formatted attribution string.  Empty string when *sources* is
        empty or contains no valid URLs.
    """
    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[SourceConfig] = []
    for s in sources:
        url = (s.url or "").strip().rstrip("/")
        if url and url not in seen:
            seen.add(url)
            unique.append(s)

    if not unique:
        return ""

    if output_format == "json":
        return json.dumps(
            [
                {
                    "name": s.name,
                    "url": s.url,
                    "quality_tier": s.quality_tier,
                    "tos_classification": s.tos_classification,
                }
                for s in unique
            ],
            indent=2,
            ensure_ascii=False,
        )

    lines: list[str] = []
    for s in unique:
        lines.append(
            f"- **{s.name}** ({s.url}) — "
            f"Tier {s.quality_tier}, {s.tos_classification}"
        )
    body = "\n".join(lines)

    if output_format == "html":
        escaped_lines = "\n".join(
            "    <li>"
            + html.escape(
                f"{s.name} ({s.url}) — "
                f"Tier {s.quality_tier}, {s.tos_classification}"
            )
            + "</li>"
            for s in unique
        )
        return (
            '<footer class="source-attribution">\n'
            f"  <h2>Source Attribution</h2>\n"
            f"  <ul>\n{escaped_lines}\n  </ul>\n"
            f"</footer>"
        )

    # Default: markdown
    return f"---\n\n## Source Attribution\n\n{body}\n"


def _normalize_column_sections(raw: Any) -> list[dict[str, Any]]:
    """Normalize the LLM ``sections`` array to ``{title, content, entries}``.

    Drops items without a usable ``title`` or ``content`` so the column
    template never renders empty subsections (issue #316).  ``entries`` is
    carried through when the LLM provides it (optional — the template
    renders an entry table only when present).
    """
    if not isinstance(raw, list):
        return []
    sections: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title or not content:
            continue
        section: dict[str, Any] = {"title": title, "content": content}
        entries = item.get("entries")
        if isinstance(entries, list):
            section["entries"] = entries
        sections.append(section)
    return sections


def _deterministic_column_sections(
    entries: list[dict[str, Any]], domain: str = ""
) -> list[dict[str, Any]]:
    """Derive column deep-dive sections deterministically from entries (#316).

    Groups entries by theme (source_type → domain → keyword, the same
    deterministic fallback the report path uses) and emits one section per
    group; when the grouping yields fewer than 8 sections but there are at
    least 8 entries, falls back to one section per entry (title + summary)
    so the column Deep Dive never renders the empty placeholder when
    entries exist.
    """
    groups = _deterministic_grouping(entries, domain=domain)
    if groups:
        sections = [
            {
                "title": str(g.get("theme") or "").strip(),
                "content": str(g.get("description") or "").strip(),
                "entries": list(g.get("entries") or []),
            }
            for g in groups
            if (str(g.get("theme") or "").strip())
        ]
        if len(sections) >= 8:
            return sections
    # One section per entry (title + summary) — real content, never
    # fabricated, and never an empty Deep Dive when entries exist.
    sections = []
    for e in entries:
        title = str(e.get("title") or "").strip()
        if not title:
            continue
        summary = str(e.get("summary") or "").strip()
        sections.append(
            {
                "title": title,
                "content": summary or title,
                "entries": [e],
            }
        )
    return sections


def _deterministic_takeaway_fields(
    entries: list[dict[str, Any]],
    domain: str = "",
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Derive premium-briefing per-takeaway implication / risk / action
    deterministically from real entries (issue #329).

    Mirrors :func:`_deterministic_column_sections`: when the LLM synthesis
    carries no (or too few) per-takeaway implication/risk/action entries,
    derive them one-per-ranked-entry from the actual KB entries so the
    premium template never renders the ``_No ..._`` empty-state placeholders.

    Issue #54 (paid review): the fallback must be HONEST, never impersonate
    real analysis.  Pre-#54 it fabricated ``Uncertain trajectory for …`` +
    ``likelihood medium / impact medium`` for every entry — indistinguishable
    from genuine LLM risk analysis and a value inversion against enterprise.
    The fallback now states plainly that NO differentiated signal was captured
    this period and rates likelihood/impact as ``n/a`` (nothing fabricated).

    Returns ``(implications, risks, action_required)`` — index-aligned lists
    (one item per entry) in the same shape the premium-briefing template
    reads.
    """
    ranked = sorted(
        (e for e in entries if isinstance(e, dict)),
        key=lambda e: float(e.get("relevance_score") or 0.0),
        reverse=True,
    )
    implications: list[str] = []
    risks: list[dict[str, Any]] = []
    action_required: list[str] = []
    for e in ranked:
        title = str(e.get("title") or "this topic").strip()
        if not title:
            continue
        url = str(e.get("source_url") or "").strip()
        implications.append(
            f"No differentiated signal captured for {title} this period — "
            "revisit next period for follow-up developments."
        )
        risks.append(
            {
                "title": "No differentiated risk signal this period — "
                "revisit next period.",
                "likelihood": "n/a",
                "impact": "n/a",
                "mitigation": (
                    "Revisit next period and validate against additional "
                    "sources before rating."
                ),
            }
        )
        action_required.append(
            f"Revisit {title} ({url}) next period for a differentiated "
            "assessment."
        )
    return implications, risks, action_required


def _fill_premium_takeaway_fields(
    implications: list[Any] | None,
    risks: list[dict[str, Any]] | None,
    action_required: list[str] | None,
    entries: list[dict[str, Any]],
    domain: str,
    *,
    weak: bool = False,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """#357 — the premium per-takeaway slots must never render empty or
    ``_No ..._`` placeholder text.  A slot list that is missing/empty is
    filled with the full deterministic fallback; a non-empty list has its
    empty/placeholder-shaped elements replaced per-index.  The list length
    the LLM produced is preserved (no padding) so product-analysis
    persistence stays faithful to the raw synthesis.

    #10 — the opt-in *weak* predicate (default False keeps the ``_usable``
    behavior) additionally replaces weak-but-non-empty action lines: a bare
    verb phrase like ``"Track AI model releases"`` (no concrete object, no
    timeframe/trigger) is flagged by :func:`autoinfo.validation_matrix._is_weak_analysis`
    and swapped per-index for the KB-derived deterministic action, so the
    premium render ships WHAT/WHEN-shaped actions even when the LLM falls
    back to shallow phrasing.  Scope: PREMIUM-ONLY — the enterprise
    ``action_required`` is a flat ``- [ ]`` checkbox list whose shape
    ``_so_what_substantive`` requires, so enterprise callers never pass
    ``weak=True`` (their lever is the prompt-side WHAT/WHEN constraint).

    The validation_matrix import is FUNCTION-LOCAL because
    ``validation_matrix`` imports ``from autoinfo.output import …`` at
    function scope (lines 124/1044/1084 of that module) — a module-level
    ``output → validation_matrix`` import would be a hard cycle.
    """
    from autoinfo.validation_matrix import _is_weak_analysis  # noqa: PLC0415

    _impl, _risks, _actions = _deterministic_takeaway_fields(entries, domain)

    def _usable(value: Any) -> bool:
        if isinstance(value, dict):
            return _usable(value.get("title"))
        if not isinstance(value, str):
            return False
        stripped = value.strip()
        return bool(stripped) and not _is_empty_placeholder(stripped)

    def _is_weak(value: Any) -> bool:
        """Weak when unusable, or (with *weak* enabled) a weak-shaped action."""
        if not _usable(value):
            return True
        if not weak:
            return False
        if isinstance(value, dict):
            return _is_weak_analysis(str(value.get("title") or ""))
        return _is_weak_analysis(str(value))

    def _fill(
        values: list[Any] | None,
        fallback: list[Any],
        is_dict: bool = False,
    ) -> list[Any]:
        values = list(values) if values else []
        if not values:
            return [dict(v) for v in fallback] if is_dict else list(fallback)
        if is_dict:
            return [
                dict(v) if isinstance(v, dict) and not _is_weak(v) else dict(fallback[i])
                for i, v in enumerate(values[: len(fallback)])
            ]
        return [
            (str(v).strip() if not _is_weak(v) else fallback[i])
            for i, v in enumerate(values[: len(fallback)])
        ]

    return (
        _fill(implications, _impl),
        _fill(risks, _risks, is_dict=True),
        _fill(action_required, _actions),
    )


def _normalize_digest_product_context(
    context: dict[str, Any],
    domain: str,
    product_family: str = "digest",
    ref_limit: int | None = None,
) -> dict[str, Any]:
    """Normalize the digest context to the flat §2.1 product-template shape.

    The digest path renders product templates with a context that nests the
    LLM synthesis under ``llm_synthesis``; product templates
    (``premium-briefing`` / ``enterprise-briefing`` / ``magazine-digest``)
    read only the FLAT keys pinned by ``phaseA-template-spec.md`` §2.1 —
    the same shape the report path produces via :func:`_report_data_to_dict`.
    This flattens the digest context to that dual-context contract:

    - ``executive_summary`` ← ``llm_synthesis["executive_summary"]``
      (``""`` when absent)
    - ``key_findings`` ← ``llm_synthesis["key_findings"]`` converted to
      ``list[dict]`` of ``{"text", "source_url"}`` (LLM ``{topic, detail}``
      dicts become ``"topic: detail"`` text; partial items kept, empty
      items dropped; ``source_url`` kept when the LLM provides it and
      back-filled from the entry list on an unambiguous title match —
      issue #279)
    - ``recommendations`` ← ``llm_synthesis["recommendations"]``
    - ``references`` ← derived from ``entries`` with the report-path item
      shape ``{title, source_url, source_type, source_platform, domain}``
      (spec §2.3 rule 4; ``entry.get("domain", <domain>)`` fallback)
    - product-specific fields (todo 7): ``implications``, ``risks``,
      ``action_required``, ``key_metrics`` ← flattened from
      ``llm_synthesis`` when present, else ``[]`` — generic, so any new
      synthesis field flows through automatically
    - ``sections`` (issue #316): the column template's Deep Dive source —
      flattened from ``llm_synthesis["sections"]`` when present (list of
      ``{title, content, entries}`` dicts, unusable items dropped); when
      *product_family* is ``"column"`` and no usable sections exist but
      entries do, sections are derived deterministically from the entries
      so the template never renders the empty placeholder.  Non-column
      families default to ``[]`` (backward compatible).

    All other top-level digest keys (``title``, ``domain``, ``generated_at``,
    ``period``, ``entries``, …) are kept untouched — templates must simply
    not read them (spec §2.3 rule 6).
    """
    synthesis_raw = context.get("llm_synthesis")
    synthesis = synthesis_raw if isinstance(synthesis_raw, dict) else {}
    raw_entries = context.get("entries")
    entries_list = raw_entries if isinstance(raw_entries, list) else []

    # --- Flattened top-level keys ------------------------------------------
    flat: dict[str, Any] = dict(context)
    flat["executive_summary"] = str(synthesis.get("executive_summary") or "")

    raw_findings = synthesis.get("key_findings", [])
    findings: list[dict[str, Any]] = []
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    findings.append({"text": text})
                continue
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if topic and detail:
                text = f"{topic}: {detail}"
            elif topic:
                text = topic
            elif detail:
                text = detail
            elif item.get("text"):
                text = str(item["text"]).strip()
            else:
                continue
            finding: dict[str, Any] = {"text": text}
            src = str(item.get("source_url") or "").strip()
            if src:
                finding["source_url"] = src
            findings.append(finding)
    # Issue #279: back-fill source_url from entries on an unambiguous
    # title match only (wrong attribution is worse than none).
    for finding in findings:
        if finding.get("source_url"):
            continue
        text = str(finding.get("text") or "").strip().lower()
        if not text:
            continue
        tokens = [t for t in re.split(r"[^a-z0-9]+", text.split(":")[0]) if t]
        if len(tokens) < 2:
            continue
        matches = [
            e.get("source_url")
            for e in entries_list
            if isinstance(e, dict)
            and (e.get("source_url") or "").strip()
            and all(t in str(e.get("title") or "").lower() for t in tokens)
        ]
        if len(matches) == 1:
            finding["source_url"] = str(matches[0]).strip()
    flat["key_findings"] = findings

    raw_recommendations = synthesis.get("recommendations", [])
    flat["recommendations"] = (
        raw_recommendations if isinstance(raw_recommendations, list) else []
    )

    # --- References derived from entries (report-path item shape) ----------
    # #325: derive the specific source label for entries whose stored
    # source_platform is a generic placeholder (pre-#323 'rss' etc.).
    # #11: cap at ref_limit, sorted by (has summary, relevance) desc — the
    # sort MUST run on the entries BEFORE the ref dicts drop summary/relevance.
    _ref_limit = ref_limit if ref_limit is not None else _output_config_ref_limit()
    _src_configs = _get_domain_source_configs(domain)
    flat["references"] = []
    for e in _sorted_ref_entries(
        [e for e in entries_list if isinstance(e, dict)], domain=domain
    )[:_ref_limit]:
        _label = _derive_source_label(
            e, e.get("domain", domain), source_configs=_src_configs,
        )
        flat["references"].append({
            "title": e.get("title", ""),
            "source_url": e.get("source_url", ""),
            "source_type": e.get("source_type", ""),
            "source_platform": _label,
            "domain": e.get("domain", domain),
            "description": (
                str(e.get("summary") or "").strip()
                or str(e.get("content") or "")[:120].strip()
                or f"{_label} item"
            ),
        })

    # --- Enterprise/premium key_findings cap (issue #11, decision a) ------
    # The enterprise-briefing template renders the selection-scope label
    # ``selected {{ key_findings|length }} of {{ references|length }}``.  Cap
    # the findings to min(12, len(references)) for the premium/enterprise
    # families so a ref_limit below the findings count can never invert the
    # label (``selected 9 of 8``).
    if product_family in ("premium-briefing", "enterprise-briefing"):
        flat["key_findings"] = _cap_product_key_findings(
            flat["key_findings"], flat["references"]
        )

    # --- Product-specific fields (todo 7), flattened generically ----------
    # List-shaped fields flow through as-is; string-shaped editorial fields
    # (editorial_intro / feature_story, issue #313) carry through as strings.
    for synthesis_field in (
        "implications",
        "risks",
        "action_required",
        "key_metrics",
        "editorial_intro",
        "feature_story",
    ):
        value = synthesis.get(synthesis_field, [])
        flat[synthesis_field] = (
            value if isinstance(value, list) else (str(value) if isinstance(value, str) else [])
        )

    # --- Deterministic per-takeaway fields (issue #329) --------------------
    # premium-briefing's takeaway layer renders per-takeaway implication /
    # risk / action by index-aligning with key_findings.  When the LLM
    # synthesis carries none (or fewer than the takeaways) OR slot values that
    # are empty / `_No ..._` placeholder-shaped, the template's `{% else %}`
    # empty-state renders `_No ..._` placeholders.  Backfill each slot
    # per-index with the deterministic fallback derived from the real entries
    # so the premium product never ships a hollow Action/Risk/So-what (same
    # pattern as #316/#326 column sections; placeholder-element case #357).
    if product_family == "premium-briefing" and entries_list:
        flat["implications"], flat["risks"], flat["action_required"] = (
            _fill_premium_takeaway_fields(
                flat.get("implications"), flat.get("risks"),
                flat.get("action_required"), entries_list, domain,
            )
        )

    # --- Column deep-dive sections (issue #316) ---------------------------
    # The column template renders ``sections`` (list of {title, content,
    # entries}) for the Deep Dive + Implications sections.  Flatten the LLM
    # synthesis ``sections`` array when present; when the family is column
    # and no usable sections exist but entries do, derive them
    # deterministically so the template never renders the empty placeholder.
    sections = _normalize_column_sections(synthesis.get("sections"))
    if product_family in ("column", "report") and not sections and entries_list:
        # #326: derive sections deterministically for the report family too
        # (previously only "column" got a deterministic fallback, so the
        # report product rendered `**Sections**: 0` + an empty shell whenever
        # the LLM synthesis carried no explicit sections).
        sections = _deterministic_column_sections(entries_list, domain)
    flat["sections"] = sections

    # --- Tutorial sections (issue #342) -----------------------------------
    # The digest path renders the tutorial template (the matrix generates
    # tutorial via generate_digest with the tutorial template).  The flat
    # context carries no objectives/content/exercises/further_reading keys,
    # so the template's ``{% else %}`` branches render ``_No objectives
    # defined._`` / ``_No exercises provided._`` / ``_No references
    # provided._``.  Fill them from the real entries via the same
    # ``_entry_derived_sections`` helper the real ``generate_tutorial``
    # uses; when there are no entries, leave them empty and let the
    # template's neutral prose render (never a placeholder).
    if product_family == "tutorial":
        if entries_list:
            _objectives, _content, _exercises, _further = _entry_derived_sections(
                entries_list
            )
        else:
            _objectives, _content, _exercises, _further = [], [], [], []
        flat.setdefault("objectives", _objectives)
        flat.setdefault("content", _content)
        flat.setdefault("exercises", _exercises)
        flat.setdefault("further_reading", _further)

    return flat


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_digest(
    domain: str,
    period: str = "weekly",
    format: str = "markdown",
    llm_config: Config | None = None,
    custom_instructions: str = "",
    target_audience: str = "",
    include_stale: bool = False,
    recipients: list[str] | None = None,
    product_template: ProductTemplate | None = None,
    product_type: str = "PROCESSED",
    delivery_gate_configs: dict[str, dict[str, Any]] | _DeliveryGatesBypass | None = None,
    user_id: str = "",
    max_items: int = 0,
    domains: list[str] | None = None,
    language: str = "",
    ref_limit: int | None = None,
) -> str | DeliveryOutput:
    """Generate a digest of KB entries for *domain* over the given *period*.

    When *domains* is provided with 2+ entries, entries are aggregated
    from all listed domains for a cross-domain digest.

    Parameters
    ----------
    domain:
        Domain to generate the digest for (e.g. ``"medical-research"``).
    period:
        Digest period.  One of ``"daily"``, ``"weekly"``, ``"monthly"``.
        Defaults to ``"weekly"``.
    format:
        Output format.  One of ``"markdown"``, ``"html"``, ``"json"``,
        ``"agent"``.  The ``"agent"`` format returns JSON-LD
        (``@type: KnowledgeDigest``) optimized for LLM re-consumption.
        Defaults to ``"markdown"``.
    llm_config:
        Optional :class:`Config` override for LLM settings.  When omitted,
        the config is auto-detected from the project directory.
    custom_instructions:
        Optional string of additional instructions to append to the LLM
        generation prompt.  Ignored when empty/absent.
    include_stale:
        When ``True``, include stale entries (below domain freshness
        threshold) in the digest.  Defaults to ``False``, which excludes
        them and logs the count of excluded items.
    recipients:
        Optional list of email recipient addresses for direct delivery.
        When provided, the digest can be sent to these addresses via
        the delivery channel.  Defaults to ``None``.
    product_template:
        Optional :class:`ProductTemplate` instance for template rendering.
        When provided, the digest is rendered through the product template
        system (with domain-specific overrides).  When ``None`` (default),
        the existing direct Jinja2 rendering is used (backward compatible).
    product_type:
        Product type for delivery gate checking.  ``"PROCESSED"`` (default)
        enables D1-D3 checks when *delivery_gate_configs* is provided.
        ``"RAW"`` skips all delivery gates.
    delivery_gate_configs:
        Optional dict of ``{gate_name: config_dict}`` for D1-D3 delivery
        gates.  When provided, D1-D3 are run after rendering and the return
        type changes to :class:`DeliveryOutput`.  When ``None`` (default),
        no gates are run and a plain ``str`` is returned (backward
        compatible).
    user_id:
        Optional user ID.  When non-empty, stored preferences from
        :func:`autoinfo.user_store.get_preferences` are auto-loaded and
        used to set *target_audience*, *format*, and *max_items* if they
        were not explicitly provided.  When empty (default), behavior is
        unchanged and no preferences are loaded.
    max_items:
        Optional maximum number of KB entries to include in the digest.
        Defaults to ``0`` (uses built-in limit of 200).  When *user_id*
        is provided and the user's stored preferences include a
        ``max_items`` key, that value is used instead.
    language:
        Optional ISO-639 language code (``"zh"`` / ``"en"``, case/alias
        tolerant: ``zh_CN``, ``中文``, ``en-US`` all match).  When provided,
        only entries whose detected ``language`` matches are included, so a
        digest never mixes languages (issue #309).  Empty (default) includes
        all languages as before.
    ref_limit:
        Optional maximum number of KB references to include in the rendered
        product.  Defaults to ``output.ref_limit`` from the project config
        (60).  Applied at the digest product-context build
        (:func:`_normalize_digest_product_context`), sorted by (has non-empty
        summary desc, ``relevance_score`` desc) — identical to the report
        path (issue #11).

    Returns
    -------
    str or DeliveryOutput
        Plain ``str`` when *delivery_gate_configs* is ``None`` (default).
        :class:`DeliveryOutput` with gate results when *delivery_gate_configs*
        is provided.

    Raises
    ------
    ValueError
        If *period* is not one of ``"daily"``, ``"weekly"``, ``"monthly"``,
        or if *format* is not one of ``"markdown"``, ``"html"``, ``"json"``,
        ``"agent"``, ``"epub"``, ``"audiobook"``.
    """
    # --- Validate parameters ------------------------------------------------
    if period not in PERIOD_DAYS:
        raise ValueError(
            f"Invalid period '{period}'. Must be one of: {', '.join(sorted(PERIOD_DAYS))}"
        )
    valid_formats = {"markdown", "html", "json", "agent", "audio", "epub", "audiobook"}
    if format not in valid_formats:
        raise ValueError(
            f"Invalid format '{format}'. Must be one of: {', '.join(sorted(valid_formats))}"
        )

    # --- Resolve delivery-gate config (issue #298: default-on in production) --
    # ``None`` resolves from the project config (domain ``delivery_gates`` /
    # global ``delivery_gates``); the ``_DELIVERY_GATES_BYPASS`` sentinel
    # explicitly bypasses.  When resolution yields nothing, the caller keeps
    # getting a plain ``str`` (backward compatible).
    delivery_gate_configs = _resolve_delivery_gate_configs(domain, delivery_gate_configs)

    # --- Determine cross-domain mode -----------------------------------------
    is_cross_domain_digest: bool = domains is not None and len(domains) >= 2
    if is_cross_domain_digest:
        digest_domains: list[str] = domains  # type: ignore[assignment]
        digest_title_domain: str = "Cross-Domain"
    else:
        digest_domains = [domain]
        digest_title_domain = domain

    # --- Auto-load preferences from user profile (G10) -----------------------
    content_preference: str = _resolve_content_preference(user_id)
    if user_id:
        try:
            from autoinfo.user_store import (  # noqa: PLC0415
                get_preferences,
            )
            prefs_result = get_preferences(user_id)
            if "preferences" in prefs_result:
                stored_prefs: dict[str, Any] = prefs_result["preferences"]
                # Auto-set target_audience if not explicitly provided
                if not target_audience and stored_prefs.get("target_audience"):
                    target_audience = str(stored_prefs["target_audience"])
                    logger.debug(
                        "Applied stored target_audience='%s' for user '%s'",
                        target_audience,
                        user_id,
                    )
                # Auto-set format if still at default
                if format == "markdown" and stored_prefs.get("format"):
                    stored_fmt = str(stored_prefs["format"]).lower()
                    if stored_fmt in valid_formats:
                        format = stored_fmt
                        logger.debug(
                            "Applied stored format='%s' for user '%s'",
                            format,
                            user_id,
                        )
                # Auto-set max_items if not explicitly provided
                if max_items == 0 and stored_prefs.get("max_items"):
                    try:
                        max_items = int(stored_prefs["max_items"])
                        if max_items < 1:
                            max_items = 0
                        logger.debug(
                            "Applied stored max_items=%d for user '%s'",
                            max_items,
                            user_id,
                        )
                    except (ValueError, TypeError):
                        pass
        except Exception:
            logger.debug(
                "Failed to load preferences for user '%s'",
                user_id,
                exc_info=True,
            )

    # --- Freemium access gating (G15) ----------------------------------------
    if user_id and product_template is not None:
        product_access = getattr(product_template, "access_level", "free")
        if product_access != "free":
            from autoinfo.billing import check_access  # noqa: PLC0415

            access_result = check_access(user_id, product_access)
            if not access_result["allowed"]:
                period_label = PERIOD_LABELS.get(period, period.capitalize())
                blocked_message = (
                    f"# {period_label} Digest \u2014 {domain}\n\n"
                    f"**{access_result['upgrade_prompt'] or 'Access denied.'}**\n\n"
                    f"_Reason_: {access_result['reason']}\n\n"
                    f"_Access level required_: `{product_access}`\n"
                    f"_Your status_: {access_result['profile_status']} "
                    f"(plan: {access_result['plan']})\n"
                )
                if delivery_gate_configs is not None:
                    return DeliveryOutput(
                        output=blocked_message,
                        gate_results={},
                        delivery_blocked=True,
                        delivery_format=format,
                        warnings=[f"G15 blocked: {access_result['reason']}"],
                    )
                return blocked_message

    # --- Compute date range --------------------------------------------------
    date_from, date_to = _compute_date_range(period)
    period_label = PERIOD_LABELS.get(period, period.capitalize())

    # --- Query KB entries ----------------------------------------------------
    store = KBStore()
    query_limit = max_items if max_items > 0 else 200

    if is_cross_domain_digest:
        entries: list[dict[str, Any]] = []
        per_domain_limit = max(query_limit // len(digest_domains), 10)
        for d in digest_domains:
            domain_entries = store.list_entries(
                domain=d,
                date_from=date_from,
                limit=per_domain_limit,
            )
            for e in domain_entries:
                if "domain" not in e:
                    e["domain"] = d
            entries.extend(domain_entries)
        entries = entries[:query_limit]
        period_was_empty = False
    else:
        period_entries = store.list_entries(
            domain=domain,
            date_from=date_from,
            limit=query_limit,
        )
        period_was_empty = not period_entries
        entries = period_entries
        # Data-staleness fallback: when no entry falls inside the period
        # window (e.g. collectors last ran weeks ago), the digest would be
        # an empty shell — unacceptable for a paying end user.  Relax the
        # date filter to the full domain set so the product still delivers
        # content (2026-08-11: online-education had 8 entries, all
        # collected 2026-07-2x, weekly window 08-04..08-11 → 0 entries →
        # empty digest/json/agent shells).
        if not entries:
            logger.info(
                "No entries for domain '%s' in period %s..%s — falling "
                "back to full domain set",
                domain, date_from, date_to,
            )
            entries = store.list_entries(
                domain=domain,
                limit=query_limit,
            )

    # --- Archive/deprecated exclusion ----------------------------------------
    digest_active: list[dict[str, Any]] = []
    for entry in entries:
        cf = entry.get("custom_fields") or "{}"
        try:
            cf_dict = json.loads(cf) if isinstance(cf, str) else dict(cf)
        except (json.JSONDecodeError, TypeError):
            cf_dict = {}
        if cf_dict.get("status") in ("archived", "deprecated"):
            continue
        digest_active.append(entry)
    entries = digest_active

    # --- Test/empty entry filtering (issue #298 — layer 1) -------------------
    # Drop empty/test/placeholder entries BEFORE synthesis and BEFORE render so
    # both the LLM input and the rendered body are clean.  Real Draft/Wiki
    # entries with an empty DB summary but file content are first enriched
    # (issue #326) so their column Deep Dive / report Sections are never an
    # empty shell from real KB data.
    entries = _filter_product_entries(_enrich_product_entries(entries))
    # Near-duplicate convergence (issue #69): collapse same-event entries
    # that char-level G2 dedup could not see (cross-language) BEFORE the
    # language filter so a cross-language cluster converges to one rep.
    entries = _converge_near_duplicates(entries)

    # --- Language filter (issue #309 / #317) --------------------------------
    # When a user requests a specific language (or a domain declares a
    # default_language), drop entries in other languages so a digest/report is
    # internally consistent (no zh/en interleave).  An explicit param wins;
    # otherwise the domain default fills in; cross-domain never auto-picks one.
    effective_language = _resolve_effective_language(
        language, domain, cross_domain=is_cross_domain_digest
    )
    if effective_language:
        filtered_entries, collapsed = _filter_entries_by_language_product_safe(
            entries, effective_language
        )
        if collapsed:
            # Issue #53: the resolved language collapsed the domain's primary
            # corpus (stale seed/config), the safety net already fell back to
            # the unfiltered input and logged — use it as-is.
            entries = filtered_entries
        else:
            if (
                not filtered_entries
                and entries
                and not period_was_empty
                and not is_cross_domain_digest
            ):
                # The period window held entries in OTHER languages while the
                # domain's default-language corpus is fully out-of-window (e.g. a
                # zh domain whose people.cn corpus is dated months ago + fresh en
                # in-window).  Relax the DATE window (keep the language filter) so
                # the digest is never an empty shell (backup-repo #28 evidence).
                logger.info(
                    "No '%s'-language entries in the '%s' window for domain '%s' "
                    "- relaxing the date window, keeping the language filter",
                    effective_language, period, domain,
                )
                relaxed = store.list_entries(domain=domain, limit=query_limit)
                if relaxed:
                    filtered_entries = _filter_entries_by_language(
                        relaxed, effective_language
                    )
            entries = filtered_entries

    # --- Per-domain exclude_keywords filter (issue #319) ---------------------
    # Cross-domain noise guard: drop entries whose title/summary/tags match a
    # keyword on the entry's OWN domain's exclude_keywords blacklist BEFORE LLM
    # synthesis.  Deterministic substring match, no LLM involvement.  No-op for
    # domains with an empty list.
    entries = _filter_entries_by_domain_exclusions(entries, domain)

    # --- Source-label enrichment (issue #325) --------------------------------
    # Derive the specific source name for every entry (stale pre-#323 entries
    # carry source_platform='rss') so ALL render surfaces — markdown entry
    # table, magazine byline/clusters, json/agent formats — show the specific
    # source name instead of the generic "(RSS)" label.  Per-entry own domain
    # for cross-domain products.
    entries = _label_entries(entries, domain)

    # --- Parse tags for each entry (they come as JSON strings from SQLite) ----
    for entry in entries:
        tags_raw = entry.get("tags", "")
        if isinstance(tags_raw, str):
            try:
                entry["tags"] = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                entry["tags"] = [tags_raw] if tags_raw else []
        elif not isinstance(tags_raw, list):
            entry["tags"] = []

    # --- Promotion trigger (T6): promote eligible 02-Draft entries ------------
    # Best-effort per entry: a rejected/failed promotion never blocks the
    # digest (rejections are expected — they stay in 02-Draft with a
    # _failed/ marker).
    _promote_eligible_drafts(
        store, digest_domains if is_cross_domain_digest else [domain], caller="digest"
    )

    # --- Content-preference tier filtering (B-001) ---------------------------
    if content_preference != "both":
        filtered_entries = _filter_entries_by_content_preference(
            entries, content_preference
        )
        if len(filtered_entries) != len(entries):
            logger.info(
                "Excluded %d entries from digest for domain '%s' "
                "due to content_preference='%s'",
                len(entries) - len(filtered_entries),
                domain,
                content_preference,
            )
        entries = filtered_entries

    # --- Stale filtering (F51) -----------------------------------------------
    excluded_stale_count = 0
    if not include_stale:
        # Resolve domain-specific TTL and freshness threshold from config.
        ttl_days = 90
        freshness_threshold = 0.5
        try:
            from autoinfo.config import get_config_path, load_config  # noqa: PLC0415

            config_path = get_config_path()
            if config_path and config_path.is_file():
                cfg = load_config(config_path)
                for dc in cfg.domains:
                    if dc.name == domain:
                        ttl_days = dc.ttl_days
                        freshness_threshold = dc.freshness_threshold
                        break
        except Exception:
            pass

        from autoinfo.kb import calculate_freshness_score  # noqa: PLC0415

        active_entries: list[dict[str, Any]] = []
        for entry in entries:
            entry_freshness = calculate_freshness_score(entry, ttl_days)
            entry["freshness_score"] = round(entry_freshness, 4)
            if entry_freshness < freshness_threshold:
                entry["is_stale"] = True
                excluded_stale_count += 1
            else:
                entry["is_stale"] = False
                active_entries.append(entry)

        if excluded_stale_count > 0:
            logger.info(
                "Excluded %d stale entries from digest for domain '%s'",
                excluded_stale_count,
                domain,
            )
        entries = active_entries

    # --- Stale-source guard (backup issue #52) --------------------------------
    if not include_stale and excluded_stale_count > 0 and not entries:
        stale_count = excluded_stale_count
        stale_msg = (
            f"All candidate entries for domain '{domain}' are stale "
            f"(excluded {stale_count} entr{'y' if stale_count == 1 else 'ies'} "
            f"older than the freshness threshold). "
            f"Refusing to generate an empty-shell product. "
            f"Re-run collection to refresh the source, or pass include_stale=true."
        )
        if delivery_gate_configs is not None:
            return DeliveryOutput(
                output="",
                gate_results={},
                delivery_blocked=True,
                delivery_format=format,
                warnings=[f"STALE_SOURCE: {stale_msg}"],
            )
        raise StaleSourceError(stale_msg)

    # --- LLM synthesis -------------------------------------------------------
    # Resolve the product template family up front (spec §2.4, todo 7) so the
    # synthesis prompt can request the product-specific fields; the render
    # site below reuses this resolution. Agent format is content-equivalent
    # to markdown, so its family resolves against the markdown template file
    # (todo 22) — otherwise premium-briefing/enterprise-briefing agent output
    # would never request the per-product synthesis fields.
    variant = FORMAT_TO_VARIANT.get(format, format)
    family_variant = "md" if variant == "agent" else variant
    digest_family = (
        _resolve_digest_product_type(product_template, family_variant)
        if product_template is not None
        else "digest"
    )
    llm_synthesis: dict[str, Any] = {}
    if entries:
        # Issue #46: prune the LLM-synthesis candidate list the same way #42
        # prunes References — low-value promo/obituary/celebrity entries must
        # not reach the Executive Summary's leading enumeration.  Clean
        # entries always stay; flagged entries are dropped for non-language
        # domains with >= _REF_LOW_VALUE_MIN_REAL_ENTRIES clean candidates and
        # demoted to the tail otherwise (language-learning keeps them as
        # teaching material).  Deterministic, no LLM.  The full *entries* list
        # still flows to References unchanged below.
        synthesis_entries = _sorted_ref_entries(entries, domain=domain)
        prompt = _build_digest_llm_prompt(
            synthesis_entries, product_family=digest_family
        )
        if custom_instructions:
            prompt += f"\n\nAdditional instructions: {custom_instructions}"
        audience = _normalize_report_audience(target_audience)
        audience_prompt = _REPORT_AUDIENCE_PROMPTS.get(audience, "")
        if audience_prompt:
            prompt += f"\n\n{audience_prompt}"
        llm_synthesis = _call_llm_for_digest(prompt, config=llm_config)
    else:
        llm_synthesis = {}

    # Issue #217: if the LLM synthesis is empty or missing the D1-required
    # sections (intermittent empty output on long prompts), fall back to a
    # deterministic synthesis derived from the real entries so the product
    # stays complete and D1 never blocks it for empty sections.
    if entries and not (
        (llm_synthesis.get("executive_summary") or "").strip()
        and llm_synthesis.get("key_findings")
        and llm_synthesis.get("recommendations")
    ):
        llm_synthesis = _deterministic_synthesis_fallback(entries)

    # --- Build template context ----------------------------------------------
    generated_at = datetime.now(timezone.utc).isoformat()
    # Issue #318: the H1 product word follows the resolved product family
    # (digest/report/premium-briefing/column/magazine-digest/enterprise-briefing)
    # instead of being hardcoded to "Digest"; the period label still drives
    # the Daily/Weekly/Monthly prefix.  The default digest family keeps the
    # historical "{period_label} Digest — {domain}" title byte-identical.
    digest_h1_word = _product_h1_word(digest_family)
    context = {
        "title": f"{period_label} {digest_h1_word} \u2014 {digest_title_domain}",
        "domain": digest_title_domain,
        "period": period,
        "period_label": period_label,
        "date_from": date_from,
        "date_to": date_to,
        "generated_at": generated_at,
        "entries": entries,
        "llm_synthesis": llm_synthesis,
        "target_audience": target_audience,
        "source_tier_badge": _source_tier_badge_enabled(),
    }

    # --- Render --------------------------------------------------------------
    if format == "agent":
        # Product templates only carry markdown variants, so agent format
        # always renders the JSON-LD payload — which surfaces the
        # per-product synthesis fields when present (todo 22).
        rendered = _render_agent_json(entries, context)
        # Persist the per-product analysis fields to the linked KB entries
        # (todo 24) — no-op when the synthesis carries no product fields.
        _persist_product_analysis_to_kb(store, entries, llm_synthesis)
    elif product_template is not None:
        product_type = digest_family
        pt_context = _normalize_digest_product_context(
            context, domain, product_family=digest_family, ref_limit=ref_limit,
        )
        rendered = product_template.render(product_type, variant, pt_context)
        rendered = _clean_skeleton_placeholders(rendered)
    elif format == "json":
        rendered = _render_json(context)
    elif format == "html":
        rendered = _render_digest_html(context)
    elif format == "audio":
        markdown_text = _render_markdown(context)
        mp3_bytes = _render_audio(markdown_text)
        rendered = base64.b64encode(mp3_bytes).decode("ascii")
    elif format in ("epub", "audiobook"):
        from autoinfo.output.ebook import render_audiobook, render_epub  # noqa: PLC0415

        ebook_chapters = _digest_chapters(context)
        if format == "epub":
            ebook_result = render_epub(
                title=str(context.get("title", "AutoInfo Digest")),
                author="AutoInfo",
                lang="en",
                chapters=ebook_chapters,
            )
        else:
            ebook_result = render_audiobook(ebook_chapters)
        rendered = ebook_result["data_b64"]
    else:
        rendered = _render_markdown(context)

    # --- Source attribution (F46) ------------------------------------------
    if is_cross_domain_digest:
        all_src_configs_d: list[Any] = []
        for d in digest_domains:
            all_src_configs_d.extend(_get_domain_source_configs(d))
        src_configs = all_src_configs_d
    else:
        src_configs = _get_domain_source_configs(domain)
    if src_configs and entries:
        entry_urls = {
            (e.get("source_url") or "").strip().rstrip("/")
            for e in entries
            if e.get("source_url")
        }
        used_sources = [
            s for s in src_configs
            if (s.url or "").strip().rstrip("/") in entry_urls
        ]
        if used_sources:
            attribution = _build_attribution_footer(used_sources, format)
            if attribution:
                if format in ("json", "agent"):
                    try:
                        data = json.loads(rendered)
                        data["sources"] = json.loads(
                            _build_attribution_footer(used_sources, "json")
                        )
                        rendered = json.dumps(
                            data, indent=2, ensure_ascii=False, default=str
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    # Text formats get a plain attribution footer. Binary
                    # formats (audio/epub/audiobook) carry base64 payloads —
                    # appending text would corrupt the base64 and make
                    # b64decode fail with "string argument should contain
                    # only ASCII characters" (F46 regression, 2026-08-11).
                    if format not in ("audio", "epub", "audiobook"):
                        rendered = rendered.rstrip() + "\n\n" + attribution

    # --- Record consumption event (CD-018) -----------------------------------
    if user_id:
        try:
            from autoinfo.consumption import ConsumptionStore  # noqa: PLC0415

            ConsumptionStore().record_event(
                user_id=user_id,
                product_type="digest",
                product_id=f"{digest_title_domain}-{period}",
                event_type="delivered",
                metadata={
                    "domain": digest_title_domain,
                    "period": period,
                    "format": format,
                    "entries_count": len(entries),
                    "stale_excluded": excluded_stale_count if not include_stale else 0,
                },
            )
        except Exception:
            logger.warning(
                "Failed to record consumption event for user '%s'",
                user_id,
                exc_info=True,
            )

    # --- Delivery gates (D1-D3) ---------------------------------------------
    if delivery_gate_configs is not None:
        result = _apply_delivery_gates(
            rendered_output=rendered,
            output_format=format,
            entries=entries,
            context=context,
            product_type=product_type,
            delivery_gate_configs=delivery_gate_configs,
            fallback_render_fn=lambda: _render_markdown(context),
            llm_config=llm_config,
        )
        result = _apply_min_content_guard(result, entries, product_type)
        if user_id:
            _try_notify_content_ready(
                user_id=user_id,
                product_type="digest",
                title=f"{period_label} {digest_h1_word} \u2014 {digest_title_domain}",
            )
        _fire_agent_notification(
            "new_digest",
            result.output if isinstance(result, DeliveryOutput) else rendered,
            product_id=f"{digest_title_domain}-{period}",
        )
        return result

    if user_id:
        _try_notify_content_ready(
            user_id=user_id,
            product_type="digest",
            title=f"{period_label} {digest_h1_word} \u2014 {digest_title_domain}",
        )
    _fire_agent_notification(
        "new_digest", rendered, product_id=f"{digest_title_domain}-{period}"
    )
    return rendered


# ---------------------------------------------------------------------------
# Report generation — structured Jinja2 + LLM reports from KB entries
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "templates" / "report.md.j2"


@dataclass
class ReportSection:
    """A single themed section within a report."""

    title: str
    content: str
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReportData:
    """Full report data passed to the Jinja2 template."""

    title: str
    generated_at: str
    domain: str
    collection_id: str = ""
    executive_summary: str = ""
    key_findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    action_required: list[str] = field(default_factory=list)
    key_metrics: list[dict[str, Any]] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    appendices: list[dict[str, Any]] = field(default_factory=list)


def generate_report(
    domain: str,
    collection_id: str | None = None,
    format: str = "markdown",
    period: str = "weekly",
    custom_instructions: str = "",
    target_audience: str = "",
    product_template: ProductTemplate | None = None,
    product_type: str = "PROCESSED",
    delivery_gate_configs: dict[str, dict[str, Any]] | _DeliveryGatesBypass | None = None,
    user_id: str = "",
    report_type: str = "standard",
    domains: list[str] | None = None,
    llm_config: Config | None = None,
    language: str = "",
    ref_limit: int | None = None,
) -> str | DeliveryOutput:
    """Generate a structured report for the given *domain* (or *domains*).

    Groups KB entries by theme using an LLM, produces an executive
    summary, and renders the result through the Jinja2 report template.

    Parameters
    ----------
    domain : str
        Domain to generate the report for (e.g. ``"medical-research"``).
        When *domains* is provided with 2+ entries, *domain* is still used
        for backward-compatible metadata but entries are aggregated from
        all listed domains.
    collection_id : str, optional
        Optional collection ID to scope the report to a specific
        collection run.  When omitted, all KB entries for the domain(s)
        are included.
    format : str, optional
        Output format (default ``"markdown"``).  Supports ``"markdown"``,
        ``"json"``, ``"html"``, ``"audio"``, ``"agent"``, ``"epub"``,
        ``"audiobook"``.  The ``"agent"`` format returns JSON-LD
        (``@type: KnowledgeDigest``) optimized for LLM re-consumption.
    period : str, optional
        Report period label (default ``"weekly"``).  One of ``"daily"``,
        ``"weekly"``, ``"monthly"``.  Used for metadata in JSON output.
        Unknown values raise :class:`ValueError`.
    custom_instructions : str, optional
        Optional string of additional instructions to append to the LLM
        generation prompt.  Ignored when empty/absent.
    report_type : str, optional
        Report type that controls section structure and content focus
        (default ``"standard"``).  Supported values: ``"standard"``
        (unchanged existing behavior), ``"industry"`` (domain-specific
        trends), ``"competitive"`` (entity comparison), ``"trend"``
        (time-series analysis), ``"daily-briefing"`` (curated top-N).
        Unknown values raise :class:`ValueError`.
    target_audience : str, optional
        Target audience for tone and depth adaptation (e.g. ``"researcher"``,
        ``"executive"``, ``"investor"``, ``"clinician"``, ``"student"``,
        ``"general"``).  Ignored when empty/absent.
    product_template:
        Optional :class:`ProductTemplate` instance for template rendering.
        When provided, the report is rendered through the product template
        system (with domain-specific overrides).  When ``None`` (default),
        the existing direct Jinja2 rendering is used (backward compatible).
        The product's ``access_level`` controls freemium gating (G15).
    product_type:
        Product type for delivery gate checking.  ``"PROCESSED"`` (default)
        enables D1-D3 checks when *delivery_gate_configs* is provided.
        ``"RAW"`` skips all delivery gates.
    delivery_gate_configs:
        Optional dict of ``{gate_name: config_dict}`` for D1-D3 delivery
        gates.  When provided, D1-D3 are run after rendering and the return
        type changes to :class:`DeliveryOutput`.  When ``None`` (default),
        no gates are run and a plain ``str`` is returned (backward
        compatible).
    domains : list[str], optional
        Optional list of domain names for cross-domain report generation.
        When provided with 2+ domains, entries are aggregated from all
        listed domains.  Each entry is labeled with its source domain.
        A special cross-domain LLM prompt encourages synthesis across
        domains.  When ``None`` or has fewer than 2 entries, the existing
        single-domain behavior is used (backward compatible).
    ref_limit:
        Optional maximum number of KB references to include in the rendered
        product.  Defaults to ``output.ref_limit`` from the project config
        (60).  References are sorted by (has non-empty summary desc,
        ``relevance_score`` desc) and capped at *ref_limit* at the
        context-build site, so title-only entries (empty summary, e.g.
        ProductHunt) de-prioritize.  All render formats (markdown/html/json/
        agent/audio/epub/video) are capped uniformly (issue #11).

    Returns
    -------
    str or DeliveryOutput
        Plain ``str`` when *delivery_gate_configs* is ``None`` (default).
        :class:`DeliveryOutput` with gate results when *delivery_gate_configs*
        is provided.

    Raises
    ------
    ValueError
        If *format* is unsupported, if *period* is not one of ``"daily"``,
        ``"weekly"``, ``"monthly"``, or if *report_type* is unknown.
    FileNotFoundError
        If the Jinja2 template file is not found.
    """
    if format not in ("markdown", "json", "html", "audio", "agent", "video", "epub", "audiobook"):
        raise ValueError(
            f"Unsupported output format: {format!r}. "
            f"Supported: markdown, json, html, audio, agent, video, epub, audiobook"
        )

    if report_type not in _VALID_REPORT_TYPES:
        raise ValueError(
            f"Unknown report type: {report_type!r}. "
            f"Supported: {', '.join(_VALID_REPORT_TYPES)}"
        )

    if period not in PERIOD_DAYS:
        raise ValueError(
            f"Invalid period '{period}'. Must be one of: {', '.join(sorted(PERIOD_DAYS))}"
        )

    # --- Resolve delivery-gate config (issue #298: default-on in production) --
    delivery_gate_configs = _resolve_delivery_gate_configs(domain, delivery_gate_configs)

    # --- Determine cross-domain mode -----------------------------------------
    is_cross_domain: bool = domains is not None and len(domains) >= 2
    if is_cross_domain:
        report_domains: list[str] = domains  # type: ignore[assignment]
        report_title_domain: str = "Cross-Domain"
    else:
        report_domains = [domain]
        report_title_domain = domain

    # --- Auto-load content_preference from user profile (B-001) --------------
    content_preference: str = _resolve_content_preference(user_id)
    source_tier_badge: bool = _source_tier_badge_enabled()

    # --- Freemium access gating (G15) ----------------------------------------
    if user_id and product_template is not None:
        product_access = getattr(product_template, "access_level", "free")
        if product_access != "free":
            from autoinfo.billing import check_access  # noqa: PLC0415

            access_result = check_access(user_id, product_access)
            if not access_result["allowed"]:
                blocked_message = (
                    f"# {report_title_domain} \u2014 Report\n\n"
                    f"**{access_result['upgrade_prompt'] or 'Access denied.'}**\n\n"
                    f"_Reason_: {access_result['reason']}\n\n"
                    f"_Access level required_: `{product_access}`\n"
                    f"_Your status_: {access_result['profile_status']} "
                    f"(plan: {access_result['plan']})\n"
                )
                if delivery_gate_configs is not None:
                    return DeliveryOutput(
                        output=blocked_message,
                        gate_results={},
                        delivery_blocked=True,
                        delivery_format=format,
                        warnings=[f"G15 blocked: {access_result['reason']}"],
                    )
                return blocked_message

    # -- Load KB entries --------------------------------------------------
    from autoinfo.llm import LLMExtractor  # noqa: PLC0415

    kb_store = KBStore()
    if is_cross_domain:
        entries: list[dict[str, Any]] = []
        for d in report_domains:
            domain_entries = kb_store.list_entries(d, limit=5000)
            for e in domain_entries:
                if "domain" not in e:
                    e["domain"] = d
            entries.extend(domain_entries)
    else:
        entries = kb_store.list_entries(domain, limit=5000)

    # --- Promotion trigger (T6): promote eligible 02-Draft entries ------------
    # Best-effort per entry — a rejected/failed promotion never blocks the
    # report (rejections stay in 02-Draft with a _failed/ marker).
    _promote_eligible_drafts(
        kb_store, report_domains if is_cross_domain else [domain], caller="report"
    )

    # --- Content-preference tier filtering (B-001) ---------------------------
    if content_preference != "both":
        filtered_entries = _filter_entries_by_content_preference(
            entries, content_preference
        )
        if len(filtered_entries) != len(entries):
            logger.info(
                "Excluded %d entries from report for domain '%s' "
                "due to content_preference='%s'",
                len(entries) - len(filtered_entries),
                domain,
                content_preference,
            )
        entries = filtered_entries

    # --- Test/empty entry filtering (issue #298 — layer 1) -------------------
    # Drop empty/test/placeholder entries BEFORE synthesis and BEFORE render.
    # Real Draft/Wiki entries with an empty DB summary but file content are
    # first enriched (issue #326) so the report Sections are never an empty
    # shell from real KB data.
    entries = _filter_product_entries(_enrich_product_entries(entries))
    # Near-duplicate convergence (issue #69) — see generate_digest.
    entries = _converge_near_duplicates(entries)

    # --- Language filter (issue #309 / #317) --------------------------------
    # An explicit param wins; otherwise the domain default fills in;
    # cross-domain never auto-picks one domain's default.
    effective_language = _resolve_effective_language(
        language, domain, cross_domain=is_cross_domain
    )
    if effective_language:
        entries, _ = _filter_entries_by_language_product_safe(
            entries, effective_language
        )

    # --- Per-domain exclude_keywords filter (issue #319) ---------------------
    # Cross-domain noise guard: drop entries matching their own domain's
    # exclude_keywords blacklist BEFORE thematic grouping / LLM synthesis.
    entries = _filter_entries_by_domain_exclusions(entries, domain)

    # --- Source-label enrichment (issue #325) --------------------------------
    # Mirror the digest path: stamp the derived specific source name on every
    # entry so ALL report-path surfaces (markdown references, section entry
    # tables, JSON entries, product-template variants column / premium-briefing
    # / enterprise-briefing / magazine-digest) render the specific source
    # instead of the generic "(RSS)" for stale pre-#323 entries.  In-place
    # mutation flows into section items because _group_by_theme reuses the same
    # entry dict objects.
    entries = _label_entries(entries, domain)

    if not entries:
        rendered: str
        if format in ("json", "agent"):
            empty_data: dict[str, Any] = {
                "title": f"{report_title_domain} \u2014 Report",
                "summary": "",
                "entries": [],
                "metadata": {
                    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "domain": report_title_domain,
                    "period": period,
                    "format": format,
                    "entry_count": 0,
                },
            }
            if format == "agent":
                empty_data["@context"] = _JSONLD_DIGEST["@context"]
                empty_data["@type"] = _JSONLD_DIGEST["@type"]
                empty_data["uuid"] = str(uuid.uuid4())
                empty_data["trends"] = []
            rendered = json.dumps(empty_data, indent=2, ensure_ascii=False, default=str)
        elif format == "html":
            rendered = _render_empty_report_html(report_title_domain)
        elif format == "audio":
            empty_md = _render_empty_report(report_title_domain)
            mp3_bytes = _render_audio(empty_md)
            rendered = base64.b64encode(mp3_bytes).decode("ascii")
        elif format in ("epub", "audiobook"):
            from autoinfo.output.ebook import render_audiobook, render_epub  # noqa: PLC0415

            empty_chapters = [
                (
                    f"{report_title_domain} \u2014 Report",
                    _render_empty_report(report_title_domain),
                )
            ]
            if format == "epub":
                ebook_result = render_epub(
                    title=f"{report_title_domain} \u2014 Report",
                    author="AutoInfo",
                    lang="en",
                    chapters=empty_chapters,
                )
            else:
                ebook_result = render_audiobook(empty_chapters)
            rendered = ebook_result["data_b64"]
        elif format == "video":
            rendered = _render_video_scaffold({}, report_title_domain, sections=None)
        else:
            rendered = _render_empty_report(report_title_domain)

        if delivery_gate_configs is not None:
            result = _apply_delivery_gates(
                rendered_output=rendered,
                output_format=format,
                entries=[],
                context={},
                product_type=product_type,
                delivery_gate_configs=delivery_gate_configs,
            )
            return _apply_min_content_guard(result, [], product_type)
        return rendered

    # -- Build reference list from entries --------------------------------
    # #325: derive the specific source label for entries whose stored
    # source_platform is a generic placeholder (pre-#323 'rss' etc.).
    # #11: cap the references at ref_limit (default output.ref_limit = 60).
    # The sort MUST run on the FULL entries list BEFORE the ref dicts are
    # built — the ref dicts drop relevance_score/summary, so capping on the
    # ref dicts would silently lose the (has summary, relevance) ordering.
    _ref_limit = ref_limit if ref_limit is not None else _output_config_ref_limit()
    _src_configs = _get_domain_source_configs(domain)
    references = []
    for e in _sorted_ref_entries(entries, domain=domain)[:_ref_limit]:
        _label = _derive_source_label(
            e, e.get("domain", domain), source_configs=_src_configs,
        )
        references.append({
            "title": e.get("title", ""),
            "source_url": e.get("source_url", ""),
            "source_type": e.get("source_type", ""),
            "source_platform": _label,
            "domain": e.get("domain", domain),
            "description": (
                str(e.get("summary") or "").strip()
                or str(e.get("content") or "")[:120].strip()
                or f"{_label} item"
            ),
        })

    # -- Thematic grouping via LLM ----------------------------------------
    extractor = LLMExtractor()
    groupings = _group_by_theme(
        extractor, entries, domain=domain,
        domains=report_domains if is_cross_domain else None,
    )

    # -- Inject report-type prompt into custom instructions ------------------
    effective_instructions = custom_instructions
    if report_type != "standard":
        type_prompt = _REPORT_TYPE_PROMPTS.get(report_type, "")
        if type_prompt:
            effective_instructions = (
                f"{custom_instructions}\n\n{type_prompt}"
                if custom_instructions
                else type_prompt
            )

    # -- Generate executive summary via LLM --------------------------------
    # Resolve the product template family up front (spec §2.4, todo 7) so
    # the synthesis can request the product-specific fields; the render
    # site below reuses this resolution. Agent format is content-equivalent
    # to markdown, so its family resolves against the markdown template file
    # (todo 22) — otherwise premium-briefing/enterprise-briefing agent output
    # would never request the per-product synthesis fields.
    variant = FORMAT_TO_VARIANT.get(format, format)
    family_variant = "md" if variant == "agent" else variant
    report_family = (
        _resolve_report_product_type(product_template, family_variant, report_type)
        if product_template is not None
        else ("column" if report_type == "column" else "report")
    )
    summary_result = _generate_executive_summary(
        extractor, entries, groupings, effective_instructions,
        target_audience=target_audience,
        domains=report_domains if is_cross_domain else None,
        product_family=report_family,
    )
    # The synthesis returns a dict of ``{executive_summary, key_findings,
    # recommendations}`` (plus the §2.4 product fields for product template
    # families).  Accept a bare string for backward compatibility (legacy
    # callers / direct mocks) — treated as summary only.
    if isinstance(summary_result, dict):
        executive_summary = summary_result.get("executive_summary", "") or ""
        # Issue #279: normalize findings to {text, source_url} objects.
        key_findings = [
            f if isinstance(f, dict) else {"text": str(f)}
            for f in (summary_result.get("key_findings") or [])
        ]
        recommendations = [
            str(r) for r in (summary_result.get("recommendations") or [])
        ]
        implications = [
            str(i) for i in (summary_result.get("implications") or [])
        ]
        action_required = [
            str(a) for a in (summary_result.get("action_required") or [])
        ]
        risks = [
            {
                k: str(v)
                for k, v in r.items()
                if k in ("title", "likelihood", "impact", "mitigation")
            }
            for r in (summary_result.get("risks") or [])
            if isinstance(r, dict)
        ]
        key_metrics = [
            {
                k: str(v)
                for k, v in m.items()
                if k in ("metric", "value", "source")
            }
            for m in (summary_result.get("key_metrics") or [])
            if isinstance(m, dict)
        ]
    else:
        executive_summary = str(summary_result or "")
        key_findings = []
        recommendations = []
        implications = []
        risks = []
        action_required = []
        key_metrics = []

    # -- Issue #217 follow-up: empty LLM synthesis → KB-derived fallback ----
    # DeepSeek empty/truncated synthesis (issue #178) must not ship a
    # section-less report: D1 rejects key_findings/summary/recommendations.
    # Derive those sections deterministically from the KB entries actually
    # used in the report — real domain content, never fabricated.
    if not executive_summary or not key_findings or not recommendations:
        logger.info(
            "LLM synthesis empty/partial for report (domain=%s, "
            "exec_summary=%d chars, key_findings=%d, recommendations=%d) — "
            "KB-derived fallback",
            domain,
            len(executive_summary or ""),
            len(key_findings),
            len(recommendations),
        )
        ranked = sorted(
            (e for e in entries),
            key=lambda e: float(e.get("relevance_score") or 0.0),
            reverse=True,
        )
        if not executive_summary:
            executive_summary = (
                f"{domain} intelligence briefing — {len(entries)} KB entries "
                f"across {len(groupings)} themes, distilled from the tracked "
                f"source set."
            )
        if not key_findings:
            key_findings = [
                {
                    "text": (
                        f"{e.get('title', 'Untitled entry')} \u2014 "
                        f"{str(e.get('summary') or '(no summary)')[:160]}"
                    ),
                    **(
                        {"source_url": str(e.get("source_url") or "").strip()}
                        if (e.get("source_url") or "").strip()
                        else {}
                    ),
                }
                for e in ranked[:5]
                if e.get("title")
            ]
        if not recommendations:
            recommendations = [
                f"Monitor {e.get('title', 'this topic')} for follow-up "
                "developments and validation from additional sources."
                for e in ranked[:3]
                if e.get("title")
            ]

    # -- Deterministic per-takeaway fields (issue #329) ----------------------
    # premium-briefing's takeaway layer renders per-takeaway implication /
    # risk / action by index-aligning with key_findings.  When the LLM
    # synthesis carries none (line 5053-5056 initializes them to []) or slot
    # values that are empty / `_No ..._` placeholder-shaped, the template's
    # `{% else %}` empty-state renders `_No ..._` placeholders.  Backfill each
    # slot per-index with the deterministic fallback derived from the ranked
    # entries (same pattern as #316/#326 column sections and the KB fallback
    # above), only for premium; placeholder-element case #357.
    if report_family == "premium-briefing":
        implications, risks, action_required = _fill_premium_takeaway_fields(
            implications, risks, action_required, entries, domain,
        )

    # -- Enterprise/premium key_findings cap (issue #11, decision a) --------
    # The enterprise-briefing template renders the selection-scope label
    # ``selected {{ key_findings|length }} of {{ references|length }}``.  The
    # PRIMARY synthesis key_findings is LLM-unbounded (only the §2.4 re-prompt
    # is bounded by _DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS), so a ref_limit
    # below the findings count would invert the label.  Cap the findings in
    # the report data to min(12, len(references)) for the families that
    # render the label (premium/enterprise), leaving the summary + findings
    # count consistent.
    if report_family in ("premium-briefing", "enterprise-briefing"):
        key_findings = _cap_product_key_findings(key_findings, references)

    # -- Build report data -------------------------------------------------
    # #325: every section item carries the derived source label.  When the
    # entry was already stamped by _label_entries (the real generate_report
    # path), reuse it; when the grouping path returns unlabeled entries (e.g.
    # tests patching _group_by_theme, or a grouping that rebuilds entry
    # dicts), derive the label here so no section surface shows "(RSS)".
    sections = [
        ReportSection(
            title=g["theme"],
            content=g.get("description", ""),
            items=[
                {
                    "title": e.get("title", ""),
                    "summary": e.get("summary", ""),
                    "source_url": e.get("source_url", ""),
                    "source_type": e.get("source_type", ""),
                    "source_platform": (
                        e.get("source_label", "")
                        or _derive_source_label(
                            e, str(e.get("domain") or domain)
                        )
                        or e.get("source_platform", "")
                    ),
                    "source_label": (
                        e.get("source_label", "")
                        or _derive_source_label(
                            e, str(e.get("domain") or domain)
                        )
                        or e.get("source_platform", "")
                    ),
                    "relevance_score": e.get("relevance_score", 0),
                    "source_tier": e.get("source_tier"),
                    "domain": e.get("domain", domain),
                }
                for e in g["entries"]
            ],
        )
        for g in groupings
    ]

    # Issue #318: the report H1 product word follows the resolved product
    # family when a product template is used (premium-briefing/column/
    # enterprise-briefing); the default report path (no product_template,
    # incl. report_type="column" T40) keeps the historical
    # "{domain} — Report" title byte-identical.
    report_h1_word = (
        _product_h1_word(report_family, default="Report")
        if product_template is not None
        else "Report"
    )

    report_data = ReportData(
        title=f"{report_title_domain} \u2014 {report_h1_word}",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        domain=report_title_domain,
        collection_id=collection_id or "",
        executive_summary=executive_summary,
        key_findings=key_findings,
        recommendations=recommendations,
        implications=implications,
        risks=risks,
        action_required=action_required,
        key_metrics=key_metrics,
        sections=sections,
        references=references,
    )

    # -- Build context for delivery gates ----------------------------------
    report_context: dict[str, Any] = {
        "llm_synthesis": {
            "executive_summary": report_data.executive_summary,
            "key_findings": report_data.key_findings,
            "recommendations": report_data.recommendations,
        },
    }

    # -- Render -------------------------------------------------------------
    if format == "agent":
        # Build entry-like dicts from report items for JSON-LD rendering
        agent_entries: list[dict[str, Any]] = []
        for section in report_data.sections:
            for item in section.items:
                agent_entries.append({
                    "entry_id": item.get("entry_id", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "source_url": item.get("source_url", ""),
                    # #325: derive the specific source label for stale
                    # pre-#323 entries (source_platform='rss') so the agent
                    # payload never carries the generic "rss" label.
                    "source_platform": _derive_source_label(
                        item, item.get("domain", domain)
                    ),
                    "collected_at": item.get("date", ""),
                    "relevance_score": item.get("relevance_score", 0),
                    "tags": [],
                })
        # The llm_synthesis carries the per-product analysis fields from
        # ReportData (todo 7); _render_agent_json surfaces them (todo 22).
        agent_context: dict[str, Any] = {
            "domain": report_title_domain,
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "llm_synthesis": {
                "executive_summary": report_data.executive_summary,
                "key_findings": report_data.key_findings,
                "trends": [],
                "recommendations": report_data.recommendations,
                "implications": report_data.implications,
                "risks": report_data.risks,
                "action_required": report_data.action_required,
                "key_metrics": report_data.key_metrics,
            },
            "target_audience": target_audience,
        }
        rendered = _render_agent_json(agent_entries, agent_context)
        # Persist the per-product analysis fields to the linked KB entries
        # (todo 24). Report-path agent entries hardcode entry_id "" — the
        # helper falls back to source_url matching.
        _persist_product_analysis_to_kb(
            kb_store,
            agent_entries,
            {
                "implications": report_data.implications,
                "risks": report_data.risks,
                "action_required": report_data.action_required,
                "key_metrics": report_data.key_metrics,
            },
        )
    elif product_template is not None:
        pt_context = _report_data_to_dict(report_data, source_tier_badge=source_tier_badge)
        # The report product resolves to its own template family when the
        # registry row has an on-disk template (premium-briefing,
        # enterprise-briefing, column); everything else keeps the report
        # family ("column" stays column for T40 backward compatibility).
        product_type = report_family
        rendered = product_template.render(product_type, variant, pt_context)
        rendered = _clean_skeleton_placeholders(rendered)
    elif format == "json":
        rendered = _render_report_json(report_data, period=period)
    elif format == "html":
        rendered = _render_report_html(report_data, period=period)
    elif format == "audio":
        markdown_text = _render_report_template(report_data, source_tier_badge=source_tier_badge)
        mp3_bytes = _render_audio(markdown_text)
        rendered = base64.b64encode(mp3_bytes).decode("ascii")
    elif format in ("epub", "audiobook"):
        from autoinfo.output.ebook import render_audiobook, render_epub  # noqa: PLC0415

        report_chapters = _report_chapters(report_data)
        if not report_chapters:
            # Degenerate report (no summary/sections/references): render the
            # full template as a single chapter so the book is still valid.
            report_chapters = [
                (
                    report_data.title,
                    _render_report_template(
                        report_data, source_tier_badge=source_tier_badge
                    ),
                )
            ]
        if format == "epub":
            ebook_result = render_epub(
                title=report_data.title,
                author="AutoInfo",
                lang="en",
                chapters=report_chapters,
                summary=report_data.executive_summary,
            )
        else:
            ebook_result = render_audiobook(report_chapters)
        rendered = ebook_result["data_b64"]
    elif format == "video":
        report_sections: list[dict[str, str]] = []
        for section in report_data.sections:
            for item in section.items:
                report_sections.append({
                    "heading": item.get("title", ""),
                    "body": item.get("summary", ""),
                })
        rendered = _render_video_scaffold(
            {},
            report_data.title if hasattr(report_data, "title") else report_title_domain,
            sections=report_sections,
        )
    else:
        rendered = _render_report_template(
            report_data, source_tier_badge=source_tier_badge
        )

    # -- Source attribution (F46) --------------------------------------------
    if is_cross_domain:
        all_src_configs: list[Any] = []
        for d in report_domains:
            all_src_configs.extend(_get_domain_source_configs(d))
        src_configs = all_src_configs
    else:
        src_configs = _get_domain_source_configs(domain)
    if src_configs and entries:
        entry_urls = {
            (e.get("source_url") or "").strip().rstrip("/")
            for e in entries
            if e.get("source_url")
        }
        used_sources = [
            s for s in src_configs
            if (s.url or "").strip().rstrip("/") in entry_urls
        ]
        if used_sources:
            attribution = _build_attribution_footer(used_sources, format)
            if attribution:
                if format in ("json", "agent"):
                    try:
                        data = json.loads(rendered)
                        data["sources"] = json.loads(
                            _build_attribution_footer(used_sources, "json")
                        )
                        rendered = json.dumps(
                            data, indent=2, ensure_ascii=False, default=str
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    # Text formats get a plain attribution footer. Binary
                    # formats (audio/epub/audiobook) carry base64 payloads —
                    # appending text would corrupt the base64 and make
                    # b64decode fail with "string argument should contain
                    # only ASCII characters" (F46 regression, 2026-08-11).
                    if format not in ("audio", "epub", "audiobook"):
                        rendered = rendered.rstrip() + "\n\n" + attribution

    # --- Record consumption event (CD-018) -----------------------------------
    if user_id:
        try:
            from autoinfo.consumption import ConsumptionStore  # noqa: PLC0415

            ConsumptionStore().record_event(
                user_id=user_id,
                product_type="report",
                product_id=f"{report_title_domain}-{period}",
                event_type="delivered",
                metadata={
                    "domain": report_title_domain,
                    "format": format,
                    "entries_count": len(entries),
                    "collection_id": collection_id or "",
                },
            )
        except Exception:
            logger.warning(
                "Failed to record consumption event for user '%s'",
                user_id,
                exc_info=True,
            )

    # -- Delivery gates (D1-D3) ---------------------------------------------
    if delivery_gate_configs is not None:
        result = _apply_delivery_gates(
            rendered_output=rendered,
            output_format=format,
            entries=entries,
            context=report_context,
            product_type=product_type,
            delivery_gate_configs=delivery_gate_configs,
            fallback_render_fn=lambda: _render_report_template(
                report_data, source_tier_badge=source_tier_badge
            ),
            llm_config=llm_config,
        )
        result = _apply_min_content_guard(result, entries, product_type)
        if user_id:
            _try_notify_content_ready(
                user_id=user_id,
                product_type="report",
                title=f"{report_title_domain} \u2014 {report_h1_word}",
            )
        _fire_agent_notification(
            "new_report",
            result.output if isinstance(result, DeliveryOutput) else rendered,
            product_id=f"{report_title_domain}-{period}",
        )
        return result

    if user_id:
        _try_notify_content_ready(
            user_id=user_id,
            product_type="report",
            title=f"{report_title_domain} \u2014 {report_h1_word}",
        )
    _fire_agent_notification(
        "new_report", rendered, product_id=f"{report_title_domain}-{period}"
    )
    return rendered


# ---------------------------------------------------------------------------
# Report internal helpers
# ---------------------------------------------------------------------------

_DOMAIN_THEME_GUIDANCE: dict[str, str] = {
    "medical-research": (
        "clinical applications, treatment outcomes/trials, "
        "reproductive health, drug development, regulatory & policy"
    ),
    "ai-commercial": (
        "product launches, market strategy, funding & acquisitions, "
        "regulatory & compliance, industry partnerships"
    ),
    "financial-intelligence": (
        "market trends, economic indicators, corporate strategy, "
        "regulatory changes, macroeconomic analysis"
    ),
    "tech-ai-developer": (
        "development tools & frameworks, research breakthroughs, "
        "industry adoption, open source & community, AI/ML advancements"
    ),
    "language-learning": (
        "learning methodology, language resources & tools, "
        "proficiency assessment, cultural context, pedagogy research"
    ),
}
_DEFAULT_DOMAIN_GUIDANCE = (
    "technology trends, industry developments, research findings, "
    "policy & regulation, emerging innovations"
)

# Entries are grouped in batches of this size so the LLM prompt stays small
# enough to return reliable JSON even for very long entry lists.
_GROUPING_BATCH_SIZE = 8

# Bounded worker pool for the per-batch grouping LLM calls.  Each call still
# goes through the shared per-provider semaphore (llm.call_with_fallback), so
# provider-level concurrency stays bounded even when the pool is this wide.
_GROUPING_MAX_WORKERS = 4


def _group_by_theme(
    extractor: LLMExtractor,
    entries: list[dict[str, Any]],
    domain: str = "",
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Group KB entries by theme using the LLM.

    Parameters
    ----------
    extractor : LLMExtractor
        LLM extractor instance for making API calls.
    entries : list[dict[str, Any]]
        List of entry dicts, each with ``entry_id``, ``title``, ``summary``,
        ``source_url``, ``source_type``, ``source_platform``.
    domain : str, optional
        Domain name for domain-specific theme guidance. If provided, the
        prompt includes themed suggestions relevant to the domain. An empty
        string (default) uses generic guidance.
    domains : list[str], optional
        Optional list of domain names for cross-domain synthesis. When
        provided, the grouping prompt includes an instruction to connect
        themes across domains.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts::

            [
                {
                    "theme": "IVF Treatment Outcomes",
                    "description": "...",
                    "entries": [...],
                },
            ]

    Entries are grouped in batches of at most ``_GROUPING_BATCH_SIZE`` so the
    LLM prompt stays small enough to return reliable JSON even for long entry
    lists; resulting themes are then merged across batches by normalized
    name.  When the LLM fails or collapses a batch, a deterministic keyword /
    source-type / domain heuristic is used instead, so the entries never
    collapse into a single ``"General"`` group while more than one distinct
    topic is detectable.
    """
    if not entries:
        return []

    from autoinfo.output import fault_inject  # noqa: PLC0415

    try:
        fault_inject.maybe_fault("group")
    except Exception:
        groups = _deterministic_grouping(entries, domain=domain)
        if groups is not None:
            # Issue #9 (reopened): the deterministic fallback may carry
            # keyword-derived generic themes — run the same blocklist/synonym
            # pass the LLM-grouping path uses so the fault-inject path cannot
            # leak ``### New`` / ``### Year`` labels either.
            return _merge_theme_groups(groups)
        return [
            {
                "theme": "General",
                "description": "Overview of the tracked developments this period.",
                "entries": list(entries),
            }
        ]

    batch_size = _GROUPING_BATCH_SIZE
    batches = [
        entries[i : i + batch_size] for i in range(0, len(entries), batch_size)
    ]

    merged = _run_grouping_batches(
        extractor, batches, domain=domain, domains=domains
    )

    return _ensure_all_entries_grouped(_merge_theme_groups(merged), entries)


def _run_grouping_batches(
    extractor: LLMExtractor,
    batches: list[list[dict[str, Any]]],
    domain: str = "",
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run the per-batch LLM grouping calls with a bounded thread pool.

    Batches are processed concurrently (bounded by ``_GROUPING_MAX_WORKERS``
    workers) while ``_group_batch_by_theme`` results are collected by index,
    so the final grouping list preserves the exact sequential batch order.
    Each LLM call inside still routes through :func:`call_with_fallback` and
    its shared per-provider semaphore, so per-provider concurrency stays
    bounded regardless of the pool width.

    Per-batch error behavior is identical to the sequential loop: a batch
    that fails (or whose LLM call raises) falls back to deterministic
    grouping inside ``_group_batch_by_theme``; if one ever raised, the first
    failing batch's exception surfaces in batch order after the pool has
    finished, exactly as the sequential ``for`` loop would.
    """
    workers = min(len(batches), _GROUPING_MAX_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        per_batch = list(
            pool.map(
                lambda batch: _group_batch_by_theme(
                    extractor, batch, domain=domain, domains=domains
                ),
                batches,
            )
        )
    return [g for batch_result in per_batch for g in batch_result]


def _group_batch_by_theme(
    extractor: LLMExtractor,
    entries: list[dict[str, Any]],
    domain: str = "",
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Group a single batch of entries (at most ``_GROUPING_BATCH_SIZE``).

    Uses the LLM (with an anti-collapse retry) and maps the returned entry
    IDs back to entry objects.  Falls back to a deterministic keyword /
    source-type / domain grouping when the LLM fails or collapses the batch.
    """
    groups_raw = _llm_group_batch(extractor, entries, domain=domain, domains=domains)
    if not groups_raw:
        groups = _deterministic_grouping(entries, domain=domain)
        if groups is not None:
            return groups
        return [
            {
                "theme": "General",
                # #338: never surface the internal "All N entries included in
                # this report" counting line to end users.
                "description": "Overview of the tracked developments this period.",
                "entries": list(entries),
            }
        ]

    entry_map: dict[str, dict[str, Any]] = {
        e.get("entry_id", ""): e for e in entries if e.get("entry_id")
    }

    result: list[dict[str, Any]] = []
    for g in groups_raw:
        group_entries = [
            entry_map[eid]
            for eid in g.get("entry_ids", [])
            if eid in entry_map
        ]
        if group_entries:
            result.append({
                "theme": g.get("theme", "Untitled"),
                "description": g.get("description", ""),
                "entries": group_entries,
            })

    # -- Coverage guard -----------------------------------------------------
    # The LLM sometimes returns parseable JSON whose entry_ids do not match
    # the actual entry IDs, which would dump every entry into a single
    # catch-all.  If the LLM groups cover fewer than half the batch, treat
    # the result as unreliable and fall back to deterministic grouping.
    matched_count = sum(len(g["entries"]) for g in result)
    if matched_count < max(1, len(entries) // 2):
        logger.warning(
            "LLM groups matched only %d/%d entries, falling back to "
            "deterministic grouping",
            matched_count,
            len(entries),
        )
        groups = _deterministic_grouping(entries, domain=domain)
        if groups is not None:
            return groups
        return [
            {
                "theme": "General",
                "description": "Overview of the tracked developments this period.",
                "entries": list(entries),
            }
        ]

    # Ensure no entry is left out (ungrouped entries go into a catch-all)
    grouped_ids: set[str] = {
        e.get("entry_id", "")
        for g in result
        for e in g["entries"]
        if e.get("entry_id")
    }
    ungrouped = [e for e in entries if e.get("entry_id", "") not in grouped_ids]
    if ungrouped:
        result.append({
            "theme": "Additional Topics",
            # #338: the previous "N entry(ies) not covered by other themes."
            # count line leaked internal grouping mechanics to end users.
            "description": "Other notable developments across the tracked sources.",
            "entries": ungrouped,
        })

    return result


def _llm_group_batch(
    extractor: LLMExtractor,
    entries: list[dict[str, Any]],
    domain: str = "",
    domains: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Ask the LLM to group a single batch of entries into themes.

    Returns the raw parsed ``groups`` list (each object carries ``theme``,
    ``description`` and ``entry_ids``) or ``None`` when the LLM fails or
    repeatedly collapses the batch into a single theme.
    """
    entry_summaries_parts: list[str] = []
    for e in entries:
        entry_domain = e.get("domain", domain)
        entry_summaries_parts.append(
            f"- [{e.get('entry_id', '?')}] [{entry_domain}] "
            f"{e.get('title', '?')}: {e.get('summary', '(no summary)')}"
        )
    entry_summaries = "\n".join(entry_summaries_parts)

    cross_domain_instruction = ""
    if domains and len(domains) >= 2:
        cross_domain_instruction = (
            f"You are synthesizing information from {len(domains)} domains: "
            f"{', '.join(domains)}. Present a cohesive view that connects "
            "findings across domains. Each entry is annotated with its "
            "source domain in [brackets]. Create themes that bridge or "
            "contrast findings from different domains where applicable.\n\n"
        )

    prompt = (
        cross_domain_instruction +
        "Group the following knowledge base entries into 3\u20135 themes. "
        "Each entry goes into exactly one theme. Do NOT use catch-all names "
        "like \"General\" or \"Additional\". "
        "Give each theme a SHORT SEMANTIC title: a concise noun phrase "
        "(2-6 words) naming the theme (e.g. 'Funding & M&A Momentum', "
        "'Reproductive Health Outcomes'). Never use a raw keyword list, "
        "concatenated entry titles, or separator-dumped keywords (no '/' or "
        "'&'-joined keyword strings). Titles must be unique and "
        "descriptive.\n\n"
        'Return JSON: {"groups": [{"theme": str, "entry_ids": [str]}]}\n\n'
        f"Entries:\n{entry_summaries}"
    )

    try:
        groups_raw = _llm_json_extract(extractor, prompt, "groups")
    except Exception as exc:
        logger.warning("Thematic grouping via LLM failed: %s", exc)
        groups_raw = None

    # -- Anti-collapse retry ------------------------------------------------
    # If the LLM returned only 1 group (or none), retry with a stricter
    # prompt that explicitly demands multiple distinct themes.
    if groups_raw and len(groups_raw) <= 1:
        logger.warning(
            "LLM returned only %d theme group(s), retrying with stricter prompt",
            len(groups_raw),
        )
        retry_prompt = (
            cross_domain_instruction +
            "STRICT RETRY: You previously grouped entries into a single "
            "theme. Re-read the entries below and identify at least "
            "2\u20133 DISTINCT themes. Do NOT use catch-all themes like "
            "\"General\", \"Miscellaneous\", or \"Other\". Each entry must "
            "be assigned to the most specific theme that describes its "
            "content. "
            "Give each theme a SHORT SEMANTIC title: a concise noun phrase "
            "(2-6 words) naming the theme (e.g. 'Funding & M&A Momentum', "
            "'Reproductive Health Outcomes'). Never use a raw keyword list, "
            "concatenated entry titles, or separator-dumped keywords (no '/' or "
            "'&'-joined keyword strings). Titles must be unique and "
            "descriptive.\n\n"
            'Return JSON: {"groups": [{"theme": str, "entry_ids": [str]}]}\n\n'
            f"Entries:\n{entry_summaries}"
        )
        try:
            groups_raw = _llm_json_extract(extractor, retry_prompt, "groups")
        except Exception as exc:
            logger.warning("Strict retry failed: %s", exc)
            groups_raw = None

        # If retry STILL produced only 1 group, treat as failure → fallback
        if groups_raw and len(groups_raw) <= 1:
            logger.warning(
                "Strict retry returned only %d group(s), falling back to "
                "deterministic grouping",
                len(groups_raw),
            )
            groups_raw = None

    result: list[dict[str, Any]] | None = groups_raw
    return result

def _deterministic_grouping(
    entries: list[dict[str, Any]],
    domain: str = "",
) -> list[dict[str, Any]] | None:
    """Group entries deterministically without the LLM.

    Splits by ``source_type`` (existing fallback), then by ``domain``, and
    finally by a keyword classifier built from the domain's ``_keywords.yaml``
    when the simpler splits still collapse to a single group.  Returns
    ``None`` only when fewer than two distinct topics are detectable, so the
    caller can decide on a last-resort group.
    """
    from collections import defaultdict

    # 1. Split by source_type
    source_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        st = (e.get("source_type") or "").strip() or "unknown"
        source_groups[st].append(e)

    if len(source_groups) >= 2:
        return [
            {
                "theme": st.upper(),
                # #338: user-facing lead, no internal "N entries from" count.
                "description": f"Updates and analysis from {st} sources.",
                "entries": es,
            }
            for st, es in sorted(source_groups.items())
        ]

    # 2. Split by domain
    domain_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        d = (e.get("domain") or "").strip() or "Unknown"
        domain_groups[d].append(e)

    if len(domain_groups) >= 2:
        return [
            {
                "theme": (
                    d.replace("-", " ").title() if d != "Unknown" else "Other Sources"
                ),
                # #338: user-facing lead, no internal "N entries from" count.
                "description": (
                    f"Developments across "
                    f"{d if d and d != 'Unknown' else 'other sources'}."
                ),
                "entries": es,
            }
            for d, es in sorted(domain_groups.items())
        ]

    # 3. Keyword classifier (from knowledge/<domain>/_keywords.yaml) — this
    #    replaces the old "General" dump when the entries are all from one
    #    source_type and one domain but still cover distinct topics.
    keyword_groups = _keyword_group_entries(entries, domain=domain)
    if keyword_groups is not None:
        return keyword_groups

    # Only a single distinct topic is detectable.
    return None


def _keyword_group_entries(
    entries: list[dict[str, Any]],
    domain: str = "",
) -> list[dict[str, Any]] | None:
    """Group entries by keyword topics from the domain's ``_keywords.yaml``.

    Loads topic keywords from ``knowledge/<domain>/_keywords.yaml`` (when
    present) and maps each entry's title/summary to the longest keyword it
    contains.  Returns a list of groups, or ``None`` when fewer than two
    distinct keyword topics are detectable so the caller can fall back to
    source-type / domain grouping.

    Issue #9 (reopened 2026-08-25): the generic-theme-label blocklist
    (``_GENERIC_THEME_LABELS``) historically lived ONLY in
    :func:`_merge_theme_groups`, which the deterministic-fallback callers of
    this function bypass (the fault-inject path in :func:`_group_by_theme`
    and :func:`_deterministic_column_sections` on the digest path).  The
    keyword classifier can therefore produce bare generic themes
    (``### New`` / ``### Year`` / ``### User`` ...) from auto-discovery
    noise keywords.  Sanitize at THIS boundary by running the result
    through :func:`_merge_theme_groups` before returning, so no caller can
    surface a generic theme; groups whose normalized theme is a bare
    generic word are dropped and their entries folded into the nearest
    surviving group or ``Additional Topics`` (no entry is ever lost).
    """
    from collections import defaultdict

    topics = _load_keyword_topics(domain)
    if not topics:
        return None

    # Normalize once, keep the original spelling for display, and match the
    # most specific (longest) keyword first.
    norm_topics: list[tuple[str, str]] = []
    for t in topics:
        nt = _normalize_text(t)
        if len(nt) >= 3:
            norm_topics.append((nt, t))
    if not norm_topics:
        return None
    norm_topics.sort(key=lambda pair: len(pair[0]), reverse=True)

    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        text = _normalize_text(
            f"{e.get('title', '')} {e.get('summary', '')}"
        )
        best = _match_keyword(text, norm_topics)
        groups[best if best else "__unmatched__"].append(e)

    keyword_names = [name for name in groups if name != "__unmatched__"]
    if not keyword_names:
        return None
    if len(keyword_names) == 1 and not groups.get("__unmatched__"):
        return None

    result: list[dict[str, Any]] = []
    for name, es in groups.items():
        if name == "__unmatched__":
            continue
        result.append({
            "theme": name.title(),
            # #338: the old "N entries related to '<kw>'." description exposed
            # the internal keyword-search/counting to end users — use a
            # user-facing section lead instead.
            "description": f"Key developments and analysis on {name.title()}.",
            "entries": es,
        })

    unmatched = groups.get("__unmatched__", [])
    if unmatched:
        result.append({
            "theme": "Additional Topics",
            # #338: no internal "N entry(ies) not matched to a topic keyword."
            # count line in the delivered product.
            "description": "Other notable developments across the tracked sources.",
            "entries": unmatched,
        })

    # Issue #9 (reopened): the generic-label blocklist must hold on EVERY
    # caller of this function, not just the ``_merge_theme_groups`` path the
    # LLM-grouping flow reaches.  Reuse the single source of truth for the
    # blocklist + synonym + near-dup passes.  The ``None`` contract is
    # preserved: when every keyword theme is generic (blocklist-stripped) or
    # structural (catch-all only), the classifier found no meaningful topic —
    # return ``None`` so the caller's source-type / domain fallback engages.
    sanitized = _merge_theme_groups(result)
    meaningful = [
        g for g in sanitized
        if _normalize_theme_text(g["theme"]) not in _STRUCTURAL_THEME_LABELS
    ]
    if not meaningful:
        return None
    return sanitized


def _load_keyword_topics(domain: str) -> list[str]:
    """Load non-deprecated topic keywords for *domain*.

    Reads ``knowledge/<domain>/_keywords.yaml`` (auto-discovery keywords)
    and MERGES the demo-domain seed ``src/autoinfo/data/domains/<domain>/
    sources.yaml`` ``topics[*].keywords`` into the result (issue #9).

    The merge is UNCONDITIONAL — not a fallback-when-empty: the runtime
    keyword table can hold 80+ usable topics that still never match English
    titles (auto-discovery noise — CJK tokens + ASCII n-gram fragments), so a
    "fallback only when none usable" branch would silently no-op on exactly
    the domains that need the curated English seed.  Seed keywords absent
    from the runtime table are appended (deduped); entries that already exist
    are not duplicated.
    """
    if not domain:
        return []
    topics: list[str] = []
    path = Path("knowledge") / domain / "_keywords.yaml"
    if path.is_file():
        try:
            raw: dict[str, Any] = yaml.safe_load(
                path.read_text(encoding="utf-8")
            ) or {}
        except Exception as exc:
            logger.warning("Failed to read keyword file %s: %s", path, exc)
            raw = {}
        kw_map: dict[str, Any] = raw.get("keywords", {}) or {}
        for keyword, data in kw_map.items():
            if isinstance(data, dict) and data.get("state") == "deprecated":
                continue
            topics.append(keyword)

    seen = set(topics)
    for seed_keyword in _seed_topic_keywords(domain):
        if seed_keyword not in seen:
            seen.add(seed_keyword)
            topics.append(seed_keyword)
    return topics


def _seed_topic_keywords(domain: str) -> list[str]:
    """Curated English topic keywords from the demo-domain seed (issue #9).

    Reads ``topics[*].keywords`` from ``src/autoinfo/data/domains/<domain>/
    sources.yaml`` — the same seed ``init`` uses to scaffold a domain.  An
    absent/unreadable seed yields ``[]`` so the runtime keyword table alone
    drives grouping.
    """
    seed_path = _DEMO_DOMAINS_DIR / domain / "sources.yaml"
    if not seed_path.is_file():
        return []
    try:
        with open(seed_path, encoding="utf-8") as f:
            seed = yaml.safe_load(f) or {}
    except Exception:
        return []
    keywords: list[str] = []
    for topic in seed.get("topics") or []:
        for kw in (topic.get("keywords") or []):
            if isinstance(kw, str) and kw.strip():
                keywords.append(kw.strip())
    return keywords


def _match_keyword(
    text: str,
    norm_topics: list[tuple[str, str]],
) -> str:
    """Return the longest normalized topic keyword found in *text*.

    Matches on normalized (lower-cased, punctuation-stripped) text with word
    boundaries so short keywords do not match inside unrelated words.
    """
    for nt, _original in norm_topics:
        if re.search(r"(?:^|\s)" + re.escape(nt) + r"(?=\s|$)", text):
            return nt
    return ""


def _normalize_text(value: str) -> str:
    """Lower-case *value*, strip punctuation and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _normalize_theme_text(value: str) -> str:
    """Normalize a theme name for exact-name merging across batches.

    Applies the ``_THEME_SYNONYMS`` map first (so synonym spellings collapse
    onto one canonical key, e.g. ``Year``/``The Year``) and then the shared
    punctuation/whitespace normalization.  Used for both the exact-name pass
    and the Jaccard near-dup pass in :func:`_merge_theme_groups`, so synonym
    variants merge BEFORE the generic-label blocklist runs.
    """
    text = _THEME_SYNONYMS.get(str(value).strip().lower(), str(value))
    return _normalize_text(text)


def _merge_theme_groups(
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge groups that share the same normalized theme name.

    Entries are deduplicated by ``entry_id`` when merging so the same entry
    is never reported under a theme twice.
    """
    from collections import defaultdict

    by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in groups:
        theme = (g.get("theme") or "").strip() or "Untitled"
        key = _normalize_theme_text(theme) or theme.strip().lower()
        by_name[key].append(g)

    result: list[dict[str, Any]] = []
    for merged in by_name.values():
        theme = merged[0]["theme"]
        description = next(
            (g["description"] for g in merged if g.get("description")), ""
        )
        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        for g in merged:
            for e in g["entries"]:
                eid = e.get("entry_id", "")
                if eid and eid in seen:
                    continue
                if eid:
                    seen.add(eid)
                entries.append(e)
        result.append({
            "theme": theme,
            "description": description,
            "entries": entries,
        })

    # -- Near-duplicate theme merge pass ------------------------------------
    # The exact-name pass above merges themes that normalize to the same
    # string, but near-duplicates (case, "&" vs "and", word order) still
    # slip through and surface as duplicate report sections.  Merge pairs
    # whose normalized token sets have Jaccard similarity >= 0.6 with one
    # set a subset of the other; keep the longest original title and
    # deduplicate entries by ``entry_id``.
    pending = list(result)
    final: list[dict[str, Any]] = []
    while pending:
        group = pending.pop(0)
        group_tokens = set(_normalize_theme_text(group["theme"]).split())
        rest: list[dict[str, Any]] = []
        for other in pending:
            other_tokens = set(_normalize_theme_text(other["theme"]).split())
            union = group_tokens | other_tokens
            if (
                group_tokens
                and other_tokens
                and len(group_tokens & other_tokens) / len(union) >= 0.6
                and (group_tokens <= other_tokens or other_tokens <= group_tokens)
            ):
                # Absorb *other* into *group*: keep the longest original
                # title, prefer the first non-empty description, dedupe ids.
                if len(str(other["theme"])) > len(str(group["theme"])):
                    group["theme"] = other["theme"]
                if not group.get("description") and other.get("description"):
                    group["description"] = other["description"]
                seen = {
                    e.get("entry_id", "") for e in group["entries"]
                    if e.get("entry_id")
                }
                for e in other["entries"]:
                    eid = e.get("entry_id", "")
                    if eid and eid in seen:
                        continue
                    if eid:
                        seen.add(eid)
                    group["entries"].append(e)
                group_tokens = set(
                    _normalize_theme_text(group["theme"]).split()
                )
            else:
                rest.append(other)
        final.append(group)
        pending = rest

    # -- Generic-label blocklist pass (issue #9) ----------------------------
    # After the exact-name and near-dup passes, drop any group whose
    # normalized theme is a bare generic word (``new`` / ``year`` /
    # ``user`` / ... — produced by auto-discovery keyword fragments).  Each
    # dropped group's entries are reassigned to the nearest surviving group
    # (by Jaccard on normalized tokens) or to "Additional Topics", so no
    # entry is ever lost.  "General" / "Additional Topics" are structural
    # catch-alls and deliberately exempt.
    survivors = [
        g for g in final
        if _normalize_theme_text(g["theme"]) not in _GENERIC_THEME_LABELS
    ]
    blocklisted = [
        g for g in final
        if _normalize_theme_text(g["theme"]) in _GENERIC_THEME_LABELS
    ]
    if not blocklisted:
        return survivors

    by_norm: dict[str, dict[str, Any]] = {}
    for g in survivors:
        nt = _normalize_theme_text(g["theme"])
        by_norm.setdefault(nt, g)
    survivor_pairs: list[tuple[set[str], dict[str, Any]]] = []
    for g in survivors:
        survivor_pairs.append((
            set(_normalize_theme_text(g["theme"]).split()),
            g,
        ))

    for g in blocklisted:
        g_tokens = set(_normalize_theme_text(g["theme"]).split())
        best: dict[str, Any] | None = None
        best_score = 0.0
        for tokens, candidate in survivor_pairs:
            if not tokens:
                continue
            union = g_tokens | tokens
            if not union:
                continue
            score = len(g_tokens & tokens) / len(union)
            if score > best_score:
                best_score = score
                best = candidate
        target = best if best_score >= 0.3 else None
        if target is None:
            target = next(
                (c for c in survivors if c["theme"] == "Additional Topics"),
                None,
            )
        if target is None:
            survivors.append({
                "theme": "Additional Topics",
                "description": "Other notable developments across the tracked sources.",
                "entries": [],
            })
            target = survivors[-1]
        seen = {e.get("entry_id", "") for e in target["entries"] if e.get("entry_id")}
        for e in g["entries"]:
            eid = e.get("entry_id", "")
            if eid and eid in seen:
                continue
            if eid:
                seen.add(eid)
            target["entries"].append(e)
    return survivors


def _ensure_all_entries_grouped(
    groups: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Guarantee every input entry appears in some group."""
    if not groups:
        return [
            {
                "theme": "General",
                # #338: no internal "All N entries included in this report."
                "description": "Overview of the tracked developments this period.",
                "entries": list(entries),
            }
        ]

    grouped_ids: set[str] = {
        e.get("entry_id", "")
        for g in groups
        for e in g["entries"]
        if e.get("entry_id")
    }
    missing = [
        e
        for e in entries
        if not (e.get("entry_id", "") and e["entry_id"] in grouped_ids)
    ]
    if missing:
        if len(groups) >= 2:
            groups.append({
                "theme": "Additional Topics",
                # #338: no internal "N entry(ies) not covered by other themes."
                "description": "Other notable developments across the tracked sources.",
                "entries": missing,
            })
        else:
            groups[0]["entries"].extend(missing)
    return groups


def _normalize_report_audience(target_audience: str) -> str:
    """Validate and normalize target_audience for report/digest generation.

    Returns the audience key if valid.  An empty or ``None``-like string
    resolves to ``"general"`` (no error).  A non-empty invalid audience
    raises :class:`ValueError` with a message naming the invalid value
    and listing valid options — mirroring tutorial/presentation behavior
    (issue #297).
    """
    if not target_audience:
        return "general"
    audience = target_audience.strip().lower()
    if audience in _VALID_REPORT_AUDIENCES:
        return audience
    raise ValueError(
        f"Invalid target_audience '{target_audience}'. "
        f"Must be one of: {', '.join(sorted(_VALID_REPORT_AUDIENCES))}"
    )


# Bounded smaller-prompt retry budgets for the report synthesis (F3 fix,
# round 1): the configured LLM endpoint returned EMPTY completions for
# synthesis prompts ≳ ~11.9K chars (F3 size sweep: 11,908–12,827 → empty
# 5/5; ≤10,734 → OK).  When the primary call comes back without a usable
# executive summary, the synthesis re-calls with an entries-detail block
# condensed to these budgets so the total prompt lands near ~5–7K chars.
_RETRY_MAX_DETAIL_ENTRIES = 12
_RETRY_MAX_ENTRY_SUMMARY_CHARS = 80
_RETRY_DETAIL_CHAR_BUDGET = 4000

# Round-2 (F3 re-verification): the endpoint's empty-completion behavior is
# no longer size-gated — bad windows (~40–60 min) return genuine empty
# completions at ALL prompt sizes, including the condensed ~5.9–6.1K retry
# prompt (0/11 probes).  So the single retry became a bounded multi-attempt
# loop (attempt 1 = full-size prompt; attempts 2+ = the condensed prompt)
# with a short sleep between attempts — long enough to bridge a flapping
# endpoint window, short enough that one ``generate_report`` still completes.
# Both bounds are injectable for tests (no real sleeps under pytest).
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_SECONDS = 60.0

# Budgets for the round-2 dedicated product-sections prompt: a small second
# call (issued only for product families when the base synthesis succeeded
# but the parsed result lacks the §2.4 sections) that carries the produced
# executive summary + findings (bounded) so the total stays ~2–3.5K chars,
# far below any prompt-size concern.
_DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS = 12
_DEDICATED_PRODUCT_PROMPT_MAX_FINDING_CHARS = 200
_DEDICATED_PRODUCT_PROMPT_MAX_SUMMARY_CHARS = 1000


def _build_report_entries_detail(
    entries: list[dict[str, Any]],
    groupings: list[dict[str, Any]],
    max_detail_entries: int = 40,
    max_entry_summary_chars: int = 120,
    detail_char_budget: int | None = None,
) -> str:
    """Build the theme-grouped entry detail block embedded in the synthesis
    prompt.

    Defaults reproduce the original behavior exactly (40 highest-relevance
    entries × 120-char summaries).  *detail_char_budget* caps the block's
    total length; when the cap is hit, remaining entries are dropped and a
    truncation note appended — used by the smaller-prompt retry in
    :func:`_generate_executive_summary` so the prompt stays within the size
    the configured LLM endpoint reliably answers.
    """
    ranked = sorted(
        (e for g in groupings for e in g["entries"]),
        key=lambda e: float(e.get("relevance_score") or 0.0),
        reverse=True,
    )[:max_detail_entries]
    picked_ids = {id(e) for e in ranked}

    detail_lines: list[str] = []
    truncated = False
    for g in groupings:
        if truncated:
            break
        picked = [e for e in g["entries"] if id(e) in picked_ids]
        for e in picked:
            line = (
                f"- [{g['theme']}] {e.get('title', '')}: "
                f"{(e.get('summary') or '')[: max_entry_summary_chars]}"
            )
            # Issue #279: thread source_url into the synthesis context.
            src = str(e.get("source_url") or "").strip()
            if src:
                line = f"{line} (Source: {src})"
            if detail_char_budget is not None:
                if len("\n".join(detail_lines + [line])) > detail_char_budget:
                    truncated = True
                    break
            detail_lines.append(line)
        if not truncated and len(picked) < len(g["entries"]):
            detail_lines.append(
                f"- [{g['theme']}] (+{len(g['entries']) - len(picked)} more "
                "entries in this theme)"
            )
    if truncated:
        detail_lines.append("(further entries omitted for brevity)")
    return "\n".join(detail_lines) or "(no entries)"


def _build_report_synthesis_prompt(
    entries_detail: str,
    custom_instructions: str = "",
    target_audience: str = "",
    domains: list[str] | None = None,
    product_family: str = "report",
) -> str:
    """Assemble the report-synthesis prompt.

    Shared by the primary call and the truncated-prompt retry in
    :func:`_generate_executive_summary` so both request and parse the same
    structure (including the §2.4 product sections for product families).
    """
    cross_domain_prefix = ""
    if domains and len(domains) >= 2:
        cross_domain_prefix = (
            f"You are synthesizing information from {len(domains)} domains: "
            f"{', '.join(domains)}. Present a cohesive view that connects "
            "findings across domains.\n\n"
        )

    prompt = (
        cross_domain_prefix +
        "Write a report synthesis analyzing the following knowledge base "
        "entries (grouped by theme). Use the actual content: cite specific "
        "findings, studies, and data points from the entries. When a key "
        "finding, recommendation, or trend is backed by a specific entry, "
        "cite its source inline as (Source: URL). Do NOT describe "
        "the report structure or the writing instructions — write the analysis "
        "itself.\n\n"
        f"Themes and entries:\n{entries_detail}\n\n"
        "Return plain Markdown with this exact structure:\n\n"
        "## Executive Summary\n"
        "<2-3 paragraphs>\n\n"
        "## Key Findings\n"
        "- <finding 1>\n"
        "- <finding 2>\n\n"
        "## Recommendations\n"
        "- <recommendation 1>\n"
        "- <recommendation 2>\n\n"
        "Use exactly the heading names above. Do NOT wrap your answer in a "
        "code fence or emit JSON."
    )
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"
    # -- Product-specific synthesis sections (todo 7, spec §2.4) -------------
    product_structure = _REPORT_PRODUCT_SYNTHESIS_PROMPTS.get(product_family, "")
    if product_structure:
        prompt += f"\n\n{product_structure}"
    # -- Structured audience adaptation -----------------------------------
    audience = _normalize_report_audience(target_audience)
    audience_prompt = _REPORT_AUDIENCE_PROMPTS.get(audience, "")
    if audience_prompt:
        prompt += f"\n\n{audience_prompt}"
    return prompt


def _report_product_fields_for_family(product_family: str) -> tuple[str, ...]:
    """Required §2.4 product fields for a product synthesis family.

    Returns ``()`` for the default ``report`` family and any unknown family
    so the dedicated product-sections prompt never fires outside the product
    template families (backward compatibility).  ``key_metrics`` is
    enterprise-only.
    """
    if product_family not in _REPORT_PRODUCT_SYNTHESIS_PROMPTS:
        return ()
    fields: tuple[str, ...] = ("implications", "risks", "action_required")
    if product_family == "enterprise-briefing":
        fields += ("key_metrics",)
    return fields


def _build_product_sections_prompt(
    parsed: dict[str, Any],
    product_family: str,
    max_findings: int = _DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS,
    max_finding_chars: int = _DEDICATED_PRODUCT_PROMPT_MAX_FINDING_CHARS,
    max_summary_chars: int = _DEDICATED_PRODUCT_PROMPT_MAX_SUMMARY_CHARS,
) -> str:
    """Build the small dedicated prompt that asks the model to emit ONLY the
    §2.4 product sections for an already-produced synthesis.

    Carries the produced executive summary and key findings (both bounded so
    the total stays ~2–3.5K chars, far below any prompt-size concern) plus
    the family's section format spec, so the response parses with
    :func:`_parse_report_markdown` (``require_exec_summary=False``).  The
    callers only merge the product fields back, so any model output outside
    the requested sections is ignored.
    """
    summary = (parsed.get("executive_summary") or "").strip()
    if len(summary) > max_summary_chars:
        summary = summary[:max_summary_chars].rstrip() + "..."
    finding_texts = [
        ((f.get("text") if isinstance(f, dict) else f) or "").strip()
        for f in (parsed.get("key_findings") or [])[:max_findings]
    ]
    findings = "\n".join(
        f"- {t[:max_finding_chars].rstrip()}" for t in finding_texts
    )
    return (
        "You are a report synthesis assistant. Below are the executive summary "
        "and key findings already produced for a briefing. Emit ONLY the "
        "additional product sections listed below — do NOT repeat the "
        "executive summary, key findings, recommendations, or any other "
        "content.\n\n"
        f"## Executive Summary\n{summary or '(none)'}\n\n"
        f"## Key Findings\n{findings or '(none)'}\n\n"
        + _REPORT_PRODUCT_SYNTHESIS_PROMPTS[product_family]
    )


def _generate_executive_summary(
    extractor: LLMExtractor,
    entries: list[dict[str, Any]],
    groupings: list[dict[str, Any]],
    custom_instructions: str = "",
    target_audience: str = "",
    domains: list[str] | None = None,
    product_family: str = "report",
    *,
    max_synthesis_attempts: int = _RETRY_MAX_ATTEMPTS,
    retry_backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Generate the report synthesis (summary + findings + recommendations).

    Asks the LLM for flat Markdown with ``## Executive Summary`` /
    ``## Key Findings`` / ``## Recommendations`` headings — the default
    model emits markdown far more reliably than a nested JSON schema —
    and parses it by heading (see :func:`_parse_report_markdown`).

    For product template families (``premium-briefing`` /
    ``enterprise-briefing`` / ``magazine-digest``) the requested structure
    additionally includes the §2.4 product sections — ``## Implications`` /
    ``## Risks & Opportunities`` / ``## Action Required`` (index-aligned
    with Key Findings), plus ``## Key Metrics`` for enterprise-briefing —
    keyed by the resolved family. The default ``report`` family is
    unchanged (spec §2.4, todo 7).

    Falls back to a legacy single-string JSON summary via the extractor,
    and finally to a bullet-list summary, so the report is never empty.
    When an attempt returns empty (or the parsed result lacks an executive
    summary) — the configured endpoint flaps with genuine empty completions
    for ~40–60-min "bad windows" at ALL prompt sizes — the call is retried
    with a condensed entries-detail prompt (see
    :func:`_build_report_entries_detail`) up to *max_synthesis_attempts*
    times total, sleeping *retry_backoff_seconds* via *sleep_fn* between
    attempts, so one ``generate_report`` can bridge an endpoint bad window
    without an unbounded loop (round-2 F3 fix; both bounds injectable for
    tests).  Attempt 1 uses the full-size prompt; attempts 2+ reuse the
    condensed prompt.

    For product families, when the synthesis succeeds but the parsed result
    lacks required §2.4 product fields (the model often omits the trailing
    sections), a SECOND small dedicated prompt (see
    :func:`_build_product_sections_prompt`) is issued — bounded to at most
    one call — asking for ONLY those sections, and the parsed sections are
    merged into the result.
    Returns a dict ``{"executive_summary": str, "key_findings": list[str],
    "recommendations": list[str]}`` — never raises.
    """
    from autoinfo.output import fault_inject  # noqa: PLC0415

    try:
        fault_inject.maybe_fault("summary")
    except Exception:
        fallback = _deterministic_synthesis_fallback(
            entries, summary_prefix="This report covers"
        )
        return {
            "executive_summary": fallback["executive_summary"],
            "key_findings": fallback["key_findings"],
            "recommendations": fallback["recommendations"],
        }

    entries_detail = _build_report_entries_detail(entries, groupings)
    prompt = _build_report_synthesis_prompt(
        entries_detail,
        custom_instructions=custom_instructions,
        target_audience=target_audience,
        domains=domains,
        product_family=product_family,
    )
    retry_prompt = _build_report_synthesis_prompt(
        _build_report_entries_detail(
            entries,
            groupings,
            max_detail_entries=_RETRY_MAX_DETAIL_ENTRIES,
            max_entry_summary_chars=_RETRY_MAX_ENTRY_SUMMARY_CHARS,
            detail_char_budget=_RETRY_DETAIL_CHAR_BUDGET,
        ),
        custom_instructions=custom_instructions,
        target_audience=target_audience,
        domains=domains,
        product_family=product_family,
    )
    retry_prompt_usable = len(retry_prompt) < len(prompt)

    # Primary path: flat markdown synthesis (reliable with the default model),
    # with a bounded multi-attempt retry loop against endpoint bad windows.
    parsed: dict[str, Any] = {}
    for attempt in range(1, max_synthesis_attempts + 1):
        if attempt > 1:
            if not retry_prompt_usable:
                break
            logger.info(
                "Report synthesis attempt %d/%d returned no executive summary; "
                "sleeping %.0fs then retrying with condensed prompt "
                "(%d -> %d chars)",
                attempt - 1,
                max_synthesis_attempts,
                retry_backoff_seconds,
                len(prompt),
                len(retry_prompt),
            )
            sleep_fn(retry_backoff_seconds)
        attempt_prompt = prompt if attempt == 1 else retry_prompt
        parsed = _parse_report_markdown(
            _call_llm_for_report_synthesis(attempt_prompt)
        )
        if parsed.get("executive_summary"):
            break

    if parsed.get("executive_summary"):
        # Round-2 F3 fix: the model often omits the trailing §2.4 product
        # sections even when the synthesis succeeds.  For product families,
        # when any required section is missing/empty, issue ONE small
        # dedicated prompt (decoupled from the base synthesis call) and
        # merge the parsed sections back.
        product_fields = _report_product_fields_for_family(product_family)
        if product_fields and any(not parsed.get(f) for f in product_fields):
            sections_prompt = _build_product_sections_prompt(parsed, product_family)
            logger.info(
                "Report synthesis succeeded but product sections (%s) missing; "
                "issuing dedicated small prompt (%d chars)",
                ", ".join(f for f in product_fields if not parsed.get(f)),
                len(sections_prompt),
            )
            sections_parsed = _parse_report_markdown(
                _call_llm_for_report_synthesis(sections_prompt),
                require_exec_summary=False,
            )
            for field in product_fields:
                if sections_parsed.get(field):
                    parsed[field] = sections_parsed[field]
        return parsed

    # Legacy path: single-string JSON summary via the extractor.
    try:
        raw = _llm_json_extract(extractor, prompt, "executive_summary")
        if raw and isinstance(raw, str) and raw.strip():
            return {
                "executive_summary": raw.strip(),
                "key_findings": [],
                "recommendations": [],
            }
    except Exception as exc:
        logger.warning("Executive summary via LLM failed: %s", exc)

    # Fallback
    # Issue #217: the fallback must still carry non-empty D1-required
    # sections — key_findings / recommendations derived from the real
    # entries (never fabricated), so D1 never blocks the report.
    # Issue #338: the previous per-theme count summary ("This report covers
    # N entries grouped into M themes: - **API**: N entry(ies)") leaked the
    # internal grouping/search mechanics to end users — use the user-facing
    # summary derived from the real entry titles instead.
    fallback = _deterministic_synthesis_fallback(
        entries, summary_prefix="This report covers"
    )
    return {
        "executive_summary": fallback["executive_summary"],
        "key_findings": fallback["key_findings"],
        "recommendations": fallback["recommendations"],
    }


def _call_llm_for_report_synthesis(prompt: str) -> str:
    """Call the configured LLM to synthesize report Markdown.

    Uses the shared :func:`call_with_fallback` helper in plain-text mode
    (no JSON mode) — the default model emits the flat ``## Executive
    Summary`` / ``## Key Findings`` / ``## Recommendations`` structure
    reliably while a nested JSON schema frequently comes back empty.
    Returns the raw Markdown text (possibly empty) on success, ``""`` on
    failure.
    """
    from autoinfo.output import fault_inject  # noqa: PLC0415

    try:
        fault_inject.maybe_fault("report")
    except Exception as exc:
        logger.warning("FAULT_INJECT[report]: %s", exc)
        return ""

    config_path = get_config_path()
    if config_path and config_path.is_file():
        try:
            config = load_config(config_path)
        except Exception:
            config = Config()
    else:
        config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a report synthesis assistant. Given knowledge "
                        "base entries and themes, write a concise executive "
                        "summary, key findings, and recommendations. Respond "
                        "with plain Markdown only — no JSON, no code fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            json_mode=False,
            max_tokens=8000,
            temperature=0.1,
            api_key=config.llm.api_key or None,
            base_url=config.llm.base_url or None,
        )
    except Exception as exc:
        logger.warning("Report synthesis via LLM failed: %s", exc)
        return ""
    content: str = response.choices[0].message.content or ""
    return content.strip()


_GLUED_BULLET_SEP = re.compile(r"(?<=\))- ?")


def _split_glued_bullets(text: str) -> list[str]:
    """Split a bullet body that carries glue-glued follow-on bullets (issue #14).

    The LLM sometimes returns Key Findings bullets joined inline without
    newlines — ``- a (Source: u)- b (Source: u)- c`` — so the whole run is
    seen by ``is_bullet`` as ONE item.  A ``)`` immediately before a ``-`` is
    the glue boundary (a ``(Source: URL)`` citation suffix followed by the
    next bullet marker), and each split part preserves its own ``(Source: u)``
    suffix.  Legitimate prose where ``)`` is *not* followed by ``-`` is never
    split.
    """
    return [part for part in _GLUED_BULLET_SEP.split(text) if part]


def _parse_report_markdown(
    content: str, require_exec_summary: bool = True
) -> dict[str, Any]:
    """Parse a Markdown report synthesis into the report context schema.

    Handles the structure requested by the report-synthesis prompt:
    ``## Executive Summary`` (paragraphs), ``## Key Findings`` (bullets)
    and ``## Recommendations`` (bullets).  For product template families
    (spec §2.4, todo 7) it also parses ``## Implications`` (bullets →
    ``list[str]``), ``## Risks & Opportunities`` (``|``-delimited bullets →
    ``list[dict]`` ``{title, likelihood, impact, mitigation}``),
    ``## Action Required`` (bullets → ``list[str]``) and ``## Key Metrics``
    (``|``-delimited bullets → ``list[dict]`` ``{metric, value, source}``).
    Returns ``{}`` when *content* is empty, or when *content* carries no
    executive summary and *require_exec_summary* is set (default).  The
    dedicated product-sections response (which intentionally omits the
    executive summary) is parsed with ``require_exec_summary=False``.
    """
    if not content:
        return {}
    result: dict[str, Any] = {
        "executive_summary": "",
        "key_findings": [],
        "recommendations": [],
        "implications": [],
        "risks": [],
        "action_required": [],
        "key_metrics": [],
    }
    current_section = ""
    summary_lines: list[str] = []

    def is_bullet(text: str) -> bool:
        return bool(re.match(r"^(?:[-*]|\d+[.)])\s+\S", text))

    def bullet_text(text: str) -> str:
        return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", text).strip()

    for raw in content.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped.lstrip("#").strip().lower()
            continue
        if not current_section:
            continue
        if current_section in ("executive summary", "summary", "overview"):
            if stripped and not line.startswith(("---", "***")):
                summary_lines.append(stripped)
        elif current_section in ("key findings", "findings", "main findings"):
            if is_bullet(stripped):
                for item in _split_glued_bullets(bullet_text(stripped)):
                    item = item.strip()
                    if item:
                        result["key_findings"].append(item)
        elif current_section in ("recommendations", "next steps", "action items"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["recommendations"].append(item)
        elif current_section == "implications":
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["implications"].append(item)
        elif current_section in ("risks & opportunities", "risks", "risk matrix"):
            if is_bullet(stripped):
                parts = [p.strip() for p in bullet_text(stripped).split("|")]
                if len(parts) >= 4 and parts[0]:
                    result["risks"].append(
                        {
                            "title": parts[0],
                            "likelihood": parts[1],
                            "impact": parts[2],
                            "mitigation": " | ".join(parts[3:]),
                        }
                    )
        elif current_section in ("action required", "actions"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["action_required"].append(item)
        elif current_section in ("key metrics", "metrics"):
            if is_bullet(stripped):
                parts = [p.strip() for p in bullet_text(stripped).split("|")]
                if len(parts) >= 3 and parts[0]:
                    result["key_metrics"].append(
                        {
                            "metric": parts[0],
                            "value": parts[1],
                            "source": " | ".join(parts[2:]),
                        }
                    )

    result["executive_summary"] = "\n\n".join(summary_lines).strip()
    if require_exec_summary and not result["executive_summary"]:
        return {}
    return result


def _llm_json_extract(
    extractor: LLMExtractor,
    prompt: str,
    field: str,
) -> Any:
    """Call the LLM and extract a top-level JSON field.

    Uses :class:`LLMExtractor` under the hood by wrapping the prompt in
    a minimal ``Item``.  Returns the value of *field* from the parsed
    JSON response, or ``None`` on failure.

    Free-provider resilience: the extraction path returns an EMPTY result
    (not an exception) on transient parse failure; retry once before
    giving up, mirroring the two-attempt pattern of ``_report_llm_call``.
    """
    from autoinfo.models import Item  # noqa: PLC0415

    dummy = Item(
        id="_report_llm_call",
        source_name="report",
        source_type="internal",
        source_url="",
        title=field.replace("_", " ").title(),
        content=prompt,
    )
    result = extractor.extract(dummy, schema=[field])
    value = result.custom_fields.get(field) if result else None
    if value is None:
        result = extractor.extract(dummy, schema=[field])
        value = result.custom_fields.get(field) if result else None
    return value


def _report_data_to_dict(
    report_data: ReportData, source_tier_badge: bool = True
) -> dict[str, Any]:
    """Convert a :class:`ReportData` instance to a flat dict for Jinja2 rendering.

    Maps ``ReportSection.items`` → ``entries`` to match the variable
    names expected by the report templates (``report.md.j2``,
    ``report.html.j2``).  Also surfaces the §2.1 product fields
    (``implications`` / ``risks`` / ``action_required`` / ``key_metrics``,
    spec §2.4, todo 7) — empty lists for plain reports, so existing callers
    are unchanged.

    Issue #342: the report-path magazine product (``generate_report`` with
    the ``magazine-digest`` template) reads the top-level ``entries`` list
    for its per-title clusters.  Build it from the references — the report
    path already derives the specific source labels there — so the magazine
    layout renders real per-title clusters instead of the
    ``_No articles found..._`` empty-state.
    """
    # #325: stamp a derived ``source_label`` on every reference so the
    # report-path templates (report/column/premium-briefing/enterprise-briefing
    # /magazine-digest) can render ``ref.source_label or ref.source_platform``
    # and never show the generic "(RSS)" for stale pre-#323 entries.  A
    # reference may already carry the derived label (the generate_report
    # references builder calls _derive_source_label); when it does not (e.g.
    # a flat context built directly), derive it here from the ref's own data.
    labeled_refs = []
    for ref in report_data.references:
        ref_label = str(ref.get("source_label") or "").strip()
        if not ref_label:
            ref_label = _derive_source_label(ref, str(ref.get("domain") or report_data.domain))
        labeled_refs.append({**ref, "source_label": ref_label})

    entries = [
        {
            "title": ref.get("title", ""),
            "summary": "",
            "source_url": ref.get("source_url", ""),
            "source_type": ref.get("source_type", ""),
            "source_platform": ref.get("source_label", "") or ref.get("source_platform", ""),
            "source_label": ref.get("source_label", ""),
            "relevance_score": None,
            "collected_at": "",
        }
        for ref in labeled_refs
    ]
    return {
        "title": report_data.title,
        "generated_at": report_data.generated_at,
        "domain": report_data.domain,
        "collection_id": report_data.collection_id,
        "executive_summary": report_data.executive_summary,
        "key_findings": report_data.key_findings,
        "recommendations": report_data.recommendations,
        "implications": report_data.implications,
        "risks": report_data.risks,
        "action_required": report_data.action_required,
        "key_metrics": report_data.key_metrics,
        "source_tier_badge": source_tier_badge,
        "entries": entries,
        "sections": [
            {
                "title": s.title,
                "content": s.content,
                "entries": [
                    {
                        **item,
                        "source_platform": (
                            item.get("source_label", "") or item.get("source_platform", "")
                        ),
                    }
                    for item in s.items
                ],
            }
            for s in report_data.sections
        ],
        "references": labeled_refs,
        "appendices": report_data.appendices,
    }


def _render_report_json(report_data: ReportData, period: str = "weekly") -> str:
    """Render the report data as a JSON string.

    The JSON structure includes ``title``, ``summary``, a flat ``entries``
    list (with ``title``, ``summary``, ``url``, ``date`` per entry), and
    ``metadata`` with generation context.
    """
    entries_list: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for section in report_data.sections:
        for item in section.items:
            url = item.get("source_url", "") or ""
            if url and url in seen_urls:
                continue
            # Defense-in-depth for issue #294: skip entries with empty title
            # or empty/placeholder summary.
            title = item.get("title", "")
            summary = item.get("summary", "")
            if not title.strip() or _is_empty_summary(summary):
                continue
            if url:
                seen_urls.add(url)
            entries_list.append({
                "title": title,
                "summary": summary,
                "url": url,
                "source_url": url,
                "source_type": item.get("source_type", ""),
                "source_platform": item.get("source_label", "") or item.get("source_platform", ""),
                "date": item.get("collected_at", ""),
                "domain": item.get("domain", ""),
            })

    # Also include any references not already covered
    for ref in report_data.references:
        url = ref.get("source_url", "") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        entries_list.append({
            "title": ref.get("title", ""),
            "summary": "",
            "url": url,
            "source_url": url,
            "source_type": ref.get("source_type", ""),
            "source_platform": ref.get("source_platform", ""),
            "date": "",
            "domain": ref.get("domain", ""),
        })

    output = {
        "title": report_data.title,
        "summary": report_data.executive_summary,
        "key_findings": report_data.key_findings,
        "recommendations": report_data.recommendations,
        "entries": entries_list,
        "metadata": {
            "generated_at": report_data.generated_at,
            "domain": report_data.domain,
            "period": period,
            "format": "json",
            "entry_count": len(entries_list),
        },
    }
    return json.dumps(output, indent=2, ensure_ascii=False, default=str)


def _report_chapters(report_data: ReportData) -> list[tuple[str, str]]:
    """Split report data into ``(heading, markdown_body)`` chapters.

    Executive summary → "Executive Summary"; each themed section → its own
    chapter (content plus an item table when items exist); references →
    a "References" appendix.  Used by the ``epub`` and ``audiobook``
    report formats.
    """
    chapters: list[tuple[str, str]] = []
    if report_data.executive_summary:
        chapters.append(("Executive Summary", report_data.executive_summary))
    for idx, section in enumerate(report_data.sections, 1):
        body = section.content or ""
        if section.items:
            rows = ["| # | Title | Summary |", "|---|-------|---------|"]
            row_idx = 0
            for item in section.items:
                title = item.get("title", "")
                summary = item.get("summary", "")
                # Defense-in-depth for issue #294: skip empty-title rows
                # and rows with empty/placeholder summary.
                if not title.strip() or _is_empty_summary(summary):
                    continue
                row_idx += 1
                rows.append(
                    f"| {row_idx} | {title} | {summary} |"
                )
            if row_idx:
                body = f"{body}\n\n{chr(10).join(rows)}".strip()
        chapters.append((section.title or f"Section {idx}", body))
    if report_data.references:
        ref_lines = []
        for ref in report_data.references:
            line = f"- **{ref.get('title', '')}**"
            if ref.get("source_url"):
                line += f" \u2014 {ref['source_url']}"
            ref_lines.append(line)
        chapters.append(("References", "\n".join(ref_lines)))
    return chapters


def _render_report_template(report_data: ReportData, source_tier_badge: bool = True) -> str:
    """Render the report data through the Jinja2 template."""
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(
            f"Report template not found at {TEMPLATE_PATH}"
        )

    template_source = TEMPLATE_PATH.read_text(encoding="utf-8")
    env = _get_jinja_env()
    template = env.from_string(template_source)

    return str(
        template.render(
            title=report_data.title,
            generated_at=report_data.generated_at,
            domain=report_data.domain,
            collection_id=report_data.collection_id,
            executive_summary=report_data.executive_summary,
            key_findings=report_data.key_findings,
            recommendations=report_data.recommendations,
            source_tier_badge=source_tier_badge,
            sections=[
                {
                    "title": s.title,
                    "content": s.content,
                    "entries": s.items,
                }
                for s in report_data.sections
            ],
            references=report_data.references,
            appendices=report_data.appendices,
        )
    )


def _render_empty_report(domain: str) -> str:
    """Return a brief message when there are no entries for *domain*."""
    return (
        f"# {domain} \u2014 Report\n\n"
        f"This edition has no curated items yet. Check back after the next collection run."
    )


def _render_empty_report_html(domain: str) -> str:
    """Return a minimal HTML5 document when there are no entries for *domain*."""
    env = _get_jinja_env()
    template = env.get_template("report.html.j2")
    return template.render(
        title=f"{domain} \u2014 Report",
        domain_name=domain,
        period="",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        executive_summary="",
        executive_summary_html="",
        sections=[],
        references=[],
    )


def _render_report_html(report_data: ReportData, period: str = "weekly") -> str:
    """Render the report as a self-contained HTML5 document.

    Maps :class:`ReportData` to the variable contract expected by
    ``report.html.j2``:

    - ``title``, ``domain_name``, ``period``, ``generated_at`` — metadata
    - ``executive_summary`` / ``executive_summary_html`` — summary text
    - ``sections`` — list of ``{id, heading, content_html}``
    - ``references`` — list of ``{id, text, url}``

    Section ``content_html`` is built by converting the section's
    Markdown ``content`` plus its item table to HTML via the ``markdown``
    library.  References are numbered to match the template's ordered list.
    """
    env = _get_jinja_env()
    template = env.get_template("report.html.j2")

    try:
        import markdown as md_lib  # noqa: PLC0415

        def _md_to_html(md_text: str) -> str:
            return str(
                md_lib.markdown(md_text or "", extensions=["fenced_code", "tables"])
            )
    except (ImportError, ModuleNotFoundError):
        def _md_to_html(md_text: str) -> str:
            return html.escape(md_text or "").replace("\n", "<br>\n")

    html_sections: list[dict[str, Any]] = []
    for idx, section in enumerate(report_data.sections, 1):
        content_md = section.content or ""
        if section.items:
            rows = ["| # | Title | Summary |", "|---|-------|---------|"]
            row_idx = 0
            for item in section.items:
                title = item.get("title", "")
                summary = item.get("summary", "")
                # Defense-in-depth for issue #294: skip rows with empty title
                # or empty/placeholder summary (rendered as blank cells).
                if not title.strip() or _is_empty_summary(summary):
                    continue
                row_idx += 1
                rows.append(f"| {row_idx} | {title} | {summary} |")
            if row_idx:
                content_md = (content_md + "\n\n" + "\n".join(rows)).strip()

        section_id = f"section-{idx}"
        html_sections.append({
            "id": section_id,
            "heading": section.title,
            "content_html": _md_to_html(content_md),
        })

    html_references: list[dict[str, Any]] = []
    for idx, ref in enumerate(report_data.references, 1):
        title = ref.get("title", "")
        platform = ref.get("source_platform", "")
        url = ref.get("source_url", "") or ""
        text = title
        if platform:
            text = f"{title} ({platform})" if title else platform
        html_references.append({
            "id": f"ref-{idx}",
            "text": text,
            "url": url,
        })

    exec_summary = report_data.executive_summary or ""
    exec_summary_html = _md_to_html(exec_summary) if exec_summary else ""

    from autoinfo.output.seo import generate_structured_data

    ld = generate_structured_data(
        title=report_data.title,
        description=exec_summary or report_data.title,
        date_published=report_data.generated_at,
        url="",
        article_type="Report",
    )
    structured_data = f'<script type="application/ld+json">\n{ld}\n</script>'

    return template.render(
        title=report_data.title,
        domain_name=report_data.domain,
        period=period,
        generated_at=report_data.generated_at,
        executive_summary=exec_summary,
        executive_summary_html=exec_summary_html,
        key_findings=report_data.key_findings,
        recommendations=report_data.recommendations,
        sections=html_sections,
        references=html_references,
        structured_data=structured_data,
    )


# ---------------------------------------------------------------------------
# LLM-based translation (F10)
# ---------------------------------------------------------------------------

_TRANSLATION_SYSTEM_PROMPT = (
    "You are a professional medical translator. Translate the following "
    "knowledge base entry into the target language. "
    "CRITICAL: Preserve all medical terminology, drug names, procedures, "
    "and technical terms in their original form — do NOT translate terms "
    "like IVF, RCT, embryo, blastocyst, gonadotropin, etc. "
    "Keep numbers, statistics, and citations exactly as-is. "
    "Respond with valid JSON only: "
    '{"translated_title": "...", "translated_body": "..."}'
)


def _build_translation_prompt(
    title: str,
    body: str,
    target_lang: str,
    domain: str = "",
) -> str:
    """Build the user prompt for translation, optionally injecting terminology guardrails.

    When *domain* is non-empty and a ``knowledge/<domain>/_terminology.yaml``
    file exists, ``do_not_translate`` terms and ``preferred`` translations
    are injected as guardrails into the prompt.
    """
    prompt_parts: list[str] = [
        f"Target language: {target_lang}\n\n",
        f"Title: {title}\n\n",
        f"Body:\n{body}\n\n",
        "Translate the title and body above into the target language. "
        "Preserve all medical terminology, drug names, procedures, "
        "statistics, and citations exactly. Return valid JSON.\n",
    ]

    if domain:
        from autoinfo.terminology import load_terminology  # noqa: PLC0415

        terminology = load_terminology(domain)
        if terminology.terms:
            do_not_translate = [
                t for t, e in terminology.terms.items() if e.type == "do_not_translate"
            ]
            preferred = {
                t: e.preferred
                for t, e in terminology.terms.items()
                if e.type == "preferred" and e.preferred
            }
            if do_not_translate:
                prompt_parts.append(
                    "The following terms MUST NOT be translated: "
                    f"{', '.join(do_not_translate)}.\n"
                )
            if preferred:
                lines = [f"  {term} → {trans}" for term, trans in preferred.items()]
                prompt_parts.append(
                    "Use these preferred translations:\n"
                    + "\n".join(lines)
                    + "\n"
                )

    return "".join(prompt_parts)


def _call_llm_for_translation(
    title: str,
    body: str,
    target_lang: str,
    config: Config | None = None,
    domain: str = "",
) -> dict[str, str]:
    """Translate *title* and *body* into *target_lang* via LiteLLM.

    Returns a dict with ``translated_title`` and ``translated_body``.
    Returns empty strings on failure.
    """
    if config is None:
        config_path = get_config_path()
        if config_path is not None:
            try:
                config = load_config(config_path)
            except Exception:
                config = Config()
        else:
            config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    full_model = model

    user_prompt = _build_translation_prompt(
        title=title,
        body=body,
        target_lang=target_lang,
        domain=domain,
    )

    try:
        response = call_with_fallback(
            model=full_model,
            messages=[
                {"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=config.llm.json_mode and not config.llm.reasoning_model,
            max_tokens=8000,
            temperature=0.1,
            api_key=config.llm.api_key or None,
            base_url=config.llm.base_url or None,
        )
    except Exception as exc:
        logger.error("LLM translation failed: %s", exc)
        return {"translated_title": "", "translated_body": ""}

    content: str = response.choices[0].message.content or ""
    parsed = _parse_json_response(content)
    return {
        "translated_title": parsed.get("translated_title", ""),
        "translated_body": parsed.get("translated_body", ""),
    }


def localize_content(
    content_id: str | None = None,
    content: str | None = None,
    source_lang: str = "",
    target_lang: str = "",
    domain: str = "",
) -> dict[str, Any]:
    """Translate a KB entry or raw text into *target_lang*.

    Two modes:

    **Content-ID mode** (reads from KB, stores translation)::

        result = localize_content(
            content_id="kb-entry-001",
            target_lang="zh",
        )

    **Direct content mode** (no storage, returns translation)::

        result = localize_content(
            content="Hello world",
            source_lang="en",
            target_lang="fr",
        )

    Parameters
    ----------
    content_id:
        KB entry ID to translate.  The entry must exist in the KB store.
    content:
        Raw text to translate directly (no KB lookup).
    source_lang:
        Source language code (e.g. ``"en"``, ``"zh"``).  Required for
        direct-content mode; optional for content-ID mode (auto-detected
        from the KB entry's ``language`` field).
    target_lang:
        Target language code (e.g. ``"zh"``, ``"fr"``, ``"ja"``).
        **Required**.
    domain:
        Domain name (e.g. ``"medical-research"``).  When provided, loads
        domain-specific terminology guardrails from
        ``knowledge/<domain>/_terminology.yaml`` into the translation
        prompt.  When empty in content-ID mode, the domain is inferred
        from the KB entry's metadata.

    Notes
    -----
    Single-entry explicit lookup: the caller names the exact content ID
    (or provides raw text), so the end-user ``content_preference`` tier
    policy is **not applicable** here.  This is an operator tool, not a
    personalized end-user output path — preference-based filtering
    intentionally does not apply.

    Returns
    -------
    dict
        Keys:
        - ``translated_title`` — translated title (empty if direct content)
        - ``translated_body`` — translated text
        - ``target_lang`` — language code used
        - ``source_lang`` — detected or provided source language
        - ``file_path`` — path to stored translation file (content-ID mode only)
        - ``success`` — whether translation succeeded

    Raises
    ------
    ValueError
        If the required parameters are missing or *target_lang* is empty.
    """
    if not target_lang:
        raise ValueError("target_lang is required")

    if content_id:
        from autoinfo.kb import KBStore  # noqa: PLC0415

        store = KBStore()
        entry = store.get_entry(content_id)
        if entry is None:
            raise ValueError(f"KB entry '{content_id}' not found")

        resolved_domain = domain or entry.get("domain", "")
        src_lang = source_lang or entry.get("language", "en")

        file_path_str = entry.get("file_path", "")
        body = ""
        if file_path_str:
            fp = Path(file_path_str)
            if fp.is_file():
                raw = fp.read_text(encoding="utf-8")
                if raw.startswith("---"):
                    end_idx = raw.find("---", 3)
                    if end_idx != -1:
                        body = raw[end_idx + 3:].strip()
                    else:
                        body = raw
                else:
                    body = raw

        result = _call_llm_for_translation(
            title=entry.get("title", ""),
            body=body,
            target_lang=target_lang,
            domain=resolved_domain,
        )

        if not result.get("translated_title") and not result.get("translated_body"):
            return {
                "success": False,
                "error": "LLM translation returned empty result",
                "content_id": content_id,
                "target_lang": target_lang,
                "source_lang": src_lang,
            }

        translated_file_path = _write_translated_file(entry, result, src_lang, target_lang)

        return {
            "success": True,
            "translated_title": result.get("translated_title", ""),
            "translated_body": result.get("translated_body", ""),
            "target_lang": target_lang,
            "source_lang": src_lang,
            "file_path": str(translated_file_path) if translated_file_path else "",
            "content_id": content_id,
        }

    if content is not None:
        if not source_lang:
            raise ValueError("source_lang is required for direct content translation")
        result = _call_llm_for_translation(
            title="",
            body=content,
            target_lang=target_lang,
            domain=domain,
        )

        if not result.get("translated_body"):
            return {
                "success": False,
                "error": "LLM translation returned empty result",
                "target_lang": target_lang,
                "source_lang": source_lang,
            }

        return {
            "success": True,
            "translated_title": result.get("translated_title", ""),
            "translated_body": result.get("translated_body", ""),
            "target_lang": target_lang,
            "source_lang": source_lang,
        }

    raise ValueError("Either content_id or content must be provided")


def _write_translated_file(
    entry: dict[str, Any],
    translation: dict[str, str],
    source_lang: str,
    target_lang: str,
) -> Path | None:
    """Write the translated Markdown file alongside the original KB entry.

    Creates: ``knowledge/<domain>/<tier>/<topic>/<date>-<slug>.<lang>.md``

    Returns the path to the written file, or ``None`` on failure.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    original_path = entry.get("file_path", "")
    if not original_path:
        return None

    orig = Path(original_path)
    if not orig.is_file():
        return None

    translated_path = orig.with_name(
        f"{orig.stem}.{target_lang}{orig.suffix}"
    )

    raw = orig.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    body = raw
    if raw.startswith("---"):
        end_idx = raw.find("---", 3)
        if end_idx != -1:
            fm_raw = raw[3:end_idx]
            import yaml  # noqa: PLC0415
            frontmatter = yaml.safe_load(fm_raw) or {}
            body = raw[end_idx + 3:].strip()

    frontmatter["translated_from"] = source_lang
    frontmatter["translated_to"] = target_lang
    frontmatter["translated_at"] = datetime.now(timezone.utc).isoformat()
    frontmatter["original_entry_id"] = entry.get("entry_id", "")
    frontmatter["original_file"] = str(orig)

    translated_title = translation.get("translated_title", "")
    if translated_title:
        frontmatter["title"] = translated_title

    translated_body = translation.get("translated_body", body)

    full_content = (
        "---\n"
        f"{yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)}"
        "---\n\n"
        f"{translated_body}"
    )
    translated_path.write_text(full_content, encoding="utf-8")
    return translated_path


# ---------------------------------------------------------------------------
# Tutorial generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Report / Digest audience adaptation (structured prompt sections)
# ---------------------------------------------------------------------------

_REPORT_AUDIENCE_PROMPTS: dict[str, str] = {
    "researcher": (
        "Structure the summary with: Methods & Data Sources, Key Results, "
        "Limitations, Discussion. Use technical terminology and cite "
        "specific findings where possible."
    ),
    "executive": (
        "Structure the summary with: Key Findings, Strategic Implications, "
        "Recommended Actions. Keep language concise and actionable."
    ),
    "investor": (
        "Structure the summary with: Market Context, Opportunities & Risks, "
        "Competitive Position. Focus on growth potential and ROI."
    ),
    "clinician": (
        "Structure the summary with: Practical Applications, Clinical "
        "Guidelines, Patient Outcomes. Emphasize actionable takeaways."
    ),
    "student": (
        "Structure the summary with: Foundational Concepts, Step-by-Step "
        "Explanations, Key Definitions, Study Takeaways. Use accessible language."
    ),
    "general": "",  # no special structure — existing behavior
}

_VALID_REPORT_AUDIENCES: list[str] = list(_REPORT_AUDIENCE_PROMPTS.keys())

# ---------------------------------------------------------------------------
# Report type prompts — specialized section structures per report type
# ---------------------------------------------------------------------------

_REPORT_TYPE_PROMPTS: dict[str, str] = {
    "standard": "",
    "industry": (
        "Structure this report with sections: Industry Overview, "
        "Key Developments, Regulatory Landscape, Competitive Dynamics, "
        "Outlook. Focus on domain-specific trends (e.g. clinical trials "
        "for medical, earnings for financial, funding rounds for tech)."
    ),
    "competitive": (
        "Structure this report with sections: Market Players, "
        "Head-to-Head Comparison (organize into comparison tables by "
        "feature/offering), Strengths & Weaknesses, Strategic Moves, "
        "Market Share Analysis. Extract entity names and compare them "
        "explicitly."
    ),
    "trend": (
        "Structure this report with sections: Trend Overview, Timeline "
        "of Developments (chronological), Change Detection (what changed "
        "in the last N months), Momentum Indicators, Forward-Looking "
        "Signals. Focus on time-based patterns and trajectory."
    ),
    "daily-briefing": (
        "Structure this briefing with sections: Top Stories (max 5, "
        "priority-ordered by relevance score), Need-to-Know Updates, "
        "Briefing Summary (3 bullet points max). Be concise. Prioritize "
        "high-relevance items (relevance_score > 50)."
    ),
    "column": (
        "Structure this column with sections: The Big Idea (single-theme "
        "thesis in an expert persona voice), Deep Dive (longer-form analysis "
        "with evidence, sources, and nuance), What Changed This Week (weekly "
        "cadence — timeline of developments in the period), Implications & "
        "Outlook, Reader Takeaways. Write in a confident expert persona with "
        "analytical depth; this is a longer-form premium column, not a "
        "briefing. Prioritize high-relevance items (relevance_score > 50).\n"
        "The Deep Dive section MUST contain 8-10 distinct subsections "
        "(numbered or headed), each with 2-3 paragraphs of analysis grounded "
        "in specific entries — quote concrete numbers, dates, and named "
        "companies/studies from the source material; no filler paragraphs. "
        "Target total column length 2000-3000 words."
    ),
}

_VALID_REPORT_TYPES: list[str] = list(_REPORT_TYPE_PROMPTS.keys())

# Product-family synthesis sections appended to the report-synthesis prompt
# (spec §2.4, todo 7), keyed by the resolved product family so the default
# ``report`` family stays unchanged. ``implications`` / ``risks`` /
# ``action_required`` are index-aligned 1:1 with ``key_findings`` (spec
# §5.2-5.4 per-takeaway pairing); ``key_metrics`` is enterprise-only.
# The ``|``-delimited line formats below are parsed by
# :func:`_parse_report_markdown` into ``{title, likelihood, impact,
# mitigation}`` / ``{metric, value, source}`` dicts.
_REPORT_PRODUCT_BASE_SECTIONS = (
    "Additionally, append these product sections with exactly one item per "
    "Key Finding bullet, index-aligned 1:1 (item N corresponds to Key "
    "Finding N):\n\n"
    "## Implications\n"
    "- <implication for finding 1>\n"
    "- <implication for finding 2>\n\n"
    "## Risks & Opportunities\n"
    "- <risk title> | <likelihood> | <impact> | <mitigation>\n"
    "(one bullet per finding, same order; likelihood/impact values: "
    "High/Medium/Low)\n"
    "Every risk title MUST embed a concrete number, case, or named entity "
    "from the source entries — no generic labels like 'Valuation Bubble "
    "Risk'. Examples: 'Fintech down-rounds up 3.2x YoY (CB Insights)', "
    "'Stripe API latency 2.1s in APAC peak'. The mitigation MUST name a "
    "specific action, who does it, and a timeline (e.g. 'Switch 30% of "
    "traffic to the fallback provider by 2026-09-30').\n\n"
    "## Action Required\n"
    "- <action for finding 1>\n"
    "- <action for finding 2>\n"
    "(index-aligned with Key Findings; each action MUST specify WHO does it, "
    "WHAT specifically, and a WHEN timeline — e.g. 'CMO: ship the Q3 pricing "
    "experiment to 10% of enterprise customers by 2026-09-15'. Never a bare "
    "'conduct market analysis'.)\n"
    "Each action MUST also name a concrete object (WHICH entity, product, "
    "model, company, or metric the action targets) and a timeframe or trigger "
    "(WHEN it happens — a date, a milestone, or a real-world trigger event). "
    "A bare single-line verb like 'Track AI model releases', 'Monitor "
    "developments', or 'Reassess the market' carries no object and no WHEN — "
    "it is forbidden.  Prefer e.g. 'Track OpenAI GPT-5 benchmark results "
    "against internal evaluation needs by 2026-09-30' or 'Monitor Stripe "
    "latency SLO breaches; reassess the primary provider when p95 exceeds "
    "800ms'.\n\n"
    "The Executive Summary's opening coverage sentence MUST name exactly the "
    "number of Key Findings you detail below — e.g. \"This briefing details N "
    "selected items from the period.\" Never state a coverage count larger "
    "than the number of Key Findings bullets you actually write."
)

_REPORT_ENTERPRISE_METRICS_SECTION = (
    "\n\n## Key Metrics\n"
    "- <metric> | <value> | <source>\n"
    "(quantified metrics from the entries only; one bullet per metric; "
    "source names the entry, study, or dataset)"
)

_REPORT_PRODUCT_SYNTHESIS_PROMPTS: dict[str, str] = {
    "premium-briefing": _REPORT_PRODUCT_BASE_SECTIONS,
    "magazine-digest": _REPORT_PRODUCT_BASE_SECTIONS,
    "enterprise-briefing": (
        _REPORT_PRODUCT_BASE_SECTIONS + _REPORT_ENTERPRISE_METRICS_SECTION
    ),
}

_REPORT_AUDIENCE_DESCRIPTIONS: dict[str, str] = {
    "researcher": "technical depth, citations, methodology focus, statistical rigor",
    "executive": "strategic overview, ROI, competitive landscape, high-level implications",
    "investor": "market context, opportunities & risks, competitive position, growth potential",
    "clinician": "practical application, clinical guidelines, patient outcomes, treatment protocols",  # noqa: E501
    "student": "foundational concepts, simplified explanations, step-by-step learning, study aids",
    "general": "balanced overview suitable for any audience — no special structure applied",
}

# ---------------------------------------------------------------------------
# Tutorial / Presentation audience adaptation (must match report vocab)
# ---------------------------------------------------------------------------

_VALID_AUDIENCES = frozenset(_VALID_REPORT_AUDIENCES)

_AUDIENCE_DESCRIPTIONS: dict[str, str] = dict(_REPORT_AUDIENCE_DESCRIPTIONS)


def _filter_stale_entries(
    entries: list[dict[str, Any]],
    domain: str,
    *,
    include_stale: bool = False,
    product: str = "product",
) -> list[dict[str, Any]]:
    """Drop entries older than the domain's freshness threshold (TTL).

    Mirrors the digest staleness filter (F51) so teaching-layer products
    (tutorial/presentation) never silently regenerate from an old corpus
    after a source swap (backup issue #60).

    Returns a NEW list containing only non-stale entries (TTL resolution
    from config, defaults ``ttl_days=90`` / ``freshness_threshold=0.5``).
    """
    if include_stale:
        return list(entries)
    ttl_days = 90
    freshness_threshold = 0.5
    try:
        from autoinfo.config import get_config_path, load_config  # noqa: PLC0415

        config_path = get_config_path()
        if config_path and config_path.is_file():
            cfg = load_config(config_path)
            for dc in cfg.domains:
                if dc.name == domain:
                    ttl_days = dc.ttl_days
                    freshness_threshold = dc.freshness_threshold
                    break
    except Exception:
        pass

    from autoinfo.kb import calculate_freshness_score  # noqa: PLC0415

    active: list[dict[str, Any]] = []
    excluded = 0
    for entry in entries:
        entry_freshness = calculate_freshness_score(entry, ttl_days)
        entry["freshness_score"] = round(entry_freshness, 4)
        if entry_freshness < freshness_threshold:
            entry["is_stale"] = True
            excluded += 1
        else:
            entry["is_stale"] = False
            active.append(entry)
    if excluded:
        logger.info(
            "Excluded %d stale entries from %s for domain '%s'",
            excluded, product, domain,
        )
    return active


def generate_tutorial(
    domain: str,
    collection_id: str | None = None,
    target_audience: str = "student",
    format: str = "markdown",
    custom_instructions: str = "",
    user_id: str = "",
    delivery_gate_configs: dict[str, dict[str, Any]] | _DeliveryGatesBypass | None = None,
    llm_config: Config | None = None,
    include_stale: bool = False,
) -> str | DeliveryOutput:
    """Generate a structured tutorial for *domain*, adapted to *target_audience*.

    Fetches KB entries, asks the LLM to structure a learning path with
    objectives, content sections, and exercises, then renders the result
    through ``tutorial.md.j2``.

    Parameters
    ----------
    domain : str
        Domain to generate the tutorial for (e.g. ``"medical-research"``).
    collection_id : str, optional
        Optional collection ID to scope the tutorial to a specific
        collection run.  When omitted, all KB entries for the domain
        are included.
    target_audience : str
        Intended audience for the tutorial.  One of ``"researcher"``,
        ``"clinician"``, ``"executive"``, ``"student"`` (default).
    format : str, optional
        Output format (default ``"markdown"``).  Only ``"markdown"``
        is currently supported.
    custom_instructions : str, optional
        Optional string of additional instructions to append to the LLM
        generation prompt.  Ignored when empty/absent.
    user_id : str, optional
        Optional end-user ID.  When non-empty, the user's stored
        ``content_preference`` (from
        :func:`autoinfo.user_store.get_preferences`) is auto-loaded and
        KB entries are tier-filtered accordingly (B-001).  When empty
        (default), behavior is unchanged and all tiers are included.

    Returns
    -------
    str
        Rendered tutorial string.

    Raises
    ------
    ValueError
        If *format* or *target_audience* is unsupported.
    """
    if format not in ("markdown", "agent"):
        raise ValueError(
            f"Unsupported output format: {format!r}. "
            f"Supported: markdown, agent"
        )

    if target_audience not in _VALID_AUDIENCES:
        raise ValueError(
            f"Invalid target_audience '{target_audience}'. "
            f"Must be one of: {', '.join(sorted(_VALID_AUDIENCES))}"
        )

    # --- Resolve delivery-gate config (issue #298: default-on in production) --
    delivery_gate_configs = _resolve_delivery_gate_configs(domain, delivery_gate_configs)

    # -- Load KB entries --------------------------------------------------
    kb_store = KBStore()
    entries = kb_store.list_entries(domain, limit=5000)

    # --- Content-preference tier filtering (B-001) ---------------------------
    content_preference: str = _resolve_content_preference(user_id)
    if content_preference != "both":
        filtered_entries = _filter_entries_by_content_preference(
            entries, content_preference
        )
        if len(filtered_entries) != len(entries):
            logger.info(
                "Excluded %d entries from tutorial for domain '%s' "
                "due to content_preference='%s'",
                len(entries) - len(filtered_entries),
                domain,
                content_preference,
            )
        entries = filtered_entries

    # --- Test/empty entry filtering (issue #298 — layer 1) -------------------
    entries = _filter_product_entries(entries)

    # --- Per-domain exclude_keywords filter (issue #319) ---------------------
    # Cross-domain noise guard: drop entries matching their own domain's
    # exclude_keywords blacklist BEFORE LLM synthesis / KB-derived sections.
    entries = _filter_entries_by_domain_exclusions(entries, domain)

    # --- Language-learning wiring (backup #59/#61/#63) -----------------------
    # Language-learning domains (default_language set) get: (1) a topic-level
    # guard dropping entries that teach a language OTHER than the domain's
    # target (#63, e.g. a Spanish grammar post in english-learning — the
    # language filter cannot catch English-written posts about another
    # language), and (2) a language-teaching tutorial prompt instead of the
    # generic news-structure prompt (#59/#61).
    lang_learning = _is_lang_learning_domain(domain)
    target_language = (
        (
            _resolve_effective_language(language="", domain=domain)
            or _seed_domain_default_language(domain)
        )
        if lang_learning
        else ""
    )
    if lang_learning and target_language:
        entries = _filter_foreign_language_teaching_entries(entries, target_language)

    # --- Staleness filter (backup #60) ---------------------------------------
    # Teaching-layer products must never silently regenerate from an old
    # corpus (e.g. 2024 Corriere after a source swap to ANSA).  Mirror the
    # digest freshness filter; all-stale raises StaleSourceError (plain path)
    # or blocks delivery (DeliveryOutput path) instead of shipping a stale
    # empty-shell product.
    prior_count = len(entries)
    entries = _filter_stale_entries(
        entries, domain, include_stale=include_stale, product="tutorial"
    )
    if not include_stale and prior_count > 0 and not entries:
        stale_msg = (
            f"All {prior_count} candidate entries for domain '{domain}' are stale. "
            f"Refusing to generate an empty-shell tutorial from old corpus. "
            f"Re-run collection to refresh the source, or pass include_stale=true."
        )
        if delivery_gate_configs is not None:
            return DeliveryOutput(
                output="",
                gate_results={},
                delivery_blocked=True,
                delivery_format=format,
                warnings=[f"STALE_SOURCE: {stale_msg}"],
            )
        raise StaleSourceError(stale_msg)

    if not entries:
        if format == "agent":
            return json.dumps(
                {
                    "@context": _JSONLD_TUTORIAL["@context"],
                    "@type": _JSONLD_TUTORIAL["@type"],
                    "error": {
                        "code": "EMPTY_CONTENT",
                        "message": (
                            f"No curated items are available for domain '{domain}' yet. "
                            "Cannot generate an agent-format tutorial."
                        ),
                    },
                    "entries": [],
                },
                indent=2,
                ensure_ascii=False,
            )
        empty_md = (
            f"# {domain} — Tutorial\n\n"
            f"This edition has no curated items yet. Check back after the next collection run."
        )
        if delivery_gate_configs is not None:
            result = _apply_delivery_gates(
                rendered_output=empty_md,
                output_format=format,
                entries=[],
                context={},
                product_type="tutorial",
                delivery_gate_configs=delivery_gate_configs,
                llm_config=llm_config,
            )
            return _apply_min_content_guard(result, [], "tutorial")
        return empty_md

    # -- Build LLM prompt with audience adaptation ------------------------
    audience_desc = _AUDIENCE_DESCRIPTIONS.get(target_audience, "general audience")
    entry_summaries = "\n".join(
        f"- [{e.get('entry_id', '?')}] {e.get('title', '?')}: "
        f"{e.get('summary', '(no summary)')}"
        + (f" (Source: {e['source_url']})" if e.get("source_url") else "")
        for e in entries
    )

    if format == "agent":
        prompt = _build_tutorial_json_prompt(
            target_audience,
            audience_desc,
            entry_summaries,
            custom_instructions,
            lang_learning=lang_learning,
            target_language=target_language,
        )
    else:
        prompt = _build_tutorial_markdown_prompt(
            target_audience,
            audience_desc,
            entry_summaries,
            custom_instructions,
            lang_learning=lang_learning,
            target_language=target_language,
        )

    llm_result = _call_llm_for_tutorial(prompt)

    # -- Deterministic completeness (markdown path) --------------------------
    # DeepSeek-V4-Flash does not reliably emit the tutorial schema as
    # parseable JSON or markdown with a stable shape.  Ensure a domain that
    # HAS entries never renders the all-empty template: replace an unusable
    # LLM result entirely and fill any still-missing sections from KB entries.
    if format in ("markdown", "agent"):
        # Deterministic completeness: DeepSeek-V4-Flash does not reliably
        # emit the tutorial schema as parseable JSON/markdown.  A domain
        # that HAS entries must never render an empty tutorial — for
        # markdown AND agent (agent consumes the same KB-derived content;
        # without this, an empty LLM result yields slides/steps=[] shells,
        # e.g. 26 empty tutorial-agent artifacts in the 2026-08-11 fill
        # run).
        if not _tutorial_has_content(llm_result):
            logger.warning(
                "Tutorial LLM output unusable for domain '%s' (missing "
                "objectives/content); falling back to KB-derived tutorial",
                domain,
            )
        llm_result = _ensure_tutorial_complete(
            llm_result, domain, entries, target_audience,
            lang_learning=lang_learning,
            target_language=target_language,
        )

    # -- Build template context -------------------------------------------
    generated_at = datetime.now(timezone.utc).isoformat()

    def _coerce_exercise(item: Any) -> dict[str, str]:
        """Normalize one exercise entry to the ``{title, description}`` shape.

        LLM results occasionally carry plain strings (or scalars) instead of
        objects; rendering those through ``{{ exercise.title }}`` leaks
        Jinja's method-object repr into the product (backup-repo #22-#37
        matrix `_no_placeholder` P0 on gaming tutorial).
        """
        if isinstance(item, dict):
            return {
                "title": str(item.get("title") or item.get("question") or ""),
                "description": str(item.get("description") or ""),
            }
        return {"title": str(item), "description": ""}

    exercises_raw = llm_result.get("exercises", [])
    if isinstance(exercises_raw, list):
        exercises = [_coerce_exercise(item) for item in exercises_raw]
    else:
        exercises = []

    context = {
        "title": llm_result.get("title", f"{domain} — Tutorial"),
        "domain": domain,
        "target_audience": target_audience,
        "collection_id": collection_id or "",
        "duration": llm_result.get("duration", "TBD"),
        "prerequisites": llm_result.get("prerequisites", "None"),
        "objectives": llm_result.get("objectives", []),
        "content": llm_result.get("content", []),
        "exercises": exercises,
        "summary": llm_result.get("summary", ""),
        "further_reading": llm_result.get("further_reading", []),
        "generated_at": generated_at,
        "vocabulary": llm_result.get("vocabulary", []),
        "grammar": llm_result.get("grammar", []),
    }

    # -- Agent-native JSON-LD format ----------------------------------------
    if format == "agent":
        rendered_agent = _render_tutorial_agent_json(
            llm_result, domain, target_audience, generated_at, entries
        )
        _fire_agent_notification(
            "new_tutorial", rendered_agent, product_id=f"{domain}-tutorial"
        )
        return rendered_agent

    # -- Render via Jinja2 template ---------------------------------------
    rendered_tutorial = _render_tutorial_template(context)

    # --- Delivery gates (D1-D3) ---------------------------------------------
    if delivery_gate_configs is not None:
        result = _apply_delivery_gates(
            rendered_output=rendered_tutorial,
            output_format=format,
            entries=entries,
            context=context,
            product_type="tutorial",
            delivery_gate_configs=delivery_gate_configs,
            llm_config=llm_config,
        )
        result = _apply_min_content_guard(result, entries, "tutorial")
        if user_id:
            _try_notify_content_ready(
                user_id=user_id,
                product_type="tutorial",
                title=f"{domain} — Tutorial",
            )
        _fire_agent_notification(
            "new_tutorial",
            result.output if isinstance(result, DeliveryOutput) else rendered_tutorial,
            product_id=f"{domain}-tutorial",
        )
        return result

    _fire_agent_notification(
        "new_tutorial", rendered_tutorial, product_id=f"{domain}-tutorial"
    )
    return rendered_tutorial


def _render_tutorial_agent_json(
    llm_result: dict[str, Any],
    domain: str,
    target_audience: str,
    generated_at: str,
    entries: list[dict[str, Any]],
) -> str:
    """Render tutorial data as agent-native JSON-LD (``@type: KnowledgeTutorial``)."""
    # Derive source entries from KB
    source_entries: list[dict[str, Any]] = []
    for e in entries[:50]:
        source_entries.append({
            "entry_id": e.get("entry_id", ""),
            "title": e.get("title", ""),
            "source_url": e.get("source_url", ""),
            "source_platform": e.get("source_platform", ""),
        })

    # Build steps from content sections
    steps: list[dict[str, Any]] = []
    for i, section in enumerate(llm_result.get("content", []), 1):
        steps.append({
            "step": i,
            "heading": section.get("heading", ""),
            "body": section.get("body", ""),
            "code_example": section.get("code_example"),
            "code_language": section.get("code_language"),
            "key_takeaway": section.get("key_takeaway"),
        })

    # Build exercises
    exercises: list[dict[str, Any]] = []
    for ex in llm_result.get("exercises", []):
        exercises.append({
            "title": ex.get("title", ""),
            "description": ex.get("description", ""),
            "hint": ex.get("hint"),
            "solution": ex.get("solution"),
        })

    output: dict[str, Any] = {
        **_JSONLD_TUTORIAL,
        "uuid": str(uuid.uuid4()),
        "title": llm_result.get("title", f"{domain} — Tutorial"),
        "domain": domain,
        "target_audience": target_audience,
        "duration": llm_result.get("duration", "TBD"),
        "prerequisites": llm_result.get("prerequisites", ""),
        "objectives": llm_result.get("objectives", []),
        "steps": steps,
        "exercises": exercises,
        "summary": llm_result.get("summary", ""),
        "further_reading": llm_result.get("further_reading", []),
        "source_entries": source_entries,
        "generated_at": generated_at,
        "metadata": {
            "entry_count": len(entries),
            "step_count": len(steps),
            "exercise_count": len(exercises),
        },
    }
    return json.dumps(output, indent=2, ensure_ascii=False, default=str)


def _call_llm_for_tutorial(prompt: str) -> dict[str, Any]:
    """Call LiteLLM to generate structured tutorial content.

    Uses the same pattern as ``_call_llm_for_digest``.
    """
    config_path = get_config_path()
    if config_path and config_path.is_file():
        try:
            config = load_config(config_path)
        except Exception:
            config = Config()
    else:
        config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    full_model = model

    try:
        response = call_with_fallback(
            model=full_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a tutorial designer. Given knowledge base "
                    "entries, structure them into a coherent learning path. "
                    "Respond with valid JSON only, no markdown formatting.",
                },
                {"role": "user", "content": prompt},
            ],
            json_mode=config.llm.json_mode and not config.llm.reasoning_model,
            max_tokens=8000,
            temperature=0.1,
            api_key=config.llm.api_key or None,
            base_url=config.llm.base_url or None,
        )
    except Exception as exc:
        logger.error("Tutorial generation failed: %s", exc)
        return {}
    content: str = response.choices[0].message.content or ""
    if not content:
        return {}
    parsed = _parse_json_response(content)
    if parsed:
        return parsed
    return _parse_tutorial_markdown(content)


def _build_tutorial_json_prompt(
    target_audience: str,
    audience_desc: str,
    entry_summaries: str,
    custom_instructions: str,
    *,
    lang_learning: bool = False,
    target_language: str = "",
) -> str:
    """Build the structured-JSON tutorial prompt (agent-native format path).

    For language-learning domains (*lang_learning* + *target_language*),
    the schema gains ``vocabulary`` and ``grammar`` arrays and the content is
    required to be written in the target language (backup #59/#61).  A
    no-fabricated-causal-attribution constraint is always appended (#62).
    """
    prompt = (
        f"You are a tutorial designer creating content for a {target_audience} "
        f"audience ({audience_desc}). "
        "Given the following knowledge base entries, structure them into a "
        "coherent learning path. "
        "Return a JSON object with the following fields:\n"
        '  - "title": tutorial title (string)\n'
        '  - "duration": estimated reading/completion time (string, e.g. "45 minutes")\n'
        '  - "prerequisites": comma-separated prerequisites (string)\n'
        '  - "objectives": array of 3-5 learning objective strings\n'
        '  - "content": array of section objects, each with:\n'
        '      - "heading": section heading\n'
        '      - "body": 2-4 paragraph section content\n'
        '      - "code_example": optional code/example snippet (string or null)\n'
        '      - "code_language": language for the code snippet (string or null)\n'
        '      - "key_takeaway": one-line takeaway (string or null)\n'
        '  - "exercises": array of exercise objects, each with:\n'
        '      - "title": exercise title\n'
        '      - "description": exercise description\n'
        '      - "hint": optional hint (string or null)\n'
        '      - "solution": optional solution (string or null)\n'
        '  - "summary": 2-3 sentence summary of the tutorial\n'
        '  - "further_reading": array of reference strings\n\n'
        f"KB Entries:\n{entry_summaries}\n\n"
        "In every \"content\" section body, follow each key claim with an "
        "inline citation to its source entry, e.g. \"(Source: <source_url>)\". "
        "Only cite URLs present in the KB Entries list.\n"
        "Return all fields in a single JSON object. Adapt depth, terminology, "
        f"and examples specifically for a {target_audience} audience."
    )
    if lang_learning and target_language:
        lang_label = _lang_display_name(target_language)
        prompt += (
            f"\n\nThis is a LANGUAGE-LEARNING tutorial for {lang_label}. "
            "Write the tutorial as a language course, not a news summary:\n"
            "- \"objectives\" MUST be language-ability goals for learners of "
            f"{lang_label} (e.g. \"Understand how to report on current "
            "events in the target language\"), NOT copies of the KB entry titles.\n"
            f"- \"content\" sections MUST be written IN {lang_label} "
            "(target-language prose adapted to a graded learner level), not "
            "an English retelling.\n"
            '- add two extra keys to the JSON: "vocabulary" (array of objects '
            'with "word" (in target language), "pos" (part of speech), '
            '"translation", "example" (a sentence in the target language)) '
            'and "grammar" (array of objects with "point" (grammar rule name), '
            '"explanation", "example" (target-language example)).\n'
            f'- "exercises" MUST be {lang_label} exercises (fill-in-the-blank, '
            f"translation, sentence construction in {lang_label}), not "
            "English comprehension questions.\n"
        )
    prompt += (
        "\nDo NOT add causal attributions, motivations, or explanations (e.g. "
        "'due to COVID-19 concerns', 'likely because of') that the source "
        "entries do not explicitly state. Only restate causes actually present "
        "in the source material."
    )
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"
    return prompt


def _build_tutorial_markdown_prompt(
    target_audience: str,
    audience_desc: str,
    entry_summaries: str,
    custom_instructions: str,
    *,
    lang_learning: bool = False,
    target_language: str = "",
) -> str:
    """Build the flat-markdown tutorial prompt (robust markdown render path).

    Plain markdown with fixed heading markers is far more reliably emitted by
    the default model than the nested tutorial JSON schema, and the response is
    parsed by heading instead of ``json.loads``.

    For language-learning domains (*lang_learning* + *target_language*), the
    required structure gains ``## Vocabulary`` and ``## Grammar`` sections and
    the body/exercises must be written in the target language (backup #59/#61).
    A no-fabricated-causal-attribution constraint is always appended (#62).
    """
    prompt = (
        f"You are a tutorial designer creating content for a {target_audience} "
        f"audience ({audience_desc}). "
        "Given the following knowledge base entries, structure them into a "
        "coherent learning path. "
        "Return plain Markdown with this exact structure:\n\n"
        "# <tutorial title>\n"
        "Duration: <estimated reading/completion time, e.g. '45 minutes'>\n"
        "Prerequisites: <comma-separated prerequisites or 'None'>\n\n"
        "## Learning Objectives\n"
        "- <objective 1>\n"
        "- <objective 2>\n"
        "- <objective 3>\n\n"
        "## Content\n"
        "### <section heading 1>\n"
        "<2-4 paragraphs of section content>\n"
        "### <section heading 2>\n"
        "<2-4 paragraphs of section content>\n\n"
        "## Exercises\n"
        "- <exercise 1>\n"
        "- <exercise 2>\n\n"
        "## Summary\n"
        "<2-3 sentence summary>\n\n"
        "## Further Reading\n"
        "- <reference 1>\n"
        "- <reference 2>\n\n"
        "In every content paragraph, follow each key claim with an inline "
        "citation to its source entry, e.g. \"(Source: <source_url>)\". Only "
        "cite URLs present in the KB Entries list.\n\n"
        "Use exactly the heading names above. Do NOT wrap your answer in a "
        "code fence or emit JSON.\n\n"
        f"KB Entries:\n{entry_summaries}\n\n"
        "Adapt depth, terminology, and examples specifically for a "
        f"{target_audience} audience."
    )
    if lang_learning and target_language:
        lang_label = _lang_display_name(target_language)
        prompt += (
            f"\n\nThis is a LANGUAGE-LEARNING tutorial for {lang_label}. "
            "Write the tutorial as a language course, not a news summary:\n"
            f"- Learning Objectives MUST be language-ability goals for learners "
            f"of {lang_label} (e.g. \"Understand how to report on current "
            "events in the target language\"), NOT copies of the KB article titles.\n"
            f"- The tutorial body MUST be written in the target language "
            f"({lang_label}); target-language prose adapted to a graded "
            "learner level, not an English retelling. Only technical terms may "
            "stay in the source language.\n"
            "- Add a '## Vocabulary' section listing 6-10 target-language words "
            "from the entries, each bullet: '<word> — <part of speech> — "
            "<translation> — <example sentence in the target language>'.\n"
            "- Add a '## Grammar' section listing 2-3 grammar points relevant "
            "to the content, each bullet: '<grammar point> — <rule> — "
            "<example in the target language>'.\n"
            f"- Exercises MUST be written in the target language "
            f"(fill-in-the-blank, translation, sentence construction in "
            f"{lang_label}), not English comprehension questions.\n"
        )
    prompt += (
        "\nDo NOT add causal attributions, motivations, or explanations (e.g. "
        "'due to COVID-19 concerns', 'likely because of') that the source "
        "entries do not explicitly state. Only restate causes actually present "
        "in the source material."
    )
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"
    return prompt


def _parse_tutorial_markdown(content: str) -> dict[str, Any]:
    """Parse a markdown tutorial response into the tutorial context schema.

    Handles the structure requested by ``_build_tutorial_markdown_prompt``:
    ``# title``, optional ``Duration:`` / ``Prerequisites:`` lines,
    ``## Learning Objectives`` bullets, ``## Content`` with ``### <heading>``
    subsections, ``## Exercises`` bullets or ``### Exercise N:`` headings,
    ``## Summary`` paragraph and ``## Further Reading`` bullets.  Returns
    ``{}`` when *content* is empty.
    """
    if not content:
        return {}
    result: dict[str, Any] = {
        "title": "",
        "duration": "",
        "prerequisites": "",
        "objectives": [],
        "content": [],
        "exercises": [],
        "summary": "",
        "further_reading": [],
        "vocabulary": [],
        "grammar": [],
    }
    current_section = ""
    content_heading = ""
    content_body: list[str] = []
    exercise_title = ""
    exercise_body: list[str] = []

    def flush_content() -> None:
        nonlocal content_heading, content_body
        if content_heading:
            result["content"].append(
                {
                    "heading": content_heading,
                    "body": "\n\n".join(line.strip() for line in content_body).strip(),
                }
            )
            content_heading = ""
            content_body = []

    def flush_exercise() -> None:
        nonlocal exercise_title, exercise_body
        if exercise_title:
            result["exercises"].append(
                {
                    "title": exercise_title,
                    "description": "\n\n".join(
                        line.strip() for line in exercise_body
                    ).strip(),
                }
            )
            exercise_title = ""
            exercise_body = []

    def is_bullet(text: str) -> bool:
        return bool(
            re.match(r"^(?:[-*]|\d+[.)])\s+\S", text)
        )

    def bullet_text(text: str) -> str:
        return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", text).strip()

    for raw in content.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            result["title"] = stripped.lstrip("#").strip()
            continue
        if not current_section and (
            stripped.lower().startswith("duration:")
            or stripped.lower().startswith("prerequisites:")
        ):
            key, _, value = stripped.partition(":")
            result[key.strip().lower()] = value.strip()
            continue
        if stripped.startswith("## "):
            flush_content()
            flush_exercise()
            current_section = stripped.lstrip("#").strip()
            continue
        if current_section in ("Learning Objectives", "Learning Goals"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["objectives"].append(item)
            continue
        if current_section == "Content":
            if stripped.startswith("### "):
                flush_content()
                content_heading = stripped.lstrip("#").strip()
                content_body = []
            elif content_heading and stripped:
                content_body.append(stripped)
            continue
        if current_section in ("Exercises", "Practice", "Practice Exercises"):
            if stripped.startswith("### "):
                flush_exercise()
                heading = stripped.lstrip("#").strip()
                exercise_title = re.sub(
                    r"^Exercise\s*(\d+)?\s*[:.)-]?\s*",
                    "",
                    heading,
                    flags=re.IGNORECASE,
                ).strip() or heading
                exercise_body = []
            elif is_bullet(stripped):
                flush_exercise()
                item = bullet_text(stripped)
                if item:
                    result["exercises"].append({"title": item, "description": ""})
            elif exercise_title and stripped:
                exercise_body.append(stripped)
            continue
        if current_section in ("Summary", "Conclusion", "Wrap-Up"):
            if stripped:
                result["summary"] = (result["summary"] + " " + stripped).strip()
            continue
        if current_section in ("Further Reading", "References", "Resources"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["further_reading"].append(item)
            elif stripped and not line.startswith(("---", "***")):
                result["further_reading"].append(stripped)
            continue
        if current_section in ("Vocabulary", "Key Vocabulary", "Word List"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["vocabulary"].append(item)
            continue
        if current_section in ("Grammar", "Grammar Points", "Grammar Notes"):
            if is_bullet(stripped):
                item = bullet_text(stripped)
                if item:
                    result["grammar"].append(item)
            continue
    flush_content()
    flush_exercise()
    return result


def _tutorial_has_content(result: dict[str, Any]) -> bool:
    """True when a tutorial LLM result carries real objectives and content."""
    return bool(result.get("objectives")) and bool(result.get("content"))


def _entry_derived_sections(
    entries: list[dict[str, Any]],
    *,
    lang_learning: bool = False,
    target_language: str = "",
) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]], list[str]]:
    """Derive objectives/content/exercises/further-reading from KB entries.

    For language-learning domains (*lang_learning* + *target_language*), the
    KB-derived fallback exercises become target-language writing practice
    instead of English "key finding" questions (backup #59).
    """
    objectives: list[str] = []
    content: list[dict[str, str]] = []
    exercises: list[dict[str, str]] = []
    further_reading: list[str] = []
    for index, entry in enumerate(entries):
        title = entry.get("title") or f"Entry {index + 1}"
        summary = entry.get("summary") or "(no summary available)"
        if len(objectives) < 5:
            objectives.append(title)
        body = summary
        url = entry.get("source_url")
        if url:
            body += f" (Source: {url})"
        content.append({"heading": title, "body": body})
        lang_label = target_language or "the target language"
        exercises.append(
            {
                "title": f"Write a {len(body.split()):d}-word summary",
                "description": (
                    f"Read '{title}' and write a short summary in {lang_label}. "
                    "Use at least 3 words or phrases from the article."
                ),
            }
            if lang_learning
            else {
                "title": f"What is the key finding in '{title}'?",
                "description": (
                    f"Summarize the main finding or conclusion of the entry "
                    f"'{title}' in one or two sentences."
                ),
            }
        )
        if url and url not in further_reading:
            further_reading.append(url)
    return objectives[:5], content, exercises, further_reading[:20]


def _ensure_tutorial_complete(
    llm_result: dict[str, Any],
    domain: str,
    entries: list[dict[str, Any]],
    target_audience: str,
    *,
    lang_learning: bool = False,
    target_language: str = "",
) -> dict[str, Any]:
    """Guarantee the markdown tutorial never renders the all-empty template.

    Keeps every usable field from *llm_result* (title, duration, objectives,
    content, …) and fills any missing or empty section from the KB entries,
    so a domain that HAS entries always produces a complete tutorial.
    """
    objectives, content, exercises, further_reading = _entry_derived_sections(
        entries,
        lang_learning=lang_learning,
        target_language=target_language,
    )
    return {
        "title": llm_result.get("title") or f"{domain} — Tutorial",
        "duration": llm_result.get("duration") or f"{len(entries)} minutes",
        "prerequisites": llm_result.get("prerequisites") or "None",
        "objectives": llm_result.get("objectives") or objectives,
        "content": llm_result.get("content") or content,
        "exercises": llm_result.get("exercises") or exercises,
        "summary": llm_result.get("summary") or (
            f"This tutorial walks through {len(entries)} knowledge base "
            f"entries in the {domain} domain, covering the key findings "
            f"for a {target_audience} audience."
        ),
        "further_reading": llm_result.get("further_reading") or further_reading,
        "vocabulary": llm_result.get("vocabulary") or [],
        "grammar": llm_result.get("grammar") or [],
    }


def _render_tutorial_template(context: dict[str, Any]) -> str:
    """Render the tutorial data through ``tutorial.md.j2``."""
    env = _get_jinja_env()
    template = env.get_template("tutorial.md.j2")
    return template.render(**context)


# ---------------------------------------------------------------------------
# Presentation generation
# ---------------------------------------------------------------------------


def generate_presentation(
    domain: str,
    topic: str,
    slide_count: int = 10,
    target_audience: str = "executive",
    format: str = "markdown",
    custom_instructions: str = "",
    user_id: str = "",
    allow_empty: bool = False,
    delivery_gate_configs: dict[str, dict[str, Any]] | _DeliveryGatesBypass | None = None,
    llm_config: Config | None = None,
    language: str = "",
    include_stale: bool = False,
) -> str | DeliveryOutput:
    """Generate a slide-based presentation for *topic* within *domain*.

    Searches the KB for entries related to *topic*, asks the LLM to
    produce structured slide content, and renders through the
    appropriate template based on *format*.

    ``allow_empty`` bypasses the empty-shell guard (#182). Unit tests that
    stub the LLM (returning no slides) use it to exercise prompt-building /
    content-preference logic; production callers leave it False so an empty
    presentation raises instead of shipping a 240-byte shell.

    Parameters
    ----------
    domain : str
        Domain to scope the presentation to (e.g. ``"medical-research"``).
    topic : str
        Presentation topic — used to filter relevant KB entries.
    slide_count : int, optional
        Desired number of slides (default 10, range 3–30).
    target_audience : str, optional
        Intended audience.  One of ``"researcher"``, ``"clinician"``,
        ``"executive"`` (default), ``"student"``.
    format : str, optional
        Output format (default ``"markdown"``).  Supported values:

        - ``"markdown"`` — Reveal.js-flavoured Markdown via
          ``presentation.md.j2`` (backward compatible).
        - ``"html"`` — standalone Reveal.js HTML5 document via
          ``presentation.html.j2`` (loads Reveal.js from CDN).
        - ``"mkslides"`` — generate mkslides-compatible Markdown and
          attempt to build via the ``mkslides`` CLI; falls back to
          standalone HTML when mkslides is unavailable.

    custom_instructions : str, optional
        Optional string of additional instructions to append to the LLM
        generation prompt.  Ignored when empty/absent.
    user_id : str, optional
        Optional end-user ID.  When non-empty, the user's stored
        ``content_preference`` (from
        :func:`autoinfo.user_store.get_preferences`) is auto-loaded and
        KB entries are tier-filtered accordingly (B-001).  When empty
        (default), behavior is unchanged and all tiers are included.

    Returns
    -------
    str
        Rendered presentation string.

    Raises
    ------
    ValueError
        If *format*, *target_audience*, or *slide_count* is invalid.
    """
    if format not in ("markdown", "html", "mkslides", "agent"):
        raise ValueError(
            f"Unsupported output format: {format!r}. "
            f"Supported: markdown, html, mkslides, agent"
        )

    if target_audience not in _VALID_AUDIENCES:
        raise ValueError(
            f"Invalid target_audience '{target_audience}'. "
            f"Must be one of: {', '.join(sorted(_VALID_AUDIENCES))}"
        )

    slide_count = max(3, min(30, slide_count))

    # --- Resolve delivery-gate config (issue #298: default-on in production) --
    delivery_gate_configs = _resolve_delivery_gate_configs(domain, delivery_gate_configs)

    # -- Load KB entries related to topic --------------------------------
    kb_store = KBStore()
    entries = kb_store.list_entries(domain, limit=5000)

    # --- Content-preference tier filtering (B-001) ---------------------------
    content_preference: str = _resolve_content_preference(user_id)
    if content_preference != "both":
        filtered_entries = _filter_entries_by_content_preference(
            entries, content_preference
        )
        if len(filtered_entries) != len(entries):
            logger.info(
                "Excluded %d entries from presentation for domain '%s' "
                "due to content_preference='%s'",
                len(entries) - len(filtered_entries),
                domain,
                content_preference,
            )
        entries = filtered_entries

    # --- Test/empty entry filtering (issue #298 — layer 1) -------------------
    entries = _filter_product_entries(entries)

    # --- Per-domain exclude_keywords filter (issue #319) ---------------------
    # Cross-domain noise guard: drop entries matching their own domain's
    # exclude_keywords blacklist BEFORE topic relevance filtering / LLM
    # synthesis / KB-derived slides.
    entries = _filter_entries_by_domain_exclusions(entries, domain)

    # --- Language filter (issue #309 / #317 / #15) ---------------------------
    # Mirror digest/report: when a user requests a specific language (or a
    # domain declares a default_language), drop entries in other languages so
    # a presentation is internally consistent (no zh/en interleave).  Without
    # this, the #8 Chinese financial noise (沪指/创业板/A股) leaked into
    # ai-commercial presentations via topic_entries and the KB-derived
    # fallback slides.  An explicit param wins; otherwise the domain default
    # fills in.
    effective_language = _resolve_effective_language(language, domain)
    if effective_language:
        entries, _ = _filter_entries_by_language_product_safe(
            entries, effective_language
        )

    # --- Staleness filter (backup #60) ---------------------------------------
    # Teaching-layer products must never silently regenerate from an old
    # corpus after a source swap; mirror the digest freshness filter.
    prior_count = len(entries)
    entries = _filter_stale_entries(
        entries, domain, include_stale=include_stale, product="presentation"
    )
    if not include_stale and prior_count > 0 and not entries and not allow_empty:
        raise StaleSourceError(
            f"All {prior_count} candidate entries for domain '{domain}' are stale. "
            f"Refusing to generate an empty-shell presentation from old corpus. "
            f"Re-run collection to refresh the source, or pass include_stale=true."
        )

    # Filter entries by topic relevance (title/summary contains topic terms)
    topic_terms = topic.lower().split()
    topic_entries = [
        e
        for e in entries
        if any(
            term in (e.get("title", "") + " " + e.get("summary", "")).lower()
            for term in topic_terms
        )
    ]

    if not topic_entries:
        # Fall back to all entries for the domain
        topic_entries = entries[:50]

    # -- Build LLM prompt -------------------------------------------------
    audience_desc = _AUDIENCE_DESCRIPTIONS.get(target_audience, "general audience")
    # Cap KB entries sent to the LLM: DeepSeek-V4-Flash is a reasoning
    # model — a long prompt burns max_tokens on reasoning_content and
    # emits empty/truncated content (issue #178). 10 representative
    # entries (title + summary) keep the prompt well under the safe
    # threshold while still grounding the deck in domain facts.
    entry_summaries = "\n".join(
        f"- {e.get('title', '?')}: {e.get('summary', '(no summary)')[:220]}"
        for e in topic_entries[:10]  # cap entries sent to LLM (#178)
    )

    prompt = (
        f"You are a presentation designer creating a slide deck for a "
        f"{target_audience} audience ({audience_desc}). "
        f"Topic: {topic}\n\n"
        "Given the following knowledge base entries, generate slide content. "
        f"Aim for approximately {slide_count} slides.\n"
        "Return a JSON object with the following fields:\n"
        '  - "title": presentation title (string)\n'
        '  - "description": one-sentence description (string)\n'
        '  - "slides": array of slide objects, each with:\n'
        '      - "title": slide heading\n'
        '      - "content": 2-4 sentence slide body\n'
        '      - "bullets": array of 2-5 bullet points (strings)\n'
        '      - "notes": speaker notes (string, optional — may be null)\n\n'
        f"KB Entries:\n{entry_summaries}\n\n"
        "Return all fields in a single JSON object. Adapt depth and terminology "
        f"specifically for a {target_audience} audience.\n"
        'When a claim comes from a specific KB entry, end that bullet with '
        '" (Source: <the entry URL>)".'
    )

    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"

    llm_result = _call_llm_for_presentation(prompt, slide_count)

    # -- Build template context -------------------------------------------
    generated_at = datetime.now(timezone.utc).isoformat()
    context = {
        "title": llm_result.get("title", f"{topic} — Presentation"),
        "topic": topic,
        "domain": domain,
        "target_audience": target_audience,
        "description": llm_result.get("description", ""),
        "slides": llm_result.get("slides", []),
        "generated_at": generated_at,
    }

    # Issue #182 audit-feedback: a presentation with zero slides or only a
    # header stub (LLM empty-content, DeepSeek #178) must NOT be persisted.
    # Raise so callers skip the artifact instead of shipping a 240-byte shell.
    # Applies to markdown AND agent: agent previously returned the JSON-LD
    # shell directly (slides=[]), producing 13 empty presentation-agent
    # artifacts in the 2026-08-11 fill run.
    slides = llm_result.get("slides") or []
    if not slides:
        # Issue #220: LLM synthesis returned no usable slides (DeepSeek
        # empty/partial content).  Fall back to KB-derived slides so the
        # deck carries real domain content instead of failing or shipping
        # an empty shell.  Content is drawn verbatim from KB entries —
        # never fabricated.
        slides = _fallback_slides_from_entries(topic_entries, slide_count)
        if slides:
            llm_result = dict(llm_result)
            llm_result["slides"] = slides
            context["slides"] = slides
            if not context.get("description"):
                context["description"] = (
                    f"KB-derived presentation for {domain} ({len(slides)} slides)"
                )
    # Render the markdown form purely as a content-completeness check for
    # agent output (same template context, same content).
    rendered = _render_presentation_template(context, format=format)
    rendered_check = (
        _render_presentation_template(context, format="markdown")
        if format == "agent"
        else rendered
    )
    if not allow_empty and (len(slides) < 1 or len(rendered_check.strip()) < 500):
        raise ValueError(
            f"Presentation generation produced no usable content for "
            f"domain={domain!r} topic={topic!r} (slides={len(slides)}, "
            f"chars={len(rendered_check.strip())})"
        )

    # -- Agent-native JSON-LD format ----------------------------------------
    if format == "agent":
        return _render_presentation_agent_json(llm_result, domain, topic, target_audience, generated_at, topic_entries)  # noqa: E501

    # --- Delivery gates (D1-D3) ---------------------------------------------
    if delivery_gate_configs is not None:
        result = _apply_delivery_gates(
            rendered_output=rendered,
            output_format=format,
            entries=entries,
            context=context,
            product_type="presentation",
            delivery_gate_configs=delivery_gate_configs,
            llm_config=llm_config,
        )
        result = _apply_min_content_guard(result, entries, "presentation")
        _fire_agent_notification(
            "new_presentation",
            result.output if isinstance(result, DeliveryOutput) else rendered,
            product_id=f"{domain}-presentation",
        )
        return result

    return rendered


def _render_presentation_agent_json(
    llm_result: dict[str, Any],
    domain: str,
    topic: str,
    target_audience: str,
    generated_at: str,
    topic_entries: list[dict[str, Any]],
) -> str:
    """Render presentation data as agent-native JSON-LD (``@type: KnowledgePresentation``)."""
    slides: list[dict[str, Any]] = []
    for s in llm_result.get("slides", []):
        slides.append({
            "title": s.get("title", ""),
            "content": s.get("content", ""),
            "bullets": s.get("bullets", []),
            "notes": s.get("notes"),
        })

    sources: list[dict[str, Any]] = []
    for e in topic_entries[:50]:
        sources.append({
            "entry_id": e.get("entry_id", ""),
            "title": e.get("title", ""),
            "source_url": e.get("source_url", ""),
        })

    output: dict[str, Any] = {
        **_JSONLD_PRESENTATION,
        "uuid": str(uuid.uuid4()),
        "title": llm_result.get("title", f"{topic} — Presentation"),
        "topic": topic,
        "domain": domain,
        "target_audience": target_audience,
        "description": llm_result.get("description", ""),
        "theme": "default",
        "slides": slides,
        "sources": sources,
        "generated_at": generated_at,
        "metadata": {
            "slide_count": len(slides),
            "source_count": len(sources),
        },
    }
    return json.dumps(output, indent=2, ensure_ascii=False, default=str)


def _fallback_slides_from_entries(
    entries: list[dict[str, Any]],
    slide_count: int,
) -> list[dict[str, Any]]:
    """Build KB-derived slides when LLM synthesis returns no usable slides.

    Issue #220: DeepSeek occasionally returns empty/partial presentation
    content.  Rather than failing (or shipping an empty shell), fall back
    to slides drawn verbatim from KB entries — one slide per entry (capped
    at *slide_count*).  Content is real domain material, never fabricated.
    """
    slides: list[dict[str, Any]] = []
    for e in entries[:slide_count]:
        title = str(e.get("title") or "Untitled")[:80]
        summary = str(e.get("summary") or "").strip()
        if not summary:
            continue
        bullets = summary.split(".")[:3]
        bullets = [b.strip().rstrip(".") for b in bullets if b.strip()]
        slides.append(
            {
                "title": title,
                "content": summary[:600],
                "bullets": bullets,
                "notes": "Prepared from knowledge base sources.",
                "source_url": str(e.get("source_url") or "").strip(),
            }
        )
        if len(slides) >= slide_count:
            break
    return slides


def _call_llm_for_presentation(prompt: str, slide_count: int) -> dict[str, Any]:
    """Call LiteLLM to generate structured presentation content."""
    config_path = get_config_path()
    if config_path and config_path.is_file():
        try:
            config = load_config(config_path)
        except Exception:
            config = Config()
    else:
        config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    full_model = model

    try:
        response = call_with_fallback(
            model=full_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a presentation designer. Given knowledge base "
                    "entries, generate structured slide content. "
                    "Respond with valid JSON only, no markdown formatting.",
                },
                {"role": "user", "content": prompt},
            ],
            json_mode=config.llm.json_mode and not config.llm.reasoning_model,
            max_tokens=8000,
            temperature=0.1,
            api_key=config.llm.api_key or None,
            base_url=config.llm.base_url or None,
        )
    except Exception as exc:
        logger.error("LLM presentation synthesis failed: %s", exc)
        return {}
    content: str = response.choices[0].message.content or ""
    return _parse_json_response(content)


def _render_presentation_template(
    context: dict[str, Any],
    format: str = "markdown",
) -> str:
    """Render the presentation data through the appropriate template.

    Parameters
    ----------
    context:
        Template context dict built by :func:`generate_presentation`.
    format:
        Output format — ``"markdown"`` (default, backward compatible),
        ``"html"`` (standalone Reveal.js HTML5 via CDN), or
        ``"mkslides"`` (mkslides-compatible Markdown with optional
        CLI build; falls back to standalone HTML on failure).
    """
    if format == "html":
        return _render_presentation_html(context)

    if format == "mkslides":
        return _render_presentation_mkslides(context)

    # Default: backward-compatible Markdown
    env = _get_jinja_env()
    template = env.get_template("presentation.md.j2")
    return template.render(**context)


def _render_presentation_html(context: dict[str, Any]) -> str:
    """Render the presentation as a standalone Reveal.js HTML5 document.

    Loads Reveal.js CSS/JS from the jsdelivr CDN — no bundling.
    The template (``presentation.html.j2``) is autoescaped by
    :func:`_html_autoescape` because of its ``.html.j2`` extension.
    """
    env = _get_jinja_env()
    template = env.get_template("presentation.html.j2")
    return template.render(**context)


def _render_presentation_mkslides(context: dict[str, Any]) -> str:
    """Render the presentation as mkslides-compatible Markdown.

    Produces a Markdown file with YAML frontmatter (``title``,
    ``author``, ``theme``) and ``---`` slide separators, writes it to
    a temporary directory, and attempts to build via the ``mkslides``
    CLI.  When mkslides is not installed or the build fails, falls
    back to the standalone HTML renderer with a log warning.
    """
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    title = context.get("title", "Presentation")
    author = context.get("domain", "AutoInfo")
    theme = context.get("theme", "black")
    slides = context.get("slides", []) or []

    # Build mkslides Markdown: frontmatter + --- separated slides
    lines: list[str] = [
        "---",
        f"title: {title}",
        f"author: {author}",
        f"theme: {theme}",
        "---",
        "",
    ]

    for slide in slides:
        slide_title = slide.get("title", "")
        slide_content = slide.get("content", "")
        bullets = slide.get("bullets", []) or []
        notes = slide.get("notes", "")

        lines.append(f"# {slide_title}")
        lines.append("")
        if slide_content:
            lines.append(slide_content)
            lines.append("")
        if bullets:
            for b in bullets:
                lines.append(f"- {b}")
            lines.append("")
        if notes:
            lines.append(f"<!-- {notes} -->")
            lines.append("")

        lines.append("---")
        lines.append("")

    mkslides_md = "\n".join(lines)

    # Attempt mkslides build in a temp directory
    try:
        with tempfile.TemporaryDirectory(prefix="autoinfo-mkslides-") as tmpdir:
            src_path = Path(tmpdir) / "presentation.md"
            src_path.write_text(mkslides_md, encoding="utf-8")

            try:
                proc = subprocess.run(
                    ["mkslides", "build", "presentation.md"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except FileNotFoundError:
                logger.warning(
                    "mkslides is not installed — falling back to "
                    "standalone HTML presentation."
                )
                return _render_presentation_html(context)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "mkslides build timed out after 30s — falling back "
                    "to standalone HTML presentation."
                )
                return _render_presentation_html(context)

            if proc.returncode != 0:
                logger.warning(
                    "mkslides build failed (rc=%d): %s — falling back "
                    "to standalone HTML presentation.",
                    proc.returncode,
                    (proc.stderr or "").strip()[:200],
                )
                return _render_presentation_html(context)

            # mkslides writes output to a default location; locate the HTML
            out_dir = Path(tmpdir) / "public"
            html_candidates = sorted(out_dir.rglob("*.html")) if out_dir.is_dir() else []
            if not html_candidates:
                # Some mkslides versions write alongside the source
                html_candidates = sorted(Path(tmpdir).glob("*.html"))

            if not html_candidates:
                logger.warning(
                    "mkslides build produced no HTML output — falling "
                    "back to standalone HTML presentation."
                )
                return _render_presentation_html(context)

            return html_candidates[0].read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "mkslides rendering failed (%s) — falling back to standalone "
            "HTML presentation.",
            exc,
        )
        return _render_presentation_html(context)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

# Default TTS voice for audio output.
DEFAULT_TTS_VOICE = "alloy"

# Default local TTS engine voice (edge-tts).
DEFAULT_LOCAL_TTS_VOICE = "en-US-JennyNeural"


def _make_audio_persist_path(domain: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    domain_slug = domain or "all"
    return str(Path("exports") / domain_slug / "podcast" / f"ep-{ts}.mp3")


def _maybe_persist_audio(mp3_bytes: bytes, persist_path: str | None) -> None:
    if not persist_path:
        return
    try:
        p = Path(persist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(mp3_bytes)
        logger.info("Audio persisted to %s (%d bytes)", persist_path, len(mp3_bytes))
    except OSError:
        logger.warning("Failed to persist audio to %s", persist_path, exc_info=True)


# Markdown patterns to strip when converting to plain text for TTS.
_MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_HEADING_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC_PATTERN = re.compile(r"\*([^*]+)\*")
_MD_CODE_PATTERN = re.compile(r"`([^`]+)`")
_MD_HR_PATTERN = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MD_QUOTE_PATTERN = re.compile(r"^>\s?", re.MULTILINE)
_MD_LIST_PATTERN = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_MD_ORDERED_LIST_PATTERN = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)


def _strip_markdown(text: str) -> str:
    """Convert Markdown text to plain text suitable for TTS.

    Strips links, images, headings, bold/italic markers, code fences,
    horizontal rules, blockquotes, and list markers.  Keeps the content
    readable for speech synthesis.
    """
    # Images: replace with alt text
    text = _MD_IMAGE_PATTERN.sub(r"\1", text)
    # Links: keep link text, drop URL
    text = _MD_LINK_PATTERN.sub(r"\1", text)
    # Bold: keep inner text
    text = _MD_BOLD_PATTERN.sub(r"\1", text)
    # Italic: keep inner text
    text = _MD_ITALIC_PATTERN.sub(r"\1", text)
    # Inline code: keep inner text
    text = _MD_CODE_PATTERN.sub(r"\1", text)
    # Headings: remove # markers
    text = _MD_HEADING_PATTERN.sub("", text)
    # Horizontal rules: remove
    text = _MD_HR_PATTERN.sub("", text)
    # Blockquotes: remove > prefix
    text = _MD_QUOTE_PATTERN.sub("", text)
    # Unordered list markers
    text = _MD_LIST_PATTERN.sub("", text)
    # Ordered list markers
    text = _MD_ORDERED_LIST_PATTERN.sub("", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _render_audio(
    text: str,
    voice: str = DEFAULT_TTS_VOICE,
    timeout: float = 120.0,
    engine: str | None = None,
    local_voice: str = DEFAULT_LOCAL_TTS_VOICE,
) -> bytes:
    """Render *text* as MP3 audio using the configured TTS engine.

    Parameters
    ----------
    text:
        Plain text (or Markdown; will be stripped) to convert to speech.
        Maximum 4096 characters per request.
    voice:
        For ``engine="openai"`` and ``engine="whisper"``: one of
        OpenAI's TTS voices (``"alloy"``, ``"echo"``, ``"fable"``,
        ``"onyx"``, ``"nova"``, ``"shimmer"``).  Ignored for
        ``engine="local"``.
    timeout:
        HTTP request timeout in seconds (default 120).
    engine:
        TTS engine: ``"local"`` (edge-tts, default), ``"openai"``,
        or ``"whisper"`` (OpenAI Whisper model via TTS API).
        When *None*, reads from the ``tts.engine`` config key, falling
        back to ``"local"``.
    local_voice:
        Voice name for the local engine (edge-tts).  Defaults to
        ``"en-US-JennyNeural"``.  Ignored for ``engine="openai"``
        and ``engine="whisper"``.

    Returns
    -------
    bytes
        MP3 audio data.

    Raises
    ------
    RuntimeError
        If the API key is not configured, the API returns an error, or
        the network request fails.
    ValueError
        If *text* is empty or exceeds the character limit.
    """
    if not text or not text.strip():
        raise ValueError("Cannot render empty text as audio")

    text = text.strip()
    if len(text) > 4096:
        # Truncate at 4000 characters and append a note.
        text = text[:4000] + "... [truncated]"

    # Strip markdown for cleaner TTS output.
    text = _strip_markdown(text)

    if not text:
        raise ValueError("Text is empty after stripping markdown formatting")

    # --- Resolve engine ---
    resolved_engine = engine
    if resolved_engine is None:
        resolved_engine = _get_tts_engine_from_config()
    if resolved_engine not in ("openai", "local", "whisper"):
        logger.warning(
            "Unknown TTS engine '%s' — falling back to 'openai'.",
            resolved_engine,
        )
        resolved_engine = "openai"

    # --- Local engine (edge-tts) ---
    if resolved_engine == "local":
        try:
            return _render_audio_edge_tts(text, voice=local_voice, timeout=timeout)
        except ImportError:
            logger.warning(
                "edge-tts is not installed — falling back to OpenAI TTS. "
                "Install with: pip install 'autoinfo[tts]'"
            )
        except Exception:
            # edge-tts is configured as the engine; a synthesis failure is
            # NOT a reason to fall back to OpenAI — the user chose local
            # explicitly (e.g. no api.openai.com route), and OpenAI may be
            # unreachable (2026-08-11: WSL has no route to api.openai.com,
            # so the fallback turns a clean edge-tts error into a
            # misleading "OpenAI TTS network error" after 150s+).  Re-raise
            # so callers can retry or surface the real error.
            raise

    # --- Whisper engine (OpenAI Whisper model via TTS API) ---
    if resolved_engine == "whisper":
        try:
            return _render_audio_whisper(text, voice=voice, timeout=timeout)
        except Exception:
            logger.warning(
                "Whisper TTS failed — falling back to OpenAI TTS.",
                exc_info=True,
            )

    # --- OpenAI TTS path (explicit or fallback) ---
    return _render_audio_openai(text, voice=voice, timeout=timeout)


def _render_video_scaffold(
    context: dict[str, Any],
    title: str,
    sections: list[dict[str, str]] | None = None,
) -> str:
    """Generate a video report — audio narration + slide images → MP4 via FFmpeg.

    Calls :func:`autoinfo.output.video.generate_report_video` to run
    the full pipeline (TTS → slides → FFmpeg assembly).  Returns a JSON
    status blob with the MP4 path and render metadata.
    """
    from autoinfo.output.video import (  # noqa: PLC0415
        VideoConfig,
        generate_report_video,
    )

    if sections is None or len(sections) == 0:
        sections = [{"heading": title, "body": "No content sections available."}]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(
        os.environ.get("AUTOINFO_TMPDIR", "/tmp/autoinfo/video"), timestamp
    )
    os.makedirs(output_dir, exist_ok=True)

    # Map context-level settings to VideoConfig
    resolution = context.get("resolution", (1920, 1080))
    if isinstance(resolution, list):
        resolution = tuple(resolution)
    vcfg = VideoConfig(
        fps=context.get("fps", 30),
        resolution=resolution,
        theme=context.get("theme", "terminal-green"),
        quality=context.get("quality", "draft"),
        tts_speed=context.get("tts_speed", 1.0),
        scene_mode=context.get("scene_mode", "auto"),
        theme_mood=context.get("theme_mood", ""),
    )

    output_path = os.path.join(output_dir, f"report_{timestamp}.mp4")

    video_path = generate_report_video(
        title=title,
        sections=sections,
        output_path=output_path,
        config=vcfg,
    )

    return json.dumps(
        {
            "status": "ok",
            "output_type": "video",
            "video_path": video_path,
            "output_dir": output_dir,
            "format": "mp4",
            "message": "Video report generated successfully.",
        },
        indent=2,
    )


def _get_tts_engine_from_config() -> str:
    """Read the ``tts.engine`` setting from the project config.

    Returns "local" (edge-tts) when the config is missing or the key
    is not set.  The OpenAI TTS endpoint is unreachable from the project's
    deployment environment (WSL has no route to api.openai.com), so the
    local engine is the sane default (#210); "tts.engine: openai" remains
    available for environments that can reach the endpoint.
    """
    try:
        config_path = get_config_path()
        if config_path and config_path.is_file():
            cfg = load_config(config_path)
            engine = getattr(cfg, "tts", None)
            if engine is not None and engine.engine:
                return str(engine.engine)
    except Exception:
        pass
    return "local"


def _render_audio_openai(
    text: str,
    voice: str = DEFAULT_TTS_VOICE,
    timeout: float = 120.0,
    model: str = "tts-1",
) -> bytes:
    """Render *text* as MP3 audio using the OpenAI Text-to-Speech API."""
    # --- API key resolution ---
    api_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
    if not api_key:
        # Fall back to config
        try:
            config_path = get_config_path()
            if config_path and config_path.is_file():
                cfg = load_config(config_path)
                api_key = cfg.llm.api_key or ""
        except Exception:
            pass
    if not api_key:
        # Last resort: OpenAI env var (set by LiteLLM)
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "AUTOINFO_LLM_API_KEY is not set.  Set the environment "
            "variable or configure `llm.api_key` in config.yaml to "
            "use OpenAI TTS."
        )

    # --- OpenAI TTS API call ---
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": "mp3",
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        mp3_bytes = response.content
        if not mp3_bytes:
            raise RuntimeError("OpenAI TTS API returned empty audio data")
        logger.info(
            "Generated audio: %d chars text → %d bytes MP3 (model=%s, voice=%s)",
            len(text), len(mp3_bytes), model, voice,
        )
        return mp3_bytes
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        logger.error("OpenAI TTS API error: %s %s", exc.response.status_code, detail)
        raise RuntimeError(
            f"OpenAI TTS API error (HTTP {exc.response.status_code}): "
            f"{detail}"
        ) from exc
    except httpx.RequestError as exc:
        logger.error("OpenAI TTS network error: %s", exc)
        raise RuntimeError(
            f"OpenAI TTS network error: {exc}"
        ) from exc


def _render_audio_whisper(
    text: str,
    voice: str = DEFAULT_TTS_VOICE,
    timeout: float = 120.0,
) -> bytes:
    """Render *text* as MP3 audio using the OpenAI Whisper model via TTS API.

    Uses the same OpenAI TTS API endpoint as :func:`_render_audio_openai`
    but with ``model="whisper-1"`` instead of ``model="tts-1"``.

    Falls back to :func:`_render_audio_openai` if the Whisper model is
    unavailable or the API request fails.
    """
    try:
        return _render_audio_openai(
            text, voice=voice, timeout=timeout, model="whisper-1"
        )
    except Exception:
        logger.warning(
            "Whisper TTS model unavailable — falling back to OpenAI TTS.",
            exc_info=True,
        )
        return _render_audio_openai(
            text, voice=voice, timeout=timeout, model="tts-1"
        )


def _run_coro_in_new_thread(coro: Any) -> Any:
    """Run *coro* in a fresh thread with its own event loop.

    ``asyncio.run`` cannot be called from a running event loop, so callers
    already inside one offload the coroutine to a dedicated thread here;
    the worker's result or exception is propagated back verbatim.
    """
    result: dict[str, Any] = {"value": None, "error": None}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


def _render_audio_edge_tts(
    text: str,
    voice: str = DEFAULT_LOCAL_TTS_VOICE,
    timeout: float = 120.0,
) -> bytes:
    """Render *text* as MP3 audio using the edge-tts library (local, free).

    Auto-selects a voice matching the dominant script when the configured
    voice cannot speak it: edge-tts ``en-US-JennyNeural`` raises
    ``NoAudioReceived`` for CJK-heavy text, which surfaced as 4 failing
    digest-audiobook cells (2026-08-11).  Text containing CJK codepoints
    uses ``zh-CN-XiaoxiaoNeural``; otherwise the requested voice is used.
    When the caller is already inside a running event loop, synthesis is
    offloaded to a new thread running its own fresh loop instead of
    ``asyncio.run`` (which would raise in that context).

    Raises
    ------
    ImportError
        If ``edge_tts`` is not installed.
    RuntimeError
        If the TTS synthesis fails.
    """
    import asyncio  # noqa: PLC0415

    import edge_tts  # noqa: PLC0415

    # CJK detection (CJK Unified Ideographs, Hiragana/Katakana, Hangul).
    cjk_ranges = (
        (0x4E00, 0x9FFF),   # CJK Unified Ideographs
        (0x3040, 0x30FF),   # Hiragana + Katakana
        (0xAC00, 0xD7AF),   # Hangul Syllables
    )
    has_cjk = any(
        any(lo <= ord(ch) <= hi for lo, hi in cjk_ranges)
        for ch in text
    )
    effective_voice = "zh-CN-XiaoxiaoNeural" if has_cjk else voice

    async def _synthesize() -> bytes:
        communicate = edge_tts.Communicate(text, effective_voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if not chunks:
            raise RuntimeError("edge-tts returned empty audio data")
        return b"".join(chunks)

    try:
        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False
        if running:
            mp3_bytes = _run_coro_in_new_thread(
                asyncio.wait_for(_synthesize(), timeout=timeout)
            )
        else:
            mp3_bytes = asyncio.run(asyncio.wait_for(_synthesize(), timeout=timeout))
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Local TTS (edge-tts) timed out after {timeout:.0f}s"
        ) from None

    logger.info(
        "Generated audio (local/edge-tts): %d chars text → %d bytes MP3 (voice=%s)",
        len(text), len(mp3_bytes), voice,
    )
    return cast(bytes, mp3_bytes)


def _render_markdown(context: dict[str, Any]) -> str:
    """Render the Jinja2 digest template to Markdown."""
    env = _get_jinja_env()
    template = env.get_template("digest.md.j2")
    return template.render(**context)


def _digest_chapters(context: dict[str, Any]) -> list[tuple[str, str]]:
    """Split digest context into ``(heading, markdown_body)`` chapters.

    Chapter 1 is front matter (title + metadata + executive summary); each
    KB entry becomes its own chapter.  Used by the ``epub`` and
    ``audiobook`` digest formats.
    """
    front_matter = [
        f"# {context.get('title', 'AutoInfo Digest')}",
        "",
        f"**Domain**: {context.get('domain', '')}",
        f"**Period**: {context.get('period_label', '')}",
        f"**Generated**: {context.get('generated_at', '')}",
    ]
    llm_synthesis = context.get("llm_synthesis") or {}
    if llm_synthesis.get("executive_summary"):
        front_matter.extend([
            "",
            "## Executive Summary",
            "",
            str(llm_synthesis["executive_summary"]),
        ])
    chapters: list[tuple[str, str]] = [("Front Matter", "\n".join(front_matter))]
    for entry in context.get("entries") or []:
        chapters.append((
            str(entry.get("title", "Untitled")),
            str(entry.get("summary", "") or ""),
        ))
    return chapters


def _render_html(markdown_text: str) -> str:
    """Convert Markdown to plain HTML (no CSS styling).

    Uses the ``markdown`` library (already a project dependency) to
    produce bare HTML without any stylesheets or CSS classes.

    .. deprecated::
        Prefer :func:`_render_digest_html` for digest output, which
        renders a full HTML5 document via ``digest.html.j2``.  This
        helper is retained for backward compatibility with callers
        that pass raw Markdown.
    """
    try:
        import markdown as md_lib  # noqa: PLC0415

        return str(md_lib.markdown(markdown_text, extensions=["fenced_code", "tables"]))
    except (ImportError, ModuleNotFoundError):
        logger.warning("markdown library not available \u2014 returning raw markdown")
        return markdown_text


def _render_digest_html(context: dict[str, Any]) -> str:
    """Render the digest as a self-contained HTML5 document.

    Maps the internal digest context (built by :func:`generate_digest`)
    to the variable contract expected by ``digest.html.j2``:

    - ``title`` — digest title
    - ``domain_name`` — domain identifier
    - ``period`` — human-readable period label with date range
    - ``generated_at`` — ISO timestamp
    - ``executive_summary`` — LLM-synthesized summary (if any)
    - ``key_findings`` — list of ``{title, text}`` dicts (ranked by order)
    - ``trends`` — list of trend strings
    - ``recommendations`` — list of recommendation strings
    - ``entries`` — list of ``{title, source_url, summary, relevance_score}``
    """
    env = _get_jinja_env()
    template = env.get_template("digest.html.j2")

    synthesis = context.get("llm_synthesis") or {}

    # Map LLM key_findings ({topic, detail}) -> {title, text}; also
    # accepts {text, source_url} objects and plain strings (issue #279
    # fallback shape), threading source_url through for inline citation.
    key_findings: list[dict[str, Any]] = []
    for f in (synthesis.get("key_findings") or []):
        if isinstance(f, dict):
            topic = str(f.get("topic") or "").strip()
            detail = str(f.get("detail") or "").strip()
            text = str(f.get("text") or "").strip()
            item = {"title": topic, "text": detail or text or topic}
            item["source_url"] = str(f.get("source_url") or "").strip()
        elif isinstance(f, str):
            item = {"title": "", "text": f.strip(), "source_url": ""}
        else:
            continue
        if item["text"]:
            key_findings.append(item)

    # Map KB entries to the template's entry contract
    html_entries = [
        {
            "title": e.get("title", ""),
            "source_url": e.get("source_url", "") or "",
            "summary": e.get("summary", "") or "",
            "relevance_score": e.get("relevance_score"),
            "source_tier": e.get("source_tier"),
        }
        for e in (context.get("entries") or [])
    ]

    period_label = context.get("period_label", "")
    date_from = context.get("date_from", "")
    date_to = context.get("date_to", "")
    period_str = f"{period_label} ({date_from} \u2013 {date_to})" if period_label else ""

    from autoinfo.output.seo import generate_structured_data

    ld = generate_structured_data(
        title=context.get("title", ""),
        description=synthesis.get("executive_summary", "") or context.get("title", ""),
        date_published=context.get("generated_at", ""),
        url="",
        article_type="Article",
    )
    structured_data = f'<script type="application/ld+json">\n{ld}\n</script>'

    return template.render(
        title=context.get("title", ""),
        domain_name=context.get("domain", ""),
        period=period_str,
        generated_at=context.get("generated_at", ""),
        executive_summary=synthesis.get("executive_summary", "") or "",
        key_findings=key_findings,
        trends=synthesis.get("trends") or [],
        recommendations=synthesis.get("recommendations") or [],
        entries=html_entries,
        structured_data=structured_data,
    )


def _render_json(context: dict[str, Any]) -> str:
    """Render the digest as a JSON string.

    The JSON structure separates metadata, LLM synthesis, and entries
    so consumers can parse with full fidelity.
    """
    output = {
        "digest_type": "digest",
        "domain": context["domain"],
        "period": context["period"],
        "period_label": context["period_label"],
        "date_from": context["date_from"],
        "date_to": context["date_to"],
        "generated_at": context["generated_at"],
        "entry_count": len(context["entries"]),
        "llm_synthesis": context["llm_synthesis"],
        "entries": context["entries"],
    }
    return json.dumps(output, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Agent-native JSON-LD output format (F28 / G11)
# ---------------------------------------------------------------------------


def _persist_product_analysis_to_kb(
    store: KBStore,
    link_entries: list[dict[str, Any]],
    product_fields: dict[str, Any],
) -> None:
    """Persist populated product analysis fields to the linked KB entries.

    Called after agent rendering (todo 24, output-quality-mega): when a
    product output (premium-briefing / enterprise-briefing / magazine-digest)
    carries the per-product analysis fields, they are written as JSON
    metadata (``{"product_analysis": {...}}``) onto the KB entries the
    output was generated from, via the existing KB metadata dict path
    (``KBStore.update_entry_metadata`` → ``entries.custom_fields`` SQLite
    column → surfaced by ``KBStore.get_entry`` / MCP ``get_kb_entry``).

    Linkage: entries are matched by ``entry_id`` when present (digest path);
    otherwise by ``source_url`` (report-path agent entries hardcode
    ``entry_id: ""``).

    Backward compatible: when no product field is populated (default
    digest/report), nothing is persisted. Failures are logged and never
    break output generation.
    """
    populated = {
        field: product_fields[field]
        for field in _PRODUCT_ANALYSIS_FIELDS
        if product_fields.get(field)
    }
    if not populated:
        return
    metadata = {"product_analysis": populated}
    seen: set[tuple[str, str]] = set()
    for entry in link_entries:
        entry_id = str(entry.get("entry_id") or "")
        source_url = str(entry.get("source_url") or "")
        if not entry_id and not source_url:
            continue
        if (entry_id, source_url) in seen:
            continue
        seen.add((entry_id, source_url))
        try:
            target_id = entry_id
            if not target_id:
                found = store.get_entry_by_source_url(source_url)
                if found is None:
                    continue
                target_id = str(found.get("entry_id") or "")
                if not target_id:
                    continue
            store.update_entry_metadata(target_id, metadata)
        except Exception:
            logger.warning(
                "Failed to persist product analysis metadata for %r — "
                "output unaffected",
                entry_id or source_url,
                exc_info=True,
            )


def _render_agent_json(
    entries: list[dict[str, Any]],
    context: dict[str, Any],
) -> str:
    """Render entries as agent-native JSON-LD (``@type: KnowledgeDigest``).

    Produces a structured JSON-LD payload optimized for LLM re-consumption.
    Agents can parse, re-synthesize, store in their own KB, or combine
    with other data sources.

    Parameters
    ----------
    entries:
        List of KB entry dicts (from :meth:`KBStore.list_entries`).
        Expected keys: ``entry_id``, ``title``, ``summary``, ``source_url``,
        ``source_platform``, ``collected_at``, ``relevance_score``, ``tags``.
    context:
        Rendering context dict.  Expected keys: ``domain``, ``period``,
        ``generated_at``, ``llm_synthesis``, ``target_audience``.

    Returns
    -------
    str
        Indented JSON-LD string.
    """
    import re

    generated_at = context.get("generated_at", datetime.now(timezone.utc).isoformat())
    domain = context.get("domain", "")
    period = context.get("period", "")
    target_audience = context.get("target_audience", "")
    llm_synthesis = context.get("llm_synthesis", {})

    # --- Build entry list ----------------------------------------------------
    agent_entries: list[dict[str, Any]] = []
    for e in entries:
        entry_uuid = e.get("entry_id", "")
        tags: list[str] = []
        tags_raw = e.get("tags", "")
        if isinstance(tags_raw, list):
            tags = tags_raw
        elif isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = [tags_raw] if tags_raw else []

        # Derive entities from tags
        entities = [
            {"name": tag, "type": "topic", "relation": "tagged"}
            for tag in tags
        ]

        # Confidence score: use relevance_score/100 as proxy if available
        relevance = e.get("relevance_score")
        if relevance is not None:
            try:
                confidence = round(float(relevance) / 100.0, 4)
            except (ValueError, TypeError):
                confidence = None
        else:
            confidence = None

        # Key points: split summary into sentences as approximate key points
        summary = e.get("summary", "") or ""
        key_points: list[str] = []
        if summary:
            sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
            key_points = [s.strip() for s in sentences[:3] if s.strip()]

        agent_entries.append({
            "uuid": entry_uuid,
            "title": e.get("title", ""),
            "tl_dr": summary,
            "source_url": e.get("source_url", ""),
            "source_platform": e.get("source_label") or e.get("source_platform", ""),
            "collected_at": e.get("collected_at", ""),
            "relevance_score": e.get("relevance_score"),
            "confidence_score": confidence,
            "key_points": key_points,
            "entities": entities,
        })

    # --- Build trends from LLM synthesis --------------------------------------
    trends: list[dict[str, Any]] = []
    for trend in llm_synthesis.get("trends", []):
        if isinstance(trend, str):
            trends.append({"topic": trend, "direction": "", "evidence": ""})
        elif isinstance(trend, dict):
            trends.append(trend)
    # Also pull from key_findings
    for finding in llm_synthesis.get("key_findings", []):
        topic = finding.get("topic", "") if isinstance(finding, dict) else str(finding)
        if topic and not any(t.get("topic") == topic for t in trends):
            detail = finding.get("detail", "") if isinstance(finding, dict) else ""
            trends.append({"topic": topic, "direction": "observed", "evidence": detail})

    # --- Build metadata -------------------------------------------------------
    metadata: dict[str, Any] = {
        "entry_count": len(entries),
        "generated_at": generated_at,
        "domain": domain,
    }
    if period:
        metadata["period"] = period

    # --- Assemble JSON-LD payload ---------------------------------------------
    output: dict[str, Any] = {
        **_JSONLD_DIGEST,
        "uuid": str(uuid.uuid4()),
        "generated_at": generated_at,
        "domain": domain,
        "period": period,
        "target_audience": target_audience or None,
        "entries": agent_entries,
        "trends": trends,
        "metadata": metadata,
    }
    # Surface the per-product analysis fields (todo 22) — implications /
    # risks / action_required / key_metrics — copied from the synthesis so a
    # downstream agent can query/filter them. Emitted only when populated,
    # so default digest/report agent output stays unchanged.
    for synthesis_field in _PRODUCT_ANALYSIS_FIELDS:
        if llm_synthesis.get(synthesis_field):
            output[synthesis_field] = llm_synthesis[synthesis_field]

    return json.dumps(output, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Content simplification (E14 — CEFR-level parameterised simplification)
# ---------------------------------------------------------------------------

_VALID_SIMPLIFY_TARGETS: frozenset[str] = frozenset({"A1", "A2", "B1", "B2", "C1"})
_CEFR_RANK: dict[str, int] = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def simplify_text(
    content: str,
    target_level: str,
    language: str = "en",
) -> dict[str, Any]:
    """Simplify *content* to a target CEFR reading level using LLM.

    First classifies the original text, then uses LLM to rewrite it at the
    target level, and finally verifies the result with a second CEFR
    classification.

    On LLM failure the original text is returned unchanged with
    ``verified=False`` so callers can inspect the ``.error`` key.

    Parameters
    ----------
    content:
        The text to simplify.  Must not be empty.
    target_level:
        Target CEFR level: ``"A1"``, ``"A2"``, ``"B1"``, ``"B2"``, or
        ``"C1"``.
    language:
        Language code: ``"en"``, ``"zh"``, or ``"ja"`` (default ``"en"``).

    Returns
    -------
    dict
        ``{"simplified": str, "original_level": str, "simplified_level":
        str, "verified": bool}`` plus an ``"error"`` key on failure.
    """
    from autoinfo.cefr import classify_text  # noqa: PLC0415

    lang_names: dict[str, str] = {"en": "English", "zh": "Chinese", "ja": "Japanese"}
    lang_name = lang_names.get(language, "English")

    # --- Validate target_level ------------------------------------------------
    if target_level not in _VALID_SIMPLIFY_TARGETS:
        return {
            "simplified": content,
            "original_level": "unknown",
            "simplified_level": "unknown",
            "verified": False,
            "error": (
                f"Invalid target_level: '{target_level}'. "
                "Must be one of A1, A2, B1, B2, C1."
            ),
        }

    if not content or not content.strip():
        return {
            "simplified": "",
            "original_level": "unknown",
            "simplified_level": "unknown",
            "verified": False,
            "error": "Content is empty",
        }

    # --- Classify original ----------------------------------------------------
    original_result = classify_text(content, lang=language)
    original_level: str = original_result.get("cefr_level", "unknown")

    # --- LLM simplification ---------------------------------------------------
    system_prompt = (
        "You are a text simplification assistant. Your task is to rewrite "
        "the given text so that it is suitable for readers at a specific "
        "CEFR level. Follow these rules:\n"
        "- Use vocabulary and sentence structures appropriate for the target CEFR level.\n"
        "- Preserve the core meaning, key facts, and important details.\n"
        "- Do NOT add new information or opinions.\n"
        "- Return ONLY the simplified text — no explanations, no prefixes, no markdown wrapping."
    )

    user_prompt = (
        f"Language: {lang_name}\n"
        f"Target CEFR Level: {target_level}\n\n"
        f"Original Text:\n{content[:5000]}\n\n"
        "Rewrite this text at the target CEFR level. Return only the simplified text."
    )

    # Resolve model config (same pattern as cefr.py)
    from autoinfo.config import get_config_path, load_config  # noqa: PLC0415

    model = "openrouter/deepseek/deepseek-chat"
    api_key = ""
    base_url = ""
    try:
        config_path = get_config_path()
        if config_path is not None:
            config = load_config(config_path)
            provider = config.llm.provider or "openrouter"
            llm_model = config.llm.model or "deepseek/deepseek-chat"
            model = f"{provider}/{llm_model}"
            api_key = config.llm.api_key or ""
            base_url = config.llm.base_url or ""
    except Exception:
        logger.debug("Could not load config for simplify_text", exc_info=True)

    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=8000,
            temperature=0.3,
            api_key=api_key or None,
            base_url=base_url or None,
        )
        simplified: str = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM simplification failed: %s", exc)
        return {
            "simplified": content,
            "original_level": original_level,
            "simplified_level": "unknown",
            "verified": False,
            "error": str(exc),
        }

    if not simplified:
        return {
            "simplified": content,
            "original_level": original_level,
            "simplified_level": "unknown",
            "verified": False,
            "error": "LLM returned empty response",
        }

    # --- Verify simplified level ----------------------------------------------
    simplified_result = classify_text(simplified, lang=language)
    simplified_level: str = simplified_result.get("cefr_level", "unknown")

    target_rank = _CEFR_RANK.get(target_level, 0)
    simplified_rank = _CEFR_RANK.get(simplified_level, 0)
    verified: bool = (
        simplified_rank > 0
        and target_rank > 0
        and simplified_rank <= target_rank
    )

    return {
        "simplified": simplified,
        "original_level": original_level,
        "simplified_level": simplified_level,
        "verified": verified,
    }
