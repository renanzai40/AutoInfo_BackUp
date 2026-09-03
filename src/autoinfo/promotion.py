"""Promotion admission checks for the KB curation pipeline (plan todo T3).

Standalone, **read-only** admission gate evaluated before a 02-Draft entry
is promoted to 03-Wiki (wired into ``KBStore.promote_kb_draft`` by T2).
It reuses the existing quality-gate machinery — G0 schema integrity and
G4 factual consistency from :mod:`autoinfo.quality` — and never mutates
the KB, never writes ``_failed/`` diagnostics, and does not change the
processing pipeline's G0-G4 behavior.

Five components, evaluated in order:

(a) **Provenance completeness** — ``entry.source_ids`` (the ``source_raw_ids``
    carried forward by T1) is non-empty and every referenced 01-Raw entry
    resolves with non-empty ``source_url`` / ``source_type`` /
    ``source_platform`` (AGENTS.md mandatory provenance).
(b) **G0 schema re-check** — the draft itself passes
    :class:`~autoinfo.quality.G0SchemaIntegrity`.
(c) **G1 source authority** — ``entry.source_score`` >= threshold (default 30).
(d) **G3 relevance** — ``entry.relevance_score`` >= threshold (default 30).
(e) **CurationGate G4** — when enabled (default) the draft's final body text
    is re-checked by :class:`~autoinfo.quality.G4FactualConsistency`; a fail
    is a hard reject.

Thresholds come from the per-domain ``quality_gates`` config when present:
the ``G1-SourceAuthority`` / ``G3-RelevanceScoring`` keys take precedence,
falling back to the ``CurationGate`` threshold (T4 will wire this key; T3
tolerates its absence with the default 30/30 and G4 **on** by default).
Deterministic checks (a)-(d) accumulate every rejection reason; G4 (an LLM
call) only runs when they are clean — fail-fast, no wasted LLM spend.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from autoinfo.config import Config, QualityGateConfig
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.quality import G0SchemaIntegrity, G4FactualConsistency, QualityResult

#: Default G1/G3 admission threshold when no per-domain config is present.
DEFAULT_GATE_THRESHOLD: float = 30.0

_G0_GATE_KEY = "G0-SchemaIntegrity"
_G1_GATE_KEY = "G1-SourceAuthority"
_G3_GATE_KEY = "G3-RelevanceScoring"
_G4_GATE_KEY = "G4-SummaryFactual"
_CURATION_GATE_KEY = "CurationGate"


class RejectionReason(StrEnum):
    """Typed, machine-readable reasons for a promotion rejection.

    A pass carries exactly ``OK``; every failed component appends its own
    reason code so callers can route/handle rejections without parsing prose.
    """

    OK = "ok"
    PROVENANCE_MISSING = "missing-source-provenance"
    PROVENANCE_UNRESOLVABLE = "unresolvable-source"
    PROVENANCE_INCOMPLETE = "incomplete-source-provenance"
    G0_SCHEMA_FAILED = "g0-schema-failed"
    SOURCE_SCORE_BELOW_THRESHOLD = "source-score-below-threshold"
    RELEVANCE_BELOW_THRESHOLD = "relevance-below-threshold"
    G4_FACTUAL_FAILED = "g4-factual-failed"


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Outcome of a promotion admission check.

    Attributes
    ----------
    allowed:
        ``True`` only when every component passed.
    reasons:
        ``[RejectionReason.OK]`` on a pass; otherwise one typed reason code
        per failed component (deterministic components all reported).
    """

    allowed: bool
    reasons: list[RejectionReason] = field(default_factory=list)


