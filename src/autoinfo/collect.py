"""Collection orchestrator — coordinates source handlers and deduplication.

This is the core entry point for ``autoinfo collect``.  It reads domain
configuration, dispatches the appropriate source handlers (PubMed, RSS),
applies deduplication, and caches collected items to disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from autoinfo.alerts import check_alerts, check_source_alerts, check_source_credentials
from autoinfo.collectors.base import SourceFailure
from autoinfo.config import Config, SourceConfig, get_config_path, load_config
from autoinfo.cost import CostMeter
from autoinfo.dedup import DedupChecker
from autoinfo.models import CollectionResult, Item, KBEntry

logger = logging.getLogger(__name__)
from autoinfo.logging import get_pipeline_logger  # noqa: E402

plog = get_pipeline_logger("collect")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_collection(
    domain: str,
    topic: str = "",
    sources: list[str] | None = None,
    limit: int = 20,
    dry_run: bool = False,
    force_full: bool = False,
    progress_cb: Callable[[CollectionResult], None] | None = None,
) -> dict[str, Any]:
    """Execute a full collection run for a domain.

    Parameters
    ----------
    domain : str
        Domain name to collect for (e.g. ``"medical-research"``).
    topic : str
        Optional topic filter (keyword used as search query for PubMed).
    sources : list[str] | None
        Optional list of source names to restrict collection to.
        When ``None``, all sources for the domain are collected.
    limit : int
        Maximum items to fetch per source (default 20).
    dry_run : bool
        When ``True``, return estimated counts without any storage
        operations (default ``False``).
    progress_cb : Callable[[CollectionResult], None] | None
        Optional callback invoked with each per-source ``CollectionResult``
        as soon as that source finishes. CLI-only, human-facing progress
        reporting — the MCP surface never passes one (its results are
        polled asynchronously; see docs/dev/cli-mcp-rest-parity.md).

    Returns
    -------
    dict
        Aggregate collection results with the following keys::

            {
                "collection_id": str,
                "domain": str,
                "total_found": int,
                "total_new": int,
                "duration_s": float,
                "per_source": [CollectionResult, ...],
                "dry_run": bool,
            }

    Raises
    ------
    FileNotFoundError
        If no configuration file is found.
    ValueError
        If *domain* is not found in config, or has no active sources.
    """
    start_time = time.time()
    collection_id = _make_collection_id()

    # -- Load configuration ------------------------------------------------
    config_path = get_config_path()
    if config_path is None:
        raise FileNotFoundError(
            "No configuration found. Run 'autoinfo init' first."
        )
    config = load_config(config_path)

    domain_config = _find_domain(config, domain)
    if domain_config is None:
        raise ValueError(f"Domain '{domain}' not found in configuration.")

    # -- Resolve topic keywords for relevance filtering (#177) --------------
    keywords = _resolve_topic_keywords(domain_config, topic)

    # -- Determine which sources to collect --------------------------------
    source_configs = _resolve_sources(domain_config.sources, sources)
    if not source_configs:
        raise ValueError(
            f"No active sources found for domain '{domain}'"
            + (f" matching: {sources}" if sources else "")
        )

    # -- Load existing KB entries for dedup --------------------------------
    checker = DedupChecker()
    existing_entries = checker.load_existing(domain)

    # -- Per-source collection ---------------------------------------------
    per_source: list[CollectionResult] = []
    all_new_items: list[Item] = []

    for src_cfg in source_configs:
        plog.info(
            "Collecting from source",
            source_type=src_cfg.type,
            extra={"source_name": src_cfg.name},
            trace_id=collection_id,
        )

        src_result = _collect_from_source(
            source_config=src_cfg,
            domain=domain,
            topic=topic,
            limit=limit,
            dry_run=dry_run,
            existing_entries=existing_entries,
            collection_id=collection_id,
            checker=checker,
            new_items_collector=all_new_items,
            force_full=force_full,
            keywords=keywords,
        )
        per_source.append(src_result)
        if progress_cb is not None:
            progress_cb(src_result)

    # -- Aggregate totals --------------------------------------------------
    total_found = sum(r.items_found for r in per_source)
    total_new = sum(r.items_new for r in per_source)
    elapsed = time.time() - start_time

    # -- Fire webhooks (fire-and-forget) -----------------------------------
    if not dry_run and domain_config.webhook_urls and all_new_items:
        _fire_webhooks_sync(domain, all_new_items, domain_config.webhook_urls)

    # -- Check alert rules (fire-and-forget) --------------------------------
    if not dry_run and all_new_items:
        for _item in all_new_items:
            try:
                check_alerts(_item, domain)
            except Exception:
                logger.exception("Alert check failed for item '%s'", _item.id)

    # -- B3 escalation: missing source credentials reach operators ----------
    # A configured source that requires a key with no key configured is a
    # blocking issue only the B3 human can resolve (user-lifecycle-definition
    # §4.1). Push a `source_requires_key` agent-callback event and evaluate
    # source_credential_missing alert rules through the delivery channels.
    if not dry_run:
        try:
            missing = check_source_credentials(domain)
            if missing:
                from autoinfo.agent_callback import notify_source_requires_key

                for cred in missing:
                    notify_source_requires_key(
                        source=cred["source"],
                        source_type=cred["source_type"],
                        key_ref=cred["key_ref"],
                        domain=domain,
                    )
                check_source_alerts(domain, missing)
        except Exception:
            logger.exception(
                "Source credential check failed for domain '%s'", domain
            )

    return {
        "collection_id": collection_id,
        "domain": domain,
        "total_found": total_found,
        "total_new": total_new,
        "items_filtered": sum(r.items_filtered for r in per_source),
        "duration_s": round(elapsed, 3),
        "per_source": [r.to_dict() for r in per_source],
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_domain(config: Config, domain: str) -> Any | None:
    """Find a domain config by name (checks active domains first)."""
    for d in config.domains:
        if d.name == domain and d.active:
            return d
    # Fallback: allow inactive if explicitly specified (user asked for it)
    for d in config.domains:
        if d.name == domain:
            return d
    return None


def _resolve_sources(
    all_sources: list[SourceConfig],
    requested: list[str] | None,
) -> list[SourceConfig]:
    """Filter the source list to only those requested (or all if ``None``)."""
    if not requested:
        return list(all_sources)

    requested_set = set(requested)
    return [s for s in all_sources if s.name in requested_set]


def _make_collection_id() -> str:
    """Generate a unique collection run identifier."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"col-{ts}-{short}"


