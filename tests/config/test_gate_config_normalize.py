"""Tests for quality-gate config key normalization.

``_normalize_gate_config_keys`` maps the short gate keys used by the
default config (``G0``, ``G1``, ...) to the canonical long keys the
pipeline looks up (``G0-SchemaIntegrity``, ``G1-SourceAuthority``, ...),
so gates always receive their configured values.
"""

from __future__ import annotations

import pytest

from autoinfo.config import (
    Config,
    _normalize_gate_config_keys,
    _dict_to_config,
)


# ---------------------------------------------------------------------------
# _normalize_gate_config_keys unit tests
# ---------------------------------------------------------------------------


def test_short_keys_only_maps_to_long_keys() -> None:
    raw = {
        "G0": {"category": "hard"},
        "G1": {"category": "soft"},
        "G1-TosCompliance": {"category": "soft"},
        "G2": {"category": "soft"},
        "G3": {"category": "soft"},
        "G4": {"category": "hard"},
        "G5": {"category": "soft"},
    }
    assert _normalize_gate_config_keys(raw) == {
        "G0-SchemaIntegrity": {"category": "hard"},
        "G1-SourceAuthority": {"category": "soft"},
        "G1-TosCompliance": {"category": "soft"},
        "G2-Dedup": {"category": "soft"},
        "G3-RelevanceScoring": {"category": "soft"},
        "G4-SummaryFactual": {"category": "hard"},
        "G5-TranslationAccuracy": {"category": "soft"},
    }


def test_long_keys_only_passthrough() -> None:
    raw = {
        "G0-SchemaIntegrity": {"category": "hard"},
        "G4-SummaryFactual": {"category": "hard", "retries": 3},
    }
    assert _normalize_gate_config_keys(raw) == raw


def test_mixed_keys_merged_with_long_key_priority() -> None:
    raw = {
        "G0": {"category": "hard", "retries": 1},
        "G0-SchemaIntegrity": {"category": "hard", "retries": 5, "action": "block"},
        "G1": {"category": "soft", "action": "flag"},
        "G5-TranslationAccuracy": {"category": "soft", "retries": 2},
    }
    assert _normalize_gate_config_keys(raw) == {
        # Long key wins when both forms appear for the same gate
        "G0-SchemaIntegrity": {"category": "hard", "retries": 5, "action": "block"},
        "G1-SourceAuthority": {"category": "soft", "action": "flag"},
        "G5-TranslationAccuracy": {"category": "soft", "retries": 2},
    }


def test_empty_dict_returns_empty_dict() -> None:
    assert _normalize_gate_config_keys({}) == {}


def test_unknown_key_passthrough_unchanged() -> None:
    raw = {"custom-gate": {"category": "soft"}}
    assert _normalize_gate_config_keys(raw) == raw


# ---------------------------------------------------------------------------
# Integration: _dict_to_config produces long-keyed gate configs
# ---------------------------------------------------------------------------


def test_dict_to_config_normalizes_short_gate_keys() -> None:
    raw = {
        "project": {"name": "t"},
        "quality_gates": {
            "G0": {"category": "hard", "action": "block"},
            "G1": {"category": "soft", "action": "flag"},
        },
    }
    config: Config = _dict_to_config(raw)
    assert set(config.quality_gates) == {"G0-SchemaIntegrity", "G1-SourceAuthority"}
    assert config.quality_gates["G0-SchemaIntegrity"].category == "hard"
    assert config.quality_gates["G1-SourceAuthority"].category == "soft"


def test_dict_to_config_passthrough_long_gate_keys() -> None:
    raw = {
        "project": {"name": "t"},
        "quality_gates": {
            "G2-Dedup": {"category": "soft", "window_days": 30},
        },
    }
    config: Config = _dict_to_config(raw)
    assert set(config.quality_gates) == {"G2-Dedup"}
    assert config.quality_gates["G2-Dedup"].window_days == 30


def test_dict_to_config_normalizes_per_domain_gate_keys() -> None:
    raw = {
        "project": {"name": "t"},
        "domains": [
            {
                "name": "d1",
                "active": True,
                "sources": [],
                "topics": [],
                "quality_gates": {"G4": {"category": "hard"}},
            }
        ],
    }
    config: Config = _dict_to_config(raw)
    assert config.domains[0].quality_gates.keys() == {"G4-SummaryFactual"}
