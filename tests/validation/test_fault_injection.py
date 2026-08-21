"""Issue #352.3 — fault injection harness for the validation system.

The validation matrix never actively injects LLM failures to verify the
product-generation guards; #328 (litellm error leak) was only caught when
12-way concurrency coincidentally triggered it.  This test module drives
the ``AUTOINFO_FAULT_INJECT`` mechanism (implemented in
``src/autoinfo/output/fault_inject.py``) and asserts that the deterministic
fallbacks fire correctly — a faulted seam must degrade to
``_deterministic_synthesis_fallback`` output that passes ``run_assertions``,
never leaking an error / placeholder / litellm text.

Deterministic by construction: KBStore is patched, ``call_with_fallback``
is patched to return valid content (so the content-poisoning hooks have
real JSON to corrupt), and a temp cwd is used.

Tests
-----
- test_fault_fail_falls_back          — ``fail`` raises at the digest seam
  and ``generate_digest`` renders via the deterministic fallback.
- test_fault_malformed_json_falls_back — ``malformed_json`` poisons the
  returned content; JSON parsing fails; the fallback fills the sections.
- test_fault_truncate_falls_back      — ``truncate`` cuts the JSON mid
  object; parsing fails; the fallback fills the sections.
- test_fault_isolated_per_product     — ``run_matrix`` with a fault env:
  the faulted product degrades via fallback; no product is ``error``; the
  other product is unaffected.
- test_no_fault_normal_path           — env unset: seams are no-ops, the
  digest renders the normal LLM synthesis (not the fallback).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from autoinfo.output import generate_digest
from autoinfo.validation_matrix import run_assertions, run_matrix

# ---------------------------------------------------------------------------
# Fixtures / sample data
# ---------------------------------------------------------------------------

_SAMPLE_ENTRIES: list[dict[str, Any]] = [
    {
        "entry_id": "med-ivf-001",
        "title": "Improved IVF outcomes with time-lapse embryo imaging",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "source_type": "api",
        "source_platform": "pubmed",
        "collected_at": "2026-08-19T10:00:00Z",
        "summary": "Time-lapse imaging improves live birth rates (48.2% vs 39.5%).",
        "tags": '["IVF", "embryo imaging", "RCT"]',
        "relevance_score": 92.0,
    },
    {
        "entry_id": "med-ivf-002",
        "title": "AI-driven embryo selection: a systematic review",
        "domain": "medical-research",
        "tier": "01-Raw",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
        "source_type": "api",
        "source_platform": "pubmed",
        "collected_at": "2026-08-20T10:00:00Z",
        "summary": "AI models show promise but lack prospective validation.",
        "tags": '["AI", "IVF", "embryo selection"]',
        "relevance_score": 85.0,
    },
]

_SAMPLE_LLM_SYNTHESIS: dict[str, Any] = {
    "executive_summary": (
        "This week's key developments focus on IVF technology advancements "
        "including time-lapse imaging and AI-driven selection."
    ),
    "key_findings": [
        {
            "topic": "Time-lapse imaging",
            "detail": (
                "Significant improvement in live birth rates (48.2% vs 39.5%) "
                "in a large RCT."
            ),
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        },
    ],
    "trends": ["Increasing integration of AI/ML in reproductive medicine"],
    "recommendations": ["Consider time-lapse imaging as standard of care"],
}

_LLM_CONTENT = json.dumps(_SAMPLE_LLM_SYNTHESIS, ensure_ascii=False)

_ANSI_RE = r"\x1b\[[0-9;]*m"
_LITELLM_MARKERS = ("Give Feedback / Get Help", "BerriAI", "litellm._turn_on_debug")
_ERROR_TEXT = ("Traceback (most recent call last):", "ConnectionError", "TimeoutError")


@pytest.fixture
def temp_cwd() -> Any:
    old = Path.cwd()
    tmp = Path(tempfile.mkdtemp(prefix="autoinfo-fault-inject-"))
    os.chdir(tmp)
    try:
        yield tmp
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def _make_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


def _assert_body_clean(body: str, domain: str, product: str) -> None:
    results = run_assertions(body, domain=domain, product=product)
    failing = [r for r in results if not r.passed]
    assert failing == [], (
        f"run_assertions failures: "
        f"{[(r.name, r.details) for r in failing]}"
    )
    import re  # noqa: PLC0415

    assert "_No " not in body
    for marker in _LITELLM_MARKERS:
        assert marker not in body
    assert re.search(_ANSI_RE, body[:2000]) is None
    for text in _ERROR_TEXT:
        assert text not in body


def _run_digest_with_fault(fault_value: str) -> str:
    with patch.dict(os.environ, {"AUTOINFO_FAULT_INJECT": fault_value}, clear=False):
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output.call_with_fallback") as mock_cwf,
        ):
            mock_cwf.return_value = _make_llm_response(_LLM_CONTENT)
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _SAMPLE_ENTRIES
            mock_kb_cls.return_value = mock_store
            result = generate_digest(domain="medical-research", period="weekly")
    return cast(str, result)


# ---------------------------------------------------------------------------
# 1. fault kind = "fail" — the seam raises → deterministic fallback
# ---------------------------------------------------------------------------


class TestFaultFail:
    def test_fault_fail_falls_back(self, temp_cwd: Any) -> None:
        body = _run_digest_with_fault("fail")

        assert "Executive Summary" in body
        assert "knowledge base" in body
        assert "IVF" in body
        assert "This week's key developments" not in body
        _assert_body_clean(body, "medical-research", "digest")


# ---------------------------------------------------------------------------
# 2. fault kind = "malformed_json" — poisoned content → parse fails → fallback
# ---------------------------------------------------------------------------


class TestFaultMalformedJson:
    def test_fault_malformed_json_falls_back(self, temp_cwd: Any) -> None:
        body = _run_digest_with_fault("malformed_json")

        assert "Executive Summary" in body
        assert "knowledge base" in body
        assert "This week's key developments" not in body
        _assert_body_clean(body, "medical-research", "digest")


# ---------------------------------------------------------------------------
# 3. fault kind = "truncate" — content cut mid-JSON → fallback
# ---------------------------------------------------------------------------


class TestFaultTruncate:
    def test_fault_truncate_falls_back(self, temp_cwd: Any) -> None:
        body = _run_digest_with_fault("truncate")

        assert "Executive Summary" in body
        assert "knowledge base" in body
        assert "This week's key developments" not in body
        _assert_body_clean(body, "medical-research", "digest")


# ---------------------------------------------------------------------------
# 4. fault isolation per product — run_matrix with a scoped fault
# ---------------------------------------------------------------------------


class TestFaultIsolation:
    def test_fault_isolated_per_product(self, temp_cwd: Any) -> None:
        from autoinfo.output import fault_inject

        real_maybe_fault = fault_inject.maybe_fault
        raised_scopes: list[str] = []

        def spy_maybe_fault(scope: str) -> None:
            try:
                real_maybe_fault(scope)
            except Exception:
                raised_scopes.append(scope)
                raise

        report_synthesis = (
            "## Executive Summary\n\nReport synthesis ok.\n\n"
            "## Key Findings\n\n- Finding R1\n\n"
            "## Recommendations\n\n- Rec R1"
        )
        report_response = _make_llm_response(report_synthesis)

        with patch.dict(
            os.environ, {"AUTOINFO_FAULT_INJECT": "digest:fail"}, clear=False
        ):
            with (
                patch("autoinfo.output.KBStore") as mock_kb_cls,
                patch(
                    "autoinfo.validation_matrix._current_commit",
                    return_value="abc",
                ),
                patch(
                    "autoinfo.output.call_with_fallback",
                    return_value=report_response,
                ),
                patch("time.sleep", return_value=None),
                patch.object(
                    fault_inject, "maybe_fault", side_effect=spy_maybe_fault
                ),
            ):
                mock_store = MagicMock()
                mock_store.list_entries.return_value = _SAMPLE_ENTRIES
                mock_kb_cls.return_value = mock_store

                report = run_matrix(
                    ["medical-research"],
                    ["digest", "report"],
                    artifacts_dir=Path("A"),
                    batch_id="b1",
                )

        assert report.summary["error_products"] == 0, (
            f"summary={report.summary}"
        )
        assert report.summary["total_products"] == 2

        by_product: dict[str, list[dict[str, Any]]] = {}
        for p in report.products:
            by_product.setdefault(p["product"], []).append(p)
        for product, rows in by_product.items():
            for row in rows:
                assert row["status"] == "ok", f"{product}: {row}"

        assert raised_scopes == ["digest"]

        digest_path = (
            Path("A") / "b1" / "products" / "medical-research"
            / "digest-markdown-b1.md"
        )
        digest_body = digest_path.read_text(encoding="utf-8")
        assert "knowledge base" in digest_body
        assert "This week's key developments" not in digest_body
        _assert_body_clean(digest_body, "medical-research", "digest")

        report_path = (
            Path("A") / "b1" / "products" / "medical-research"
            / "report-markdown-b1.md"
        )
        report_body = report_path.read_text(encoding="utf-8")
        assert "Report synthesis ok" in report_body
        assert "knowledge base" not in report_body
        _assert_body_clean(report_body, "medical-research", "report")


# ---------------------------------------------------------------------------
# 5. no fault — the normal path is byte-for-byte unchanged
# ---------------------------------------------------------------------------


class TestNoFault:
    def test_no_fault_normal_path(self, temp_cwd: Any) -> None:
        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output.call_with_fallback") as mock_cwf,
        ):
            mock_cwf.return_value = _make_llm_response(_LLM_CONTENT)
            mock_store = MagicMock()
            mock_store.list_entries.return_value = _SAMPLE_ENTRIES
            mock_kb_cls.return_value = mock_store

            result = generate_digest(domain="medical-research", period="weekly")

        body = cast(str, result)
        assert "This week's key developments" in body
        assert "Time-lapse imaging" in body
        _assert_body_clean(body, "medical-research", "digest")