def _resolve_topic_keywords(domain_config: Any, topic: str) -> list[str]:
    """Resolve the keyword list used for topic-relevance filtering (#177).

    When *topic* names a configured topic, only that topic's keywords apply;
    otherwise the union of all domain topics' keywords is used (order-
    preserving, deduplicated). Returns ``[]`` when nothing is configured —
    callers must then skip filtering so keyword-less domains behave exactly
    as before the filter existed.
    """
    topics = getattr(domain_config, "topics", [])
    candidates = [t for t in topics if t.name == topic] if topic else []
    if not candidates:
        candidates = list(topics)
    keywords: list[str] = []
    for t in candidates:
        for kw in getattr(t, "keywords", []) or []:
            if kw and kw not in keywords:
                keywords.append(kw)
    return keywords


# ---------------------------------------------------------------------------
# Topic-keyword relevance filter (#177) — source-type aware
# ---------------------------------------------------------------------------
# The filter exists to keep cross-disciplinary *search platforms* on-domain
# (OpenAlex/CrossRef/Semantic Scholar returning "Loot Crates" for a medical
# query).  Curated niche feeds (publication RSS like retail-dive/techcrunch,
# provider APIs like pubmed) are topical by construction — the source itself
# is the relevance signal — so filtering them drops real items (the #177
# over-filtering regression).  Classification mirrors the name-based
# dispatch in ``_build_handler``.
CROSS_DISCIPLINARY_SOURCE_TYPES: frozenset[str] = frozenset({
    "openalex",
    "dblp",
    "web",
})
# Generic ``api`` handlers whose NAME marks a cross-disciplinary platform.
# (Deep-imported alongside ``_build_handler``: Semantic Scholar, CrossRef.)
CROSS_DISCIPLINARY_API_NAME_MARKERS: tuple[str, ...] = ("semantic", "crossref")
# Token-level word splitter for partial-word matching ("retail" -> "retailer",
# "gene" -> "gene-editing").
_WORD_RE = re.compile(r"[a-z0-9]+")


