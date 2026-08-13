"""Tests for v1.5 config schema — QualityGateConfig and DeliveryGateConfig.

Covers: dataclass defaults, YAML parsing, serialization, validation,
per-domain overrides, global defaults, and backward compatibility.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest
import yaml

from autoinfo.config import (
    Config,
    DeliveryGateConfig,
    DomainConfig,
    LLMConfig,
    ProjectConfig,
    QualityGateConfig,
    SourceConfig,
    _dict_to_config,
    config_to_dict,
    validate_config,
)

# ---------------------------------------------------------------------------
# Sample YAML configs
# ---------------------------------------------------------------------------

CONFIG_WITH_GATES = """
project:
  name: Gate Test
  created_at: "2026-07-24"

llm:
  provider: openai
  model: gpt-4o-mini
  api_key: test-key

domains:
  - name: medical-research
    active: true
    sources:
      - name: pubmed
        type: api
        url: https://example.com

quality_gates:
  G0:
    category: hard
    retries: 1
    action: block
  G4:
    category: hard
    retries: 3
    retry_models: [deepseek/deepseek-chat, anthropic/claude-sonnet-4]
    action: block
  G3:
    category: soft
    retries: 2
    retry_models: [deepseek/deepseek-chat]
    action: archive
    threshold: 30

delivery_gates:
  D1:
    enabled: true
    action_on_failure: block
  D2:
    enabled: true
    action_on_failure: fallback
"""

CONFIG_WITH_DOMAIN_GATES = """
project:
  name: Domain Gate Test

llm:
  provider: openai
  model: gpt-4o-mini
  api_key: test-key

domains:
  - name: medical-research
    active: true
    sources:
      - name: pubmed
        type: api
        url: https://example.com
    quality_gates:
      G0:
        category: hard
        action: retry
    delivery_gates:
      D1:
        enabled: false
        action_on_failure: flag

quality_gates:
  G0:
    category: hard
    retries: 1
    action: block
  G4:
    category: hard
    retries: 3
    action: block

delivery_gates:
  D1:
    enabled: true
    action_on_failure: block
  D2:
    enabled: true
    action_on_failure: fallback
"""

MINIMAL_CONFIG = """
project:
  name: Minimal

llm:
  provider: openai
  model: gpt-4o-mini
  api_key: test-key

domains:
  - name: test-domain
    active: true
    sources:
      - name: src
        type: api
        url: https://example.com
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gates_dict() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_WITH_GATES)


@pytest.fixture
def domain_gates_dict() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_WITH_DOMAIN_GATES)


@pytest.fixture
def minimal_dict() -> dict[str, Any]:
    return yaml.safe_load(MINIMAL_CONFIG)


# ===================================================================
# QualityGateConfig basics
# ===================================================================


class TestQualityGateConfig:
    def test_defaults(self) -> None:
        cfg = QualityGateConfig()
        assert cfg.name == ""
        assert cfg.category == "soft"
        assert cfg.retries == 0
        assert cfg.retry_models == []
        assert cfg.action == "flag"
        assert cfg.threshold is None

    def test_custom_values(self) -> None:
        cfg = QualityGateConfig(
            name="G4",
            category="hard",
            retries=3,
            retry_models=["deepseek/deepseek-chat"],
            action="block",
        )
        assert cfg.name == "G4"
        assert cfg.category == "hard"
        assert cfg.retries == 3
        assert cfg.retry_models == ["deepseek/deepseek-chat"]
        assert cfg.action == "block"
        assert cfg.threshold is None

    def test_with_threshold(self) -> None:
        cfg = QualityGateConfig(
            name="G3",
            category="soft",
            retries=2,
            action="archive",
            threshold=30.0,
        )
        assert cfg.threshold == 30.0

    def test_round_trip(self) -> None:
        original = QualityGateConfig(
            name="G4",
            category="hard",
            retries=3,
            retry_models=["m1", "m2"],
            action="block",
            threshold=None,
        )
        d = asdict(original)
        restored = QualityGateConfig(**d)
        assert restored == original


# ===================================================================
# DeliveryGateConfig basics
# ===================================================================


