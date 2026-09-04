"""Integration tests for the 01-QA-GATES/ directory in the delivery package.

Task 7 of the report-validation concierge wave
(.omo/plans/autoinfo-report-validation-concierge-wave.md:124-130):
``scripts/validation_delivery.py`` must emit ``01-QA-GATES/gate-report-<product>.{md,json}``
for every PROCESSED product it packages, recording the delivery-layer
determinations (D1-D3 + authenticity + packager-level results) honestly —
G0-G5 run at process time and are NOT recomputed here — plus an index whose
``rejected`` list mirrors manifest.json's ``rejected`` key exactly.

Placement note: the existing delivery tests live in ``tests/validation/``
(test_validation_delivery.py / test_validation_delivery_gates.py), not in
``tests/integration/`` or ``tests/scripts/``. The task pinned this new test
to ``tests/integration/``, so it lives here while mirroring the
``tests/validation/`` conventions (importlib-load of the real script, real
``autoinfo.quality`` D gates — hermetic, no LLM, no network).

Honesty requirements under test:
- Fixtures use real/recent ``collected_at`` timestamps so D3-Freshness is not
  false-rejected (quality.py D3Freshness).
- The D1 failure is triggered by a product genuinely missing required
  sections (per the ``_build_product_output`` required-section rules).
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Load the real scripts/validation_delivery.py (same pattern as the sibling
# tests/validation/test_validation_delivery.py) so the tests exercise the
# script's own code.
_SPEC = importlib.util.spec_from_file_location(
    "validation_delivery", ROOT / "scripts" / "validation_delivery.py"
)
assert _SPEC is not None and _SPEC.loader is not None
vd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vd)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _zip_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def _zip_read(zip_path: Path, name: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name).decode("utf-8")


def _zip_manifest(zip_path: Path) -> dict:
    return json.loads(_zip_read(zip_path, "manifest.json"))


def _zip_index(zip_path: Path) -> dict:
    return json.loads(_zip_read(zip_path, "01-QA-GATES/gate-reports-index.json"))


def _fresh_iso() -> str:
    """A real, recent collected_at (1 day ago) — D3-Freshness-safe."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _complete_digest(tmp_path: Path) -> Path:
    """A digest-style markdown with the required D1 section (alias match)."""
    p = tmp_path / "digest-2026-09-04.md"
    p.write_text(
        "# Weekly AI Digest\n\n"
        "## Executive Summary\n\nAI adoption accelerates.\n\n"
        "### Key Findings\n\n- LLM costs dropped 40%.\n\n"
        "### Recommendations\n\n- Adopt agent workflows.\n",
        encoding="utf-8",
    )
    return p


