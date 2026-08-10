"""Processing pipeline — LLM extraction → quality gates → KB storage.

Reads cached items from ``collections/<domain>/``, runs LLM extraction,
applies quality gates (G1-G3), and stores results in the knowledge base.

Typical usage::

    >>> from autoinfo.process import run_processing
    >>> result = run_processing("medical-research")
    >>> print(f"{result.kb_entries_created} entries created")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoinfo.config import Config, DomainConfig, QualityGateConfig, get_config_path, load_config
from autoinfo.kb import _FTS5_STOPWORDS, KBStore, PromotionRejected
from autoinfo.keywords import KeywordsFile, KeywordState
from autoinfo.llm import LLMExtractor
from autoinfo.models import Item
from autoinfo.quality import (
    G0SchemaIntegrity,
    G4FactualConsistency,
    G5TranslationAccuracy,
    QualityResult,
    check_inline_tags,
    check_length_ratio,
    check_source_copy,
    check_terminology,
    llm_judge,
    run_quality_gates,
)

logger = logging.getLogger(__name__)

# Minimal stop sets for keyword auto-discovery (Step e in processing pipeline)
# — augmented with the richer FTS5 stopword list from kb.py.
_STOP_WORDS: frozenset[str] = frozenset({
    "the", "this", "that", "with", "from", "have", "been", "were",
    "their", "which", "about", "study", "also", "show", "shown",
    "using", "used", "may", "results", "result", "method", "methods",
    "however", "conclusion", "background", "objective", "aim",
}) | _FTS5_STOPWORDS
_STOP_PHRASES: frozenset[str] = frozenset({"", "  ", "   "})


def _is_valid_discovery_keyword(candidate: str, min_length: int = 2) -> bool:
    """Return ``True`` when *candidate* is fit for keyword auto-discovery.

    A candidate passes when, after trimming and lower-casing, it is at
    least ``min_length`` chars, contains at least one letter, and is not
    a stopword or a stopword-only phrase.  Multi-word candidates are
    additionally rejected when any constituent word is digit/punctuation
    only (e.g. ``"results 2024"``).
    """
    text = candidate.strip().lower()
    if not text or len(text) < min_length:
        return False
    if text in _STOP_PHRASES or text in _STOP_WORDS:
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    words = text.split()
    if len(words) > 1:
        if any(not any(ch.isalpha() for ch in w) for w in words):
            return False
        if all(w in _STOP_WORDS for w in words):
            return False
    return True

# Parallel processing (issue #136): LLM extraction dominates per-item latency,
# so items are processed concurrently in a bounded thread pool.  Default 5
# workers; override with AUTOINFO_PROCESS_WORKERS (clamped to 1..8).
_DEFAULT_PROCESS_WORKERS = 5
_PROCESS_WORKER_CAP = 8

# Serializes SQLite / markdown KB writes (store_entry, store_entities, CEFR
# frontmatter updates) so concurrent workers never contend on the same file.
_STORAGE_LOCK = threading.Lock()


def _resolve_process_workers() -> int:
    """Resolve the processing thread-pool size from ``AUTOINFO_PROCESS_WORKERS``."""
    try:
        raw = int(os.environ.get("AUTOINFO_PROCESS_WORKERS", _DEFAULT_PROCESS_WORKERS))
    except (TypeError, ValueError):
        raw = _DEFAULT_PROCESS_WORKERS
    return max(1, min(raw, _PROCESS_WORKER_CAP))


def _progress_enabled() -> bool:
    """Return ``True`` when per-item progress lines should be printed.

    Enabled for interactive terminals, or explicitly via
    ``AUTOINFO_PROCESS_PROGRESS`` (any value except ``0``/``false``/``off``).
    Disabled by default when stdout is piped — the MCP server speaks
    JSON-RPC over stdio and CLI ``--json`` output must stay parseable.
    """
    raw = os.environ.get("AUTOINFO_PROCESS_PROGRESS")
    if raw is not None:
        return raw.strip().lower() not in ("0", "false", "off", "")
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_language(text: str) -> str:
    """Auto-detect the language of *text* using ``langdetect``.

    Returns a language code (e.g. ``"en"``, ``"zh-cn"``) when confidence
    is ≥ 0.8 and text has ≥ 20 characters.  Returns ``"unknown"`` for
    short/noisy text or when detection fails.

    .. note::
        Non-blocking — returns ``"unknown"`` when ``langdetect`` is not
        installed or ``LangDetectException`` is raised.
    """
    if len(text.strip()) < 20:
        return "unknown"
    try:
        from langdetect import LangDetectException as _LDE  # noqa: N814
        from langdetect import detect_langs
    except ImportError:
        logger.debug("langdetect not installed — language detection disabled")
        return "unknown"

    try:
        langs = detect_langs(text)
        if not langs:
            return "unknown"
        top = langs[0]
        if top.prob < 0.8:
            return "unknown"
        return top.lang
    except _LDE:
        return "unknown"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ProcessResult:
    """Aggregate result of a processing run.

    Parameters
    ----------
    domain : str
        Domain that was processed.
    total_items : int
        Total number of cached items loaded.
    processed_count : int
        Number of items processed in this run (batch or full).
    remaining_count : int
        Number of items not yet processed (0 when batch is complete).
    is_complete : bool
        True when all cached items have been processed.
    passed_gates : int
        Number of items that passed all quality gates (G2 + G3).
    kb_entries_created : int
        Number of KB entries actually written.
    errors : list[dict]
        Per-item error details.
    duration_s : float
        Wall-clock duration of the run.
    per_item_logs : list[dict]
        Log entry for each processed item (model, duration, scores).
    """

    domain: str
    total_items: int = 0
    processed_count: int = 0
    remaining_count: int = 0
    is_complete: bool = True
    passed_gates: int = 0
    kb_entries_created: int = 0
    errors: list[dict] = field(default_factory=list)
    duration_s: float = 0.0
    per_item_logs: list[dict] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "items_with_usage": 0,
    })


# ---------------------------------------------------------------------------
# Cache loading
# ---------------------------------------------------------------------------


def load_cached_items(domain: str, base_path: str | Path = "collections") -> list[Item]:
    """Read cached items from ``collections/<domain>/<source>/<date>/<id>.json``.

    Parameters
    ----------
    domain : str
        Domain to load cached items for.
    base_path : str | Path, optional
        Root path for the collections directory (defaults to ``"collections"``).
        Useful for testing with temporary directories.

    Returns
    -------
    list[Item]
        Deserialized items (empty list when no cache directory exists).
    """
    items: list[Item] = []
    base_dir = Path(base_path) / domain

    if not base_dir.is_dir():
        logger.info("No cached items found for domain '%s'", domain)
        return items

    for source_dir in sorted(base_dir.iterdir()):
        if not source_dir.is_dir() or source_dir.name.startswith("_"):
            continue
        for date_dir in sorted(source_dir.iterdir()):
            if not date_dir.is_dir() or date_dir.name.startswith("_"):
                continue
            for json_file in sorted(date_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    # Pre-validate: skip non-dict JSON values (list, str, number, …)
                    if not isinstance(data, dict):
                        logger.warning(
                            "Skipping cache file %s: expected a JSON object, got %s",
                            json_file,
                            type(data).__name__,
                        )
                        continue
                    items.append(Item.from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed cache file %s: %s", json_file, exc
                    )

    logger.info("Loaded %d cached items for domain '%s'", len(items), domain)
    return items


# ---------------------------------------------------------------------------
# SQLite progress tracking (for batch processing)
# ---------------------------------------------------------------------------


def _get_progress_db_path() -> Path:
    """Return the path to the shared SQLite database used by ``KBStore``."""
    return Path("knowledge").resolve().parent / "autoinfo.db"


def _init_progress_table(conn: sqlite3.Connection) -> None:
    """Create the ``processing_progress`` table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processing_progress (
            domain                  TEXT PRIMARY KEY,
            last_processed_index    INTEGER NOT NULL DEFAULT 0,
            total_items             INTEGER NOT NULL DEFAULT 0
        )
    """)


def _read_progress(domain: str) -> dict:
    """Read the persisted processing progress for *domain*.

    Returns
    -------
    dict
        Keys: ``last_processed_index`` (int), ``total_items`` (int).
        Returns zeroed values when no progress row exists.
    """
    db_path = _get_progress_db_path()
    # If the db does not exist yet there is no progress
    if not db_path.is_file():
        return {"last_processed_index": 0, "total_items": 0}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _init_progress_table(conn)
            row = conn.execute(
                "SELECT last_processed_index, total_items FROM processing_progress WHERE domain = ?",  # noqa: E501
                (domain,),
            ).fetchone()
            if row is not None:
                return {"last_processed_index": row[0], "total_items": row[1]}
    except sqlite3.OperationalError:
        logger.warning("Could not read processing progress for '%s'", domain)
    return {"last_processed_index": 0, "total_items": 0}


def _write_progress(domain: str, last_processed_index: int, total_items: int) -> None:
    """Persist the current processing progress for *domain*."""
    db_path = _get_progress_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _init_progress_table(conn)
            conn.execute(
                """INSERT OR REPLACE INTO processing_progress
                   (domain, last_processed_index, total_items)
                   VALUES (?, ?, ?)""",
                (domain, last_processed_index, total_items),
            )
    except sqlite3.OperationalError as exc:
        logger.warning("Could not write processing progress: %s", exc)


def _reset_progress(domain: str) -> None:
    """Delete the progress row for *domain* (forces a full re-process)."""
    db_path = _get_progress_db_path()
    if not db_path.is_file():
        return
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "DELETE FROM processing_progress WHERE domain = ?",
                (domain,),
            )
    except sqlite3.OperationalError:
        pass


# ---------------------------------------------------------------------------
# CEFR classification helper (non-blocking, post-store)
# ---------------------------------------------------------------------------


def _update_index_cefr(entry_id: str, cefr_level: str) -> None:
    """Persist *cefr_level* on the SQLite index row for *entry_id*.

    Non-blocking: any failure is logged and swallowed.
    """
    try:
        store = KBStore(min_content_chars=50)
        with store.index._connect() as conn:
            conn.execute(
                "UPDATE entries SET cefr = ? WHERE entry_id = ?",
                (cefr_level, entry_id),
            )
    except Exception as exc:
        logger.debug("Failed to update cefr in index for %s: %s", entry_id, exc)


def _classify_entry_cefr(
    entry: Any,
    item: Item,
    config: Config,
) -> None:
    """Run CEFR classification on *item* and store result in entry frontmatter.

    Called after ``store_entry()``.  Failures are logged but do **not**
    propagate — classification must never block entry creation.

    Steps
    -----
    1. Determine language from the item (detected language or config default).
    2. If the language is not in ``config.cefr.languages``, skip.
    3. Call ``classify_text()``.
    4. If a level was returned (not "unknown"), write it to the frontmatter
       of the entry's Markdown file as ``cefr: <level>``.
    """
    try:
        # Determine language: use detected language, or fall back to "en"
        lang = item.language or "en"
        # Normalize: langdetect returns "zh-cn" etc. — take the base
        lang = lang.split("-")[0] if lang else "en"

        # Check if language is configured for CEFR
        if lang not in config.cefr.languages:
            return

        # Build model config from the effective LLM config
        model_config: dict[str, Any] = {}
        if config.cefr.model:
            model_config["model"] = config.cefr.model
        elif config.llm.provider and config.llm.model:
            model_config["model"] = config.llm.resolve_model()
        if config.llm.api_key:
            model_config["api_key"] = config.llm.api_key
        if config.llm.base_url:
            model_config["base_url"] = config.llm.base_url
        if config.llm.timeout:
            model_config["timeout"] = config.llm.timeout

        # Classify the text (title + content, truncated)
        text_for_classification = f"{item.title}\n\n{item.content}"[:3000]
        from autoinfo.cefr import classify_text

        result = classify_text(
            text=text_for_classification,
            lang=lang,
            model_config=model_config,
        )

        cefr_level = result.get("cefr_level", "unknown")
        if cefr_level != "unknown":
            from autoinfo.kb import update_frontmatter_field

            update_frontmatter_field(
                file_path=entry.file_path,
                key="cefr",
                value=cefr_level,
            )
            _update_index_cefr(entry.entry_id, cefr_level)
            logger.debug(
                "CEFR classification for %s: %s (confidence=%.2f)",
                entry.entry_id,
                cefr_level,
                result.get("confidence", 0.0),
            )
    except Exception as exc:
        logger.debug(
            "CEFR classification skipped for item %s: %s",
            getattr(item, "id", "?"),
            exc,
        )


# ---------------------------------------------------------------------------
# Processing pipeline
# ---------------------------------------------------------------------------


def _build_config_with_model(
    config: Config | None,
    model: str | None,
) -> Config | None:
    """Return a *config* copy with the LLM model overridden.

    When *model* contains a ``/`` it is treated as ``provider/model``;
    otherwise only the model name is replaced and the provider is kept
    from the original config (or left empty).
    """
    if model is None:
        return config

    from copy import deepcopy

    if config is not None:
        cfg = deepcopy(config)
    else:
        # Minimal config so LLMExtractor can resolve the model string
        from autoinfo.config import LLMConfig

        cfg = Config(llm=LLMConfig())

    if "/" in model:
        provider, model_name = model.split("/", 1)
        cfg.llm.provider = provider
        cfg.llm.model = model_name
    else:
        cfg.llm.model = model

    return cfg


# ---------------------------------------------------------------------------
# Failed-item diagnostics writer
# ---------------------------------------------------------------------------


def _write_failed_item(
    failed_dir: Path,
    item: Item,
    result: QualityResult,
    gate: str,
) -> None:
    """Write blocked-item diagnostics to ``collections/<domain>/_failed/<item_id>.json``.

    Parameters
    ----------
    failed_dir : Path
        The ``collections/<domain>/_failed/`` directory (already created).
    item : Item
        The item that was blocked.
    result : QualityResult
        The quality gate result that caused the block.
    gate : str
        Gate identifier (e.g. ``"G0"``, ``"G4"``).
    """
    diagnostics: dict[str, Any] = {
        "item_id": item.id,
        "source_url": item.source_url,
        "gate": gate,
        "gate_result": {
            "passed": result.passed,
            "score": result.score,
            "details": result.details,
        },
        "item_snapshot": {
            "id": item.id,
            "source_name": item.source_name,
            "source_type": item.source_type,
            "source_url": item.source_url,
            "title": item.title,
            "domain": item.domain,
            "language": item.language,
            "collected_at": item.collected_at,
        },
    }
    failed_path = failed_dir / f"{item.id}.json"
    with open(failed_path, "w", encoding="utf-8") as fh:
        json.dump(diagnostics, fh, indent=2, ensure_ascii=False)
    logger.warning(
        "%s blocked item %s — diagnostics written to %s",
        gate,
        item.id,
        failed_path,
    )


def run_processing(
    domain: str,
    model: str | None = None,
    topic: str | None = None,
    batch_size: int = 0,
    check_factual: bool = False,
    check_translation: bool = False,
    auto_promote: bool = False,
) -> ProcessResult:
    """Main processing pipeline.

    Steps
    -----
    1. Load cached items from ``collections/<domain>/``.
    2. If *batch_size* > 0, read SQLite progress to determine the starting
       index and only process up to *batch_size* items.
    3. For each item:
        a. LLM extraction  (call :meth:`LLMExtractor.extract`)
        b. Quality gates   (call :func:`run_quality_gates`; optionally G4
                           factual consistency when *check_factual* is set,
                           and optionally G5 translation accuracy when
                           *check_translation* is set)
        c. KB storage      (call :meth:`KBStore.store_entry`)
       d. Per-item log    (model, duration, scores, flags, …)
    4. When *batch_size* > 0, persist the updated progress index.
    5. Return a :class:`ProcessResult` with summary stats (including
       ``processed_count``, ``remaining_count``, ``is_complete``).

    If an individual item fails at any step the pipeline **continues**
    to the next item — a single failure does not abort the run.

    Parameters
    ----------
    domain : str
        Domain to process (e.g. ``"medical-research"``).
    model : str, optional
        LLM model override (e.g. ``"deepseek/deepseek-chat"`` or
        ``"gpt-4o-mini"``).  When *model* contains a ``/`` it is parsed
        as ``provider/model``; otherwise the provider from the config is
        kept.
    topic : str, optional
        Topic name used to resolve keywords for the G3 relevance gate.
        When omitted the gate scores without keywords (always passes).
    batch_size : int, optional
        Max number of items to process in this run.  When 0 (default)
        all cached items are processed.  When > 0, progress is tracked
        in SQLite and subsequent calls pick up where the last call
        stopped.
    check_factual : bool, optional
        When ``True``, run the G4 factual consistency gate after G1-G3
        (requires an LLM call per item).  Defaults to ``False``.
    check_translation : bool, optional
        When ``True``, run the G5 translation accuracy gate after G4
        (requires an LLM call per item).  Defaults to ``False``.
    auto_promote : bool, optional
        When ``True``, each item that passes extraction + quality gates is
        automatically admission-checked via the curation gate and promoted
        to 03-Wiki when eligible (per-entry try/except — a rejection or
        unexpected failure never aborts the run; rejected items stay in
        02-Draft with a ``_failed/`` marker).  Defaults to ``False``.

    Returns
    -------
    ProcessResult
        Aggregate result with per-item logs.
    """
    start_time = time.time()

    # -- Load configuration -------------------------------------------------
    config_path = get_config_path()
    config: Config | None = None
    if config_path is not None:
        config = load_config(config_path)

    # -- Load cached items --------------------------------------------------
    cached_items = load_cached_items(domain)
    total_items = len(cached_items)

    # -- Determine which items to process (batch vs full) --------------------
    new_index = 0
    if batch_size > 0:
        progress = _read_progress(domain)
        start_index: int = progress["last_processed_index"]  # type: ignore[assignment]
        persisted_total: int = progress["total_items"]  # type: ignore[assignment]

        # If the cache grew (new items collected), restart from 0 so nothing
        # is missed.  If it shrank, also reset to avoid an out-of-range slice.
        if persisted_total != total_items:
            start_index = 0

        items_slice = cached_items[start_index : start_index + batch_size]
        processed_count = len(items_slice)
        new_index = start_index + processed_count
        remaining_count = total_items - new_index
        is_complete = new_index >= total_items
    else:
        items_slice = cached_items
        processed_count = total_items
        remaining_count = 0
        is_complete = True

    result = ProcessResult(
        domain=domain,
        total_items=total_items,
        processed_count=processed_count,
        remaining_count=remaining_count,
        is_complete=is_complete,
    )

    if not items_slice:
        result.duration_s = round(time.time() - start_time, 3)
        logger.info("No items to process for domain '%s'", domain)
        return result

    # -- Initialise components ----------------------------------------------
    proc_config = _build_config_with_model(config, model)
    extractor = LLMExtractor(config=proc_config)
    kb_store = KBStore(min_content_chars=50)

    # Load existing entries for G2 dedup checking
    # Convert SQLite dicts back to KBEntry objects for type safety.
    # Filter row dicts to only KBEntry's dataclass fields — SQLite may
    # return extra columns (created_at, cefr, etc.) that KBEntry doesn't
    # accept as constructor args.
    from dataclasses import fields as _dc_fields

    from autoinfo.models import KBEntry
    _KB_FIELDS = {f.name for f in _dc_fields(KBEntry)}  # noqa: N806
    existing_entries_raw = kb_store.list_entries(domain, limit=10000)
    existing_entries: list[KBEntry] = [
        KBEntry(**{k: v for k, v in row.items() if k in _KB_FIELDS})
        for row in existing_entries_raw
    ]

    # Deserialize JSON fields (tags, custom_fields) stored as JSON strings in SQLite
    import json

    for i, row in enumerate(existing_entries_raw):
        tags = row.get("tags")
        cf = row.get("custom_fields")
        if isinstance(tags, str):
            existing_entries[i].tags = json.loads(tags)
        if isinstance(cf, str):
            existing_entries[i].custom_fields = json.loads(cf)

    # Resolve topic keywords from domain config (for G3)
    topic_keywords: list[str] = []
    if config and topic:
        for d in config.domains:
            if d.name == domain:
                for t in d.topics:
                    if t.name == topic:
                        topic_keywords = t.keywords
                        break

    # Resolve gate config: merge global defaults with domain overrides
    gate_config: dict[str, QualityGateConfig] = {}
    if config:
        # Start with global quality_gates
        gate_config.update(config.quality_gates)
        # Override with domain-specific config
        for d in config.domains:
            if d.name == domain:
                gate_config.update(d.quality_gates)
                break

    # Resolve the domain config for keyword auto-discovery (#179): toggle,
    # AUTO_ADDED cap and minimum candidate length.  Defaults (on / 100 / 2)
    # apply when the domain omits the fields, preserving pre-#179 behavior.
    domain_cfg: DomainConfig | None = None
    if config:
        for d in config.domains:
            if d.name == domain:
                domain_cfg = d
                break

    # Resolve source quality tiers from domain config (for G1 propagation)
    source_tiers: dict[str, int] = {}
    if config:
        for d in config.domains:
            if d.name == domain:
                for s in d.sources:
                    source_tiers[s.name] = s.quality_tier
                break

    # Resolve custom extract_fields from domain config
    extract_fields: list[str] | None = None
    if config:
        for d in config.domains:
            if d.name == domain and d.extract_fields:
                extract_fields = d.extract_fields
                break

    # -- Prepare _failed/ directory -----------------------------------------
    collections_path = Path("collections")
    failed_dir = collections_path / domain / "_failed"

    # -- Parallel processing setup (issue #136) ------------------------------
    llm_timeout: float | None = None
    if proc_config is not None and proc_config.llm is not None:
        llm_timeout = proc_config.llm.timeout

    worker_count = _resolve_process_workers()
    progress_enabled = _progress_enabled()

    # -- Process each item --------------------------------------------------
    def _process_item(item: Item) -> tuple[dict[str, Any], dict[str, Any]]:
        """Process one item end-to-end; returns (item_log, stats).

        Runs inside a worker thread: LLM extraction, quality gates and KB
        storage.  ``stats`` carries the deltas the caller aggregates into
        :class:`ProcessResult` on the main thread (no shared-state races).
        All per-item exceptions are caught here so a single failure never
        aborts the run.
        """
        item_start = time.time()
        item_log: dict[str, Any] = {
            "item_id": item.id,
            "title": item.title,
            "status": "ok",
        }
        stats: dict[str, Any] = {
            "token_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "items_with_usage": 0,
            },
            "kb_entries_created": 0,
            "passed_gates": 0,
            "errors": [],
            "discovered": [],
            "logged": True,
        }

        try:
            # Step a0: G0 Schema Integrity — hard gate, runs BEFORE LLM
            # extraction to avoid wasting LLM calls on malformed items.
            g0_checker = G0SchemaIntegrity()
            g0_raw_config = gate_config.get("G0-SchemaIntegrity") if gate_config else None
            raw_dict = item.to_dict()
            if item.raw_data:
                raw_dict.update(item.raw_data)
            g0_check_result = g0_checker.check(raw_dict, None, g0_raw_config)

            if g0_check_result.details.get("action") == "block":
                failed_dir.mkdir(parents=True, exist_ok=True)
                _write_failed_item(failed_dir, item, g0_check_result, "G0")
                item_log["status"] = "g0_blocked"
                item_log["g0_reason"] = str(
                    g0_check_result.details.get(
                        "error", "Schema integrity check failed"
                    )
                )
                logger.warning(
                    "G0 blocked item %s — skipping extraction and storage",
                    item.id,
                )
                stats["logged"] = False
                return item_log, stats

            # Step a: LLM extraction (with custom schema if configured)
            extraction = extractor.extract(item, schema=extract_fields)
            # Aggregate token usage from this item, and record to the cost
            # meter so billing / budget-alert / cost-dashboard tools have
            # real data to query after processing completes.
            if extraction.usage:
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    stats["token_usage"][k] += extraction.usage.get(k, 0)
                stats["token_usage"]["items_with_usage"] += 1

                from autoinfo.cost import CostMeter  # noqa: PLC0415

                CostMeter().log_llm_tokens(
                    model=extractor._model,
                    input_tokens=extraction.usage.get("prompt_tokens", 0),
                    output_tokens=extraction.usage.get("completion_tokens", 0),
                    domain=domain,
                    item_id=item.id,
                )
            item_log["tl_dr_length"] = len(extraction.tl_dr)
            item_log["key_points_count"] = len(extraction.key_points)
            item_log["relevance_score"] = extraction.relevance_score

            # Detect extraction failure: empty tl_dr + no key points + no entities + score 0
            extraction_failed = (
                not extraction.tl_dr
                and not extraction.key_points
                and not extraction.entities
                and extraction.relevance_score == 0.0
            )
            item_log["extraction_failed"] = extraction_failed
            if extraction_failed:
                logger.warning(
                    "LLM extraction returned empty result for item %s — "
                    "entry will be indexed with empty summary",
                    item.id,
                )

            # Step b: Quality gates (G1, G2, G3)
            item_source_config: dict[str, Any] = {}
            if item.source_name in source_tiers:
                item_source_config = {"quality_tier": source_tiers[item.source_name]}
            quality_results = run_quality_gates(
                item,
                context={
                    "source_config": item_source_config,
                    "existing_entries": existing_entries,
                    "topic_keywords": topic_keywords,
                },
                gate_config=gate_config if gate_config else None,
                llm_timeout=llm_timeout,
            )

            # Step b2: Optional G4 factual consistency gate
            if check_factual and extraction.tl_dr:
                try:
                    g4_provider = (
                        proc_config.llm.provider
                        if proc_config and proc_config.llm.provider
                        else "openrouter"
                    )
                    g4_model_name = (
                        proc_config.llm.model
                        if proc_config and proc_config.llm.model
                        else "deepseek/deepseek-chat"
                    )
                    g4_model = f"{g4_provider}/{g4_model_name}"
                    g4_gate_config = gate_config.get("G4-SummaryFactual") if gate_config else None
                    g4 = G4FactualConsistency(model=g4_model, json_mode=proc_config.llm.json_mode if proc_config else False, timeout=llm_timeout)  # noqa: E501
                    g4_result = g4.check(item, extraction, gate_config=g4_gate_config)
                    quality_results["G4-SummaryFactual"] = g4_result

                    # G4 hard gate: block action → skip storage
                    # (G4 already writes its own diagnostics to _failed/ internally)
                    if g4_result.details.get("action") == "block":
                        item_log["status"] = "g4_blocked"
                        logger.warning(
                            "G4 blocked item %s — skipping storage",
                            item.id,
                        )
                        stats["logged"] = False
                        return item_log, stats
                except Exception as exc:
                    logger.warning(
                        "G4 factual check failed for item %s: %s", item.id, exc
                    )
                    g4_result = QualityResult(
                        gate_name="G4-SummaryFactual",
                        passed=False,
                        flagged=True,
                        details={
                            "contradiction": None,
                            "explanation": str(exc),
                        },
                    )
                    quality_results["G4-SummaryFactual"] = g4_result

            # Step b3: Optional G5 translation accuracy gate
            # Augmentation approach: deterministic gates 1-4 as fast pre-check,
            # LLM judge (gate 5) as composite final gate only if pre-checks pass.
            # Falls back to single-LLM-check path if 5-gate pipeline fails.
            if check_translation:
                translation = (extraction.custom_fields or {}).get("translation", "")

                if not translation:
                    # No translation to check — trivially pass (backward compat)
                    g5_result = QualityResult(
                        gate_name="G5-TranslationAccuracy",
                        passed=True,
                        flagged=False,
                        details={
                            "faithful": True,
                            "explanation": "No translation to check",
                            "issues": [],
                        },
                    )
                else:
                    # Resolve model string (also used by fallback path)
                    g5_model = (
                        f"{proc_config.llm.provider}/{proc_config.llm.model}"
                        if proc_config and proc_config.llm.provider and proc_config.llm.model
                        else "openrouter/deepseek/deepseek-chat"
                    )
                    try:
                        source_text = item.content or ""
                        target_text = translation
                        source_lang = item.language or "en"
                        target_lang = (
                            extraction.custom_fields or {}
                        ).get("target_language", "zh")

                        # Resolve terminology dictionary from domain config
                        terminology_dict: dict[str, Any] = {}
                        if config:
                            for d in config.domains:
                                if d.name == domain:
                                    terminology_dict = (
                                        getattr(d, "terminology", {}) or {}
                                    )
                                    break

                        # --- Deterministic pre-checks (gates 1-4, no LLM) ---
                        g1_pre = check_inline_tags(source_text, target_text)
                        g2_pre = check_terminology(
                            source_text, target_text, terminology_dict
                        )
                        g3_pre = check_length_ratio(source_text, target_text)
                        g4_pre = check_source_copy(source_text, target_text)

                        pre_checks = [g1_pre, g2_pre, g3_pre, g4_pre]
                        pre_check_failed = any(
                            not g["passed"] for g in pre_checks
                        )

                        if pre_check_failed:
                            # Pre-checks failed → skip LLM judge, composite failure
                            failed_gates = [
                                k for g, k in zip(
                                    pre_checks,
                                    ["inline_tags", "terminology",
                                     "length_ratio", "source_copy"],
                                ) if not g["passed"]
                            ]
                            logger.info(
                                "G5 deterministic pre-checks failed for "
                                "item %s: %s — skipping LLM judge",
                                item.id, ", ".join(failed_gates),
                            )
                            g5_result = QualityResult(
                                gate_name="G5-TranslationAccuracy",
                                passed=False,
                                flagged=True,
                                score=0.0,
                                details={
                                    "faithful": False,
                                    "explanation": (
                                        "Deterministic pre-checks failed: "
                                        + ", ".join(failed_gates)
                                        + " — LLM judge skipped"
                                    ),
                                    "issues": [],
                                    "gates": {
                                        "inline_tags": g1_pre,
                                        "terminology": g2_pre,
                                        "length_ratio": g3_pre,
                                        "source_copy": g4_pre,
                                    },
                                    "composite_score": 0.0,
                                },
                            )
                        else:
                            # Pre-checks pass → run LLM judge (gate 5)
                            from autoinfo.translation_qa import (
                                calculate_quality_score,  # noqa: PLC0415
                            )

                            g5_scores = llm_judge(
                                source_text, target_text,
                                source_lang, target_lang,
                                model=g5_model,
                                json_mode=proc_config.llm.json_mode if proc_config else False,
                                timeout=llm_timeout,
                            )

                            composite = calculate_quality_score(
                                faithfulness=float(
                                    g5_scores.get("faithfulness", 0)
                                ),
                                terminology=float(
                                    g5_scores.get("terminology", 0)
                                ),
                                style=float(g5_scores.get("style", 0)),
                                readability=float(
                                    g5_scores.get("readability", 0)
                                ),
                            )

                            composite_score = float(
                                composite.get("composite", 0.0)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                            )

                            # Threshold: faithful when composite >= 50
                            faithful = composite_score >= 50.0

                            g5_result = QualityResult(
                                gate_name="G5-TranslationAccuracy",
                                passed=faithful,
                                flagged=not faithful,
                                score=composite_score / 100.0,
                                details={
                                    "faithful": faithful,
                                    "explanation": "5-gate pipeline evaluation",
                                    "issues": g5_scores.get("issues", []),
                                    "gates": {
                                        "inline_tags": g1_pre,
                                        "terminology": g2_pre,
                                        "length_ratio": g3_pre,
                                        "source_copy": g4_pre,
                                        "llm_judge": g5_scores,
                                    },
                                    "composite_score": composite_score,
                                },
                            )

                    except Exception as five_gate_exc:
                        logger.warning(
                            "G5 5-gate pipeline failed for item %s: %s — "
                            "falling back to single-LLM-check path",
                            item.id, five_gate_exc,
                        )
                        # Fallback: single-LLM-check path (existing behavior)
                        try:
                            g5 = G5TranslationAccuracy(model=g5_model, timeout=llm_timeout)
                            g5_result = g5.check(item, extraction)
                        except Exception as single_exc:
                            logger.warning(
                                "G5 fallback also failed for item %s: %s",
                                item.id, single_exc,
                            )
                            g5_result = QualityResult(
                                gate_name="G5-TranslationAccuracy",
                                passed=False,
                                flagged=True,
                                details={
                                    "faithful": None,
                                    "explanation": str(single_exc),
                                    "issues": [],
                                },
                            )

                quality_results["G5-TranslationAccuracy"] = g5_result

            g1 = quality_results.get("G1-SourceAuthority")
            g2 = quality_results.get("G2-Dedup")
            g3 = quality_results.get("G3-RelevanceScoring")

            item_log["g1_flagged"] = g1.flagged if g1 else False
            item_log["g2_passed"] = g2.passed if g2 else True
            item_log["g3_passed"] = g3.passed if g3 else True
            item_log["g3_score"] = g3.score if g3 else 0.0

            # Count how many gates passed (G1 always passes, G2+G3 matter)
            gates_passed = 0
            if g2 is not None and g2.passed:
                gates_passed += 1
            if g3 is not None and g3.passed:
                gates_passed += 1
            # G1 is advisory-only — always counted as passed
            if g1 is not None and g1.passed:
                gates_passed += 1

            # Log G4 if it ran
            g4_result = quality_results.get("G4-SummaryFactual")
            if g4_result is not None:
                item_log["g4_flagged"] = g4_result.flagged
                item_log["g4_contradiction"] = g4_result.details.get("contradiction")

            # Log G5 if it ran
            g5_result = quality_results.get("G5-TranslationAccuracy")
            if g5_result is not None:
                item_log["g5_flagged"] = g5_result.flagged
                item_log["g5_faithful"] = g5_result.details.get("faithful")
                item_log["g5_composite_score"] = g5_result.details.get(
                    "composite_score"
                )

            # Step c0: Language detection (non-blocking)
            text_for_lang = f"{item.title} {item.content}"
            detected_lang = detect_language(text_for_lang)
            item.language = detected_lang
            item_log["language"] = detected_lang

            # Step c: KB storage — store all items (quality gates are
            # advisory). Duplicates get marked in their frontmatter.
            if g2 is not None and not g2.passed:
                item_log["status"] = "duplicate"
                item_log["detail"] = str(g2.details.get("matched_by", "unknown"))

            with _STORAGE_LOCK:
                entry = kb_store.store_entry(item, extraction, quality_results)
            if entry is None:
                # Issue #182: entry rejected by KB (content too short) —
                # skip it; do not crash or count it as created.
                item_log["status"] = "rejected"
                item_log["detail"] = "content below minimum length"
                return item_log, stats
            # M1T14: keep in-memory entry trace_id in sync with item (store_entry
            # already persists item.trace_id to KBEntry + frontmatter in kb.py)
            if not entry.trace_id:
                entry.trace_id = item.trace_id
            item_log["entry_id"] = entry.entry_id
            stats["kb_entries_created"] += 1

            # Step c1: Auto-promotion (T6) — admission-checked, best-effort.
            # Only items that passed all quality gates (G1+G2+G3) qualify;
            # each promotion attempt is isolated so a rejection or an
            # unexpected failure never aborts the pipeline.
            if auto_promote and gates_passed == 3:
                item_log["auto_promote_attempted"] = True
                try:
                    with _STORAGE_LOCK:
                        draft_entry = kb_store.create_kb_draft(
                            raw_ids=[entry.entry_id],
                            title=item.title,
                            summary=extraction.tl_dr if extraction else "",
                            tags=item.topic_tags,
                        )
                        kb_store.promote_kb_draft(
                            draft_id=draft_entry.entry_id,
                            config=config,
                            caller="process",
                        )
                    item_log["auto_promoted"] = True
                    item_log["promoted_entry_id"] = draft_entry.entry_id
                except PromotionRejected as exc:
                    item_log["auto_promoted"] = False
                    item_log["promotion_rejected"] = [str(r) for r in exc.reasons]
                    logger.warning(
                        "Auto-promotion rejected for item %s: %s",
                        item.id,
                        exc,
                    )
                except Exception as exc:
                    item_log["auto_promoted"] = False
                    item_log["promotion_error"] = str(exc)
                    logger.warning(
                        "Auto-promotion failed for item %s: %s",
                        item.id,
                        exc,
                    )

            # Step c2: CEFR classification (non-blocking — only when enabled)
            if config is not None and config.cefr.enabled:
                with _STORAGE_LOCK:
                    _classify_entry_cefr(entry, item, config)

            # Step d: Knowledge graph — store entities & discover relations
            if extraction and extraction.entities:
                with _STORAGE_LOCK:
                    kg_result = kb_store.store_entities(
                        entry_id=entry.entry_id,
                        domain=domain,
                        entities=extraction.entities,
                    )
                item_log["entities_indexed"] = kg_result["entities_indexed"]
                item_log["relations_discovered"] = kg_result["relations_discovered"]

            # Step e: Keyword auto-discovery — extract new keywords from LLM
            # response.  The YAML writes are deferred to the caller (main
            # thread) because KeywordsFile is not thread-safe.
            discovered: list[str] = []
            if extraction:
                min_len = (
                    domain_cfg.auto_keyword_min_length if domain_cfg else 2
                )
                # Collect entity names as keyword candidates
                for entity in extraction.entities:
                    name = entity.get("name", "").strip().lower()
                    if _is_valid_discovery_keyword(name, min_length=min_len):
                        discovered.append(name)
                # Collect key-point phrases as keyword candidates
                for kp in extraction.key_points:
                    words = [w.strip().lower() for w in kp.split() if len(w.strip()) > 2]
                    # Use short phrases (2-4 words) as single keywords
                    for i in range(len(words)):
                        w = words[i]
                        if _is_valid_discovery_keyword(w, min_length=min_len):
                            discovered.append(w)
                    for n in (2, 3):
                        phrases = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
                        for p in phrases:
                            if _is_valid_discovery_keyword(p, min_length=min_len):
                                discovered.append(p)

            if discovered:
                # Deduplicate and defer the writes
                seen: set[str] = set()
                pending: list[tuple[str, str]] = []
                for kw in discovered:
                    if kw not in seen:
                        seen.add(kw)
                        pending.append((kw, item.source_name))
                stats["discovered"] = pending
                item_log["keywords_discovered"] = len(seen)

            # Track items that passed all gates
            if gates_passed == 3:
                stats["passed_gates"] += 1

        except Exception as exc:
            logger.error("Processing failed for item %s: %s", item.id, exc)
            item_log["status"] = "error"
            item_log["error"] = str(exc)
            stats["errors"].append({"item_id": item.id, "error": str(exc)})

        item_log["duration_s"] = round(time.time() - item_start, 3)
        return item_log, stats

    # -- Dispatch items to the worker pool -----------------------------------
    total_to_process = len(items_slice)
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="process") as pool:
        futures = {
            pool.submit(_process_item, item): idx
            for idx, item in enumerate(items_slice)
        }
        logs_by_index: dict[int, dict[str, Any]] = {}
        logged_by_index: dict[int, bool] = {}
        completed = 0
        kf = KeywordsFile()
        for future in as_completed(futures):
            idx = futures[future]
            try:
                item_log, stats = future.result()
            except Exception as exc:  # safety net — _process_item catches all
                logger.error(
                    "Unexpected worker failure for item index %d: %s", idx, exc
                )
                item_log = {
                    "item_id": str(idx),
                    "title": "unknown",
                    "status": "error",
                    "error": str(exc),
                }
                stats = {
                    "token_usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "items_with_usage": 0,
                    },
                    "kb_entries_created": 0,
                    "passed_gates": 0,
                    "errors": [{"item_id": str(idx), "error": str(exc)}],
                    "discovered": [],
                    "logged": True,
                }
            logs_by_index[idx] = item_log
            logged_by_index[idx] = bool(stats.get("logged", True))
            completed += 1

            # -- Aggregate per-item stats on the main thread (no races) ------
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                result.token_usage[k] += stats["token_usage"][k]
            result.token_usage["items_with_usage"] += stats["token_usage"]["items_with_usage"]
            result.kb_entries_created += stats["kb_entries_created"]
            result.passed_gates += stats["passed_gates"]
            result.errors.extend(stats["errors"])

            # Keyword auto-discovery writes (single-threaded — file I/O).
            # Toggle + cap (#179): when disabled nothing is written; once the
            # domain's AUTO_ADDED count reaches the cap, further new keywords
            # are skipped (never an error).
            discovery_enabled = (
                domain_cfg.auto_keyword_discovery if domain_cfg else True
            )
            max_auto = domain_cfg.max_auto_keywords if domain_cfg else 100
            if discovery_enabled and stats["discovered"]:
                entries = kf.load(domain)
                existing = {e.keyword: e for e in entries}
                auto_count = sum(
                    1 for e in entries if e.state == KeywordState.AUTO_ADDED
                )
                for kw, source_name in stats["discovered"]:
                    current = existing.get(kw)
                    if current is None:
                        if auto_count >= max_auto:
                            continue
                        auto_count += 1
                    elif current.state != KeywordState.AUTO_ADDED:
                        # Re-adding a non-AUTO_ADDED keyword flips it to
                        # AUTO_ADDED, which consumes cap budget too.
                        if auto_count >= max_auto:
                            continue
                        auto_count += 1
                    try:
                        stored = kf.add_keyword(
                            domain=domain,
                            keyword=kw,
                            state=KeywordState.AUTO_ADDED,
                            source=f"auto-discovery:{source_name}",
                        )
                    except Exception:
                        logger.debug("Failed to add discovered keyword '%s':", kw, exc_info=True)
                        continue
                    existing[kw] = stored

            # Per-item progress output — flushed so it survives a killed run
            if progress_enabled:
                title = str(item_log.get("title") or "untitled")[:60]
                dur = item_log.get("duration_s", 0.0)
                print(f"[{completed}/{total_to_process}] processed '{title}' ({dur}s)", flush=True)

        # Preserve input order; g0/g4-blocked items are excluded (matching
        # the historical sequential loop where ``continue`` skipped the log).
        result.per_item_logs = [
            logs_by_index[i]
            for i in range(total_to_process)
            if logged_by_index.get(i, True)
        ]

    # -- Persist progress (batch mode only) ---------------------------------
    if batch_size > 0:
        _write_progress(domain, new_index, total_items)

    result.duration_s = round(time.time() - start_time, 3)

    # -- Summary ------------------------------------------------------------
    g4_count = sum(
        1 for log in result.per_item_logs if log.get("g4_flagged") is not None
    )
    g5_count = sum(
        1 for log in result.per_item_logs if log.get("g5_flagged") is not None
    )
    logger.info(
        "Processing complete: %d items → %d passed G1-G3 → %d KB entries created "
        "(batch=%d, remaining=%d, g4_checked=%d, g5_checked=%d)",
        result.total_items,
        result.passed_gates,
        result.kb_entries_created,
        result.processed_count,
        result.remaining_count,
        g4_count,
        g5_count,
    )

    # -- Auto-verify: compare expected entries vs KB store count ----------
    if result.kb_entries_created > 0:
        try:
            actual_count = kb_store.count_entries()  # total across all domains
            if actual_count < result.kb_entries_created:
                logger.warning(
                    "KB count mismatch: expected %d entries, SQLite returned %d. "
                    "Run 'autoinfo kb reindex --domain %s' to rebuild the index.",
                    result.kb_entries_created,
                    actual_count,
                    domain,
                )
        except Exception as verr:
            logger.debug("KB verification skipped: %s", verr)

    return result


def get_processing_progress(domain: str) -> dict:
    """Return the current processing progress for *domain*.

    Parameters
    ----------
    domain : str
        Domain to query.

    Returns
    -------
    dict
        Keys: ``total_items``, ``processed_count``, ``remaining_count``,
        ``is_complete``.  When no progress has been recorded or all items
        are done, ``is_complete`` is ``True``.
    """
    progress = _read_progress(domain)
    total = progress["total_items"]
    processed = progress["last_processed_index"]
    remaining = total - processed
    is_complete = total == 0 or processed >= total
    return {
        "total_items": total,
        "processed_count": processed,
        "remaining_count": remaining,
        "is_complete": is_complete,
    }
