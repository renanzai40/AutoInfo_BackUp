"""Tests for scripts/validation_delivery.py delivery quality gates (E7, #131).

Covers:
- ``check_authenticity`` — per-artifact field-presence pre-check (md N/A-pass,
  JSON entry validation, example.com placeholder rejection)
- ``run_delivery_gates`` — D1-D3 (reusing autoinfo.quality unmodified) combined
  with authenticity into a unified gates dict + PASS/FAIL quality
- ``_package`` — gates/quality in manifest entries, 06-REJECTED/ output for
  failed artifacts, rejected summary in the manifest
"""
from __future__ import annotations

import importlib.util
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

# Load the real scripts/validation_delivery.py (same pattern as the sibling
# E3 test_validation_coverage.py) so the tests exercise the script's own code.
_SPEC = importlib.util.spec_from_file_location(
    "validation_delivery", ROOT / "scripts" / "validation_delivery.py"
)
assert _SPEC is not None and _SPEC.loader is not None
vd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vd)

from autoinfo.quality import QualityResult  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _passing_result(name: str, details: dict[str, Any] | None = None) -> QualityResult:
    return QualityResult(gate_name=name, passed=True, score=1.0, details=details or {})


def _failing_result(name: str, error: str) -> QualityResult:
    return QualityResult(
        gate_name=name,
        passed=False,
        score=0.0,
        flagged=True,
        details={"action": "block", "error": error},
    )


def _all_pass_gates(product_output, context=None, delivery_gate_configs=None):
    """Fake quality.run_delivery_gates that always passes (isolation)."""
    return {
        "D1-ProductCompleteness": _passing_result("D1-ProductCompleteness"),
        "D2-FormatIntegrity": _passing_result("D2-FormatIntegrity"),
        "D3-Freshness": _passing_result("D3-Freshness"),
    }


