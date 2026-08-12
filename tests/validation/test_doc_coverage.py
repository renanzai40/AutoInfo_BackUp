"""Integration test: verify blocked-sources.md covers all doc-only sources (A7, A18, A19, A20).

Reads docs/known-limitations/blocked-sources.md and asserts that every source
listed in the enduser-coverage-matrix (A7, A18, A19, A20) is documented.

Coverage matrix reference: docs/dev/enduser-coverage-matrix.md

  A7  — Financial Data (institutional): Bloomberg, Refinitiv, Wind
  A18 — Paid News / Wire Services:      WSJ, FT, 财新, 新华社
  A19 — Chinese Knowledge Platforms:    知乎, 得到, 微信公众号
  A20 — Social / Microblog:             X/Twitter, 微博, 抖音, 小红书
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BLOCKED_SOURCES_PATH = Path(__file__).resolve().parents[2] / "docs" / "known-limitations" / "blocked-sources.md"


@pytest.fixture(scope="module")
def blocked_sources_content() -> str:
    """Load the blocked-sources.md document once for all tests."""
    assert BLOCKED_SOURCES_PATH.exists(), f"Missing: {BLOCKED_SOURCES_PATH}"
    return BLOCKED_SOURCES_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A7 — Financial Data (institutional): Bloomberg, Refinitiv, Wind
# ---------------------------------------------------------------------------

A7_TERMS = ["Bloomberg", "Refinitiv", "Wind"]


@pytest.mark.parametrize("term", A7_TERMS, ids=[f"A7-{t}" for t in A7_TERMS])
def test_a7_financial_institutional_covered(term: str, blocked_sources_content: str) -> None:
    """A7: Each institutional financial source must appear in blocked-sources.md."""
    assert term in blocked_sources_content, (
        f"A7 source '{term}' not found in blocked-sources.md. "
        "Expected Bloomberg, Refinitiv, and Wind (万得) coverage."
    )


def test_a7_wind_chinese_name_covered(blocked_sources_content: str) -> None:
    """A7: Wind's Chinese name 万得 should also appear for discoverability."""
    assert "万得" in blocked_sources_content, "Wind's Chinese name '万得' not found in blocked-sources.md."


# ---------------------------------------------------------------------------
# A18 — Paid News / Wire Services: WSJ, FT, 财新, 新华社
# ---------------------------------------------------------------------------

A18_TERMS = ["WSJ", "FT", "财新", "新华社"]


@pytest.mark.parametrize("term", A18_TERMS, ids=[f"A18-{t}" for t in A18_TERMS])
def test_a18_paid_news_wire_covered(term: str, blocked_sources_content: str) -> None:
    """A18: Each paid news / wire service source must appear in blocked-sources.md."""
    assert term in blocked_sources_content, (
        f"A18 source '{term}' not found in blocked-sources.md. "
        "Expected WSJ, FT, 财新 (Caixin), and 新华社 (Xinhua) coverage."
    )


def test_a18_has_detailed_sections(blocked_sources_content: str) -> None:
    """A18: WSJ, FT, 财新, and 新华社 should each have a dedicated heading, not just a summary row."""
    heading_re = re.compile(r"^#{2,4}\s+.*", re.MULTILINE)
    headings = heading_re.findall(blocked_sources_content)
    for term in ["Wall Street Journal", "Financial Times", "财新", "新华社"]:
        assert any(term in h for h in headings), (
            f"No dedicated heading found for '{term}' in blocked-sources.md."
        )


# ---------------------------------------------------------------------------
# A19 — Chinese Knowledge Platforms: 知乎, 得到, 微信公众号
# ---------------------------------------------------------------------------

A19_TERMS = ["知乎", "得到", "微信公众号"]


