"""Tests for #325 — specific source labels across ALL product surfaces.

The #323/#325 fix (``_derive_source_label``) was applied at only the report
references and digest product-context builders, so stale pre-#323 entries
(``source_platform='rss'``) still rendered the generic ``(RSS)`` label on the
entry-level surfaces: the digest markdown entry table, the magazine-digest
byline + per-title clusters, the digest json/agent formats, and the report
agent payload.

This suite locks the fix: ``generate_digest`` enriches every entry with a
derived ``source_label`` (via ``_label_entries``) before the context is built,
the templates render ``source_label``, and the report agent path derives the
label per item — so the specific source name appears and no ``(RSS)`` /
``RSS`` / ``(rss)`` residue renders anywhere.
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    DeliveryOutput,
    ReportData,
    ReportSection,
    _normalize_digest_product_context,
    _report_data_to_dict,
    generate_digest,
    generate_report,
)

STALE_SOURCE_NAME = "techcrunch"
STALE_SOURCE_URL = "https://techcrunch.com/2026/01/01/ai-startup"


def _as_text(result: str | DeliveryOutput) -> str:
    """Extract the rendered body from a generate_* return value."""
    if isinstance(result, DeliveryOutput):
        return result.output
    return str(result)


def _write_config(tmp_path: Any) -> None:
    """Write a minimal project config with an ai-commercial techcrunch source."""
    cfg_dir = tmp_path / ".autoinfo"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "project": {"name": "test"},
        "llm": {"provider": "openai", "model": "deepseek-v4-flash"},
        "domains": [
            {
                "name": "ai-commercial",
                "active": True,
                "sources": [
                    {
                        "name": STALE_SOURCE_NAME,
                        "type": "rss",
                        "url": "https://techcrunch.com/feed/",
                    }
                ],
                "topics": [],
            }
        ],
    }
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _stale_entry() -> dict[str, Any]:
    """A pre-#323 KB entry: generic ``source_platform='rss'`` but a real
    source_url whose host matches the configured techcrunch source."""
    return {
        "entry_id": "e-325-stale",
        "title": "AI startup raises $50M",
        "summary": "TechCrunch reports on the funding round.",
        "source_url": STALE_SOURCE_URL,
        "source_type": "rss",
        "source_platform": "rss",
        "language": "en",
        "relevance_score": 90.0,
        "tags": "[]",
        "tier": "01-Raw",
        "collected_at": "2026-08-19T10:00:00Z",
    }


_SYNTH: dict[str, Any] = {
    "executive_summary": "Synthesis.",
    "key_findings": [],
    "recommendations": [],
}


def _magazine_template() -> Any:
    for row in PRODUCT_TEMPLATES:
        if row["name"] == "magazine-digest":
            return row["template"]
    raise AssertionError("magazine-digest ProductTemplate row missing")


def _report_template(name: str) -> Any:
    """The ProductTemplate for a report-path product family (#325)."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return row["template"]
    raise AssertionError(f"{name} ProductTemplate row missing")


@pytest.fixture
def stale_config(tmp_path: Any) -> Any:
    """Write the source config and chdir into the temp project dir."""
    _write_config(tmp_path)
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _assert_no_rss_residue(body: str) -> None:
    """The rendered surface must carry no generic RSS label residue."""
    assert "(RSS)" not in body
    assert "RSS" not in body
    assert "(rss)" not in body


class TestSourceLabelSurfaces:
    def test_digest_markdown_entry_table(
        self, stale_config: Any
    ) -> None:
        """The digest entry-table Source row renders the specific name."""
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._call_llm_for_digest", return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_digest(
                domain="ai-commercial", period="weekly", format="markdown"
            ))
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)

    def test_magazine_digest_byline_and_clusters(
        self, stale_config: Any
    ) -> None:
        """The magazine byline + per-title clusters use the specific name."""
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._call_llm_for_digest", return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_digest(
                domain="ai-commercial", period="weekly", format="markdown",
                product_template=_magazine_template(),
            ))
        assert STALE_SOURCE_NAME in out
        assert f"**{STALE_SOURCE_NAME}**" in out
        assert f"## {STALE_SOURCE_NAME}" in out
        _assert_no_rss_residue(out)

    def test_digest_json_carries_source_label(
        self, stale_config: Any
    ) -> None:
        """The digest json entry carries the derived ``source_label``."""
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._call_llm_for_digest", return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_digest(
                domain="ai-commercial", period="weekly", format="json"
            ))
        data = json.loads(out)
        entry = data["entries"][0]
        assert entry["source_label"] == STALE_SOURCE_NAME
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)

    def test_digest_agent_carries_specific_source(
        self, stale_config: Any
    ) -> None:
        """The digest agent payload's source_platform is the specific name."""
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._call_llm_for_digest", return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_digest(
                domain="ai-commercial", period="weekly", format="agent"
            ))
        data = json.loads(out)
        assert data["entries"][0]["source_platform"] == STALE_SOURCE_NAME
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)

    def test_report_agent_carries_specific_source(
        self, stale_config: Any
    ) -> None:
        """The report agent payload's source_platform is the specific name."""
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._group_by_theme",
                   return_value=[{
                       "theme": "AI Funding",
                       "description": "Funding rounds.",
                       "entries": [_stale_entry()],
                   }]), \
             patch("autoinfo.output._generate_executive_summary",
                   return_value={"executive_summary": "Overview.",
                                 "key_findings": [], "recommendations": []}):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_report(
                domain="ai-commercial", period="weekly", format="agent"
            ))
        data = json.loads(out)
        assert data["entries"][0]["source_platform"] == STALE_SOURCE_NAME
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)

    def test_report_json_entries_carry_derived_source_label(
        self, stale_config: Any
    ) -> None:
        """#325 — the report json ``entries`` carry the derived source label
        instead of the raw ``source_platform='rss'`` for stale pre-#323
        entries.  RED today: ``_render_report_json`` emits the raw item
        ``source_platform`` (verified ``entries[0].source_platform == 'rss'``).
        """
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._group_by_theme",
                   return_value=[{
                       "theme": "AI Funding",
                       "description": "Funding rounds.",
                       "entries": [_stale_entry()],
                   }]), \
             patch("autoinfo.output._generate_executive_summary",
                   return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_report(
                domain="ai-commercial", period="weekly", format="json"
            ))
        data = json.loads(out)
        assert data["entries"][0]["source_platform"] == STALE_SOURCE_NAME
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)

    def test_report_markdown_references_prefer_source_label(
        self, stale_config: Any
    ) -> None:
        """#325 — the report markdown References render the specific source
        name, and no RSS residue appears in the whole body.

        The report-path references are already derived at generation time
        (``_derive_source_label``), so this locks the rendered surface and —
        the NEW behavior — the flat render context carries the derived
        ``source_label`` on the references for the templates to consume.
        """
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._group_by_theme",
                   return_value=[{
                       "theme": "AI Funding",
                       "description": "Funding rounds.",
                       "entries": [_stale_entry()],
                   }]), \
             patch("autoinfo.output._generate_executive_summary",
                   return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_report(
                domain="ai-commercial", period="weekly", format="markdown"
            ))
        # The references line renders the derived name, never "(RSS)".
        assert "(techcrunch)" in out
        assert STALE_SOURCE_NAME in out
        _assert_no_rss_residue(out)
        # The flat context the report templates consume carries a derived
        # ``source_label`` on the reference (target fix: templates render
        # ``ref.source_label or ref.source_platform``).
        flat = _report_data_to_dict(
            ReportData(
                title="ai-commercial \u2014 Report",
                generated_at="2026-08-21 00:00 UTC",
                domain="ai-commercial",
                executive_summary="Synthesis.",
                sections=[
                    ReportSection(
                        title="AI Funding",
                        content="Funding rounds.",
                        items=[_stale_entry()],
                    )
                ],
                references=[{
                    "title": _stale_entry()["title"],
                    "source_url": STALE_SOURCE_URL,
                    "source_type": "rss",
                    "source_platform": STALE_SOURCE_NAME,
                    "domain": "ai-commercial",
                }],
            )
        )
        assert flat["references"][0]["source_label"] == STALE_SOURCE_NAME

    def test_column_premium_enterprise_markdown_no_rss_residue(
        self, stale_config: Any
    ) -> None:
        """#325 — column / premium-briefing / enterprise-briefing templates
        prefer the derived ``source_label`` over the raw ``source_platform``
        in their References.  RED today: the templates render
        ``ref.source_platform | platform_name`` with no ``source_label``
        fallback, so a stale reference (``source_platform='rss'``) renders
        "(RSS)".  After the fix the flat context carries the derived
        ``source_label`` and the templates render it.
        """
        entry = _stale_entry()
        data = ReportData(
            title="ai-commercial \u2014 Report",
            generated_at="2026-08-21 00:00 UTC",
            domain="ai-commercial",
            executive_summary="Synthesis.",
            sections=[
                ReportSection(
                    title="AI Funding",
                    content="Funding rounds.",
                    items=[entry],
                )
            ],
            references=[{
                "title": entry["title"],
                "source_url": STALE_SOURCE_URL,
                "source_type": entry["source_type"],
                "source_platform": entry["source_platform"],
                "domain": "ai-commercial",
            }],
        )
        flat = _report_data_to_dict(data)
        for name in ("column", "premium-briefing", "enterprise-briefing"):
            out = _report_template(name).render(name, "md", flat)
            assert STALE_SOURCE_NAME in out, f"{name} lost the specific source"
            _assert_no_rss_residue(out)

    def test_report_section_items_carry_source_label(
        self, stale_config: Any
    ) -> None:
        """#325 — every section ``entries[i].source_platform`` in the report
        JSON output is the derived source name, not the raw ``'rss'``.  RED
        today: the section items are built verbatim from the KB entries at
        L5262-5272, so the JSON render surfaces ``source_platform='rss'``.
        """
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._group_by_theme",
                   return_value=[{
                       "theme": "AI Funding",
                       "description": "Funding rounds.",
                       "entries": [_stale_entry()],
                   }]), \
             patch("autoinfo.output._generate_executive_summary",
                   return_value=_SYNTH):
            kb = MagicMock()
            kb.list_entries.return_value = [_stale_entry()]
            kb_cls.return_value = kb
            out = _as_text(generate_report(
                domain="ai-commercial", period="weekly", format="json"
            ))
        data = json.loads(out)
        assert data["entries"], "report JSON carried no entries"
        for entry in data["entries"]:
            assert entry["source_platform"] == STALE_SOURCE_NAME, (
                f"section entry rendered raw platform {entry['source_platform']!r}"
            )

    def test_title_only_entry_reference_not_bare(
        self, stale_config: Any
    ) -> None:
        """A title-only ProductHunt reference (empty summary, e.g. OpenLogi)
        must render a description fallback — never the bare title+platform
        line.  RED today: the ref builders carry no ``description`` key, so
        the References line renders ``**OpenLogi** (producthunt)`` with no
        context.  After the fix the builders carry
        ``summary → content[:120] → '<label> item'`` and the templates render
        it after the source_url fragment.
        """
        openlogi = {
            "entry_id": "e-openlogi",
            "title": "OpenLogi",
            "summary": "",
            "source_url": "https://www.producthunt.com/posts/openlogi",
            "source_type": "rss",
            "source_platform": "producthunt",
            "domain": "b2b",
            "relevance_score": 80.0,
            "tier": "01-Raw",
            "collected_at": "2026-08-25T10:00:00Z",
        }
        summary_entry = {
            "entry_id": "e-ai-copilot",
            "title": "AI copilot for sales teams",
            "summary": "A real description here.",
            "source_url": "https://www.producthunt.com/posts/ai-copilot",
            "source_type": "rss",
            "source_platform": "producthunt",
            "domain": "b2b",
            "relevance_score": 90.0,
            "tier": "01-Raw",
            "collected_at": "2026-08-25T10:00:00Z",
        }
        entries = [openlogi, summary_entry]

        # (a) digest ref builder: title-only entry falls back to "<label> item".
        flat = _normalize_digest_product_context(
            {
                "title": "b2b \u2014 Report",
                "domain": "b2b",
                "generated_at": "2026-08-25 00:00 UTC",
                "entries": entries,
                "llm_synthesis": _SYNTH,
            },
            domain="b2b",
        )
        refs = {r["title"]: r for r in flat["references"]}
        assert refs["OpenLogi"]["description"], (
            "title-only ref must carry a non-empty description"
        )

        # (b)+(c) rendered report References; the empty-entry filter is
        # patched to identity (orthogonal to this rendering contract).
        with patch("autoinfo.output.KBStore") as kb_cls, \
             patch("autoinfo.output._group_by_theme", return_value=[]), \
             patch("autoinfo.output._generate_executive_summary",
                   return_value=_SYNTH), \
             patch("autoinfo.output._filter_product_entries",
                   side_effect=lambda es: list(es)):
            kb = MagicMock()
            kb.list_entries.return_value = entries
            kb_cls.return_value = kb
            out = _as_text(generate_report(
                domain="b2b", period="weekly", format="markdown"
            ))
        refs_section = out.split("## References", 1)[1]
        openlogi_line = next(
            line for line in refs_section.splitlines() if "OpenLogi" in line
        )
        # (b) not the bare form: the fallback description renders.
        assert "producthunt item" in openlogi_line, openlogi_line
        # (c) the summary-bearing entry renders its own summary as description.
        assert "A real description here." in refs_section


