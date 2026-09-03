"""Tests for the L1 agent-review battery (scripts/agent_review/battery.py).

Issue #194: the battery assembles blind-spot worklist items from
blindspots.yaml, pre-filters with the L0 gate, and (opt-in --semantic) asks
the config-driven LLM for verdicts with a fail-loud ESCALATE policy.  These
tests lock the DETERMINISTIC machinery: worklist assembly, blind-spot
attachment, markdown-verdict parsing, and the fail-loud path (an unreachable
LLM yields ESCALATE, never PASS — #195/#127).

No network, no real LLM: the judgment call is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# scripts/agent_review/ is not a package — load it via sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "agent_review"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import battery as bat  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "known-defects"


def _load_bs() -> list[dict[str, Any]]:
    return bat._load_blindspots()


# ---------------------------------------------------------------------------
# blindspots.yaml integrity
# ---------------------------------------------------------------------------


def test_blindspots_yaml_loads_all_families() -> None:
    bs = _load_bs()
    families = {m["family"] for m in bs}
    assert {
        "digest", "magazine-digest", "column", "premium-briefing",
        "enterprise-briefing", "report", "presentation", "cross-domain",
        "all", "bilingual-domains",
    } <= families


def test_blindspot_descriptions_have_no_vendor_names() -> None:
    """#194 comment + #195: check_desc must never name a model/vendor."""
    bs = _load_bs()
    banned = ("deepseek", "openrouter", "ark-", "volces", "openai", "claude")
    for manifest in bs:
        for blind in manifest["blind_spots"]:
            desc = (blind.get("check_desc", "") + " " + blind.get("name", "")).lower()
            for token in banned:
                assert token not in desc, (
                    f"blind spot {blind['id']} mentions vendor/model {token!r}"
                )


# ---------------------------------------------------------------------------
# Worklist assembly
# ---------------------------------------------------------------------------


def test_worklist_maps_product_families(tmp_path: Path) -> None:
    (tmp_path / "magazine-digest.md").write_text("# m\n", encoding="utf-8")
    (tmp_path / "digest.md").write_text("# d\n", encoding="utf-8")
    items = bat.build_worklist(tmp_path, _load_bs())
    fams = {it["family"] for it in items}
    assert "magazine-digest" in fams
    assert "digest" in fams
    # Every magazine item is a blind spot from the manifest.
    magazine_items = [it for it in items if it["family"] == "magazine-digest"]
    assert {it["blind_spot"] for it in magazine_items} == {
        "claim-fabrication-vs-hedge",
        "inferential-wording",
        "feature-grounding",
    }


def test_worklist_cross_domain_only_when_aggregate_present(tmp_path: Path) -> None:
    # A single-domain dir with several product files: NO cross-domain attach.
    for name in ("digest.md", "report.md", "magazine-digest.md", "column.md"):
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    items = bat.build_worklist(tmp_path, _load_bs())
    assert all(it["family"] != "cross-domain" for it in items)

    # A dir with a cross-domain aggregate product: attach fires.
    (tmp_path / "cross-domain-report.md").write_text("# c\n", encoding="utf-8")
    items2 = bat.build_worklist(tmp_path, _load_bs())
    assert any(it["family"] == "cross-domain" for it in items2)


def test_worklist_bilingual_local_market_attach(tmp_path: Path) -> None:
    """The bilingual-domains blind spot attaches for ai-commercial dirs."""
    ai_dir = tmp_path / "ai-commercial"
    ai_dir.mkdir()
    (ai_dir / "digest.md").write_text("# d\n", encoding="utf-8")
    blindspots = _load_bs()
    # run_battery attaches the bilingual blind spot — emulate via _bs_for.
    local = bat._bs_for(blindspots, "bilingual-domains")
    assert local and local[0]["id"] == "local-market-presence"
    # The detection helper recognises ai-commercial.
    assert bat._detect_bilingual_domains(ai_dir) == ["ai-commercial"]


