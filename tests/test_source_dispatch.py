"""Tests for source dispatch logic — verifies every configured demo source
has a corresponding handler.

This tests a different concern than ``test_demo_sources.py`` (which validates
YAML structure). Here we verify that the dispatch function ``_build_handler()``
in ``collect.py`` can actually process each source configuration.

Dispatch rules (from ``collect.py`` ``_build_handler()``):

1. ``type == "api"`` AND ``"pubmed" in name`` → PubMedHandler
2. ``type == "rss"`` → RSSHandler
3. ``type == "web"`` → WebHandler
4. ``type in ("email", "email_imap")`` → EmailHandler
5. ``type == "pdf"`` → PDFHandler
6. ``type == "api"`` (generic) → HttpApiHandler
7. Anything else → ValueError("Unknown source type...")
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.collect import _build_handler
from autoinfo.collectors.gdelt import GDELTHandler
from autoinfo.collectors.rss import RSSHandler
from autoinfo.collectors.unpaywall import UnpaywallHandler
from autoinfo.collectors.youtube import YouTubeHandler
from autoinfo.config import VALID_SOURCE_TYPES, SourceConfig

DEMO_DIR = Path(__file__).resolve().parents[1] / "src" / "autoinfo" / "data" / "domains"

# All 9 demo domains (5 legacy + 4 added by M3T24)
DOMAINS: list[str] = [
    "medical-research",
    "ai-commercial",
    "financial-intelligence",
    "tech-ai-developer",
    "language-learning",
    "general-news",
    "gaming",
    "b2b",
    "retail",
]

# Expected dispatch results
# All sources now pass — HttpApiHandler handles any type=api source
# that isn't pubmed (which gets PubMedHandler).
EXPECTED_PASS: dict[str, list[str]] = {
    "medical-research": ["pubmed", "arXiv", "CrossRef", "dblp", "openalex", "semantic-scholar", "uspto"],
    "ai-commercial": ["techcrunch", "producthunt", "Crunchbase", "36kr"],
    "financial-intelligence": ["Alpha Vantage", "FRED", "Finnhub", "SEC EDGAR", "Twelve Data", "World Bank Data", "Quandl/Nasdaq Data Link"],
    "tech-ai-developer": ["Substack RSS (tech) — Pragmatic Engineer", "GitHub Trending", "HackerNews API", "Stack Exchange", "ProductHunt", "Reddit", "Spotify AI Podcasts", "Bilibili (B站)"],
    "language-learning": ["project-gutenberg", "news-in-levels", "commonlit"],
    # M3T24 demo domains (D12/D14/D15/D16) — all sources dispatch cleanly
    "general-news": ["gdelt", "guardian-open-platform", "google-news-rss", "nyt", "ap-api", "zhihu-daily", "mastodon", "bluesky", "wechat2rss", "medium-user", "medium-publication", "medium-tag", "the-atlantic", "wired", "time-magazine"],
    "gaming": ["ign-rss", "polygon-rss", "gamesindustry-biz", "gcores-rss", "yystv-via-google-news"],
    "b2b": ["producthunt", "techcrunch", "crunchbase-news", "a16z", "hackernews"],
    "retail": ["retail-dive", "modern-retail", "ebrun-via-google-news", "shopify-news", "digiday"],
}

EXPECTED_FAIL: dict[str, list[str]] = {
    "medical-research": [],
    "ai-commercial": [],
    "financial-intelligence": [],
    "tech-ai-developer": [],
    "language-learning": [],
    "general-news": [],
    "gaming": [],
    "b2b": [],
    "retail": [],
}

# Flattened expected names for quick membership checks
_ALL_EXPECTED_PASS: set[str] = {n for names in EXPECTED_PASS.values() for n in names}
_ALL_EXPECTED_FAIL: set[str] = {n for names in EXPECTED_FAIL.values() for n in names}
_ALL_EXPECTED: set[str] = _ALL_EXPECTED_PASS | _ALL_EXPECTED_FAIL


def _load_sources(domain: str) -> list[dict[str, Any]]:
    """Load source definitions from a demo domain's ``sources.yaml``."""
    path = DEMO_DIR / domain / "sources.yaml"
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return data["sources"]


