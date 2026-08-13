"""T4 — CurationGate configuration in per-domain quality_gates (plan todo 4).

Covers the configurable side of the KB curation admission gate:

1. ``set_gate_config`` accepts "CurationGate" and routes it to the domain's
   *quality* gates — even though its dict carries ``enabled``, which the
   generic quality-vs-delivery heuristic would otherwise misread.
2. Full round-trip: set → ``_save_config`` YAML → fresh ``load_config`` —
   the ``enabled`` / ``threshold`` values survive a restart-equivalent load.
3. The wired CurationGate drives :func:`check_promotion_admission` from a
   real YAML-loaded config: ``threshold`` raises the shared G1/G3 bar and
   ``enabled=False`` skips the G4 LLM check.
4. A domain without a CurationGate gets the documented defaults
   (G1/G3 threshold 30, G4 on) through the same YAML parse → admission path.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from autoinfo.config import load_config
from autoinfo.mcp.server import _handle_get_gate_config, _handle_set_gate_config
from autoinfo.models import KBEntry
from autoinfo.promotion import RejectionReason, check_promotion_admission
from autoinfo.quality import QualityResult

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _make_config_yaml(project_dir: Path) -> None:
    """Write a minimal config.yaml with a medical-research domain (no gates)."""
    config: dict[str, Any] = {
        "project": {"name": "Test Project", "created_at": "2026-07-01"},
        "llm": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat",
            "api_key": "test-key",
        },
        "domains": [
            {
                "name": "medical-research",
                "active": True,
                "sources": [
                    {
                        "name": "pubmed",
                        "type": "api",
                        "url": "https://example.com/api",
                        "quality_tier": 1,
                    }
                ],
                "topics": [],
            }
        ],
    }
    config_dir = project_dir / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / "config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(config, fh, default_flow_style=False)


@pytest.fixture
def project_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch Path.cwd to a temp project with a minimal config.yaml."""
    _make_config_yaml(tmp_path)
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        yield tmp_path


def _make_entry(**overrides: object) -> KBEntry:
    """Build a complete, admission-ready 02-Draft entry."""
    entry = KBEntry(
        entry_id="medical-research-draft-001",
        title="Time-lapse imaging in IVF",
        domain="medical-research",
        tier="02-Draft",
        source_url="https://example.com/paper1",
        source_type="api",
        source_platform="pubmed",
        summary="Time-lapse embryo imaging improves IVF selection.",
        source_score=72.0,
        relevance_score=85.0,
        quality_tier=1,
        source_ids=["raw-001"],
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def _make_raw() -> KBEntry:
    """Build a complete 01-Raw source entry with mandatory provenance."""
    return KBEntry(
        entry_id="raw-001",
        title="Raw source paper",
        domain="medical-research",
        tier="01-Raw",
        source_url="https://example.com/paper1",
        source_type="api",
        source_platform="pubmed",
        quality_tier=1,
        source_score=72.0,
        relevance_score=85.0,
    )


def _fake_g4(monkeypatch: pytest.MonkeyPatch, passed: bool) -> None:
    """Monkeypatch promotion's G4 class so admission never calls a real LLM."""

    class _FakeG4:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def check(
            self,
            item: object,
            extraction: object,
            gate_config: object | None = None,  # noqa: ARG002
        ) -> QualityResult:
            return QualityResult(
                gate_name="G4-SummaryFactual",
                passed=passed,
                score=1.0 if passed else 0.0,
                details={"contradiction": not passed},
            )

    monkeypatch.setattr("autoinfo.promotion.G4FactualConsistency", _FakeG4)


# ===================================================================
# set_gate_config / get_gate_config — CurationGate is a quality gate
# ===================================================================


class TestCurationGateConfig:
    def test_set_gate_config_accepts_curation_gate_as_quality(
        self, project_dir: Path
    ) -> None:
        """CurationGate routes to quality gates despite carrying ``enabled``."""
        result = _handle_set_gate_config(
            domain="medical-research",
            gate="CurationGate",
            config={"enabled": False, "threshold": 35},
        )
        assert "error_code" not in result, f"Unexpected error: {result}"
        assert result["updated"] is True
        assert result["config"]["enabled"] is False
        assert result["config"]["threshold"] == 35

        readback = _handle_get_gate_config(
            domain="medical-research", gate="CurationGate"
        )
        assert "error_code" not in readback, f"Unexpected error: {readback}"
        assert readback["gate_type"] == "quality"
        assert readback["config"]["enabled"] is False
        assert readback["config"]["threshold"] == 35

    def test_gate_config_curation_roundtrip(self, project_dir: Path) -> None:
        """CurationGate survives a fresh config load (restart persistence)."""
        result = _handle_set_gate_config(
            domain="medical-research",
            gate="CurationGate",
            config={"enabled": False, "threshold": 35},
        )
        assert "error_code" not in result, f"Unexpected error: {result}"

        cfg = load_config(project_dir / ".autoinfo" / "config.yaml")
        curation = cfg.domains[0].quality_gates["CurationGate"]
        assert curation.enabled is False
        assert curation.threshold == 35

    def test_loaded_curation_config_drives_admission(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wired config raises the G1/G3 bar and disables G4 in admission."""
        result = _handle_set_gate_config(
            domain="medical-research",
            gate="CurationGate",
            config={"enabled": False, "threshold": 35},
        )
        assert "error_code" not in result, f"Unexpected error: {result}"
        cfg = load_config(project_dir / ".autoinfo" / "config.yaml")

        _fake_g4(monkeypatch, passed=False)
        # Above the default 30 but below the configured 35 → threshold rejects.
        low = check_promotion_admission(
            _make_entry(source_score=32.0, relevance_score=32.0),
            "medical-research",
            cfg,
            resolve_raw=lambda _rid: _make_raw(),
        )
        assert not low.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in low.reasons

        # At/above 35 with G4 disabled: an inconsistent draft still passes.
        high = check_promotion_admission(
            _make_entry(source_score=40.0, relevance_score=40.0),
            "medical-research",
            cfg,
            resolve_raw=lambda _rid: _make_raw(),
        )
        assert high.allowed

    def test_domain_without_curation_gate_uses_defaults(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No CurationGate → defaults apply: G1/G3 ≥ 30, G4 on."""
        cfg = load_config(project_dir / ".autoinfo" / "config.yaml")
        assert "CurationGate" not in cfg.domains[0].quality_gates

        _fake_g4(monkeypatch, passed=True)
        ok = check_promotion_admission(
            _make_entry(source_score=30.0, relevance_score=30.0),
            "medical-research",
            cfg,
            resolve_raw=lambda _rid: _make_raw(),
        )
        assert ok.allowed
        assert ok.reasons == [RejectionReason.OK]

        _fake_g4(monkeypatch, passed=True)
        rejected = check_promotion_admission(
            _make_entry(source_score=29.9, relevance_score=30.0),
            "medical-research",
            cfg,
            resolve_raw=lambda _rid: _make_raw(),
        )
        assert not rejected.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in rejected.reasons
