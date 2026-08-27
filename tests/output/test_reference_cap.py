"""Tests for issue #11 — the references render cap (``ref_limit``).

A report/digest with 76-130 KB entries previously rendered every entry as a
numbered reference (~half the product surface).  This locks the fix:

- ``generate_report`` caps the ``references`` context at ``ref_limit``
  (default 60) at the context-build site (the entries list is sorted by
  (has non-empty summary desc, ``relevance_score`` desc) BEFORE the ref
  dicts are built — ref dicts drop ``relevance_score``/``summary``).
- ``_normalize_digest_product_context`` (digest-path products: premium/
  enterprise via digest) caps identically, so there is no format/path
  divergence (markdown/html/json/agent/audio/epub/video all capped at the
  build site).
- ``ref_limit`` precedence: explicit param > ``OutputConfig.ref_limit``
  (config.py) > default 60.
- Enterprise ``N key findings selected · M source references`` label-inversion
  hole (decision a): the product's ``key_findings`` in the render context is
  ALSO capped at ``min(_DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS,
  len(references))`` for the premium/enterprise families, so the label can
  never render ``9 key findings selected · 8 source references``.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import (
    _DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS,
    PRODUCT_TEMPLATES,
    DeliveryOutput,
    ProductTemplate,
    _normalize_digest_product_context,
    generate_report,
)


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return row["template"]
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


def _make_entries(n_summary: int, n_title_only: int) -> list[dict[str, Any]]:
    """``n_summary`` summary-bearing entries (relevance 1..N) + one top-score
    entry (relevance 99) + ``n_title_only`` title-only entries whose high
    relevance (61..) must NOT outrank the summary-bearing ones.  The
    title-only entries carry a real ``content`` body so the #294/#326
    product-entry filter keeps them (they model real Draft/Wiki entries with
    an empty DB summary)."""
    entries: list[dict[str, Any]] = []
    for i in range(1, n_summary + 1):
        entries.append({
            "entry_id": f"sum-{i}",
            "title": f"Summary Ref {i}",
            "summary": f"Summary content {i}.",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{10000000 + i}/",
            "source_type": "api",
            "source_platform": "pubmed",
            "domain": "medical-research",
            "relevance_score": float(i),
            "language": "en",
            "tags": "[]",
            "tier": "01-Raw",
            "collected_at": "2026-08-19T10:00:00Z",
        })
    entries.append({
        "entry_id": "top",
        "title": "Top Score Entry",
        "summary": "The single highest-relevance summary-bearing entry.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/99999999/",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": 99.0,
        "language": "en",
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-08-19T10:00:00Z",
    })
    for i in range(1, n_title_only + 1):
        entries.append({
            "entry_id": f"titleonly-{i}",
            "title": f"TitleOnly Ref {i}",
            "summary": "",
            "source_url": f"https://www.producthunt.com/posts/{i}",
            "source_type": "rss",
            "source_platform": "producthunt",
            "domain": "medical-research",
            "relevance_score": float(60 + i),
            "language": "en",
            "tags": "[]",
            "tier": "01-Raw",
            "collected_at": "2026-08-19T10:00:00Z",
            "content": f"Body content for title-only entry {i}.",
        })
    return entries


def _make_plain_entries(n: int) -> list[dict[str, Any]]:
    """``n`` summary-bearing entries with descending relevance (N..1)."""
    return [
        {
            "entry_id": f"e-{i}",
            "title": f"Entry {i}",
            "summary": f"Summary {i}.",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{20000000 + i}/",
            "source_type": "api",
            "source_platform": "pubmed",
            "domain": "medical-research",
            "relevance_score": float(n - i),
            "language": "en",
            "tags": "[]",
            "tier": "01-Raw",
            "collected_at": "2026-08-19T10:00:00Z",
        }
        for i in range(1, n + 1)
    ]


def _references_titles(md: str) -> list[str]:
    """Parse the ``## References`` numbered list titles out of rendered markdown."""
    titles: list[str] = []
    in_refs = False
    for line in md.splitlines():
        stripped = line.strip()
        if stripped == "## References":
            in_refs = True
            continue
        if in_refs:
            if stripped.startswith("---") or stripped.startswith("*AutoInfo"):
                break
            m = re.match(r"^\d+\. \*\*(.+?)\*\*", stripped)
            if m:
                titles.append(m.group(1))
    return titles


def _expected_ranked_titles(
    entries: list[dict[str, Any]], limit: int
) -> list[str]:
    """The titles the deterministic sort must produce (mirror of the fix)."""
    ranked = sorted(
        entries,
        key=lambda e: (
            bool(str(e.get("summary") or "").strip()),
            float(e.get("relevance_score") or 0.0),
        ),
        reverse=True,
    )
    return [e["title"] for e in ranked[:limit]]