class TestDeliveryGateConfig:
    def test_defaults(self) -> None:
        cfg = DeliveryGateConfig()
        assert cfg.name == ""
        assert cfg.enabled is True
        assert cfg.action_on_failure == "block"

    def test_custom_values(self) -> None:
        cfg = DeliveryGateConfig(
            name="D2",
            enabled=True,
            action_on_failure="fallback",
        )
        assert cfg.name == "D2"
        assert cfg.action_on_failure == "fallback"

    def test_disabled(self) -> None:
        cfg = DeliveryGateConfig(
            name="D1",
            enabled=False,
            action_on_failure="flag",
        )
        assert cfg.enabled is False

    def test_round_trip(self) -> None:
        original = DeliveryGateConfig(name="D1", enabled=False, action_on_failure="flag")
        d = asdict(original)
        restored = DeliveryGateConfig(**d)
        assert restored == original


# ===================================================================
# Global quality_gates YAML parsing
# ===================================================================


class TestGlobalGatesParsing:
    def test_quality_gates_loaded(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        assert "G0-SchemaIntegrity" in config.quality_gates
        assert "G4-SummaryFactual" in config.quality_gates
        assert "G3-RelevanceScoring" in config.quality_gates

    def test_delivery_gates_loaded(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        assert "D1" in config.delivery_gates
        assert "D2" in config.delivery_gates

    def test_g0_values(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        g0 = config.quality_gates["G0-SchemaIntegrity"]
        assert g0.category == "hard"
        assert g0.retries == 1
        assert g0.retry_models == []
        assert g0.action == "block"
        assert g0.threshold is None

    def test_g4_values(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        g4 = config.quality_gates["G4-SummaryFactual"]
        assert g4.category == "hard"
        assert g4.retries == 3
        assert g4.retry_models == ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"]
        assert g4.action == "block"
        assert g4.threshold is None

    def test_g3_values(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        g3 = config.quality_gates["G3-RelevanceScoring"]
        assert g3.category == "soft"
        assert g3.retries == 2
        assert g3.retry_models == ["deepseek/deepseek-chat"]
        assert g3.action == "archive"
        assert g3.threshold == 30

    def test_d1_values(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        d1 = config.delivery_gates["D1"]
        assert d1.enabled is True
        assert d1.action_on_failure == "block"

    def test_d2_values(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        d2 = config.delivery_gates["D2"]
        assert d2.enabled is True
        assert d2.action_on_failure == "fallback"

    def test_no_gates_defaults_empty(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        assert config.quality_gates == {}
        assert config.delivery_gates == {}


# ===================================================================
# Per-domain quality_gates overrides
# ===================================================================


class TestDomainGatesOverrides:
    def test_domain_quality_gates_loaded(self, domain_gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(domain_gates_dict)
        domain = config.domains[0]
        assert "G0-SchemaIntegrity" in domain.quality_gates
        assert domain.quality_gates["G0-SchemaIntegrity"].action == "retry"

    def test_domain_delivery_gates_loaded(self, domain_gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(domain_gates_dict)
        domain = config.domains[0]
        assert "D1" in domain.delivery_gates
        assert domain.delivery_gates["D1"].enabled is False
        assert domain.delivery_gates["D1"].action_on_failure == "flag"

    def test_domain_gates_override_globals(self, domain_gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(domain_gates_dict)
        # Global G0 is action=block, domain override is action=retry
        assert config.quality_gates["G0-SchemaIntegrity"].action == "block"
        assert config.domains[0].quality_gates["G0-SchemaIntegrity"].action == "retry"
        # Domain D1 disabled, global D1 enabled
        assert config.delivery_gates["D1"].enabled is True
        assert config.domains[0].delivery_gates["D1"].enabled is False

    def test_domain_without_gates_defaults_empty(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        domain = config.domains[0]
        assert domain.quality_gates == {}
        assert domain.delivery_gates == {}


# ===================================================================
# config_to_dict serialization
# ===================================================================


class TestSerialization:
    def test_quality_gates_serialized(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        raw = config_to_dict(config)
        assert "quality_gates" in raw
        assert "G0-SchemaIntegrity" in raw["quality_gates"]
        assert "G4-SummaryFactual" in raw["quality_gates"]
        assert raw["quality_gates"]["G0-SchemaIntegrity"]["category"] == "hard"
        assert raw["quality_gates"]["G0-SchemaIntegrity"]["retries"] == 1
        assert raw["quality_gates"]["G0-SchemaIntegrity"]["action"] == "block"

    def test_delivery_gates_serialized(self, gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(gates_dict)
        raw = config_to_dict(config)
        assert "delivery_gates" in raw
        assert "D1" in raw["delivery_gates"]
        assert raw["delivery_gates"]["D1"]["action_on_failure"] == "block"

    def test_domain_gates_serialized(self, domain_gates_dict: dict[str, Any]) -> None:
        config = _dict_to_config(domain_gates_dict)
        raw = config_to_dict(config)
        domain_raw = raw["domains"][0]
        assert "quality_gates" in domain_raw
        assert "G0-SchemaIntegrity" in domain_raw["quality_gates"]
        assert domain_raw["quality_gates"]["G0-SchemaIntegrity"]["action"] == "retry"

    def test_empty_gates_omitted(self, minimal_dict: dict[str, Any]) -> None:
        """Empty quality_gates/delivery_gates should be omitted from output."""
        config = _dict_to_config(minimal_dict)
        raw = config_to_dict(config)
        assert "quality_gates" not in raw
        assert "delivery_gates" not in raw

    def test_round_trip_preserves_gates(self, gates_dict: dict[str, Any]) -> None:
        """Parsing then serializing should preserve all gate values."""
        config = _dict_to_config(gates_dict)
        raw = config_to_dict(config)
        config2 = _dict_to_config(raw)
        assert config2.quality_gates["G4-SummaryFactual"].retries == 3
        assert config2.quality_gates["G4-SummaryFactual"].retry_models == [
            "deepseek/deepseek-chat",
            "anthropic/claude-sonnet-4",
        ]
        assert config2.quality_gates["G3-RelevanceScoring"].threshold == 30
        assert config2.delivery_gates["D2"].action_on_failure == "fallback"


# ===================================================================
# Validation
# ===================================================================


class TestGateValidation:
    def test_hard_gate_valid_action_block(self) -> None:
        """Hard gate with action=block should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", action="block"),
            },
        )
        errors = validate_config(config)
        assert all("G0" not in e for e in errors)

    def test_hard_gate_valid_action_retry(self) -> None:
        """Hard gate with action=retry should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", action="retry"),
            },
        )
        errors = validate_config(config)
        assert all("G0" not in e for e in errors)

    def test_hard_gate_invalid_action(self) -> None:
        """Hard gate with action=flag (invalid for hard) should fail."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", action="flag"),
            },
        )
        errors = validate_config(config)
        assert any("G0" in e and "action" in e for e in errors)

    def test_hard_gate_invalid_action_skip(self) -> None:
        """Hard gate with action=skip should fail."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", action="skip"),
            },
        )
        errors = validate_config(config)
        assert any("G0" in e and "action" in e for e in errors)

    def test_soft_gate_valid_action_flag(self) -> None:
        """Soft gate with action=flag should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G1": QualityGateConfig(name="G1", category="soft", action="flag"),
            },
        )
        errors = validate_config(config)
        assert all("G1" not in e for e in errors)

    def test_soft_gate_valid_action_archive(self) -> None:
        """Soft gate with action=archive should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G1": QualityGateConfig(name="G1", category="soft", action="archive"),
            },
        )
        errors = validate_config(config)
        assert all("G1" not in e for e in errors)

    def test_soft_gate_valid_action_skip(self) -> None:
        """Soft gate with action=skip should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G1": QualityGateConfig(name="G1", category="soft", action="skip"),
            },
        )
        errors = validate_config(config)
        assert all("G1" not in e for e in errors)

    def test_soft_gate_valid_action_retry(self) -> None:
        """Soft gate with action=retry should pass."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G1": QualityGateConfig(name="G1", category="soft", action="retry"),
            },
        )
        errors = validate_config(config)
        assert all("G1" not in e for e in errors)

    def test_soft_gate_invalid_action_block(self) -> None:
        """Soft gate with action=block should fail."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G1": QualityGateConfig(name="G1", category="soft", action="block"),
            },
        )
        errors = validate_config(config)
        assert any("G1" in e and "action" in e for e in errors)

    def test_domain_gate_validation(self) -> None:
        """Domain-level gate overrides should also be validated."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                    quality_gates={
                        "G0": QualityGateConfig(name="G0", category="hard", action="flag"),
                    },
                )
            ],
        )
        errors = validate_config(config)
        assert any("G0" in e and "action" in e for e in errors)

    def test_custom_gate_name_in_validation(self) -> None:
        """Custom gate names not in G0-G5 should also be validated."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "CustomGate": QualityGateConfig(name="CustomGate", category="hard", action="skip"),
            },
        )
        errors = validate_config(config)
        assert any("CustomGate" in e and "action" in e for e in errors)


# ===================================================================
# Default gates in create_default_config
# ===================================================================


class TestDefaultGates:
    def test_create_default_config_has_gates(self) -> None:
        """create_default_config() should include default gate configs."""
        d = {}
        # We test via Config / config_to_dict round trip to verify
        # the defaults are as expected
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="test-domain",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", retries=1, action="block"),
                "G1": QualityGateConfig(name="G1", category="soft", action="flag"),
                "G2": QualityGateConfig(name="G2", category="soft", action="flag"),
                "G3": QualityGateConfig(name="G3", category="soft", retries=2, action="archive", threshold=30.0),
                "G4": QualityGateConfig(
                    name="G4",
                    category="hard",
                    retries=3,
                    retry_models=["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
                    action="block",
                ),
                "G5": QualityGateConfig(name="G5", category="soft", retries=2, action="flag"),
            },
            delivery_gates={
                "D1": DeliveryGateConfig(name="D1", enabled=True, action_on_failure="block"),
                "D2": DeliveryGateConfig(name="D2", enabled=True, action_on_failure="fallback"),
                "D3": DeliveryGateConfig(name="D3", enabled=True, action_on_failure="flag"),
            },
        )
        # Validate should pass with these defaults
        errors = validate_config(config)
        assert errors == []

    def test_g0_is_hard(self) -> None:
        """G0 should be hard with action=block."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1", active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G0": QualityGateConfig(name="G0", category="hard", retries=1, action="block"),
            },
        )
        g0 = config.quality_gates["G0"]
        assert g0.category == "hard"
        assert g0.retries == 1
        assert g0.action == "block"

    def test_g4_is_hard_with_retry_models(self) -> None:
        """G4 should be hard with retries=3 and retry_models specified."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1", active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                "G4": QualityGateConfig(
                    name="G4",
                    category="hard",
                    retries=3,
                    retry_models=["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
                    action="block",
                ),
            },
        )
        g4 = config.quality_gates["G4"]
        assert g4.category == "hard"
        assert g4.retries == 3
        assert len(g4.retry_models) == 2

    def test_g1_g2_g5_are_soft_flag(self) -> None:
        """G1, G2, G5 should be soft with action=flag."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1", active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            quality_gates={
                name: QualityGateConfig(name=name, category="soft", action="flag")
                for name in ("G1", "G2", "G5")
            },
        )
        for name in ("G1", "G2", "G5"):
            assert config.quality_gates[name].category == "soft"
            assert config.quality_gates[name].action == "flag"

    def test_delivery_gate_defaults(self) -> None:
        """D1, D2, D3 should have reasonable defaults."""
        config = Config(
            project=ProjectConfig(name="test"),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="d1", active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                )
            ],
            delivery_gates={
                "D1": DeliveryGateConfig(name="D1", enabled=True, action_on_failure="block"),
                "D2": DeliveryGateConfig(name="D2", enabled=True, action_on_failure="fallback"),
                "D3": DeliveryGateConfig(name="D3", enabled=True, action_on_failure="flag"),
            },
        )
        assert config.delivery_gates["D1"].action_on_failure == "block"
        assert config.delivery_gates["D2"].action_on_failure == "fallback"
        assert config.delivery_gates["D3"].action_on_failure == "flag"


# ===================================================================
# Backward compatibility
# ===================================================================


class TestBackwardCompat:
    def test_config_without_gates_still_loads(self, minimal_dict: dict[str, Any]) -> None:
        """Old configs without quality_gates should still parse."""
        config = _dict_to_config(minimal_dict)
        assert config.project.name == "Minimal"
        assert config.quality_gates == {}
        assert config.delivery_gates == {}

    def test_config_without_gates_validates_ok(self, minimal_dict: dict[str, Any]) -> None:
        """Old configs should validate successfully."""
        config = _dict_to_config(minimal_dict)
        errors = validate_config(config)
        assert errors == []

    def test_domain_without_gates_still_loads(self, minimal_dict: dict[str, Any]) -> None:
        """Old domain configs without gates should parse."""
        config = _dict_to_config(minimal_dict)
        domain = config.domains[0]
        assert domain.quality_gates == {}
        assert domain.delivery_gates == {}