def _zip_manifest(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


def _zip_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


@pytest.fixture
def digest_md(tmp_path: Path) -> Path:
    """A realistic digest-style markdown with all three D1 sections."""
    p = tmp_path / "digest-2026-08-06.md"
    p.write_text(
        "# Weekly AI Digest\n\n"
        "## Executive Summary\n\nAI adoption accelerates.\n\n"
        "### Key Findings\n\n- LLM costs dropped 40%.\n\n"
        "### Recommendations\n\n- Adopt agent workflows.\n\n"
        "## Entries\n\n### 1. Some article\n\nBody text.\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# check_authenticity
# ---------------------------------------------------------------------------


def test_check_authenticity_md_pass(tmp_path: Path):
    """A .md content file is text, not a structured entry -> N/A pass."""
    p = tmp_path / "digest.md"
    p.write_text("# Title\n\nplain content\n", encoding="utf-8")
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "pass"
    assert "N/A" in res["reason"]


def test_check_authenticity_md_with_frontmatter_pass(tmp_path: Path):
    """md with source frontmatter still N/A-passes (field presence only)."""
    p = tmp_path / "entry.md"
    p.write_text(
        "---\nsource_url: https://pubmed.ncbi.nlm.nih.gov/123\n"
        "source_type: pubmed\nsource_platform: pubmed\n---\n\nBody.\n",
        encoding="utf-8",
    )
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "pass"
    assert "frontmatter" in res["reason"]


def test_check_authenticity_html_pass(tmp_path: Path):
    """.html content files N/A-pass like markdown."""
    p = tmp_path / "digest.html"
    p.write_text("<html><body><h1>Digest</h1></body></html>", encoding="utf-8")
    assert vd.check_authenticity(p)["authenticity"] == "pass"


def test_check_authenticity_json_valid(tmp_path: Path):
    """JSON with fully-provenanced entries passes."""
    p = tmp_path / "agent.json"
    p.write_text(
        json.dumps({
            "entries": [{
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345",
                "source_type": "pubmed",
                "source_platform": "pubmed",
            }]
        }),
        encoding="utf-8",
    )
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "pass"
    assert "complete source fields" in res["reason"]


def test_check_authenticity_json_example_com(tmp_path: Path):
    """JSON with an example.com placeholder URL fails."""
    p = tmp_path / "agent.json"
    p.write_text(
        json.dumps({
            "entries": [{
                "source_url": "https://example.com/article",
                "source_type": "web",
                "source_platform": "web",
            }]
        }),
        encoding="utf-8",
    )
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "fail"
    assert "example.com" in res["reason"]


def test_check_authenticity_json_missing_fields(tmp_path: Path):
    """JSON entries missing source_type (or source_platform) fail."""
    p = tmp_path / "agent.json"
    p.write_text(
        json.dumps({
            "entries": [{
                "source_url": "https://arxiv.org/abs/2608.00001",
                "source_platform": "arxiv",
            }]
        }),
        encoding="utf-8",
    )
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "fail"
    assert "source_type" in res["reason"]
    assert "source_platform" not in res["reason"] or "source_platform" in res["reason"]

    # A second entry missing source_platform also fails
    p.write_text(
        json.dumps({
            "entries": [{
                "source_url": "https://arxiv.org/abs/2608.00001",
                "source_type": "arxiv",
            }]
        }),
        encoding="utf-8",
    )
    res2 = vd.check_authenticity(p)
    assert res2["authenticity"] == "fail"
    assert "source_platform" in res2["reason"]


def test_check_authenticity_json_missing_source_url(tmp_path: Path):
    """JSON entry without source_url at all fails."""
    p = tmp_path / "agent.json"
    p.write_text(
        json.dumps({"entries": [{"title": "no url", "source_type": "x", "source_platform": "x"}]}),
        encoding="utf-8",
    )
    assert vd.check_authenticity(p)["authenticity"] == "fail"


def test_check_authenticity_json_no_entries_pass(tmp_path: Path):
    """JSON with no structured entries has nothing to verify -> pass."""
    p = tmp_path / "scenarios.json"
    p.write_text(json.dumps({"results": [{"name": "a", "status": "passed"}]}), encoding="utf-8")
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "pass"


def test_check_authenticity_jsonl(tmp_path: Path):
    """JSONL entries are validated per line."""
    p = tmp_path / "items.jsonl"
    entry1 = json.dumps(
        {"source_url": "https://pubmed.ncbi.nlm.nih.gov/1",
         "source_type": "pubmed", "source_platform": "pubmed"}
    )
    entry2 = json.dumps(
        {"source_url": "https://example.com/fake", "source_type": "web", "source_platform": "web"}
    )
    p.write_text(entry1 + "\n" + entry2 + "\n", encoding="utf-8")
    res = vd.check_authenticity(p)
    assert res["authenticity"] == "fail"
    assert "example.com" in res["reason"]


def test_check_authenticity_binary_na_pass(tmp_path: Path):
    """Non-JSON binaries (mp3/pdf) are content, not structured entries."""
    p = tmp_path / "digest.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00fake-mp3-bytes")
    assert vd.check_authenticity(p)["authenticity"] == "pass"


# ---------------------------------------------------------------------------
# run_delivery_gates
# ---------------------------------------------------------------------------


def test_run_delivery_gates_combined(tmp_path: Path, monkeypatch):
    """D1-D3 (from quality.py) combine with authenticity into one gates dict."""
    digest = tmp_path / "digest.md"
    digest.write_text(
        "# T\n\n## Executive Summary\n\ns\n\n### Key Findings\n\nk\n\n### Recommendations\n\nr\n",
        encoding="utf-8",
    )
    def _mixed(product_output, context=None, delivery_gate_configs=None):
        return {
            "D1-ProductCompleteness": _passing_result("D1-ProductCompleteness"),
            "D2-FormatIntegrity": _passing_result("D2-FormatIntegrity"),
            "D3-Freshness": _failing_result("D3-Freshness", "1 / 2 entries are stale"),
        }

    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _mixed)
    res = vd.run_delivery_gates(digest, "PROCESSED")

    assert set(res["gates"]) == {"D1", "D2", "D3", "authenticity"}
    assert res["gates"]["D1"]["passed"] is True
    assert res["gates"]["D2"]["passed"] is True
    assert res["gates"]["D3"]["passed"] is False
    assert res["gates"]["authenticity"]["authenticity"] == "pass"
    assert res["quality"] == "FAIL"


def test_run_delivery_gates_all_pass_quality_pass(tmp_path: Path, monkeypatch):
    """PASS quality only when every gate passes."""
    digest = tmp_path / "digest.md"
    digest.write_text("# T\n\n## Executive Summary\n\ns\n", encoding="utf-8")
    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _all_pass_gates)
    res = vd.run_delivery_gates(digest, "PROCESSED")
    assert res["quality"] == "PASS"
    assert res["gates"]["authenticity"]["authenticity"] == "pass"


