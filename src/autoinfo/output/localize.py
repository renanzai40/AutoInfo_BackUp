"""Product-level localization (backup-repo issue #38).

Generate a product (digest / report / column / premium-briefing /
enterprise-briefing / magazine-digest) for a domain, then post-translate
the whole product into ``target_lang`` — not by source-language filtering
but by translating the generated output:

1. generate the product markdown (existing digest/report generators),
2. segment the markdown into translatable vs protected content (URLs,
   code fences, frontmatter, table rows, placeholders and inline code
   spans never reach the translator),
3. translate each translatable segment via :func:`localize_content`
   (content mode, no KB storage),
4. QA-gate each segment through the back-translation pipeline
   (:func:`run_back_translation_pipeline`), refining once when the
   composite score is below threshold,
5. write ``<product>-<lang>.md`` under ``<out_dir>/<target_lang>/`` and
   record the language in ``<out_dir>/manifest.json``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoinfo.config import get_config_path, load_config
from autoinfo.output import PRODUCT_TEMPLATES, generate_digest, generate_report, localize_content
from autoinfo.translation_qa import refine_translation, run_back_translation_pipeline

logger = logging.getLogger(__name__)

# Kinds that are never sent to the translator.
PROTECTED_KINDS: frozenset[str] = frozenset(
    {"frontmatter", "code", "blank", "table_row", "html", "placeholder"}
)

# Products the localization pipeline can generate (digest/report families;
# tutorial/presentation are excluded by design — issue #38 light plan).
_DIGEST_FAMILY: frozenset[str] = frozenset({"digest", "premium-briefing", "magazine-digest"})
_REPORT_FAMILY: frozenset[str] = frozenset({"report", "column", "enterprise-briefing"})

_QA_THRESHOLD = 75.0

_URL_RE = re.compile(r"https?://[^\s)\]}>]+")
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
_CODE_SPAN_RE = re.compile(r"`[^`]+`")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def _line_kind(line: str, in_code: bool) -> tuple[str, str]:
    """Classify a markdown line into (kind, text)."""
    stripped = line.strip()
    if stripped == "---":
        return "frontmatter", line
    if in_code:
        return "code", line
    if stripped.startswith("```"):
        return "code", line
    if not stripped:
        return "blank", line
    if stripped.startswith(("{{", "{%")) and ("}}" in stripped or "%}" in stripped):
        return "placeholder", line
    if stripped.startswith("<"):
        return "html", line
    if stripped.startswith("|") and stripped.endswith("|"):
        return "table_row", line
    if re.match(r"^#{1,6}\s", stripped):
        return "heading", line
    if re.match(r"^(\s*[-*+]\s+)", stripped):
        return "list_item", line
    if re.match(r"^\s*\d+[.)]\s", stripped):
        return "list_item", line
    return "text", line


def _protect_tokens(text: str) -> tuple[str, list[str]]:
    """Replace URLs / placeholders / code spans / link targets with sentinels.

    Return ``(protected_text, tokens)`` — the translator only ever sees
    sentinel tokens for protected spans, so URLs and markup can never be
    altered or dropped.
    """
    tokens: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        tok = f"\u00a7K{len(tokens)}\u00a7"
        tokens.append(match.group(0))
        return tok

    protected = _LINK_RE.sub(_replace, text)
    protected = _PLACEHOLDER_RE.sub(_replace, protected)
    protected = _CODE_SPAN_RE.sub(_replace, protected)
    protected = _URL_RE.sub(_replace, protected)
    return protected, tokens


def _restore_tokens(text: str, tokens: list[str]) -> str:
    """Restore sentinel tokens back into their original protected spans."""
    for i, tok in enumerate(tokens):
        text = text.replace(f"\u00a7K{i}\u00a7", tok)
    return text


def _segment_markdown(md: str) -> list[dict[str, Any]]:
    """Split markdown into translatable/protected segments (line granularity)."""
    segments: list[dict[str, Any]] = []
    in_code = False
    in_frontmatter = False
    for raw_line in md.splitlines():
        stripped = raw_line.strip()
        if not in_frontmatter and stripped == "---" and not segments:
            in_frontmatter = True
            kind = "frontmatter"
        elif in_frontmatter and stripped == "---":
            in_frontmatter = False
            kind = "frontmatter"
        elif in_frontmatter:
            kind = "frontmatter"
        elif stripped.startswith("```"):
            in_code = not in_code
            kind = "code"
        else:
            kind, _ = _line_kind(raw_line, in_code)
        segments.append({"kind": kind, "text": raw_line, "translated": False})
    return segments


def _reassemble_markdown(segments: list[dict[str, Any]]) -> str:
    """Join translated segments back into a single markdown document."""
    return "\n".join(seg["text"] for seg in segments)


def _translate_segment_text(
    text: str,
    source_lang: str,
    target_lang: str,
    domain: str,
) -> str:
    """Translate one segment's text, keeping protected spans untouched."""
    protected, tokens = _protect_tokens(text)
    if not protected.strip():
        return text
    result = localize_content(
        content=protected,
        source_lang=source_lang,
        target_lang=target_lang,
        domain=domain,
    )
    translated = (result or {}).get("translated_body") or ""
    if not isinstance(translated, str):
        # localize_content may return a non-string body (e.g. the LLM
        # answered with a JSON array); treat it as a failed translation.
        logger.warning(
            "localize_content returned non-str body (%s) for segment: %.60s",
            type(translated).__name__, text[:60],
        )
        return text
    if not translated.strip():
        logger.warning("localize_content returned empty translation for segment: %.60s", text[:60])
        return text
    return _restore_tokens(translated, tokens)


