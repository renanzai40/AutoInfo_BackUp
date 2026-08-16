# mypy: ignore-errors
"""Tests for digest-path context normalization (output-quality-mega, todo 5).

Covers the dual-context contract: when ``generate_digest`` is called with a
``product_template``, the render context MUST be normalized to the flat
§2.1 shape of ``.omo/evidence/phaseA-template-spec.md`` — mirroring the
report path's ``_report_data_to_dict`` output:

- ``executive_summary`` (str, ``""`` when absent)
- ``key_findings`` (``list[dict]`` — ``{topic, detail}`` dicts converted to
  ``{"text": "Topic: detail", "source_url": ...}`` objects; partial items
  kept, empty items dropped; ``source_url`` back-filled from the entries
  on an unambiguous title match — issue #279)
- ``recommendations`` (``list[str]``)
- ``references`` (``list[dict]`` of exactly 5 keys derived from entries:
  ``title``, ``source_url``, ``source_type``, ``source_platform``, ``domain``)

so ``premium-briefing.md.j2`` / ``enterprise-briefing.md.j2`` render
non-empty on the digest path, same as the report path.

Regression guards:

- The default digest (NO ``product_template``) still renders
  ``digest.md.j2`` unchanged (``tests/test_magazine_digest.py`` stays green).
- The ``format in ("markdown", "html", "json", "agent")`` non-template
  branches are untouched (raw digest context, no flattening).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    PRODUCT_TEMPLATES,
    ProductTemplate,
    _normalize_digest_product_context,
    generate_digest,
)

# ===================================================================
# Sample data
# ===================================================================

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "entry-001",
        "title": "Improved IVF outcomes with time-lapse imaging",
        "summary": "Time-lapse imaging improves live birth rates in IVF.",
        "source_url": "https://example.com/ivf-1",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": 92.0,
        "tags": '["IVF", "embryo"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-15T10:00:00Z",
    },
    {
        "entry_id": "entry-002",
        "title": "AI-driven embryo selection: a systematic review",
        "summary": "AI models show promise but lack prospective validation.",
        "source_url": "https://example.com/ivf-2",
        "source_type": "api",
        "source_platform": "pubmed",
        "domain": "medical-research",
        "relevance_score": 85.0,
        "tags": '["AI", "IVF"]',
        "tier": "01-Raw",
        "collected_at": "2026-07-16T10:00:00Z",
    },
]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's key developments focus on IVF technology "
        "advancements including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": "Significant improvement in live birth rates (48.2% vs 39.5%).",
        },
        {
            "topic": "AI embryo selection",
            "detail": "Promising but lacks prospective clinical validation.",
        },
    ],
    "trends": [
        "Increasing integration of AI/ML in reproductive medicine",
        "Growing evidence for time-lapse imaging benefits",
    ],
    "recommendations": [
        "Consider time-lapse imaging as standard of care",
        "Support prospective AI validation trials",
    ],
}


def _mock_list_entries(
    domain: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
    offset: int = 0,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Return sample entries for any domain (mirrors test_digest helper)."""
    return _SAMPLE_ENTRIES


def _registry_template(name: str) -> ProductTemplate:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return row["template"]
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _premium_briefing_template() -> ProductTemplate:
    """Return the premium-briefing ProductTemplate row from the registry."""
    return _registry_template("premium-briefing")


def _enterprise_briefing_template() -> ProductTemplate:
    """Return the enterprise-briefing ProductTemplate row from the registry."""
    return _registry_template("enterprise-briefing")


def _render_digest(
    *,
    product_template: ProductTemplate | None = None,
    format: str = "markdown",
) -> str:
    """Render a digest through generate_digest with the shared mocks."""
    with (
        patch("autoinfo.output.KBStore") as mock_kb_cls,
        patch("autoinfo.output._call_llm_for_digest") as mock_llm,
    ):
        mock_llm.return_value = _SAMPLE_LLM_SYNTHESIS
        mock_store = MagicMock()
        mock_store.list_entries.side_effect = _mock_list_entries
        mock_kb_cls.return_value = mock_store
        result = generate_digest(
            domain="medical-research",
            period="weekly",
            format=format,
            product_template=product_template,
        )
    assert isinstance(result, str)
    return result


# ===================================================================
# Unit tests: _normalize_digest_product_context
# ===================================================================