def check_promotion_admission(
    entry: KBEntry,
    domain: str,
    config: Config | None,
    *,
    resolve_raw: Callable[[str], KBEntry | None] | None = None,
) -> AdmissionResult:
    """Evaluate all five admission components for *entry*.

    Parameters
    ----------
    entry:
        The 02-Draft entry about to be promoted.
    domain:
        Domain name — resolves the per-domain ``quality_gates`` config.
    config:
        Project configuration.  ``None`` (no config) falls back to the
        default thresholds and G4 enabled.
    resolve_raw:
        Callable resolving a ``source_raw_ids`` reference to its 01-Raw
        entry, or ``None`` when the entry is not found.  When omitted the
        check **fails closed** — provenance cannot be verified.

    Returns
    -------
    AdmissionResult
        ``allowed=True`` with ``reasons=[OK]`` on a full pass; otherwise
        ``allowed=False`` with one typed reason per failed component.
    """
    gate_config = _per_domain_gate_config(config, domain)
    curation = gate_config.get(_CURATION_GATE_KEY) if gate_config else None

    shared_default = _curation_threshold(curation) or DEFAULT_GATE_THRESHOLD
    g1_threshold = _gate_threshold(gate_config, _G1_GATE_KEY, shared_default)
    g3_threshold = _gate_threshold(gate_config, _G3_GATE_KEY, shared_default)

    reasons: list[RejectionReason] = []

    # (a) Provenance completeness — fail closed when unresolved.
    reasons.extend(_check_provenance(entry, resolve_raw))

    # (b) G0 schema re-check of the draft itself (existing checker).
    if not _check_g0_schema(entry, gate_config):
        reasons.append(RejectionReason.G0_SCHEMA_FAILED)

    # (c) G1 source authority (score carried forward from Raw by T1).
    if entry.source_score < g1_threshold:
        reasons.append(RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD)

    # (d) G3 relevance.
    if entry.relevance_score < g3_threshold:
        reasons.append(RejectionReason.RELEVANCE_BELOW_THRESHOLD)

    # (e) CurationGate G4 — only when deterministic checks are clean
    # (fail-fast: never spend an LLM call on an already-rejected draft).
    if not reasons and _curation_enabled(curation):
        g4_result = _run_g4_check(entry, config, gate_config)
        if not g4_result.passed:
            reasons.append(RejectionReason.G4_FACTUAL_FAILED)

    if reasons:
        return AdmissionResult(allowed=False, reasons=reasons)
    return AdmissionResult(allowed=True, reasons=[RejectionReason.OK])


# ---------------------------------------------------------------------------
# (a) Provenance
# ---------------------------------------------------------------------------


def _check_provenance(
    entry: KBEntry,
    resolve_raw: Callable[[str], KBEntry | None] | None,
) -> list[RejectionReason]:
    """Check that every referenced Raw entry resolves with full provenance."""
    source_ids = entry.source_ids or []
    if not source_ids:
        return [RejectionReason.PROVENANCE_MISSING]
    if resolve_raw is None:
        # No resolver supplied — provenance cannot be verified (fail closed).
        return [RejectionReason.PROVENANCE_UNRESOLVABLE]

    reasons: list[RejectionReason] = []
    for raw_id in source_ids:
        raw = resolve_raw(raw_id)
        if raw is None:
            reasons.append(RejectionReason.PROVENANCE_UNRESOLVABLE)
        elif not _has_mandatory_provenance(raw):
            reasons.append(RejectionReason.PROVENANCE_INCOMPLETE)
    return reasons


def _has_mandatory_provenance(raw: KBEntry) -> bool:
    """AGENTS.md mandatory provenance: source_url / source_type / source_platform."""
    return bool(raw.source_url) and bool(raw.source_type) and bool(raw.source_platform)


# ---------------------------------------------------------------------------
# (b) G0 schema re-check — delegates to the existing G0 checker
# ---------------------------------------------------------------------------


def _check_g0_schema(
    entry: KBEntry,
    gate_config: dict[str, QualityGateConfig] | None,
) -> bool:
    g0 = G0SchemaIntegrity()
    g0_config = gate_config.get(_G0_GATE_KEY) if gate_config else None
    return g0.check(entry.to_dict(), None, g0_config).passed


# ---------------------------------------------------------------------------
# (e) CurationGate G4 — delegates to the existing G4 checker (LLM)
# ---------------------------------------------------------------------------


