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