class TestNormalizeDigestProductContext:
    """The flat-context normalizer (digest path, §2.3)."""

    def _context(
        self, llm_synthesis: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "title": "Weekly Digest \u2014 medical-research",
            "domain": "medical-research",
            "period": "weekly",
            "period_label": "Weekly",
            "date_from": "2026-08-03",
            "date_to": "2026-08-10",
            "generated_at": "2026-08-10T00:00:00+00:00",
            "entries": _SAMPLE_ENTRIES,
            "llm_synthesis": (
                _SAMPLE_LLM_SYNTHESIS if llm_synthesis is None else llm_synthesis
            ),
            "target_audience": "",
            "source_tier_badge": False,
        }

    def test_flattens_llm_synthesis_to_top_level_keys(self) -> None:
        """executive_summary / key_findings / recommendations move to the top."""
        flat = _normalize_digest_product_context(self._context(), "medical-research")
        assert flat["executive_summary"] == _SAMPLE_LLM_SYNTHESIS["executive_summary"]
        # {topic, detail} -> {text, source_url} objects; source_url
        # back-filled from the entries on unambiguous title match (#279).
        assert flat["key_findings"] == [
            {
                "text": "Time-lapse imaging: Significant improvement in live "
                        "birth rates (48.2% vs 39.5%).",
                "source_url": "https://example.com/ivf-1",
            },
            {
                "text": "AI embryo selection: Promising but lacks prospective "
                        "clinical validation.",
                "source_url": "https://example.com/ivf-2",
            },
        ]
        assert flat["recommendations"] == _SAMPLE_LLM_SYNTHESIS["recommendations"]

    def test_keeps_existing_top_level_digest_keys(self) -> None:
        """title / domain / generated_at / period / entries stay in the dict."""
        flat = _normalize_digest_product_context(self._context(), "medical-research")
        assert flat["title"] == "Weekly Digest \u2014 medical-research"
        assert flat["domain"] == "medical-research"
        assert flat["generated_at"] == "2026-08-10T00:00:00+00:00"
        assert flat["period"] == "weekly"
        assert flat["entries"] == _SAMPLE_ENTRIES

    def test_key_findings_conversion_partial_and_empty_items(self) -> None:
        """topic-only / detail-only kept, fully empty items dropped."""
        synthesis = {
            "executive_summary": "S.",
            "key_findings": [
                {"topic": "Full", "detail": "Both parts"},
                {"topic": "Topic only", "detail": ""},
                {"topic": "", "detail": "Detail only"},
                {"topic": "", "detail": ""},
            ],
            "recommendations": [],
        }
        flat = _normalize_digest_product_context(
            self._context(synthesis), "medical-research"
        )
        assert flat["key_findings"] == [
            {"text": "Full: Both parts"},
            {"text": "Topic only"},
            {"text": "Detail only"},
        ]

    def test_missing_synthesis_returns_empty_flat_values(self) -> None:
        """Absent synthesis yields ``""`` summary and empty lists (never None)."""
        flat = _normalize_digest_product_context(
            self._context({}), "medical-research"
        )
        assert flat["executive_summary"] == ""
        assert flat["key_findings"] == []
        assert flat["recommendations"] == []

    def test_references_carry_five_key_item_shape(self) -> None:
        """References derive from entries with exactly the report-path shape."""
        flat = _normalize_digest_product_context(self._context(), "medical-research")
        assert flat["references"] == [
            {
                "title": "Improved IVF outcomes with time-lapse imaging",
                "source_url": "https://example.com/ivf-1",
                "source_type": "api",
                "source_platform": "pubmed",
                "domain": "medical-research",
            },
            {
                "title": "AI-driven embryo selection: a systematic review",
                "source_url": "https://example.com/ivf-2",
                "source_type": "api",
                "source_platform": "pubmed",
                "domain": "medical-research",
            },
        ]
        for ref in flat["references"]:
            assert set(ref.keys()) == {
                "title",
                "source_url",
                "source_type",
                "source_platform",
                "domain",
            }

    def test_references_domain_defaults_to_digest_domain(self) -> None:
        """Entries without a ``domain`` key fall back to the digest domain."""
        entries = [
            {
                "title": "No domain entry",
                "source_url": "https://example.com/none",
                "source_type": "rss",
                "source_platform": "feed",
            }
        ]
        ctx = self._context()
        ctx["entries"] = entries
        flat = _normalize_digest_product_context(ctx, "medical-research")
        assert flat["references"][0]["domain"] == "medical-research"

    def test_product_specific_fields_flow_through_generically(self) -> None:
        """implications / risks / action_required / key_metrics flatten too."""
        synthesis = {
            "executive_summary": "S.",
            "key_findings": [],
            "recommendations": [],
            "implications": ["Implication one"],
            "risks": [
                {
                    "title": "Validation lag",
                    "likelihood": "medium",
                    "impact": "high",
                    "mitigation": "Run prospective trials",
                }
            ],
            "action_required": ["Fund prospective validation"],
            "key_metrics": [
                {"metric": "Live birth rate", "value": "48.2%", "source": "RCT"}
            ],
        }
        flat = _normalize_digest_product_context(
            self._context(synthesis), "medical-research"
        )
        assert flat["implications"] == ["Implication one"]
        assert flat["risks"] == synthesis["risks"]
        assert flat["action_required"] == ["Fund prospective validation"]
        assert flat["key_metrics"] == synthesis["key_metrics"]

    def test_product_specific_fields_default_to_empty_list(self) -> None:
        """Absent product fields are ``[]`` (todo 7 fields land later)."""
        flat = _normalize_digest_product_context(self._context(), "medical-research")
        assert flat["implications"] == []
        assert flat["risks"] == []
        assert flat["action_required"] == []
        assert flat["key_metrics"] == []


