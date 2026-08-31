"""Text normalization and shared heuristics for collected content.

Two families of helpers live here:

1. Feed sanitization (:func:`clean_feed_text`) — feed readers return
   titles/summaries that may contain leftover HTML tags and HTML entities.
   These helpers strip that markup so sanitized text reaches the KB and
   downstream products rather than leaking placeholder forms such as
   ``V<Benchmark>`` (backup issue #51).

2. Event-signature heuristics (proper-noun extraction + the cross-language
   death/obituary event-word lexicon).  Both the collection-layer dedup
   (:mod:`autoinfo.dedup`) and the product-layer near-duplicate convergence
   (:mod:`autoinfo.output`) need these, and sharing them here keeps the two
   drift-free (backup issue #109).
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_feed_text(text: str | None) -> str:
    """Sanitize a feed title/summary string.

    Strips HTML tags, decodes HTML entities (``&amp;`` -> ``&``,
    ``&nbsp;`` -> space), normalizes non-breaking spaces, and collapses
    runs of whitespace. Plain text with no markup is returned unchanged,
    so non-HTML content is never mangled.

    This closes the collection-side sanitization gap reported in backup
    issue #51 (e.g. ``V<em>Benchmark</em>`` -> ``VBenchmark``).
    """
    if not text:
        return ""
    # 1. Remove HTML tags (feedparser preserves tags that were not stripped).
    text = _TAG_RE.sub("", text)
    # 2. Decode HTML entities now that tags are gone.
    text = html.unescape(text)
    # 3. Normalize non-breaking spaces introduced by entity decoding.
    text = text.replace("\xa0", " ")
    # 4. Collapse internal whitespace and trim.
    text = _WS_RE.sub(" ", text).strip()
    return text


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


def _normalize_lang(value: str) -> str:
    """Normalize a language tag to a canonical 2-letter ISO code.

    ``zh_CN``/``zh-CN``/``es_ES``/``es-ES`` → ``zh``/``es``; ``en-us`` → ``en``.
    Full language names ("spanish") are not remapped here — an unrecognised
    tag is lowercased and passed through, causing the caller's lexicon lookup
    to fall back to the union lexicon.  The output layer keeps its own richer
    alias-normalising :func:`autoinfo.output._normalize_lang` for display
    naming; this smaller one is sufficient for event-signature keying.
    """
    v = (value or "").strip().replace("_", "-").replace(" ", "-").lower()
    if not v:
        return ""
    return v.split("-")[0]


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
