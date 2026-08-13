"""Translation quality assessment utilities.

Provides scoring functions for evaluating translation quality across multiple
dimensions: faithfulness, terminology, style, and readability.

This module also provides back-translation verification and LLM judge
functionality:

- :func:`back_translate` — translate a target text back to the source language
  using a DIFFERENT model from the forward pass
- :func:`llm_judge_translation` — compare original source with back-translated
  result and score faithfulness
- :func:`run_back_translation_pipeline` — orchestrator that chains
  back-translation → evaluation → composite score
"""

from __future__ import annotations

import json
import logging
from typing import Any

from autoinfo.llm import call_with_fallback

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "faithfulness": 40,
    "terminology": 30,
    "style": 20,
    "readability": 10,
}

# ---------------------------------------------------------------------------
# Composite score (preserved from earlier task)
# ---------------------------------------------------------------------------


def calculate_quality_score(
    faithfulness: float | None = None,
    terminology: float | None = None,
    style: float | None = None,
    readability: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, float | dict[str, float]]:
    """Calculate a composite translation quality score (0-100) from 4 sub-scores.

    Each sub-score is expected to be in the 0-100 range. Missing sub-scores
    default to 0. Out-of-range values are clamped to [0, 100].

    Parameters
    ----------
    faithfulness:
        Accuracy / fidelity to source text (0-100).
    terminology:
        Terminology accuracy / domain term handling (0-100).
    style:
        Style / tone consistency with source (0-100).
    readability:
        Readability / fluency in target language (0-100).
    weights:
        Optional dict overriding the default weight distribution.
        Default: ``{"faithfulness": 40, "terminology": 30, "style": 20, "readability": 10}``.
        Weights are auto-normalized if they don't sum to 100.

    Returns
    -------
    dict
        ``composite`` — weighted composite score (0-100, rounded to 1 decimal)
        ``faithfulness`` — clamped input score
        ``terminology`` — clamped input score
        ``style`` — clamped input score
        ``readability`` — clamped input score
        ``weights_used`` — the normalised weight percentages applied
    """
    # Clamp and default individual scores
    scores = {
        "faithfulness": max(0.0, min(100.0, float(faithfulness))) if faithfulness is not None else 0.0,
        "terminology": max(0.0, min(100.0, float(terminology))) if terminology is not None else 0.0,
        "style": max(0.0, min(100.0, float(style))) if style is not None else 0.0,
        "readability": max(0.0, min(100.0, float(readability))) if readability is not None else 0.0,
    }

    # Normalise weights
    w = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    total_weight = sum(w.values())
    if total_weight <= 0:
        w = dict(DEFAULT_WEIGHTS)
        total_weight = 100.0

    composite = sum(scores[k] * (w.get(k, 0) / total_weight) for k in scores)
    composite = max(0.0, min(100.0, composite))

    return {
        "composite": round(composite, 1),
        "faithfulness": scores["faithfulness"],
        "terminology": scores["terminology"],
        "style": scores["style"],
        "readability": scores["readability"],
        "weights_used": {k: round(v / total_weight * 100, 1) for k, v in w.items()},
    }


# ---------------------------------------------------------------------------
# Back-translation
# ---------------------------------------------------------------------------