def test_source_dispatch_pass_fail() -> None:
    """Verify each configured source has a dispatch path (pass or documented ValueError).

    Asserts:
    * No unexpected exceptions (anything other than ValueError).
    * Pass and fail counts match EXPECTED_PASS / EXPECTED_FAIL per domain.
    """
    all_pass: list[tuple[str, str]] = []
    all_fail: list[tuple[str, str]] = []
    all_unexpected: list[tuple[str, str, str]] = []

    for domain in DOMAINS:
        sources = _load_sources(domain)
        for src in sources:
            name: str = src["name"]
            config = SourceConfig(
                name=name,
                type=src["type"],
                url=src.get("url", ""),
            )
            try:
                handler = _build_handler(config)
                assert handler is not None, f"Handler returned None for {domain}/{name}"
                all_pass.append((domain, name))
            except ValueError:
                all_fail.append((domain, name))
            except Exception as exc:
                all_unexpected.append((domain, name, str(exc)))

    # -----------------------------------------------------------------------
    # Summary output
    # -----------------------------------------------------------------------
    total = len(all_pass) + len(all_fail) + len(all_unexpected)
    print()
    print("=" * 70)
    print("  Source Dispatch Test Summary")
    print("=" * 70)
    print(f"  Total sources tested: {total}")
    print(f"  ✅ PASS (handler created):              {len(all_pass)}")
    print(f"  ❌ FAIL (ValueError — documented gap):  {len(all_fail)}")
    if all_unexpected:
        print(f"  💥 UNEXPECTED ERROR:                  {len(all_unexpected)}")
    print()

    for domain in DOMAINS:
        domain_pass = sorted(n for d, n in all_pass if d == domain)
        domain_fail = sorted(n for d, n in all_fail if d == domain)
        domain_unexp = [f"{n}: {e}" for d, n, e in all_unexpected if d == domain]
        print(f"  [{domain}]")
        for n in domain_pass:
            print(f"    ✅ {n}")
        for n in domain_fail:
            print(f"    ❌ {n}")
        for n in domain_unexp:
            print(f"    💥 {n}")
        print()

    # -----------------------------------------------------------------------
    # Assertions
    # -----------------------------------------------------------------------

    # 1. No unexpected exception types
    assert not all_unexpected, (
        f"Unexpected exceptions ({len(all_unexpected)}):\n" +
        "\n".join(f"  {d}/{n}: {e}" for d, n, e in all_unexpected)
    )

    # 2. Pass / fail counts per domain match expected
    for domain in DOMAINS:
        domain_pass_names: set[str] = {n for d, n in all_pass if d == domain}
        domain_fail_names: set[str] = {n for d, n in all_fail if d == domain}

        assert domain_pass_names == set(EXPECTED_PASS[domain]), (
            f"{domain}: PASS mismatch.\n"
            f"  Expected: {sorted(EXPECTED_PASS[domain])}\n"
            f"  Got:      {sorted(domain_pass_names)}"
        )
        assert domain_fail_names == set(EXPECTED_FAIL[domain]), (
            f"{domain}: FAIL mismatch.\n"
            f"  Expected: {sorted(EXPECTED_FAIL[domain])}\n"
            f"  Got:      {sorted(domain_fail_names)}"
        )

        # 3. Grand totals: 59 pass, 0 fail (29 legacy incl. M3T30 Finnhub + 30 M3T24)
        assert len(all_pass) == 59, f"Expected 59 PASS, got {len(all_pass)}"
        assert len(all_fail) == 0, f"Expected 0 FAIL, got {len(all_fail)}"
        assert total == 59, f"Expected 59 total sources, got {total}"


# ---------------------------------------------------------------------------
# VALID_SOURCE_TYPES parity with _build_handler dispatch
# ---------------------------------------------------------------------------

# Source types accepted by add_source but not dispatched by _build_handler:
# * webhook — inbound push, delivered via the webhook receiver
# * ssrn/gdelt/huggingface/kaggle/unpaywall/core — forward-declared types
#   whose collectors land in later implementation tasks (T7-T10)
_NON_DISPATCH_TYPES: frozenset[str] = frozenset({
    "webhook",
    "ssrn",
    "gdelt",
    "unpaywall",
    "core",
})

# Matches `stype == "x"` and `stype in ("a", "b")` in _build_handler source.
_DISPATCH_STYPE_RE = re.compile(
    r'stype\s*==\s*["\']([a-z_0-9]+)["\']|stype\s*in\s*\(\s*([^)]*?)\s*\)'
)


def _build_handler_dispatch_types() -> set[str]:
    """Extract every source type string compared against ``stype`` from the
    live ``_build_handler`` source, so this test can never silently drift
    from the real dispatch logic."""
    src = inspect.getsource(_build_handler)
    types: set[str] = set()
    for match in _DISPATCH_STYPE_RE.finditer(src):
        if match.group(1) is not None:
            types.add(match.group(1))
        else:
            types.update(re.findall(r'["\']([a-z_0-9]+)["\']', match.group(2)))
    return types