# ---------------------------------------------------------------------------
# T1/T2 (issue #325 data layer): _host_matches_source contract + recovery of
# stale entries whose URL host does NOT exactly equal the configured feed host
# (arXiv article links on arxiv.org vs feed host rss.arxiv.org) and stale
# entries from non-rss source types (openalex/dblp/quandl/sec_edgar).
# ---------------------------------------------------------------------------


class TestHostMatchesSource:
    """Contract for ``autoinfo.output._host_matches_source`` (RED until T3)."""

    def test_subdomain_matches(self) -> None:
        from autoinfo.output import _host_matches_source

        # RSS feed host vs article host: subdomain relationship.
        assert _host_matches_source("arxiv.org", "rss.arxiv.org") is True
        assert _host_matches_source("arxiv.org", "export.arxiv.org") is True
        assert _host_matches_source("36kr.com", "www.36kr.com") is True

    def test_exact_and_www_normalised(self) -> None:
        from autoinfo.output import _host_matches_source

        assert _host_matches_source("techcrunch.com", "techcrunch.com") is True
        assert _host_matches_source("techcrunch.com", "www.techcrunch.com") is True

    def test_unrelated_hosts_do_not_match(self) -> None:
        from autoinfo.output import _host_matches_source

        assert _host_matches_source("example.com", "arxiv.org") is False
        assert _host_matches_source("pitchfork.com", "techcrunch.com") is False

    def test_substring_trap_rejected(self) -> None:
        from autoinfo.output import _host_matches_source

        # "evil-arxiv.org" ends with "arxiv.org" as a bare substring but NOT
        # at a label boundary — must not match.
        assert _host_matches_source("evil-arxiv.org", "arxiv.org") is False

    def test_empty_or_invalid_hosts_do_not_match(self) -> None:
        from autoinfo.output import _host_matches_source

        assert _host_matches_source("", "arxiv.org") is False
        assert _host_matches_source("arxiv.org", "") is False
        assert _host_matches_source("", "") is False


