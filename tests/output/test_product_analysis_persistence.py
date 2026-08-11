"""Tests for persisting per-product analysis fields to KB entry metadata.

(output-quality-mega, todo 24 — Phase C: make agent output queryable.)

When a product output (premium-briefing / enterprise-briefing) is generated
in ``format="agent"``, the per-product analysis fields — ``implications`` /
``risks`` / ``action_required`` (and ``key_metrics`` for enterprise) — are
persisted as JSON metadata on the related KB entries via the existing KB
metadata dict path (``entries.custom_fields`` SQLite column, surfaced by
``KBStore.get_entry`` / MCP ``get_kb_entry``).

Linkage:
- digest path: agent entries carry the real ``entry_id`` → link by entry_id;
- report path: report agent entries hardcode ``entry_id: ""`` → fall back to
  ``source_url`` matching.

Backward compatibility: default digest/report (no product fields) persist
nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.kb import KBStore
from autoinfo.models import KBEntry

# ===========================================================================
# Fixtures / helpers
# ===========================================================================

_PRODUCT_SYNTHESIS: dict[str, Any] = {
    "executive_summary": "This week's key developments focus on IVF technology.",
    "key_findings": [
        {"topic": "Time-lapse imaging", "detail": "Improved live birth rates."},
        {"topic": "AI embryo selection", "detail": "Lacks prospective validation."},
    ],
    "trends": ["Increasing AI use in embryo selection"],
    "recommendations": ["Consider time-lapse imaging as standard of care"],
    "implications": [
        "Clinics should evaluate time-lapse imaging adoption.",
        "Regulators should watch for unvalidated AI selection tools.",
    ],
    "risks": [
        {
            "title": "Validation lag",
            "likelihood": "high",
            "impact": "medium",
            "mitigation": "Run prospective trials before standardizing.",
        },
    ],
    "action_required": [
        "Run a pilot evaluation of time-lapse imaging across two clinics.",
    ],
    "key_metrics": [
        {"metric": "Live birth rate", "value": "48.2% vs 39.5%", "source": "time-lapse RCT"},
    ],
}

# Premium-briefing synthesis — the todo-7 prompt keys key_metrics to
# enterprise-briefing only, so the premium mock synthesis carries no
# key_metrics; the persistence layer persists whatever is populated.
_PREMIUM_SYNTHESIS: dict[str, Any] = {
    k: v for k, v in _PRODUCT_SYNTHESIS.items() if k != "key_metrics"
}

_PLAIN_DIGEST_SYNTHESIS: dict[str, Any] = {
    "executive_summary": "Key developments in medical research this week.",
    "key_findings": [
        {"topic": "Gene Editing", "detail": "CRISPR advances show promise."},
        {"topic": "Quantum Bio", "detail": "Quantum simulation for drug discovery."},
    ],
    "trends": ["Increasing quantum computing applications in biotech"],
    "recommendations": ["Monitor quantum-bio convergence"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_template(name: str) -> Any:
    """Return the ProductTemplate instance of a PRODUCT_TEMPLATES row."""
    from autoinfo.output import PRODUCT_TEMPLATES

    for row in PRODUCT_TEMPLATES:
        if row["name"] == name:
            return row["template"]
    raise AssertionError(f"{name} ProductTemplate row missing from PRODUCT_TEMPLATES")


def _entry(entry_id: str, source_url: str, title: str) -> KBEntry:
    return KBEntry(
        entry_id=entry_id,
        title=title,
        domain="medical-research",
        tier="01-Raw",
        source_url=source_url,
        source_type="api",
        source_platform="pubmed",
        collected_at=_now(),
        summary="Time-lapse improves live birth rates.",
        tags=["IVF", "time-lapse"],
        relevance_score=92.0,
    )


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    """A real KBStore on a temp dir with two indexed 01-Raw entries."""
    kb_store = KBStore(base_path=tmp_path / "knowledge")
    kb_store.index.index_entry(
        _entry(
            "medical-research-ivf-entry-1",
            "https://example.com/article1",
            "Time-lapse imaging improves IVF outcomes",
        )
    )
    kb_store.index.index_entry(
        _entry(
            "medical-research-ivf-entry-2",
            "https://example.com/article2",
            "AI embryo selection shows promise",
        )
    )
    return kb_store


def _product_analysis(store: KBStore, entry_id: str) -> dict[str, Any]:
    """Return the persisted ``product_analysis`` metadata dict for *entry_id*.

    Mirrors what MCP ``get_kb_entry`` surfaces: ``KBStore.get_entry`` returns
    the row with ``custom_fields`` as a JSON string.
    """
    entry = store.get_entry(entry_id)
    assert entry is not None, f"entry {entry_id} not found"
    custom_fields_raw = entry.get("custom_fields") or "{}"
    custom_fields = (
        json.loads(custom_fields_raw)
        if isinstance(custom_fields_raw, str)
        else dict(custom_fields_raw)
    )
    return custom_fields["product_analysis"]


# ===========================================================================
# Digest path — link via entry_id
# ===========================================================================


class TestDigestPersistsProductAnalysis:
    def test_premium_briefing_persists_fields_via_entry_id(
        self, store: KBStore
    ) -> None:
        """Digest premium-briefing agent output persists to linked entries."""
        from autoinfo.output import generate_digest

        with patch("autoinfo.output.KBStore", return_value=store):
            with patch(
                "autoinfo.output._call_llm_for_digest",
                return_value=_PREMIUM_SYNTHESIS,
            ):
                result = generate_digest(
                    domain="medical-research",
                    period="weekly",
                    format="agent",
                    product_template=_registry_template("premium-briefing"),
                )

        assert isinstance(result, str)
        for entry_id in ("medical-research-ivf-entry-1", "medical-research-ivf-entry-2"):
            pa = _product_analysis(store, entry_id)
            assert pa["implications"] == _PREMIUM_SYNTHESIS["implications"]
            assert pa["risks"] == _PREMIUM_SYNTHESIS["risks"]
            assert pa["action_required"] == _PREMIUM_SYNTHESIS["action_required"]
            # premium-briefing synthesis carries no key_metrics
            assert "key_metrics" not in pa

    def test_enterprise_briefing_persists_key_metrics(self, store: KBStore) -> None:
        """Enterprise-briefing agent output additionally persists key_metrics."""
        from autoinfo.output import generate_digest

        with patch("autoinfo.output.KBStore", return_value=store):
            with patch(
                "autoinfo.output._call_llm_for_digest",
                return_value=_PRODUCT_SYNTHESIS,
            ):
                result = generate_digest(
                    domain="medical-research",
                    period="weekly",
                    format="agent",
                    product_template=_registry_template("enterprise-briefing"),
                )

        assert isinstance(result, str)
        for entry_id in ("medical-research-ivf-entry-1", "medical-research-ivf-entry-2"):
            pa = _product_analysis(store, entry_id)
            assert pa["key_metrics"] == _PRODUCT_SYNTHESIS["key_metrics"]
            assert pa["implications"] == _PRODUCT_SYNTHESIS["implications"]


# ===========================================================================
# Report path — link via source_url fallback (entry_id hardcoded "")
# ===========================================================================


class TestReportPersistsProductAnalysis:
    def test_premium_briefing_persists_via_source_url_fallback(
        self, store: KBStore
    ) -> None:
        """Report agent entries hardcode ``entry_id: ""`` → source_url fallback."""
        from autoinfo.output import generate_report

        groupings: list[dict[str, Any]] = [
            {
                "theme": "Gene Editing",
                "description": "CRISPR advances",
                "entries": store.list_entries("medical-research", limit=10),
            }
        ]

        with patch("autoinfo.output.KBStore", return_value=store):
            with patch("autoinfo.output._group_by_theme", return_value=groupings):
                with patch(
                    "autoinfo.output._generate_executive_summary",
                    return_value=_PREMIUM_SYNTHESIS,
                ):
                    with patch(
                        "autoinfo.llm.LLMExtractor",
                        return_value=MagicMock(),
                    ):
                        result = generate_report(
                            domain="medical-research",
                            format="agent",
                            period="monthly",
                            product_template=_registry_template("premium-briefing"),
                        )

        assert isinstance(result, str)
        # The report-path agent entries carry entry_id "" — the persistence
        # must have found the KB entries by source_url.
        for entry_id in ("medical-research-ivf-entry-1", "medical-research-ivf-entry-2"):
            pa = _product_analysis(store, entry_id)
            assert pa["implications"] == _PREMIUM_SYNTHESIS["implications"]
            assert pa["risks"] == _PREMIUM_SYNTHESIS["risks"]
            assert pa["action_required"] == _PREMIUM_SYNTHESIS["action_required"]


# ===========================================================================
# Backward compatibility — no product fields, nothing persisted
# ===========================================================================


class TestBackwardCompatibleNoPersistence:
    def test_default_digest_persists_nothing(self, store: KBStore) -> None:
        """Default digest (no product template) leaves custom_fields untouched."""
        from autoinfo.output import generate_digest

        with patch("autoinfo.output.KBStore", return_value=store):
            with patch(
                "autoinfo.output._call_llm_for_digest",
                return_value=_PLAIN_DIGEST_SYNTHESIS,
            ):
                result = generate_digest(
                    domain="medical-research",
                    period="weekly",
                    format="agent",
                )

        assert isinstance(result, str)
        for entry_id in ("medical-research-ivf-entry-1", "medical-research-ivf-entry-2"):
            entry = store.get_entry(entry_id)
            assert entry is not None
            custom_fields_raw = entry.get("custom_fields") or "{}"
            custom_fields = (
                json.loads(custom_fields_raw)
                if isinstance(custom_fields_raw, str)
                else dict(custom_fields_raw)
            )
            assert "product_analysis" not in custom_fields

    def test_default_report_persists_nothing(self, store: KBStore) -> None:
        """Default report (no product template) leaves custom_fields untouched."""
        from autoinfo.output import generate_report

        groupings: list[dict[str, Any]] = [
            {
                "theme": "Gene Editing",
                "description": "CRISPR advances",
                "entries": store.list_entries("medical-research", limit=10),
            }
        ]

        with patch("autoinfo.output.KBStore", return_value=store):
            with patch("autoinfo.output._group_by_theme", return_value=groupings):
                with patch(
                    "autoinfo.output._generate_executive_summary",
                    return_value="Executive summary for the report.",
                ):
                    with patch(
                        "autoinfo.llm.LLMExtractor",
                        return_value=MagicMock(),
                    ):
                        result = generate_report(
                            domain="medical-research",
                            format="agent",
                            period="monthly",
                        )

        assert isinstance(result, str)
        for entry_id in ("medical-research-ivf-entry-1", "medical-research-ivf-entry-2"):
            entry = store.get_entry(entry_id)
            assert entry is not None
            custom_fields_raw = entry.get("custom_fields") or "{}"
            custom_fields = (
                json.loads(custom_fields_raw)
                if isinstance(custom_fields_raw, str)
                else dict(custom_fields_raw)
            )
            assert "product_analysis" not in custom_fields


# ===========================================================================
# KB metadata dict path — update_entry_metadata round trip
# ===========================================================================


class TestUpdateEntryMetadata:
    def test_update_entry_metadata_merges_into_custom_fields(
        self, store: KBStore
    ) -> None:
        """Metadata merges into the existing custom_fields JSON column."""
        entry_id = "medical-research-ivf-entry-1"
        store.update_entry_metadata(entry_id, {"product_analysis": {"implications": ["x"]}})
        updated = store.update_entry_metadata(
            entry_id,
            {"product_analysis": {"implications": ["x"], "action_required": ["y"]}},
        )
        assert updated is True

        entry = store.get_entry(entry_id)
        assert entry is not None
        custom_fields = json.loads(entry["custom_fields"] or "{}")
        assert custom_fields["product_analysis"] == {
            "implications": ["x"],
            "action_required": ["y"],
        }

    def test_update_entry_metadata_unknown_entry_returns_false(
        self, store: KBStore
    ) -> None:
        """Updating a missing entry is a no-op that returns False."""
        assert store.update_entry_metadata("no-such-entry", {"k": "v"}) is False