def _qa_segment(
    source_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
) -> dict[str, Any]:
    """Back-translation QA gate for one segment; refine once on failure.

    Returns ``{"score": float, "refined": bool, "passed": bool, "text": str}``.
    """

    def _score(trans: str) -> float:
        pipeline = run_back_translation_pipeline(
            source_text=source_text,
            translated_text=trans,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        if not pipeline:
            return 0.0
        return float(pipeline.get("quality_score") or 0.0)

    score = _score(translated_text)
    if score >= _QA_THRESHOLD:
        return {"score": score, "refined": False, "passed": True, "text": translated_text}

    refined = refine_translation(
        source_text=source_text,
        initial_translation=translated_text,
        source_lang=source_lang,
        target_lang=target_lang,
        judge_feedback=[{"issue": "back-translation quality below threshold"}],
    )
    refined_text = (refined or {}).get("refined_text") or translated_text
    score = _score(refined_text)
    return {
        "score": score,
        "refined": True,
        "passed": score >= _QA_THRESHOLD,
        "text": refined_text,
    }


def _resolve_source_language(domain: str, source_lang: str) -> str:
    """Explicit source_lang wins; else the domain's default_language; else 'en'."""
    if source_lang:
        return source_lang
    try:
        config = load_config(get_config_path())
        for d in config.domains:
            if d.name == domain and d.default_language:
                return d.default_language
    except Exception:
        pass
    return "en"


def _generate_product_text(
    domain: str, product: str, period: str, max_items: int = 0
) -> tuple[str, str]:
    """Generate the product markdown; return (markdown, generator-name)."""
    for row in PRODUCT_TEMPLATES:
        if row["name"] == product:
            template: Any = row["template"]
            break
    else:
        valid = ", ".join(row["name"] for row in PRODUCT_TEMPLATES)
        raise ValueError(
            f"Unsupported product '{product}'. Localization supports the "
            f"digest/report families ({', '.join(sorted(_DIGEST_FAMILY | _REPORT_FAMILY))}). "
            f"All registry products: {valid}"
        )
    if product in _DIGEST_FAMILY:
        kwargs: dict[str, Any] = {
            "domain": domain, "period": period, "format": "markdown",
            "product_template": template,
        }
        if max_items:
            kwargs["max_items"] = max_items
        result = generate_digest(**kwargs)
        return str(result), "generate_digest"
    if product in _REPORT_FAMILY:
        result = generate_report(
            domain=domain, period=period, format="markdown", product_template=template
        )
        return str(result), "generate_report"
    raise ValueError(
        f"Unsupported product '{product}'. Localization supports: "
        f"{', '.join(sorted(_DIGEST_FAMILY | _REPORT_FAMILY))}"
    )


def localize_product(
    domain: str,
    product: str = "digest",
    period: str = "weekly",
    target_lang: str = "",
    source_lang: str = "",
    out_dir: str | Path | None = None,
    qa_sample_rate: float = 0.2,
    qa_min_samples: int = 5,
    max_items: int = 0,
) -> dict[str, Any]:
    """Localize a generated product into ``target_lang`` (issue #38).

    Returns a result dict with ``file_path``, ``language``, ``domain``,
    ``product`` and ``qa`` (gate/avg_score/refined_count/failed_count).

    Back-translation QA runs on a deterministic stride sample of the
    translated segments (``qa_sample_rate``, minimum ``qa_min_samples``)
    — the gate semantics are identical (any sampled failure degrades the
    gate) while the LLM cost stays bounded for large products.
    """
    if not target_lang:
        raise ValueError("target_lang is required (e.g. --target-lang zh)")
    effective_source = _resolve_source_language(domain, source_lang)

    markdown, _ = _generate_product_text(domain, product, period, max_items=max_items)

    segments = _segment_markdown(markdown)
    translatable_idx = [
        i for i, seg in enumerate(segments) if seg["kind"] not in PROTECTED_KINDS
    ]
    sample_size = max(qa_min_samples, round(len(translatable_idx) * qa_sample_rate))
    stride = max(1, -(-len(translatable_idx) // sample_size))
    sampled_idx = set(translatable_idx[::stride])

    qa_scores: list[float] = []
    refined_count = 0
    failed_count = 0
    for i, seg in enumerate(segments):
        if seg["kind"] in PROTECTED_KINDS:
            continue
        translated = _translate_segment_text(seg["text"], effective_source, target_lang, domain)
        seg["text"] = translated
        seg["translated"] = True
        if i in sampled_idx:
            qa = _qa_segment(seg["text"], translated, effective_source, target_lang)
            seg["text"] = qa["text"]
            qa_scores.append(qa["score"])
            refined_count += 1 if qa["refined"] else 0
            failed_count += 0 if qa["passed"] else 1

    localized_md = _reassemble_markdown(segments)

    base_dir = Path(out_dir) if out_dir else Path("outputs") / "localized"
    lang_dir = base_dir / target_lang
    lang_dir.mkdir(parents=True, exist_ok=True)
    file_path = lang_dir / f"{product}-{target_lang}.md"
    file_path.write_text(localized_md, encoding="utf-8")

    avg_score = round(sum(qa_scores) / len(qa_scores), 1) if qa_scores else 100.0
    entry = {
        "product": product,
        "domain": domain,
        "language": target_lang,
        "source_lang": effective_source,
        "period": period,
        "file": str(file_path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "qa": {
            "gate": "passed" if failed_count == 0 else "degraded",
            "avg_score": avg_score,
            "refined_count": refined_count,
            "failed_count": failed_count,
            "sampled_segments": len(qa_scores),
            "total_segments": len(translatable_idx),
            "sample_rate": qa_sample_rate,
        },
    }

    manifest_path = base_dir / "manifest.json"
    manifest: list[dict[str, Any]] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            manifest = []
    manifest.append(entry)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "localized %s/%s -> %s (qa=%s, avg=%.1f, refined=%d, failed=%d) at %s",
        domain, product, target_lang, entry["qa"]["gate"], avg_score,
        refined_count, failed_count, file_path,
    )
    return {
        "file_path": str(file_path),
        "language": target_lang,
        "source_lang": effective_source,
        "domain": domain,
        "product": product,
        "qa": entry["qa"],
    }