def _is_cross_disciplinary_source(source_config: SourceConfig) -> bool:
    """Return True when *source_config* is a cross-disciplinary search platform.

    Such platforms execute a broad query over a cross-topic corpus, so an
    item's on-domain-ness can only be judged by topic keywords (#177).
    Everything else — curated publication RSS, provider APIs (pubmed, uspto,
    coursera), site-scoped Google News feeds — is topical by construction
    and is never keyword-filtered.
    """
    stype = (source_config.type or "").lower()
    if stype in CROSS_DISCIPLINARY_SOURCE_TYPES:
        return True
    if stype == "api":
        name = (source_config.name or "").lower()
        if any(marker in name for marker in CROSS_DISCIPLINARY_API_NAME_MARKERS):
            return True
    # Google News search RSS: unscoped feeds (news.google.com/rss,
    # /search?q=...) return cross-topic headlines; site-scoped queries
    # (q=site:...) are effectively curated per-site feeds.
    if stype == "rss":
        url = (source_config.url or "").lower()
        if "news.google.com/rss" in url and "q=site:" not in url:
            return True
    return False


def _keyword_matches(keyword: str, text: str) -> bool:
    """Return True when every word of *keyword* appears in *text*.

    Matching is case-insensitive, token-level, partial-word aware: a word
    matches when it occurs at a word boundary as a prefix of a longer token
    — "retail" matches "retailers", "gene" matches "gene-editing" — so
    inflected/hyphenated forms of a keyword count even though a naive
    substring match would miss them.
    """
    words = _WORD_RE.findall(keyword.lower())
    if not words:
        return False
    return all(
        re.search(rf"(?<![a-z0-9]){re.escape(w)}", text) is not None
        for w in words
    )


def _matches_keywords(
    item: Item,
    keywords: list[str] | None,
    min_keywords: int = 1,
) -> bool:
    """Return True when at least *min_keywords* topic keywords match *item*.

    A keyword matches when every one of its words appears (partial-word
    aware) in title or content.  The *min_keywords* floor (default 1)
    requires that many distinct keywords to match, tolerating a single
    loose phrase while still rejecting keyword-less items.  An empty
    keyword list keeps every item so keyword-less domains never lose data.
    """
    if not keywords:
        return True
    text = f"{item.title or ''} {item.content or ''}".lower()
    matched = 0
    for kw in keywords:
        if kw and _keyword_matches(kw, text):
            matched += 1
            if matched >= min_keywords:
                return True
    return False


