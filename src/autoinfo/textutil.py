"""Text normalization helpers for collected content.

Feed parsers (feedparser et al.) return titles/summaries that may contain
leftover HTML tags and HTML entities. These helpers strip that markup so
sanitized text reaches the knowledge base and downstream products rather
than leaking placeholder forms such as ``V<Benchmark>`` (backup issue #51).
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