def _fresh_json_digest(tmp_path: Path) -> Path:
    """A JSON report product with a real/recent collected_at timestamp."""
    p = tmp_path / "digest-fresh.json"
    p.write_text(
        json.dumps(
            {
                "title": "Fresh digest",
                "summary": "s",
                "key_findings": ["k1"],
                "recommendations": ["r1"],
                "entries": [
                    {
                        "title": "fresh entry",
                        "source_url": "https://pubmed.ncbi.nlm.nih.gov/42",
                        "source_type": "pubmed",
                        "source_platform": "pubmed",
                        "collected_at": _fresh_iso(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return p


def _incomplete_report(tmp_path: Path) -> Path:
    """A report-type product missing every D1 required section (real D1 fail)."""
    p = tmp_path / "broken-report.md"
    p.write_text("# Broken Report\n\nNo canonical sections here.\n", encoding="utf-8")
    return p


def _package(tmp_path: Path, artifacts: list[Path]) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return vd._package([{"path": str(p)} for p in artifacts], [], out)


# ---------------------------------------------------------------------------
# docstring / directory listing
# ---------------------------------------------------------------------------


def test_docstring_directory_listing_includes_qa_gates():
    doc = (ROOT / "scripts" / "validation_delivery.py").read_text(encoding="utf-8")
    assert "01-QA-GATES/" in doc


# ---------------------------------------------------------------------------
# 01-QA-GATES emission
# ---------------------------------------------------------------------------


def test_package_emits_qa_gates_dir_with_reports(tmp_path):
    """Every PROCESSED product gets gate-report-<product>.md AND .json."""
    zip_path = _package(tmp_path, [_complete_digest(tmp_path), _fresh_json_digest(tmp_path)])
    names = _zip_names(zip_path)
    assert any(n.startswith("01-QA-GATES/") for n in names), names
    assert "01-QA-GATES/gate-reports-index.json" in names

    manifest = _zip_manifest(zip_path)
    processed = [e for e in manifest["files"] if e.get("kind") == "PROCESSED"]
    assert len(processed) == 2, manifest["files"]

    index = _zip_index(zip_path)
    by_product = {r["product"]: r for r in index["reports"]}
    for entry in processed:
        assert entry["file"] in by_product, (
            f"no gate report for {entry['file']}: {sorted(by_product)}"
        )
        rep = by_product[entry["file"]]
        assert rep["delivered"] is True
        assert rep["report_md"] in names, names
        assert rep["report_json"] in names, names


def test_gate_report_json_records_d_gates_and_layer_note(tmp_path):
    """JSON reports carry a gates array (D1-D3 + authenticity) + layer note."""
    zip_path = _package(tmp_path, [_fresh_json_digest(tmp_path)])
    index = _zip_index(zip_path)
    report_json = index["reports"][0]["report_json"]
    payload = json.loads(_zip_read(zip_path, report_json))

    assert set(payload) >= {
        "product",
        "kind",
        "delivered",
        "rejected_reason",
        "layer_note",
        "gates",
        "quality",
    }
    assert payload["kind"] == "PROCESSED"
    assert payload["delivered"] is True
    assert payload["quality"] == "PASS"
    # Honesty: G0-G5 are process-layer; only delivery determinations here.
    assert "G0-G5" in payload["layer_note"]
    assert "process" in payload["layer_note"]
    # gates array: D1-D3 determinations + authenticity.
    assert [g["gate"] for g in payload["gates"]] == ["D1", "D2", "D3", "authenticity"]
    by_gate = {g["gate"]: g for g in payload["gates"]}
    assert by_gate["D1"]["passed"] is True
    assert by_gate["D2"]["passed"] is True
    # Real/recent timestamps -> D3 must NOT false-reject.
    assert by_gate["D3"]["passed"] is True
    assert by_gate["authenticity"]["passed"] is True


def test_gate_report_md_is_human_readable_and_honest(tmp_path):
    md_text = _zip_read(
        zip_path := _package(tmp_path, [_complete_digest(tmp_path)]),
        _zip_index(zip_path)["reports"][0]["report_md"],
    )
    assert md_text.startswith("# Gate Report — ")
    assert "## Gates" in md_text
    for gate in ("D1", "D2", "D3", "authenticity"):
        assert gate in md_text
    assert "G0-G5" in md_text and "process" in md_text
    assert "PASS" in md_text


def test_rejected_product_has_gate_report_consistent_with_manifest(tmp_path):
    """A real D1 failure lands in 06-REJECTED and its gate report honestly
    records D1 failed + delivered=false; the index rejected list equals the
    manifest rejected key."""
    zip_path = _package(tmp_path, [_complete_digest(tmp_path), _incomplete_report(tmp_path)])
    names = _zip_names(zip_path)
    manifest = _zip_manifest(zip_path)
    index = _zip_index(zip_path)

    # The broken product was really rejected by the real D1 gate.
    assert len(manifest["rejected"]) == 1, manifest["rejected"]
    rejected_entry = manifest["rejected"][0]
    assert rejected_entry["file"].startswith("06-REJECTED/")
    assert rejected_entry["reason"].startswith("D1:")
    assert "Missing sections" in rejected_entry["reason"]

    # Index rejected list is consistent with the manifest rejected key.
    assert index["rejected"] == manifest["rejected"]

    # Its gate report records the rejection honestly.
    by_product = {r["product"]: r for r in index["reports"]}
    rep = by_product[rejected_entry["file"]]
    assert rep["delivered"] is False
    assert rep["report_md"] in names and rep["report_json"] in names
    payload = json.loads(_zip_read(zip_path, rep["report_json"]))
    payload_gates = {g["gate"]: g for g in payload["gates"]}
    assert payload["delivered"] is False
    assert payload["rejected_reason"].startswith("D1:")
    assert payload_gates["D1"]["passed"] is False
    assert payload["quality"] == "FAIL"

    # The complete digest is still delivered with its own passing report.
    processed = [e for e in manifest["files"] if e.get("kind") == "PROCESSED"]
    assert len(processed) == 1
    good = by_product[processed[0]["file"]]
    assert good["delivered"] is True


def test_qa_gates_report_files_registered_in_manifest(tmp_path):
    zip_path = _package(tmp_path, [_complete_digest(tmp_path)])
    manifest = _zip_manifest(zip_path)
    # Additive key — the ``files`` list stays delivered+MATRIX evidence.
    qa_entries = manifest["qa_gate_reports"]
    names = {e["file"] for e in qa_entries}
    assert "01-QA-GATES/gate-reports-index.json" in names
    assert any(n.endswith(".md") for n in names)
    assert any(n.endswith(".json") for n in names)
    assert all(e["quality"] == "PASS" for e in qa_entries)
    # And ``files`` is untouched by the QA section (no QA-GATES kind).
    assert all(e.get("kind") != "QA-GATES" for e in manifest["files"])


# ---------------------------------------------------------------------------
# _qa_product_key — deterministic, filesystem-safe, collision-free
# ---------------------------------------------------------------------------


def test_qa_product_key_unique_and_safe():
    used: set[str] = set()
    k1 = vd._qa_product_key(Path("digest.md"), used)
    k2 = vd._qa_product_key(Path("digest.md"), used)
    k3 = vd._qa_product_key(Path("sub/dir/digest.json"), used)
    assert k1 == "digest"
    assert k2 != k1, "same stem twice must not collide"
    assert k3 == "sub__dir__digest"
    for key in (k1, k2, k3):
        assert "/" not in key
        assert key and key == key.strip()