def test_run_delivery_gates_authenticity_fail_flips_quality(tmp_path: Path, monkeypatch):
    """A failing authenticity pre-check fails quality even when D gates pass."""
    p = tmp_path / "agent.json"
    entry = {
        "entries": [{
            "source_url": "https://example.com/x",
            "source_type": "web",
            "source_platform": "web",
        }]
    }
    p.write_text(json.dumps(entry), encoding="utf-8")
    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _all_pass_gates)
    res = vd.run_delivery_gates(p, "PROCESSED")
    assert res["quality"] == "FAIL"
    assert res["gates"]["authenticity"]["authenticity"] == "fail"


def test_run_delivery_gates_raw_bucket_skips_d_gates(tmp_path: Path, monkeypatch):
    """RAW-bucket files run with product_type=RAW so D gates trivially pass."""
    captured: dict[str, Any] = {}

    def _capture(product_output, context=None, delivery_gate_configs=None):
        captured["product_type"] = product_output.get("product_type")
        return {
            "D1-ProductCompleteness": _passing_result("D1-ProductCompleteness", {"skipped": True}),
            "D2-FormatIntegrity": _passing_result("D2-FormatIntegrity", {"skipped": True}),
            "D3-Freshness": _passing_result("D3-Freshness", {"skipped": True}),
        }

    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _capture)
    raw = tmp_path / "cached.json"
    item = json.dumps(
        {"items": [{"source_url": "https://a.example.org/1",
                    "source_type": "rss", "source_platform": "rss"}]}
    )
    raw.write_text(item, encoding="utf-8")
    res = vd.run_delivery_gates(raw, "RAW")
    assert captured["product_type"] == "RAW"
    assert res["quality"] == "PASS"


def test_run_delivery_gates_real_quality_integration(tmp_path: Path):
    """The wrapper works against the real autoinfo.quality D1-D3 gates.

    A digest markdown with all three sections passes D1 (headings), D2
    (markdown trivially valid) and D3 (no dated entries to check).
    """
    digest = tmp_path / "digest.md"
    digest.write_text(
        "# Weekly Digest\n\n"
        "## Executive Summary\n\nSummary text.\n\n"
        "### Key Findings\n\n- Finding one.\n\n"
        "### Recommendations\n\n- Recommendation one.\n\n",
        encoding="utf-8",
    )
    res = vd.run_delivery_gates(digest, "PROCESSED")
    assert res["gates"]["D1"]["passed"] is True
    assert res["gates"]["D2"]["passed"] is True
    assert res["gates"]["D3"]["passed"] is True
    assert res["quality"] == "PASS"


