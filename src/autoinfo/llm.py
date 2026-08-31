"""LLM extraction pipeline — structured information extraction from collected items.

Uses LiteLLM to call configured models (default: openai/ark-code-latest via Volcengine Ark)
and extract structured fields (TL;DR, key points, entities, relevance score) from
raw article content. All LLM calls go through :func:`litellm.completion`.

Typical usage::

    from autoinfo.llm import LLMExtractor
    from autoinfo.models import Item

    extractor = LLMExtractor()
    item = Item(id="1", source_name="pubmed", title="...", content="...", collected_at="...")
    result = extractor.extract(item)
    print(result.tl_dr)
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Optional

from autoinfo.config import (
    JUDGMENT_TASKS,
    Config,
    _resolve_task_llm_config,
    get_config_path,
    load_config,
)
from autoinfo.models import ExtractionResult, Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "openai/ark-code-latest"

SYSTEM_PROMPT = (
    "You are AutoInfo, an information extraction assistant. "
    "Extract structured information from the following article. "
    "Respond with valid JSON only, no markdown formatting."
)

FIELD_DESCRIPTIONS: dict[str, str] = {
    "tl_dr": '"tl_dr": "2-3 sentence summary of the article"',
    "key_points": '"key_points": ["3-5 most important findings or takeaways"]',
    "entities": (
        '"entities": [{"name": "Entity name", '
        '"type": "concept|person|org|drug|technology|procedure"}]'
    ),
    "relevance_score": '"relevance_score": integer 0-100 indicating relevance to medical research',
}

# Supported entity types for knowledge graph extraction.
ENTITY_TYPES: list[str] = [
    "concept",
    "person",
    "org",
    "drug",
    "technology",
    "procedure",
]

# Fields always included when no custom schema is provided.
DEFAULT_SCHEMA: list[str] = ["tl_dr", "key_points", "entities", "relevance_score"]

# Default fields that are ALWAYS included in extraction prompts, even when
# custom schema fields are specified.
DEFAULT_FIELDS: list[str] = ["tl_dr", "key_points", "entities", "relevance_score"]

# ---------------------------------------------------------------------------
# Per-provider shared rate limiting + 429/5xx jittered backoff
# ---------------------------------------------------------------------------

# Default concurrency per (provider, base_url); override via the
# AUTOINFO_LLM_MAX_CONCURRENCY environment variable (read once at
# semaphore creation).
DEFAULT_MAX_CONCURRENCY = 4

# Bounded retry loop: at most 3 total attempts (2 retries) per chain entry.
MAX_LLM_ATTEMPTS = 3

# Exponential backoff: base 1.0s, factor 2, cap 8s, jitter +/-25%.
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
BACKOFF_CAP_SECONDS = 8.0
BACKOFF_JITTER = 0.25

# Registry of shared semaphores keyed by (provider, base_url).  Get-or-create
# is guarded by a module-level lock so concurrent first-time callers never
# create duplicate semaphores for the same provider endpoint.
_PROVIDER_SEMAPHORES: dict[tuple[str, str], threading.Semaphore] = {}
_PROVIDER_SEMAPHORES_LOCK = threading.Lock()


def _max_concurrency() -> int:
    """Resolve the per-provider concurrency (env override, default 4).

    ``AUTOINFO_LLM_MAX_CONCURRENCY`` is read at registry creation time;
    values below 1 clamp to 1, unparsable values fall back to the default.
    """
    raw = os.environ.get("AUTOINFO_LLM_MAX_CONCURRENCY", "")
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_MAX_CONCURRENCY


def get_provider_semaphore(provider: str, base_url: str) -> threading.Semaphore:
    """Get-or-create the shared semaphore for a ``(provider, base_url)`` pair.

    All concurrent LLM callers of the same provider endpoint share this
    semaphore, bounding in-flight requests per provider — there is no single
    global process-wide lock.
    """
    key = (provider, base_url)
    with _PROVIDER_SEMAPHORES_LOCK:
        semaphore = _PROVIDER_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.Semaphore(_max_concurrency())
            _PROVIDER_SEMAPHORES[key] = semaphore
        return semaphore


def _error_status(exc: Exception) -> int | None:
    """Extract an HTTP status from a provider error, when one is present.

    Handles LiteLLM ``HTTPException`` subclasses (``status_code``), stubs and
    providers exposing only ``status``, and ``httpx``-style errors carrying a
    ``response`` object with ``status_code``.
    """
    for attr in ("status_code", "status"):
        status = getattr(exc, attr, None)
        if isinstance(status, int):
            return status
        if isinstance(status, str) and status.isdigit():
            return int(status)
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _is_retryable_error(exc: Exception) -> bool:
    """Whether *exc* warrants a retry: HTTP 429 or any 5xx status.

    Any other status (including non-retryable 4xx like 400/403/404) or an
    error without an HTTP status surfaces immediately — no retry.
    """
    status = _error_status(exc)
    if status is None:
        return False
    if status == 429:
        return True
    return 500 <= status <= 599


def _backoff_delay(attempt: int) -> float:
    """Jittered exponential backoff delay for retry *attempt* (0-based).

    ``base 1.0s * factor 2**attempt``, capped at 8s, with +/-25% uniform
    jitter so concurrent retriers do not stampede in lockstep.
    """
    raw = min(
        BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR**attempt), BACKOFF_CAP_SECONDS
    )
    jitter = raw * BACKOFF_JITTER
    return max(0.0, raw - jitter + random.uniform(0.0, 2.0 * jitter))

# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class LLMExtractor:
    """Extract structured fields from a collected :class:`Item` using an LLM.

    Parameters
    ----------
    config : Config, optional
        Application configuration.  If omitted the extractor tries to load the
        config from the default paths (``.autoinfo/config.yaml`` or
        ``~/.autoinfo/config.yaml``).  When neither exists an empty config is
        used and the provider/model fall back to their defaults.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        if config is None:
            config_path = get_config_path()
            if config_path is not None:
                config = load_config(config_path)
            else:
                config = Config()

        # Per-task model routing: extraction/classification resolves through
        # the "extraction" task config (deepseek-v4-flash this release).  The
        # base config is returned as-is when no task config exists, so
        # historical defaults are preserved exactly.
        config = Config(llm=_resolve_task_llm_config(config, "extraction"))

        self._config = config
        self._json_mode = config.llm.json_mode
        self._reasoning_model = config.llm.reasoning_model
        self._timeout = float(config.llm.timeout or 120.0)

        provider = config.llm.provider or DEFAULT_PROVIDER
        model = config.llm.model or DEFAULT_MODEL
        self._model = config.llm.resolve_model() or f"{provider}/{model}"
        self._base_url = config.llm.base_url

        # If the config carries an API key, let the environment variable take
        # it — LiteLLM reads OPENROUTER_API_KEY automatically for OpenRouter
        # calls, OPENAI_API_KEY for OpenAI calls, etc.
        # Fall back to the AUTOINFO_LLM_API_KEY env var when the config key is
        # empty or is an unresolved ${ENV} placeholder (fixes #119: llm.py
        # previously ignored AUTOINFO_LLM_API_KEY entirely, while
        # _is_llm_configured / _resolve_llm_config in mcp/validation.py
        # honored it — inconsistent key resolution).
        resolved_key = config.llm.api_key or ""
        if (
            isinstance(resolved_key, str)
            and resolved_key.startswith("${")
            and resolved_key.endswith("}")
        ):
            resolved_key = os.environ.get(resolved_key[2:-1], "")
        if not resolved_key:
            resolved_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
        if resolved_key:
            env_key = f"{provider.upper()}_API_KEY"
            os.environ.setdefault(env_key, resolved_key)

        # Build fallback model chain from config.llm.fallback.
        # Each entry is a dict with "model" (provider/model string) and
        # optional "base_url".  API keys are set via env vars so that
        # LiteLLM picks them up automatically at call time.
        self._fallback_models: list[dict[str, str]] = []
        for fb in config.llm.fallback:
            fb_provider = fb.provider or provider
            fb_model = fb.model or model
            fb_full = f"{fb_provider}/{fb_model}"
            # Skip duplicates (e.g. same model already in chain)
            if fb_full == self._model:
                continue
            # Set API key env var for this fallback provider
            if fb.api_key:
                env_key = f"{fb_provider.upper()}_API_KEY"
                os.environ.setdefault(env_key, fb.api_key)
            fb_burl = fb.base_url or ""
            self._fallback_models.append({
                "model": fb_full,
                "base_url": fb_burl,
            })

    def _should_use_json_mode(self) -> bool:
        """Return True only when json_mode is enabled AND not a reasoning model.

        Reasoning models (e.g. DeepSeek-R1) do not support
        ``response_format={"type": "json_object"}``.  When the config flag
        ``reasoning_model`` is set, json_object is *always* skipped, even if
        ``json_mode`` is ``True``.
        """
        return self._json_mode and not self._reasoning_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        item: Item,
        schema: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """Extract structured fields from *item*.

        Returns an :class:`ExtractionResult` with the parsed fields.  If the
        LLM call or JSON parsing fails the result contains empty/default values
        (no exception is raised).
        """
        try:
            return self._call_llm(item, schema)
        except Exception as exc:
            logger.error("LLM extraction failed for item %s: %s", item.id, exc)
            return ExtractionResult(item_id=item.id, title=item.title)

    def dry_run(
        self,
        item: Item,
        schema: Optional[list[str]] = None,
    ) -> str:
        """Return the full prompt that *would* be sent to the LLM.

        No API call is made — useful for debugging and prompt iteration.
        """
        system, user = self._build_prompt(item, schema)
        return f"System:\n{system}\n\nUser:\n{user}"

    def extract_with_retry(
        self,
        item: Item,
        max_retries: int = 2,
        schema: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """Extract with retry logic.

        On failure the method logs a warning, waits 1 second, and retries.
        If all attempts fail a :class:`RuntimeError` is raised.

        Raises
        ------
        RuntimeError
            When extraction fails after *max_retries* + 1 attempts.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                return self._call_llm(item, schema)
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "LLM extraction attempt %d/%d failed: %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                if attempt < max_retries:
                    time.sleep(1)

        raise RuntimeError(
            f"LLM extraction failed after {max_retries + 1} attempts "
            f"(no fallback configured)" if not self._fallback_models
            else f"LLM extraction failed after {max_retries + 1} attempts "
            f"(all primary + fallback models exhausted)"
        ) from last_exception

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        item: Item,
        schema: Optional[list[str]] = None,
    ) -> tuple[str, str]:
        """Build (system_prompt, user_prompt) for the given *item*.

        Default fields (TL;DR, key points, entities, relevance score) are
        **always** included in the prompt.  When *schema* is provided any
        additional field names not in the default set are treated as custom
        fields and appended with an "Extract additionally" instruction.
        When *schema* is ``None`` only the default fields are requested.
        """
        if schema is None:
            fields = DEFAULT_SCHEMA
            custom = []
        else:
            fields = DEFAULT_FIELDS[:]
            custom = [f for f in schema if f not in DEFAULT_FIELDS]

        lines = [SYSTEM_PROMPT, "", "Extract the following fields:"]
        for field in fields:
            desc = FIELD_DESCRIPTIONS.get(field, f'"{field}": <value>')
            lines.append(f"  - {desc}")

        # Append entity type guidance when entities are requested
        if "entities" in fields:
            lines.append("")
            lines.append(
                "Entity types: " + ", ".join(ENTITY_TYPES)
            )

        if custom:
            lines.append("")
            lines.append("Extract additionally:")
            for cf in custom:
                # Auto-generate description from field name
                desc = cf.replace("_", " ").replace("-", " ").title()
                lines.append(f'  - "{cf}": {desc}')

        lines.append("")
        lines.append("Return all fields in a single JSON object.")

        system = "\n".join(lines)
        user = (
            f"Title: {item.title}\n\n"
            f"Content: {item.content}\n\n"
            "Extract structured information from this article."
        )
        return system, user

    @staticmethod
    def _get_litellm() -> Any:
        """Lazily import and return the ``litellm`` module.

        Returns ``None`` when the package is not available (graceful
        degradation for environments where LiteLLM is not installed).
        """
        try:
            import litellm  # noqa: PLC0415 — deferred import

            return litellm
        except (ImportError, ModuleNotFoundError):
            logger.error("litellm is not installed — run 'pip install litellm'")
            return None

    def _call_llm(
        self,
        item: Item,
        schema: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """Execute the LLM completion and parse the result.

        Delegates the primary + fallback chain walk to
        :func:`call_with_fallback` (issue #147 — single shared helper for
        every LLM call path).  Raises :class:`RuntimeError` only after
        **all** models have failed; the caller (``extract`` /
        ``extract_with_retry``) decides how to handle that final failure.
        """
        system, user_prompt = self._build_prompt(item, schema)

        response = call_with_fallback(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            base_url=self._base_url,
            max_tokens=4000,
            temperature=0.1,
            json_mode=self._should_use_json_mode(),
            reasoning_model=self._reasoning_model,
            timeout=self._timeout,
            config=self._config,
        )

        usage: dict[str, Any] = {}
        if hasattr(response, "usage") and response.usage is not None:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        content: str = response.choices[0].message.content  # type: ignore[union-attr]
        parsed = self._parse_response(content)

        custom_field_names: list[str] = []
        if schema is not None:
            custom_field_names = [f for f in schema if f not in DEFAULT_FIELDS]

        custom_fields: dict[str, Any] = {}
        for cf in custom_field_names:
            if cf in parsed:
                custom_fields[cf] = parsed[cf]

        return ExtractionResult(
            item_id=item.id,
            title=item.title,
            tl_dr=parsed.get("tl_dr", ""),
            key_points=parsed.get("key_points", []),
            entities=parsed.get("entities", []),
            relevance_score=max(
                0.0, min(100.0, float(parsed.get("relevance_score", 0)))
            ),
            custom_fields=custom_fields,
            usage=usage,
        )

    @staticmethod
    def _parse_response(content: str | None) -> dict[str, Any]:
        """Parse the LLM response as JSON via :func:`parse_json_response`.

        Returns an empty dict when all strategies fail or content is ``None``
        — the historical lenient contract for extraction.  The raising
        contract lives in the public :func:`parse_json_response`.
        """
        if content is None:
            logger.warning("LLM returned None content — empty response")
            return {}
        try:
            parsed = parse_json_response(content)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse LLM response as JSON: %.200s", content or ""
            )
            return {}
        if isinstance(parsed, dict):
            return parsed
        logger.warning(
            "LLM response parsed but is not a JSON object: %.200s", content or ""
        )
        return {}


def parse_json_response(content: str | None) -> Any:
    """Parse LLM output as JSON, tolerating markdown and prose noise.

    Strategies, in order:

    1. Direct :func:`json.loads` (plain JSON object or array).
    2. Extract JSON from a markdown fenced code block (`` ```json ... ``` ``
       or a bare `` ``` ... ``` ``).
    3. Extract the first ``{…}`` brace-delimited block from surrounding
       prose.

    Parameters
    ----------
    content:
        The raw LLM response text, or ``None`` when the model returned no
        content.

    Returns
    -------
    Any
        The parsed JSON value (typically a ``dict`` or ``list``).

    Raises
    ------
    json.JSONDecodeError
        When *content* is ``None`` (empty response) or none of the three
        strategies yields valid JSON.  Callers decide the failure policy —
        e.g. retry/block (quality gates) or a graceful error envelope
        (MCP tools).
    TypeError
        When *content* is not a string (mirrors :func:`json.loads`).
    """
    if content is None:
        raise json.JSONDecodeError("LLM returned no parseable content", "", 0)
    if not isinstance(content, str):
        raise TypeError(
            f"LLM response content must be a string, got {type(content).__name__}"
        )

    # Strategy 1 — direct JSON
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 2 — markdown fenced code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategy 3 — bare JSON object anywhere in the text
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    raise json.JSONDecodeError("Failed to parse LLM response as JSON", content, 0)


def _completion_request(
    entry: dict[str, str],
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    reasoning_model: bool,
    timeout: float | None,
    disable_thinking: bool = True,
) -> dict[str, Any]:
    """Build the LiteLLM completion kwargs for a single chain *entry*.

    ``response_format`` is added only when ``json_mode`` is set **and** the
    effective reasoning-model flag is ``False`` — reasoning providers
    reject the parameter, so callers rely on the prompt plus
    :func:`parse_json_response` instead (issue #178).

    ``disable_thinking`` (default True for reasoning models) sends
    ``thinking={"type": "disabled"}`` so the model's chain-of-thought does
    not consume the shared ``max_tokens`` budget — on DeepSeek-style
    reasoning endpoints the reasoning pass runs *before* the content pass,
    so a small budget (e.g. 2000) can be exhausted by thinking alone,
    truncating the JSON output mid-object (finish_reason=length).
    """
    kwargs: dict[str, Any] = {
        "model": entry["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "api_base": entry["base_url"] or None,
        "api_key": entry["api_key"] or None,
        "timeout": timeout,
    }
    if reasoning_model and disable_thinking:
        # Supported by DeepSeek R1/V4 endpoints; rejected by non-reasoning
        # providers, so gate on the reasoning flag only. LiteLLM forwards
        # extra body params via additional_body (thinking is not an OpenAI
        # SDK kwarg).
        kwargs["additional_body"] = {"thinking": {"type": "disabled"}}
    if json_mode and not reasoning_model:
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def call_with_fallback(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.1,
    json_mode: bool = False,
    reasoning_model: bool | None = None,
    timeout: float | None = None,
    config: Config | None = None,
    disable_thinking: bool = True,
    task: str | None = None,
) -> Any:
    """Call LiteLLM through the configured primary + fallback model chain.

    Walks ``[primary] + config.llm.fallback`` — when the primary model
    fails each configured fallback is tried in order and the first
    successful response is returned.  Raises :class:`RuntimeError` once
    every model has failed.

    *model* overrides the config-derived primary.  *base_url* / *api_key*
    are passed through to LiteLLM only when explicitly provided —
    otherwise credentials resolve from the environment (``${ENV}``
    placeholders in fallback keys are expanded).  Fallback entries always
    come from *config* (or the on-disk config when *config* is ``None``).
    *json_mode* adds ``response_format={"type": "json_object"}`` unless
    the effective reasoning-model flag is set (see below).

    *reasoning_model* marks the model as a reasoning model that rejects
    ``response_format`` (e.g. DeepSeek-R1).  When ``None`` (default) the
    value inherits from ``config.llm.reasoning_model``; an explicit bool
    wins.  When ``json_mode`` is ``True`` and the effective flag is
    ``True``, ``response_format`` is suppressed and callers rely on the
    prompt plus :func:`parse_json_response` (issue #178).

    *max_tokens* defaults to ``config.llm.max_tokens`` when set, else the
    historical 2000.  A task-level ``llm.tasks[<task>].max_tokens``
    resolved via :func:`autoinfo.config._resolve_task_llm_config` therefore
    reaches the request payload (issue #178).

    *task* routes the call through
    :func:`autoinfo.config._resolve_task_llm_config` before any value is
    read from the config: the resolved config's ``model`` and
    ``max_tokens`` become the effective defaults.  An explicit *model* /
    *max_tokens* parameter always wins over the resolved task values.
    Judgment task names (G4/G5/llm_judge) resolve their model to the
    release-pinned :data:`autoinfo.config.JUDGMENT_MODEL` — a drifted
    ``llm.tasks`` entry can never re-route a judgment call.  ``None``
    (default) keeps the historical behavior with no task resolution.

    Every actual provider call is guarded by a per-provider shared
    semaphore (keyed ``(provider, base_url)``, default width 4, override
    ``AUTOINFO_LLM_MAX_CONCURRENCY``) and retried on HTTP 429 / 5xx with
    jittered exponential backoff — at most ``MAX_LLM_ATTEMPTS`` attempts
    (2 retries) per chain entry, base 1.0s / factor 2 / cap 8s / +/-25%
    jitter.  The last error of the final attempt surfaces.
    """
    _litellm = LLMExtractor._get_litellm()
    if _litellm is None:
        raise RuntimeError("litellm is not available")

    if config is None:
        config_path = get_config_path()
        try:
            config = load_config(config_path) if config_path is not None else Config()
        except Exception:
            config = Config()

    if task:
        config = Config(llm=_resolve_task_llm_config(config, task))

    if reasoning_model is None:
        reasoning_model = config.llm.reasoning_model
    if max_tokens is None:
        max_tokens = config.llm.max_tokens or 2000

    provider = config.llm.provider or DEFAULT_PROVIDER
    primary = (
        model
        or config.llm.resolve_model()
        or f"{provider}/{config.llm.model or DEFAULT_MODEL}"
    )

    # Primary api_key falls back to config.llm.api_key (which may hold a
    # ${ENV} placeholder) — matches the fallback entries below (#166/#119).
    primary_key = api_key or config.llm.api_key or ""
    if primary_key.startswith("${") and primary_key.endswith("}"):
        primary_key = os.environ.get(primary_key[2:-1], "")

    chain: list[dict[str, str]] = [{
        "model": primary,
        # Effective provider for rate-limiting keying (shared semaphore).
        "provider": provider,
        # Primary base_url defaults to config.llm.base_url (issue #147
        # follow-up: callers like cefr/quality/qa/keywords pass no base_url,
        # so without this the primary silently hits the provider default
        # endpoint (e.g. api.openai.com) instead of the configured one).
        "base_url": base_url or (config.llm.base_url or ""),
        "api_key": primary_key,
    }]
    for fb in config.llm.fallback:
        fb_provider = fb.provider or provider
        fb_full = f"{fb_provider}/{fb.model or config.llm.model or DEFAULT_MODEL}"
        if fb_full == primary:
            continue
        fb_key = fb.api_key or ""
        if fb_key.startswith("${") and fb_key.endswith("}"):
            fb_key = os.environ.get(fb_key[2:-1], "")
        chain.append({
            "model": fb_full,
            "provider": fb_provider,
            "base_url": fb.base_url or "",
            "api_key": fb_key,
        })

    attempted: list[str] = []
    last_exception: Optional[Exception] = None

    for entry in chain:
        attempted.append(entry["model"])
        # Shared per-provider semaphore: bounds concurrent in-flight calls to
        # this (provider, base_url) across every LLM caller in the process.
        semaphore = get_provider_semaphore(entry["provider"], entry["base_url"])
        entry_error: Optional[Exception] = None
        for attempt in range(MAX_LLM_ATTEMPTS):
            try:
                with semaphore:
                    response = _litellm.completion(
                        **_completion_request(
                            entry,
                            messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            json_mode=json_mode,
                            reasoning_model=reasoning_model,
                            timeout=timeout,
                            disable_thinking=disable_thinking,
                        )
                    )
                if entry["model"] != primary:
                    logger.info(
                        "Fallback to %s succeeded after primary %s failed",
                        entry["model"],
                        primary,
                    )
                return response
            except Exception as exc:
                entry_error = exc
                last_exception = exc
                # Only HTTP 429 / 5xx retry (jittered backoff, up to
                # MAX_LLM_ATTEMPTS total); everything else surfaces
                # immediately and the chain moves to the next model.
                if not _is_retryable_error(exc) or attempt >= MAX_LLM_ATTEMPTS - 1:
                    break
                delay = _backoff_delay(attempt)
                logger.warning(
                    "LLM model %s attempt %d/%d failed (%s); retrying in %.2fs",
                    entry["model"],
                    attempt + 1,
                    MAX_LLM_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
        logger.warning(
            "LLM model %s failed (attempted %d/%d): %s",
            entry["model"],
            len(attempted),
            len(chain),
            entry_error,
        )

    # Judgment gate calls (G4/G5/llm_judge) must NEVER fail silently: when
    # every chain model is exhausted, raise the error to ERROR level so a
    # broken judgment gate is visible instead of quietly passing entries
    # through.  The RuntimeError still propagates to the caller, which
    # decides gate policy.
    if task in JUDGMENT_TASKS:
        logger.error(
            "Judgment task %r failed after exhausting all %d model(s) "
            "[%s] — G4/G5 gate may be impaired. Last error: %s",
            task,
            len(attempted),
            ", ".join(attempted),
            last_exception,
        )

    raise RuntimeError(
        f"All LLM models (primary + fallback) failed: {', '.join(attempted)}"
        f" — last error: {last_exception}"
    ) from last_exception