class TestSourceLabelDataLayerRecovery:
    """Issue #325 data layer — stale entries recovered by host/type matching.

    RED until T3/T4: ``_derive_source_label`` only does exact host equality
    (fails arXiv article-vs-feed host) and ``_MATCHABLE_SOURCE_TYPES`` skips
    openalex/dblp/quandl/sec_edgar.
    """

    def _label(self, source_url: str, platform: str = "rss",
               domain: str = "medical-research",
               source_configs: list[Any] | None = None) -> str:
        from autoinfo.output import _derive_source_label

        entry = {
            "entry_id": "e-stale",
            "title": "t",
            "summary": "s",
            "source_url": source_url,
            "source_type": "rss",
            "source_platform": platform,
            "relevance_score": 90.0,
            "tags": "[]",
            "tier": "01-Raw",
            "collected_at": "2026-08-19T10:00:00Z",
        }
        if source_configs is not None:
            return _derive_source_label(
                entry, domain, source_configs=source_configs,
            )
        return _derive_source_label(entry, domain)

    def test_host_mismatch_arxiv_recovered(self) -> None:
        """arXiv article link (arxiv.org) vs configured feed host
        (rss.arxiv.org) — the stale 'rss' entry must recover 'arXiv'.

        The source configs are passed EXPLICITLY so the test is deterministic
        (the derivation reads the runtime config when source_configs is None,
        which is absent in CI's fresh checkout).
        """
        from autoinfo.config import SourceConfig

        configs = [
            SourceConfig(name="arXiv", type="rss",
                         url="https://rss.arxiv.org/rss/q-bio"),
        ]
        label = self._label(
            "https://arxiv.org/abs/2401.12345", source_configs=configs,
        )
        assert label.lower() != "rss", f"arXiv host mismatch not recovered: {label!r}"
        assert label

    def test_openalex_source_recovered(self) -> None:
        label = self._label(
            "https://api.openalex.org/works/W123", platform="openalex"
        )
        assert label.lower() != "rss", f"openalex not recovered: {label!r}"
        assert label

    def test_dblp_source_recovered(self) -> None:
        label = self._label("https://dblp.org/rec/conf/aaai/2023", platform="dblp")
        assert label.lower() != "rss", f"dblp not recovered: {label!r}"
        assert label

    def test_quandl_source_recovered(self) -> None:
        label = self._label(
            "https://www.quandl.com/data/EIA/PET", platform="quandl",
            domain="financial-intelligence",
        )
        assert label.lower() != "rss", f"quandl not recovered: {label!r}"
        assert label

    def test_sec_edgar_source_recovered(self) -> None:
        label = self._label(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000013/aapl-20260328.htm",
            platform="sec_edgar", domain="financial-intelligence",
        )
        assert label.lower() != "rss", f"sec_edgar not recovered: {label!r}"
        assert label

    def test_unrelated_host_stays_unchanged(self) -> None:
        """A stale rss entry pointing at an unrelated host must NOT be
        mislabelled — it keeps its generic platform (no false positive)."""
        label = self._label("https://example.com/some/random/article")
        assert label == "rss"

    def test_specific_platform_passthrough(self) -> None:
        """Non-generic stored platforms are returned unchanged."""
        label = self._label("https://eutils.ncbi.nlm.nih.gov/...", platform="pubmed")
        assert label == "pubmed"
