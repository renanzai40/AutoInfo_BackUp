"""Config-parsing tests for the mimo-v2.5 fallback chain (todo 2).

Asserts that :func:`autoinfo.config.load_config` parses ``llm.fallback``
from the repository's real ``.autoinfo/config.yaml`` (the single
authorized direct config edit): exactly one fallback entry, model
``mimo-v2.5`` on the opencode gateway (``https://opencode.ai/zen/go/v1``),
with **no** per-entry provider or api_key — the fallback inherits the
primary provider and the gateway inherits the primary key.  The primary
provider/model must stay untouched (deepseek-v4-flash stays primary).

The config path is resolved relative to this test file (repo root) so the
assertions hold regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

from autoinfo.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".autoinfo" / "config.yaml"

OPENGATE_BASE_URL = "https://opencode.ai/zen/go/v1"
FALLBACK_MODEL = "mimo-v2.5"
PRIMARY_MODEL = "deepseek-v4-flash"
PRIMARY_PROVIDER = "openai"


def test_fallback_chain_parsed_from_real_config() -> None:
    """The loader parses the single mimo-v2.5 fallback entry verbatim."""
    cfg = load_config(CONFIG_PATH)

    assert len(cfg.llm.fallback) == 1, (
        f"expected exactly 1 fallback entry, got {len(cfg.llm.fallback)}"
    )
    fb = cfg.llm.fallback[0]
    assert fb.model == FALLBACK_MODEL
    assert fb.base_url == OPENGATE_BASE_URL
    # No per-entry provider/key: provider inherits the primary provider and
    # the key inherits the primary gateway key (MUST NOT add a raw key).
    assert fb.provider == ""
    assert fb.api_key == ""


def test_primary_unchanged() -> None:
    """deepseek-v4-flash on openai stays the primary model/provider."""
    cfg = load_config(CONFIG_PATH)

    assert cfg.llm.provider == PRIMARY_PROVIDER
    assert cfg.llm.model == PRIMARY_MODEL
    assert cfg.llm.base_url == OPENGATE_BASE_URL
    assert cfg.llm.resolve_model() == f"{PRIMARY_PROVIDER}/{PRIMARY_MODEL}"


def test_fallback_model_resolves_with_primary_provider() -> None:
    """The effective fallback model string is ``openai/mimo-v2.5`` (the
    same model ``call_with_fallback`` builds at llm.py:689-702)."""
    cfg = load_config(CONFIG_PATH)

    fb = cfg.llm.fallback[0]
    effective_provider = fb.provider or cfg.llm.provider
    effective_model = fb.model or cfg.llm.model
    assert f"{effective_provider}/{effective_model}" == (
        f"{PRIMARY_PROVIDER}/{FALLBACK_MODEL}"
    )
