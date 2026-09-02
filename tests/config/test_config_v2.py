"""Tests for config schema v2 extensions.

Covers: LLMTaskConfig, llm.tasks, llm.fallback, domain.extract_fields,
domain.search_mode, get_effective_llm_config(), and backward compatibility
with v0.1 configs.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from autoinfo.config import (
    Config,
    DomainConfig,
    LLMConfig,
    LLMTaskConfig,
    ProjectConfig,
    SourceConfig,
    TopicConfig,
    _dict_to_config,
    _resolve_task_llm_config,
    config_to_dict,
    get_effective_llm_config,
    load_config,
    validate_config,
)

# ---------------------------------------------------------------------------
# Sample YAML configs
# ---------------------------------------------------------------------------

V2_CONFIG_YAML = """
project:
  name: Test Project v2
  created_at: "2026-07-20"

llm:
  provider: openai
  model: gpt-4o-mini
  api_key: "${AUTOINFO_LLM_API_KEY}"
  tasks:
    extraction:
      model: deepseek/deepseek-chat
      max_tokens: 2000
    summarization:
      provider: anthropic
      model: claude-sonnet-4-20250514
  fallback:
    - provider: openrouter
      model: anthropic/claude-sonnet-4
      api_key: "${FALLBACK_API_KEY}"
    - provider: openai
      model: gpt-4o

domains:
  - name: medical-research
    active: true
    sources:
      - name: pubmed
        type: api
        url: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
        quality_tier: 1
    topics:
      - name: IVF breakthroughs
        keywords: ["IVF", "embryo"]
    extract_fields:
      - title
      - abstract
      - authors
    search_mode: hybrid
"""

V1_CONFIG_YAML = """
project:
  name: Legacy Project
  created_at: "2026-01-01"

llm:
  provider: openai
  model: gpt-4o-mini
  api_key: "sk-legacy"

domains:
  - name: legacy-domain
    active: true
    sources:
      - name: test-source
        type: api
        url: https://example.com/api
        quality_tier: 1
    topics:
      - name: Test Topic
        keywords: ["test"]
"""

MINIMAL_V2_CONFIG = """
project:
  name: Minimal Config

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
def v2_dict() -> dict[str, Any]:
    return yaml.safe_load(V2_CONFIG_YAML)


@pytest.fixture
def v1_dict() -> dict[str, Any]:
    return yaml.safe_load(V1_CONFIG_YAML)


@pytest.fixture
def minimal_dict() -> dict[str, Any]:
    return yaml.safe_load(MINIMAL_V2_CONFIG)


# ---------------------------------------------------------------------------
# LLMTaskConfig basics
# ---------------------------------------------------------------------------


class TestLLMTaskConfig:
    def test_defaults(self) -> None:
        cfg = LLMTaskConfig()
        assert cfg.model == ""
        assert cfg.provider == ""
        assert cfg.max_tokens == 0

    def test_custom_values(self) -> None:
        cfg = LLMTaskConfig(model="deepseek/deepseek-chat", provider="", max_tokens=2000)
        assert cfg.model == "deepseek/deepseek-chat"
        assert cfg.max_tokens == 2000

    def test_round_trip(self) -> None:
        original = LLMTaskConfig(model="gpt-4", provider="openai", max_tokens=4096)
        d = asdict(original)
        restored = LLMTaskConfig(**d)
        assert restored == original


# ---------------------------------------------------------------------------
# Parsing: llm.tasks
# ---------------------------------------------------------------------------