def _collect_from_source(
    source_config: SourceConfig,
    domain: str,
    topic: str,
    limit: int,
    dry_run: bool,
    existing_entries: list[KBEntry],
    collection_id: str,
    checker: DedupChecker,
    new_items_collector: list[Item] | None = None,
    force_full: bool = False,
    keywords: list[str] | None = None,
) -> CollectionResult:
    """Fetch items from a single source, deduplicate, and optionally cache."""
    src_start = time.time()
    errors: list[dict[str, Any]] = []

    # -- Determine and instantiate handler ---------------------------------
    try:
        handler = _build_handler(source_config)
    except ValueError as exc:
        plog.warning(
            "Skipping source",
            source_type=source_config.type,
            extra={"source_name": source_config.name, "error": str(exc)},
        )
        skipped_duration = round(time.time() - src_start, 3)
        _log_run(
            domain=domain,
            source_name=source_config.name,
            collection_id=collection_id,
            items_found=0,
            items_new=0,
            status="skipped",
            errors=[{"message": str(exc)}],
            duration_s=skipped_duration,
        )
        return CollectionResult(
            collection_id=collection_id,
            domain=domain,
            source=source_config.name,
            status="skipped",
            items_found=0,
            items_new=0,
            errors=[{"message": str(exc)}],
            duration_s=skipped_duration,
        )

    # -- Fetch items -------------------------------------------------------
    try:
        items = _fetch_items(handler, source_config, topic, limit, keywords)
    except SourceFailure as exc:
        plog.error(
            "Source failed",
            source_type=source_config.type,
            extra={"source_name": source_config.name, "reason": exc.reason},
        )
        error_duration = round(time.time() - src_start, 3)
        error_dict = {
            "message": str(exc),
            "source_failed": True,
            "reason": exc.reason,
        }
        _log_run(
            domain=domain,
            source_name=source_config.name,
            collection_id=collection_id,
            items_found=0,
            items_new=0,
            status="error",
            errors=[error_dict],
            duration_s=error_duration,
        )
        return CollectionResult(
            collection_id=collection_id,
            domain=domain,
            source=source_config.name,
            status="error",
            items_found=0,
            items_new=0,
            errors=[error_dict],
            source_failed=True,
            duration_s=error_duration,
        )
    except Exception as exc:
        plog.error(
            "Fetch failed for source",
            source_type=source_config.type,
            extra={"source_name": source_config.name, "error": str(exc)},
        )
        error_duration = round(time.time() - src_start, 3)
        error_dict = {
            "message": f"Fetch failed: {exc}",
            "source_failed": True,
            "reason": str(exc),
        }
        _log_run(
            domain=domain,
            source_name=source_config.name,
            collection_id=collection_id,
            items_found=0,
            items_new=0,
            status="error",
            errors=[error_dict],
            duration_s=error_duration,
        )
        return CollectionResult(
            collection_id=collection_id,
            domain=domain,
            source=source_config.name,
            status="error",
            items_found=0,
            items_new=0,
            errors=[error_dict],
            source_failed=True,
            duration_s=error_duration,
        )

    items_found = len(items)

    # -- Topic-keyword relevance filter (#177) ------------------------------
    # Curated sources skip the filter entirely (topical by construction),
    # so they keep every item and report 0 filtered — the #177 regression fix.
    kept_items: list[Item] = []
    items_filtered = 0
    if _is_cross_disciplinary_source(source_config):
        for item in items:
            if _matches_keywords(item, keywords):
                kept_items.append(item)
            else:
                items_filtered += 1
    else:
        kept_items = items
    if items_filtered:
        plog.info(
            "Relevance filter dropped items",
            source_type=source_config.type,
            extra={
                "source_name": source_config.name,
                "items_found": items_found,
                "items_filtered": items_filtered,
                "items_kept": len(kept_items),
            },
        )
    items = kept_items

    # Ensure every item carries the correct domain and source quality tier
    for item in items:
        item.domain = domain
        item.quality_tier = source_config.quality_tier

    # Log API call cost (non-blocking — failures are swallowed)
    try:
        CostMeter().log_api_call(
            source_type=source_config.type,
            domain=domain,
            item_id="",
        )
    except Exception:
        logger.debug("CostMeter log_api_call skipped", exc_info=True)

    # -- Build source_url lookup for version bumping (F50) -----------------
    url_to_existing: dict[str, KBEntry] = {}
    for entry in existing_entries:
        if entry.source_url:
            existing_for_url = url_to_existing.get(entry.source_url)
            if existing_for_url is None or entry.version > existing_for_url.version:
                url_to_existing[entry.source_url] = entry

    # -- Apply dedup + version bumping -------------------------------------
    new_items: list[Item] = []
    for item in items:
        existing = url_to_existing.get(item.source_url) if item.source_url else None
        if existing is not None:
            # Re-collection of same URL — version bump
            item.version = existing.version + 1
            item.previous_version = existing.version
            item.supersedes = existing.entry_id
            new_items.append(item)
            plog.info(
                "Version bump on re-collection",
                item_id=item.id,
                source_type=source_config.type,
                extra={
                    "source_url": item.source_url,
                    "new_version": item.version,
                    "previous_version": existing.version,
                    "supersedes": existing.entry_id,
                },
            )
        elif force_full:
            new_items.append(item)
        else:
            verdict = checker.check(item, existing_entries)
            if not verdict["is_duplicate"]:
                new_items.append(item)

    items_new = len(new_items)

    # -- Assign trace_id to each new item ----------------------------------
    trace_ids: list[str] = []
    for item in new_items:
        if not item.trace_id:
            item.trace_id = str(uuid.uuid4())
        trace_ids.append(item.trace_id)
        plog.info(
            "Item collected",
            item_id=item.id,
            source_type=source_config.type,
            trace_id=item.trace_id,
            extra={
                "source_name": source_config.name,
                "domain": domain,
                "title": item.title,
            },
        )

    elapsed = round(time.time() - src_start, 3)

    # -- Cache (only if not dry_run) ---------------------------------------
    if not dry_run and new_items:
        _cache_items(new_items, domain, source_config.name)
        if new_items_collector is not None:
            new_items_collector.extend(new_items)
        _log_run(
            domain, source_config.name, collection_id,
            items_found, items_new,
            status="success",
            duration_s=elapsed,
            trace_ids=trace_ids,
            items_filtered=items_filtered,
        )

    return CollectionResult(
        collection_id=collection_id,
        domain=domain,
        source=source_config.name,
        status="success" if not errors else "partial",
        items_found=items_found,
        items_new=items_new,
        items_filtered=items_filtered,
        errors=errors,
        duration_s=elapsed,
        estimated_duration_s=elapsed,
    )


