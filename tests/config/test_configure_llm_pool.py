"""Tests for the ``configure_llm`` MCP tool's ``llm_fallback`` / ``llm_tasks`` params.

Covers the write path of ``_handle_configure_llm`` (server.py): fallback
merge + dedup keyed on ``(provider or primary, model)``, per-task routing
via ``_resolve_task_llm_config``, judgment-task pinning (``JUDGMENT_MODEL``
is release-level and must NOT be overridable via ``llm.tasks``), the
``None``-vs-``[]`` clear semantics, validate-before-write (mtime unchanged
on failure), and the ``${ENV}`` round-trip trap (``load_config`` resolves
env references, so field-fidelity assertions must not compare the raw
placeholder after loading).

All tests run against a tmp_path config so the repository's runtime
``.autoinfo/config.yaml`` is never touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from autoinfo.config import (
    JUDGMENT_MODEL,
    JUDGMENT_TASKS,
    _resolve_task_llm_config,
    get_effective_llm_config,
    load_config,
)
from autoinfo.mcp.errors import ErrorCode
from autoinfo.mcp.server import _handle_configure_llm

OPENGATE_BASE_URL = "https://opencode.ai/zen/go/v1"
PRIMARY_MODEL = "deepseek-v4-flash"
PRIMARY_PROVIDER = "openai"

# Exact bytes of the base config written by ``_write_base_config`` — used by
# ``_assert_file_untouched`` to prove a failed validation never touched disk.
_BASE_CONFIG_BYTES: bytes | None = None


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """chdir into a tmp dir so ``_config_path()`` resolves to tmp/.autoinfo/config.yaml."""
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".autoinfo"
    cfg_dir.mkdir()
    return cfg_dir


def _write_base_config(cfg_dir: Path) -> Path:
    """Write a base config (provider/model/api_key/base_url) and return its path."""
    global _BASE_CONFIG_BYTES
    cfg = {
        "project": {"name": "test", "created_at": ""},
        "llm": {
            "provider": PRIMARY_PROVIDER,
            "model": PRIMARY_MODEL,
            "api_key": "${AUTOINFO_LLM_API_KEY}",
            "base_url": OPENGATE_BASE_URL,
        },
        "domains": [],
    }
    path = cfg_dir / "config.yaml"
    text = yaml.safe_dump(cfg, sort_keys=False)
    _BASE_CONFIG_BYTES = text.encode("utf-8")
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy path — fallback write + field fidelity
# ---------------------------------------------------------------------------


def test_fallback_entry_written_with_field_fidelity(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fallback entry survives the write and the load_config round-trip."""
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test")
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(
        llm_fallback=[{"model": "mimo-v2.5", "base_url": OPENGATE_BASE_URL}]
    )

    assert result["success"] is True
    assert result["data"]["status"] == "success"

    loaded = load_config(config_path)
    assert len(loaded.llm.fallback) == 1
    fb = loaded.llm.fallback[0]
    assert fb.model == "mimo-v2.5"
    assert fb.base_url == OPENGATE_BASE_URL
    # Empty provider/api_key: inheritance happens at consumption time
    # (llm.py call_with_fallback), not at write time.
    assert fb.provider == ""
    assert fb.api_key == ""
    # Primary untouched
    assert loaded.llm.model == PRIMARY_MODEL
    assert loaded.llm.provider == PRIMARY_PROVIDER
    # ${ENV} reference survives in the raw YAML text (bypasses load_config)
    raw = config_path.read_text(encoding="utf-8")
    assert "${AUTOINFO_LLM_API_KEY}" in raw
    assert "mimo-v2.5" in raw


def test_same_model_second_call_does_not_duplicate(config_dir: Path) -> None:
    """Re-writing the same (provider, model) identity merges, never appends."""
    config_path = _write_base_config(config_dir)

    _handle_configure_llm(
        llm_fallback=[{"model": "mimo-v2.5", "base_url": OPENGATE_BASE_URL}]
    )
    _handle_configure_llm(
        llm_fallback=[{"model": "mimo-v2.5", "base_url": OPENGATE_BASE_URL}]
    )

    loaded = load_config(config_path)
    assert len(loaded.llm.fallback) == 1
    assert loaded.llm.fallback[0].model == "mimo-v2.5"


def test_same_model_call_updates_fields(config_dir: Path) -> None:
    """Same (provider, model) identity with new fields updates in place."""
    config_path = _write_base_config(config_dir)

    _handle_configure_llm(
        llm_fallback=[{"model": "mimo-v2.5", "base_url": OPENGATE_BASE_URL}]
    )
    _handle_configure_llm(
        llm_fallback=[
            {"model": "mimo-v2.5", "base_url": "https://new.example.com/v1"}
        ]
    )

    loaded = load_config(config_path)
    assert len(loaded.llm.fallback) == 1
    assert loaded.llm.fallback[0].base_url == "https://new.example.com/v1"