def _synthesis(n_findings: int) -> dict[str, Any]:
    """A complete report synthesis dict (D1-required sections non-empty)."""
    return {
        "executive_summary": "Executive summary for the period.",
        "key_findings": [
            {"text": f"Finding number {i}"} for i in range(1, n_findings + 1)
        ],
        "recommendations": ["Monitor the period's developments."],
    }


# ---------------------------------------------------------------------------
# (a) Report-path cap applied (default ref_limit=60)
# ---------------------------------------------------------------------------


class TestReportPathReferenceCap:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_with_80_entries_renders_at_most_60_references(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock
    ) -> None:
        """80+ entries render exactly 60 references by default."""
        entries = _make_entries(60, 19)  # 61 summary-bearing + 19 title-only
        assert len(entries) == 80
        mock_synthesis.return_value = _synthesis(3)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        out = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown"
        ))
        titles = _references_titles(out)
        assert len(titles) == 60, (
            f"expected 60 references, got {len(titles)}"
        )
        # The first reference carries the max relevance_score.
        assert titles[0] == "Top Score Entry"
        # Title-only (empty summary) entries de-prioritize below summary-bearing.
        assert not any(t.startswith("TitleOnly Ref") for t in titles)
        assert "**References**: 60" in out

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_references_are_sorted_deterministically(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock
    ) -> None:
        """The rendered references match the (summary desc, relevance desc) order."""
        entries = _make_entries(60, 19)
        mock_synthesis.return_value = _synthesis(3)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        out = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown"
        ))
        assert _references_titles(out) == _expected_ranked_titles(entries, 60)


# ---------------------------------------------------------------------------
# (b) Explicit override: ref_limit=100
# ---------------------------------------------------------------------------


class TestReportPathReferenceOverride:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_report_ref_limit_100_renders_all_80(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock
    ) -> None:
        """``ref_limit=100`` renders the full 80-entry reference list (≤ 100)."""
        entries = _make_entries(60, 19)
        mock_synthesis.return_value = _synthesis(3)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        out = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown",
            ref_limit=100,
        ))
        titles = _references_titles(out)
        assert len(titles) == 80
        assert titles[0] == "Top Score Entry"
        # Title-only refs ARE present, but only after every summary-bearing ref.
        title_only_idx = next(
            i for i, t in enumerate(titles) if t.startswith("TitleOnly Ref")
        )
        assert title_only_idx >= 61
        assert "**References**: 80" in out


# ---------------------------------------------------------------------------
# (c) Digest-path consistency: _normalize_digest_product_context capped
#     identically to the report path
# ---------------------------------------------------------------------------


class TestDigestPathReferenceCap:
    def _context(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "title": "Weekly Digest \u2014 medical-research",
            "domain": "medical-research",
            "period": "weekly",
            "period_label": "Weekly",
            "date_from": "2026-08-03",
            "date_to": "2026-08-10",
            "generated_at": "2026-08-10T00:00:00+00:00",
            "entries": entries,
            "llm_synthesis": {
                "executive_summary": "Synthesis.",
                "key_findings": [],
                "recommendations": [],
            },
            "target_audience": "",
            "source_tier_badge": False,
        }

    def test_digest_product_context_capped_identically_to_report(self) -> None:
        """80-entry digest context -> exactly 60 references, same order as report."""
        entries = _make_entries(60, 19)
        flat = _normalize_digest_product_context(
            self._context(entries), "medical-research"
        )
        assert len(flat["references"]) == 60
        titles = [r["title"] for r in flat["references"]]
        assert titles == _expected_ranked_titles(entries, 60)
        assert titles[0] == "Top Score Entry"
        assert not any(t.startswith("TitleOnly Ref") for t in titles)

    def test_digest_product_context_override(self) -> None:
        """``ref_limit=100`` on the digest path keeps all 80 references."""
        entries = _make_entries(60, 19)
        flat = _normalize_digest_product_context(
            self._context(entries), "medical-research", ref_limit=100
        )
        assert len(flat["references"]) == 80


# ---------------------------------------------------------------------------
# (d) Enterprise ``N key findings selected · M source references`` label:
#     k findings (1 <= k <= 12) and m entries (12 <= m <= 60) always render
#     ``k key findings selected · m source references``; the discriminating
#     ``ref_limit=8`` with 9 findings case renders ``8 key findings selected ·
#     8 source references`` (decision a: key_findings min-capped), NEVER
#     ``9 key findings selected · 8 source references``.
# ---------------------------------------------------------------------------