class TestTasksParsing:
    def test_tasks_section_loaded(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        assert "extraction" in config.llm.tasks
        assert "summarization" in config.llm.tasks

    def test_extraction_task_values(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        task = config.llm.tasks["extraction"]
        assert task.model == "deepseek/deepseek-chat"
        assert task.provider == ""
        assert task.max_tokens == 2000

    def test_summarization_task_values(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        task = config.llm.tasks["summarization"]
        assert task.model == "claude-sonnet-4-20250514"
        assert task.provider == "anthropic"
        assert task.max_tokens == 0

    def test_no_tasks_defaults_empty(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        assert config.llm.tasks == {}


# ---------------------------------------------------------------------------
# Parsing: llm.fallback
# ---------------------------------------------------------------------------


class TestFallbackParsing:
    def test_fallback_chain_parsed(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        assert len(config.llm.fallback) == 2

    def test_first_fallback_values(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        fb = config.llm.fallback[0]
        assert fb.provider == "openrouter"
        assert fb.model == "anthropic/claude-sonnet-4"
        assert fb.api_key == "${FALLBACK_API_KEY}"

    def test_second_fallback_values(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        fb = config.llm.fallback[1]
        assert fb.provider == "openai"
        assert fb.model == "gpt-4o"
        assert fb.api_key == ""

    def test_no_fallback_defaults_empty(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        assert config.llm.fallback == []


# ---------------------------------------------------------------------------
# Parsing: domain.extract_fields & search_mode
# ---------------------------------------------------------------------------


class TestDomainExtensions:
    def test_extract_fields_parsed(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        domain = config.domains[0]
        assert domain.extract_fields == ["title", "abstract", "authors"]

    def test_search_mode_hybrid(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        domain = config.domains[0]
        assert domain.search_mode == "hybrid"

    def test_default_search_mode(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        domain = config.domains[0]
        assert domain.search_mode == "keyword"

    def test_default_extract_fields(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        domain = config.domains[0]
        assert domain.extract_fields == []


# ---------------------------------------------------------------------------
# Parsing: source requires_key (D4 requirement awareness)
# ---------------------------------------------------------------------------


class TestSourceRequiresKey:
    def test_requires_key_parsed_from_yaml(self) -> None:
        raw = yaml.safe_load(
            """
            domains:
              - name: d
                active: true
                sources:
                  - name: ap
                    type: ap_api
                    url: https://api.example.com
                    requires_key: true
            """
        )
        config = _dict_to_config(raw)
        assert config.domains[0].sources[0].requires_key is True

    def test_requires_key_false_parsed(self) -> None:
        raw = yaml.safe_load(
            """
            domains:
              - name: d
                active: true
                sources:
                  - name: rss
                    type: rss
                    url: https://example.com/feed
                    requires_key: false
            """
        )
        config = _dict_to_config(raw)
        assert config.domains[0].sources[0].requires_key is False

    def test_requires_key_defaults_false_when_absent(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        assert config.domains[0].sources[0].requires_key is False

    def test_requires_key_string_value_coerced(self) -> None:
        raw = yaml.safe_load(
            """
            domains:
              - name: d
                active: true
                sources:
                  - name: ap
                    type: ap_api
                    url: https://api.example.com
                    requires_key: "true"
            """
        )
        config = _dict_to_config(raw)
        assert config.domains[0].sources[0].requires_key is True

    def test_requires_key_does_not_leak_into_settings(self) -> None:
        raw = yaml.safe_load(
            """
            domains:
              - name: d
                active: true
                sources:
                  - name: ap
                    type: ap_api
                    url: https://api.example.com
                    requires_key: true
                    rate_limit: 10
            """
        )
        config = _dict_to_config(raw)
        source = config.domains[0].sources[0]
        assert "requires_key" not in source.settings
        assert source.settings["rate_limit"] == 10

    def test_config_to_dict_round_trip_preserves_requires_key(self) -> None:
        raw = yaml.safe_load(
            """
            domains:
              - name: d
                active: true
                sources:
                  - name: ap
                    type: ap_api
                    url: https://api.example.com
                    requires_key: true
                  - name: rss
                    type: rss
                    url: https://example.com/feed
            """
        )
        config = _dict_to_config(raw)
        dumped = config_to_dict(config)
        dumped_sources = dumped["domains"][0]["sources"]
        assert dumped_sources[0]["requires_key"] is True
        assert "requires_key" not in dumped_sources[1]
        restored = _dict_to_config(dumped)
        assert restored.domains[0].sources[0].requires_key is True
        assert restored.domains[0].sources[1].requires_key is False


# ---------------------------------------------------------------------------
# get_effective_llm_config
# ---------------------------------------------------------------------------


class TestGetEffectiveLLMConfig:
    def test_unknown_task_returns_base(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "nonexistent")
        assert effective.model == "gpt-4o-mini"
        assert effective.provider == "openai"

    def test_empty_task_returns_base(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "")
        assert effective.model == "gpt-4o-mini"

    def test_extraction_task_overrides_model(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "extraction")
        assert effective.model == "deepseek/deepseek-chat"
        assert effective.provider == "openai"

    def test_summarization_task_overrides_provider_and_model(
        self, v2_dict: dict[str, Any]
    ) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "summarization")
        assert effective.model == "claude-sonnet-4-20250514"
        assert effective.provider == "anthropic"

    def test_task_keeps_base_api_key(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "extraction")
        assert effective.api_key == "${AUTOINFO_LLM_API_KEY}"

    def test_task_keeps_fallback_chain(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        effective = _resolve_task_llm_config(config, "extraction")
        assert len(effective.fallback) == 2
        assert effective.fallback[0].model == "anthropic/claude-sonnet-4"

    def test_no_tasks_returns_base(self, minimal_dict: dict[str, Any]) -> None:
        config = _dict_to_config(minimal_dict)
        effective = _resolve_task_llm_config(config, "anything")
        assert effective is config.llm


# ---------------------------------------------------------------------------
# Backward compatibility: old v0.1 configs still load
# ---------------------------------------------------------------------------


class TestPublicEffectiveLLMConfig:
    """Tests for the public ``get_effective_llm_config()`` (dict-based API)."""

    def test_returns_base_without_task(self, tmp_path: Path) -> None:
        cfg = {
            "project": {"name": "test", "created_at": ""},
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "test-key",
                "tasks": {"extraction": {"model": "deepseek/deepseek-chat", "max_tokens": 2000}},
            },
            "domains": [],
        }
        config_path = tmp_path / ".autoinfo"
        config_path.mkdir()
        yaml_path = config_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f)

        # Patch get_config_path to return our temp config
        import autoinfo.config as cfg_mod

        original = cfg_mod.get_config_path
        try:
            cfg_mod.get_config_path = lambda: yaml_path  # type: ignore[method-assign]
            result = get_effective_llm_config(task=None)
            assert result["task"] == "default"
            assert result["model"] == "gpt-4o-mini"
            assert result["provider"] == "openai"
            assert result["max_tokens"] == 0
            assert result["fallback_chain"] == []
        finally:
            cfg_mod.get_config_path = original

    def test_task_override_in_dict(self, tmp_path: Path) -> None:
        cfg = {
            "project": {"name": "test", "created_at": ""},
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "test-key",
                "tasks": {"extraction": {"model": "deepseek/deepseek-chat", "max_tokens": 2000}},
                "fallback": [{"provider": "openrouter", "model": "claude-4"}],
            },
            "domains": [],
        }
        config_path = tmp_path / ".autoinfo"
        config_path.mkdir()
        yaml_path = config_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f)

        import autoinfo.config as cfg_mod

        original = cfg_mod.get_config_path
        try:
            cfg_mod.get_config_path = lambda: yaml_path  # type: ignore[method-assign]
            result = get_effective_llm_config(task="extraction")
            assert result["task"] == "extraction"
            assert result["model"] == "deepseek/deepseek-chat"
            assert result["max_tokens"] == 2000
            assert len(result["fallback_chain"]) == 1
            assert result["fallback_chain"][0]["model"] == "claude-4"
        finally:
            cfg_mod.get_config_path = original


class TestBackwardCompat:
    def test_v1_config_loads(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        assert config.project.name == "Legacy Project"
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o-mini"
        assert len(config.domains) == 1

    def test_v1_config_has_default_tasks(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        assert config.llm.tasks == {}

    def test_v1_config_has_default_fallback(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        assert config.llm.fallback == []

    def test_v1_config_has_default_search_mode(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        assert config.domains[0].search_mode == "keyword"

    def test_v1_config_has_default_extract_fields(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        assert config.domains[0].extract_fields == []

    def test_v1_config_validates_ok(self, v1_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v1_dict)
        errors = validate_config(config)
        assert errors == []

    def test_v2_config_validates_ok(self, v2_dict: dict[str, Any]) -> None:
        config = _dict_to_config(v2_dict)
        errors = validate_config(config)
        assert errors == []

    def test_file_load_v1_config(self, tmp_path: Path, v1_dict: dict[str, Any]) -> None:
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(v1_dict, f)
        config = load_config(config_path)
        assert config.llm.tasks == {}


# ---------------------------------------------------------------------------
# Dataclass round-trip (to_dict / from_dict)
# ---------------------------------------------------------------------------


class TestDataclassRoundTrip:
    def test_llm_task_config_round_trip(self) -> None:
        d = {"model": "gpt-4", "provider": "openai", "max_tokens": 4096}
        obj = LLMTaskConfig(**d)
        assert asdict(obj) == d

    def test_llm_config_round_trip(self) -> None:
        tasks = {
            "extraction": LLMTaskConfig(model="deepseek/deepseek-chat", max_tokens=2000),
        }
        fallback = [LLMConfig(provider="openrouter", model="claude-sonnet-4")]
        original = LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
            fallback=fallback,
            tasks=tasks,
        )
        d = asdict(original)
        restored = LLMConfig(
            provider=d["provider"],
            model=d["model"],
            api_key=d["api_key"],
            fallback=[LLMConfig(**fb) for fb in d["fallback"]],
            tasks={k: LLMTaskConfig(**v) for k, v in d["tasks"].items()},
        )
        assert restored.provider == original.provider
        assert restored.model == original.model
        assert restored.fallback[0].model == "claude-sonnet-4"
        assert restored.tasks["extraction"].max_tokens == 2000

    def test_domain_config_round_trip(self) -> None:
        source = SourceConfig(name="pubmed", type="api", url="https://example.com")
        topic = TopicConfig(name="test", keywords=["a", "b"])
        original = DomainConfig(
            name="test-domain",
            active=True,
            sources=[source],
            topics=[topic],
            extract_fields=["title", "abstract"],
            search_mode="hybrid",
        )
        d = asdict(original)
        restored = DomainConfig(
            name=d["name"],
            active=d["active"],
            sources=[SourceConfig(**s) for s in d["sources"]],
            topics=[TopicConfig(**t) for t in d["topics"]],
            extract_fields=d["extract_fields"],
            search_mode=d["search_mode"],
        )
        assert restored.extract_fields == ["title", "abstract"]
        assert restored.search_mode == "hybrid"

    def test_config_round_trip(self) -> None:
        original = Config(
            project=ProjectConfig(name="test", created_at=""),
            llm=LLMConfig(
                provider="openai",
                model="gpt-4o-mini",
                api_key="key",
                fallback=[LLMConfig(provider="openrouter", model="claude-4")],
                tasks={"x": LLMTaskConfig(model="m", max_tokens=100)},
            ),
            domains=[
                DomainConfig(
                    name="d1",
                    extract_fields=["title"],
                    search_mode="hybrid",
                )
            ],
        )
        d = asdict(original)
        assert d["llm"]["tasks"]["x"]["max_tokens"] == 100
        assert d["llm"]["fallback"][0]["model"] == "claude-4"
        assert d["domains"][0]["search_mode"] == "hybrid"
        assert d["domains"][0]["extract_fields"] == ["title"]

    def test_config_to_dict_preserves_llm_base_url_and_fallback(self) -> None:
        """#155: save_config must not drop llm.base_url / fallback base_url+api_key.

        Regression: config_to_dict wrote llm.fallback twice — the second pass
        overwrote the full serialization with a reduced dict that omitted
        ``base_url`` and ``api_key``, silently wiping them on every save.
        """
        original = Config(
            project=ProjectConfig(name="test", created_at=""),
            llm=LLMConfig(
                provider="openai",
                model="deepseek-v4-flash",
                api_key="primary-key",
                base_url="https://opencode.ai/zen/go/v1",
                fallback=[
                    LLMConfig(
                        provider="openai",
                        model="mimo-v2.5",
                        api_key="fb-key",
                        base_url="https://opencode.ai/zen/go/v1",
                    )
                ],
            ),
        )
        d = config_to_dict(original)
        assert d["llm"]["base_url"] == "https://opencode.ai/zen/go/v1"
        fb = d["llm"]["fallback"][0]
        assert fb["model"] == "mimo-v2.5"
        assert fb["base_url"] == "https://opencode.ai/zen/go/v1"
        assert fb["api_key"] == "fb-key"


# ---------------------------------------------------------------------------
# Validation edge cases
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_search_mode(self) -> None:
        config = Config(
            project=ProjectConfig(name="test", created_at=""),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="test-domain",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                    search_mode="vector",
                )
            ],
        )
        errors = validate_config(config)
        assert any("search_mode" in e for e in errors)

    def test_valid_keyword_mode(self) -> None:
        config = Config(
            project=ProjectConfig(name="test", created_at=""),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="test-domain",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                    search_mode="keyword",
                )
            ],
        )
        errors = validate_config(config)
        assert all("search_mode" not in e for e in errors)

    def test_valid_hybrid_mode(self) -> None:
        config = Config(
            project=ProjectConfig(name="test", created_at=""),
            llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="key"),
            domains=[
                DomainConfig(
                    name="test-domain",
                    active=True,
                    sources=[SourceConfig(name="s", type="api", url="https://x.com")],
                    search_mode="hybrid",
                )
            ],
        )
        errors = validate_config(config)
        assert all("search_mode" not in e for e in errors)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_tasks_with_empty_config(self) -> None:
        """A task entry with no keys should produce defaults."""
        raw = {
            "project": {"name": "test", "created_at": ""},
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "key",
                "tasks": {"extraction": None},
            },
            "domains": [],
        }
        config = _dict_to_config(raw)
        assert config.llm.tasks["extraction"].model == ""

    def test_fallback_with_missing_fields(self) -> None:
        """Fallback entries with partial data should still parse."""
        raw = {
            "project": {"name": "test", "created_at": ""},
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "key",
                "fallback": [{"model": "gpt-4"}],  # no provider
            },
            "domains": [],
        }
        config = _dict_to_config(raw)
        assert len(config.llm.fallback) == 1
        assert config.llm.fallback[0].model == "gpt-4"
        assert config.llm.fallback[0].provider == ""

    def test_empty_domain_extract_fields(self) -> None:
        """Empty extract_fields list should be preserved."""
        raw = {
            "project": {"name": "test", "created_at": ""},
            "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "key"},
            "domains": [
                {
                    "name": "d1",
                    "active": True,
                    "sources": [{"name": "s", "type": "api", "url": "https://x.com"}],
                    "extract_fields": [],
                }
            ],
        }
        config = _dict_to_config(raw)
        assert config.domains[0].extract_fields == []


class TestDefaultQualityGates:
    """Issue #170: default quality gates fallback (LLM retries on G3)."""

    def test_default_gates_have_canonical_keys_and_llm_retries(self) -> None:
        from autoinfo.config import default_quality_gates

        gates = default_quality_gates()
        assert "G3-RelevanceScoring" in gates
        g3 = gates["G3-RelevanceScoring"]
        assert g3.retries >= 2, "G3 default must keep LLM retries (#170)"
        assert g3.threshold == 30
        assert "G4-SummaryFactual" in gates
        assert gates["G4-SummaryFactual"].retries >= 3

    def test_create_default_config_matches_default_gates(self) -> None:
        from autoinfo.config import create_default_config, _DEFAULT_QUALITY_GATES

        cfg = create_default_config("test-domain")
        assert cfg["quality_gates"] == _DEFAULT_QUALITY_GATES