def _run_g4_check(
    entry: KBEntry,
    config: Config | None,
    gate_config: dict[str, QualityGateConfig] | None,
) -> QualityResult:
    """Re-check the draft's final body text against its summary via G4.

    Mirrors the ``run_processing`` G4 wrapper (process.py): resolves the
    model string from config and calls :meth:`G4FactualConsistency.check`
    with the draft body as source text and the draft summary as TL;DR.
    A ``retries=0`` gate config keeps the legacy single-call path, so the
    checker never writes ``_failed/`` diagnostics — this wrapper is
    read-only (``_failed/`` routing is T2's concern).

    When *config* is ``None`` the on-disk project config is loaded (same
    fallback as :func:`autoinfo.llm.call_with_fallback`) so the G4 model
    resolves to the configured provider/model — the historical hardcoded
    ``openrouter/deepseek/deepseek-chat`` default (an unsupported model)
    previously blocked every promotion when callers omitted ``config``
    (#283).  Issue #195: the model resolves softly through
    ``resolve_model_or_empty`` — the real G4 gate's own constructor then
    raises :class:`JudgmentModelNotConfiguredError` when truly unconfigured
    (never a guessed vendor default), while an injected test double accepts
    the empty model.
    """
    if config is None:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        try:
            config = load_config(config_path) if config_path is not None else None
        except Exception:
            config = None

    if config is not None:
        from autoinfo.config import resolve_model_or_empty

        # Soft resolution: the deployment's configured model, or "" when
        # unconfigured — the G4 gate's own constructor then raises
        # JudgmentModelNotConfiguredError for the REAL gate (issue #195),
        # while an injected test double accepts the empty model.  Never a
        # hardcoded vendor default; never double-prefix.
        model_name = resolve_model_or_empty(config.llm)
        json_mode = bool(config.llm.json_mode)
        timeout = config.llm.timeout
    else:
        # No config at all — same soft path; the real G4 raises on its own.
        model_name = ""
        json_mode = False
        timeout = None

    g4_config = gate_config.get(_G4_GATE_KEY) if gate_config else None
    if g4_config is not None:
        g4_config = replace(g4_config, retries=0)

    g4 = G4FactualConsistency(
        model=model_name,
        json_mode=json_mode,
        timeout=timeout,
        api_key=(config.llm.api_key or None) if config else None,
        base_url=(config.llm.base_url or None) if config else None,
    )
    return g4.check(
        _item_from_entry(entry, _draft_body(entry)),
        ExtractionResult(item_id=entry.entry_id, tl_dr=entry.summary),
        gate_config=g4_config,
    )


def _draft_body(entry: KBEntry) -> str:
    """Return the draft's body text (YAML frontmatter stripped) when it exists.

    Read-only: no writes, and an empty result is returned when the draft
    file is not available (G4 then trivially passes or sees an empty source).
    """
    if not entry.file_path:
        return ""
    path = Path(entry.file_path)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _item_from_entry(entry: KBEntry, content: str) -> Item:
    """Map the draft onto an :class:`Item` for the G4 checker."""
    return Item(
        id=entry.entry_id,
        source_name="",
        source_type=entry.source_type,
        source_url=entry.source_url,
        title=entry.title,
        content=content,
        source_platform=entry.source_platform,
        domain=entry.domain,
        quality_tier=entry.quality_tier,
        language=entry.language,
    )


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def _per_domain_gate_config(
    config: Config | None,
    domain: str,
) -> dict[str, QualityGateConfig]:
    """Merge global ``quality_gates`` with the domain's overrides.

    Mirrors ``run_processing`` (process.py): global defaults first, then
    the domain's own entries take precedence.
    """
    merged: dict[str, QualityGateConfig] = {}
    if config is None:
        return merged
    merged.update(config.quality_gates)
    for d in config.domains:
        if d.name == domain:
            merged.update(d.quality_gates)
            break
    return merged


def _gate_threshold(
    gate_config: dict[str, QualityGateConfig] | None,
    key: str,
    default: float,
) -> float:
    """Read ``threshold`` from a gate's :class:`QualityGateConfig` (default fallback)."""
    cfg = gate_config.get(key) if gate_config else None
    if cfg is None:
        return default
    threshold = cfg.threshold
    if threshold is None:
        return default
    return float(threshold)


def _curation_threshold(
    curation: QualityGateConfig | Mapping[str, object] | None,
) -> float | None:
    """Read the ``CurationGate`` threshold — tolerates the future T4 shape.

    ``CurationGate`` may arrive as a :class:`QualityGateConfig` or a raw
    dict (T4's ``set_gate_config`` persistence); ``None`` (key absent) is
    tolerated and yields the default threshold.
    """
    if curation is None:
        return None
    value: object
    if isinstance(curation, Mapping):
        value = curation.get("threshold")
    else:
        value = getattr(curation, "threshold", None)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _curation_enabled(
    curation: QualityGateConfig | Mapping[str, object] | None,
) -> bool:
    """Read the ``CurationGate`` G4 flag — **on by default** when absent."""
    if curation is None:
        return True
    if isinstance(curation, Mapping):
        value: object = curation.get("enabled", True)
    else:
        value = getattr(curation, "enabled", True)
    return bool(value)
