"""End-user coverage matrix tests (E8, issue #131).

Exercises the real ``scripts/coverage_matrix.py`` (same importlib pattern as
the sibling E3/E7 tests) so the tests cover the script's own logic:

1. ``classify_cell`` — the four-way cell classification, including the Oracle
   R8 critical rule: a required empty cell of an LLM-gated product is
   ``未配置unconfigured`` when the LLM is unavailable — NEVER ``空gap``.
2. ``scan_evidence`` — outputs/** persisted artifacts + validation_delivery
   ``manifest.json`` (bare and inside zips), with ``quality == FAIL`` entries
   excluded.
3. ``render_report`` — valid markdown with legend + COVERAGE_GAP summary.
4. End-to-end CLI run (exit 0 with gaps, exit 2 on missing spec/evidence).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "dev" / "specs" / "end-user-matrix.yaml"
SCRIPT = ROOT / "scripts" / "coverage_matrix.py"

_SPEC_IMPORT = importlib.util.spec_from_file_location("coverage_matrix", SCRIPT)
assert _SPEC_IMPORT is not None and _SPEC_IMPORT.loader is not None
cm = importlib.util.module_from_spec(_SPEC_IMPORT)
_SPEC_IMPORT.loader.exec_module(cm)


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


EMPTY_PRODUCED: frozenset = frozenset()


# ---------------------------------------------------------------------------
# classify_cell — four-way classification + the Oracle R8 critical rule
# ---------------------------------------------------------------------------


def test_required_produced_is_produced(spec):
    cell = {"domain": "medical-research", "product": "digest", "format": "json"}
    produced = {("medical-research", "digest", "json")}
    assert cm.classify_cell(cell, produced, llm_available=True, spec=spec) == cm.PRODUCED


def test_required_not_produced_llm_available_is_gap(spec):
    cell = {"domain": "medical-research", "product": "digest", "format": "json"}
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=True, spec=spec) == cm.GAP


def test_required_not_produced_no_llm_is_gap_for_non_gated_product(spec):
    """digest is NOT llm_gated — without evidence it is a real 空gap even
    with no LLM key (absence is a product gap, not a config obligation)."""
    cell = {"domain": "medical-research", "product": "digest", "format": "json"}
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=False, spec=spec) == cm.GAP


def test_required_llm_gated_not_produced_no_llm_is_unconfigured(spec):
    """Oracle R8 CRITICAL: required empty cell of an LLM-gated product with
    the LLM unavailable is 未配置unconfigured — NEVER 空gap."""
    cell = {"domain": "medical-research", "product": "tutorial", "format": "markdown"}
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=False, spec=spec) == cm.UNCONFIGURED
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=False, spec=spec) != cm.GAP


def test_required_llm_gated_not_produced_llm_available_is_gap(spec):
    """Same cell flips to 空gap once the LLM IS configured."""
    cell = {"domain": "tech-ai-developer", "product": "presentation", "format": "markdown"}
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=True, spec=spec) == cm.GAP
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=False, spec=spec) == cm.UNCONFIGURED


def test_non_required_produced_is_produced(spec):
    cell = {"domain": "gaming", "product": "magazine-digest", "format": "epub"}
    produced = {("gaming", "magazine-digest", "epub")}
    assert cm.classify_cell(cell, produced, llm_available=False, spec=spec) == cm.PRODUCED


def test_non_required_no_evidence_is_not_applicable(spec):
    cell = {"domain": "retail", "product": "column", "format": "audio"}
    result = cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=True, spec=spec)
    assert result == cm.NOT_APPLICABLE


def test_classify_cell_accepts_tuple_form(spec):
    # not-implemented cell → NOT_APPLICABLE (capability boundary, not a gap)
    assert cm.classify_cell(
        ("medical-research", "tutorial", "html"), EMPTY_PRODUCED, llm_available=True, spec=spec
    ) == cm.NOT_APPLICABLE


def test_capability_boundary_required_cell_is_not_applicable(spec):
    """A required cell annotated capability: not-implemented is a deliberate
    capability boundary — it must render 不适用not-applicable, NEVER 空gap or
    未配置unconfigured, whether or not the LLM is available."""
    cell = {"domain": "medical-research", "product": "tutorial", "format": "html"}
    assert ("medical-research", "tutorial", "html") in cm.not_implemented_cells_set(spec)
    assert cm.classify_cell(
        cell, EMPTY_PRODUCED, llm_available=True, spec=spec
    ) == cm.NOT_APPLICABLE
    assert cm.classify_cell(
        cell, EMPTY_PRODUCED, llm_available=False, spec=spec
    ) == cm.NOT_APPLICABLE
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=True, spec=spec) != cm.GAP
    assert cm.classify_cell(
        cell, EMPTY_PRODUCED, llm_available=False, spec=spec
    ) != cm.UNCONFIGURED


def test_capability_boundary_with_evidence_is_produced(spec):
    """Evidence trumps the capability annotation: a not-implemented cell that
    somehow has produced artifacts still renders 有produced."""
    cell = {"domain": "medical-research", "product": "tutorial", "format": "html"}
    produced = {("medical-research", "tutorial", "html")}
    assert cm.classify_cell(cell, produced, llm_available=True, spec=spec) == cm.PRODUCED


def test_implemented_required_cell_without_evidence_is_still_gap(spec):
    """capability: implemented required cells stay real gaps when empty —
    the annotation must NOT blanket-exempt required cells from gap status."""
    cell = {"domain": "medical-research", "product": "tutorial", "format": "markdown"}
    assert ("medical-research", "tutorial", "markdown") not in cm.not_implemented_cells_set(spec)
    assert cm.classify_cell(cell, EMPTY_PRODUCED, llm_available=True, spec=spec) == cm.GAP


def test_required_cells_set_contains_all_required_cells(spec):
    """required_cells_set (gap-domain) is a superset of the implemented cells
    while not_implemented_cells_set holds only the capability boundaries."""
    required = cm.required_cells_set(spec)
    not_impl = cm.not_implemented_cells_set(spec)
    assert required
    assert not_impl
    assert not_impl <= required
    for c in spec["required_cells"]:
        triple = (c["domain"], c["product"], c["format"])
        if c["capability"] == "implemented":
            assert triple in required and triple not in not_impl
        else:
            assert triple in not_impl


# ---------------------------------------------------------------------------
# Spec file validity
# ---------------------------------------------------------------------------


def test_spec_parses_and_has_required_structure(spec):
    assert spec["version"] == 2
    assert len(spec["products"]) == 8
    assert len(spec["formats"]) == 7
    assert len(spec["domains"]) == 13


def test_spec_full_capability_dimensions_present(spec):
    """Full-capability revision (2026-08-07): source + KB-tier dimensions."""
    assert len(spec["source_platforms"]) >= 25
    assert set(spec["kb_tiers"]) == {"01-Raw", "02-Draft", "03-Wiki"}
    assert len(spec["required_sources"]) >= 10
    assert len(spec["required_kb_tiers"]) >= 4


def test_spec_has_at_least_10_required_cells(spec):
    required = spec["required_cells"]
    assert len(required) >= 10
    for cell in required:
        assert set(cell) == {"domain", "product", "format", "capability"}
        assert cell["capability"] in {"implemented", "not-implemented"}
        assert cell["domain"] in spec["domains"]
        assert cell["product"] in spec["products"]
        assert cell["format"] in spec["formats"]


def test_spec_required_cells_cover_oracle_r8_shape(spec):
    """R8: digest/report json+html + tutorial/presentation markdown across
    medical-research and tech-ai-developer, plus one audio cell."""
    cells = {(c["domain"], c["product"], c["format"]) for c in spec["required_cells"]}
    for domain in ("medical-research", "tech-ai-developer"):
        for product in ("digest", "report"):
            for fmt in ("json", "html"):
                assert (domain, product, fmt) in cells
        for product in ("tutorial", "presentation"):
            assert (domain, product, "markdown") in cells
    assert ("medical-research", "digest", "audio") in cells


def test_spec_llm_gated_products_listed(spec):
    gated = set(spec["llm_gated_products"])
    assert {"premium-briefing", "column", "magazine-digest", "enterprise-briefing",
            "tutorial", "presentation"} <= gated
    assert "digest" not in gated and "report" not in gated


# ---------------------------------------------------------------------------
# Evidence scanning — outputs/** + validation_delivery manifests
# ---------------------------------------------------------------------------


def test_parse_persisted_path():
    assert cm.parse_persisted_path(
        "outputs/medical-research/digest-json-20260806-120000.json"
    ) == ("medical-research", "digest", "json")
    assert cm.parse_persisted_path(
        "outputs/tech-ai-developer/magazine-digest-markdown-20260806-120000.md"
    ) == ("tech-ai-developer", "magazine-digest", "markdown")
    assert cm.parse_persisted_path(
        "outputs/ai-commercial/digest-markdown-20260810-paygrade.md"
    ) == ("ai-commercial", "digest", "markdown")
    assert cm.parse_persisted_path("outputs/x/audio-20260806-120000.mp3") is None
    assert cm.parse_persisted_path("knowledge/medical-research/01-Raw/x.md") is None
    assert cm.parse_persisted_path("outputs/medical-research/README.md") is None


def _write_manifest(path: Path, entries: list[dict]) -> None:
    path.write_text(
        json.dumps({"files": entries, "rejected": []}),
        encoding="utf-8",
    )


def _manifest_entry(source: str, quality: str = "PASS") -> dict:
    return {
        "file": f"02-PROCESSED/{Path(source).name}",
        "kind": "PROCESSED",
        "source": source,
        "size": 10,
        "gates": {"D1": {"passed": quality == "PASS"}},
        "quality": quality,
    }


def test_scan_evidence_outputs_and_manifests(tmp_path):
    out = tmp_path / "outputs"
    (out / "medical-research").mkdir(parents=True)
    (out / "tech-ai-developer").mkdir(parents=True)
    (out / "medical-research" / "digest-json-20260806-120000.json").touch()
    (out / "medical-research" / "magazine-digest-markdown-20260806-120000.md").touch()
    (out / "medical-research" / "README.md").touch()  # not a persisted artifact
    (out / "tech-ai-developer" / "report-html-20260806-120000.html").touch()

    deliveries = tmp_path / "validation-deliveries" / "2026-08-06"
    deliveries.mkdir(parents=True)
    _write_manifest(
        deliveries / "manifest.json",
        [
            _manifest_entry("outputs/medical-research/digest-html-20260806-120000.html"),
            _manifest_entry("outputs/medical-research/column-markdown-20260806-120000.md",
                            quality="FAIL"),  # rejected at delivery gates — excluded
        ],
    )
    with zipfile.ZipFile(deliveries / "validation-delivery-20260806-120000.zip", "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({
                "files": [
                    _manifest_entry("outputs/tech-ai-developer/report-json-20260806-120000.json")
                ],
                "rejected": [],
            }),
        )

    produced = cm.scan_evidence(tmp_path)

    assert produced == {
        ("medical-research", "digest", "json"),
        ("medical-research", "magazine-digest", "markdown"),
        ("tech-ai-developer", "report", "html"),
        ("medical-research", "digest", "html"),
        ("tech-ai-developer", "report", "json"),
    }


def test_scan_evidence_missing_dir_returns_empty(tmp_path):
    assert cm.scan_evidence(tmp_path / "does-not-exist") == set()


# ---------------------------------------------------------------------------
# LLM availability detection
# ---------------------------------------------------------------------------


def test_detect_llm_available(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  provider: openai\n  api_key: sk-test\n", encoding="utf-8")
    assert cm.detect_llm_available(cfg) is True

    cfg.write_text("llm:\n  provider: openai\n  api_key: ''\n", encoding="utf-8")
    assert cm.detect_llm_available(cfg) is False

    cfg.unlink()
    assert cm.detect_llm_available(cfg) is False


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_render_report_valid_markdown_with_legend(spec):
    produced = {
        ("medical-research", "digest", "json"),
        ("medical-research", "digest", "html"),
    }
    report = cm.render_report(spec, produced, llm_available=False)

    assert report.startswith("# End-User Coverage Matrix (E8, issue #131)")
    assert "## Legend" in report
    for status in (cm.PRODUCED, cm.GAP, cm.NOT_APPLICABLE, cm.UNCONFIGURED):
        assert status in report
    assert "## Matrix (rows = products, columns = domains)" in report
    assert "## COVERAGE_GAP" in report
    assert "| digest | 有produced |" in report
    # required LLM-gated cells surface as 未配置 in the matrix with no LLM
    assert "| tutorial | 未配置unconfigured |" in report
    assert "| presentation | 未配置unconfigured |" in report
    # the empty required digest/report cells land in COVERAGE_GAP, not silence
    assert "| medical-research | digest | html |" not in report  # produced
    assert "| medical-research | report | json |" in report


def test_render_report_gap_summary_present_but_not_silent_when_no_gaps(spec):
    all_required = {(c["domain"], c["product"], c["format"]) for c in spec["required_cells"]}
    report = cm.render_report(spec, all_required, llm_available=True)
    assert "No required-empty gap cells" in report


# ---------------------------------------------------------------------------
# CLI behavior
# ---------------------------------------------------------------------------


def test_cli_exit_2_on_missing_spec():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", "/nonexistent.yaml",
         "--evidence", str(ROOT)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2


def test_cli_exit_2_on_missing_evidence(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(SPEC),
         "--evidence", str(tmp_path / "missing-evidence")],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2


def test_cli_end_to_end_writes_report(tmp_path):
    out = tmp_path / "outputs" / "medical-research"
    out.mkdir(parents=True)
    (out / "digest-json-20260806-120000.json").touch()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(SPEC),
         "--evidence", str(tmp_path), "--no-llm", "--output", str(tmp_path / "report")],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report_path = tmp_path / "report" / "matrix-report.md"
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert "## Legend" in report
    assert "## COVERAGE_GAP" in report
    assert "有produced" in report
    assert "未配置unconfigured" in report
    # with --no-llm the empty tutorial/presentation cells must NOT be gaps
    assert "| tutorial | 空gap |" not in report