def test_different_model_appends(config_dir: Path) -> None:
    """A different (provider, model) identity appends a new entry."""
    config_path = _write_base_config(config_dir)

    _handle_configure_llm(llm_fallback=[{"model": "mimo-v2.5"}])
    _handle_configure_llm(llm_fallback=[{"model": "gpt-4o"}])

    loaded = load_config(config_path)
    assert len(loaded.llm.fallback) == 2
    assert {fb.model for fb in loaded.llm.fallback} == {"mimo-v2.5", "gpt-4o"}


# ---------------------------------------------------------------------------
# llm_tasks — per-task routing
# ---------------------------------------------------------------------------


def test_llm_tasks_take_effect_via_resolve_task_llm_config(
    config_dir: Path,
) -> None:
    """``llm_tasks`` written via configure_llm routes through
    ``_resolve_task_llm_config`` (the ONLY place with the judgment
    exemption)."""
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(
        llm_tasks={
            "summarization": {
                "model": "claude-sonnet-4",
                "provider": "anthropic",
                "max_tokens": 4000,
            }
        }
    )
    assert result["success"] is True

    loaded = load_config(config_path)
    effective = _resolve_task_llm_config(loaded, "summarization")
    assert effective.model == "claude-sonnet-4"
    assert effective.provider == "anthropic"
    assert effective.max_tokens == 4000


def test_judgment_tasks_ignore_tasks_override(config_dir: Path) -> None:
    """Judgment tasks (g4_factual/g5_translation/llm_judge) ALWAYS resolve
    to JUDGMENT_MODEL via ``_resolve_task_llm_config`` — a written
    ``llm.tasks`` override must never change the judging model."""
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(
        llm_tasks={
            "g4_factual": {"model": "evil-judge", "provider": "evil"},
            "g5_translation": {"model": "evil-judge"},
            "llm_judge": {"model": "evil-judge"},
        }
    )
    assert result["success"] is True

    loaded = load_config(config_path)
    for task_name in ("g4_factual", "g5_translation", "llm_judge"):
        effective = _resolve_task_llm_config(loaded, task_name)
        assert effective.model == JUDGMENT_MODEL, (
            f"{task_name} must resolve to JUDGMENT_MODEL, got {effective.model}"
        )


def test_judgment_task_names_allowed_to_write(config_dir: Path) -> None:
    """Judgment task names are writable, but the success message notes the
    runtime pinning."""
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(
        llm_tasks={"g4_factual": {"model": "evil-judge"}}
    )

    assert result["success"] is True
    assert "运行期仍强制 JUDGMENT_MODEL" in result["data"]["message"]

    loaded = load_config(config_path)
    assert "g4_factual" in loaded.llm.tasks
    assert loaded.llm.tasks["g4_factual"].model == "evil-judge"


def test_get_effective_llm_config_judgment_behavior_unchanged(
    config_dir: Path,
) -> None:
    """``get_effective_llm_config`` has NO judgment exemption — its existing
    behavior (task override wins) must stay locked and untouched by this
    change."""
    config_path = _write_base_config(config_dir)

    _handle_configure_llm(
        llm_tasks={
            "g4_factual": {"model": "evil-judge"},
            "summarization": {"model": "claude-sonnet-4"},
        }
    )

    # Existing behavior: get_effective_llm_config applies the task override
    # verbatim (no JUDGMENT_MODEL pinning here — that lives only in
    # _resolve_task_llm_config).
    result = get_effective_llm_config(task="g4_factual")
    assert result["model"] == "evil-judge"
    assert result["task"] == "g4_factual"

    result = get_effective_llm_config(task="summarization")
    assert result["model"] == "claude-sonnet-4"

    # Sanity: the file on disk still carries the written tasks.
    loaded = load_config(config_path)
    assert "g4_factual" in loaded.llm.tasks


# ---------------------------------------------------------------------------
# None vs [] semantics + no-op
# ---------------------------------------------------------------------------