def back_translate(
    source_text: str,  # noqa: ARG001 — unused, kept for API symmetry
    translated_text: str,
    source_lang: str,
    target_lang: str,
    model_pool: list[str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Translate *translated_text* back to *source_lang* using a DIFFERENT model.

    Parameters
    ----------
    source_text:
        Original source text (used for reference / logging only).
    translated_text:
        The forward-translated text to translate back.
    source_lang:
        Original source language code (e.g. ``"en"``, ``"zh"``).
    target_lang:
        Language the text was translated into (e.g. ``"zh"``, ``"en"``).
    model_pool:
        List of model names (e.g. ``["openrouter/deepseek/deepseek-chat",
        "openrouter/anthropic/claude-sonnet"]``). The first model is treated
        as the forward model; a different model is selected for
        back-translation. If ``None``, the pool is resolved from config.
        If only one model is available, a warning is logged and it is used
        for both directions (suboptimal).

    Returns
    -------
    dict
        ``back_translated_text`` — the result of translating back to source lang
        ``back_model`` — the model used for back-translation
        ``forward_model`` — the model assumed for forward translation
        ``success`` — ``True`` when the LLM call succeeded
    """
    pool = _resolve_model_pool(model_pool)

    # Pick models: first is forward, try different for back
    forward_model = pool[0] if pool else _resolve_default_model()
    back_model = forward_model

    if len(pool) >= 2:
        # Use a different model for back-translation
        back_model = pool[1]
    elif len(pool) == 1:
        logger.warning(
            "back_translate: only one model in pool (%s) — using the same "
            "model for forward and back-translation. This defeats the purpose "
            "of back-translation verification.",
            forward_model,
        )

    if timeout is None:
        timeout = _resolve_timeout()

    prompt = (
        f"Translate the following text from {target_lang} back to {source_lang}. "
        f"Preserve the original meaning, tone, and factual details as closely as possible.\n\n"
        f"TEXT ({target_lang}):\n{translated_text[:6000]}\n\n"
        f"TRANSLATION ({source_lang}):"
    )

    try:
        response = call_with_fallback(
            model=back_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a professional translator. Translate the given text "
                        f"from {target_lang} to {source_lang}. Return only the translated "
                        f"text, no explanations or commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.1,
            timeout=timeout,
        )

        back_text: str = response.choices[0].message.content  # type: ignore[union-attr]
        if not back_text or not back_text.strip():
            logger.warning("back_translate: empty response from model %s", back_model)
            return {
                "back_translated_text": "",
                "back_model": back_model,
                "forward_model": forward_model,
                "success": False,
            }

        return {
            "back_translated_text": back_text.strip(),
            "back_model": back_model,
            "forward_model": forward_model,
            "success": True,
        }

    except Exception as exc:
        logger.warning("back_translate: LLM call failed with %s: %s", back_model, exc)
        return {
            "back_translated_text": "",
            "back_model": back_model,
            "forward_model": forward_model,
            "success": False,
        }


# ---------------------------------------------------------------------------
# LLM Judge — faithfulness evaluation
# ---------------------------------------------------------------------------


def llm_judge_translation(
    original_source: str,
    back_translated_text: str,
    source_lang: str,
    model: str | None = None,
    json_mode: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Compare original source with back-translated text and score faithfulness.

    Parameters
    ----------
    original_source:
        The original text in the source language.
    back_translated_text:
        The text after forward translation + back-translation.
    source_lang:
        Source language code (e.g. ``"en"``, ``"zh"``).
    model:
        Optional model override. Falls back to config / default when ``None``.

    Returns
    -------
    dict
        ``faithfulness_score`` — 0-100 float
        ``issues`` — list of ``{"severity": str, "description": str, "position": str}``
    """
    if model is None:
        model = _resolve_default_model()
    if timeout is None:
        timeout = _resolve_timeout()

    system_prompt = (
        "You are a translation quality evaluator. Compare the ORIGINAL source text "
        "with the BACK-TRANSLATED text (i.e. text that was translated to another "
        "language and then translated back). "
        "Assess how faithfully the back-translated text preserves the meaning, "
        "tone, and factual content of the original.\n\n"
        "Return JSON with:\n"
        '- "faithfulness_score": integer 0-100 (100 = perfect preservation)\n'
        '- "issues": list of objects, each with:\n'
        '    - "severity": "minor" | "major" | "critical"\n'
        '    - "description": what changed or was lost\n'
        '    - "position": where in the text the issue occurs (e.g. "paragraph 2", '
        '"sentence 1", "last line")\n\n'
        "If no significant issues are found, return an empty issues list."
    )

    user_prompt = (
        f"ORIGINAL ({source_lang}):\n{original_source[:4000]}\n\n"
        f"BACK-TRANSLATED ({source_lang}):\n{back_translated_text[:4000]}\n\n"
        "Evaluate faithfulness and list any issues."
    )

    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=json_mode,
            max_tokens=2000,
            temperature=0.1,
            timeout=timeout,
            disable_thinking=False,
        )

        content: str = response.choices[0].message.content  # type: ignore[union-attr]
        parsed = json.loads(content)

        faithfulness = max(0.0, min(100.0, float(parsed.get("faithfulness_score", 0))))
        raw_issues: list[dict[str, str]] = list(parsed.get("issues", []) or [])

        # Normalise issue format
        issues: list[dict[str, str]] = []
        for iss in raw_issues:
            if isinstance(iss, dict):
                issues.append({
                    "severity": str(iss.get("severity", "minor")),
                    "description": str(iss.get("description", "")),
                    "position": str(iss.get("position", "")),
                })

        return {"faithfulness_score": faithfulness, "issues": issues}

    except (json.JSONDecodeError, KeyError, AttributeError) as exc:
        logger.warning("llm_judge_translation: malformed response: %s", exc)
        return {
            "faithfulness_score": 0.0,
            "issues": [{"severity": "major", "description": f"Failed to parse LLM response: {exc}", "position": "n/a"}],
        }
    except Exception as exc:
        logger.warning("llm_judge_translation: LLM call failed: %s", exc)
        return {
            "faithfulness_score": 0.0,
            "issues": [{"severity": "major", "description": f"LLM evaluation failed: {exc}", "position": "n/a"}],
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_back_translation_pipeline(
    source_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    model_pool: list[str] | None = None,
    enable_back_translation: bool = True,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    """Run the full back-translation verification pipeline.

    1. If ``enable_back_translation=False``, return ``None``.
    2. Call :func:`back_translate` to translate the target text back to *source_lang*.
    3. Call :func:`llm_judge_translation` to score faithfulness.
    4. Calculate composite score using :func:`calculate_quality_score`.

    Parameters
    ----------
    source_text:
        Original source text.
    translated_text:
        The forward-translated text.
    source_lang:
        Source language code.
    target_lang:
        Target language code (the language *translated_text* is in).
    model_pool:
        List of model names for forward/back. First is forward, second is back.
        Falls back to config when ``None``.
    enable_back_translation:
        When ``False``, skip the pipeline entirely and return ``None``.
        Defaults to ``True`` (on for high-stakes, off for bulk).

    Returns
    -------
    dict or None
        Per-round diagnostics dict, or ``None`` when back-translation is disabled::

            {
                "round": 1,
                "forward_model": "...",
                "back_model": "...",
                "judge_model": "...",
                "faithfulness": 85.0,
                "issues": [...],
                "composite_score": 72.5
            }
    """
    if not enable_back_translation:
        logger.info("back-translation pipeline disabled — skipping")
        return None

    # Step 1 — back-translate
    bt_result = back_translate(
        source_text=source_text,
        translated_text=translated_text,
        source_lang=source_lang,
        target_lang=target_lang,
        model_pool=model_pool,
        timeout=timeout,
    )

    if not bt_result["success"] or not bt_result["back_translated_text"].strip():
        logger.warning("back-translation failed or returned empty — returning partial diagnostics")
        return {
            "round": 1,
            "forward_model": bt_result["forward_model"],
            "back_model": bt_result["back_model"],
            "judge_model": "n/a",
            "faithfulness": 0.0,
            "issues": [{"severity": "major", "description": "Back-translation failed or returned empty", "position": "n/a"}],
            "composite_score": 0.0,
        }

    # Step 2 — LLM judge
    # Use the back_model for the judge, or resolve from config
    judge_model = bt_result["back_model"]
    judge_result = llm_judge_translation(
        original_source=source_text,
        back_translated_text=bt_result["back_translated_text"],
        source_lang=source_lang,
        model=judge_model,
        timeout=timeout,
    )

    faithfulness = judge_result.get("faithfulness_score", 0.0)

    # Step 3 — composite score (faithfulness only dimension available from
    # back-translation; terminology / style / readability are scored 0)
    # We also reuse calculate_quality_score for compatibility with the
    # existing scoring framework.
    composite = calculate_quality_score(
        faithfulness=faithfulness,
        terminology=None,
        style=None,
        readability=None,
    )
    composite_score = composite["composite"]

    return {
        "round": 1,
        "forward_model": bt_result["forward_model"],
        "back_model": bt_result["back_model"],
        "judge_model": judge_model,
        "faithfulness": faithfulness,
        "issues": judge_result.get("issues", []),
        "composite_score": composite_score,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_timeout() -> float | None:
    """Resolve the per-call LLM timeout (seconds) from config.

    Reads ``llm.timeout`` from the autoinfo config; returns ``None`` when
    no config can be loaded so callers fall back to litellm's default.
    """
    from autoinfo.config import Config, get_config_path, load_config  # noqa: PLC0415

    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
        else:
            config = Config()
        return float(config.llm.timeout)
    except Exception:
        return None


def _resolve_default_model() -> str:
    """Resolve default model string from config, falling back to default."""
    from autoinfo.config import Config, get_config_path, load_config  # noqa: PLC0415

    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
        else:
            config = Config()
    except Exception:
        config = Config()

    model = config.llm.resolve_model() or "openrouter/deepseek/deepseek-chat"
    return model


def _resolve_model_pool(model_pool: list[str] | None) -> list[str]:
    """Resolve the model pool from explicit list or config.

    When *model_pool* is a non-empty list it is returned as-is.
    When ``None``, the pool is built from config: the primary model
    (``provider/model``) plus any fallback models.
    """
    if model_pool:
        return [m for m in model_pool if m]

    pool: list[str] = []

    try:
        from autoinfo.config import Config, get_config_path, load_config  # noqa: PLC0415

        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
        else:
            config = Config()

        provider = config.llm.provider or "openrouter"
        model = config.llm.model or "deepseek/deepseek-chat"
        if "/" not in model:
            pool.append(f"{provider}/{model}")
        else:
            pool.append(model)

        # Add fallback models
        for fb in config.llm.fallback:
            fb_provider = fb.provider or provider
            fb_model = fb.model or model
            fb_full = f"{fb_provider}/{fb_model}"
            if fb_full not in pool:
                pool.append(fb_full)
    except Exception:
        pass

    if not pool:
        pool.append(_resolve_default_model())

    return pool


# ---------------------------------------------------------------------------
# Refinement — multi-round translation improvement
# ---------------------------------------------------------------------------


def refine_translation(
    source_text: str,
    initial_translation: str,
    source_lang: str,
    target_lang: str,
    judge_feedback: list[dict[str, str]],
    model: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Refine a translation based on judge feedback.

    Takes the source text, the initial (flawed) translation, language codes,
    and the judge's feedback (list of issues).  Constructs a prompt that
    incorporates the judge's feedback and calls the LLM with a lower
    temperature (0.1) for consistency.

    Parameters
    ----------
    source_text:
        Original source text.
    initial_translation:
        The forward-translated text that needs refinement.
    source_lang:
        Source language code (e.g. ``"en"``, ``"zh"``).
    target_lang:
        Target language code (e.g. ``"zh"``, ``"en"``).
    judge_feedback:
        List of issue dicts from the LLM judge, each with
        ``severity``, ``description``, and ``position`` keys.
    model:
        Optional model override.  Falls back to config / default when ``None``.

    Returns
    -------
    dict
        ``translation`` — the refined translation text (falls back to
        *initial_translation* on failure)
        ``model_used`` — the model used for refinement
    """
    if model is None:
        model = _resolve_default_model()

    if timeout is None:
        timeout = _resolve_timeout()

    # Format issues into a readable bullet list for the prompt
    issues_lines: list[str] = []
    for i, issue in enumerate(judge_feedback, 1):
        sev = issue.get("severity", "unknown")
        desc = issue.get("description", "")
        pos = issue.get("position", "")
        line = f"{i}. [{sev}] {desc}"
        if pos:
            line += f" (location: {pos})"
        issues_lines.append(line)

    issues_text = "\n".join(issues_lines) if issues_lines else (
        "No specific issues were identified, but the overall quality "
        "score was below the acceptable threshold."
    )

    prompt = (
        f"Translate the following text from {source_lang} to {target_lang}.\n\n"
        f"SOURCE TEXT ({source_lang}):\n{source_text[:4000]}\n\n"
        "A PREVIOUS TRANSLATION had the following issues identified "
        "by a quality evaluator:\n"
        f"{issues_text}\n\n"
        "Please provide a NEW translation that fixes ALL of the above issues. "
        "Pay special attention to accuracy, terminology, style, and readability.\n\n"
        f"IMPROVED TRANSLATION ({target_lang}):"
    )

    try:
        response = call_with_fallback(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a professional translator. Translate the given text "
                        f"from {source_lang} to {target_lang}. Return only the translated "
                        f"text, no explanations or commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.1,
            timeout=timeout,
        )

        translation: str = response.choices[0].message.content  # type: ignore[union-attr]
        if not translation or not translation.strip():
            logger.warning(
                "refine_translation: empty response from model %s", model
            )
            return {"translation": initial_translation, "model_used": model}

        return {"translation": translation.strip(), "model_used": model}

    except Exception as exc:
        logger.warning(
            "refine_translation: LLM call failed with %s: %s", model, exc
        )
        return {"translation": initial_translation, "model_used": model}


# ---------------------------------------------------------------------------
# Orchestrator — multi-round refinement pipeline
# ---------------------------------------------------------------------------


def _build_rounds_list(
    candidates: list[tuple[str, str, dict[str, Any] | None]],
) -> list[dict[str, Any]]:
    """Build the ``rounds`` list from pipeline candidates.

    Parameters
    ----------
    candidates:
        List of ``(translation, model_used, evaluation_dict_or_None)`` tuples
        accumulated during the refinement pipeline.

    Returns
    -------
    list[dict]
        Each entry: ``{round, model_used, faithfulness, composite, issues}``.
    """
    rounds: list[dict[str, Any]] = []
    for i, (_, model_used, ev) in enumerate(candidates):
        if ev is not None:
            rounds.append({
                "round": i + 1,
                "model_used": model_used,
                "faithfulness": ev.get("faithfulness", 0.0),
                "composite": ev.get("composite_score", 0.0),
                "issues": list(ev.get("issues", [])),
            })
        else:
            rounds.append({
                "round": i + 1,
                "model_used": model_used,
                "faithfulness": 0.0,
                "composite": 0.0,
                "issues": [],
            })
    return rounds


def run_refinement_pipeline(
    source_text: str,
    initial_translation: str,
    source_lang: str,
    target_lang: str,
    model_pool: list[str] | None = None,
    threshold: float = 70.0,
    max_rounds: int = 2,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run the multi-round translation refinement pipeline.

    Pipeline flow::

        evaluate initial translation
          ↓ score ≥ threshold? ──Yes──→ return immediately
          ↓ No
        refine with judge feedback ──→ re-evaluate
          ↓ score ≥ threshold? ──Yes──→ return best
          ↓ No  (repeat up to *max_rounds* times)
        pick best attempt across all rounds

    Parameters
    ----------
    source_text:
        Original source text.
    initial_translation:
        The forward-translated text to evaluate and potentially refine.
    source_lang:
        Source language code (e.g. ``"en"``, ``"zh"``).
    target_lang:
        Target language code (e.g. ``"zh"``, ``"en"``).
    model_pool:
        List of model names for forward/back translation.  First = primary
        model; subsequent models are tried for re-refinement.  Falls back
        to config when ``None``.
    threshold:
        Minimum composite score (0-100) to consider a translation acceptable.
        Defaults to 70.0.
    max_rounds:
        Maximum number of refinement iterations.  Defaults to 2.
        Use 0 to only evaluate without any refinement.

    Returns
    -------
    dict
        ``final_translation`` — best translation across all rounds
        ``rounds`` — list of per-round evaluation diagnostics::

            [
                {
                    "round": 1,
                    "model_used": "...",
                    "faithfulness": 85.0,
                    "composite": 72.5,
                    "issues": [...]
                },
                ...
            ]

        ``best_round_index`` — 0-based index into ``rounds`` for the
        highest-scoring candidate
    """
    pool = _resolve_model_pool(model_pool)
    primary_model: str = pool[0] if pool else _resolve_default_model()

    # candidates: (translation, model_used, evaluation_result_or_None)
    candidates: list[tuple[str, str, dict[str, Any] | None]] = [
        (initial_translation, primary_model, None)
    ]

    # --- Evaluate initial translation ---
    eval_result = run_back_translation_pipeline(
        source_text=source_text,
        translated_text=initial_translation,
        source_lang=source_lang,
        target_lang=target_lang,
        model_pool=model_pool,
        timeout=timeout,
    )
    candidates[0] = (initial_translation, primary_model, eval_result)

    # If initial translation is already good enough, return immediately
    if eval_result and eval_result.get("composite_score", 0.0) >= threshold:
        return {
            "final_translation": initial_translation,
            "rounds": _build_rounds_list(candidates),
            "best_round_index": 0,
        }

    # Accumulated issues across all evaluations (for the refine prompt)
    all_issues: list[dict[str, str]] = []
    if eval_result:
        all_issues.extend(eval_result.get("issues", []))

    # --- Refinement loop ---
    for refinement_idx in range(max_rounds):
        # Use a different model for round 2+ if available
        if refinement_idx == 0:
            refine_model = primary_model
        elif len(pool) >= 2:
            refine_model = pool[1]
        else:
            logger.warning(
                "run_refinement_pipeline: only one model in pool — "
                "reusing %s for round %d",
                primary_model,
                refinement_idx + 1,
            )
            refine_model = primary_model

        # Fetch the latest translation to refine
        latest_translation = candidates[-1][0]

        # --- Refine ---
        refined = refine_translation(
            source_text=source_text,
            initial_translation=latest_translation,
            source_lang=source_lang,
            target_lang=target_lang,
            judge_feedback=all_issues,
            model=refine_model,
            timeout=timeout,
        )

        # --- Re-evaluate ---
        new_result = run_back_translation_pipeline(
            source_text=source_text,
            translated_text=refined["translation"],
            source_lang=source_lang,
            target_lang=target_lang,
            model_pool=model_pool,
            timeout=timeout,
        )

        candidates.append((refined["translation"], refine_model, new_result))

        if new_result:
            all_issues.extend(new_result.get("issues", []))

            if new_result.get("composite_score", 0.0) >= threshold:
                logger.info(
                    "run_refinement_pipeline: round %d reached threshold %.1f",
                    refinement_idx + 2,
                    threshold,
                )
                break

    # --- Select best candidate ---
    rounds_data = _build_rounds_list(candidates)

    best_idx = 0
    best_score = -1.0
    for i, (_, _, ev) in enumerate(candidates):
        score = ev.get("composite_score", 0.0) if ev is not None else -1.0
        if score > best_score:
            best_score = score
            best_idx = i

    return {
        "final_translation": candidates[best_idx][0],
        "rounds": rounds_data,
        "best_round_index": best_idx,
    }
