"""Config-parsing tests for the LLM fallback chain.

Asserts that :func:`autoinfo.config.load_config` parses ``llm.fallback``
from the repository's real ``.autoinfo/config.yaml`` (the single
authorized direct config edit): three fallback entries with different
providers (zhipu, nvidia, agnes).  The primary provider/model must stay
untouched (deepseek-v4-flash stays primary).

The config path is resolved relative to this test file (repo root) so the
assertions hold regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoinfo.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".autoinfo" / "config.yaml"

# The tests assert against the repository's real (gitignored) config — the
# single authorized direct config edit. Absent on CI (fresh checkout has no
# .autoinfo/), so skip cleanly instead of failing FileNotFoundError.
pytestmark = pytest.mark.skipif(
    not CONFIG_PATH.is_file(),
    reason=".autoinfo/config.yaml absent (gitignored) — deployment-config test",
)

PRIMARY_MODEL = "openai/mimo-v2.5"
PRIMARY_PROVIDER = "openai"
PRIMARY_BASE_URL = "https://opencode.ai/zen/go/v1"


def test_fallback_chain_parsed_from_real_config() -> None:
    """The loader parses all three fallback entries verbatim."""
    cfg = load_config(CONFIG_PATH)

    assert len(cfg.llm.fallback) == 3, (
        f"expected exactly 3 fallback entries, got {len(cfg.llm.fallback)}"
    )

    # First fallback: glm-4.7-flash on zhipu
    fb0 = cfg.llm.fallback[0]
    assert fb0.model == "glm-4.7-flash"
    assert fb0.base_url == "https://open.bigmodel.cn/api/paas/v4"

    # Second fallback: nvidia/llama on nvidia
    fb1 = cfg.llm.fallback[1]
    assert fb1.model == "nvidia/llama-3.3-nemotron-super-49b-v1"
    assert fb1.base_url == "https://integrate.api.nvidia.com/v1"

    # Third fallback: agnes-2.5-flash
    fb2 = cfg.llm.fallback[2]
    assert fb2.model == "agnes-2.5-flash"
    assert fb2.base_url == "https://apihub.agnes-ai.com/v1"


def test_primary_unchanged() -> None:
    """openai/mimo-v2.5 stays the primary model/provider."""
    cfg = load_config(CONFIG_PATH)

    assert cfg.llm.provider == PRIMARY_PROVIDER
    assert cfg.llm.model == PRIMARY_MODEL
    assert cfg.llm.base_url == PRIMARY_BASE_URL
    assert cfg.llm.resolve_model() == PRIMARY_MODEL


def test_fallback_model_resolves_with_primary_provider() -> None:
    """Each fallback model resolves with the primary provider when provider is empty."""
    cfg = load_config(CONFIG_PATH)

    fb0 = cfg.llm.fallback[0]
    effective_provider = fb0.provider or cfg.llm.provider
    effective_model = fb0.model or cfg.llm.model
    assert f"{effective_provider}/{effective_model}" == "openai/glm-4.7-flash"