# ---------------------------------------------------------------------------
# L0 pre-filter
# ---------------------------------------------------------------------------


def test_l0_gate_defects_surfaced() -> None:
    """run_l0_gate returns the L0 defect lines for a polluted dir."""
    defects = bat.run_l0_gate(_FIXTURES / "three-person-drift")
    assert any("C6" in d for d in defects)


def test_l0_gate_clean_returns_empty() -> None:
    defects = bat.run_l0_gate(_FIXTURES / "known-good")
    assert defects == []


# ---------------------------------------------------------------------------
# Markdown verdict parsing (non-json_mode channel)
# ---------------------------------------------------------------------------


def test_parse_markdown_verdicts_valid_block() -> None:
    text = """## Verdict
- **blind_spot**: claim-fabrication-vs-hedge
- **verdict**: FLAG
- **evidence**: magazine-digest.md:24
- **note**: drift detected
"""
    parsed = bat._parse_markdown_verdicts(text)
    assert len(parsed) == 1
    assert parsed[0]["verdict"] == "FLAG"
    assert parsed[0]["evidence"] == "magazine-digest.md:24"


def test_parse_markdown_verdicts_missing_evidence_dropped() -> None:
    # A block without evidence is invalid and must be dropped (the item
    # falls back to ESCALATE at assembly — fail loud).
    text = """## Verdict
- **blind_spot**: x
- **verdict**: PASS
"""
    assert bat._parse_markdown_verdicts(text) == []


# ---------------------------------------------------------------------------
# Fail-loud LLM path (#195/#127): unreachable channel -> ESCALATE, never PASS
# ---------------------------------------------------------------------------
# battery.py imports call_with_fallback INSIDE _judge_with_llm (from
# autoinfo.llm) so the patch target is autoinfo.llm.call_with_fallback.
_REPO_ROOT_SRC = _REPO_ROOT / "src"


def _judge(prompt: str, want_json: bool = False) -> dict[str, Any]:
    # Make autoinfo importable, then run the judge with the channel patched.
    sys.path.insert(0, str(_REPO_ROOT_SRC))
    try:
        return bat._judge_with_llm(prompt, want_json=want_json)
    finally:
        sys.path.remove(str(_REPO_ROOT_SRC))


@patch("autoinfo.llm.call_with_fallback", side_effect=RuntimeError("provider down"))
def test_unreachable_llm_escalates_not_passes(mock_call: Any) -> None:
    res = _judge("some prompt")
    assert res["verdict"] == "ESCALATE"
    assert "unreachable" in res["evidence"]
    mock_call.assert_called_once()


@patch("autoinfo.llm.call_with_fallback", return_value="not a verdict at all")
def test_unparseable_llm_output_escalates(mock_call: Any) -> None:
    res = _judge("some prompt")
    assert res["verdict"] == "ESCALATE"


@patch("autoinfo.llm.call_with_fallback", return_value="{broken json")
def test_unparseable_json_mode_escalates(mock_call: Any) -> None:
    res = _judge("some prompt", want_json=True)
    assert res["verdict"] == "ESCALATE"


# ---------------------------------------------------------------------------
# Battery run against known-defects fixtures (deterministic preview)
# ---------------------------------------------------------------------------


def test_battery_preview_known_good_dir() -> None:
    report = bat.run_battery(_FIXTURES / "known-good", semantic=False)
    # L0 clean; worklist present; no verdicts (preview mode).
    assert report["l0_defects"] == []
    assert report["worklist"]
    assert report["verdicts"] == []
    assert report["summary"]["l0_failed"] is False


def test_battery_preview_defect_dir_reports_l0() -> None:
    report = bat.run_battery(_FIXTURES / "three-person-drift", semantic=False)
    assert report["l0_defects"]  # C6 catches the three-person drift
    assert report["summary"]["l0_failed"] is True