def _build_handler(source_config: SourceConfig) -> Any:
    """Build the appropriate handler for a source configuration.

    Returns a handler instance with a common interface:

    * ``PubMedHandler`` — ``search(query, max_results)`` / ``fetch(pmids)``
      / ``to_item(article)``
    * ``RSSHandler`` — ``fetch(url) -> list[Item]``
    * ``WebHandler`` — ``fetch(url) -> list[Item]``
    * ``EmailHandler`` — ``collect(config) -> list[Item]``

    Raises ``ValueError`` if the source type is unknown or unsupported.
    """
    name = (source_config.name or "").lower()
    stype = (source_config.type or "").lower()

    if stype == "api" and "pubmed" in name:
        from autoinfo.collectors.pubmed import PubMedHandler

        return PubMedHandler(source_config=source_config)

    if stype == "api" and "semantic" in name:
        from autoinfo.collectors.semantic_scholar import SemanticScholarHandler

        return SemanticScholarHandler(source_config=source_config)

    if stype == "api" and "uspto" in name:
        from autoinfo.collectors.uspto import USPTOHandler

        return USPTOHandler(source_config=source_config)

    if stype == "dblp":
        from autoinfo.collectors.dblp import DBLPHandler

        return DBLPHandler(source_config=source_config)

    if stype == "nyt":
        from autoinfo.collectors.nyt import NYTHandler

        return NYTHandler(config=source_config.settings or {})

    if stype == "openalex":
        from autoinfo.collectors.openalex import OpenAlexHandler

        return OpenAlexHandler(config=source_config.settings or {})

    if stype == "ap_api":
        from autoinfo.collectors.ap_api import APAPIHandler

        return APAPIHandler(source_config=source_config)

    if stype == "reuters_mcp":
        from autoinfo.collectors.reuters_mcp import ReutersMCPHandler

        return ReutersMCPHandler(source_config=source_config)

    if stype == "reddit":
        from autoinfo.collectors.reddit import RedditHandler

        return RedditHandler(config=source_config.settings or {})

    if stype == "spotify":
        from autoinfo.collectors.spotify import SpotifyHandler

        return SpotifyHandler(config=source_config.settings or {})

    if stype == "youtube":
        from autoinfo.collectors.youtube import YouTubeHandler

        return YouTubeHandler(config=source_config.settings or {})

    if stype == "bilibili":
        from autoinfo.collectors.bilibili import BilibiliHandler

        return BilibiliHandler(config=source_config.settings or {})

    if stype == "apple_podcasts":
        from autoinfo.collectors.apple_podcasts import ApplePodcastsHandler

        return ApplePodcastsHandler(config=source_config.settings or {})

    if stype == "unpaywall":
        from autoinfo.collectors.unpaywall import UnpaywallHandler

        return UnpaywallHandler(config=source_config.settings or {})

    if stype == "gdelt":
        from autoinfo.collectors.gdelt import GDELTHandler

        return GDELTHandler(config=source_config.settings or {})

    if stype == "yahoo_finance":
        from autoinfo.collectors.yahoo_finance import YahooFinanceHandler

        return YahooFinanceHandler(source_name=source_config.name)

    if stype == "quandl":
        from autoinfo.collectors.quandl import QuandlHandler

        return QuandlHandler(source_config=source_config)

    if stype in ("huggingface", "kaggle"):
        from autoinfo.collectors.huggingface import HuggingFaceHandler

        provider = "kaggle" if stype == "kaggle" else "huggingface"
        return HuggingFaceHandler(
            config={
                **(source_config.settings or {}),
                "provider": provider,
            },
        )

    if stype == "rss":
        from autoinfo.collectors.rss import RSSHandler

        return RSSHandler(source_name=source_config.name)

    if stype == "web":
        from autoinfo.collectors.web import WebHandler

        return WebHandler(source_name=source_config.name)

    if stype in ("email", "email_imap"):
        from autoinfo.collectors.email_imap import EmailHandler

        return EmailHandler(source_name=source_config.name)

    if stype == "pdf":
        from autoinfo.collectors.pdf import PDFHandler

        return PDFHandler(source_name=source_config.name)

    if stype == "ssrn":
        from autoinfo.collectors.ssrn import SSRNHandler

        return SSRNHandler(config=source_config.settings or {})

    if stype == "hackernews":
        from autoinfo.collectors.hackernews import HackerNewsHandler

        return HackerNewsHandler(source_config)

    if stype == "akshare":
        from autoinfo.collectors.akshare import AKShareHandler

        return AKShareHandler(config=source_config.settings or {})

    if stype == "sec_edgar":
        from autoinfo.collectors.sec_edgar import SecEdgarHandler

        return SecEdgarHandler(config=source_config.settings or {})

    if stype == "edx_sitemap":
        from autoinfo.collectors.edx_sitemap import EdxSitemapHandler

        return EdxSitemapHandler(config=source_config.settings or {})

    if stype == "api":
        from autoinfo.collectors.http_api import HttpApiHandler

        return HttpApiHandler(source_config)

    raise ValueError(
        f"Unknown source type '{source_config.type}' for source "
        f"'{source_config.name}'. Supported types: api (pubmed + generic), rss, web, email_imap, pdf."  # noqa: E501
    )