@pytest.mark.parametrize("term", A19_TERMS, ids=[f"A19-{t}" for t in A19_TERMS])
def test_a19_chinese_knowledge_platforms_covered(term: str, blocked_sources_content: str) -> None:
    """A19: Each Chinese knowledge platform must appear in blocked-sources.md."""
    assert term in blocked_sources_content, (
        f"A19 source '{term}' not found in blocked-sources.md. "
        "Expected 知乎 (Zhihu), 得到 (Dedao), and 微信公众号 (WeChat OA) coverage."
    )


def test_a19_wechat_english_alias_covered(blocked_sources_content: str) -> None:
    """A19: WeChat OA English alias should appear for discoverability."""
    assert "WeChat Official Account" in blocked_sources_content, (
        "WeChat Official Account (English alias) not found in blocked-sources.md."
    )


def test_a19_has_detailed_sections(blocked_sources_content: str) -> None:
    """A19: 知乎, 得到, and 微信公众号 should each have a dedicated heading."""
    heading_re = re.compile(r"^#{2,4}\s+.*", re.MULTILINE)
    headings = heading_re.findall(blocked_sources_content)
    for term in ["知乎", "得到", "微信公众号"]:
        assert any(term in h for h in headings), (
            f"No dedicated heading found for '{term}' in blocked-sources.md."
        )


# ---------------------------------------------------------------------------
# A20 — Social / Microblog: X/Twitter, 微博, 抖音, 小红书
# ---------------------------------------------------------------------------

A20_TERMS = ["Twitter", "微博", "抖音", "小红书"]


@pytest.mark.parametrize("term", A20_TERMS, ids=[f"A20-{t}" for t in A20_TERMS])
def test_a20_social_microblog_covered(term: str, blocked_sources_content: str) -> None:
    """A20: Each social / microblog source must appear in blocked-sources.md."""
    assert term in blocked_sources_content, (
        f"A20 source '{term}' not found in blocked-sources.md. "
        "Expected X/Twitter, 微博 (Weibo), 抖音 (Douyin), and 小红书 (Xiaohongshu) coverage."
    )


def test_a20_has_detailed_sections(blocked_sources_content: str) -> None:
    """A20: 微博, 抖音, and 小红书 should each have a dedicated heading."""
    heading_re = re.compile(r"^#{2,4}\s+.*", re.MULTILINE)
    headings = heading_re.findall(blocked_sources_content)
    for term in ["微博", "抖音", "小红书"]:
        assert any(term in h for h in headings), (
            f"No dedicated heading found for '{term}' in blocked-sources.md."
        )


# ---------------------------------------------------------------------------
# Combined grep assertion (matches the task's exit-0 check)
# ---------------------------------------------------------------------------

def test_combined_grep_assertion(blocked_sources_content: str) -> None:
    """The combined grep 'WSJ|FT|知乎|Twitter' must match (equivalent to exit 0)."""
    pattern = re.compile(r"WSJ|FT|知乎|Twitter")
    assert pattern.search(blocked_sources_content), (
        "Combined grep 'WSJ|FT|知乎|Twitter' did not match blocked-sources.md."
    )


# ---------------------------------------------------------------------------
# Structural integrity: summary table should list all blocked sources
# ---------------------------------------------------------------------------

# Terms expected in the Summary table (uses full names / abbreviations as written in the table)
SUMMARY_TABLE_TERMS = [
    # A7
    "Bloomberg", "Refinitiv", "Wind",
    # A18 (summary uses full names for WSJ/FT)
    "Wall Street Journal", "Financial Times", "财新", "新华社",
    # A19
    "知乎", "得到", "微信公众号",
    # A20
    "Twitter", "微博", "抖音", "小红书",
    # A7 Chinese alias
    "万得",
]


def test_summary_table_lists_all_sources(blocked_sources_content: str) -> None:
    """The Summary table section should reference every blocked source."""
    summary_section = blocked_sources_content.split("## Summary")[1] if "## Summary" in blocked_sources_content else ""
    assert summary_section, "No '## Summary' section found in blocked-sources.md."

    missing = [t for t in SUMMARY_TABLE_TERMS if t not in summary_section]
    assert not missing, f"Summary table missing references to: {missing}"