def test_run_delivery_gates_json_freshness_real(tmp_path: Path):
    """JSON entries with recent collected_at pass the real D3 freshness gate."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    p = tmp_path / "digest.json"
    p.write_text(
        json.dumps({
            "key_findings": ["k1"],
            "summary": "s",
            "recommendations": ["r1"],
            "entries": [{
                "title": "fresh entry",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/1",
                "source_type": "pubmed",
                "source_platform": "pubmed",
                "collected_at": fresh,
            }],
        }),
        encoding="utf-8",
    )
    res = vd.run_delivery_gates(p, "PROCESSED")
    assert res["gates"]["D1"]["passed"] is True
    assert res["gates"]["D3"]["passed"] is True
    assert res["gates"]["authenticity"]["authenticity"] == "pass"
    assert res["quality"] == "PASS"


def test_bucket_classification(tmp_path: Path):
    """_bucket maps delivery path patterns to RAW / KB / PROCESSED."""
    assert vd._bucket(Path("knowledge/medical-research/01-Raw/x/2026-08-06-a.md")) == "RAW"
    assert vd._bucket(Path("collections/medical-research/cached.json")) == "RAW"
    assert vd._bucket(Path("knowledge/medical-research/02-Draft/d.md")) == "KB"
    assert vd._bucket(Path("knowledge/medical-research/03-Wiki/w.md")) == "KB"
    assert vd._bucket(Path("outputs/digest.md")) == "PROCESSED"
    # #192: non-deliverable artifacts (rejected KB promotion drafts under
    # knowledge/_failed/, internal coverage-matrix reports) are excluded by
    # the shared predicate, so they never classify into RAW/KB/PROCESSED.
    assert vd.is_excluded_artifact("knowledge/_failed/medical-research/rejected.md")
    assert vd.is_excluded_artifact("outputs/coverage-matrix/matrix-report.md")
    assert not vd.is_excluded_artifact("outputs/digest.md")
    assert not vd.is_excluded_artifact(
        "knowledge/medical-research/01-Raw/x/2026-08-06-a.md"
    )


def test_package_skips_excluded_artifacts(tmp_path: Path, monkeypatch):
    """Excluded artifacts never enter the delivery package (#192).

    knowledge/_failed/<domain>/ drafts and outputs/coverage-matrix/ reports
    must be absent from the zip and the manifest, while a legit output file
    next to them is still delivered.
    """
    legit = tmp_path / "outputs" / "digest.md"
    legit.parent.mkdir(parents=True)
    legit.write_text(
        "# T\n\n## Executive Summary\n\ns\n\n### Key Findings\n\nk\n\n### Recommendations\n\nr\n",
        encoding="utf-8",
    )
    rejected_draft = tmp_path / "knowledge" / "_failed" / "medical-research" / "rejected.md"
    rejected_draft.parent.mkdir(parents=True)
    rejected_draft.write_text("# Rejected draft\n", encoding="utf-8")
    matrix = tmp_path / "outputs" / "coverage-matrix" / "matrix-report.md"
    matrix.parent.mkdir(parents=True)
    matrix.write_text("# Coverage Matrix\n", encoding="utf-8")

    zip_path = _package_with(
        tmp_path, [legit, rejected_draft, matrix], monkeypatch, _all_pass_gates
    )
    names = _zip_names(zip_path)
    assert any(n.endswith("/digest.md") for n in names), f"legit file missing: {names}"
    assert not any("_failed" in n for n in names), f"_failed leaked: {names}"
    assert not any(
        "coverage-matrix" in n for n in names
    ), f"coverage-matrix leaked: {names}"
    manifest = _zip_manifest(zip_path)
    for entry in manifest["files"]:
        assert "_failed" not in entry["file"], f"_failed in manifest: {entry}"
        assert "coverage-matrix" not in entry["file"], f"coverage-matrix in manifest: {entry}"


# ---------------------------------------------------------------------------
# _package — manifest gates/quality + 06-REJECTED
# ---------------------------------------------------------------------------


def _package_with(tmp_path: Path, artifacts: list[Path], monkeypatch, quality_fake=None) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    if quality_fake is not None:
        monkeypatch.setattr(vd, "_quality_run_delivery_gates", quality_fake)
    return vd._package([{"path": str(p)} for p in artifacts], [], out)


def test_package_includes_gates_in_manifest(tmp_path: Path, monkeypatch):
    """Every manifest file entry carries a gates dict + PASS/FAIL quality."""
    digest = tmp_path / "digest.md"
    digest.write_text(
        "# T\n\n## Executive Summary\n\ns\n\n### Key Findings\n\nk\n\n### Recommendations\n\nr\n",
        encoding="utf-8",
    )
    zip_path = _package_with(tmp_path, [digest], monkeypatch, _all_pass_gates)

    manifest = _zip_manifest(zip_path)
    assert manifest["files"], "expected at least one delivered file"
    entry = next(e for e in manifest["files"] if e["kind"] != "MATRIX")
    assert entry["file"].startswith("02-PROCESSED/") and entry["file"].endswith("/digest.md")
    assert entry["quality"] == "PASS"
    assert set(entry["gates"]) == {"D1", "D2", "D3", "authenticity"}
    assert entry["gates"]["D1"]["passed"] is True
    assert entry["gates"]["D2"]["passed"] is True
    assert entry["gates"]["D3"]["passed"] is True
    assert entry["gates"]["authenticity"]["authenticity"] == "pass"
    assert entry["gates"]["D1"]["gate"] == "D1-ProductCompleteness"


def test_package_rejects_failed(tmp_path: Path, monkeypatch):
    """FAIL-quality artifacts are moved to 06-REJECTED/ and listed as rejected."""
    digest = tmp_path / "digest.md"
    digest.write_text(
        "# T\n\n## Executive Summary\n\ns\n\n### Key Findings\n\nk\n\n### Recommendations\n\nr\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.json"
    bad_entry = {
        "entries": [{
            "source_url": "https://example.com/x",
            "source_type": "web",
            "source_platform": "web",
        }]
    }
    bad.write_text(json.dumps(bad_entry), encoding="utf-8")
    zip_path = _package_with(tmp_path, [digest, bad], monkeypatch, _all_pass_gates)

    names = _zip_names(zip_path)
    assert any(n.startswith("02-PROCESSED/") and n.endswith("/digest.md") for n in names)
    assert any(n.startswith("06-REJECTED/") and n.endswith("/bad.json") for n in names)
    assert not any(n.startswith("02-PROCESSED/") and n.endswith("/bad.json") for n in names)

    manifest = _zip_manifest(zip_path)
    assert len([e for e in manifest["files"] if e["kind"] != "MATRIX"]) == 1
    assert len(manifest["rejected"]) == 1
    rejected = manifest["rejected"][0]
    assert rejected["file"].startswith("06-REJECTED/") and rejected["file"].endswith("/bad.json")
    assert "example.com" in rejected["reason"]
    assert rejected["reason"].startswith("authenticity:")


def test_package_rejects_d_gate_failure(tmp_path: Path, monkeypatch):
    """A D-gate failure (not just authenticity) also lands in 06-REJECTED."""
    digest = tmp_path / "digest.md"
    digest.write_text("# T\n\nplain, no sections\n", encoding="utf-8")

    def _d1_fails(product_output, context=None, delivery_gate_configs=None):
        return {
            "D1-ProductCompleteness": _failing_result(
                "D1-ProductCompleteness", "missing sections: key_findings, summary, recommendations"
            ),
            "D2-FormatIntegrity": _passing_result("D2-FormatIntegrity"),
            "D3-Freshness": _passing_result("D3-Freshness"),
        }

    zip_path = _package_with(tmp_path, [digest], monkeypatch, _d1_fails)
    manifest = _zip_manifest(zip_path)
    assert [e for e in manifest["files"] if e["kind"] != "MATRIX"] == []
    assert len(manifest["rejected"]) == 1
    assert manifest["rejected"][0]["reason"].startswith("D1:")
    assert "missing sections" in manifest["rejected"][0]["reason"]


def test_package_kb_raw_artifacts_pass_gates(tmp_path: Path, monkeypatch):
    """KB/RAW-bucket artifacts pass the D gates (skipped) and stay delivered."""
    kb_entry = tmp_path / "knowledge" / "medical-research" / "03-Wiki" / "2026-08-06-x.md"
    kb_entry.parent.mkdir(parents=True)
    kb_entry.write_text(
        "---\ntitle: X\nsource_url: https://pubmed.ncbi.nlm.nih.gov/9\n"
        "source_type: pubmed\nsource_platform: pubmed\n---\n\nBody.\n",
        encoding="utf-8",
    )
    zip_path = _package_with(tmp_path, [kb_entry], monkeypatch, _all_pass_gates)
    manifest = _zip_manifest(zip_path)
    assert len([e for e in manifest["files"] if e["kind"] != "MATRIX"]) == 1
    entry = next(e for e in manifest["files"] if e["kind"] != "MATRIX")
    assert entry["kind"] == "KB"
    assert entry["quality"] == "PASS"
    assert entry["gates"]["D1"]["passed"] is True
    assert manifest["rejected"] == []


def test_package_skips_missing_files(tmp_path: Path, monkeypatch):
    """Non-existent artifact paths are skipped without failing delivery."""
    ghost = tmp_path / "ghost.md"
    zip_path = _package_with(tmp_path, [ghost], monkeypatch, _all_pass_gates)
    manifest = _zip_manifest(zip_path)
    assert [e for e in manifest["files"] if e["kind"] != "MATRIX"] == []
    assert manifest["rejected"] == []


# ---------------------------------------------------------------------------
# _package — E9 (#141) end-user journey UX metrics
# ---------------------------------------------------------------------------

_UX_SCENARIO = "enduser-journey"


def _journey_result(*, passed: int, total: int, status: str = "passed",
                    steps: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """A run_scenario-shaped enduser-journey result (name-keyed, the shape
    _run_all_scenarios hands to _package; run_scenario itself uses the
    ``scenario`` key — covered by test_ux_metrics_matches_scenario_key)."""
    if steps is None:
        steps = [("generate_digest", "passed" if i < passed else "failed") for i in range(total)]
    return {
        "name": _UX_SCENARIO,
        "status": status,
        "summary": {"passed": passed, "failed": total - passed,
                    "unconfigured": 0, "recovered": 0, "total": total},
        "steps": [{"name": n, "status": s, "detail": {}} for n, s in steps],
    }


def _package_with_results(tmp_path: Path, results: list[dict[str, Any]], monkeypatch,
                          artifacts: list[Path] | None = None) -> Path:
    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _all_pass_gates)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return vd._package([{"path": str(p)} for p in (artifacts or [])], results, out)


def _zip_report(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read("validation-report.md").decode("utf-8")


def test_package_ux_metrics_ok_when_journey_passes(tmp_path: Path, monkeypatch):
    """A fully-passing enduser-journey yields UX_OK=True and
    completion_rate >= 0.8 in both validation-report.md and manifest.json."""
    results = [
        {"name": "some-other-scenario", "status": "passed", "summary": {"passed": 3, "total": 3}},
        _journey_result(
            passed=2, total=2,
            steps=[("generate_digest markdown for the end-user inbox", "passed"),
                   ("search_knowledge_base returns entries for the journey query", "passed")],
        ),
    ]
    zip_path = _package_with_results(tmp_path, results, monkeypatch)

    report = _zip_report(zip_path)
    assert "## UX Metrics (issue #141)" in report
    assert "UX_OK: True" in report
    assert "completion_rate=1.0" in report
    assert "threshold 0.8" in report
    assert "generate_digest markdown for the end-user inbox — passed" in report

    manifest = _zip_manifest(zip_path)
    assert manifest["ux"]["ux_ok"] is True
    assert manifest["ux"]["completion_rate"] >= 0.8
    assert manifest["ux"]["threshold"] == 0.8
    assert manifest["ux"]["scenario_status"] == "passed"
    assert {s["status"] for s in manifest["ux"]["steps"]} == {"passed"}


def test_package_ux_metrics_fail_when_journey_below_threshold(tmp_path: Path, monkeypatch):
    """A journey with 1/2 steps passing (completion_rate 0.5 < 0.8) yields
    UX_OK=False and the metric is still reported (advisory, never blocking)."""
    results = [
        _journey_result(
            passed=1, total=2, status="failed",
            steps=[("generate_digest markdown for the end-user inbox", "passed"),
                   ("search_knowledge_base returns entries for the journey query", "failed")],
        ),
    ]
    zip_path = _package_with_results(tmp_path, results, monkeypatch)

    report = _zip_report(zip_path)
    assert "UX_OK: False" in report
    assert "completion_rate=0.5" in report
    assert "search_knowledge_base returns entries for the journey query — failed" in report

    manifest = _zip_manifest(zip_path)
    assert manifest["ux"]["ux_ok"] is False
    assert manifest["ux"]["completion_rate"] < 0.8
    assert manifest["ux"]["scenario_status"] == "failed"
    # the package still built — advisory metrics never block delivery
    assert [e for e in manifest["files"] if e["kind"] != "MATRIX"] == []


def test_package_ux_metrics_absent_without_journey(tmp_path: Path, monkeypatch):
    """When the enduser-journey scenario did not run (e.g. skipped smoke
    run), the report and manifest omit the UX block entirely."""
    results = [{"name": "error-boundary", "status": "passed", "summary": {"passed": 3, "total": 3}}]
    zip_path = _package_with_results(tmp_path, results, monkeypatch)

    report = _zip_report(zip_path)
    assert "UX Metrics" not in report
    manifest = _zip_manifest(zip_path)
    assert manifest.get("ux") is None


def test_ux_metrics_matches_scenario_key_and_step_fallback():
    """_ux_metrics also matches the run_scenario-shaped result (``scenario``
    key, as persisted in validation-runs/<date>/scenarios.json) and falls
    back to per-step statuses when summary counts are missing."""
    raw = {
        "scenario": _UX_SCENARIO,
        "status": "passed",
        "summary": {},
        "steps": [
            {"name": "generate_digest markdown for the end-user inbox", "status": "passed"},
            {"name": "search_knowledge_base returns entries for the journey query",
             "status": "passed"},
            {"name": "some-other-step", "status": "passed"},
            {"name": "some-other-step-2", "status": "passed"},
            {"name": "some-other-step-3", "status": "failed"},
        ],
    }
    metrics = vd._ux_metrics([raw])
    assert metrics is not None
    assert metrics["ux_ok"] is True  # 4/5 == 0.8 threshold
    assert metrics["completion_rate"] == pytest.approx(0.8)
    assert metrics["passed"] == 4 and metrics["total"] == 5

    below = {
        "scenario": _UX_SCENARIO,
        "status": "failed",
        "summary": {},
        "steps": [
            {"name": "generate_digest markdown for the end-user inbox", "status": "passed"},
            {"name": "search_knowledge_base returns entries for the journey query",
             "status": "passed"},
            {"name": "some-other-step", "status": "passed"},
            {"name": "some-other-step-3", "status": "failed"},
        ],
    }
    assert vd._ux_metrics([below])["ux_ok"] is False  # 3/4 = 0.75 < 0.8

    assert vd._ux_metrics([{"name": "other", "status": "passed"}]) is None
    assert vd._ux_metrics([]) is None


# ---------------------------------------------------------------------------
# error-boundary.yaml — error envelope asserts the actionable boolean (#141)
# ---------------------------------------------------------------------------


def test_error_boundary_asserts_actionable_on_error_envelope():
    """error-boundary.yaml expect blocks reference ``error.actionable``
    (error_actionable) for every error-envelope step, verifying the
    canonical {code, message, actionable} shape from errors.py."""
    yaml_path = ROOT / "src" / "autoinfo" / "mcp" / "scenarios" / "error-boundary.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["name"] == "error-boundary"
    error_steps = [s for s in data["steps"] if s["expect"].get("success") is False]
    assert error_steps, "expected error-envelope steps"
    for step in error_steps:
        # Every error step must pin the actionable boolean (true OR false —
        # UnknownTool is genuinely not actionable, #141).
        assert step["expect"].get("error_actionable") is not None, (
            f"step '{step['name']}' must assert error.actionable"
        )
        assert step["expect"]["error_code"], f"step '{step['name']}' keeps error_code"


def test_enduser_journey_scenario_loads():
    """enduser-journey.yaml passes load_scenarios() validation and exercises
    the end-user product surface: generate_digest + search_knowledge_base."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    try:
        from autoinfo.mcp.validation import load_scenarios
    finally:
        sys.path.remove(str(ROOT / "src"))
    scenarios = {s["name"]: s for s in load_scenarios()}
    journey = scenarios.get("enduser-journey")
    assert journey is not None, "enduser-journey.yaml must load"
    assert journey["category"] == "enduser"
    assert journey["requires_env"] == ["AUTOINFO_LLM_API_KEY"]
    assert journey["requires_domain"] == ["medical-research"]
    tools = [s["tool"] for s in journey["steps"]]
    assert tools == ["generate_digest", "search_knowledge_base"]
    assert journey["steps"][0]["arguments"]["format"] == "markdown"
    assert "query" in journey["steps"][1]["arguments"]


# ---------------------------------------------------------------------------
# _package — E8 (#131) 04-MATRIX coverage section
# ---------------------------------------------------------------------------


def _required_cells() -> set[tuple[str, str, str]]:
    """The spec's required-capability domain x product x format cells
    (Oracle R8) — required cells annotated ``capability: not-implemented``
    are capability boundaries (rendered 不适用not-applicable, never 空gap),
    so they are excluded from the gap-domain set."""
    spec = yaml.safe_load(
        (ROOT / "docs" / "dev" / "specs" / "end-user-matrix.yaml").read_text(encoding="utf-8")
    )
    return {
        (c["domain"], c["product"], c["format"])
        for c in spec["required_cells"]
        if c.get("capability", "implemented") == "implemented"
    }


def _zip_matrix_meta(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("04-MATRIX/coverage-gaps.json").decode("utf-8"))


def test_package_matrix_section_with_gaps(tmp_path: Path, monkeypatch):
    """04-MATRIX/ ships in the zip: matrix-report.md rendered from the
    package's own artifact manifest, coverage-gaps.json listing every
    remaining 空gap required cell (one required cell produced as evidence)."""
    artifact = tmp_path / "outputs" / "medical-research" / "digest-json-20260806-120000.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps({"summary": "s", "key_findings": ["k1"], "recommendations": ["r1"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _all_pass_gates)
    monkeypatch.setattr(vd, "_matrix_llm_available", lambda: True)

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    zip_path = vd._package([{"path": str(artifact)}], [], out)

    names = _zip_names(zip_path)
    assert "04-MATRIX/matrix-report.md" in names
    assert "04-MATRIX/coverage-gaps.json" in names

    with zipfile.ZipFile(zip_path) as zf:
        report = zf.read("04-MATRIX/matrix-report.md").decode("utf-8")
        gap_meta = _zip_matrix_meta(zip_path)
        manifest = _zip_manifest(zip_path)
        vreport = zf.read("validation-report.md").decode("utf-8")

    assert report.startswith("# End-User Coverage Matrix (E8")
    assert "## COVERAGE_GAP" in report
    assert "| digest | 有produced |" in report  # medical-research column shows evidence

    expected_gaps = _required_cells() - {("medical-research", "digest", "json")}
    gap_cells = {(g["domain"], g["product"], g["format"]) for g in gap_meta["gaps"]}
    assert gap_cells == expected_gaps
    assert all(g["cell_state"] == "空gap" for g in gap_meta["gaps"])
    assert gap_meta["llm_available"] is True

    matrix_files = [e for e in manifest["files"] if e["kind"] == "MATRIX"]
    assert {e["file"] for e in matrix_files} == {
        "04-MATRIX/matrix-report.md",
        "04-MATRIX/coverage-gaps.json",
    }
    assert all(e["quality"] == "PASS" for e in matrix_files)
    assert "## Coverage Matrix (E8)" in vreport
    assert "### COVERAGE_GAP (required cells with no evidence)" in vreport
    assert "`medical-research × report × json`" in vreport


def test_package_matrix_llm_absent_marks_gated_unconfigured(tmp_path: Path, monkeypatch):
    """Oracle R8 in the delivery package: with no LLM key, required cells of
    LLM-gated products (tutorial/presentation) are 未配置unconfigured in
    coverage-gaps.json and the report — never 空gap."""
    monkeypatch.setattr(vd, "_quality_run_delivery_gates", _all_pass_gates)
    monkeypatch.setattr(vd, "_matrix_llm_available", lambda: False)

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    zip_path = vd._package([], [], out)

    with zipfile.ZipFile(zip_path) as zf:
        gap_meta = _zip_matrix_meta(zip_path)
        report = zf.read("04-MATRIX/matrix-report.md").decode("utf-8")

    assert gap_meta["llm_available"] is False
    unconf = {(u["domain"], u["product"], u["format"]) for u in gap_meta["unconfigured"]}
    assert ("medical-research", "tutorial", "markdown") in unconf
    assert ("tech-ai-developer", "presentation", "markdown") in unconf
    assert all(u["cell_state"] == "未配置unconfigured" for u in gap_meta["unconfigured"])

    assert all(g["product"] not in ("tutorial", "presentation") for g in gap_meta["gaps"])
    assert {(g["domain"], g["product"], g["format"]) for g in gap_meta["gaps"]} == (
        _required_cells() - unconf
    )

    assert "未配置unconfigured" in report
    assert "| tutorial | 空gap |" not in report
    assert "| tutorial | 未配置unconfigured |" in report


# ---------------------------------------------------------------------------
# _tier_subpath — absolute-prefix stripping (issue #143)
# ---------------------------------------------------------------------------


def test_tier_subpath_absolute_repo_path_relativized():
    """Absolute paths under the repo root map to the tier subpath only."""
    cwd = Path.cwd()
    src = cwd / "knowledge" / "medical-research" / "01-Raw" / "general" / "x.md"
    assert vd._tier_subpath(src) == Path("01-Raw/general/x.md")


def test_tier_subpath_absolute_draft_path_relativized():
    """Absolute 02-Draft path under the repo root → tier subpath, no prefix."""
    cwd = Path.cwd()
    src = cwd / "knowledge" / "medical-research" / "02-Draft" / "d.md"
    assert vd._tier_subpath(src) == Path("02-Draft/d.md")


def test_tier_subpath_relative_paths_unchanged():
    """Repo-relative inputs keep the historical slice behaviour."""
    assert vd._tier_subpath(Path("knowledge/medical-research/01-Raw/w.md")) == Path("01-Raw/w.md")
    assert vd._tier_subpath(Path("collections/medical-research/z.json")) == Path("z.json")
    assert vd._tier_subpath(Path("outputs/medical-research/digest.md")) == Path("digest.md")


def test_tier_subpath_shallow_bare_name():
    """Shallow paths fall back to the bare file name."""
    assert vd._tier_subpath(Path("digest.md")) == Path("digest.md")


def test_tier_subpath_outside_repo_keeps_slice():
    """Paths outside the repo root keep the historical slice behaviour."""
    src = Path("/tmp/outside/knowledge/medical-research/02-Draft/d.md")
    assert vd._tier_subpath(src) == Path("outside/knowledge/medical-research/02-Draft/d.md")


# ---------------------------------------------------------------------------
# KB scenario artifact globs — 03-Wiki coverage (issue #144)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fname",
    ["kb-promote.yaml", "kb-draft.yaml"],
)
def test_kb_scenarios_collect_03_wiki(fname: str):
    """KB scenarios glob all three tiers so 03-KB is never empty (#144)."""
    scenario = ROOT / "src" / "autoinfo" / "mcp" / "scenarios" / fname
    data = yaml.safe_load(scenario.read_text(encoding="utf-8"))
    globs = data["collect_artifacts"]
    assert any("03-Wiki" in g for g in globs)
    assert any("01-Raw" in g for g in globs)
    assert any("02-Draft" in g for g in globs)