def _fetch_items(
    handler: Any,
    source_config: SourceConfig,
    topic: str,
    limit: int,
    keywords: list[str] | None = None,
) -> list[Item]:
    """Fetch items from a handler.

    Dispatches based on handler type:
    * ``PubMedHandler`` — uses ``search()`` + ``fetch()`` + ``to_item()``
    * ``RSSHandler`` — uses ``fetch(url)`` directly
    * ``WebHandler`` — uses ``fetch(url)`` directly
    """
    # -- Webhook handler path (push-based, no URL to pull) ----------------
    if hasattr(handler, "handle") and not hasattr(handler, "fetch"):
        plog.info(
            "Source is push-based; nothing to fetch during pull collection",
            source_type=source_config.type,
            extra={"source_name": source_config.name, "handler_type": type(handler).__name__},
        )
        return []

    # -- Email handler path (uses collect() with settings dict) ------------
    if hasattr(handler, "collect"):
        settings = source_config.settings
        email_config: dict[str, Any] = {
            "host": source_config.url or settings.get("host", ""),
            "port": int(settings.get("port", 993)),
            "username": settings.get("username", ""),
            "password": settings.get("password", "")
            or os.environ.get("AUTOINFO_EMAIL_PASSWORD", ""),
            "mailbox": settings.get("mailbox", "INBOX"),
        }
        if settings.get("since_date"):
            email_config["since_date"] = settings["since_date"]
        items = handler.collect(email_config)
        return items[:limit]

    # -- PubMed handler path -----------------------------------------------
    if hasattr(handler, "search") and hasattr(handler, "fetch"):
        query = topic if topic else source_config.name
        pmids = handler.search(query, max_results=limit)
        if not pmids:
            return []
        articles = handler.fetch(pmids)
        return [handler.to_item(a) for a in articles]

    # -- HttpApiHandler path (generic HTTP JSON API) -----------------------
    if getattr(handler, "_handler_type", "") == "HttpApiHandler":
        url = source_config.url
        if not url:
            plog.warning(
                "API source has no URL configured",
                source_type=source_config.type,
                extra={"source_name": source_config.name},
            )
            return []
        query = topic or source_config.settings.get("query", "") or ""
        if not query.strip():
            plog.warning(
                "API source has no query (no --topic and no source query); "
                "skipping to avoid fetching unrelated content",
                source_type=source_config.type,
                extra={"source_name": source_config.name},
            )
            return []
        items = handler.fetch(url, query=query, limit=limit)
        return items[:limit]

    # -- QuandlHandler path -------------------------------------------------
    if getattr(handler, "_handler_type", "") == "QuandlHandler":
        url = source_config.url
        if not url:
            plog.warning(
                "Quandl source has no URL configured",
                source_type=source_config.type,
                extra={"source_name": source_config.name},
            )
            return []
        query = topic or source_config.settings.get("query", "") or ""
        if not query.strip():
            plog.warning(
                "Quandl source has no query (no --topic and no source query); "
                "skipping to avoid fetching unrelated content",
                source_type=source_config.type,
                extra={"source_name": source_config.name},
            )
            return []
        items = handler.fetch(url, query=query, limit=limit)
        return items[:limit]

    # -- NYT handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "nyt":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- OpenAlex handler path --------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "openalex":
        query = " ".join(keywords) if keywords else topic
        items = handler.fetch(limit=limit, query=query)
        return [handler.to_item(item) for item in items]

    # -- AP API handler path (paid/enterprise) ----------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "ap_api":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Reuters MCP handler path (paid/enterprise) -------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "reuters_mcp":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- DBLP handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_name", "") == "dblp":
        query = topic if topic else ""
        items = handler.fetch(query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Reddit handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "reddit":
        query = topic if topic else ""
        items = handler.fetch(query=query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Spotify handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "spotify":
        query = topic if topic else ""
        items = handler.fetch(limit=limit, query=query)
        return [handler.to_item(item) for item in items]

    # -- HackerNews handler path ----------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "hackernews":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- YouTube handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "youtube":
        # Set topic as query on the handler if not already configured
        if topic and not handler.config.get("query"):
            handler.query = topic
            handler.config["query"] = topic
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Bilibili handler path -----------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "bilibili":
        # Set topic as query on the handler if not already configured
        if topic and not handler.config.get("query"):
            handler.query = topic
            handler.config["query"] = topic
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Apple Podcasts handler path ----------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "apple_podcasts":
        term = topic if topic else ""
        items = handler.fetch(term=term, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Unpaywall handler path -------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "unpaywall":
        query = topic if topic else ""
        items = handler.fetch(query=query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- SSRN handler path --------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "ssrn":
        query = topic if topic else ""
        items = handler.fetch(query=query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- GDELT handler path -------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "gdelt":
        search_query = topic if topic else ""
        items = handler.fetch(query=search_query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- HuggingFace / Kaggle handler path -----------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") in ("huggingface", "kaggle"):  # noqa: E501
        search_query = topic if topic else ""
        items = handler.fetch(query=search_query, limit=limit)
        return [handler.to_item(item) for item in items]

    # -- AKShare handler path ------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "akshare":
        items = [handler.to_item(i) for i in handler.fetch(limit=limit)]
        return items

    # -- edX Sitemap handler path ------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "edx_sitemap":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- SEC EDGAR handler path -----------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_type", "") == "sec_edgar":
        items = handler.fetch(limit=limit)
        return [handler.to_item(item) for item in items]

    # -- Semantic Scholar handler path --------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_name", "") == "semantic_scholar":
        query = topic if topic else ""
        papers = handler.fetch(query, limit=limit)
        return [handler.to_item(p) for p in papers]

    # -- USPTO handler path --------------------------------------------------
    if hasattr(handler, "fetch") and getattr(handler, "source_name", "") == "uspto":
        query = topic if topic else ""
        patents = handler.fetch(query, limit=limit)
        return [handler.to_item(p) for p in patents]

    # -- RSS / Web handler path --------------------------------------------
    if hasattr(handler, "fetch"):
        url = source_config.url
        if not url:
            plog.warning(
                "RSS source has no URL configured",
                source_type=source_config.type,
                extra={"source_name": source_config.name},
            )
            return []
        items = handler.fetch(url)
        # Apply limit
        return items[:limit]

    raise TypeError(f"Handler for '{source_config.name}' has no usable fetch method")


def _cache_items(
    items: list[Item],
    domain: str,
    source_name: str,
) -> None:
    """Write deduplicated items to ``collections/<domain>/<source>/<date>/<id>.json``."""
    today = date.today().isoformat()
    base_dir = Path("collections") / domain / source_name / today
    base_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        safe_id = str(item.id).replace("/", "_") if item.id else item.id
        file_path = base_dir / f"{safe_id}.json"
        # Avoid overwriting existing cached files (idempotent)
        if file_path.exists():
            continue
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(item.to_dict(), fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Webhook push
# ---------------------------------------------------------------------------


def _build_webhook_payload(domain: str, item: Item) -> dict[str, Any]:
    """Build the JSON payload for a webhook POST."""
    import uuid as _uuid

    return {
        "item_id": item.id or str(_uuid.uuid4()),
        "trace_id": item.trace_id,
        "title": item.title,
        "url": item.source_url,
        "source": item.source_name,
        "source_type": item.source_type,
        "domain": domain,
        "topic": item.topic_tags,
        "content": item.content,
        "collected_at": item.collected_at,
        "extracted": {
            "summary": item.raw_data.get("summary", ""),
            "key_points": item.raw_data.get("key_points", []),
            "entities": item.raw_data.get("entities", []),
        },
    }


async def _post_webhook(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    retries: int = 3,
) -> None:
    """POST *payload* to *url* with exponential backoff retry.

    Retries on 5xx and network errors only.  2xx and 4xx are terminal.
    """
    for attempt in range(retries):
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code < 500:
                return  # 2xx or 4xx — terminal
            await asyncio.sleep(2**attempt)  # 2s, 4s, 8s
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == retries - 1:
                plog.error(
                    "Webhook failed after retries",
                    extra={"retries": retries, "url": url},
                )
            await asyncio.sleep(2**attempt)


async def _fire_webhooks(
    domain: str,
    new_items: list[Item],
    webhook_urls: list[str],
) -> None:
    """Fire-and-forget webhook POST for each new item.

    All items are sent to all configured webhooks concurrently.
    Exceptions are logged and never propagated.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks: list[asyncio.Task[None]] = []
        for item in new_items:
            payload = _build_webhook_payload(domain, item)
            for url in webhook_urls:
                tasks.append(asyncio.create_task(_post_webhook(client, url, payload)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _fire_webhooks_sync(
    domain: str,
    new_items: list[Item],
    webhook_urls: list[str],
) -> None:
    """Synchronous fire-and-forget entry point.

    Runs the async webhook fire in a daemon thread so collection is
    never blocked even when called from an already-running event loop.
    """
    if not webhook_urls or not new_items:
        return

    def _run() -> None:
        try:
            asyncio.run(_fire_webhooks(domain, new_items, webhook_urls))
        except Exception:
            logger.exception("Webhook fire failed for domain '%s'", domain)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _log_run(
    domain: str,
    source_name: str,
    collection_id: str,
    items_found: int,
    items_new: int,
    status: str = "success",
    errors: list[dict[str, Any]] | None = None,
    duration_s: float = 0.0,
    trace_ids: list[str] | None = None,
    items_filtered: int = 0,
) -> None:
    """Append a run entry to ``collections/<domain>/<source>/_runs.json``.

    Parameters
    ----------
    status:
        Run outcome: ``"success"``, ``"error"``, or ``"skipped"``.
    errors:
        Optional list of error dicts (only meaningful when status != success).
    duration_s:
        Wall-clock duration of the collection run in seconds.
    """
    runs_dir = Path("collections") / domain / source_name
    runs_dir.mkdir(parents=True, exist_ok=True)
    runs_path = runs_dir / "_runs.json"

    entry: dict[str, Any] = {
        "collection_id": collection_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "items_found": items_found,
        "items_new": items_new,
        "items_filtered": items_filtered,
        "errors": errors or [],
        "duration_ms": round(duration_s * 1000, 1),
    }
    if trace_ids:
        entry["trace_ids"] = trace_ids

    if runs_path.exists():
        try:
            with open(runs_path, "r", encoding="utf-8") as fh:
                runs: list[dict[str, Any]] = json.load(fh)
        except (json.JSONDecodeError, FileNotFoundError):
            runs = []
    else:
        runs = []

    runs.append(entry)

    with open(runs_path, "w", encoding="utf-8") as fh:
        json.dump(runs, fh, ensure_ascii=False, indent=2)


def list_active_collections() -> list[dict[str, Any]]:
    """Return a list of active/in-progress collection runs.

    Reads the latest runs from ``collections/_runs.json`` and returns
    any that do not have a terminal status (``completed``, ``failed``).
    Falls back to returning the 5 most recent runs if no active run
    is found.
    """
    runs_path = Path("collections") / "_runs.json"
    if not runs_path.is_file():
        return []

    try:
        with open(runs_path, "r", encoding="utf-8") as fh:
            runs: list[dict[str, Any]] = json.load(fh)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

    terminal_statuses = frozenset({"completed", "failed", "cancelled"})
    active = [r for r in runs if r.get("status", "") not in terminal_statuses]
    if active:
        return sorted(active, key=lambda x: x.get("timestamp", ""), reverse=True)

    # No active runs — return the 5 most recent for visibility
    recent = sorted(runs, key=lambda x: x.get("timestamp", ""), reverse=True)
    return recent[:5]
