"""LLM extraction pipeline — structured information extraction from collected items.

Uses LiteLLM to call configured models (default: deepseek/deepseek-chat via OpenRouter)
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
import re
import time
from typing import Any, Optional

from autoinfo.config import Config, get_config_path, load_config
from autoinfo.models import ExtractionResult, Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "deepseek/deepseek-chat"

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
            max_tokens=2000,
            temperature=0.1,
            json_mode=self._should_use_json_mode(),
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
        """Parse the LLM response as JSON with several fallback strategies.

        1. Direct :func:`json.loads`.
        2. Extract JSON from markdown code blocks (```json ... ```).
        3. Find the first ``{…}`` brace-delimited block.

        Returns an empty dict when all strategies fail or content is ``None``.
        """
        if content is None:
            logger.warning("LLM returned None content — empty response")
            return {}

        # Strategy 1 — direct JSON
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        # Strategy 2 — markdown fenced code block
        try:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                try:
                    return json.loads(match.group(1))
                except (json.JSONDecodeError, TypeError):
                    pass
        except TypeError:
            pass

        # Strategy 3 — bare JSON object anywhere in the text
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group(0))
                except (json.JSONDecodeError, TypeError):
                    pass
        except TypeError:
            pass

        logger.warning("Failed to parse LLM response as JSON: %.200s", content or "")
        return {}


def call_with_fallback(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    json_mode: bool = False,
    timeout: float | None = None,
    config: Config | None = None,
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
    *json_mode* adds ``response_format={"type": "json_object"}``.
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
            "base_url": fb.base_url or "",
            "api_key": fb_key,
        })

    attempted: list[str] = []
    last_exception: Optional[Exception] = None

    for entry in chain:
        attempted.append(entry["model"])
        try:
            response = _litellm.completion(
                model=entry["model"],
                messages=messages,
                **(dict(response_format={"type": "json_object"}) if json_mode else {}),
                max_tokens=max_tokens,
                temperature=temperature,
                api_base=entry["base_url"] or None,
                api_key=entry["api_key"] or None,
                timeout=timeout,
            )
            if entry["model"] != primary:
                logger.info(
                    "Fallback to %s succeeded after primary %s failed",
                    entry["model"],
                    primary,
                )
            return response
        except Exception as exc:
            last_exception = exc
            logger.warning(
                "LLM model %s failed (attempted %d/%d): %s",
                entry["model"],
                len(attempted),
                len(chain),
                exc,
            )

    raise RuntimeError(
        f"All LLM models (primary + fallback) failed: {', '.join(attempted)}"
        f" — last error: {last_exception}"
    ) from last_exception