# ===================================================================
# Integration tests: generate_digest with product_template
# ===================================================================


class TestPremiumBriefingDigestPath:
    """``generate_digest(product_template=premium-briefing)`` renders non-empty."""

    def test_premium_briefing_renders_flat_keys_non_empty(self) -> None:
        """All mandatory §5 sections render with real content, not empty states."""
        result = _render_digest(product_template=_premium_briefing_template())

        # Title + masthead (leading newline from trim_blocks)
        assert result.lstrip().startswith("# ") or "\n# " in result
        assert "**Domain**: medical-research" in result
        # Executive summary (flat key)
        assert "## Executive Summary" in result
        assert "IVF technology advancements" in result
        # Key Takeaways — numbered, converted list[str]
        assert "## Key Takeaways" in result
        assert "1. Time-lapse imaging: Significant improvement" in result
        assert "2. AI embryo selection: Promising but lacks" in result
        # References — 5-key items derived from entries
        assert "## References" in result
        assert "https://example.com/ivf-1" in result
        assert "https://example.com/ivf-2" in result
        # Footer marker literal to premium-briefing.md.j2
        assert "AutoInfo Premium Briefing" in result
        # NOT the default digest.md.j2 layout
        assert "## Entries" not in result

    def test_enterprise_briefing_renders_flat_keys_non_empty(self) -> None:
        """The enterprise template reads the same flat contract on the digest path."""
        result = _render_digest(product_template=_enterprise_briefing_template())

        assert result.startswith("# ")
        assert "## Executive Summary" in result
        assert "IVF technology advancements" in result
        # Key Findings section (guarded by key_findings being non-empty)
        assert "## Key Findings" in result
        assert "- Time-lapse imaging: Significant improvement" in result
        # Recommendations section
        assert "## Recommendations" in result
        assert "- Consider time-lapse imaging as standard of care" in result
        # Key Metrics + Risk Matrix render their empty states (todo 7 fields)
        assert "## Key Metrics" in result
        assert "_No quantified metrics in this period._" in result
        assert "## Risk Matrix" in result
        assert "_No material risks identified in this period._" in result
        # References derived from entries
        assert "## References" in result
        assert "https://example.com/ivf-1" in result
        # Footer marker literal to enterprise-briefing.md.j2
        assert "AutoInfo Enterprise Briefing" in result
        assert "## Entries" not in result


# ===================================================================
# Regression guards: non-template paths untouched
# ===================================================================


class TestNonTemplatePathsUntouched:
    """Default digest (no product_template) renders digest.md.j2 unchanged."""

    def test_default_digest_renders_digest_template(self) -> None:
        """No product_template → standard digest.md.j2 layout (byte-identical)."""
        result = _render_digest()

        assert "Weekly Digest" in result
        assert "## Entries" in result
        assert "Improved IVF outcomes with time-lapse imaging" in result
        assert "AutoInfo Premium Briefing" not in result
        assert "## Key Takeaways" not in result

    def test_json_format_without_template_keeps_raw_shape(self) -> None:
        """format=json without product_template keeps the nested digest shape."""
        result = _render_digest(format="json")
        payload = json.loads(result)
        assert payload["digest_type"] == "digest"
        assert "llm_synthesis" in payload
        assert payload["entry_count"] == 2
        assert payload["llm_synthesis"]["key_findings"][0]["topic"] == (
            "Time-lapse imaging"
        )

    def test_agent_format_without_template_keeps_raw_shape(self) -> None:
        """format=agent without product_template keeps the JSON-LD digest shape."""
        result = _render_digest(format="agent")
        payload = json.loads(result)
        assert payload["@type"] == "KnowledgeDigest"
        # Raw digest synthesis flows into the JSON-LD trends — untouched
        # by the product-template normalization
        assert any(t.get("topic") == "Time-lapse imaging" for t in payload["trends"])