def test_valid_source_types_parity_with_build_handler() -> None:
    """VALID_SOURCE_TYPES must match every _build_handler dispatch type plus
    the documented non-dispatch types. Catches single-place drift: adding a
    branch to _build_handler without extending VALID_SOURCE_TYPES (or vice
    versa) fails this test."""
    dispatch_types = _build_handler_dispatch_types()
    expected = dispatch_types | set(_NON_DISPATCH_TYPES)

    # Direction 1: every type _build_handler can dispatch must be addable.
    missing = dispatch_types - set(VALID_SOURCE_TYPES)
    assert not missing, (
        "Types dispatchable in _build_handler but missing from VALID_SOURCE_TYPES: "
        f"{sorted(missing)}"
    )

    # Direction 2: VALID_SOURCE_TYPES must equal dispatch + documented extras.
    extra = set(VALID_SOURCE_TYPES) - expected
    assert set(VALID_SOURCE_TYPES) == expected, (
        f"VALID_SOURCE_TYPES drifted from _build_handler dispatch.\n"
        f"  In VALID_SOURCE_TYPES but not in _build_handler or _NON_DISPATCH_TYPES: "
        f"{sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# fetch_depth threading through dispatch (todo 14 — Phase B content depth)
# ---------------------------------------------------------------------------
# A source with ``fetch_depth: fulltext`` must reach its handler carrying the
# value, so the fulltext collectors (unpaywall / rss / youtube / gdelt) can
# branch on it. Handlers that receive only a settings dict must see it inside
# their ``config``; RSS (which receives only ``source_name``) must expose it
# as a handler attribute. Sources WITHOUT an explicit ``fetch_depth`` keep the
# ``"abstract"`` default — backward compatible.


@pytest.mark.parametrize(
    "source, handler_cls, settings_key",
    [
        (
            SourceConfig(
                name="oa-fulltext",
                type="unpaywall",
                fetch_depth="fulltext",
                settings={"provider": "core"},
            ),
            UnpaywallHandler,
            "provider",
        ),
        (
            SourceConfig(
                name="yt-fulltext",
                type="youtube",
                fetch_depth="fulltext",
                settings={"query": "machine learning"},
            ),
            YouTubeHandler,
            "query",
        ),
        (
            SourceConfig(
                name="news-fulltext",
                type="gdelt",
                fetch_depth="fulltext",
                settings={"maxrecords": 50},
            ),
            GDELTHandler,
            "maxrecords",
        ),
    ],
)
def test_fetch_depth_reaches_settings_based_handlers(
    source: SourceConfig,
    handler_cls: type[Any],
    settings_key: str,
) -> None:
    """``fetch_depth: fulltext`` on the source is visible on the constructed
    settings-based handler (unpaywall / youtube / gdelt)."""
    handler = _build_handler(source)
    assert isinstance(handler, handler_cls)
    assert handler.config.get("fetch_depth") == "fulltext"
    # Original settings survive alongside the injected fetch_depth.
    assert handler.config.get(settings_key) is not None
    # The shared SourceConfig settings dict is never mutated.
    assert "fetch_depth" not in source.settings


def test_fetch_depth_reaches_rss_handler() -> None:
    """RSS (which receives only ``source_name``) still sees per-source
    ``fetch_depth`` on the constructed handler."""
    handler = _build_handler(
        SourceConfig(
            name="feed-fulltext",
            type="rss",
            url="https://example.com/rss",
            fetch_depth="fulltext",
        )
    )
    assert isinstance(handler, RSSHandler)
    assert handler.source_name == "feed-fulltext"
    assert handler.fetch_depth == "fulltext"


def test_fetch_depth_defaults_to_abstract_when_unset() -> None:
    """Sources without an explicit ``fetch_depth`` behave identically to
    today: the ``"abstract"`` default flows through the dispatch."""
    rss = _build_handler(SourceConfig(name="feed", type="rss", url="https://example.com/rss"))
    assert isinstance(rss, RSSHandler)
    assert rss.fetch_depth == "abstract"

    for source in (
        SourceConfig(name="oa", type="unpaywall"),
        SourceConfig(name="yt", type="youtube"),
        SourceConfig(name="news", type="gdelt"),
    ):
        handler = _build_handler(source)
        assert handler.config.get("fetch_depth") == "abstract"
        assert isinstance(
            handler, (UnpaywallHandler, YouTubeHandler, GDELTHandler)
        )