class TestEnterpriseSelectedLabel:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    @pytest.mark.parametrize(
        ("k", "m"),
        [
            (1, 12),
            (9, 20),
            (12, 60),
        ],
    )
    def test_selected_k_of_m_never_inverts(
        self,
        mock_synthesis: MagicMock,
        mock_group: MagicMock,
        mock_kb: MagicMock,
        k: int,
        m: int,
    ) -> None:
        """With k <= 12 <= m (m within the default 60 cap), the label stays
        ``k key findings selected · m source references`` — no key_findings
        cap ever fires."""
        entries = _make_plain_entries(m)
        mock_synthesis.return_value = _synthesis(k)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        out = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown",
            product_template=_registry_template("enterprise-briefing"),
        ))
        assert f"{k} key findings selected · {m} source references" in out
        assert f"{m} key findings selected · {k} source references" not in out  # never inverted
        assert re.search(rf"of {m} key findings", out) is None

    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_ref_limit_8_with_9_findings_renders_selected_8_of_8(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock
    ) -> None:
        """The discriminating case: ``ref_limit=8`` with 9 LLM findings must
        render ``8 key findings selected · 8 source references`` (key_findings
        min-capped to min(12, len(references))), NEVER ``9 key findings
        selected · 8 source references``."""
        entries = _make_plain_entries(8)
        mock_synthesis.return_value = _synthesis(9)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        out = _as_text(generate_report(
            domain="medical-research", period="weekly", format="markdown",
            product_template=_registry_template("enterprise-briefing"),
            ref_limit=8,
        ))
        assert "8 key findings selected · 8 source references" in out
        assert "of 8 key findings" not in out
        assert "9 key findings selected" not in out

    def test_digest_path_ref_limit_8_with_9_findings_renders_selected_8_of_8(
        self,
    ) -> None:
        """Digest path: same discriminating case through
        ``_normalize_digest_product_context``."""
        entries = _make_plain_entries(8)
        ctx = {
            "title": "Weekly Digest \u2014 medical-research",
            "domain": "medical-research",
            "entries": entries,
            "llm_synthesis": {
                "executive_summary": "Synthesis.",
                "key_findings": [
                    {"topic": f"Topic {i}", "detail": f"Detail {i}."}
                    for i in range(1, 10)
                ],
                "recommendations": [],
            },
        }
        flat = _normalize_digest_product_context(
            ctx, "medical-research", product_family="enterprise-briefing",
            ref_limit=8,
        )
        assert len(flat["references"]) == 8
        assert len(flat["key_findings"]) == 8
        out = _registry_template("enterprise-briefing").render(
            "enterprise-briefing", "md", flat
        )
        assert "8 key findings selected · 8 source references" in out
        assert "of 8 key findings" not in out
        assert "9 key findings selected" not in out

    def test_key_findings_cap_never_exceeds_references_for_k_le_12(self) -> None:
        """General invariant: after normalization the enterprise flat context
        always satisfies len(key_findings) <= len(references)."""
        for m in (12, 20, 60):
            entries = _make_plain_entries(m)
            ctx = {
                "title": "t",
                "domain": "medical-research",
                "entries": entries,
                "llm_synthesis": {
                    "executive_summary": "S.",
                    "key_findings": [
                        {"topic": f"T{i}", "detail": f"D{i}."}
                        for i in range(1, _DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS + 1)
                    ],
                    "recommendations": [],
                },
            }
            flat = _normalize_digest_product_context(
                ctx, "medical-research", product_family="enterprise-briefing"
            )
            assert len(flat["key_findings"]) <= len(flat["references"]), m
            assert len(flat["key_findings"]) == _DEDICATED_PRODUCT_PROMPT_MAX_FINDINGS


# ---------------------------------------------------------------------------
# OutputConfig.ref_limit precedence helper (config-default wiring)
# ---------------------------------------------------------------------------


class TestOutputConfigRefLimitPrecedence:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._group_by_theme")
    @patch("autoinfo.output._generate_executive_summary")
    def test_config_ref_limit_used_when_param_omitted(
        self, mock_synthesis: MagicMock, mock_group: MagicMock, mock_kb: MagicMock,
        tmp_path: Any,
    ) -> None:
        """A config file declaring ``output.ref_limit: 30`` drives the default
        when the explicit param is omitted; the explicit param wins over it."""
        import os

        import yaml

        cfg_dir = tmp_path / ".autoinfo"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {"name": "test"},
                    "domains": [],
                    "output": {"ref_limit": 30},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        entries = _make_entries(60, 19)
        mock_synthesis.return_value = _synthesis(3)
        mock_group.return_value = []
        mock_kb.return_value = _mock_store(entries)
        old = os.getcwd()
        os.chdir(tmp_path)
        try:
            # config-default path: output.ref_limit=30 -> 30 references
            out = _as_text(generate_report(
                domain="medical-research", period="weekly", format="markdown"
            ))
            assert len(_references_titles(out)) == 30
            # explicit param wins over the config value
            out2 = _as_text(generate_report(
                domain="medical-research", period="weekly", format="markdown",
                ref_limit=50,
            ))
            assert len(_references_titles(out2)) == 50
        finally:
            os.chdir(old)


def _mock_store(entries: list[dict[str, Any]]) -> MagicMock:
    """A KBStore stub returning *entries* for any domain."""
    store = MagicMock()
    store.list_entries.return_value = entries
    return store