def test_empty_params_noop_does_not_write(config_dir: Path) -> None:
    """No params at all → ``{"status": "noop"}`` and the file is untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm()

    assert result["status"] == "noop"
    assert config_path.stat().st_mtime_ns == mtime_before


def test_empty_params_noop_without_config_file(config_dir: Path) -> None:
    """No params and no config file → noop, and no file is created."""
    result = _handle_configure_llm()

    assert result["status"] == "noop"
    assert not (config_dir / "config.yaml").exists()


def test_explicit_empty_list_clears_fallback(config_dir: Path) -> None:
    """``llm_fallback=[]`` clears the fallback key (None would leave it)."""
    config_path = _write_base_config(config_dir)
    _handle_configure_llm(llm_fallback=[{"model": "mimo-v2.5"}])

    result = _handle_configure_llm(llm_fallback=[])
    assert result["success"] is True

    loaded = load_config(config_path)
    assert loaded.llm.fallback == []


def test_explicit_empty_dict_clears_tasks(config_dir: Path) -> None:
    """``llm_tasks={}`` clears the tasks key (None would leave it)."""
    config_path = _write_base_config(config_dir)
    _handle_configure_llm(llm_tasks={"summarization": {"model": "claude-sonnet-4"}})

    result = _handle_configure_llm(llm_tasks={})
    assert result["success"] is True

    loaded = load_config(config_path)
    assert loaded.llm.tasks == {}


def test_none_does_not_touch_existing_pool(config_dir: Path) -> None:
    """``llm_fallback=None`` / ``llm_tasks=None`` leave existing pool intact."""
    config_path = _write_base_config(config_dir)
    _handle_configure_llm(
        llm_fallback=[{"model": "mimo-v2.5"}],
        llm_tasks={"summarization": {"model": "claude-sonnet-4"}},
    )

    # A provider-only call with None pool params must not disturb the pool.
    result = _handle_configure_llm(provider="openai", llm_fallback=None, llm_tasks=None)
    assert result["success"] is True

    loaded = load_config(config_path)
    assert len(loaded.llm.fallback) == 1
    assert loaded.llm.fallback[0].model == "mimo-v2.5"
    assert loaded.llm.tasks["summarization"].model == "claude-sonnet-4"


def test_explicit_clear_is_not_noop(config_dir: Path) -> None:
    """``llm_fallback=[]`` / ``llm_tasks={}`` are actions, not no-ops.

    (tmpfs mtime granularity can coalesce back-to-back writes, so the
    assertion is on file CONTENT, not mtime.)
    """
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(llm_fallback=[], llm_tasks={})

    assert result["success"] is True
    raw = config_path.read_text(encoding="utf-8")
    assert "fallback: []" in raw
    assert "tasks: {}" in raw


# ---------------------------------------------------------------------------
# Validate-before-write — failure leaves the file untouched
# ---------------------------------------------------------------------------


def _assert_file_untouched(config_path: Path, mtime_before: int) -> None:
    """Assert the config file was not modified: mtime AND content unchanged."""
    assert config_path.stat().st_mtime_ns == mtime_before
    # Content equality is the strongest guarantee (tmpfs mtime granularity
    # can be coarse, but a real write always changes the bytes).
    assert config_path.read_bytes() == _BASE_CONFIG_BYTES


def test_fallback_missing_model_validation_error(config_dir: Path) -> None:
    """A fallback entry without ``model`` → VALIDATION_ERROR, file untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm(llm_fallback=[{"base_url": "x"}])

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert result["error"]["actionable"] is True
    _assert_file_untouched(config_path, mtime_before)


def test_fallback_entry_not_dict_validation_error(config_dir: Path) -> None:
    """A non-dict fallback entry → VALIDATION_ERROR, file untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm(
        llm_fallback=cast(list[dict[str, Any]], ["mimo-v2.5"])
    )

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert result["error"]["actionable"] is True
    _assert_file_untouched(config_path, mtime_before)


def test_tasks_invalid_field_type_validation_error(config_dir: Path) -> None:
    """A task value with an unknown field type → VALIDATION_ERROR, untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm(
        llm_tasks={"summarization": {"max_tokens": "not-an-int"}}
    )

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert result["error"]["actionable"] is True
    _assert_file_untouched(config_path, mtime_before)


def test_tasks_value_not_dict_validation_error(config_dir: Path) -> None:
    """A non-dict task value → VALIDATION_ERROR, file untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm(llm_tasks={"summarization": "claude-sonnet-4"})

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert result["error"]["actionable"] is True
    _assert_file_untouched(config_path, mtime_before)


def test_tasks_unknown_field_validation_error(config_dir: Path) -> None:
    """A task value with an unknown field name → VALIDATION_ERROR, untouched."""
    config_path = _write_base_config(config_dir)
    mtime_before = config_path.stat().st_mtime_ns

    result = _handle_configure_llm(
        llm_tasks={"summarization": {"model": "x", "temperature": 0.7}}
    )

    assert result["success"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert result["error"]["actionable"] is True
    _assert_file_untouched(config_path, mtime_before)


# ---------------------------------------------------------------------------
# ${ENV} round-trip trap
# ---------------------------------------------------------------------------


def test_api_key_env_round_trip(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key`` is stored as ``${AUTOINFO_LLM_API_KEY}``; after
    ``load_config`` the env-resolved value is visible (never the raw
    placeholder)."""
    monkeypatch.setenv("AUTOINFO_LLM_API_KEY", "sk-test")
    config_path = _write_base_config(config_dir)

    result = _handle_configure_llm(api_key="sk-anything")
    assert result["success"] is True

    loaded = load_config(config_path)
    assert loaded.llm.api_key == "sk-test"

    raw = config_path.read_text(encoding="utf-8")
    assert "${AUTOINFO_LLM_API_KEY}" in raw
    assert "sk-anything" not in raw


def test_judgment_tasks_constant_unchanged() -> None:
    """Guard: the release-pinned judgment set is exactly the three names."""
    assert JUDGMENT_TASKS == frozenset({"g4_factual", "g5_translation", "llm_judge"})
    assert JUDGMENT_MODEL == "deepseek-v4-flash"
